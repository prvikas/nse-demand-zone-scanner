"""Standalone DB connection check + schema init.
Run locally:  python db_check.py
Run in CI:    called as a dedicated step before main.py
"""
import sys
import os

# Minimal env check before importing config
if not os.environ.get("DATABASE_URL"):
    print("[db_check] ERROR: DATABASE_URL is not set.", file=sys.stderr)
    print("  Set it in your .env file or as a GitHub Actions secret.", file=sys.stderr)
    sys.exit(1)

try:
    import psycopg2
except ImportError:
    print("[db_check] psycopg2 not installed. Run: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(1)

DATABASE_URL = os.environ["DATABASE_URL"]

print(f"[db_check] Connecting to database...")
try:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT version();")
    version = cur.fetchone()[0]
    print(f"[db_check] ✅ Connected! PostgreSQL version: {version}")
except Exception as e:
    print(f"[db_check] ❌ Connection FAILED: {e}", file=sys.stderr)
    print()
    print("  Common causes:", file=sys.stderr)
    print("  1. DATABASE_URL is wrong or incomplete.", file=sys.stderr)
    print("  2. Missing ?sslmode=require at the end of the URL.", file=sys.stderr)
    print("  3. Neon/Supabase project is paused (free tier auto-pauses).", file=sys.stderr)
    print("  4. IP not allowlisted (check your Neon/Supabase dashboard).", file=sys.stderr)
    print()
    print("  Expected format:", file=sys.stderr)
    print("  postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require", file=sys.stderr)
    sys.exit(1)

# Init schema
print("[db_check] Initialising schema (CREATE TABLE IF NOT EXISTS)...")
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
try:
    cur.execute(CREATE_TABLES_SQL)
    conn.commit()
    print("[db_check] ✅ Schema ready (signals + signal_events tables exist).")
except Exception as e:
    print(f"[db_check] ❌ Schema creation failed: {e}", file=sys.stderr)
    conn.rollback()
    sys.exit(1)
finally:
    cur.close()
    conn.close()

# Verify tables
print("[db_check] Verifying tables...")
try:
    conn2 = psycopg2.connect(DATABASE_URL)
    cur2 = conn2.cursor()
    cur2.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name;
    """)
    tables = [row[0] for row in cur2.fetchall()]
    print(f"[db_check] Tables in database: {tables}")
    for t in ["signals", "signal_events"]:
        if t in tables:
            print(f"[db_check] ✅ Table '{t}' exists.")
        else:
            print(f"[db_check] ❌ Table '{t}' NOT FOUND.", file=sys.stderr)
    cur2.close()
    conn2.close()
except Exception as e:
    print(f"[db_check] Could not verify tables: {e}", file=sys.stderr)

print("[db_check] Done. DB is ready for the scanner.")
