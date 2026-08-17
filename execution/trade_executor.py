"""Order orchestration: signals → risk → MT5 / paper."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

import pandas as pd

from config import AppConfig
from database import TradeDatabase
from execution.mt5_client import MT5Client
from execution.risk_manager import RiskManager
from strategy import RsiEmaStrategy, SignalType, TradeSignal, create_strategy
from utils.logger import get_logger
from utils.notifications import NotificationHub

logger = get_logger("executor")


@dataclass
class BotSnapshot:
    status: str
    connected: bool
    dry_run: bool
    account: dict[str, Any]
    signal: TradeSignal | None
    rsi: float | None
    ema48: float | None
    ema50: float | None
    confidence: float
    positions: list[dict[str, Any]]
    candles: pd.DataFrame | None
    indicators: pd.DataFrame | None
    day_profit: float
    win_rate: float
    logs: list[str] = field(default_factory=list)
    risk_reason: str = ""
    markers: list[dict[str, Any]] = field(default_factory=list)


class TradeExecutor:
    def __init__(
        self,
        config: AppConfig,
        notify: NotificationHub | None = None,
    ) -> None:
        self.config = config
        self.client = MT5Client(config)
        self.risk = RiskManager(config)
        self.db = TradeDatabase()
        self.strategy = create_strategy(RsiEmaStrategy.name, config)
        self.notify = notify or NotificationHub(config.telegram, config.enable_notifications)
        self.status = "IDLE"
        self.paused = False
        self._last_bar_time: pd.Timestamp | None = None
        self._acted_entry_bar: pd.Timestamp | None = None
        self._entry_backoff_until: datetime | None = None
        self._log_buffer: list[str] = []
        self._markers: list[dict[str, Any]] = []
        self._listeners: list[Callable[[str], None]] = []

    def subscribe_log(self, callback: Callable[[str], None]) -> None:
        self._listeners.append(callback)

    def _log(self, message: str) -> None:
        logger.info(message)
        self._log_buffer.append(message)
        self._log_buffer = self._log_buffer[-200:]
        for callback in self._listeners:
            callback(message)

    def live_blockers(self) -> list[str]:
        """Issues that must be cleared before LIVE start (empty = OK)."""
        return self.client.live_readiness()

    def start(self) -> bool:
        mode = "DRY-RUN" if self.config.dry_run else "LIVE"

        if self.config.dry_run:
            self.client.connect()
        else:
            if not self.client.connect():
                self._log("LIVE start blocked: MT5 connection failed")
                self.status = "IDLE"
                return False
            blockers = self.live_blockers()
            if blockers:
                for issue in blockers:
                    self._log(f"LIVE start blocked: {issue}")
                self.status = "IDLE"
                return False

        self.status = "RUNNING"
        self.paused = False
        self._acted_entry_bar = None
        self._entry_backoff_until = None
        self._log(f"Bot started ({mode})")
        self.notify.notify("Bot Started", f"Mode: {mode} | Symbol: {self.config.symbol}")
        return True

    def stop(self) -> None:
        self.status = "STOPPED"
        self._log("Bot stopped")
        self.notify.notify("Bot Stopped", "Trading loop halted")

    def pause(self) -> None:
        self.paused = True
        self.status = "PAUSED"
        self._log("Bot paused")

    def resume(self) -> None:
        self.paused = False
        self.status = "RUNNING"
        self._log("Bot resumed")

    def close_all(self, reason: str = "Manual close") -> None:
        for result in self.client.close_all():
            self._record_close(result, reason)

    def _record_close(
        self,
        result: dict[str, Any],
        reason: str,
        *,
        from_halt_flatten: bool = False,
    ) -> None:
        self.db.close_trade(
            ticket=result["ticket"],
            exit_price=result["price"],
            profit=result["profit"],
            reason_closed=reason,
        )
        just_halted = self.risk.register_close(result["profit"])
        self._markers.append(
            {
                "kind": "exit",
                "price": result["price"],
                "side": "FLAT",
                "time": pd.Timestamp.utcnow(),
            }
        )
        self._log(f"Closed ticket {result['ticket']} ({reason}) P/L={result['profit']:.2f}")
        self.notify.notify("Trade Closed", f"Ticket {result['ticket']} | {result['profit']:.2f}")
        if just_halted and not from_halt_flatten:
            self._log(f"Daily halt: {self.risk.halt_reason} — flattening remaining positions")
            for pos in list(self.client.positions()):
                closed = self.client.close_position(pos["ticket"])
                if closed:
                    self._record_close(
                        closed,
                        self.risk.halt_reason,
                        from_halt_flatten=True,
                    )

    def _reconcile_broker_closes(self, positions: list[dict[str, Any]]) -> None:
        """Detect positions closed by SL/TP/manual in MT5 and sync DB + day P/L."""
        if self.config.dry_run:
            return
        live_tickets = {int(p["ticket"]) for p in positions}
        for ticket in self.db.open_tickets(dry_run=False):
            if ticket in live_tickets:
                continue
            info = self.client.deal_close_info(ticket)
            if info is None:
                # Still mark closed so we don't loop forever; profit unknown
                self.db.close_trade(
                    ticket=ticket,
                    exit_price=0.0,
                    profit=0.0,
                    reason_closed="Broker close (details unavailable)",
                )
                self._log(f"Reconciled missing ticket {ticket} (no deal details)")
                continue
            self._record_close(info, "Broker SL/TP or manual close")

    def _sl_tp_prices(self, side: str, entry: float) -> tuple[float, float]:
        point = self.client.symbol_point()
        status = self.client.symbol_status()
        stops_level = int(status.get("stops_level", 0) or 0)
        sl_points = float(self.config.stop_loss_points)
        tp_points = float(self.config.take_profit_points)

        if stops_level > 0:
            if sl_points > 0:
                sl_points = max(sl_points, float(stops_level))
            if tp_points > 0:
                tp_points = max(tp_points, float(stops_level))

        sl = tp = 0.0
        if sl_points > 0:
            sl = (
                entry - sl_points * point
                if side == "BUY"
                else entry + sl_points * point
            )
        if tp_points > 0:
            tp = (
                entry + tp_points * point
                if side == "BUY"
                else entry - tp_points * point
            )
        return sl, tp

    def _has_side(self, side: str) -> bool:
        return any(p["type"] == side for p in self.client.positions())

    def _update_trailing_stops(self, positions: list[dict[str, Any]]) -> None:
        """Move SL to lock in profit when position is ahead by trailing_stop_points."""
        trail = self.config.trailing_stop_points
        if trail <= 0:
            return
        point = self.client.symbol_point()
        if point <= 0:
            return
        tick = self.client.symbol_tick(allow_simulated=self.config.dry_run)
        if tick is None:
            return
        for pos in positions:
            side = pos["type"]
            entry = pos["price_open"]
            ticket = pos["ticket"]
            current_sl = pos.get("sl", 0.0)
            if side == "BUY":
                current_price = tick["bid"]
                profit_pts = (current_price - entry) / point
                if profit_pts >= trail:
                    new_sl = entry + (profit_pts - trail) * point
                    if new_sl > current_sl or current_sl <= 0:
                        self.client.modify_position(ticket, new_sl, pos.get("tp", 0.0))
                        self._log(f"Trailing SL BUY #{ticket}: {current_sl:.5f} → {new_sl:.5f}")
            elif side == "SELL":
                current_price = tick["ask"]
                profit_pts = (entry - current_price) / point
                if profit_pts >= trail:
                    new_sl = entry - (profit_pts - trail) * point
                    if new_sl < current_sl or current_sl <= 0:
                        self.client.modify_position(ticket, new_sl, pos.get("tp", 0.0))
                        self._log(f"Trailing SL SELL #{ticket}: {current_sl:.5f} → {new_sl:.5f}")

    def tick(self) -> BotSnapshot:
        candles = self.client.copy_rates()
        indicators = self.strategy.prepare(candles)
        spread = self.client.symbol_spread_points()
        positions = self.client.positions()

        # Sync broker-side closes before decisions
        self._reconcile_broker_closes(positions)
        positions = self.client.positions()

        # Trail SL to lock in profit
        self._update_trailing_stops(positions)

        has_buy = any(p["type"] == "BUY" for p in positions)
        has_sell = any(p["type"] == "SELL" for p in positions)

        bar_time = candles.index[-1]
        new_bar = self._last_bar_time is not None and bar_time != self._last_bar_time
        if new_bar:
            self.risk.on_new_candle()
        self._last_bar_time = bar_time

        signal = self.strategy.evaluate(candles, spread, has_buy, has_sell)

        if self.status == "RUNNING" and not self.paused:
            # If daily halt is active, flatten any leftover exposure
            if self.risk.halted and positions:
                self.close_all(self.risk.halt_reason or "Daily halt")
                positions = self.client.positions()
                has_buy = any(p["type"] == "BUY" for p in positions)
                has_sell = any(p["type"] == "SELL" for p in positions)
                signal = self.strategy.evaluate(candles, spread, has_buy, has_sell)

            self._maybe_reverse_close(signal, positions)
            positions = self.client.positions()
            has_buy = any(p["type"] == "BUY" for p in positions)
            has_sell = any(p["type"] == "SELL" for p in positions)
            # Re-evaluate risk AFTER closes so daily halt blocks the next open
            risk = self.risk.can_trade(spread)

            if signal.signal in (SignalType.BUY, SignalType.SELL) and risk.allowed:
                self._open_from_signal(signal, bar_time)
            elif signal.signal in (SignalType.BUY, SignalType.SELL) and not risk.allowed:
                # Log once per bar to avoid spam
                if new_bar or self._acted_entry_bar != signal.bar_time:
                    self._log(f"Signal {signal.signal.value} blocked: {risk.reason}")
                    self._acted_entry_bar = signal.bar_time
        else:
            risk = self.risk.can_trade(spread)

        values = self.strategy.latest_values()
        stats = self.db.stats(dry_run=self.config.dry_run)
        account = self.client.account_info()

        return BotSnapshot(
            status=self.status,
            connected=self.client.connected or self.config.dry_run,
            dry_run=self.config.dry_run,
            account=account,
            signal=signal,
            rsi=values["rsi"],
            ema48=values["ema48"],
            ema50=values["ema50"],
            confidence=signal.confidence if signal else 0.0,
            positions=positions,
            candles=candles,
            indicators=indicators,
            day_profit=self.risk.day_profit,
            win_rate=stats["win_rate"],
            logs=list(self._log_buffer[-40:]),
            risk_reason=risk.reason,
            markers=list(self._markers[-50:]),
        )

    def _maybe_reverse_close(self, signal: TradeSignal, positions: list[dict[str, Any]]) -> None:
        if not self.config.close_on_reverse:
            return
        if signal.signal == SignalType.BUY and any(p["type"] == "SELL" for p in positions):
            self.close_all("Reverse signal BUY")
        elif signal.signal == SignalType.SELL and any(p["type"] == "BUY" for p in positions):
            self.close_all("Reverse signal SELL")

    def _open_from_signal(self, signal: TradeSignal, current_bar: pd.Timestamp) -> None:
        side = signal.signal.value
        if self._has_side(side):
            return

        # One entry attempt per signal bar
        signal_bar = signal.bar_time or current_bar
        if self._acted_entry_bar is not None and signal_bar == self._acted_entry_bar:
            return

        # Backoff after failed order_send
        if self._entry_backoff_until and datetime.utcnow() < self._entry_backoff_until:
            return

        account = self.client.account_info()
        volume = self.risk.position_size(
            balance=float(account["balance"]),
            stop_points=self.config.stop_loss_points or 50,
        )
        tick = self.client.symbol_tick(allow_simulated=self.config.dry_run)
        if tick is None:
            self._log(f"Failed to open {side}: no price tick available")
            self._acted_entry_bar = signal_bar
            self._entry_backoff_until = datetime.utcnow() + timedelta(seconds=30)
            return
        entry = tick["ask"] if side == "BUY" else tick["bid"]
        sl, tp = self._sl_tp_prices(side, entry)
        if not self.config.dry_run and sl <= 0:
            self._log(f"Failed to open {side}: live trading requires stop loss > 0")
            self._acted_entry_bar = signal_bar
            return
        pos = self.client.open_market(side, volume, sl=sl, tp=tp)
        if not pos:
            detail = self.client.last_error or "unknown error"
            self._log(f"Failed to open {side}: {detail}")
            self._acted_entry_bar = signal_bar
            self._entry_backoff_until = datetime.utcnow() + timedelta(seconds=30)
            return

        self._acted_entry_bar = signal_bar
        self._entry_backoff_until = None
        self.risk.register_open()
        self.db.insert_open(
            ticket=pos["ticket"],
            trade_type=side,
            entry_price=pos["price_open"],
            lot_size=volume,
            signal=signal.reason,
            confidence=signal.confidence,
            dry_run=self.config.dry_run,
            time_open=pos["time"],
        )
        self._markers.append(
            {
                "kind": "entry",
                "price": pos["price_open"],
                "side": side,
                "sl": sl,
                "tp": tp,
                "time": pd.Timestamp.utcnow(),
            }
        )
        msg = (
            f"{side} opened @ {pos['price_open']:.5f} "
            f"lot={volume} conf={signal.confidence:.0f}%"
        )
        self._log(msg)
        self.notify.notify("Trade Opened", msg)
