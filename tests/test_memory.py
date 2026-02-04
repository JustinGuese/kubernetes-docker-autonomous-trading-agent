"""Tests for core/memory.py — MemoryStore load/save, daily reset, benchmark, trades."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from core.memory import MemoryStore


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    """Use a unique filename so we never read the project's agent_memory.json."""
    return MemoryStore(path=tmp_path / "test_memory_store.json")


class TestLoadSave:
    def test_missing_file_returns_default_state(self, store: MemoryStore) -> None:
        state = store.load()
        assert state["daily_spend_sol"] == 0.0
        assert state["trades"] == []
        assert state.get("daily_swap_usd") == 0.0

    def test_save_and_load_round_trip(self, store: MemoryStore) -> None:
        today = date.today().isoformat()
        state = store.load()
        state["daily_spend_sol"] = 0.5
        state["daily_spend_date"] = today
        state["daily_swap_date"] = today
        state["trades"] = [{"action_type": "analyze"}]
        store.save(state)
        loaded = store.load()
        assert loaded["daily_spend_sol"] == 0.5
        assert len(loaded["trades"]) == 1
        assert loaded["trades"][0]["action_type"] == "analyze"


class TestDailyReset:
    def test_stale_daily_spend_date_resets_counters(self, store: MemoryStore) -> None:
        state = store.load()
        state["daily_spend_sol"] = 0.3
        state["daily_spend_date"] = "2000-01-01"
        state["daily_swap_usd"] = 100.0
        state["daily_swap_date"] = "2000-01-01"
        store.save(state)
        loaded = store.load()
        assert loaded["daily_spend_sol"] == 0.0
        assert loaded["daily_swap_usd"] == 0.0
        assert loaded["daily_spend_date"] == loaded["daily_swap_date"]


class TestAddSpendAndSwap:
    def test_add_spend_increments_and_sets_date(self, store: MemoryStore) -> None:
        store.add_spend(0.1)
        state = store.load()
        assert state["daily_spend_sol"] == 0.1
        assert state["daily_spend_date"]

    def test_add_swap_usd_increments_and_sets_date(self, store: MemoryStore) -> None:
        store.add_swap_usd(50.0)
        state = store.load()
        assert state["daily_swap_usd"] == 50.0
        assert state["daily_swap_date"]


class TestEnsureBenchmarkInitialized:
    def test_first_call_sets_benchmark(self, store: MemoryStore) -> None:
        state = store.ensure_benchmark_initialized(
            portfolio_usd_now=100.0,
            prices_now={"SOL": 20.0},
        )
        assert state["benchmark"]["start_date"]
        assert state["benchmark"]["start_portfolio_usd"] == 100.0
        assert state["benchmark"]["start_prices"] == {"SOL": 20.0}

    def test_second_call_leaves_benchmark_unchanged(self, store: MemoryStore) -> None:
        store.ensure_benchmark_initialized(portfolio_usd_now=100.0, prices_now={"SOL": 20.0})
        state = store.ensure_benchmark_initialized(
            portfolio_usd_now=999.0,
            prices_now={"SOL": 99.0},
        )
        assert state["benchmark"]["start_portfolio_usd"] == 100.0
        assert state["benchmark"]["start_prices"] == {"SOL": 20.0}


class TestAppendTradeAndRecentTrades:
    def test_recent_trades_newest_first_and_respects_n(self, store: MemoryStore) -> None:
        for i in range(3):
            store.append_trade(
                plan={"action_type": f"action_{i}", "target": "", "params": {}, "confidence": 0.8, "reason": ""},
                result="ok",
            )
        recent = store.recent_trades(2)
        assert len(recent) == 2
        assert recent[0]["action_type"] == "action_2"
        assert recent[1]["action_type"] == "action_1"

    def test_append_trade_truncates_result_at_300_chars(self, store: MemoryStore) -> None:
        long_result = "x" * 500
        store.append_trade(
            plan={"action_type": "swap", "target": "", "params": {}, "confidence": 0.7, "reason": ""},
            result=long_result,
        )
        recent = store.recent_trades(1)
        assert len(recent[0]["result"]) == 300


class TestAppendReflection:
    def test_append_reflection_adds_entry_with_date_and_text(self, store: MemoryStore) -> None:
        store.append_reflection("thought")
        state = store.load()
        assert len(state["reflections"]) == 1
        assert state["reflections"][0]["text"] == "thought"
        assert state["reflections"][0]["date"]
