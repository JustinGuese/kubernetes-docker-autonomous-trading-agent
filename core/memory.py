"""File-based JSON state store with atomic writes and daily-spend reset."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from core.config import MemoryConfig

# Default location for on-disk JSON state.
# In containerized deployments we mount a PVC at /app/memory so this resolves
# to /app/memory/agent_memory.json instead of a bare file in the working dir.
MEMORY_PATH = Path("memory/agent_memory.json")

_DEFAULT_STATE: dict[str, Any] = {
    "daily_spend_sol": 0.0,
    "daily_spend_date": "",  # ISO date string; reset when stale
    "daily_swap_usd": 0.0,
    "daily_swap_date": "",
    "reflections": [],
    "trades": [],             # structured action log — see append_trade()
    "trade_summaries": [],    # statistical summaries of pruned trades
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
    "last_observations": "",
    "last_observations_prices": [],
}

# How many chars of action_result to persist per trade
_RESULT_TRUNCATE = 300


class MemoryStore:
    """Thin wrapper around a JSON file.  All reads go to disk — no in-process cache."""

    def __init__(self, path: Path = MEMORY_PATH, config: MemoryConfig | None = None):
        self.path = path
        self._config = config or MemoryConfig()

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
        """Apply rotation limits and atomically write to disk."""
        state = self._summarize_and_rotate(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(state, fh, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            os.unlink(tmp)
            raise

    # ── rotation / summarisation ─────────────────────────────────────

    def _summarize_and_rotate(self, state: dict[str, Any]) -> dict[str, Any]:
        """Generate summary stats from pruned entries, then trim arrays."""
        limits = {
            "reflections": self._config.max_reflections,
            "trades": self._config.max_trades,
            "swap_history": self._config.max_swap_history,
        }

        for key, limit in limits.items():
            arr = state.get(key, [])
            if not isinstance(arr, list) or limit <= 0:
                continue
            if len(arr) > limit:
                pruned = arr[:-limit]  # Entries being removed
                kept = arr[-limit:]    # Entries to keep

                # Generate summary of pruned trade entries
                if key == "trades" and pruned:
                    summary = self._summarize_trades(pruned)
                    summaries = state.setdefault("trade_summaries", [])
                    if isinstance(summaries, list):
                        summaries.append(summary)
                    else:
                        state["trade_summaries"] = [summary]

                state[key] = kept
        return state

    def _summarize_trades(self, trades: list[dict[str, Any]]) -> dict[str, Any]:
        """Generate statistical summary of trades being pruned."""
        action_counts: dict[str, int] = {}
        successes = 0
        failures = 0

        for t in trades:
            action = str(t.get("action_type", "unknown"))
            action_counts[action] = action_counts.get(action, 0) + 1
            result = str(t.get("result", ""))
            if "failed" in result.lower() or "blocked" in result.lower():
                failures += 1
            else:
                successes += 1

        period = "unknown"
        if trades:
            first = trades[0]
            last = trades[-1]
            period = f"{first.get('date', '?')} to {last.get('date', '?')}"

        total = len(trades)
        return {
            "period": period,
            "total": total,
            "actions": action_counts,
            "success_rate": successes / total if total else 0.0,
        }

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
        params = plan.get("params", {}) or {}
        # For extend_code, don't store full code - just metadata
        if plan.get("action_type") == "extend_code":
            code_str = str(params.get("code", ""))
            params = {
                "commit_message": params.get("commit_message", ""),
                "code_lines": len(code_str.splitlines()) if code_str else 0,
            }

        state.setdefault("trades", []).append({
            "date": date.today().isoformat(),
            "action_type": plan.get("action_type", "unknown"),
            "target": plan.get("target", ""),
            "params": params,
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

    # ── observation compression ─────────────────────────────────────

    def set_observations_compressed(self, observations: str) -> None:
        """Store only price lines from observations, not full scrape."""
        if not self._config.compress_observations:
            state = self.load()
            state["last_observations"] = observations
            self.save(state)
            return

        prices: list[str] = []
        for line in str(observations).splitlines():
            # Extract compact close values from TA summaries like:
            # [SOLUSDT] close=90.19, [BTCUSDT] close=70283.23
            if "] close=" in line:
                symbol_part = line.split("]", 1)[0] + "]"
                try:
                    price_part = line.split("close=")[1].split()[0]
                except Exception:
                    continue
                prices.append(f"{symbol_part} {price_part}")

        state = self.load()
        state["last_observations_prices"] = prices
        # Optionally keep a short stub instead of the full blob.
        state["last_observations"] = ""
        self.save(state)
