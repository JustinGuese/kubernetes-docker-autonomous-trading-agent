"""Tests for tools/binance_tool.py with mocked Binance client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tools.binance_tool import BinanceTool


# Minimal kline row as returned by Binance (12 elements)
def _fake_kline(open_time: int = 1700000000000) -> list:
    return [
        open_time,          # open_time (ms)
        "42000.00",         # open
        "42500.00",         # high
        "41800.00",         # low
        "42300.00",         # close
        "1500.50",          # volume
        open_time + 3600000 - 1,  # close_time
        "63000000.00",      # quote_volume
        12345,              # num_trades
        "750.25",           # taker_buy_base
        "31500000.00",      # taker_buy_quote
        "0",                # ignore
    ]


@pytest.fixture
def tool() -> BinanceTool:
    with patch("tools.binance_tool.Client") as MockClient:
        # Return 5 fake candles
        instance = MagicMock()
        instance.get_klines.return_value = [
            _fake_kline(1700000000000 + i * 3600000) for i in range(5)
        ]
        MockClient.return_value = instance
        t = BinanceTool()
        yield t


class TestGetKlines:
    def test_returns_dataframe(self, tool: BinanceTool) -> None:
        df = tool.get_klines(symbol="BTCUSDT")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 5

    def test_has_expected_columns(self, tool: BinanceTool) -> None:
        df = tool.get_klines()
        for col in ["open", "high", "low", "close", "volume", "open_time", "close_time"]:
            assert col in df.columns

    def test_ohlcv_are_float(self, tool: BinanceTool) -> None:
        df = tool.get_klines()
        for col in ["open", "high", "low", "close", "volume"]:
            assert df[col].dtype == float

    def test_timestamps_are_datetime(self, tool: BinanceTool) -> None:
        df = tool.get_klines()
        assert pd.api.types.is_datetime64_any_dtype(df["open_time"])
        assert pd.api.types.is_datetime64_any_dtype(df["close_time"])

    def test_values_are_correct(self, tool: BinanceTool) -> None:
        df = tool.get_klines()
        assert df.iloc[0]["open"] == 42000.0
        assert df.iloc[0]["close"] == 42300.0
        assert df.iloc[0]["high"] == 42500.0
