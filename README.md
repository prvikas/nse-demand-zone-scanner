# NSE Demand / Supply Zone Scanner

A daily scanner for **Nifty 500** stocks that identifies high-quality supply/demand zone setups with ATR-confirmed impulses, multi-timeframe trend alignment, and full trade lifecycle tracking.

## Strategy Logic

| Step | Rule |
|---|---|
| Weekly trend | HH/HL for longs, LH/LL for shorts |
| Daily trend | Same as weekly (both must agree) |
| Impulse | ≥ 3 consecutive directional bars + ATR(14) at end > 1.2× ATR before |
| Zone | Body of the first impulse bar (open/close range) |
| Retest | First retest only |
| Confirmation | Next-day candle closes above prior high (long) or below prior low (short) |
| Invalidation | Body close beyond zone |
| Stop | Below zone low − 0.3×ATR (long) / Above zone high + 0.3×ATR (short) |
| Target | Nearest opposite supply/demand zone |

## Stack

| Part | Tool |
|---|---|
| Data | yfinance (free, Yahoo Finance) |
| Database | Neon / Supabase (free Postgres) |
| Scheduler | GitHub Actions (cron, Mon–Fri 09:30 IST) |
| Email | Gmail SMTP + App Password |

## Setup

### 1. Create the database

Create a free Postgres database at [Neon](https://neon.tech) or [Supabase](https://supabase.com).

Copy the connection string (format: `postgresql://user:pass@host/db?sslmode=require`).

Run the schema once locally:
```bash
pip install -r requirements.txt
export DATABASE_URL="your-connection-string"
python db_init.py
```

### 2. Configure GitHub Secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret name | Value |
|---|---|
| `DATABASE_URL` | Neon/Supabase connection string |
| `EMAIL_USER` | Your Gmail sender address |
| `EMAIL_APP_PASSWORD` | Gmail App Password (not your login password) |
| `EMAIL_TO` | Your recipient email address |

**How to create a Gmail App Password:**
1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Enable 2-Step Verification
3. Search for "App Passwords" and create one for "Mail"
4. Use the 16-character password as `EMAIL_APP_PASSWORD`

### 3. Test manually

Trigger the workflow from **Actions → NSE Daily Scanner → Run workflow**.

### 4. Automatic schedule

The workflow runs automatically **Monday–Friday at ~09:30 IST (04:00 UTC)**.

## Email Report Format

Every morning you receive:

### New Setups
| Symbol | Side | Recommended On | Entry | Stop | Target | R:R | Zone | Score |

### Updates on Open Setups
| Symbol | Side | Recommended On | Resolved On | Status | Reason |

Statuses: `open` → `target_hit` / `stop_hit` / `invalidated`

## Database Tables

### `signals`
Stores every detected setup with entry, stop, target, zone, and resolution.

### `signal_events`
Full audit log — every status change with date, price, and reason.

## Configuration

All parameters are configurable via environment variables or GitHub Secrets:

| Variable | Default | Description |
|---|---|---|
| `PIVOT_DEPTH` | 3 | Bars each side for pivot confirmation |
| `STRUCTURE_SWING_COUNT` | 3 | Min swings for trend confirmation |
| `IMPULSE_MIN_BARS` | 3 | Min consecutive directional bars |
| `ATR_EXPANSION_FACTOR` | 1.2 | ATR multiplier for impulse quality |
| `STOP_ATR_BUFFER` | 0.3 | ATR buffer beyond zone for stop |
| `MAX_OPEN_DAYS` | 20 | Days before signal expires |

## Disclaimer

This tool is for informational and research purposes only. It is not financial advice. Always verify signals before trading.
