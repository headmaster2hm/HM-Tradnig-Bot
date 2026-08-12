"""Historical signal replay / lightweight backtest."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config import AppConfig
from strategy.indicators import compute_rsi_stack
from strategy.signals import SignalType, detect_crossover


@dataclass
class BacktestResult:
    trades: list[dict]
    win_rate: float
    net_profit: float
    signals: int


def run_backtest(candles: pd.DataFrame, config: AppConfig, point_value: float = 100.0) -> BacktestResult:
    ind = compute_rsi_stack(
        candles["close"],
        config.indicators.rsi_period,
        config.indicators.ema_fast,
        config.indicators.ema_slow,
    )
    trades: list[dict] = []
    position: dict | None = None
    signals = 0

    for i in range(2, len(ind)):
        prev = ind.iloc[i - 1]
        cur = ind.iloc[i]
        cross = detect_crossover(prev["ema48"], prev["ema50"], cur["ema48"], cur["ema50"])
        price = float(candles.iloc[i]["close"])
        rsi = float(cur["rsi"]) if pd.notna(cur["rsi"]) else 50.0

        if position and cross:
            want_close = (
                (position["side"] == "BUY" and cross == "down")
                or (position["side"] == "SELL" and cross == "up")
            )
            if want_close:
                pnl = (
                    (price - position["entry"]) * config.lot_size * point_value
                    if position["side"] == "BUY"
                    else (position["entry"] - price) * config.lot_size * point_value
                )
                trades.append({**position, "exit": price, "profit": pnl})
                position = None

        if cross == "up" and rsi > 50 and position is None:
            signals += 1
            position = {"side": "BUY", "entry": price, "time": candles.index[i]}
        elif cross == "down" and rsi < 50 and position is None:
            signals += 1
            position = {"side": "SELL", "entry": price, "time": candles.index[i]}

    profits = [t["profit"] for t in trades]
    wins = [p for p in profits if p > 0]
    return BacktestResult(
        trades=trades,
        win_rate=(len(wins) / len(profits) * 100.0) if profits else 0.0,
        net_profit=sum(profits) if profits else 0.0,
        signals=signals,
    )
