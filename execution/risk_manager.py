"""Risk gates: daily targets, spread, session, cooldown, sizing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from config import AppConfig
from utils.logger import get_logger

logger = get_logger("risk")


@dataclass
class RiskDecision:
    allowed: bool
    reason: str


class RiskManager:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._day: date | None = None
        self.day_profit: float = 0.0
        self.trades_today: int = 0
        self.candles_since_close: int = 10_000
        self.halted: bool = False
        self.halt_reason: str = ""

    def _roll_day(self) -> None:
        today = datetime.now().date()
        if self._day != today:
            self._day = today
            self.day_profit = 0.0
            self.trades_today = 0
            self.halted = False
            self.halt_reason = ""

    def register_close(self, profit: float) -> bool:
        """Record a closed trade. Returns True if a daily halt was just triggered."""
        self._roll_day()
        was_halted = self.halted
        self.day_profit += profit
        self.candles_since_close = 0
        if self.day_profit >= self.config.daily_profit_target:
            self.halted = True
            self.halt_reason = "Daily profit target reached"
            logger.info(self.halt_reason)
        elif self.day_profit <= -abs(self.config.daily_loss_limit):
            self.halted = True
            self.halt_reason = "Daily loss limit reached"
            logger.info(self.halt_reason)
        return self.halted and not was_halted

    def on_new_candle(self) -> None:
        self.candles_since_close += 1

    def in_session(self) -> bool:
        now = datetime.now().time()
        start = time.fromisoformat(self.config.session_start)
        end = time.fromisoformat(self.config.session_end)
        if start <= end:
            return start <= now <= end
        return now >= start or now <= end

    def can_trade(self, spread: float) -> RiskDecision:
        self._roll_day()

        if self.halted:
            return RiskDecision(False, self.halt_reason)
        if not self.in_session():
            return RiskDecision(False, "Outside trading session")
        if spread > self.config.spread_limit:
            return RiskDecision(False, f"Spread {spread:.0f} exceeds limit")
        if self.trades_today >= self.config.max_trades_per_day:
            return RiskDecision(False, "Max trades per day reached")
        if self.candles_since_close < self.config.cooldown_candles:
            return RiskDecision(
                False,
                f"Cooldown ({self.candles_since_close}/{self.config.cooldown_candles})",
            )
        return RiskDecision(True, "OK")

    def position_size(self, balance: float, stop_points: float, point_value: float = 1.0) -> float:
        if not self.config.use_risk_sizing or stop_points <= 0:
            return float(self.config.lot_size)
        risk_cash = balance * (self.config.risk_percent / 100.0)
        lots = risk_cash / (stop_points * point_value)
        return max(0.01, round(lots, 2))

    def register_open(self) -> None:
        self._roll_day()
        self.trades_today += 1

    def reset_daily_limits(self) -> None:
        """Clear daily halt counters (same calendar day). Use with care."""
        self._roll_day()
        self.day_profit = 0.0
        self.trades_today = 0
        self.halted = False
        self.halt_reason = ""
        self.candles_since_close = 10_000
        logger.info("Daily risk limits reset by user")
