"""End-to-end test for the HM Bridge: dashboard WS endpoint + RemoteMT5 proxy.

A simulated desktop agent connects over WebSocket, authenticates, answers
RPC calls with canned data, and pushes telemetry — exactly like the real
``bridge_agent.py`` running next to MetaTrader 5 on Windows.
"""

from __future__ import annotations

import json
import os
import threading
import time

os.environ["HM_BRIDGE_TOKEN"] = "test-token-123"

import numpy as np
import pandas as pd
import pytest
import websocket  # type: ignore[import-untyped]

from bridge.manager import get_manager
from bridge.remote_mt5 import RemoteMT5

TOKEN = "test-token-123"


def _account() -> dict:
    return {
        "login": 50014,
        "server": "DemoBroker",
        "name": "Test Account",
        "balance": 12345.67,
        "equity": 12500.0,
        "profit": 154.33,
        "currency": "USD",
    }


def _rates(count: int) -> list[dict]:
    base = 2800.0
    rows = []
    for i in range(count):
        close = base + i * 0.5
        rows.append(
            {
                "time": 1_700_000_000 + i * 60,
                "open": close - 0.2,
                "high": close + 0.5,
                "low": close - 0.7,
                "close": close,
                "tick_volume": 120,
                "spread": 2,
                "real_volume": 0,
            }
        )
    return rows


class FakeAgent:
    def __init__(self, url: str) -> None:
        self.ws = websocket.create_connection(url, timeout=10, max_size=4 * 1024 * 1024)
        self.ws.send(json.dumps({"type": "auth", "token": TOKEN}))
        welcome = json.loads(self.ws.recv())
        assert welcome.get("type") == "auth_ok", welcome
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        self.commands: list[str] = []

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                raw = self.ws.recv()
            except Exception:  # noqa: BLE001
                return
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            msg_id = msg.get("id")
            method = str(msg.get("method") or "").split(".", 1)[-1]
            if msg_id is None or not method:
                continue
            self.commands.append(method)
            reply = {"id": msg_id, "result": self._answer(method, msg.get("params") or {})}
            self.ws.send(json.dumps(reply))

    def _answer(self, method: str, params: dict) -> object:
        if method == "initialize":
            return True
        if method == "account_info":
            return _account()
        if method == "terminal_info":
            return {"trade_allowed": True}
        if method == "symbol_info":
            return {
                "visible": True,
                "filling_mode": 2,
                "volume_min": 0.01,
                "volume_step": 0.01,
                "point": 0.01,
                "digits": 2,
                "trade_stops_level": 0,
                "spread": 2,
                "trade_mode": 4,
            }
        if method == "symbol_select":
            return True
        if method == "symbol_info_tick":
            return {"bid": 2800.5, "ask": 2800.7}
        if method == "copy_rates_from_pos":
            return _rates(int(params.get("count", 100)))
        if method == "positions_get":
            return [{"ticket": 111, "type": 0, "volume": 0.2, "price_open": 2800.0, "sl": 0.0, "tp": 0.0, "profit": 5.0, "time": 1_700_000_100, "magic": 50014}]
        if method == "order_send":
            return {"retcode": 10009, "order": 999, "price": 2800.5, "comment": "done"}
        if method == "history_deals_get":
            return [{"position_id": 111, "entry": 1, "profit": 5.0, "swap": 0.0, "commission": -0.2, "price": 2800.9}]
        return None

    def close(self) -> None:
        self._stop.set()
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass

    def send_telemetry(self, data: dict) -> None:
        self.ws.send(json.dumps({"type": "telemetry", "data": data}))


@pytest.fixture()
def bridge_server():
    from http.server import ThreadingHTTPServer

    from config import load_config
    from dashboard.webapp import Engine, make_handler

    config = load_config()
    engine = Engine(config)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(engine))
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, port
    server.shutdown()
    server.server_close()
    engine.executor.stop()


def _wait_bridge(manager) -> bool:
    for _ in range(50):
        if manager.connected:
            return True
        time.sleep(0.1)
    return False


