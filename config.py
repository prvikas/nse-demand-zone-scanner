"""Central configuration - all parameters are read from environment variables.
Store secrets in GitHub Actions secrets or a local .env file (never commit .env).
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    """Return env var value or raise RuntimeError (never sys.exit - let caller handle it)."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set.\n"
            f"  For GitHub Actions: Settings -> Secrets and variables -> Actions -> New secret\n"
            f"  For local use: add '{name}=...' to your .env file"
        )
    return value


# -- Database ----------------------------------------------------------------
DATABASE_URL: str = _require("DATABASE_URL")

# -- Email -------------------------------------------------------------------
EMAIL_SMTP_HOST: str = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT: int = int(os.getenv("EMAIL_SMTP_PORT", "587"))
EMAIL_USER: str = _require("EMAIL_USER")
EMAIL_APP_PASSWORD: str = _require("EMAIL_APP_PASSWORD")
EMAIL_TO: str = _require("EMAIL_TO")

# -- Universe ----------------------------------------------------------------
INDEX_TICKER: str = os.getenv("INDEX_TICKER", "^CNX500")
NSE_SUFFIX: str = ".NS"

# -- Strategy parameters -----------------------------------------------------
PIVOT_DEPTH: int = int(os.getenv("PIVOT_DEPTH", "3"))
STRUCTURE_SWING_COUNT: int = int(os.getenv("STRUCTURE_SWING_COUNT", "3"))
IMPULSE_MIN_BARS: int = int(os.getenv("IMPULSE_MIN_BARS", "3"))
ATR_PERIOD: int = int(os.getenv("ATR_PERIOD", "14"))
ATR_EXPANSION_FACTOR: float = float(os.getenv("ATR_EXPANSION_FACTOR", "1.2"))
LOOKBACK_DAYS: int = int(os.getenv("LOOKBACK_DAYS", "365"))
WEEKLY_STRUCTURE_BARS: int = int(os.getenv("WEEKLY_STRUCTURE_BARS", "52"))
MAX_WORKERS: int = int(os.getenv("MAX_WORKERS", "8"))
STOP_ATR_BUFFER: float = float(os.getenv("STOP_ATR_BUFFER", "0.3"))
MAX_OPEN_DAYS: int = int(os.getenv("MAX_OPEN_DAYS", "20"))
