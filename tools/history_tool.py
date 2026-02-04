"""Read and format the agent's own past actions for LLM consumption."""

from __future__ import annotations

import logging
from typing import Any

from core.memory import MemoryStore

logger = logging.getLogger(__name__)


class HistoryTool:
    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory

    # ── public ────────────────────────────────────────────────────

    def recent(self, n: int = 5) -> str:
        """Return a formatted summary of the last *n* trades (newest first)."""
        trades = self.memory.recent_trades(n)
        if not trades:
            return "[history] no past actions recorded yet"

        logger.info("history: returning %d trade(s)", len(trades))
        return "\n\n".join(_format_trade(i, t) for i, t in enumerate(trades, 1))


# ── helpers ───────────────────────────────────────────────────────────────────


def _format_trade(idx: int, t: dict[str, Any]) -> str:
    lines = [
        f"--- past action #{idx} ({t.get('date', '?')}) ---",
        f"  action   : {t.get('action_type', '?')}",
        f"  target   : {t.get('target', '')}",
        f"  confidence: {t.get('confidence', '?')}",
        f"  why      : {t.get('reason', '(none)')}",
        f"  result   : {t.get('result', '(none)')}",
    ]
    params = t.get("params", {})
    if params:
        lines.insert(3, f"  params   : {params}")
    return "\n".join(lines)
