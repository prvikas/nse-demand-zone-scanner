"""Check open signals against latest price and update stop/target status."""
import logging
from datetime import date
from typing import Dict
import pandas as pd

import repository as repo

log = logging.getLogger(__name__)


def update_open_signals(price_data: Dict[str, pd.DataFrame]):
    """For every open signal, check if stop or target was hit today."""
    open_signals = repo.get_open_signals()
    today = date.today()
    log.info("Checking %d open signals", len(open_signals))

    for sig in open_signals:
        symbol = sig["symbol"]
        df = price_data.get(symbol)
        if df is None or df.empty:
            continue

        latest = df.iloc[-1]
        high_today = float(latest["High"])
        low_today = float(latest["Low"])
        close_today = float(latest["Close"])

        stop = float(sig["stop_loss"])
        target = float(sig["target_price"]) if sig["target_price"] else None
        side = sig["side"]
        old_status = sig["status"]
        signal_id = sig["signal_id"]

        new_status = None
        reason = None
        price_snap = close_today

        if side == "long":
            # Check zone invalidation first
            zone_low = float(sig["zone_low"])
            if close_today < zone_low:
                new_status = "invalidated"
                reason = f"Body close {close_today} below zone low {zone_low}"
            elif low_today <= stop:
                new_status = "stop_hit"
                reason = f"Low {low_today} reached stop {stop}"
                price_snap = stop
            elif target and high_today >= target:
                new_status = "target_hit"
                reason = f"High {high_today} reached target {target}"
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
            elif target and low_today <= target:
                new_status = "target_hit"
                reason = f"Low {low_today} reached target {target}"
                price_snap = target

        if new_status:
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
            log.info("Signal %d (%s %s) → %s", signal_id, symbol, side, new_status)
        else:
            # Still open: log a daily check event
            repo.insert_event(
                signal_id=signal_id,
                event_date=today,
                event_type="daily_check",
                old_status=old_status,
                new_status=old_status,
                price_snapshot=close_today,
                notes="Still open",
            )
