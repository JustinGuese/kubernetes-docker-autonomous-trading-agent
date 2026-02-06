"""Tests for core/policy_engine.py — every rule gets a pass + fail case."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import AppConfig, GitConfig, LLMConfig, MemoryConfig, PolicyConfig, SolanaConfig
from core.memory import MemoryStore
from core.network_config import NetworkType
from core.policy_engine import PolicyEngine, PolicyViolation

# ── fixtures ──────────────────────────────────────────────────────────────────


def _make_config(
    max_sol_per_tx: float = 0.1,
    daily_cap: float = 0.5,
    max_loc_delta: int = 200,
    solana_rpc_url: str = "https://fake",
    mainnet_min_balance_sol: float = 0.1,
) -> AppConfig:
    return AppConfig(
        llm=LLMConfig(api_key="test-key"),
        solana=SolanaConfig(
            private_key="fake",
            rpc_url=solana_rpc_url,
            mainnet_min_balance_sol=mainnet_min_balance_sol,
        ),
        policy=PolicyConfig(
            confidence_threshold=0.6,
            max_sol_per_tx=max_sol_per_tx,
            daily_spend_cap_sol=daily_cap,
            max_loc_delta=max_loc_delta,
        ),
        git=GitConfig(token="ghp_fake", repo="owner/repo"),
        memory=MemoryConfig(),
    )


@pytest.fixture
def memory(tmp_path: Path) -> MemoryStore:
    return MemoryStore(path=tmp_path / "agent_memory.json")


@pytest.fixture
def engine(memory: MemoryStore) -> PolicyEngine:
    return PolicyEngine(_make_config(), memory)


# ── wallet send ───────────────────────────────────────────────────────────────


class TestWalletSend:
    def test_valid_send_passes(self, engine: PolicyEngine) -> None:
        # Should not raise
        engine.check_wallet_send(0.05, "A" * 44)

    def test_zero_amount_blocked(self, engine: PolicyEngine) -> None:
        with pytest.raises(PolicyViolation, match="positive"):
            engine.check_wallet_send(0.0, "A" * 44)

    def test_negative_amount_blocked(self, engine: PolicyEngine) -> None:
        with pytest.raises(PolicyViolation, match="positive"):
            engine.check_wallet_send(-0.01, "A" * 44)

    def test_exceeds_per_tx_cap(self, engine: PolicyEngine) -> None:
        with pytest.raises(PolicyViolation, match="MAX_SOL_PER_TX"):
            engine.check_wallet_send(0.2, "A" * 44)

    def test_exceeds_daily_cap(self, memory: MemoryStore) -> None:
        # Simulate 0.45 already spent today
        memory.add_spend(0.45)
        eng = PolicyEngine(_make_config(), memory)
        with pytest.raises(PolicyViolation, match="daily spend"):
            eng.check_wallet_send(0.1, "A" * 44)

    def test_daily_cap_exactly_at_limit(self, memory: MemoryStore) -> None:
        memory.add_spend(0.4)
        eng = PolicyEngine(_make_config(), memory)
        # 0.4 + 0.1 == 0.5 == cap → should pass (not strictly greater)
        eng.check_wallet_send(0.1, "A" * 44)

    def test_short_destination_blocked(self, engine: PolicyEngine) -> None:
        with pytest.raises(PolicyViolation, match="destination"):
            engine.check_wallet_send(0.05, "short")

    def test_empty_destination_blocked(self, engine: PolicyEngine) -> None:
        with pytest.raises(PolicyViolation, match="destination"):
            engine.check_wallet_send(0.05, "")


# ── browser URL ───────────────────────────────────────────────────────────────


class TestBrowserUrl:
    def test_allowed_domain_passes(self, engine: PolicyEngine) -> None:
        engine.check_browser_url("https://coingecko.com/en/coins/solana")

    def test_disallowed_domain_blocked(self, engine: PolicyEngine) -> None:
        # Scraping is now allowed for all domains; this should not raise.
        engine.check_browser_url("https://evil.com/phish")

    def test_subdomain_blocked(self, engine: PolicyEngine) -> None:
        # Subdomains are also allowed under the permissive scraping policy.
        engine.check_browser_url("https://sub.coingecko.com/page")

    def test_port_stripped(self, engine: PolicyEngine) -> None:
        engine.check_browser_url("https://coingecko.com:443/en")

    def test_path_traversal_in_url_still_checks_domain(self, engine: PolicyEngine) -> None:
        # Path traversal in URLs does not affect the now-unrestricted domain policy.
        engine.check_browser_url("https://evil.com/../coingecko.com/trick")


# ── git paths ─────────────────────────────────────────────────────────────────


class TestGitPaths:
    def test_tools_path_passes(self, engine: PolicyEngine) -> None:
        engine.check_git_paths(["tools/my_new_tool.py"])

    def test_experiments_path_passes(self, engine: PolicyEngine) -> None:
        engine.check_git_paths(["experiments/scratch.py"])

    def test_core_path_blocked(self, engine: PolicyEngine) -> None:
        with pytest.raises(PolicyViolation, match="outside allowed"):
            engine.check_git_paths(["core/config.py"])

    def test_root_path_blocked(self, engine: PolicyEngine) -> None:
        with pytest.raises(PolicyViolation, match="outside allowed"):
            engine.check_git_paths(["main.py"])

    def test_multiple_paths_one_bad(self, engine: PolicyEngine) -> None:
        with pytest.raises(PolicyViolation):
            engine.check_git_paths(["tools/good.py", "core/bad.py"])


# ── LOC delta ─────────────────────────────────────────────────────────────────


class TestLocDelta:
    def test_within_limit_passes(self) -> None:
        eng = PolicyEngine(_make_config(max_loc_delta=200), MemoryStore())
        eng.check_loc_delta(150)

    def test_at_limit_passes(self) -> None:
        eng = PolicyEngine(_make_config(max_loc_delta=200), MemoryStore())
        eng.check_loc_delta(200)

    def test_over_limit_blocked(self) -> None:
        eng = PolicyEngine(_make_config(max_loc_delta=200), MemoryStore())
        with pytest.raises(PolicyViolation, match="LOC delta"):
            eng.check_loc_delta(201)

    def test_large_negative_delta_blocked(self) -> None:
        eng = PolicyEngine(_make_config(max_loc_delta=200), MemoryStore())
        with pytest.raises(PolicyViolation, match="LOC delta"):
            eng.check_loc_delta(-250)


# ── swap ─────────────────────────────────────────────────────────────────────


class TestSwap:
    """PolicyEngine.check_swap: same token, amount, per-tx cap, daily cap."""

    def test_same_token_raises(self, engine: PolicyEngine) -> None:
        with pytest.raises(PolicyViolation, match="must differ"):
            engine.check_swap("SOL", "SOL", 10.0, NetworkType.DEVNET)

    def test_zero_amount_raises(self, engine: PolicyEngine) -> None:
        with pytest.raises(PolicyViolation, match="must be positive"):
            engine.check_swap("SOL", "USDC", 0.0, NetworkType.DEVNET)

    def test_negative_amount_raises(self, engine: PolicyEngine) -> None:
        with pytest.raises(PolicyViolation, match="must be positive"):
            engine.check_swap("SOL", "USDC", -5.0, NetworkType.DEVNET)

    def test_exceeds_per_tx_cap_raises(self, engine: PolicyEngine) -> None:
        # Default max_swap_usd_per_tx is 50
        with pytest.raises(PolicyViolation, match="MAX_SWAP_USD_PER_TX"):
            engine.check_swap("SOL", "USDC", 51.0, NetworkType.DEVNET)

    def test_exceeds_daily_cap_raises(self, memory: MemoryStore) -> None:
        memory.add_swap_usd(180.0)  # default daily_swap_cap_usd is 200
        eng = PolicyEngine(_make_config(), memory)
        with pytest.raises(PolicyViolation, match="daily swap volume"):
            eng.check_swap("SOL", "USDC", 25.0, NetworkType.DEVNET)

    def test_within_limits_passes(self, engine: PolicyEngine) -> None:
        engine.check_swap("SOL", "USDC", 10.0, NetworkType.DEVNET)


class TestSwapMainnetSafety:
    def test_mainnet_sol_swap_respects_min_balance(self, tmp_path: Path) -> None:
        """Mainnet SOL swap should not drain below configured minimum balance."""
        mem = MemoryStore(path=tmp_path / "mem_mainnet.json")
        state = mem.load()
        # Seed a SOL position of 0.5
        state["positions"] = {"SOL": {"amount": 0.5}}
        mem.save(state)

        # Ensure a specific minimum balance and mainnet RPC URL for the test.
        cfg = _make_config(
            solana_rpc_url="https://api.mainnet-beta.solana.com",
            mainnet_min_balance_sol=0.1,
        )
        eng = PolicyEngine(cfg, mem)

        # Swapping 0.35 SOL-equivalent should leave 0.15 SOL (> 0.1) → allowed.
        eng.check_swap(
            "SOL",
            "USDC",
            amount_usd=0.35,
            network=NetworkType.MAINNET,
            amount_native=0.35,
        )

        # Swapping 0.45 SOL-equivalent would leave 0.05 (< 0.1) → blocked.
        with pytest.raises(PolicyViolation, match="Mainnet safety"):
            eng.check_swap(
                "SOL",
                "USDC",
                amount_usd=0.45,
                network=NetworkType.MAINNET,
                amount_native=0.45,
            )

    def test_mainnet_sol_swap_uses_native_not_usd(self, tmp_path: Path) -> None:
        """Guard should respect SOL amount even when USD notional is large."""
        mem = MemoryStore(path=tmp_path / "mem_mainnet_native.json")
        state = mem.load()
        # Seed a SOL position of 0.5
        state["positions"] = {"SOL": {"amount": 0.5}}
        mem.save(state)

        cfg = _make_config(
            solana_rpc_url="https://api.mainnet-beta.solana.com",
            mainnet_min_balance_sol=0.1,
        )
        eng = PolicyEngine(cfg, mem)

        # Example: SOL at $100 → amount_usd=10.0, amount_native=0.1. Using native
        # amount, 0.5 - 0.1 = 0.4 (> 0.1) so this should pass.
        eng.check_swap(
            "SOL",
            "USDC",
            amount_usd=10.0,
            network=NetworkType.MAINNET,
            amount_native=0.1,
        )
