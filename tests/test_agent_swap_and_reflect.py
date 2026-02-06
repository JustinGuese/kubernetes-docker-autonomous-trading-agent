from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.config import AppConfig, GitConfig, LLMConfig, MemoryConfig, PolicyConfig, SolanaConfig
from core.memory import MemoryStore
from core.network_config import NetworkType
from core.policy_engine import PolicyEngine
from tools.position_tool import PositionTool


def _make_config_for_agent() -> AppConfig:
    return AppConfig(
        llm=LLMConfig(api_key="test"),
        solana=SolanaConfig(private_key="fake", rpc_url="https://api.mainnet-beta.solana.com"),
        policy=PolicyConfig(),
        git=GitConfig(token="gh", repo="owner/repo"),
        memory=MemoryConfig(),
    )


@patch("core.agent.NetworkDetector.detect")
def test_mainnet_swap_appends_mainnet_transaction(mock_detect, tmp_path) -> None:
    """Successful non-mock mainnet swaps should append to mainnet_transactions."""
    mock_detect.return_value = NetworkType.MAINNET

    from core.agent import build_graph  # imported late to pick up patched detector

    mem = MemoryStore(path=tmp_path / "mem.json")
    cfg = _make_config_for_agent()
    policy = PolicyEngine(cfg, mem)

    # Seed a SOL position so mainnet safety check passes
    state = mem.load()
    state["positions"] = {"SOL": {"amount": 1.0}}
    mem.save(state)

    # Pre-populate observations price so the agent can compute amount_usd
    state = mem.load()
    state["last_observations_prices"] = ["[SOLUSDT] 100.0"]
    mem.save(state)

    # Patch swap_tool.swap to return a non-mock signature
    with patch("core.agent.SwapTool.swap", return_value="real-mainnet-sig"):
        graph = build_graph(cfg, mem, policy, dry_run=False)

        # Craft a simple state that will cause the agent to execute a swap action
        # directly by providing a fixed plan.
        from core.agent import AgentState  # type: ignore

        initial: AgentState = {
            "observations": "",
            "plan": {
                "action_type": "swap",
                "target": "",
                "params": {
                    "from_token": "SOL",
                    "to_token": "USDC",
                    "amount_sol": 0.2,
                    "slippage_bps": 50,
                },
                "confidence": 1.0,
                "reason": "test mainnet swap logging",
            },
            "action_result": "",
            "reflection": "",
            "done": False,
            "step": 0,
            "last_action_type": None,
        }

        final_state = graph.invoke(initial)
        assert final_state["done"] is True

    logged = mem.load().get("mainnet_transactions", [])
    assert len(logged) == 1
    entry = logged[0]
    assert entry["type"] == "swap"
    assert entry["details"]["signature"] == "real-mainnet-sig"


@patch("core.agent.WalletTool.balance_token")
def test_swap_from_zero_balance_token_is_skipped(mock_balance_token, tmp_path) -> None:
    """Swaps from a zero-balance token should be skipped with a clear message."""
    mock_balance_token.return_value = 0.0

    from core.agent import AgentState, build_graph  # type: ignore

    mem = MemoryStore(path=tmp_path / "mem_zero.json")
    cfg = _make_config_for_agent()
    policy = PolicyEngine(cfg, mem)
    graph = build_graph(cfg, mem, policy, dry_run=False)

    initial: AgentState = {
        "observations": "",
        "plan": {
            "action_type": "swap",
            "target": "",
            "params": {
                "from_token": "USDC",
                "to_token": "SOL",
                "amount_sol": 0.05,
                "slippage_bps": 50,
            },
            "confidence": 1.0,
            "reason": "test zero-balance skip",
        },
        "action_result": "",
        "reflection": "",
        "done": False,
        "step": 0,
        "last_action_type": None,
    }

    final_state = graph.invoke(initial)
    assert final_state["done"] is True
    assert "Swap skipped: 0 USDC balance" in final_state["action_result"]

