"""Tests for tools/ta_tool.py — enrichment and summary formatting."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tools.ta_tool import TATool


def _make_ohlcv(n: int = 200) -> pd.DataFrame:
    """Synthesise n rows of OHLCV data (random walk close, realistic OHLV)."""
    rng = np.random.default_rng(42)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0, 2, n)
    low = close - rng.uniform(0, 2, n)
    open_ = close + rng.normal(0, 0.5, n)
    volume = rng.uniform(1000, 50000, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


@pytest.fixture
def enriched() -> pd.DataFrame:
    df = _make_ohlcv(200)
    return TATool.enrich(df)


class TestEnrich:
    def test_adds_columns(self, enriched: pd.DataFrame) -> None:
        # Should have way more columns than the original 5
        assert len(enriched.columns) > 20

    def test_rsi_present(self, enriched: pd.DataFrame) -> None:
        assert "momentum_rsi" in enriched.columns

    def test_macd_present(self, enriched: pd.DataFrame) -> None:
        assert "trend_macd" in enriched.columns
        assert "trend_macd_signal" in enriched.columns

    def test_bollinger_present(self, enriched: pd.DataFrame) -> None:
        assert "volatility_bbh" in enriched.columns
        assert "volatility_bbl" in enriched.columns

    def test_sma_present(self, enriched: pd.DataFrame) -> None:
        assert "trend_sma_fast" in enriched.columns
        assert "trend_sma_slow" in enriched.columns

    def test_no_nans_after_fillna(self, enriched: pd.DataFrame) -> None:
        # fillna=True in enrich; last row should have no NaNs
        assert enriched.iloc[-1].isna().sum() == 0


class TestSummarize:
    def test_contains_symbol(self, enriched: pd.DataFrame) -> None:
        summary = TATool.summarize(enriched, symbol="BTCUSDT")
        assert "BTCUSDT" in summary

    def test_contains_key_indicators(self, enriched: pd.DataFrame) -> None:
        summary = TATool.summarize(enriched, symbol="ETHUSDT")
        for label in ["RSI", "MACD", "SMA20", "BB_upper", "OBV"]:
            assert label in summary

    def test_empty_df_returns_no_data(self) -> None:
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        summary = TATool.summarize(empty, symbol="SOLUSDT")
        assert "no data" in summary


class TestCorrelationHelpers:
    def test_btc_dominance_insufficient_data(self) -> None:
        msg = TATool.compute_btc_dominance(pd.DataFrame(), {})
        assert "BTC dominance: insufficient data" in msg

    def test_summarize_correlations_insufficient_data(self) -> None:
        msg = TATool.summarize_correlations({})
        assert "SOL/BTC: insufficient data" in msg
