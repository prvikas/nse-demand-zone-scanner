"""Core strategy: supply/demand zone scanner with ATR impulse filter.

Key rules:
- Weekly trend sets the bias (bullish/bearish/neutral)
- Daily trend must agree
- Impulse: consecutive directional bars with ATR expansion
- Zone: body of first impulse bar
- Retest: ANY touch of zone after impulse (2nd, 3rd visits all valid)
- Confirmation: candle after retest closes beyond prior bar's high/low
- Signal window: confirmation within last CONFIRMATION_WINDOW bars (default 3)
- Zone invalidation: body close THROUGH the zone
- scan_date: always the date the scanner RAN (passed in as run_date)
"""
import logging
from dataclasses import dataclass
from datetime import date
from typing import List, Optional
import pandas as pd

from config import STOP_ATR_BUFFER
from indicators import compute_atr, detect_structure
from zones import find_zones, find_nearest_opposite_zone

log = logging.getLogger(__name__)

CONFIRMATION_WINDOW = 3
MAX_RETESTS = 5


@dataclass
class Signal:
    symbol: str
    side: str
    scan_date: str          # date the scanner ran (today)
    confirmation_date: str  # date of the confirmation candle on the chart
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
    run_date: Optional[date] = None,
) -> List[Signal]:
    """Run the full strategy pipeline. Checks ALL retests of every zone."""
    if run_date is None:
        from datetime import date as _date
        run_date = _date.today()

    signals: List[Signal] = []
    weekly_structure = detect_structure(weekly)
    daily_structure  = detect_structure(daily)

    for side in ["long", "short"]:
        required = "bullish" if side == "long" else "bearish"

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
            search_from = 0
            retest_count = 0
            zone_valid = True

            while retest_count < MAX_RETESTS and zone_valid:
                slice_df = post_impulse.iloc[search_from:]
                if slice_df.empty:
                    break

                retest_local = _find_next_retest(slice_df, zone, side)
                if retest_local is None:
                    break

                retest_count += 1
                retest_bar = slice_df.iloc[retest_local]
                abs_retest_idx = search_from + retest_local

                # Zone invalidation
                if side == "long" and retest_bar["Close"] < zone.zone_low:
                    zone_valid = False
                    break
                if side == "short" and retest_bar["Close"] > zone.zone_high:
                    zone_valid = False
                    break

                if abs_retest_idx + 1 >= len(post_impulse):
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
                    search_from = abs_retest_idx + 1
                    continue

                confirm_abs = abs_retest_idx + 1
                bars_since  = len(post_impulse) - 1 - confirm_abs

                if bars_since > CONFIRMATION_WINDOW:
                    search_from = abs_retest_idx + 1
                    continue

                # Valid fresh signal
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
                    scan_date=str(run_date),          # RUN date, not bar date
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

                search_from = abs_retest_idx + 2

    return signals


def _find_next_retest(df: pd.DataFrame, zone, side: str) -> Optional[int]:
    for i, (_, row) in enumerate(df.iterrows()):
        if side == "long":
            if row["Low"] <= zone.zone_high and row["High"] >= zone.zone_low:
                return i
        else:
            if row["High"] >= zone.zone_low and row["Low"] <= zone.zone_high:
                return i
    return None
