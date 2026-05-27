"""Core strategy: supply/demand zone scanner with ATR impulse filter.

Key rules:
- Weekly trend sets the bias (bullish/bearish/neutral)
- Daily trend must agree
- Impulse: consecutive directional bars with ATR expansion
- Zone: body of first impulse bar
- Retest: ANY touch of zone after impulse (2nd, 3rd visits all valid)
- Confirmation: candle after retest closes beyond prior bar's high/low
- Signal window: confirmation within last CONFIRMATION_WINDOW bars (default 3)
- Zone invalidation: body close THROUGH the zone (not just a wick)
"""
import logging
from dataclasses import dataclass
from typing import List, Optional
import pandas as pd

from config import STOP_ATR_BUFFER
from indicators import compute_atr, detect_structure
from zones import find_zones, find_nearest_opposite_zone

log = logging.getLogger(__name__)

CONFIRMATION_WINDOW = 3   # confirmation valid if within last N bars
MAX_RETESTS = 5           # cap retests per zone to avoid noise


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
    retest_number: int = 1


def scan_symbol(
    symbol: str,
    daily: pd.DataFrame,
    weekly: pd.DataFrame,
) -> List[Signal]:
    """Run the full strategy pipeline. Checks ALL retests of every zone."""
    signals: List[Signal] = []

    weekly_structure = detect_structure(weekly)
    daily_structure  = detect_structure(daily)

    for side in ["long", "short"]:
        required = "bullish" if side == "long" else "bearish"

        # Weekly must agree OR be neutral (daily leads)
        if weekly_structure != required and weekly_structure != "neutral":
            continue
        if daily_structure != required:
            continue

        zones = find_zones(daily, side)
        if not zones:
            continue

        for zone in zones:
            post_impulse = daily.iloc[zone.impulse_end_idx + 1:]
            if post_impulse.empty:
                continue

            atr = compute_atr(daily)

            # ── Walk ALL retests of this zone ─────────────────────────────
            search_from = 0          # slide forward after each retest
            retest_count = 0
            zone_valid = True        # flip False if price closes through zone

            while retest_count < MAX_RETESTS and zone_valid:
                slice_df = post_impulse.iloc[search_from:]
                if slice_df.empty:
                    break

                retest_local = _find_next_retest(slice_df, zone, side)
                if retest_local is None:
                    break

                retest_count += 1
                retest_bar = slice_df.iloc[retest_local]
                abs_retest_idx = search_from + retest_local  # index within post_impulse

                # Zone invalidation: body closed through zone → stop scanning
                if side == "long" and retest_bar["Close"] < zone.zone_low:
                    log.debug("%s [%s]: zone invalidated at retest #%d", symbol, side, retest_count)
                    zone_valid = False
                    break
                if side == "short" and retest_bar["Close"] > zone.zone_high:
                    log.debug("%s [%s]: zone invalidated at retest #%d", symbol, side, retest_count)
                    zone_valid = False
                    break

                # Need a bar after retest for confirmation
                if abs_retest_idx + 1 >= len(post_impulse):
                    # retest is the very last bar — no confirmation yet
                    search_from = abs_retest_idx + 1
                    continue

                confirm_bar = post_impulse.iloc[abs_retest_idx + 1]
                prev_bar    = retest_bar

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
                    # No confirmation here — advance past retest and keep looking
                    search_from = abs_retest_idx + 1
                    continue

                # How fresh is this confirmation?
                confirm_abs = abs_retest_idx + 1
                bars_since  = len(post_impulse) - 1 - confirm_abs

                if bars_since > CONFIRMATION_WINDOW:
                    # Confirmed but stale — keep walking (a later retest may be fresh)
                    search_from = abs_retest_idx + 1
                    continue

                # ── Valid fresh signal ────────────────────────────────────
                atr_idx     = min(zone.impulse_end_idx + confirm_abs + 1, len(atr) - 1)
                current_atr = float(atr.iloc[atr_idx])
                entry       = float(confirm_bar["Close"])

                if side == "long":
                    stop = round(zone.zone_low - STOP_ATR_BUFFER * current_atr, 2)
                else:
                    stop = round(zone.zone_high + STOP_ATR_BUFFER * current_atr, 2)

                target = find_nearest_opposite_zone(daily, entry, side)
                if target is None:
                    rr     = abs(entry - stop)
                    target = round(
                        entry + rr * 2 if side == "long" else entry - rr * 2, 2
                    )

                expansion = zone.atr_end / zone.atr_before if zone.atr_before > 0 else 1.0
                rr_ratio  = abs(target - entry) / abs(entry - stop) if abs(entry - stop) > 0 else 0.0
                quality   = round((expansion - 1.0) * 0.4 + min(rr_ratio / 3.0, 1.0) * 0.6, 3)

                log.info(
                    "%s [%s] retest#%d: SIGNAL | entry=%.2f stop=%.2f target=%.2f "
                    "confirmed %d bar(s) ago | zone=%.2f-%.2f",
                    symbol, side, retest_count,
                    entry, stop, target or 0, bars_since,
                    zone.zone_low, zone.zone_high,
                )

                signals.append(Signal(
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
                    retest_number=retest_count,
                ))

                # Advance past this confirmation — look for more retests
                search_from = abs_retest_idx + 2

    return signals


def _find_next_retest(
    df: pd.DataFrame,
    zone,
    side: str,
) -> Optional[int]:
    """Return index (within df) of the next bar that touches the zone."""
    for i, (_, row) in enumerate(df.iterrows()):
        if side == "long":
            if row["Low"] <= zone.zone_high and row["High"] >= zone.zone_low:
                return i
        else:
            if row["High"] >= zone.zone_low and row["Low"] <= zone.zone_high:
                return i
    return None
