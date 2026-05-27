"""Entry point for the daily scan + lifecycle update + email report."""
import logging
from datetime import date

import repository as repo
from universe import get_nifty500_symbols
from data_loader import fetch_all, fetch_weekly
from strategy import scan_symbol
from lifecycle import update_open_signals
from notifier import send_daily_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
log = logging.getLogger(__name__)


def run():
    today = date.today()
    log.info("=== NSE Scanner starting — %s ===", today)

    # ── Ensure schema exists ──────────────────────────────────────────────────
    repo.init_schema()

    # ── Fetch universe ────────────────────────────────────────────────────────
    symbols = get_nifty500_symbols()
    log.info("%d symbols in universe", len(symbols))

    # ── Fetch market data ─────────────────────────────────────────────────────
    price_data = fetch_all(symbols)

    # ── Lifecycle: update open signals ────────────────────────────────────────
    update_open_signals(price_data)

    # ── Morning scan: find new confirmed setups ───────────────────────────────
    new_signal_ids = []
    for symbol, daily_df in price_data.items():
        weekly_df = daily_df.resample("W-FRI").agg(
            {"Open": "first", "High": "max", "Low": "min",
             "Close": "last", "Volume": "sum"}
        ).dropna()

        try:
            signals = scan_symbol(symbol, daily_df, weekly_df)
        except Exception as exc:
            log.warning("scan_symbol failed for %s: %s", symbol, exc)
            continue

        for sig in signals:
            if repo.signal_already_exists(
                sig.symbol, sig.side, sig.zone_low, sig.zone_high
            ):
                continue
            sid = repo.insert_signal(sig)
            repo.insert_event(
                signal_id=sid,
                event_date=today,
                event_type="detected",
                old_status="",
                new_status="open",
                price_snapshot=sig.entry_price,
                notes="New setup detected by morning scan",
            )
            new_signal_ids.append(sid)

    log.info("New signals inserted: %d", len(new_signal_ids))

    # ── Build report ──────────────────────────────────────────────────────────
    new_signals = repo.get_new_signals_today(today)
    resolved_signals = repo.get_today_resolved_signals(today)

    send_daily_report(new_signals, resolved_signals, today)
    log.info("=== NSE Scanner complete ===")


if __name__ == "__main__":
    run()
