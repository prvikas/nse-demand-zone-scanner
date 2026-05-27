"""Fetch and return the Nifty 500 constituent symbols."""
import io
import logging
from typing import List

import pandas as pd
import requests

log = logging.getLogger(__name__)

NIFTY500_URL = (
    "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
)


def get_nifty500_symbols() -> List[str]:
    """Return Yahoo Finance tickers for Nifty 500 constituents.
    Falls back to a cached list if NSE is unreachable.
    """
    try:
        resp = requests.get(NIFTY500_URL, timeout=30,
                            headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        # NSE CSV has a column 'Symbol'
        symbols = df["Symbol"].dropna().str.strip().tolist()
        log.info("Fetched %d Nifty 500 symbols from NSE", len(symbols))
        return [s + ".NS" for s in symbols]
    except Exception as exc:
        log.warning("Could not fetch Nifty 500 list: %s — using fallback", exc)
        return _fallback_symbols()


def _fallback_symbols() -> List[str]:
    """A small hardcoded fallback so the scanner doesn't crash if NSE is down."""
    # Top 20 Nifty 50 names as a safety net
    tickers = [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
        "HINDUNILVR", "HDFC", "SBIN", "BAJFINANCE", "BHARTIARTL",
        "KOTAKBANK", "LT", "ASIANPAINT", "AXISBANK", "MARUTI",
        "SUNPHARMA", "ULTRACEMCO", "TITAN", "WIPRO", "ONGC",
    ]
    return [t + ".NS" for t in tickers]
