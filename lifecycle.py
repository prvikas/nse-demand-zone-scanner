"""Check open signals against latest price and update stop/target status."""
import logging
from datetime import date
from typing import Dict
import pandas as pd

import repository as repo

log = logging.getLogger(__name__)


def _is_market_day(df: pd.DataFrame, today: date) -> bool:
    """Return True only if the latest candle in df is from today."""
    if df is None or df.empty:
        return False
    latest_date = df.index[-1].date()
    return latest_date == today


def update_open_signals(price_data: Dict[str, pd.DataFrame]):
    """For every open signal, check if stop or target was hit today.

    Idempotency rules:
    - Skip entirely if the latest candle for a symbol is not from today
      (market closed, weekend, holiday, or stale yfinance data).
    - Skip signals that are already resolved (status != 'open').
    - Never insert a duplicate daily_check or resolution event for the same
      (signal_id, event_date, event_type) tuple.
    """
    open_signals = repo.get_open_signals()
    today = date.today()
    log.info("Checking %d open signals", len(open_signals))

    for sig in open_signals:
        symbol = sig["symbol"]
        df = price_data.get(symbol)

        # Guard 1: only process if today's candle is available
        if not _is_market_day(df, today):
            log.debug("%s: latest candle not from today — skipping lifecycle", symbol)
            continue

        latest = df.iloc[-1]
        high_today  = float(latest["High"])
        low_today   = float(latest["Low"])
        close_today = float(latest["Close"])

        stop   = float(sig["stop_loss"])
        target = float(sig["target_price"]) if sig["target_price"] else None
        side   = sig["side"]
        old_status = sig["status"]
        signal_id  = sig["signal_id"]

        new_status = None
        reason     = None
        price_snap = close_today

        if side == "long":
            zone_low = float(sig["zone_low"])
            if close_today < zone_low:
                new_status = "invalidated"
                reason = f"Body close {close_today} below zone low {zone_low}"
            elif low_today <= stop:
                new_status = "stop_hit"
                reason = f"Low {low_today} reached stop {stop}"
                price_snap = stop
            elif target and close_today >= target:
                # Guard 2: use close (not wick) to confirm target
                new_status = "target_hit"
                reason = f"Close {close_today} reached target {target}"
                price_snap = target
        else:
            zone_high = float(sig["zone_high"])
            if close_today > zone_high:
                new_status = "invalidated"
                reason = f"Body close {close_today} above zone high {zone_high}"
            elif high_today >= stop:
                new_status = "stop_hit"
                reason = f"High {high_today} reached stop {stop}"
                price_snap = stop
            elif target and close_today <= target:
                # Guard 2: use close (not wick) to confirm target
                new_status = "target_hit"
                reason = f"Close {close_today} reached target {target}"
                price_snap = target

        if new_status:
            # Guard 3: skip if this resolution event already exists today
            if repo.event_exists_today(signal_id, today, new_status):
                log.debug("Signal %d already has %s event today — skipping", signal_id, new_status)
                continue
            repo.update_signal_status(signal_id, new_status, today, reason)
            repo.insert_event(
                signal_id=signal_id,
                event_date=today,
                event_type=new_status,
                old_status=old_status,
                new_status=new_status,
                price_snapshot=price_snap,
                notes=reason,
            )
            log.info("Signal %d (%s %s) -> %s", signal_id, symbol, side, new_status)
        else:
            # Guard 3: skip if daily_check already logged today
            if repo.event_exists_today(signal_id, today, "daily_check"):
                log.debug("Signal %d daily_check already logged today — skipping", signal_id)
                continue
            repo.insert_event(
                signal_id=signal_id,
                event_date=today,
                event_type="daily_check",
                old_status=old_status,
                new_status=old_status,
                price_snapshot=close_today,
                notes="Still open",
            )
