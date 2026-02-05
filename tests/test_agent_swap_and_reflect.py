from __future__ import annotations

from typing import Dict

import pytest

from core.memory import MemoryStore
from core.policy_engine import PolicyEngine, PolicyViolation
from tools.position_tool import PositionTool


class _DummyWallet:
    def __init__(self, balances: Dict[str, float]) -> None:
        self._balances = balances

    def balance_token(self, symbol: str) -> float:
        return float(self._balances.get(symbol.upper(), 0.0))


class TestCheckSwapBalance:
    def test_insufficient_balance_raises(self) -> None:
        """PolicyEngine.check_swap_balance should reject when balance is too low."""
        from core.config import AppConfig, GitConfig, LLMConfig, MemoryConfig, PolicyConfig, SolanaConfig
        from core.memory import MemoryStore

        cfg = AppConfig(
            llm=LLMConfig(api_key="test"),
            solana=SolanaConfig(private_key="fake"),
            policy=PolicyConfig(),
            git=GitConfig(token="gh", repo="owner/repo"),
            memory=MemoryConfig(),
        )
        engine = PolicyEngine(cfg, MemoryStore())
        wallet = _DummyWallet({"USDC": 0.05})

        with pytest.raises(PolicyViolation, match="Insufficient USDC balance"):
            engine.check_swap_balance(wallet, "USDC", 0.1)

    def test_sufficient_balance_passes(self) -> None:
        from core.config import AppConfig, GitConfig, LLMConfig, MemoryConfig, PolicyConfig, SolanaConfig
        from core.memory import MemoryStore

        cfg = AppConfig(
            llm=LLMConfig(api_key="test"),
            solana=SolanaConfig(private_key="fake"),
            policy=PolicyConfig(),
            git=GitConfig(token="gh", repo="owner/repo"),
            memory=MemoryConfig(),
        )
        engine = PolicyEngine(cfg, MemoryStore())
        wallet = _DummyWallet({"USDC": 1.0})

        # Should not raise
        engine.check_swap_balance(wallet, "USDC", 0.1)


class TestDriftReconcileHelpers:
    def test_onchain_sync_does_not_overwrite_nonzero_positions(self, tmp_path) -> None:
        """Regression-style test to ensure sync_from_onchain preserves existing positions.

        This indirectly supports the drift reconciliation logic by confirming that
        the initial on-chain sync used at startup cannot clobber already-tracked
        SOL amounts when they are non-zero.
        """
        mem = MemoryStore(path=tmp_path / "mem.json")
        pos = PositionTool(mem)
        # Seed non-zero SOL position
        pos.update_position("SOL", 0.2, 5.0)

        class _Wallet:
            def __init__(self) -> None:
                self._balances = {"SOL": 0.5}

            def get_all_balances(self) -> Dict[str, float]:
                return dict(self._balances)

        wallet = _Wallet()
        pos.sync_from_onchain(wallet, {"SOL": 100.0})

        sol_pos = pos.get_position("SOL")
        assert sol_pos["amount"] == 0.2

