"""Tests for tools/sentiment_tool.py."""

from __future__ import annotations

from tools.sentiment_tool import SentimentTool


class TestSentimentTool:
    def test_get_sentiment_returns_entry_per_symbol(self) -> None:
        tool = SentimentTool()
        symbols = ["BTCUSDT", "SOLUSDT"]
        data = tool.get_sentiment(symbols)
        assert set(data.keys()) == {"BTCUSDT", "SOLUSDT"}

    def test_summarize_sentiment_includes_symbol(self) -> None:
        tool = SentimentTool()
        summary = tool.summarize_sentiment(["BTCUSDT"])
        assert "BTCUSDT" in summary

