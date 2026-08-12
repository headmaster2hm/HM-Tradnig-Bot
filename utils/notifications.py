"""Desktop + optional Telegram notifications."""

from __future__ import annotations

from typing import Callable

from config import TelegramConfig
from utils.logger import get_logger

logger = get_logger("notifications")


class NotificationHub:
    def __init__(self, telegram: TelegramConfig, enabled: bool = True) -> None:
        self.enabled = enabled
        self.telegram = telegram
        self._listeners: list[Callable[[str, str], None]] = []

    def subscribe(self, callback: Callable[[str, str], None]) -> None:
        self._listeners.append(callback)

    def notify(self, title: str, message: str) -> None:
        if not self.enabled:
            return
        logger.info("%s — %s", title, message)
        for callback in self._listeners:
            try:
                callback(title, message)
            except Exception:  # noqa: BLE001
                logger.exception("Notification listener failed")
        self._send_telegram(f"*{title}*\n{message}")

    def _send_telegram(self, text: str) -> None:
        if not self.telegram.enabled:
            return
        import os

        from config.secrets import ENV_TELEGRAM_TOKEN

        token = (os.environ.get(ENV_TELEGRAM_TOKEN) or self.telegram.bot_token or "").strip()
        if not token:
            return
        try:
            import urllib.parse
            import urllib.request

            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = urllib.parse.urlencode(
                {
                    "chat_id": self.telegram.chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                }
            ).encode()
            urllib.request.urlopen(url, data=payload, timeout=5)  # noqa: S310
        except Exception:  # noqa: BLE001
            logger.exception("Telegram notification failed")
