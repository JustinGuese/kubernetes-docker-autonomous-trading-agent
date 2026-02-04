"""Fetch OHLCV kline data from Binance (public endpoints, no API key needed)."""

from __future__ import annotations

import logging

import pandas as pd
from binance import Client

logger = logging.getLogger(__name__)

# Column names that Binance returns in the kline array
_KLINE_COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "num_trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]

# Numeric columns to cast to float
_FLOAT_COLS = ["open", "high", "low", "close", "volume",
               "quote_volume", "taker_buy_base", "taker_buy_quote"]


class BinanceTool:
    def __init__(self) -> None:
        self.client = Client()  # public endpoints only

    def get_klines(
        self,
        symbol: str = "BTCUSDT",
        interval: str = Client.KLINE_INTERVAL_1HOUR,
        limit: int = 100,
    ) -> pd.DataFrame:
        """Return a DataFrame of the last *limit* candles for *symbol*.

        Columns: open_time, open, high, low, close, volume, close_time, …
        open_time / close_time are converted to datetime (UTC).
        OHLCV columns are float.
        """
        logger.info("get_klines symbol=%s interval=%s limit=%d", symbol, interval, limit)
        raw = self.client.get_klines(symbol=symbol, interval=interval, limit=limit)
        logger.info("  → %d raw candles returned", len(raw))
        df = pd.DataFrame(raw, columns=_KLINE_COLS)

        # Timestamps are milliseconds → datetime
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)

        # Cast numeric columns
        for col in _FLOAT_COLS:
            df[col] = df[col].astype(float)

        return df
