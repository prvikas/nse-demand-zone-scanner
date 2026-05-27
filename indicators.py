"""Technical indicator calculations: ATR, RSI, Volume, pivot detection, market structure."""
import numpy as np
import pandas as pd

from config import ATR_PERIOD, PIVOT_DEPTH, STRUCTURE_SWING_COUNT

RSI_PERIOD    = 14
VOL_AVG_BARS  = 20


def compute_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """True Range and ATR(period)."""
    high       = df["High"]
    low        = df["Low"]
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def compute_rsi(df: pd.DataFrame, period: int = RSI_PERIOD) -> pd.Series:
    """Wilder RSI — returns a Series aligned to df.index."""
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)  # fill early NaN with neutral 50


def compute_volume_ratio(df: pd.DataFrame, avg_bars: int = VOL_AVG_BARS) -> pd.Series:
    """Volume of each bar divided by rolling avg_bars mean.
    A ratio >= 1.3 means 30% above average — institutional participation.
    """
    vol_avg = df["Volume"].rolling(avg_bars, min_periods=5).mean()
    return (df["Volume"] / vol_avg).fillna(1.0)


def find_pivot_highs(df: pd.DataFrame, depth: int = PIVOT_DEPTH) -> pd.Series:
    """Return a boolean series — True where bar is a confirmed pivot high."""
    h      = df["High"]
    result = pd.Series(False, index=df.index)
    for i in range(depth, len(df) - depth):
        window = h.iloc[i - depth: i + depth + 1]
        if h.iloc[i] == window.max():
            result.iloc[i] = True
    return result


def find_pivot_lows(df: pd.DataFrame, depth: int = PIVOT_DEPTH) -> pd.Series:
    """Return a boolean series — True where bar is a confirmed pivot low."""
    lo     = df["Low"]
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
    recent_lows  = [df.loc[i, "Low"]  for i in pl[-n_swings:]] if len(pl) >= n_swings else []

    if len(recent_highs) < 2 or len(recent_lows) < 2:
        return "neutral"

    highs_rising  = all(recent_highs[i] < recent_highs[i + 1] for i in range(len(recent_highs) - 1))
    lows_rising   = all(recent_lows[i]  < recent_lows[i + 1]  for i in range(len(recent_lows)  - 1))
    highs_falling = all(recent_highs[i] > recent_highs[i + 1] for i in range(len(recent_highs) - 1))
    lows_falling  = all(recent_lows[i]  > recent_lows[i + 1]  for i in range(len(recent_lows)  - 1))

    if highs_rising and lows_rising:
        return "bullish"
    if highs_falling and lows_falling:
        return "bearish"
    return "neutral"
