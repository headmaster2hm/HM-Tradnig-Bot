"""MetaTrader 5 connection wrapper with reconnect + dry-run fallback."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from config import AppConfig
from utils.logger import get_logger

logger = get_logger("mt5")

TIMEFRAME_MAP = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}

# MT5 SYMBOL_TRADE_MODE_* values (constants not always exported by the Python package)
_TRADE_MODE_DISABLED = 0
_TRADE_MODE_LONGONLY = 1
_TRADE_MODE_SHORTONLY = 2
_TRADE_MODE_CLOSEONLY = 3
_TRADE_MODE_FULL = 4


class MT5Client:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.connected = False
        self._mt5: Any = None
        self._demo_price = 2800.0
        self._demo_rng = np.random.default_rng(42)
        self._paper_positions: list[dict[str, Any]] = []
        self._paper_ticket = 100000
        self.last_error: str = ""
        self.using_simulated_feed: bool = False

    def _set_error(self, message: str) -> None:
        self.last_error = message
        logger.error(message)

    def _clear_error(self) -> None:
        self.last_error = ""

    def _symbol_info(self) -> Any | None:
        if not self.ensure_connected() or self._mt5 is None:
            return None
        info = self._mt5.symbol_info(self.config.symbol)
        if info is None:
            return None
        if not info.visible:
            if not self._mt5.symbol_select(self.config.symbol, True):
                return None
            info = self._mt5.symbol_info(self.config.symbol)
        return info

    def _order_filling_mode(self, info: Any) -> int:
        """Pick a filling mode the symbol allows.

        MetaTrader5 Python does not always expose SYMBOL_FILLING_* constants,
        so we use the documented bit flags: FOK=1, IOC=2.
        """
        assert self._mt5 is not None
        mode = int(getattr(info, "filling_mode", 0) or 0)
        if mode & 2:  # IOC  
            return self._mt5.ORDER_FILLING_IOC
        if mode & 1:  # FOK
            return self._mt5.ORDER_FILLING_FOK
        return self._mt5.ORDER_FILLING_RETURN

    def _normalize_volume(self, volume: float, info: Any) -> float:
        step = float(info.volume_step) or 0.01
        minimum = float(info.volume_min) or step
        maximum = float(info.volume_max) or volume
        lots = max(minimum, round(volume / step) * step)
        return min(lots, maximum)

    def _normalize_price(self, price: float, info: Any) -> float:
        digits = int(getattr(info, "digits", 5) or 5)
        return round(float(price), digits)

    def symbol_point(self) -> float:
        """Broker point size for the configured symbol (fallback for dry-run)."""
        info = self._symbol_info()
        if info is not None:
            point = float(getattr(info, "point", 0.0) or 0.0)
            if point > 0:
                return point
        # Sensible offline fallbacks
        if "USD" in self.config.symbol.upper() and "CRASH" not in self.config.symbol.upper():
            return 0.00001
        return 0.01

    def _format_order_error(self, result: Any | None) -> str:
        if self._mt5 is None:
            return "MT5 not connected"
        if result is None:
            err = self._mt5.last_error()
            return f"order_send returned None ({err})"
        return f"retcode {result.retcode}: {result.comment}"

    def _trade_mode_allows(self, trade_mode: int, side: str | None = None) -> bool:
        if trade_mode == _TRADE_MODE_DISABLED or trade_mode == _TRADE_MODE_CLOSEONLY:
            return False
        if side is None:
            return trade_mode in (
                _TRADE_MODE_FULL,
                _TRADE_MODE_LONGONLY,
                _TRADE_MODE_SHORTONLY,
            )
        if trade_mode == _TRADE_MODE_FULL:
            return True
        if trade_mode == _TRADE_MODE_LONGONLY:
            return side == "BUY"
        if trade_mode == _TRADE_MODE_SHORTONLY:
            return side == "SELL"
        return False

    def symbol_status(self, side: str | None = None) -> dict[str, Any]:
        info = self._symbol_info()
        if info is None:
            return {
                "available": False,
                "trade_allowed": False,
                "message": (
                    f"Symbol '{self.config.symbol}' not found in MT5. "
                    "Add it in Market Watch or change symbol in Settings."
                ),
            }
        trade_mode = int(getattr(info, "trade_mode", _TRADE_MODE_DISABLED))
        trade_allowed = self._trade_mode_allows(trade_mode, side)
        message = "OK"
        if not trade_allowed:
            if trade_mode == _TRADE_MODE_CLOSEONLY:
                message = f"'{self.config.symbol}' is close-only on this account"
            elif trade_mode == _TRADE_MODE_DISABLED:
                message = f"Trading disabled for '{self.config.symbol}' on this account"
            elif side == "BUY" and trade_mode == _TRADE_MODE_SHORTONLY:
                message = f"'{self.config.symbol}' allows SELL only"
            elif side == "SELL" and trade_mode == _TRADE_MODE_LONGONLY:
                message = f"'{self.config.symbol}' allows BUY only"
            else:
                message = f"Trading not allowed for '{self.config.symbol}' (mode={trade_mode})"
        return {
            "available": True,
            "trade_allowed": trade_allowed,
            "trade_mode": trade_mode,
            "message": message,
            "volume_min": float(info.volume_min),
            "volume_step": float(info.volume_step),
            "point": float(info.point),
            "digits": int(info.digits),
            "stops_level": int(getattr(info, "trade_stops_level", 0) or 0),
        }

    def algo_trading_enabled(self) -> bool:
        if not self.ensure_connected() or self._mt5 is None:
            return False
        terminal = self._mt5.terminal_info()
        if terminal is None:
            return False
        return bool(getattr(terminal, "trade_allowed", False))

    def has_live_tick(self) -> bool:
        if not self.ensure_connected() or self._mt5 is None:
            return False
        self._symbol_info()
        tick = self._mt5.symbol_info_tick(self.config.symbol)
        if tick is None:
            return False
        return float(tick.bid) > 0 and float(tick.ask) > 0

    def live_readiness(self) -> list[str]:
        """Return blocking issues for live trading (empty list = ready)."""
        issues: list[str] = []
        if self.config.dry_run:
            return issues

        if self.config.stop_loss_points <= 0:
            issues.append("Stop loss (points) must be > 0 before live trading")

        if not self.ensure_connected() or self._mt5 is None:
            issues.append("MT5 is not connected — open MetaTrader 5 and log in")
            return issues

        if not self.algo_trading_enabled():
            issues.append("Algo Trading is OFF in MT5 — click Algo Trading until it turns green")

        self.copy_rates(10)
        if self.using_simulated_feed:
            issues.append(
                f"No live candles for '{self.config.symbol}' — "
                "add the symbol in Market Watch or change symbol in Settings"
            )

        status = self.symbol_status()
        if not status["available"]:
            issues.append(status["message"])
        elif not status["trade_allowed"]:
            issues.append(status["message"])

        if not self.has_live_tick():
            issues.append(
                f"No live bid/ask tick for '{self.config.symbol}' — "
                "symbol may be closed or unavailable on this broker"
            )

        return issues

    def connect(self) -> bool:
        try:
            if getattr(self.config, "mt5_bridge", None) and self.config.mt5_bridge.enabled:
                from bridge.remote_mt5 import RemoteMT5

                target = str(self.config.mt5.login) if self.config.mt5.login else None
                mt5: Any = RemoteMT5(target_account=target)
                self._mt5 = mt5
                logger.info("Using remote MT5 bridge (%s)", self.config.mt5_bridge.url)
            else:
                import MetaTrader5 as mt5

                self._mt5 = mt5

            kwargs: dict[str, Any] = {}
            if self.config.mt5.path:
                kwargs["path"] = self.config.mt5.path
            if self.config.mt5.login:
                from config.secrets import resolve_mt5_password

                kwargs["login"] = self.config.mt5.login
                kwargs["password"] = resolve_mt5_password(self.config)
                kwargs["server"] = self.config.mt5.server
                if not kwargs["password"]:
                    logger.warning(
                        "MT5 login set but no password (settings/env). "
                        "Prefer logging into MT5 first and leave login=0."
                    )

            if not mt5.initialize(**kwargs):
                logger.error("MT5 initialize failed: %s", mt5.last_error())
                self.connected = False
                return False

            self.connected = True
            info = mt5.account_info()
            if info:
                logger.info(
                    "Connected to MT5 — %s | %s | balance %.2f",
                    info.login,
                    info.server,
                    info.balance,
                )
            return True
        except ImportError:
            logger.warning("MetaTrader5 package not available — using simulation feed")
            self.connected = False
            return False
        except Exception:  # noqa: BLE001
            logger.exception("MT5 connection error")
            self.connected = False
            return False

    def ensure_connected(self) -> bool:
        if self.connected and self._mt5 is not None:
            try:
                if self._mt5.terminal_info() is not None:
                    return True
            except Exception:  # noqa: BLE001
                logger.warning("MT5 connection lost — reconnecting")
                self.connected = False
        return self.connect()

    def shutdown(self) -> None:
        if self._mt5 is not None and self.connected:
            self._mt5.shutdown()
        self.connected = False

    def account_info(self) -> dict[str, Any]:
        if self.ensure_connected() and self._mt5 is not None:
            info = self._mt5.account_info()
            if info:
                return {
                    "login": info.login,
                    "server": info.server,
                    "name": info.name,
                    "balance": float(info.balance),
                    "equity": float(info.equity),
                    "profit": float(info.profit),
                    "currency": info.currency,
                }
        floating = sum(p.get("profit", 0.0) for p in self._paper_positions)
        return {
            "login": "SIM",
            "server": "DemoFeed",
            "name": "Paper Account",
            "balance": 10_000.0 + floating,
            "equity": 10_000.0 + floating,
            "profit": floating,
            "currency": "USD",
        }

    def _timeframe(self) -> Any:
        assert self._mt5 is not None
        key = self.config.timeframe.upper()
        mapping = {
            "M1": self._mt5.TIMEFRAME_M1,
            "M5": self._mt5.TIMEFRAME_M5,
            "M15": self._mt5.TIMEFRAME_M15,
            "M30": self._mt5.TIMEFRAME_M30,
            "H1": self._mt5.TIMEFRAME_H1,
            "H4": self._mt5.TIMEFRAME_H4,
            "D1": self._mt5.TIMEFRAME_D1,
        }
        return mapping.get(key, self._mt5.TIMEFRAME_M1)

    def copy_rates(self, count: int | None = None) -> pd.DataFrame:
        bars = count or self.config.candle_count
        if self.ensure_connected() and self._mt5 is not None:
            self._symbol_info()
            rates = self._mt5.copy_rates_from_pos(
                self.config.symbol, self._timeframe(), 0, bars
            )
            if rates is not None and len(rates) > 0:
                self.using_simulated_feed = False
                frame = pd.DataFrame(rates)
                frame["time"] = pd.to_datetime(frame["time"], unit="s")
                frame = frame.set_index("time")
                return frame[["open", "high", "low", "close", "tick_volume"]]

        self.using_simulated_feed = True
        return self._simulate_rates(bars)

    def _simulate_rates(self, bars: int) -> pd.DataFrame:
        """Synthetic Crash-like series for dry-run / offline demo."""
        now = pd.Timestamp.utcnow().floor("min")
        index = pd.date_range(end=now, periods=bars, freq="min")
        returns = self._demo_rng.normal(0.00015, 0.0012, size=bars)
        crash_hits = self._demo_rng.random(bars) < 0.015
        returns[crash_hits] = -abs(self._demo_rng.normal(0.012, 0.004, size=crash_hits.sum()))
        close = self._demo_price * np.cumprod(1.0 + returns)
        self._demo_price = float(close[-1])
        open_ = np.roll(close, 1)
        open_[0] = close[0]
        high = np.maximum(open_, close) * (1.0 + self._demo_rng.uniform(0, 0.0008, bars))
        low = np.minimum(open_, close) * (1.0 - self._demo_rng.uniform(0, 0.0008, bars))
        volume = self._demo_rng.integers(50, 400, size=bars)
        return pd.DataFrame(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "tick_volume": volume,
            },
            index=index,
        )

    def symbol_spread_points(self) -> float:
        if self.ensure_connected() and self._mt5 is not None:
            info = self._mt5.symbol_info(self.config.symbol)
            if info is not None:
                return float(info.spread)
        return 20.0

    def symbol_tick(self, *, allow_simulated: bool = True) -> dict[str, float] | None:
        if self.ensure_connected() and self._mt5 is not None:
            tick = self._mt5.symbol_info_tick(self.config.symbol)
            if tick is not None and float(tick.bid) > 0 and float(tick.ask) > 0:
                return {"bid": float(tick.bid), "ask": float(tick.ask)}
            if not allow_simulated or not self.config.dry_run:
                return None
        if not allow_simulated:
            return None
        mid = self._demo_price
        return {"bid": mid, "ask": mid + 0.2}

    def positions(self, magic: int | None = None) -> list[dict[str, Any]]:
        magic = magic if magic is not None else self.config.magic_number
        if self.ensure_connected() and self._mt5 is not None and not self.config.dry_run:
            raw = self._mt5.positions_get(symbol=self.config.symbol)
            if raw is None:
                return []
            result = []
            for pos in raw:
                if pos.magic != magic:
                    continue
                result.append(
                    {
                        "ticket": pos.ticket,
                        "type": "BUY" if pos.type == self._mt5.POSITION_TYPE_BUY else "SELL",
                        "volume": float(pos.volume),
                        "price_open": float(pos.price_open),
                        "sl": float(pos.sl),
                        "tp": float(pos.tp),
                        "profit": float(pos.profit),
                        "time": datetime.fromtimestamp(pos.time).isoformat(timespec="seconds"),
                    }
                )
            return result

        tick = self.symbol_tick(allow_simulated=True) or {"bid": self._demo_price, "ask": self._demo_price}
        for pos in self._paper_positions:
            if pos["type"] == "BUY":
                pos["profit"] = (tick["bid"] - pos["price_open"]) * pos["volume"] * 100
            else:
                pos["profit"] = (pos["price_open"] - tick["ask"]) * pos["volume"] * 100
        return list(self._paper_positions)

    def open_market(
        self,
        side: str,
        volume: float,
        sl: float = 0.0,
        tp: float = 0.0,
    ) -> dict[str, Any] | None:
        self._clear_error()

        # Paper path — only when dry_run is explicitly on
        if self.config.dry_run:
            tick = self.symbol_tick(allow_simulated=True)
            if tick is None:
                self._set_error("No price available for dry-run order")
                return None
            price = tick["ask"] if side == "BUY" else tick["bid"]
            self._paper_ticket += 1
            pos = {
                "ticket": self._paper_ticket,
                "type": side,
                "volume": volume,
                "price_open": price,
                "sl": sl,
                "tp": tp,
                "profit": 0.0,
                "time": datetime.utcnow().isoformat(timespec="seconds"),
            }
            self._paper_positions.append(pos)
            logger.info("DRY-RUN %s opened @ %.5f lot=%.2f", side, price, volume)
            return pos

        # Live path — never fall back to paper
        if not self.ensure_connected() or self._mt5 is None:
            self._set_error("MT5 not connected — live orders blocked (no paper fallback)")
            return None

        if not self.algo_trading_enabled():
            self._set_error("Algo Trading is OFF in MT5 — live orders blocked")
            return None

        if self.using_simulated_feed:
            self._set_error(
                f"No live price data for '{self.config.symbol}'. "
                "Simulated candles cannot be used for live orders."
            )
            return None

        status = self.symbol_status(side=side)
        if not status["available"] or not status["trade_allowed"]:
            self._set_error(status["message"])
            return None

        tick = self.symbol_tick(allow_simulated=False)
        if tick is None:
            self._set_error(f"No live tick for '{self.config.symbol}' — order blocked")
            return None
        price = tick["ask"] if side == "BUY" else tick["bid"]

        info = self._symbol_info()
        if info is None:
            self._set_error(f"Could not load symbol info for '{self.config.symbol}'")
            return None

        if self.config.stop_loss_points <= 0 or sl <= 0:
            self._set_error("Live orders require a stop loss — set Stop loss (points) > 0")
            return None

        try:
            volume = self._normalize_volume(volume, info)
            price = self._normalize_price(price, info)
            sl = self._normalize_price(sl, info) if sl > 0 else 0.0
            tp = self._normalize_price(tp, info) if tp > 0 else 0.0
            order_type = self._mt5.ORDER_TYPE_BUY if side == "BUY" else self._mt5.ORDER_TYPE_SELL
            request = {
                "action": self._mt5.TRADE_ACTION_DEAL,
                "symbol": self.config.symbol,
                "volume": float(volume),
                "type": order_type,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": self.config.slippage,
                "magic": self.config.magic_number,
                "comment": self.config.comment,
                "type_time": self._mt5.ORDER_TIME_GTC,
                "type_filling": self._order_filling_mode(info),
            }
            result = self._mt5.order_send(request)
        except Exception as exc:  # noqa: BLE001
            self._set_error(f"Order exception: {exc}")
            return None

        if result is None or result.retcode != self._mt5.TRADE_RETCODE_DONE:
            self._set_error(f"Order failed: {self._format_order_error(result)}")
            return None
        return {
            "ticket": result.order,
            "type": side,
            "volume": volume,
            "price_open": float(result.price),
            "sl": sl,
            "tp": tp,
            "profit": 0.0,
            "time": datetime.utcnow().isoformat(timespec="seconds"),
        }

    def close_position(self, ticket: int) -> dict[str, Any] | None:
        self._clear_error()
        positions = self.positions()
        match = next((p for p in positions if p["ticket"] == ticket), None)
        if match is None:
            return None

        profit = float(match.get("profit", 0.0))

        if self.config.dry_run:
            tick = self.symbol_tick(allow_simulated=True) or {
                "bid": match["price_open"],
                "ask": match["price_open"],
            }
            price = tick["bid"] if match["type"] == "BUY" else tick["ask"]
            self._paper_positions = [p for p in self._paper_positions if p["ticket"] != ticket]
            logger.info("DRY-RUN closed ticket %s @ %.5f profit=%.2f", ticket, price, profit)
            return {"ticket": ticket, "price": price, "profit": profit}

        if not self.ensure_connected() or self._mt5 is None:
            self._set_error("MT5 not connected — cannot close live position")
            return None

        tick = self.symbol_tick(allow_simulated=False)
        if tick is None:
            self._set_error(f"No live tick for '{self.config.symbol}' — close blocked")
            return None
        price = tick["bid"] if match["type"] == "BUY" else tick["ask"]

        order_type = (
            self._mt5.ORDER_TYPE_SELL
            if match["type"] == "BUY"
            else self._mt5.ORDER_TYPE_BUY
        )
        info = self._symbol_info()
        if info is None:
            self._set_error(f"Could not load symbol info for '{self.config.symbol}'")
            return None

        request = {
            "action": self._mt5.TRADE_ACTION_DEAL,
            "symbol": self.config.symbol,
            "volume": float(match["volume"]),
            "type": order_type,
            "position": ticket,
            "price": self._normalize_price(price, info),
                 "deviation": self.config.slippage,
            "magic": self.config.magic_number,
            "comment": f"{self.config.comment}-close",
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": self._order_filling_mode(info),
        }
        result = self._mt5.order_send(request)
        if result is None or result.retcode != self._mt5.TRADE_RETCODE_DONE:
            self._set_error(f"Close failed: {self._format_order_error(result)}")
            return None
        return {"ticket": ticket, "price": float(result.price), "profit": profit}

    def close_all(self) -> list[dict[str, Any]]:
        closed = []
        for pos in list(self.positions()):
            result = self.close_position(pos["ticket"])
            if result:
                closed.append(result)
        return closed

    def deal_close_info(self, position_ticket: int) -> dict[str, Any] | None:
        """Look up broker deal history for a position that left the Trade tab."""
        if not self.ensure_connected() or self._mt5 is None:
            return None
        from datetime import timedelta

        now = datetime.now()
        start = now - timedelta(days=7)
        deals = self._mt5.history_deals_get(start, now)
        if deals is None:
            return None

        profit = 0.0
        exit_price = 0.0
        found = False
        for deal in deals:
            if int(getattr(deal, "position_id", 0) or 0) != int(position_ticket):
                continue
            # entry: 0=in, 1=out, 2=inout, 3=out_by
            entry = int(getattr(deal, "entry", -1))
            if entry in (1, 2, 3):
                found = True
                profit += float(deal.profit) + float(getattr(deal, "swap", 0) or 0) + float(
                    getattr(deal, "commission", 0) or 0
                )
                exit_price = float(deal.price)
        if not found:
            return None
        return {"ticket": position_ticket, "price": exit_price, "profit": profit}
