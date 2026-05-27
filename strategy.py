"""Core strategy: supply/demand zone scanner with ATR impulse filter.

Key rules:
- Weekly trend sets the bias (bullish/bearish/neutral)
- Daily trend must agree OR be neutral (daily leads are allowed)
- Impulse: >= IMPULSE_MIN_BARS consecutive directional bars with ATR expansion
- Zone: body of first impulse bar
- Retest: first touch of zone after impulse
- Confirmation: candle after retest closes beyond prior bar's high/low
- Signal window: confirmation within last CONFIRMATION_WINDOW bars (default 3)
"""
import logging
from dataclasses import dataclass
from typing import List, Optional
import pandas as pd

from config import STOP_ATR_BUFFER, MAX_OPEN_DAYS
from indicators import compute_atr, detect_structure
from zones import find_zones, find_nearest_opposite_zone

log = logging.getLogger(__name__)

# How many bars back a confirmation is still considered "fresh" / actionable
CONFIRMATION_WINDOW = 3  # signal is valid if confirmation happened within last 3 bars


@dataclass
class Signal:
    symbol: str
    side: str
    scan_date: str
    confirmation_date: str
    entry_price: float
    stop_loss: float
    target_price: Optional[float]
    zone_low: float
    zone_high: float
    weekly_structure: str
    daily_structure: str
    atr_before: float
    atr_end: float
    atr_expansion: float
    confirmation_close: float
    confirmation_prev_high: float
    quality_score: float
    bars_since_confirmation: int = 0


def scan_symbol(
    symbol: str,
    daily: pd.DataFrame,
    weekly: pd.DataFrame,
) -> List[Signal]:
    """Run the full strategy pipeline on one symbol. Returns confirmed signals."""
    signals: List[Signal] = []

    weekly_structure = detect_structure(weekly)
    daily_structure = detect_structure(daily)

    for side in ["long", "short"]:
        required = "bullish" if side == "long" else "bearish"

        # Weekly must agree OR daily must lead (weekly neutral is OK)
        if weekly_structure != required and weekly_structure != "neutral":
            continue
        # Daily must agree
        if daily_structure != required:
            continue

        zones = find_zones(daily, side)
        if not zones:
            log.debug("%s [%s]: no impulse zones found", symbol, side)
            continue

        for zone in zones:
            post_impulse = daily.iloc[zone.impulse_end_idx + 1:]
            if post_impulse.empty:
                continue

            retest_idx = _find_first_retest(post_impulse, zone, side)
            if retest_idx is None:
                continue

            retest_bar = post_impulse.iloc[retest_idx]

            # Zone invalidation: body close beyond zone
            if side == "long" and retest_bar["Close"] < zone.zone_low:
                log.debug("%s [%s]: zone invalidated on retest", symbol, side)
                continue
            if side == "short" and retest_bar["Close"] > zone.zone_high:
                log.debug("%s [%s]: zone invalidated on retest", symbol, side)
                continue

            # Need at least one bar after retest for confirmation
            if retest_idx + 1 >= len(post_impulse):
                continue

            confirm_bar = post_impulse.iloc[retest_idx + 1]
            prev_bar = retest_bar

            # Confirmation check
            if side == "long":
                confirmed = (
                    confirm_bar["Close"] > confirm_bar["Open"] and
                    confirm_bar["Close"] > prev_bar["High"]
                )
            else:
                confirmed = (
                    confirm_bar["Close"] < confirm_bar["Open"] and
                    confirm_bar["Close"] < prev_bar["Low"]
                )

            if not confirmed:
                log.debug("%s [%s]: confirmation candle failed", symbol, side)
                continue

            # Check confirmation is within the actionable window
            confirm_pos = retest_idx + 1        # position within post_impulse
            bars_since = len(post_impulse) - 1 - confirm_pos

            if bars_since > CONFIRMATION_WINDOW:
                log.debug("%s [%s]: confirmation too old (%d bars ago)", symbol, side, bars_since)
                continue

            # Compute entry, stop, target
            atr = compute_atr(daily)
            atr_idx = zone.impulse_end_idx + confirm_pos + 1
            atr_idx = min(atr_idx, len(atr) - 1)
            current_atr = float(atr.iloc[atr_idx])
            entry = float(confirm_bar["Close"])

            if side == "long":
                stop = round(zone.zone_low - STOP_ATR_BUFFER * current_atr, 2)
            else:
                stop = round(zone.zone_high + STOP_ATR_BUFFER * current_atr, 2)

            target = find_nearest_opposite_zone(daily, entry, side)
            if target is None:
                rr = abs(entry - stop)
                target = round(
                    entry + rr * 2 if side == "long" else entry - rr * 2, 2
                )

            expansion = zone.atr_end / zone.atr_before if zone.atr_before > 0 else 1.0
            rr_ratio = abs(target - entry) / abs(entry - stop) if abs(entry - stop) > 0 else 0.0
            quality = round((expansion - 1.0) * 0.4 + min(rr_ratio / 3.0, 1.0) * 0.6, 3)

            sig = Signal(
                symbol=symbol,
                side=side,
                scan_date=str(daily.index[-1].date()),
                confirmation_date=str(confirm_bar.name.date()),
                entry_price=round(entry, 2),
                stop_loss=round(stop, 2),
                target_price=round(target, 2) if target else None,
                zone_low=round(zone.zone_low, 2),
                zone_high=round(zone.zone_high, 2),
                weekly_structure=weekly_structure,
                daily_structure=daily_structure,
                atr_before=round(zone.atr_before, 4),
                atr_end=round(zone.atr_end, 4),
                atr_expansion=round(expansion, 3),
                confirmation_close=round(float(confirm_bar["Close"]), 2),
                confirmation_prev_high=round(float(prev_bar["High"]), 2),
                quality_score=quality,
                bars_since_confirmation=bars_since,
            )
            log.info("%s [%s]: SIGNAL found | entry=%.2f stop=%.2f target=%.2f confirmed %d bar(s) ago",
                     symbol, side, entry, stop, target or 0, bars_since)
            signals.append(sig)

    return signals


def _find_first_retest(post_impulse: pd.DataFrame, zone, side: str) -> Optional[int]:
    """Return index within post_impulse of the first retest bar."""
    for i, (_, row) in enumerate(post_impulse.iterrows()):
        if side == "long":
            if row["Low"] <= zone.zone_high and row["High"] >= zone.zone_low:
                return i
        else:
            if row["High"] >= zone.zone_low and row["Low"] <= zone.zone_high:
                return i
    return None
