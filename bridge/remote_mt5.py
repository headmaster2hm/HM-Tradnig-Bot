"""A drop-in replacement for the ``MetaTrader5`` module, driven over the bridge.

The bot's ``MT5Client`` calls ``self._mt5.<method>(...)`` and reads results as
namedtuple-like attributes. :class:`RemoteMT5` mirrors exactly that surface,
translating each call into an RPC to the desktop agent and reconstructing
lightweight objects (``SimpleNamespace`` / numpy structured arrays) so the
rest of the codebase is untouched.

Constants match the real module's documented values.
"""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from typing import Any

import numpy as np

from bridge.manager import BridgeError, get_manager

logger = logging.getLogger("bridge.mt5")

# --- MT5 constants (documented numeric values) --------------------------
TIMEFRAME_M1 = 1
TIMEFRAME_M5 = 5
TIMEFRAME_M15 = 15
TIMEFRAME_M30 = 30
TIMEFRAME_H1 = 60
TIMEFRAME_H4 = 240
TIMEFRAME_D1 = 1440

ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
ORDER_TYPE_BUY_LIMIT = 2
ORDER_TYPE_SELL_LIMIT = 3
ORDER_TYPE_BUY_STOP = 4
ORDER_TYPE_SELL_STOP = 5
ORDER_TYPE_BUY_STOP_LIMIT = 6
ORDER_TYPE_SELL_STOP_LIMIT = 7
ORDER_TYPE_CLOSE_BY = 8

POSITION_TYPE_BUY = 0
POSITION_TYPE_SELL = 1

TRADE_ACTION_DEAL = 1
TRADE_ACTION_PENDING = 2
TRADE_ACTION_SLTP = 3
TRADE_ACTION_MODIFY = 4
TRADE_ACTION_REMOVE = 5
TRADE_ACTION_CLOSE_BY = 6

TRADE_RETCODE_DONE = 10009

ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_RETURN = 2

ORDER_TIME_GTC = 0
ORDER_TIME_DAY = 1
ORDER_TIME_SPECIFIED = 2
ORDER_TIME_SPECIFIED_DAY = 3

_RATES_DTYPE = np.dtype(
    [
        ("time", "<i8"),
        ("open", "<f8"),
        ("high", "<f8"),
        ("low", "<f8"),
        ("close", "<f8"),
        ("tick_volume", "<i8"),
        ("spread", "<i4"),
        ("real_volume", "<i8"),
    ]
)


def _obj(data: dict[str, Any] | None) -> SimpleNamespace | None:
    return SimpleNamespace(**data) if isinstance(data, dict) else None


def _obj_list(rows: list[dict[str, Any]] | None) -> tuple[SimpleNamespace, ...]:
    if not rows:
        return ()
    return tuple(SimpleNamespace(**row) for row in rows)


def _rates_frame(rows: list[dict[str, Any]] | None) -> np.ndarray | None:
    if not rows:
        return None
    frame = np.zeros(len(rows), dtype=_RATES_DTYPE)
    for i, row in enumerate(rows):
        frame[i] = (
            int(row.get("time", 0)),
            float(row.get("open", 0.0)),
            float(row.get("high", 0.0)),
            float(row.get("low", 0.0)),
            float(row.get("close", 0.0)),
            int(row.get("tick_volume", 0)),
            int(row.get("spread", 0)),
            int(row.get("real_volume", 0)),
        )
    return frame


