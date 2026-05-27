"""Technical indicator calculations: ATR, pivot detection, market structure."""
import numpy as np
import pandas as pd

from config import ATR_PERIOD, PIVOT_DEPTH, STRUCTURE_SWING_COUNT


def compute_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """True Range and ATR(period)."""
    high = df["High"]
    low = df["Low"]
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def find_pivot_highs(df: pd.DataFrame, depth: int = PIVOT_DEPTH) -> pd.Series:
    """Return a boolean series — True where bar is a confirmed pivot high."""
    h = df["High"]
    result = pd.Series(False, index=df.index)
    for i in range(depth, len(df) - depth):
        window = h.iloc[i - depth: i + depth + 1]
        if h.iloc[i] == window.max():
            result.iloc[i] = True
    return result


def find_pivot_lows(df: pd.DataFrame, depth: int = PIVOT_DEPTH) -> pd.Series:
    """Return a boolean series — True where bar is a confirmed pivot low."""
    lo = df["Low"]
    result = pd.Series(False, index=df.index)
    for i in range(depth, len(df) - depth):
        window = lo.iloc[i - depth: i + depth + 1]
        if lo.iloc[i] == window.min():
            result.iloc[i] = True
    return result


def detect_structure(df: pd.DataFrame, n_swings: int = STRUCTURE_SWING_COUNT) -> str:
    """Return 'bullish', 'bearish', or 'neutral' based on last n pivot swing highs/lows."""
    ph = df.index[find_pivot_highs(df)].tolist()
    pl = df.index[find_pivot_lows(df)].tolist()

    recent_highs = [df.loc[i, "High"] for i in ph[-n_swings:]] if len(ph) >= n_swings else []
    recent_lows = [df.loc[i, "Low"] for i in pl[-n_swings:]] if len(pl) >= n_swings else []

    if len(recent_highs) < 2 or len(recent_lows) < 2:
        return "neutral"

    highs_rising = all(recent_highs[i] < recent_highs[i + 1] for i in range(len(recent_highs) - 1))
    lows_rising = all(recent_lows[i] < recent_lows[i + 1] for i in range(len(recent_lows) - 1))
    highs_falling = all(recent_highs[i] > recent_highs[i + 1] for i in range(len(recent_highs) - 1))
    lows_falling = all(recent_lows[i] > recent_lows[i + 1] for i in range(len(recent_lows) - 1))

    if highs_rising and lows_rising:
        return "bullish"
    if highs_falling and lows_falling:
        return "bearish"
    return "neutral"
