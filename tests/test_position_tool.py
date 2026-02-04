"""Tests for tools/position_tool.py."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.memory import MemoryStore
from tools.position_tool import PositionTool


def _default_state() -> dict[str, Any]:
    return {
        "positions": {},
        "trades": [],
        "reflections": [],
        "daily_spend_sol": 0.0,
        "daily_spend_date": "",
        "daily_swap_usd": 0.0,
        "daily_swap_date": "",
        "benchmark": {"start_date": "", "start_portfolio_usd": 0.0, "start_prices": {}},
        "swap_history": [],
    }


class _InMemoryStore:
    """Minimal store that never touches disk; used for isolated position tests."""

    def __init__(self) -> None:
        self._state = _default_state()

    def load(self) -> dict[str, Any]:
        return dict(self._state)

    def save(self, state: dict[str, Any]) -> None:
        self._state = dict(state)


def test_update_and_value(tmp_path: Path) -> None:
    memory = MemoryStore(path=tmp_path / "agent_memory.json")
    tool = PositionTool(memory)

    # Buy 1 SOL at $100
    tool.update_position("SOL", amount_delta=1.0, usd_value=100.0)
    prices = {"SOL": 120.0}
    value = tool.get_portfolio_value_usd(prices)
    assert value == 120.0

    # Sell 0.5 SOL at $120 (approximate)
    tool.update_position("SOL", amount_delta=-0.5, usd_value=60.0)
    summary = tool.portfolio_summary(prices)
    assert "SOL" in summary


def test_multiple_tokens_portfolio_value_and_summary() -> None:
    memory = _InMemoryStore()
    tool = PositionTool(memory)  # type: ignore[arg-type]
    tool.update_position("SOL", amount_delta=1.0, usd_value=100.0)
    tool.update_position("USDC", amount_delta=50.0, usd_value=50.0)
    prices = {"SOL": 120.0, "USDC": 1.0}
    value = tool.get_portfolio_value_usd(prices)
    assert value == 170.0
    summary = tool.portfolio_summary(prices)
    assert "SOL" in summary
    assert "USDC" in summary
    assert "170" in summary


def test_empty_portfolio_no_crash() -> None:
    memory = _InMemoryStore()
    tool = PositionTool(memory)  # type: ignore[arg-type]
    value = tool.get_portfolio_value_usd({"SOL": 100.0})
    assert value == 0.0
    summary = tool.portfolio_summary({"SOL": 100.0})
    assert summary == "no tracked positions yet"

