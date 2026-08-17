"""MetaTrader-compatible indicator calculations.

RSI uses Wilder's smoothing (same as MT5).
EMA uses MT5's SMA seed then exponential smoothing.
Second EMA is applied to the first EMA series (Previous Indicator's Data).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index matching MetaTrader 5."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = gain.copy()
    avg_loss = loss.copy()
    avg_gain.iloc[:period] = np.nan
    avg_loss.iloc[:period] = np.nan

    if len(close) <= period:
        return pd.Series(np.nan, index=close.index, name="rsi")

    avg_gain.iloc[period] = gain.iloc[1 : period + 1].mean()
    avg_loss.iloc[period] = loss.iloc[1 : period + 1].mean()

    for i in range(period + 1, len(close)):
        avg_gain.iloc[i] = (avg_gain.iloc[i - 1] * (period - 1) + gain.iloc[i]) / period
        avg_loss.iloc[i] = (avg_loss.iloc[i - 1] * (period - 1) + loss.iloc[i]) / period

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(avg_loss != 0.0, 100.0)
    rsi = rsi.where(~((avg_gain == 0.0) & (avg_loss == 0.0)), 50.0)
    rsi.name = "rsi"
    return rsi


def mt5_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average matching MetaTrader 5."""
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan, dtype=float)
    alpha = 2.0 / (period + 1.0)

    valid_idx = np.where(~np.isnan(values))[0]
    if len(valid_idx) < period:
        return pd.Series(out, index=series.index, name=f"ema_{period}")

    start = int(valid_idx[0])
    seed_end = start + period
    if seed_end > len(values):
        return pd.Series(out, index=series.index, name=f"ema_{period}")

    seed_slice = values[start:seed_end]
    if np.isnan(seed_slice).any():
        # Skip forward until we have a contiguous seed window
        for i in range(start, len(values) - period + 1):
            window = values[i : i + period]
            if not np.isnan(window).any():
                start = i
                seed_end = i + period
                seed_slice = window
                break
        else:
            return pd.Series(out, index=series.index, name=f"ema_{period}")

    out[seed_end - 1] = float(np.mean(seed_slice))
    for i in range(seed_end, len(values)):
        if np.isnan(values[i]):
            continue
        prev = out[i - 1]
        if np.isnan(prev):
            continue
        out[i] = prev + alpha * (values[i] - prev)

    return pd.Series(out, index=series.index, name=f"ema_{period}")


def compute_rsi_stack(
    close: pd.Series,
    rsi_period: int = 14,
    ema_fast: int = 8,
    ema_slow: int = 21,
    trend_ema_period: int = 200,
) -> pd.DataFrame:
    """Build RSI + fast/slow EMAs on RSI + trend EMA on price."""
    rsi = wilder_rsi(close, rsi_period)
    ema_fast_series = mt5_ema(rsi, ema_fast)
    ema_slow_series = mt5_ema(ema_fast_series, ema_slow)
    trend_ema = mt5_ema(close, trend_ema_period)
    frame = pd.DataFrame(
        {
            "rsi": rsi,
            "ema48": ema_fast_series,
            "ema50": ema_slow_series,
            "trend_ema": trend_ema,
        },
        index=close.index,
    )
    return frame
