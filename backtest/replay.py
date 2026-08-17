"""Historical signal replay / lightweight backtest."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import AppConfig
from strategy.indicators import compute_rsi_stack
from strategy.signals import (
    SignalType,
    compute_confidence,
    detect_crossover,
)


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
        config.indicators.trend_ema_period,
    )
    trades: list[dict] = []
    position: dict | None = None
    signals = 0
    min_conf = config.min_confidence
    use_trend = config.use_trend_filter
    trailing = config.trailing_stop_points

    for i in range(2, len(ind)):
        prev = ind.iloc[i - 1]
        cur = ind.iloc[i]
        cross = detect_crossover(prev["ema48"], prev["ema50"], cur["ema48"], cur["ema50"])
        price = float(candles.iloc[i]["close"])
        rsi = float(cur["rsi"]) if pd.notna(cur["rsi"]) else 50.0
        trend_val = float(cur["trend_ema"]) if pd.notna(cur.get("trend_ema")) else float("nan")

        # Trailing stop: update SL on open position
        if position and trailing > 0:
            point = point_value
            if position["side"] == "BUY":
                profit_pts = (price - position["entry"]) / point
                if profit_pts >= trailing:
                    new_sl = position["entry"] + (profit_pts - trailing) * point
                    if new_sl > position.get("sl", 0):
                        position["sl"] = new_sl
            elif position["side"] == "SELL":
                profit_pts = (position["entry"] - price) / point
                if profit_pts >= trailing:
                    new_sl = position["entry"] - (profit_pts - trailing) * point
                    if new_sl < position.get("sl", float("inf")):
                        position["sl"] = new_sl

        # Check SL hit
        if position:
            sl = position.get("sl", 0)
            if position["side"] == "BUY" and sl > 0 and price <= sl:
                pnl = (price - position["entry"]) * config.lot_size * point_value
                trades.append({**position, "exit": price, "profit": pnl, "exit_reason": "trailing_sl"})
                position = None
            elif position["side"] == "SELL" and sl > 0 and price >= sl:
                pnl = (position["entry"] - price) * config.lot_size * point_value
                trades.append({**position, "exit": price, "profit": pnl, "exit_reason": "trailing_sl"})
                position = None

        # Close on reverse crossover
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
                trades.append({**position, "exit": price, "profit": pnl, "exit_reason": "reverse"})
                position = None

        # Open new position
        if cross and position is None:
            candle = candles.iloc[i]
            conf = compute_confidence(
                rsi=rsi,
                ema48=float(cur["ema48"]) if pd.notna(cur["ema48"]) else 0,
                ema50=float(cur["ema50"]) if pd.notna(cur["ema50"]) else 0,
                prev_rsi=float(prev["rsi"]) if pd.notna(prev["rsi"]) else 50,
                open_=float(candle["open"]),
                close=float(candle["close"]),
                spread=0,
                spread_limit=config.spread_limit,
            )
            if conf < min_conf:
                continue

            if cross == "up" and rsi > 50:
                if use_trend and not np.isnan(trend_val) and price < trend_val:
                    continue
                signals += 1
                sl_price = price - config.stop_loss_points * point_value if config.stop_loss_points > 0 else 0
                position = {"side": "BUY", "entry": price, "time": candles.index[i], "sl": sl_price}
            elif cross == "down" and rsi < 50:
                if use_trend and not np.isnan(trend_val) and price > trend_val:
                    continue
                signals += 1
                sl_price = price + config.stop_loss_points * point_value if config.stop_loss_points > 0 else 0
                position = {"side": "SELL", "entry": price, "time": candles.index[i], "sl": sl_price}

    # Close any remaining position at last price
    if position:
        price = float(candles.iloc[-1]["close"])
        pnl = (
            (price - position["entry"]) * config.lot_size * point_value
            if position["side"] == "BUY"
            else (position["entry"] - price) * config.lot_size * point_value
        )
        trades.append({**position, "exit": price, "profit": pnl, "exit_reason": "end"})

    profits = [t["profit"] for t in trades]
    wins = [p for p in profits if p > 0]
    return BacktestResult(
        trades=trades,
        win_rate=(len(wins) / len(profits) * 100.0) if profits else 0.0,
        net_profit=sum(profits) if profits else 0.0,
        signals=signals,
    )
