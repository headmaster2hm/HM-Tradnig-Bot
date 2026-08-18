"""Bridge connection manager: auth, request/response RPC, telemetry cache.

The desktop agent connects to ``/bridge/ws`` and authenticates on the first
frame with ``{"type": "auth", "token": ...}``. After that it:

- answers RPC calls  ``{"id": N, "result": ...}`` / ``{"id": N, "error": ...}``
- pushes telemetry   ``{"type": "telemetry", "data": {...}}`` every second

Multiple agents may be attached simultaneously — each identified by its
MT5 account login (extracted from the first telemetry push).  RPC calls
are routed to the agent matching the requested ``account`` parameter.
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


class _AgentState:
    """Tracks one connected bridge agent."""

    __slots__ = ("conn", "agent_key", "login", "telemetry", "last_telemetry_at", "attached_since", "version")

    def __init__(self, conn: _Connection, agent_key: str) -> None:
        self.conn = conn
        self.agent_key = agent_key
        self.login: str | None = None
        self.telemetry: dict[str, Any] = {}
        self.last_telemetry_at: float | None = None
        self.attached_since: float = time.time()
        self.version: str = ""


class BridgeManager:
    def __init__(self) -> None:
        self._agents: dict[str, _AgentState] = {}
        self._conn_to_key: dict[int, str] = {}
        self._next_temp = 0
        self._next_id = 0
        self._pending: dict[int, tuple[threading.Event, dict[str, Any]]] = {}
        self._send_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self.on_telemetry: Callable[[dict[str, Any]], None] | None = None
        self._last_log = 0.0
        self._latest_agent_version: str = ""
        self._update_url: str = ""
        self._update_sha256: str = ""
        self._updated_agents: set[str] = set()

    # -- transport -------------------------------------------------------
    def attach(self, conn: _Connection) -> bool:
        with self._state_lock:
            key = f"_temp_{self._next_temp}"
            self._next_temp += 1
            agent = _AgentState(conn, key)
            self._agents[key] = agent
            self._conn_to_key[id(conn)] = key
        logger.info("bridge agent attached (pending identification)")
        return True

    def _identify_agent(self, login: str, conn: _Connection) -> None:
        """Promote a pending agent to an identified login key."""
        with self._state_lock:
            old_key = self._conn_to_key.get(id(conn))
            if old_key is None:
                return
            # Already identified as this login — nothing to do
            if old_key == login:
                return
            agent = self._agents.pop(old_key, None)
            if agent is None:
                return
            del self._conn_to_key[id(conn)]
            agent.login = login
            agent.agent_key = login
            if login in self._agents:
                old = self._agents[login]
                logger.info("bridge: replacing previous agent for login %s", login)
                old.conn.closed = True
            self._agents[login] = agent
            self._conn_to_key[id(conn)] = login
            logger.info("bridge: agent identified as login %s", login)

    def detach(self, conn: _Connection) -> None:
        with self._state_lock:
            key = self._conn_to_key.pop(id(conn), None)
            if key is not None:
                agent = self._agents.get(key)
                # Only remove the agent if THIS connection is still the active one.
                # If a newer connection has already replaced it, leave it alone.
                if agent is not None and agent.conn is conn:
                    self._agents.pop(key, None)
                    if agent.login:
                        logger.info("bridge: agent %s detached", agent.login)
                    else:
                        logger.info("bridge: unidentified agent detached")
                elif agent is not None:
                    logger.debug("bridge: ignoring detach for superseded connection")
                else:
                    logger.info("bridge: unidentified agent detached")
            else:
                logger.info("bridge: agent detached")
        with self._pending_lock:
            for _event, holder in self._pending.values():
                holder["error"] = "bridge disconnected"
            self._pending.clear()

    @property
    def connected(self) -> bool:
        with self._state_lock:
            for agent in self._agents.values():
                if not agent.conn.closed:
                    return True
            return False

    def _get_agent(self, account: str | None = None) -> _AgentState | None:
        with self._state_lock:
            if account:
                agent = self._agents.get(str(account))
                if agent and not agent.conn.closed:
                    return agent
                return None
            # Default: first identified (non-temp) agent
            for key, agent in self._agents.items():
                if not key.startswith("_temp_") and not agent.conn.closed:
                    return agent
            # Fall back to first pending agent
            for agent in self._agents.values():
                if not agent.conn.closed:
                    return agent
            logger.warning("bridge _get_agent: agents=%s", {k: (v.login, v.conn.closed) for k, v in self._agents.items()})
            return None

    def _send_to(self, payload: dict[str, Any], conn: _Connection) -> None:
        if conn.closed:
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
        return self.connected

    # -- RPC -------------------------------------------------------------
    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = CALL_TIMEOUT,
        account: str | None = None,
    ) -> Any:
        agent = self._get_agent(account)
        if agent is None:
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
            self._send_to({"id": msg_id, "method": method, "params": params or {}}, agent.conn)
            logger.debug("bridge: sent %s (id=%d) to %s", method, msg_id, agent.login or agent.agent_key)
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

    def _on_message(self, payload: dict[str, Any], conn: _Connection | None = None) -> None:
        if "id" in payload:
            msg_id = payload.get("id")
            if not isinstance(msg_id, int):
                return
            with self._pending_lock:
                entry = self._pending.pop(msg_id, None)
            if entry is None:
                logger.debug("bridge: response for unknown msg_id %s", msg_id)
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
                # Identify agent from telemetry login
                if conn is not None:
                    account = extract_account(data)
                    login = str(account.get("login") or "").strip()
                    if login and login != "SIM" and login.isdigit():
                        self._identify_agent(login, conn)
                # Update per-agent telemetry
                with self._state_lock:
                    if conn is not None:
                        key = self._conn_to_key.get(id(conn))
                        if key and key in self._agents:
                            agent = self._agents[key]
                            agent.telemetry = data
                            agent.last_telemetry_at = time.time()
                            version = str(data.get("version") or "").strip()
                            if version:
                                agent.version = version
                            # Push update if version is outdated
                            if (
                                version
                                and self._latest_agent_version
                                and version != self._latest_agent_version
                                and self._update_url
                                and key not in self._updated_agents
                            ):
                                self._updated_agents.add(key)
                                threading.Thread(
                                    target=self._push_update,
                                    args=(conn, agent.login or key),
                                    daemon=True,
                                    name="push-update",
                                ).start()
                if self.on_telemetry is not None:
                    try:
                        self.on_telemetry(data)
                    except Exception:  # noqa: BLE001
                        logger.exception("bridge on_telemetry hook failed")
            return
        logger.debug("bridge: unhandled message %r", payload)

    # -- cached telemetry ------------------------------------------------
    def telemetry(self, account: str | None = None) -> dict[str, Any]:
        agent = self._get_agent(account)
        if agent is None:
            return {}
        with self._state_lock:
            return dict(agent.telemetry)

    def bridge_status(self) -> dict[str, Any]:
        with self._state_lock:
            agents_info = []
            for key, agent in self._agents.items():
                acct = extract_account(agent.telemetry)
                agents_info.append({
                    "connected": not agent.conn.closed,
                    "login": acct.get("login") or agent.login,
                    "server": acct.get("server"),
                    "name": acct.get("name"),
                    "balance": acct.get("balance"),
                    "currency": acct.get("currency"),
                    "version": agent.version,
                    "since": agent.attached_since,
                    "last_telemetry_at": agent.last_telemetry_at,
                })
        if not agents_info:
            return {
                "connected": False,
                "since": None,
                "last_telemetry_at": None,
                "login": None,
                "server": None,
                "name": None,
                "balance": None,
                "currency": None,
            }
        # Backward compat: return first identified agent
        primary = next(
            (a for a in agents_info if a.get("login")), agents_info[0]
        )
        result = {**primary, "agents": agents_info}
        return result

    def set_update_info(self, version: str, url: str, sha256: str = "") -> None:
        self._latest_agent_version = version
        self._update_url = url
        self._update_sha256 = sha256
        self._updated_agents.clear()
        logger.info("bridge: update info set — latest version %s", version)

    def _push_update(self, conn: _Connection, login: str) -> None:
        with self._pending_lock:
            self._next_id += 1
            msg_id = self._next_id
        try:
            self._send_to({
                "id": msg_id,
                "method": "agent.update",
                "params": {"url": self._update_url, "sha256": self._update_sha256},
            }, conn)
            logger.info("bridge: pushed update to agent %s", login)
        except BridgeError:
            pass

    def _throttled_log(self, fmt: str, *args: Any) -> None:
        now = time.time()
        if now - self._last_log > 30:
            self._last_log = now
            logger.warning(fmt, *args)


def resolve_bridge_token() -> str:
    return os.environ.get(ENV_BRIDGE_TOKEN, "").strip()


def extract_account(telemetry: dict[str, Any]) -> dict[str, Any]:
    """Best-effort account dict from a telemetry payload.

    Current agents send ``{"account": {...}}`` but early builds sent the raw
    MT5 ``AccountInfo`` as a single-element list, or positionally as a list of
    scalars. Only the stable anchors of the positional form are decoded:
    ``login`` is always first, ``balance`` sits at index 10, and the four
    trailing string fields are always ``name``/``server``/``currency``/``company``.
    """
    account = telemetry.get("account")
    if isinstance(account, dict):
        return account
    if isinstance(account, (list, tuple)):
        for item in account:
            if isinstance(item, dict):
                return item
        values = list(account)
        if len(values) >= 14 and all(
            not isinstance(item, (list, tuple, dict)) for item in values
        ):
            return {
                "login": values[0],
                "balance": values[10],
                "equity": values[13],
                "margin": values[14],
                "margin_free": values[15],
                "name": values[-4],
                "server": values[-3],
                "currency": values[-2],
                "company": values[-1],
            }
    return {}


_bridge_manager: BridgeManager | None = None


def get_manager() -> BridgeManager:
    global _bridge_manager
    if _bridge_manager is None:
        _bridge_manager = BridgeManager()
    return _bridge_manager
