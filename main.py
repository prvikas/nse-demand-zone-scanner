"""Entry point for the daily scan + lifecycle update + email report."""
import logging
import sys
import traceback
from datetime import date

# Open scanner.log FIRST - before any other imports
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
        from indicators import detect_structure
        from zones import find_zones
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
        log.warning("No price data fetched - yfinance may be rate-limited or NSE is down.")
        sys.exit(1)

    update_open_signals(price_data)

    new_signal_ids = []
    scanned = 0

    # Structure summary: collect top bullish/bearish stocks for email
    structure_summary = []   # list of dicts

    for symbol, daily_df in price_data.items():
        scanned += 1
        try:
            weekly_df = daily_df.resample("W-FRI").agg(
                {"Open": "first", "High": "max", "Low": "min",
                 "Close": "last", "Volume": "sum"}
            ).dropna()

            daily_structure  = detect_structure(daily_df)
            weekly_structure = detect_structure(weekly_df)

            # Collect structure data for email summary (top 20 per side)
            if daily_structure in ("bullish", "bearish"):
                demand_zones = find_zones(daily_df, "long") if daily_structure == "bullish" else []
                supply_zones = find_zones(daily_df, "short") if daily_structure == "bearish" else []
                nearest_zone = None
                current_price = round(float(daily_df["Close"].iloc[-1]), 2)

                if demand_zones:
                    # nearest demand zone below current price
                    below = [z for z in demand_zones if z.zone_high < current_price]
                    if below:
                        nearest_zone = max(below, key=lambda z: z.zone_high)
                elif supply_zones:
                    above = [z for z in supply_zones if z.zone_low > current_price]
                    if above:
                        nearest_zone = min(above, key=lambda z: z.zone_low)

                structure_summary.append(dict(
                    symbol=symbol,
                    daily_structure=daily_structure,
                    weekly_structure=weekly_structure,
                    current_price=current_price,
                    zone_low=round(nearest_zone.zone_low, 2) if nearest_zone else None,
                    zone_high=round(nearest_zone.zone_high, 2) if nearest_zone else None,
                ))

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
    log.info("Structure summary: %d stocks with clear structure", len(structure_summary))

    try:
        new_signals = repo.get_new_signals_today(today)
        resolved_signals = repo.get_today_resolved_signals(today)
        log.info("Email report: %d new signals, %d resolved", len(new_signals), len(resolved_signals))
        send_daily_report(new_signals, resolved_signals, today, structure_summary)
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
