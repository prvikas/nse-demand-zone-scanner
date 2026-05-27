"""Central configuration — all parameters are read from environment variables.
Store secrets in GitHub Actions secrets or a local .env file (never commit .env).
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.environ["DATABASE_URL"]          # postgres://user:pass@host/db?sslmode=require

# ── Email ─────────────────────────────────────────────────────────────────────
EMAIL_SMTP_HOST: str = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT: int = int(os.getenv("EMAIL_SMTP_PORT", "587"))
EMAIL_USER: str = os.environ["EMAIL_USER"]              # sender gmail address
EMAIL_APP_PASSWORD: str = os.environ["EMAIL_APP_PASSWORD"]  # Gmail App Password
EMAIL_TO: str = os.environ["EMAIL_TO"]                  # recipient address

# ── Universe ──────────────────────────────────────────────────────────────────
INDEX_TICKER: str = os.getenv("INDEX_TICKER", "^CNX500")  # Yahoo Finance symbol for Nifty 500
NSE_SUFFIX: str = ".NS"                                  # Yahoo Finance suffix for NSE stocks

# ── Strategy parameters (all configurable) ────────────────────────────────────
# Market structure
PIVOT_DEPTH: int = int(os.getenv("PIVOT_DEPTH", "3"))    # bars on each side to confirm HH/HL pivot
STRUCTURE_SWING_COUNT: int = int(os.getenv("STRUCTURE_SWING_COUNT", "3"))  # min swings to confirm trend

# Impulse
IMPULSE_MIN_BARS: int = int(os.getenv("IMPULSE_MIN_BARS", "3"))  # min consecutive directional bars
ATR_PERIOD: int = int(os.getenv("ATR_PERIOD", "14"))
ATR_EXPANSION_FACTOR: float = float(os.getenv("ATR_EXPANSION_FACTOR", "1.2"))

# Data
LOOKBACK_DAYS: int = int(os.getenv("LOOKBACK_DAYS", "365"))   # history to fetch per symbol
WEEKLY_STRUCTURE_BARS: int = int(os.getenv("WEEKLY_STRUCTURE_BARS", "52"))  # weeks of weekly data

# Execution
MAX_WORKERS: int = int(os.getenv("MAX_WORKERS", "8"))    # parallel symbol fetch threads
STOP_ATR_BUFFER: float = float(os.getenv("STOP_ATR_BUFFER", "0.3"))  # stop = zone_low - buffer * ATR

# Signal expiry
MAX_OPEN_DAYS: int = int(os.getenv("MAX_OPEN_DAYS", "20"))  # expire signal after N bars
