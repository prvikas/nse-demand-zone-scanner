"""Entry point for the daily scan + lifecycle update + email report."""
import logging
import sys
import traceback
from datetime import date

# -------------------------------------------------------------------
# Open scanner.log FIRST - before any other imports
# This ensures even config/import crashes are captured in the file
# -------------------------------------------------------------------
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
        log.error("Configuration error:\n%s", exc)
        sys.exit(1)
    except Exception as exc:
        log.error("Import failed: %s", exc)
        log.error(traceback.format_exc())
        sys.exit(1)

    today = date.today()
    log.info("=== NSE Scanner starting - %s ===", today)

    # DB schema
    try:
        repo.init_schema()
        log.info("DB schema ready")
    except Exception as exc:
        log.error("DB schema init failed: %s", exc)
        log.error(traceback.format_exc())
        sys.exit(1)

    # Universe
    symbols = get_nifty500_symbols()
    log.info("%d symbols in universe", len(symbols))

    # Price data
    price_data = fetch_all(symbols)
    log.info("Price data fetched for %d / %d symbols", len(price_data), len(symbols))

    if not price_data:
        log.warning("No price data fetched - yfinance may be rate-limited or NSE is down.")
        sys.exit(1)

    # Lifecycle: update open signals
    update_open_signals(price_data)

    # Scan for new signals
    new_signal_ids = []
    for symbol, daily_df in price_data.items():
        try:
            weekly_df = daily_df.resample("W-FRI").agg(
                {"Open": "first", "High": "max", "Low": "min",
                 "Close": "last", "Volume": "sum"}
            ).dropna()
            signals = scan_symbol(symbol, daily_df, weekly_df)
        except Exception as exc:
            log.warning("scan_symbol failed for %s: %s", symbol, exc)
            continue

        for sig in signals:
            if repo.signal_already_exists(
                sig.symbol, sig.side, sig.zone_low, sig.zone_high
            ):
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

    log.info("New signals inserted: %d", len(new_signal_ids))

    # Email report
    try:
        new_signals = repo.get_new_signals_today(today)
        resolved_signals = repo.get_today_resolved_signals(today)
        send_daily_report(new_signals, resolved_signals, today)
        log.info("Email report sent")
    except Exception as exc:
        log.error("Email failed: %s", exc)
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
