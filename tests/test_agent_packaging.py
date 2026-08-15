"""Unit checks for the Windows bridge agent packaging modules.

These only exercise the code paths that run on any OS — the Windows-only
registry/GUI logic is guarded and skipped on Linux.
"""

from __future__ import annotations

import json

import bridge_defaults
import mt5_detect
from bridge_agent import BridgeAgent


def test_bridge_defaults_are_sane():
    assert bridge_defaults.DEFAULT_URL.startswith("wss://")
    assert len(bridge_defaults.DEFAULT_TOKEN) >= 16
    assert bridge_defaults.APP_ID == "HMBotBridgeAgent"


def test_mt5_detect_is_graceful_off_windows():
    assert isinstance(mt5_detect.detect_terminals(), list)
    assert isinstance(mt5_detect.detect_primary(), str)


def test_agent_state_tracking():
    agent = BridgeAgent("wss://example.test/bridge/ws", "tok", {})
    assert agent.connected is False
    assert agent.status_text == "idle"
    agent.status_text = "connecting"
    agent.stop()
    assert agent.status_text == "stopped"
    assert agent._stop.is_set()


def test_agent_prefix_stripping():
    agent = BridgeAgent("wss://example.test/bridge/ws", "tok", {})

    calls: list[str] = []

    def fake_dispatch(method: str, params: dict):
        calls.append(method)
        return True

    agent._dispatch = fake_dispatch
    reply = agent._handle_request({"id": 7, "method": "mt5.initialize", "params": {}})
    assert reply == {"id": 7, "result": True}
    assert calls == ["initialize"]


def test_agent_dispatch_error_reply():
    agent = BridgeAgent("wss://example.test/bridge/ws", "tok", {})

    def boom(method: str, params: dict):
        raise RuntimeError("nope")

    agent._dispatch = boom
    reply = agent._handle_request({"id": 3, "method": "mt5.terminal_info", "params": {}})
    assert reply["id"] == 3 and "nope" in reply["error"]
    assert agent._handle_request({"type": "telemetry"}) is None
