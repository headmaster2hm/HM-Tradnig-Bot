"""HM Bridge — drive a desktop MetaTrader 5 from the hosted bot.

Architecture
------------
- ``bridge_agent.py`` (Windows, next to MT5) opens a secure outbound
  WebSocket to the bot's dashboard and authenticates with a shared token.
- The dashboard exposes ``/bridge/ws``; ``bridge.ws`` speaks raw WebSocket
  frames, ``bridge.manager`` runs the RPC + telemetry state.
- ``bridge.remote_mt5`` is a drop-in replacement for ``MetaTrader5`` that
  the bot's MT5 client uses when the bridge is enabled.
"""

from __future__ import annotations

from bridge.manager import BridgeError, get_manager
from bridge.remote_mt5 import RemoteMT5

__all__ = ["BridgeError", "get_manager", "RemoteMT5"]
