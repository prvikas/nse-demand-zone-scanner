"""Core strategy: supply/demand zone scanner with ATR impulse + RSI + Volume filters.

Key rules:
- Weekly trend sets the bias (bullish/bearish/neutral)
- Daily trend must agree
- Impulse: consecutive directional bars with ATR expansion
- Zone: body of first impulse bar
- Retest: ANY touch of zone after impulse (2nd, 3rd visits all valid)
- Confirmation: candle after retest closes beyond prior bar's high/low
- RSI filter (hard): long RSI >= 50 and rising; short RSI <= 50 and falling
- Volume filter (hard): confirm bar volume >= VOL_RATIO_MIN x 20-day average
- Signal window: confirmation within last CONFIRMATION_WINDOW bars (default 3)
- Zone invalidation: body close THROUGH the zone
- scan_date: always the date the scanner RAN (passed in as run_date)
"""
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional
import pandas as pd

from config import STOP_ATR_BUFFER
from indicators import compute_atr, compute_rsi, compute_volume_ratio, detect_structure
from zones import find_zones, find_nearest_opposite_zone

log = logging.getLogger(__name__)

CONFIRMATION_WINDOW = 3
MAX_RETESTS         = 5
RSI_LONG_MIN        = 50.0   # RSI must be >= this for longs
RSI_SHORT_MAX       = 50.0   # RSI must be <= this for shorts
VOL_RATIO_MIN       = 1.3    # confirm bar volume must be >= 1.3x 20-day avg


@dataclass
class Signal:
    symbol:                 str
    side:                   str
    scan_date:              str
    confirmation_date:      str
    entry_price:            float
    stop_loss:              float
    target_price:           Optional[float]
    zone_low:               float
    zone_high:              float
    weekly_structure:       str
    daily_structure:        str
    atr_before:             float
    atr_end:                float
    atr_expansion:          float
    confirmation_close:     float
    confirmation_prev_high: float
    quality_score:          float
    rsi_at_confirm:         float   # RSI value on the confirmation bar
    volume_ratio:           float   # confirm bar vol / 20-day avg vol
    bars_since_confirmation: int = 0
    retest_number:          int = 1


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

    signals:          List[Signal] = []
    weekly_structure = detect_structure(weekly)
    daily_structure  = detect_structure(daily)

    # Pre-compute RSI and Volume ratio for the full daily series
    rsi_series = compute_rsi(daily)
    vol_series = compute_volume_ratio(daily)

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

            atr            = compute_atr(daily)
            search_from    = 0
            retest_count   = 0
            zone_valid     = True

            while retest_count < MAX_RETESTS and zone_valid:
                slice_df = post_impulse.iloc[search_from:]
                if slice_df.empty:
                    break

                retest_local = _find_next_retest(slice_df, zone, side)
                if retest_local is None:
                    break

                retest_count  += 1
                retest_bar     = slice_df.iloc[retest_local]
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

                # ── Candle confirmation ───────────────────────────────────────
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

                # ── RSI hard filter ───────────────────────────────────────────
                confirm_date  = confirm_bar.name
                rsi_val       = float(rsi_series.loc[confirm_date]) if confirm_date in rsi_series.index else 50.0
                rsi_prev      = float(rsi_series.iloc[rsi_series.index.get_loc(confirm_date) - 1]) \
                                if rsi_series.index.get_loc(confirm_date) > 0 else rsi_val

                if side == "long":
                    rsi_ok = rsi_val >= RSI_LONG_MIN and rsi_val > rsi_prev   # >= 50 AND rising
                else:
                    rsi_ok = rsi_val <= RSI_SHORT_MAX and rsi_val < rsi_prev  # <= 50 AND falling

                if not rsi_ok:
                    log.debug("%s [%s] retest#%d: RSI filter failed (rsi=%.1f prev=%.1f)",
                              symbol, side, retest_count, rsi_val, rsi_prev)
                    search_from = abs_retest_idx + 1
                    continue

                # ── Volume hard filter ────────────────────────────────────────
                vol_ratio = float(vol_series.loc[confirm_date]) if confirm_date in vol_series.index else 1.0

                if vol_ratio < VOL_RATIO_MIN:
                    log.debug("%s [%s] retest#%d: Volume filter failed (ratio=%.2f)",
                              symbol, side, retest_count, vol_ratio)
                    search_from = abs_retest_idx + 1
                    continue

                # ── Build signal ──────────────────────────────────────────────
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
                    "rsi=%.1f vol_ratio=%.2f bars_since=%d | zone=%.2f-%.2f",
                    symbol, side, retest_count,
                    entry, stop, target or 0,
                    rsi_val, vol_ratio, bars_since,
                    zone.zone_low, zone.zone_high,
                )

                signals.append(Signal(
                    symbol=symbol,
                    side=side,
                    scan_date=str(run_date),
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
                    rsi_at_confirm=round(rsi_val, 1),
                    volume_ratio=round(vol_ratio, 2),
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
