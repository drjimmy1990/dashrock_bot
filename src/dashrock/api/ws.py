"""WebSocket connection manager — broadcasts events to dashboard clients."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from dashrock.api.auth import verify_token

log = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections with auth and dead-connection cleanup."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        log.debug("WS client connected (%d total)", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        log.debug("WS client disconnected (%d total)", len(self.active_connections))

    async def broadcast_json(self, data: dict[str, Any]) -> None:
        """Send JSON to all connected clients. Auto-remove dead connections."""
        dead: list[WebSocket] = []
        for ws in self.active_connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def client_count(self) -> int:
        return len(self.active_connections)


# Module-level singleton
ws_manager = ConnectionManager()


def create_ws_router(auth_enabled: bool = True) -> APIRouter:
    """Create WebSocket router with optional auth."""
    router = APIRouter()

    @router.websocket("/ws")
    async def websocket_endpoint(
        websocket: WebSocket,
        token: str = Query(default=""),
    ) -> None:
        # MUST accept() first — closing before accept causes silent failures
        await websocket.accept()

        # Auth check via query param
        if auth_enabled:
            if not token:
                await websocket.close(code=4001, reason="Token required")
                return
            try:
                verify_token(token)
            except Exception:
                await websocket.close(code=4001, reason="Unauthorized")
                return

        ws_manager.active_connections.append(websocket)
        log.debug("WS client connected (%d total)", len(ws_manager.active_connections))
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            ws_manager.disconnect(websocket)

    return router
