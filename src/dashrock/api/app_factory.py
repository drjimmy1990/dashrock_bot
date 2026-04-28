"""FastAPI application factory."""
from __future__ import annotations
import logging
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dashrock.api.deps import EngineState
from dashrock.api.routes.trading import create_routes
from dashrock.api.ws import create_ws_router

log = logging.getLogger(__name__)

def create_api(state: EngineState, auth_enabled: bool = True) -> FastAPI:
    app = FastAPI(title="Dashrock Bot API", version="2.0.0")
    # Read allowed CORS origins from env (comma-separated), default to local dev
    cors_raw = os.environ.get("CORS_ORIGINS", "http://localhost:5173")
    allowed_origins = [o.strip() for o in cors_raw.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware, allow_origins=allowed_origins, allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )
    app.include_router(create_routes(state, auth_enabled=auth_enabled))
    app.include_router(create_ws_router(auth_enabled=auth_enabled))
    return app
