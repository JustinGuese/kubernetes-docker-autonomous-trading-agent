"""File-based JSON state store with atomic writes and daily-spend reset."""

from __future__ import annotations

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
    "reflections": [],
    "trades": [],             # structured action log — see append_trade()
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
            return dict(_DEFAULT_STATE)
        with open(self.path) as fh:
            state = json.load(fh)
        # Auto-reset daily spend when the date has changed
        if state.get("daily_spend_date") != date.today().isoformat():
            state["daily_spend_sol"] = 0.0
            state["daily_spend_date"] = date.today().isoformat()
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

    def add_spend(self, amount_sol: float) -> None:
        """Increment daily spend (re-reads from disk first)."""
        state = self.load()
        state["daily_spend_sol"] = state.get("daily_spend_sol", 0.0) + amount_sol
        state["daily_spend_date"] = date.today().isoformat()
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
