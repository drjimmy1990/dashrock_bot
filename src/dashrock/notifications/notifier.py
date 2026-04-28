"""Notification system — Telegram + Discord alerts."""
from __future__ import annotations
import logging
import httpx
from dashrock.config import NotificationsCfg

log = logging.getLogger(__name__)

class Notifier:
    def __init__(self, cfg: NotificationsCfg) -> None:
        self.cfg = cfg
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10)
        return self._client

    async def send(self, event_type: str, message: str) -> None:
        if event_type not in self.cfg.events:
            return
        if self.cfg.telegram_bot_token and self.cfg.telegram_chat_id:
            await self._send_telegram(message)
        if self.cfg.discord_webhook:
            await self._send_discord(message)

    async def _send_telegram(self, message: str) -> None:
        url = f"https://api.telegram.org/bot{self.cfg.telegram_bot_token}/sendMessage"
        try:
            resp = await self._get_client().post(url, json={
                "chat_id": self.cfg.telegram_chat_id, "text": message, "parse_mode": "HTML",
            })
            if resp.status_code != 200:
                log.warning("Telegram failed: %s", resp.text)
        except Exception:
            log.exception("Telegram error")

    async def _send_discord(self, message: str) -> None:
        try:
            resp = await self._get_client().post(self.cfg.discord_webhook, json={"content": message})
            if resp.status_code not in (200, 204):
                log.warning("Discord failed: %s", resp.text)
        except Exception:
            log.exception("Discord error")

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
