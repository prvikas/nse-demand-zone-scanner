"""Central configuration — reads from environment variables or .env file."""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Database ────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

# ── Data loader ──────────────────────────────────────────────────────────────
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "365"))
MAX_WORKERS   = int(os.environ.get("MAX_WORKERS",   "10"))

# ── Zone detection ───────────────────────────────────────────────────────────
IMPULSE_MIN_BARS     = int(os.environ.get("IMPULSE_MIN_BARS",     "3"))
ATR_EXPANSION_FACTOR = float(os.environ.get("ATR_EXPANSION_FACTOR", "1.2"))

# ── Strategy parameters ──────────────────────────────────────────────────────
ATR_PERIOD            = int(os.environ.get("ATR_PERIOD",            "14"))
PIVOT_DEPTH           = int(os.environ.get("PIVOT_DEPTH",           "5"))
STRUCTURE_SWING_COUNT = int(os.environ.get("STRUCTURE_SWING_COUNT", "3"))
STOP_ATR_BUFFER       = float(os.environ.get("STOP_ATR_BUFFER",     "0.5"))

# ── Email (optional — kept for local .env use, not used in Actions) ──────────
EMAIL_SMTP_HOST    = os.environ.get("EMAIL_SMTP_HOST",    "smtp.gmail.com")
EMAIL_SMTP_PORT    = int(os.environ.get("EMAIL_SMTP_PORT", "587"))
EMAIL_USER         = os.environ.get("EMAIL_USER",         "")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD", "")
EMAIL_TO           = os.environ.get("EMAIL_TO",           "")
