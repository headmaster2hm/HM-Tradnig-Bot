"""Plugin-based strategy architecture."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from config import AppConfig
from strategy.indicators import compute_rsi_stack
from strategy.signals import SignalType, TradeSignal, evaluate_signals


class BaseStrategy(ABC):
    name: str = "base"

    @abstractmethod
    def prepare(self, candles: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def evaluate(
        self,
        candles: pd.DataFrame,
        spread: float,
        has_buy: bool,
        has_sell: bool,
    ) -> TradeSignal:
        raise NotImplementedError


class RsiEmaStrategy(BaseStrategy):
    """RSI(14) + EMA48(on RSI) + EMA50(on EMA48) crossover strategy."""

    name = "rsi_ema_stack"

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.indicators: pd.DataFrame | None = None

    def prepare(self, candles: pd.DataFrame) -> pd.DataFrame:
        ind = self.config.indicators
        self.indicators = compute_rsi_stack(
            candles["close"],
            rsi_period=ind.rsi_period,
            ema_fast=ind.ema_fast,
            ema_slow=ind.ema_slow,
            trend_ema_period=ind.trend_ema_period,
        )
        return self.indicators

    def evaluate(
        self,
        candles: pd.DataFrame,
        spread: float,
        has_buy: bool,
        has_sell: bool,
    ) -> TradeSignal:
        if self.indicators is None or len(self.indicators) != len(candles):
            self.prepare(candles)
        assert self.indicators is not None
        return evaluate_signals(
            indicators=self.indicators,
            candles=candles,
            spread=spread,
            spread_limit=self.config.spread_limit,
            has_buy=has_buy,
            has_sell=has_sell,
            min_confidence=self.config.min_confidence,
            use_trend_filter=self.config.use_trend_filter,
        )

    def latest_values(self) -> dict[str, Any]:
        if self.indicators is None or self.indicators.empty:
            return {"rsi": None, "ema48": None, "ema50": None}
        row = self.indicators.iloc[-1]
        return {
            "rsi": float(row["rsi"]) if pd.notna(row["rsi"]) else None,
            "ema48": float(row["ema48"]) if pd.notna(row["ema48"]) else None,
            "ema50": float(row["ema50"]) if pd.notna(row["ema50"]) else None,
        }


STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    RsiEmaStrategy.name: RsiEmaStrategy,
}


def create_strategy(name: str, config: AppConfig) -> BaseStrategy:
    cls = STRATEGY_REGISTRY.get(name, RsiEmaStrategy)
    return cls(config)