def test_ws_handshake_and_auth(bridge_server):
    _server, port = bridge_server
    ws = websocket.create_connection(f"ws://127.0.0.1:{port}/bridge/ws", timeout=5)
    ws.send(json.dumps({"type": "auth", "token": "wrong-token"}))
    reply = json.loads(ws.recv())
    assert reply.get("type") == "error"
    ws.close()


def test_bridge_rpc_roundtrip(bridge_server):
    _server, port = bridge_server
    agent = FakeAgent(f"ws://127.0.0.1:{port}/bridge/ws")
    try:
        manager = get_manager()
        assert _wait_bridge(manager)

        mt5 = RemoteMT5()
        assert mt5.initialize() is True
        assert mt5.last_error() == (0, "")

        acct = mt5.account_info()
        assert acct.login == 50014 and float(acct.balance) == 12345.67

        term = mt5.terminal_info()
        assert term.trade_allowed is True

        info = mt5.symbol_info("Crash 500 Index")
        assert float(info.volume_step) == 0.01 and int(info.digits) == 2

        tick = mt5.symbol_info_tick("Crash 500 Index")
        assert float(tick.bid) == 2800.5

        rates = mt5.copy_rates_from_pos("Crash 500 Index", 1, 0, 5)
        assert rates is not None and len(rates) == 5
        frame = pd.DataFrame(rates)
        assert {"open", "high", "low", "close", "tick_volume"} <= set(frame.columns)
        assert frame.iloc[-1]["close"] > 0

        positions = mt5.positions_get("Crash 500 Index")
        assert len(positions) == 1 and int(positions[0].ticket) == 111

        result = mt5.order_send({"action": 1, "symbol": "Crash 500 Index"})
        assert result.retcode == 10009 and int(result.order) == 999

        deals = mt5.history_deals_get(0, 2_000_000_000)
        assert len(deals) == 1 and float(deals[0].profit) == 5.0

        assert "copy_rates_from_pos" in agent.commands
        assert "order_send" in agent.commands
    finally:
        agent.close()


def test_bridge_down_fails_fast(bridge_server):
    _server, port = bridge_server
    manager = get_manager()
    for _ in range(50):  # wait for any earlier test connection to detach
        if not manager.connected:
            break
        time.sleep(0.1)
    assert not manager.connected
    mt5 = RemoteMT5()
    assert mt5.initialize() is False
    assert mt5.terminal_info() is None
    assert mt5.account_info() is None


def test_bridge_telemetry_and_status(bridge_server):
    _server, port = bridge_server
    manager = get_manager()
    original = manager.on_telemetry
    manager.on_telemetry = None  # keep the test out of the real admin DB
    try:
        agent = FakeAgent(f"ws://127.0.0.1:{port}/bridge/ws")
        try:
            assert _wait_bridge(manager)
            agent.send_telemetry({"account": _account()})
            for _ in range(50):
                if manager.bridge_status().get("login") == 50014:
                    break
                time.sleep(0.1)
            status = manager.bridge_status()
            assert status["connected"] is True
            assert status["login"] == 50014
            assert status["server"] == "DemoBroker"
            assert status["name"] == "Test Account"
            assert manager.telemetry()["account"]["login"] == 50014
        finally:
            agent.close()
    finally:
        manager.on_telemetry = original


def test_make_handler_wires_telemetry_hook(bridge_server):
    from dashboard import webapp

    assert get_manager().on_telemetry is webapp._register_connected_account


def test_register_connected_account_writes_user(tmp_path, monkeypatch):
    from database.admin_db import AdminDatabase
    from dashboard import webapp

    db = AdminDatabase(tmp_path / "control.db")
    monkeypatch.setattr(webapp, "_get_admin_db", lambda: db)
    webapp._connected_account_seen["login"] = ""
    webapp._connected_account_seen["ts"] = 0.0

    webapp._register_connected_account({"account": {"login": 60001, "server": "DemoBroker"}})
    user = db.get_user_by_account("60001")
    assert user is not None
    assert user["status"] == "active"
    assert user["last_seen_at"] is not None

    webapp._register_connected_account({"account": {}})
    webapp._register_connected_account({"account": {"login": "SIM"}})
    webapp._register_connected_account({"account": {"login": "not-a-number"}})
    assert len(db.list_users()) == 1