class RemoteMT5:
    """Proxy with the same API surface the bot uses from ``MetaTrader5``."""

    def __init__(self, target_account: str | None = None) -> None:
        self._manager = get_manager()
        self._target_account = target_account
        self._connected = False
        self._last_error: tuple[int, str] = (0, "")
        self._log_throttle = 0.0
        self.TIMEFRAME_M1 = TIMEFRAME_M1
        self.TIMEFRAME_M5 = TIMEFRAME_M5
        self.TIMEFRAME_M15 = TIMEFRAME_M15
        self.TIMEFRAME_M30 = TIMEFRAME_M30
        self.TIMEFRAME_H1 = TIMEFRAME_H1
        self.TIMEFRAME_H4 = TIMEFRAME_H4
        self.TIMEFRAME_D1 = TIMEFRAME_D1
        self.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        self.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        self.POSITION_TYPE_BUY = POSITION_TYPE_BUY
        self.TRADE_ACTION_DEAL = TRADE_ACTION_DEAL
        self.TRADE_RETCODE_DONE = TRADE_RETCODE_DONE
        self.ORDER_FILLING_FOK = ORDER_FILLING_FOK
        self.ORDER_FILLING_IOC = ORDER_FILLING_IOC
        self.ORDER_FILLING_RETURN = ORDER_FILLING_RETURN
        self.ORDER_TIME_GTC = ORDER_TIME_GTC

    # -- helpers ---------------------------------------------------------
    def _call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 8.0) -> Any:
        try:
            result = self._manager.call(
                f"mt5.{method}", params, timeout=timeout, account=self._target_account
            )
        except BridgeError as exc:
            self._last_error = (-1, str(exc))
            now = time.time()
            if now - self._log_throttle > 30:
                self._log_throttle = now
                logger.warning("bridge %s failed: %s", method, exc)
            raise
        return result

    def _call_soft(self, method: str, params: dict[str, Any] | None = None, timeout: float = 8.0) -> Any:
        try:
            return self._call(method, params, timeout)
        except BridgeError:
            return None

    # -- module API ------------------------------------------------------
    def initialize(self, **kwargs: Any) -> bool:
        try:
            result = self._call("initialize", kwargs or {}, timeout=15.0)
            self._connected = bool(result)
            self._last_error = (0, "" if result else "initialize failed")
            return self._connected
        except BridgeError:
            self._connected = False
            return False

    def shutdown(self) -> bool:
        self._call_soft("shutdown", timeout=5.0)
        self._connected = False
        return True

    def last_error(self) -> tuple[int, str]:
        return self._last_error

    def terminal_info(self) -> SimpleNamespace | None:
        if not self._connected:
            return None
        return _obj(self._call_soft("terminal_info", timeout=5.0))

    def account_info(self) -> SimpleNamespace | None:
        if not self._connected:
            return None
        return _obj(self._call_soft("account_info", timeout=6.0))

    def symbol_info(self, name: str) -> SimpleNamespace | None:
        return _obj(self._call_soft("symbol_info", {"symbol": name}, timeout=6.0))

    def symbol_select(self, name: str, enable: bool = True) -> bool:
        return bool(self._call_soft("symbol_select", {"symbol": name, "enable": bool(enable)}, timeout=6.0))

    def symbol_info_tick(self, name: str) -> SimpleNamespace | None:
        return _obj(self._call_soft("symbol_info_tick", {"symbol": name}, timeout=5.0))

    def copy_rates_from_pos(self, symbol: str, timeframe: int, start: int, count: int) -> np.ndarray | None:
        rows = self._call_soft(
            "copy_rates_from_pos",
            {"symbol": symbol, "timeframe": timeframe, "start": int(start), "count": int(count)},
            timeout=10.0,
        )
        return _rates_frame(rows)

    def copy_rates_range(self, symbol: str, timeframe: int, start: Any, stop: Any) -> np.ndarray | None:
        rows = self._call_soft(
            "copy_rates_range",
            {"symbol": symbol, "timeframe": timeframe, "start": int(start), "stop": int(stop)},
            timeout=10.0,
        )
        return _rates_frame(rows)

    def positions_get(self, symbol: str | None = None) -> tuple[SimpleNamespace, ...]:
        rows = self._call_soft("positions_get", {"symbol": symbol or ""}, timeout=6.0)
        return _obj_list(rows)

    def orders_get(self, symbol: str | None = None) -> tuple[SimpleNamespace, ...]:
        rows = self._call_soft("orders_get", {"symbol": symbol or ""}, timeout=6.0)
        return _obj_list(rows)

    def order_send(self, request: dict[str, Any]) -> SimpleNamespace | None:
        result = self._call_soft("order_send", {"request": request}, timeout=20.0)
        return _obj(result)

    def position_modify(self, ticket: int, sl: float, tp: float) -> SimpleNamespace | None:
        result = self._call_soft("position_modify", {"ticket": ticket, "sl": sl, "tp": tp}, timeout=10.0)
        return _obj(result)

    def history_deals_get(self, date_from: Any, date_to: Any) -> tuple[SimpleNamespace, ...]:
        start = int(date_from.timestamp()) if hasattr(date_from, "timestamp") else int(date_from)
        stop = int(date_to.timestamp()) if hasattr(date_to, "timestamp") else int(date_to)
        rows = self._call_soft("history_deals_get", {"date_from": start, "date_to": stop}, timeout=8.0)
        return _obj_list(rows)
