"""Entry point for the daily scan + lifecycle update + email report."""
import logging
import sys
import traceback
from datetime import date

_log_file = open("scanner.log", "w", encoding="utf-8")  # noqa

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.StreamHandler(_log_file),
    ],
    force=True,
)
log = logging.getLogger(__name__)
log.info("scanner.log opened - logging initialised")


def _get_swing_narrative(symbol, daily_df, weekly_df):
    """Return swing structure + projected trade levels for email."""
    from indicators import find_pivot_highs, find_pivot_lows, detect_structure, compute_atr
    from zones import find_zones, find_nearest_opposite_zone
    from config import STRUCTURE_SWING_COUNT, STOP_ATR_BUFFER

    daily_structure  = detect_structure(daily_df)
    weekly_structure = detect_structure(weekly_df)

    if daily_structure not in ("bullish", "bearish"):
        return None

    n = STRUCTURE_SWING_COUNT
    ph_mask = find_pivot_highs(daily_df)
    pl_mask = find_pivot_lows(daily_df)

    pivot_high_dates = daily_df.index[ph_mask].tolist()[-n:]
    pivot_low_dates  = daily_df.index[pl_mask].tolist()[-n:]

    pivot_highs = [(str(d.date()), round(float(daily_df.loc[d, "High"]), 2)) for d in pivot_high_dates]
    pivot_lows  = [(str(d.date()), round(float(daily_df.loc[d, "Low"]),  2)) for d in pivot_low_dates]

    current_price = round(float(daily_df["Close"].iloc[-1]), 2)
    atr           = compute_atr(daily_df)
    current_atr   = round(float(atr.iloc[-1]), 2)

    side  = "long" if daily_structure == "bullish" else "short"
    zones = find_zones(daily_df, side)

    nearest_zone   = None
    entry = stop = target = rr = None

    if zones and daily_structure == "bullish":
        below = [z for z in zones if z.zone_high < current_price]
        if below:
            nearest_zone = max(below, key=lambda z: z.zone_high)
    elif zones and daily_structure == "bearish":
        above = [z for z in zones if z.zone_low > current_price]
        if above:
            nearest_zone = min(above, key=lambda z: z.zone_low)

    if nearest_zone:
        if daily_structure == "bullish":
            entry  = round(nearest_zone.zone_high, 2)          # enter at top of demand zone
            stop   = round(nearest_zone.zone_low - STOP_ATR_BUFFER * current_atr, 2)
            raw_target = find_nearest_opposite_zone(daily_df, entry, "long")
            if raw_target is None:
                raw_target = round(entry + abs(entry - stop) * 2, 2)
            target = round(raw_target, 2)
        else:
            entry  = round(nearest_zone.zone_low, 2)           # enter at bottom of supply zone
            stop   = round(nearest_zone.zone_high + STOP_ATR_BUFFER * current_atr, 2)
            raw_target = find_nearest_opposite_zone(daily_df, entry, "short")
            if raw_target is None:
                raw_target = round(entry - abs(entry - stop) * 2, 2)
            target = round(raw_target, 2)

        risk   = abs(entry - stop)
        reward = abs(target - entry)
        rr     = round(reward / risk, 1) if risk > 0 else None

    return dict(
        symbol=symbol,
        daily_structure=daily_structure,
        weekly_structure=weekly_structure,
        current_price=current_price,
        pivot_highs=pivot_highs,
        pivot_lows=pivot_lows,
        zone_low=round(nearest_zone.zone_low,  2) if nearest_zone else None,
        zone_high=round(nearest_zone.zone_high, 2) if nearest_zone else None,
        entry=entry,
        stop=stop,
        target=target,
        rr=rr,
    )


def run():
    log.info("Importing project modules...")
    try:
        import repository as repo
        from universe import get_nifty500_symbols
        from data_loader import fetch_all
        from strategy import scan_symbol
        from lifecycle import update_open_signals
        from notifier import send_daily_report
        log.info("All modules imported OK")
    except RuntimeError as exc:
        log.error("Configuration error: %s", exc)
        sys.exit(1)
    except Exception as exc:
        log.error("Import failed: %s", exc)
        log.error(traceback.format_exc())
        sys.exit(1)

    today = date.today()
    log.info("=== NSE Scanner starting - %s ===", today)

    try:
        repo.init_schema()
        log.info("DB schema ready")
    except Exception as exc:
        log.error("DB schema init failed: %s", exc)
        log.error(traceback.format_exc())
        sys.exit(1)

    symbols = get_nifty500_symbols()
    log.info("%d symbols in universe", len(symbols))

    price_data = fetch_all(symbols)
    log.info("Price data fetched for %d / %d symbols", len(price_data), len(symbols))

    if not price_data:
        log.warning("No price data fetched - yfinance may be rate-limited.")
        sys.exit(1)

    update_open_signals(price_data)

    new_signal_ids = []
    scanned        = 0
    structure_data = []

    for symbol, daily_df in price_data.items():
        scanned += 1
        try:
            weekly_df = daily_df.resample("W-FRI").agg(
                {"Open": "first", "High": "max", "Low": "min",
                 "Close": "last", "Volume": "sum"}
            ).dropna()

            narrative = _get_swing_narrative(symbol, daily_df, weekly_df)
            if narrative:
                structure_data.append(narrative)

            signals = scan_symbol(symbol, daily_df, weekly_df, today)
        except Exception as exc:
            log.warning("scan_symbol failed for %s: %s", symbol, exc)
            continue

        for sig in signals:
            if repo.signal_already_exists(
                sig.symbol, sig.side, sig.zone_low, sig.zone_high
            ):
                log.debug("%s: duplicate signal skipped", symbol)
                continue
            try:
                sid = repo.insert_signal(sig)
                repo.insert_event(
                    signal_id=sid, event_date=today,
                    event_type="detected", old_status="",
                    new_status="open", price_snapshot=sig.entry_price,
                    notes="New setup detected by morning scan",
                )
                new_signal_ids.append(sid)
            except Exception as exc:
                log.warning("DB insert failed for %s: %s", symbol, exc)

    log.info("Scanned %d symbols | New signals inserted: %d", scanned, len(new_signal_ids))
    log.info("Structure narratives collected: %d", len(structure_data))

    try:
        new_signals      = repo.get_new_signals_today(today)
        resolved_signals = repo.get_today_resolved_signals(today)
        log.info("Email: %d new, %d resolved, %d structure",
                 len(new_signals), len(resolved_signals), len(structure_data))
        send_daily_report(new_signals, resolved_signals, today, structure_data)
        log.info("Issue report created")
    except Exception as exc:
        log.error("Report failed: %s", exc)
        log.error(traceback.format_exc())
        sys.exit(1)

    log.info("=== NSE Scanner complete ===")


if __name__ == "__main__":
    try:
        run()
    except SystemExit:
        _log_file.flush()
        raise
    except Exception as exc:
        log.exception("Unhandled exception: %s", exc)
        _log_file.flush()
        sys.exit(1)
    finally:
        _log_file.flush()
