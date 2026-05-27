"""Database access layer — all SQL in one place."""
import logging
from datetime import date
from typing import List, Optional

import psycopg2
import psycopg2.extras

from config import DATABASE_URL

log = logging.getLogger(__name__)


def _conn():
    return psycopg2.connect(DATABASE_URL)


def _f(v) -> Optional[float]:
    """Cast numpy/pandas scalar to plain Python float (psycopg2 safe)."""
    return float(v) if v is not None else None


# ── Schema ────────────────────────────────────────────────────────────────────

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS signals (
    signal_id       SERIAL PRIMARY KEY,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    scan_date       DATE NOT NULL,
    confirmation_date DATE NOT NULL,
    entry_price     NUMERIC NOT NULL,
    stop_loss       NUMERIC NOT NULL,
    target_price    NUMERIC,
    zone_low        NUMERIC NOT NULL,
    zone_high       NUMERIC NOT NULL,
    weekly_structure TEXT,
    daily_structure  TEXT,
    atr_before      NUMERIC,
    atr_end         NUMERIC,
    atr_expansion   NUMERIC,
    confirmation_close NUMERIC,
    confirmation_prev_high NUMERIC,
    quality_score   NUMERIC,
    bars_since_confirmation INT DEFAULT 0,
    retest_number   INT DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'open',
    resolved_at     DATE,
    resolution_reason TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS signal_events (
    event_id        SERIAL PRIMARY KEY,
    signal_id       INT REFERENCES signals(signal_id),
    event_date      DATE NOT NULL,
    event_type      TEXT NOT NULL,
    old_status      TEXT,
    new_status      TEXT,
    price_snapshot  NUMERIC,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
"""


def init_schema():
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLES_SQL)
            # Add new columns if upgrading from older schema
            for col, defn in [
                ("bars_since_confirmation", "INT DEFAULT 0"),
                ("retest_number", "INT DEFAULT 1"),
            ]:
                cur.execute(f"""
                    DO $$ BEGIN
                        ALTER TABLE signals ADD COLUMN {col} {defn};
                    EXCEPTION WHEN duplicate_column THEN NULL;
                    END $$;
                """)
        conn.commit()
    log.info("Schema initialised")


# ── Writes ────────────────────────────────────────────────────────────────────

def insert_signal(sig) -> int:
    sql = """
        INSERT INTO signals
            (symbol, side, scan_date, confirmation_date, entry_price, stop_loss,
             target_price, zone_low, zone_high, weekly_structure, daily_structure,
             atr_before, atr_end, atr_expansion, confirmation_close,
             confirmation_prev_high, quality_score,
             bars_since_confirmation, retest_number)
        VALUES
            (%(symbol)s, %(side)s, %(scan_date)s, %(confirmation_date)s,
             %(entry_price)s, %(stop_loss)s, %(target_price)s, %(zone_low)s,
             %(zone_high)s, %(weekly_structure)s, %(daily_structure)s,
             %(atr_before)s, %(atr_end)s, %(atr_expansion)s,
             %(confirmation_close)s, %(confirmation_prev_high)s, %(quality_score)s,
             %(bars_since_confirmation)s, %(retest_number)s)
        RETURNING signal_id
    """
    params = dict(
        symbol=str(sig.symbol),
        side=str(sig.side),
        scan_date=sig.scan_date,
        confirmation_date=sig.confirmation_date,
        entry_price=_f(sig.entry_price),
        stop_loss=_f(sig.stop_loss),
        target_price=_f(sig.target_price),
        zone_low=_f(sig.zone_low),
        zone_high=_f(sig.zone_high),
        weekly_structure=str(sig.weekly_structure),
        daily_structure=str(sig.daily_structure),
        atr_before=_f(sig.atr_before),
        atr_end=_f(sig.atr_end),
        atr_expansion=_f(sig.atr_expansion),
        confirmation_close=_f(sig.confirmation_close),
        confirmation_prev_high=_f(sig.confirmation_prev_high),
        quality_score=_f(sig.quality_score),
        bars_since_confirmation=int(sig.bars_since_confirmation),
        retest_number=int(sig.retest_number),
    )
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            signal_id = cur.fetchone()[0]
        conn.commit()
    return signal_id


def update_signal_status(signal_id: int, new_status: str, resolved_at: date, reason: str):
    sql = """
        UPDATE signals
        SET status = %(status)s, resolved_at = %(resolved_at)s, resolution_reason = %(reason)s
        WHERE signal_id = %(signal_id)s
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, dict(status=new_status, resolved_at=resolved_at,
                                  reason=reason, signal_id=signal_id))
        conn.commit()


def insert_event(signal_id: int, event_date: date, event_type: str,
                 old_status: str, new_status: str,
                 price_snapshot: Optional[float] = None, notes: str = ""):
    sql = """
        INSERT INTO signal_events
            (signal_id, event_date, event_type, old_status, new_status, price_snapshot, notes)
        VALUES
            (%(signal_id)s, %(event_date)s, %(event_type)s, %(old_status)s,
             %(new_status)s, %(price_snapshot)s, %(notes)s)
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, dict(
                signal_id=signal_id, event_date=event_date,
                event_type=event_type, old_status=old_status,
                new_status=new_status, price_snapshot=_f(price_snapshot),
                notes=notes,
            ))
        conn.commit()


# ── Reads ─────────────────────────────────────────────────────────────────────

def get_open_signals() -> List[dict]:
    sql = "SELECT * FROM signals WHERE status = 'open' ORDER BY scan_date"
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]


def get_today_resolved_signals(today: date) -> List[dict]:
    sql = "SELECT * FROM signals WHERE resolved_at = %(today)s ORDER BY symbol"
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, dict(today=today))
            return [dict(r) for r in cur.fetchall()]


def get_new_signals_today(today: date) -> List[dict]:
    sql = "SELECT * FROM signals WHERE scan_date = %(today)s ORDER BY quality_score DESC"
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, dict(today=today))
            return [dict(r) for r in cur.fetchall()]


def signal_already_exists(symbol: str, side: str, zone_low: float, zone_high: float) -> bool:
    """Prevent duplicate signals for the same zone."""
    sql = """
        SELECT 1 FROM signals
        WHERE symbol = %(symbol)s
          AND side = %(side)s
          AND zone_low = %(zone_low)s
          AND zone_high = %(zone_high)s
          AND status = 'open'
        LIMIT 1
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, dict(
                symbol=str(symbol),
                side=str(side),
                zone_low=_f(zone_low),
                zone_high=_f(zone_high),
            ))
            return cur.fetchone() is not None
