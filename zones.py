"""Identify impulse moves and mark demand / supply zones."""
from dataclasses import dataclass, field
from typing import List, Optional
import pandas as pd

from config import IMPULSE_MIN_BARS, ATR_EXPANSION_FACTOR
from indicators import compute_atr


@dataclass
class Zone:
    side: str           # 'long' or 'short'
    zone_high: float
    zone_low: float
    impulse_start_idx: int
    impulse_end_idx: int
    atr_before: float
    atr_end: float
    retest_idx: Optional[int] = None
    retest_confirmed: bool = False
    confirmation_idx: Optional[int] = None
    invalidated: bool = False


def find_zones(df: pd.DataFrame, side: str) -> List[Zone]:
    """Scan df for all valid impulse-based zones for 'long' or 'short'."""
    atr = compute_atr(df)
    zones: List[Zone] = []

    i = IMPULSE_MIN_BARS
    while i < len(df) - 1:
        # ── Detect impulse ───────────────────────────────────────────────────
        if side == "long":
            is_impulse_bar = lambda idx: df["Close"].iloc[idx] > df["Open"].iloc[idx]  # bullish bar
        else:
            is_impulse_bar = lambda idx: df["Close"].iloc[idx] < df["Open"].iloc[idx]  # bearish bar

        # check if we have IMPULSE_MIN_BARS consecutive bars ending at i
        bars = list(range(i - IMPULSE_MIN_BARS + 1, i + 1))
        if not all(is_impulse_bar(b) for b in bars):
            i += 1
            continue

        # ATR check
        atr_before = atr.iloc[i - IMPULSE_MIN_BARS]   # ATR immediately before impulse
        atr_end = atr.iloc[i]                          # ATR at end of impulse
        if atr_before == 0 or atr_end < ATR_EXPANSION_FACTOR * atr_before:
            i += 1
            continue

        # ── Define zone from first impulse bar body ──────────────────────────
        first_bar = df.iloc[i - IMPULSE_MIN_BARS + 1]
        zone_high = max(first_bar["Open"], first_bar["Close"])
        zone_low = min(first_bar["Open"], first_bar["Close"])

        zones.append(Zone(
            side=side,
            zone_high=zone_high,
            zone_low=zone_low,
            impulse_start_idx=i - IMPULSE_MIN_BARS + 1,
            impulse_end_idx=i,
            atr_before=float(atr_before),
            atr_end=float(atr_end),
        ))
        i += IMPULSE_MIN_BARS  # skip forward to avoid overlapping impulses

    return zones


def find_nearest_opposite_zone(df: pd.DataFrame, current_price: float, side: str) -> Optional[float]:
    """Find target by locating the nearest opposite zone above (long) or below (short)."""
    opposite_side = "short" if side == "long" else "long"
    opp_zones = find_zones(df, opposite_side)
    if not opp_zones:
        return None

    if side == "long":
        # nearest supply zone above current price
        candidates = [z.zone_low for z in opp_zones if z.zone_low > current_price]
        return min(candidates) if candidates else None
    else:
        # nearest demand zone below current price
        candidates = [z.zone_high for z in opp_zones if z.zone_high < current_price]
        return max(candidates) if candidates else None
