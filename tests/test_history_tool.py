"""Tests for tools/history_tool.py — HistoryTool.recent() and formatting."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.memory import MemoryStore
from tools.history_tool import HistoryTool


@pytest.fixture
def history_tool(tmp_path: Path) -> HistoryTool:
    memory = MemoryStore(path=tmp_path / "memory.json")
    return HistoryTool(memory)


class TestRecent:
    def test_empty_memory_returns_no_past_actions_message(
        self, history_tool: HistoryTool
    ) -> None:
        assert history_tool.recent(5) == "[history] no past actions recorded yet"

    def test_recent_returns_formatted_trades_with_action_types_and_dates(
        self, history_tool: HistoryTool
    ) -> None:
        memory = history_tool.memory
        memory.append_trade(
            plan={
                "action_type": "swap",
                "target": "SOL",
                "params": {},
                "confidence": 0.8,
                "reason": "momentum",
            },
            result="sig123",
        )
        memory.append_trade(
            plan={
                "action_type": "analyze",
                "target": "",
                "params": {},
                "confidence": 0.6,
                "reason": "",
            },
            result="ok",
        )
        text = history_tool.recent(2)
        assert "swap" in text
        assert "analyze" in text
        assert "past action #1" in text
        assert "past action #2" in text

    def test_recent_includes_params_when_present(
        self, history_tool: HistoryTool
    ) -> None:
        history_tool.memory.append_trade(
            plan={
                "action_type": "swap",
                "target": "SOL",
                "params": {"from_token": "USDC", "to_token": "SOL"},
                "confidence": 0.7,
                "reason": "",
            },
            result="done",
        )
        text = history_tool.recent(1)
        assert "params" in text
        assert "USDC" in text
        assert "SOL" in text
