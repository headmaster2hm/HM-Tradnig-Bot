"""Signal generation and confidence scoring for the RSI EMA stack."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class TradeSignal:
    signal: SignalType
    rsi: float
    ema48: float
    ema50: float
    confidence: float
    reason: str
    bar_time: pd.Timestamp | None = None


def _safe(value: float) -> float:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return float("nan")
    return float(value)


def compute_confidence(
    rsi: float,
    ema48: float,
    ema50: float,
    prev_rsi: float,
    open_: float,
    close: float,
    spread: float,
    spread_limit: float,
) -> float:
    """0–100 confidence from RSI slope, crossover strength, momentum, spread."""
    score = 0.0

    # RSI slope / distance from midline
    rsi_edge = abs(rsi - 50.0)
    score += min(rsi_edge, 25.0)  # up to 25

    slope = rsi - prev_rsi
    if (rsi > 50 and slope > 0) or (rsi < 50 and slope < 0):
        score += min(abs(slope) * 4.0, 20.0)
    else:
        score += 5.0

    # EMA crossover separation
    sep = abs(ema48 - ema50)
    score += min(sep * 3.0, 25.0)

    # Candle momentum
    body = abs(close - open_)
    mid = (abs(close) + abs(open_)) / 2.0 or 1.0
    momentum = (body / mid) * 1000.0
    score += min(momentum, 15.0)

    # Spread quality
    if spread_limit > 0:
        quality = max(0.0, 1.0 - (spread / spread_limit))
        score += quality * 15.0

    return float(max(0.0, min(100.0, round(score, 1))))


def detect_crossover(prev_fast: float, prev_slow: float, fast: float, slow: float) -> str | None:
    if any(np.isnan(v) for v in (prev_fast, prev_slow, fast, slow)):
        return None
    if prev_fast <= prev_slow and fast > slow:
        return "up"
    if prev_fast >= prev_slow and fast < slow:
        return "down"
    return None


def evaluate_signals(
    indicators: pd.DataFrame,
    candles: pd.DataFrame,
    spread: float,
    spread_limit: float,
    has_buy: bool,
    has_sell: bool,
) -> TradeSignal:
    """Evaluate the latest closed bar for BUY / SELL / HOLD."""
    if len(indicators) < 3:
        return TradeSignal(SignalType.HOLD, 0, 0, 0, 0, "Insufficient data")

    # Use last closed candle (exclude forming bar when available)
    idx = -2 if len(indicators) >= 2 else -1
    prev_idx = idx - 1

    row = indicators.iloc[idx]
    prev = indicators.iloc[prev_idx]
    candle = candles.iloc[idx]

    rsi = _safe(row["rsi"])
    ema48 = _safe(row["ema48"])
    ema50 = _safe(row["ema50"])
    prev_rsi = _safe(prev["rsi"])
    bar_time = indicators.index[idx] if hasattr(indicators.index[idx], "isoformat") else None

    cross = detect_crossover(
        _safe(prev["ema48"]),
        _safe(prev["ema50"]),
        ema48,
        ema50,
    )

    confidence = compute_confidence(
        rsi=rsi,
        ema48=ema48,
        ema50=ema50,
        prev_rsi=prev_rsi,
        open_=float(candle["open"]),
        close=float(candle["close"]),
        spread=spread,
        spread_limit=spread_limit,
    )

    if cross == "up" and rsi > 50 and not has_buy:
        return TradeSignal(
            SignalType.BUY,
            rsi,
            ema48,
            ema50,
            confidence,
            "EMA48 crossed above EMA50 with RSI > 50",
            bar_time,
        )

    if cross == "down" and rsi < 50 and not has_sell:
        return TradeSignal(
            SignalType.SELL,
            rsi,
            ema48,
            ema50,
            confidence,
            "EMA48 crossed below EMA50 with RSI < 50",
            bar_time,
        )

    if cross == "up" and has_buy:
        return TradeSignal(SignalType.HOLD, rsi, ema48, ema50, confidence, "Duplicate BUY ignored", bar_time)
    if cross == "down" and has_sell:
        return TradeSignal(SignalType.HOLD, rsi, ema48, ema50, confidence, "Duplicate SELL ignored", bar_time)

    return TradeSignal(
        SignalType.HOLD,
        rsi,
        ema48,
        ema50,
        confidence,
        "No crossover",
        bar_time,
    )
