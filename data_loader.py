"""Download daily OHLCV data using yfinance.

yfinance >= 0.2.x returns MultiLevel columns when downloading a single ticker
with group_by default. We always flatten to simple Open/High/Low/Close/Volume.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional

import pandas as pd
import yfinance as yf

from config import LOOKBACK_DAYS, MAX_WORKERS

log = logging.getLogger(__name__)


def _flatten_columns(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Flatten MultiIndex columns returned by newer yfinance versions."""
    if isinstance(df.columns, pd.MultiIndex):
        # columns look like ('Close', 'RELIANCE.NS') — keep only level 0
        df.columns = df.columns.get_level_values(0)
    # Normalise column names
    df.columns = [c.strip().title() for c in df.columns]
    return df


def fetch_daily(symbol: str, lookback_days: int = LOOKBACK_DAYS) -> Optional[pd.DataFrame]:
    """Return a cleaned daily OHLCV DataFrame for one symbol."""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=f"{lookback_days}d", interval="1d", auto_adjust=True)
        if df is None or df.empty:
            log.debug("No data returned for %s", symbol)
            return None

        df = _flatten_columns(df, symbol)

        # Keep only OHLCV columns that exist
        wanted = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        if len(wanted) < 4:
            log.debug("Missing OHLCV columns for %s: got %s", symbol, df.columns.tolist())
            return None

        df = df[wanted].copy()
        df.index = pd.to_datetime(df.index)
        # Strip timezone so downstream code doesn't need tz-awareness
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df.sort_index(inplace=True)
        df.dropna(inplace=True)

        if len(df) < 60:
            log.debug("Insufficient rows (%d) for %s", len(df), symbol)
            return None

        return df
    except Exception as exc:
        log.debug("Failed to fetch %s: %s", symbol, exc)
        return None


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
