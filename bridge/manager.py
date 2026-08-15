"""Bridge connection manager: auth, request/response RPC, telemetry cache.

The desktop agent connects to ``/bridge/ws`` and authenticates on the first
frame with ``{"type": "auth", "token": ...}``. After that it:

- answers RPC calls  ``{"id": N, "result": ...}`` / ``{"id": N, "error": ...}``
- pushes telemetry   ``{"type": "telemetry", "data": {...}}`` every second

Only one agent may be attached at a time. Calls fail fast when the agent is
not connected, so the bot's polling loop never stalls on a dead bridge.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Callable

logger = logging.getLogger("bridge")

ENV_BRIDGE_TOKEN = "HM_BRIDGE_TOKEN"

CALL_TIMEOUT = 8.0
_EPOCH = time.time()  # "now" reference so id counters stay small


class BridgeError(Exception):
    pass


class _Connection:
    """Thin wrapper over the WebSocket transport used by the manager."""

    def __init__(self, send_text: Callable[[str], None]) -> None:
        self.send_text = send_text
        self.closed = False


class BridgeManager:
    def __init__(self) -> None:
        self._conn: _Connection | None = None
        self._next_id = 0
        self._pending: dict[int, tuple[threading.Event, dict[str, Any]]] = {}
        self._send_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._telemetry: dict[str, Any] = {}
        self._last_log = 0.0

    # -- transport -------------------------------------------------------
    def attach(self, conn: _Connection) -> bool:
        with self._state_lock:
            if self._conn is not None:
                return False
            self._conn = conn
        logger.info("bridge agent attached")
        return True

    def detach(self, conn: _Connection) -> None:
        with self._state_lock:
            if self._conn is conn:
                self._conn = None
        with self._pending_lock:
            for _event, holder in self._pending.values():
                holder["error"] = "bridge disconnected"
            self._pending.clear()
        logger.info("bridge agent detached")

    @property
    def connected(self) -> bool:
        with self._state_lock:
            return self._conn is not None and not self._conn.closed

    def _send(self, payload: dict[str, Any]) -> None:
        conn = self._conn
        if conn is None or conn.closed:
            raise BridgeError("bridge not connected")
        text = json.dumps(payload)
        with self._send_lock:
            try:
                conn.send_text(text)
            except OSError:
                conn.closed = True
                raise BridgeError("bridge socket closed")

    def _reject_new(self) -> bool:
        """Another connection is active — don't replace it silently."""
        with self._state_lock:
            return self._conn is not None and not self._conn.closed

    # -- RPC -------------------------------------------------------------
    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = CALL_TIMEOUT) -> Any:
        if not self.connected:
            self._throttled_log("bridge down — call %s failed fast", method)
            raise BridgeError("bridge not connected")
        with self._pending_lock:
            self._next_id += 1
            msg_id = self._next_id
        event = threading.Event()
        holder: dict[str, Any] = {}
        with self._pending_lock:
            self._pending[msg_id] = (event, holder)
        try:
            self._send({"id": msg_id, "method": method, "params": params or {}})
        except BridgeError:
            with self._pending_lock:
                self._pending.pop(msg_id, None)
            raise
        if not event.wait(timeout):
            with self._pending_lock:
                self._pending.pop(msg_id, None)
            self._throttled_log("bridge call %s timed out", method)
            raise BridgeError(f"bridge call '{method}' timed out")
        if holder.get("error"):
            raise BridgeError(f"bridge '{method}' error: {holder['error']}")
        return holder.get("result")

    def _on_message(self, payload: dict[str, Any]) -> None:
        if "id" in payload:
            msg_id = payload.get("id")
            if not isinstance(msg_id, int):
                return
            with self._pending_lock:
                entry = self._pending.pop(msg_id, None)
            if entry is None:
                return
            event, holder = entry
            if "error" in payload:
                holder["error"] = payload["error"]
            else:
                holder["result"] = payload.get("result")
            event.set()
            return
        if payload.get("type") == "telemetry":
            data = payload.get("data")
            if isinstance(data, dict):
                with self._state_lock:
                    self._telemetry = data
            return
        logger.debug("bridge: unhandled message %r", payload)

    # -- cached telemetry ------------------------------------------------
    def telemetry(self) -> dict[str, Any]:
        with self._state_lock:
            return dict(self._telemetry)

    def _throttled_log(self, fmt: str, *args: Any) -> None:
        now = time.time()
        if now - self._last_log > 30:
            self._last_log = now
            logger.warning(fmt, *args)


def resolve_bridge_token() -> str:
    return os.environ.get(ENV_BRIDGE_TOKEN, "").strip()


_bridge_manager: BridgeManager | None = None


def get_manager() -> BridgeManager:
    global _bridge_manager
    if _bridge_manager is None:
        _bridge_manager = BridgeManager()
    return _bridge_manager
