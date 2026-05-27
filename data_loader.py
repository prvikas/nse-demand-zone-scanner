"""Download daily OHLCV data using yfinance."""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional

import pandas as pd
import yfinance as yf

from config import LOOKBACK_DAYS, MAX_WORKERS

log = logging.getLogger(__name__)


def fetch_daily(symbol: str, lookback_days: int = LOOKBACK_DAYS) -> Optional[pd.DataFrame]:
    """Return a cleaned daily OHLCV DataFrame for one symbol."""
    try:
        df = yf.download(
            symbol,
            period=f"{lookback_days}d",
            interval="1d",
            auto_adjust=True,
            progress=False,
        )
        if df is None or df.empty or len(df) < 60:
            log.debug("Insufficient data for %s", symbol)
            return None
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.index = pd.to_datetime(df.index)
        df.sort_index(inplace=True)
        df.dropna(inplace=True)
        return df
    except Exception as exc:
        log.debug("Failed to fetch %s: %s", symbol, exc)
        return None


def fetch_weekly(symbol: str) -> Optional[pd.DataFrame]:
    """Return weekly OHLCV derived from daily data."""
    daily = fetch_daily(symbol, lookback_days=730)
    if daily is None:
        return None
    weekly = daily.resample("W-FRI").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    ).dropna()
    return weekly


def fetch_all(symbols: list, lookback_days: int = LOOKBACK_DAYS) -> Dict[str, pd.DataFrame]:
    """Fetch daily data for all symbols in parallel."""
    results: Dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_daily, s, lookback_days): s for s in symbols}
        for fut in as_completed(futures):
            sym = futures[fut]
            df = fut.result()
            if df is not None:
                results[sym] = df
    log.info("Fetched data for %d / %d symbols", len(results), len(symbols))
    return results
