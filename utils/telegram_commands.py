"""Optional Telegram remote commands (/status /pause /resume /closeall)."""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

from utils.logger import get_logger

if TYPE_CHECKING:
    from execution.trade_executor import TradeExecutor

logger = get_logger("telegram")


class TelegramCommander:
    def __init__(self, executor: TradeExecutor, token: str, chat_id: str) -> None:
        self.executor = executor
        self.token = token
        self.chat_id = str(chat_id)
        self._offset = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if not self.token or not self.chat_id:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _api(self, method: str, **params):
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        data = urllib.parse.urlencode(params).encode()
        with urllib.request.urlopen(url, data=data, timeout=25) as resp:  # noqa: S310
            return json.loads(resp.read().decode())

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                payload = self._api(
                    "getUpdates",
                    offset=self._offset,
                    timeout=20,
                )
                for update in payload.get("result", []):
                    self._offset = update["update_id"] + 1
                    message = update.get("message") or {}
                    if str(message.get("chat", {}).get("id")) != self.chat_id:
                        continue
                    text = (message.get("text") or "").strip().lower()
                    reply = self._handle(text)
                    if reply:
                        self._api("sendMessage", chat_id=self.chat_id, text=reply)
            except Exception:  # noqa: BLE001
                logger.exception("Telegram poll error")
                time.sleep(3)

    def _handle(self, text: str) -> str:
        if text.startswith("/status"):
            snap = self.executor.tick()
            return (
                f"Status: {snap.status}\n"
                f"Signal: {snap.signal.signal.value if snap.signal else '—'}\n"
                f"RSI: {snap.rsi}\n"
                f"Open: {len(snap.positions)}\n"
                f"Today: {snap.day_profit:.2f}"
            )
        if text.startswith("/pause"):
            self.executor.pause()
            return "Paused"
        if text.startswith("/resume"):
            self.executor.resume()
            return "Resumed"
        if text.startswith("/closeall"):
            self.executor.close_all("Telegram /closeall")
            return "Closed all"
        return "Commands: /status /pause /resume /closeall"
