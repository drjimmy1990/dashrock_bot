"""Async PostgreSQL database connection using asyncpg + SQLAlchemy.

Designed for Supabase (managed PostgreSQL) with connection pooling.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from dashrock.config import DatabaseCfg
from dashrock.persistence.models import Base

log = logging.getLogger(__name__)


class Database:
    """Async PostgreSQL database with connection pooling."""

    def __init__(self, cfg: DatabaseCfg) -> None:
        # Prefer DATABASE_URL from environment, fall back to config
        url = os.environ.get("DATABASE_URL", cfg.url)
        if not url:
            raise RuntimeError(
                "DATABASE_URL must be set in .env or config.yaml database.url"
            )

        # Convert postgresql:// to postgresql+asyncpg:// for async driver
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

        self._engine = create_async_engine(
            url,
            pool_size=cfg.pool_min,
            max_overflow=cfg.pool_max - cfg.pool_min,
            pool_pre_ping=True,  # verify connections are alive
            echo=False,
            # Supabase uses PgBouncer — disable prepared statement caching
            connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def connect(self) -> None:
        """Test the connection and create tables if needed."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info("Database connected and tables verified")

    async def close(self) -> None:
        """Close all connections."""
        await self._engine.dispose()
        log.info("Database connections closed")

    def session(self) -> AsyncSession:
        """Create a new async session."""
        return self._session_factory()

    async def is_connected(self) -> bool:
        """Health check — can we reach the database?"""
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
