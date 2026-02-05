"""Position tracking helper built on top of MemoryStore.

This tool keeps an internal, agent-centric view of the portfolio (amounts and
cost basis per token). It does *not* query on-chain balances directly; instead
it assumes that swaps and wallet actions are the only way balances change and
that those are recorded via this tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict

from core.memory import MemoryStore


@dataclass(frozen=True)
class PositionSnapshot:
    amount: float
    cost_basis_usd: float
    last_updated: str


class PositionTool:
    """Lightweight wrapper around MemoryStore for portfolio operations.

    Notes on semantics:
    - `amount` is tracked per token symbol.
    - `cost_basis_usd` is an approximate USD cost basis, often derived from SOL
      prices; it is meant for rough PnL intuition rather than exact accounting.
    - For swaps, the agent typically uses a SOL-equivalent notional
      (`amount_sol`) and maps that into `usd_value` using SOLUSDT.
    """

    def __init__(self, memory: MemoryStore) -> None:
        self._memory = memory

    # ── internal helpers ───────────────────────────────────────────

    def _load_positions(self) -> Dict[str, Dict[str, float | str]]:
        state = self._memory.load()
        return state.setdefault("positions", {})

    # ── public API ─────────────────────────────────────────────────

    def update_position(self, token: str, amount_delta: float, usd_value: float) -> None:
        """Update the position for *token* by amount_delta.

        - For positive amount_delta (a buy), adjust cost basis by adding usd_value.
        - For negative amount_delta (a sell), reduce amount; cost_basis_usd is
          reduced proportionally but never goes negative.
        """
        state = self._memory.load()
        positions = state.setdefault("positions", {})
        pos = positions.get(token.upper()) or {
            "amount": 0.0,
            "cost_basis_usd": 0.0,
            "last_updated": "",
        }
        amount = float(pos.get("amount", 0.0)) + float(amount_delta)
        cost_basis = float(pos.get("cost_basis_usd", 0.0))

        if amount_delta > 0 and usd_value > 0:
            cost_basis += float(usd_value)
        elif amount_delta < 0 and amount > 0 and cost_basis > 0:
            # Reduce cost basis proportionally to the fraction of position sold
            sold_fraction = min(1.0, abs(amount_delta) / (amount + abs(amount_delta)))
            cost_basis *= 1.0 - sold_fraction
        if amount <= 0:
            amount = 0.0
            cost_basis = 0.0

        positions[token.upper()] = {
            "amount": amount,
            "cost_basis_usd": cost_basis,
            "last_updated": date.today().isoformat(),
        }
        state["positions"] = positions
        self._memory.save(state)

    def get_position(self, token: str) -> Dict[str, float | str]:
        """Return the current tracked position snapshot for *token*.

        If no position exists yet, a zeroed snapshot is returned.
        """
        state = self._memory.load()
        positions = state.get("positions", {})
        return positions.get(
            token.upper(),
            {
                "amount": 0.0,
                "cost_basis_usd": 0.0,
                "last_updated": "",
            },
        )

    def get_portfolio_value_usd(self, prices: Dict[str, float]) -> float:
        """Return the total portfolio value in USD given a symbol->price mapping."""
        state = self._memory.load()
        positions = state.get("positions", {})
        total = 0.0
        for symbol, pos in positions.items():
            amount = float(pos.get("amount", 0.0))
            price = float(prices.get(symbol.upper(), 0.0))
            total += amount * price
        return total

    def append_swap(self, record: Dict) -> None:
        """Persist a swap record (input/output, prices, tx sig).

        Rotation and pruning of the underlying swap_history list is delegated
        to MemoryStore.save(), which applies global memory limits.
        """
        state = self._memory.load()
        history = state.setdefault("swap_history", [])
        history.append(record)
        state["swap_history"] = history
        self._memory.save(state)

    def portfolio_summary(self, prices: Dict[str, float]) -> str:
        """Return a compact human-readable portfolio summary for the LLM."""
        state = self._memory.load()
        positions = state.get("positions", {})
        if not positions:
            return "no tracked positions yet"

        lines = []
        total_usd = 0.0
        for symbol, pos in positions.items():
            amount = float(pos.get("amount", 0.0))
            price = float(prices.get(symbol.upper(), 0.0))
            value = amount * price
            total_usd += value
            lines.append(f"{symbol}: {amount:.6f} (~${value:.2f})")
        return f"total ≈ ${total_usd:.2f}; " + ", ".join(lines)

    def sync_from_onchain(self, wallet_tool, prices: Dict[str, float]) -> None:
        """Initialise missing positions from on-chain balances.

        For each token with a non-zero on-chain balance and no existing tracked
        position, create a new position entry with:
          - amount set to the on-chain balance
          - cost_basis_usd approximated as amount * price (if price available)
          - source flag set to "onchain_sync"
        """
        state = self._memory.load()
        positions = state.setdefault("positions", {})

        try:
            balances: Dict[str, float] = wallet_tool.get_all_balances()
        except Exception:
            # If on-chain balance fetch fails, do not modify existing positions.
            return

        changed = False
        for symbol, balance in balances.items():
            if balance <= 0:
                continue
            key = symbol.upper()
            existing = positions.get(key)
            existing_amount = float(existing.get("amount", 0.0)) if existing else 0.0
            if existing and existing_amount > 0:
                continue

            price = float(prices.get(key, 0.0))
            usd_value = balance * price if price > 0 else 0.0
            positions[key] = {
                "amount": float(balance),
                "cost_basis_usd": float(usd_value),
                "last_updated": date.today().isoformat(),
                "source": "onchain_sync",
            }
            changed = True

        if changed:
            state["positions"] = positions
            self._memory.save(state)

