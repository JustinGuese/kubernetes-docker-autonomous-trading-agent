"""File-based JSON state store with atomic writes and daily-spend reset."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

MEMORY_PATH = Path("agent_memory.json")

_DEFAULT_STATE: dict[str, Any] = {
    "daily_spend_sol": 0.0,
    "daily_spend_date": "",  # ISO date string; reset when stale
    "daily_swap_usd": 0.0,
    "daily_swap_date": "",
    "reflections": [],
    "trades": [],             # structured action log — see append_trade()
    # Portfolio-aware benchmark: compare total portfolio value vs a simple
    # SOL buy-and-hold from the same starting USD value. Fields populated lazily.
    "benchmark": {
        "start_date": "",
        "start_portfolio_usd": 0.0,
        "start_prices": {},
    },
    # Token positions and swap history are populated lazily.
    "positions": {},
    "swap_history": [],
}

# How many chars of action_result to persist per trade
_RESULT_TRUNCATE = 300


class MemoryStore:
    """Thin wrapper around a JSON file.  All reads go to disk — no in-process cache."""

    def __init__(self, path: Path = MEMORY_PATH):
        self.path = path

    # ── public API ────────────────────────────────────────────────

    def load(self) -> dict[str, Any]:
        """Read state from disk.  Returns fresh default if file is missing."""
        if not self.path.exists():
            return copy.deepcopy(_DEFAULT_STATE)
        with open(self.path) as fh:
            state = json.load(fh)
        # Auto-reset daily spend / swap when the date has changed
        today = date.today().isoformat()
        mutated = False
        if state.get("daily_spend_date") != today:
            state["daily_spend_sol"] = 0.0
            state["daily_spend_date"] = today
            mutated = True
        if state.get("daily_swap_date") != today:
            state["daily_swap_usd"] = 0.0
            state["daily_swap_date"] = today
            mutated = True
        if mutated:
            self.save(state)
        return state

    def save(self, state: dict[str, Any]) -> None:
        """Atomic write: write to temp file then rename."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(state, fh, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            os.unlink(tmp)
            raise

    # ── benchmark helpers ──────────────────────────────────────────

    def ensure_benchmark_initialized(
        self,
        portfolio_usd_now: float,
        prices_now: dict[str, float],
    ) -> dict[str, Any]:
        """Ensure benchmark is populated; return updated full state.

        On first call, records today's date, the current total portfolio USD
        value, and the current token prices as the reference point.
        Subsequent calls leave the benchmark fixed.
        """
        state = self.load()
        bench = state.get("benchmark") or {}
        if not bench.get("start_date"):
            bench = {
                "start_date": date.today().isoformat(),
                "start_portfolio_usd": float(portfolio_usd_now),
                "start_prices": {k: float(v) for k, v in prices_now.items()},
            }
            state["benchmark"] = bench
            self.save(state)
        return state

    def add_spend(self, amount_sol: float) -> None:
        """Increment daily spend (re-reads from disk first)."""
        state = self.load()
        state["daily_spend_sol"] = state.get("daily_spend_sol", 0.0) + amount_sol
        state["daily_spend_date"] = date.today().isoformat()
        self.save(state)

    def add_swap_usd(self, amount_usd: float) -> None:
        """Increment daily swap notional (re-reads from disk first)."""
        state = self.load()
        state["daily_swap_usd"] = state.get("daily_swap_usd", 0.0) + float(amount_usd)
        state["daily_swap_date"] = date.today().isoformat()
        self.save(state)

    def append_reflection(self, text: str) -> None:
        state = self.load()
        state.setdefault("reflections", []).append(
            {"date": date.today().isoformat(), "text": text}
        )
        self.save(state)

    # ── trade log ─────────────────────────────────────────────────

    def append_trade(self, plan: dict[str, Any], result: str) -> None:
        """Persist a full action record derived from the executed plan + outcome."""
        state = self.load()
        state.setdefault("trades", []).append({
            "date": date.today().isoformat(),
            "action_type": plan.get("action_type", "unknown"),
            "target": plan.get("target", ""),
            "params": plan.get("params", {}),
            "confidence": plan.get("confidence", 0.0),
            "reason": plan.get("reason", ""),
            "result": result[:_RESULT_TRUNCATE],
        })
        self.save(state)

    def recent_trades(self, n: int = 5) -> list[dict[str, Any]]:
        """Return the most recent *n* trade records (newest first)."""
        state = self.load()
        trades = state.get("trades", [])
        return list(reversed(trades[-n:]))
