"""Core strategy: combine multi-timeframe structure, impulse, zone, retest, confirmation."""
import logging
from dataclasses import dataclass
from typing import List, Optional
import pandas as pd

from config import STOP_ATR_BUFFER, MAX_OPEN_DAYS
from indicators import compute_atr, detect_structure
from zones import find_zones, find_nearest_opposite_zone

log = logging.getLogger(__name__)


@dataclass
class Signal:
    symbol: str
    side: str                    # 'long' or 'short'
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
    atr_expansion: float         # atr_end / atr_before
    confirmation_close: float
    confirmation_prev_high: float  # for audit
    quality_score: float


def scan_symbol(
    symbol: str,
    daily: pd.DataFrame,
    weekly: pd.DataFrame,
) -> List[Signal]:
    """Run the full strategy pipeline on one symbol. Returns confirmed signals."""
    signals: List[Signal] = []

    # ── Step 1: Weekly + daily structure ─────────────────────────────────────
    weekly_structure = detect_structure(weekly)
    daily_structure = detect_structure(daily)

    for side in ["long", "short"]:
        required_structure = "bullish" if side == "long" else "bearish"
        if weekly_structure != required_structure:
            continue
        if daily_structure != required_structure:
            continue

        # ── Step 2: Find impulse zones ────────────────────────────────────────
        zones = find_zones(daily, side)

        for zone in zones:
            # Only first retest: ensure price returned to zone exactly once after impulse
            post_impulse = daily.iloc[zone.impulse_end_idx + 1:]
            if post_impulse.empty:
                continue

            retest_idx = _find_first_retest(post_impulse, zone, side)
            if retest_idx is None:
                continue

            retest_bar = post_impulse.iloc[retest_idx]

            # ── Zone invalidation: body close beyond zone ─────────────────────
            if side == "long" and retest_bar["Close"] < zone.zone_low:
                continue
            if side == "short" and retest_bar["Close"] > zone.zone_high:
                continue

            # ── Step 3: Confirmation candle (day AFTER retest) ────────────────
            if retest_idx + 1 >= len(post_impulse):
                continue
            confirm_bar = post_impulse.iloc[retest_idx + 1]
            prev_bar = retest_bar

            if side == "long":
                if not (confirm_bar["Close"] > confirm_bar["Open"] and
                        confirm_bar["Close"] > prev_bar["High"]):
                    continue
            else:
                if not (confirm_bar["Close"] < confirm_bar["Open"] and
                        confirm_bar["Close"] < prev_bar["Low"]):
                    continue

            # ── This is the most recent bar (yesterday's candle = today signal) ──
            if retest_idx + 1 != len(post_impulse) - 1:
                continue  # only emit signals where confirmation is the latest bar

            # ── Compute entry, stop, target ───────────────────────────────────
            atr = compute_atr(daily)
            current_atr = float(atr.iloc[zone.impulse_end_idx + retest_idx + 1])
            entry = float(confirm_bar["Close"])

            if side == "long":
                stop = round(zone.zone_low - STOP_ATR_BUFFER * current_atr, 2)
            else:
                stop = round(zone.zone_high + STOP_ATR_BUFFER * current_atr, 2)

            target = find_nearest_opposite_zone(daily, entry, side)
            if target is None:
                # fallback: 2R target
                rr = abs(entry - stop)
                target = round(entry + rr * 2 if side == "long" else entry - rr * 2, 2)

            # ── Quality score ─────────────────────────────────────────────────
            expansion = zone.atr_end / zone.atr_before if zone.atr_before > 0 else 1.0
            rr_ratio = abs(target - entry) / abs(entry - stop) if abs(entry - stop) > 0 else 0.0
            quality = round((expansion - 1.0) * 0.4 + min(rr_ratio / 3.0, 1.0) * 0.6, 3)

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
            ))

    return signals


def _find_first_retest(post_impulse: pd.DataFrame, zone, side: str) -> Optional[int]:
    """Return the index (within post_impulse) of the first retest bar."""
    for i, (_, row) in enumerate(post_impulse.iterrows()):
        if side == "long":
            if row["Low"] <= zone.zone_high and row["High"] >= zone.zone_low:
                return i
        else:
            if row["High"] >= zone.zone_low and row["Low"] <= zone.zone_high:
                return i
    return None
