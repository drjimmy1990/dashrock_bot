"""JWT authentication module.

Uses bcrypt directly (passlib is abandoned and incompatible with bcrypt>=4.1).
"""

from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

log = logging.getLogger(__name__)

_security = HTTPBearer()

# Loaded from env
_JWT_SECRET = ""
_JWT_ALGORITHM = "HS256"
_TOKEN_EXPIRY_HOURS = 24
_ADMIN_USERNAME = ""
_ADMIN_PASSWORD_HASH = b""


def _hash_password(password: str) -> bytes:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())


def _verify_password(password: str, hashed: bytes) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), hashed)


def configure_auth(
    jwt_secret: str, token_expiry_hours: int,
    admin_username: str, admin_password: str,
) -> None:
    """Set auth config from env/config at startup.

    Raises RuntimeError if critical secrets are not configured.
    """
    global _JWT_SECRET, _TOKEN_EXPIRY_HOURS, _ADMIN_USERNAME, _ADMIN_PASSWORD_HASH
    _JWT_SECRET = jwt_secret or os.environ.get("JWT_SECRET", "")
    if not _JWT_SECRET or _JWT_SECRET == "change-me-to-a-random-string":
        raise RuntimeError(
            "JWT_SECRET is not set or is still the default placeholder. "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
        )
    _TOKEN_EXPIRY_HOURS = token_expiry_hours
    _ADMIN_USERNAME = admin_username or os.environ.get("ADMIN_USERNAME", "")
    if not _ADMIN_USERNAME:
        raise RuntimeError("ADMIN_USERNAME is not set.")
    raw_password = admin_password or os.environ.get("ADMIN_PASSWORD", "")
    if not raw_password or raw_password in ("change-me", "admin"):
        raise RuntimeError(
            "ADMIN_PASSWORD is not set or is still a default placeholder. "
            "Set a strong password (16+ chars) in your .env file."
        )
    _ADMIN_PASSWORD_HASH = _hash_password(raw_password)
    log.info("Auth configured for user: %s", _ADMIN_USERNAME)


def authenticate(username: str, password: str) -> str | None:
    """Verify credentials, return JWT token or None."""
    if username != _ADMIN_USERNAME:
        return None
    if not _verify_password(password, _ADMIN_PASSWORD_HASH):
        return None
    return _create_token(username)


def _create_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=_TOKEN_EXPIRY_HOURS)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def verify_token(token: str) -> str:
    """Verify a JWT and return the username. Raises on invalid."""
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        username: str = payload.get("sub", "")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Token expired or invalid")


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> str:
    """FastAPI dependency — require valid Bearer token."""
    return verify_token(credentials.credentials)
