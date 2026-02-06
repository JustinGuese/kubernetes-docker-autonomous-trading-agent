"""Tests for tools/swap_tool.py.

These tests mock HTTP calls so no real Jupiter API traffic is generated.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from solders.keypair import Keypair

from core.network_config import DEVNET_TOKENS, MAINNET_TOKENS, NetworkDetector, NetworkType
from tools.swap_tool import JupiterUltraSwap, JupiterV6Swap, MockSwap, SwapTool


class TestNetworkDetection:
    def test_detect_mainnet(self) -> None:
        assert (
            NetworkDetector.detect("https://api.mainnet-beta.solana.com")
            == NetworkType.MAINNET
        )

    def test_detect_devnet(self) -> None:
        assert (
            NetworkDetector.detect("https://api.devnet.solana.com")
            == NetworkType.DEVNET
        )

    def test_get_tokens_mainnet_and_devnet(self) -> None:
        assert MAINNET_TOKENS.usdc != ""
        assert DEVNET_TOKENS.usdc != ""
        assert DEVNET_TOKENS.wbtc is None


class TestSwapStrategies:
    @patch("tools.swap_tool.httpx.post")
    @patch("tools.swap_tool.httpx.get")
    def test_ultra_mainnet_happy_path(self, mock_get, mock_post) -> None:
        # Use a real keypair object; no RPC calls from the strategy itself.
        keypair = Keypair()
        rpc = MagicMock()

        # Build a minimal-but-valid empty transaction to satisfy from_bytes.
        import base64
        from solders.transaction import VersionedTransaction

        dummy_tx = VersionedTransaction.default()
        unsigned_b64 = base64.b64encode(bytes(dummy_tx)).decode("utf-8")

        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "swapTransaction": unsigned_b64,
            "requestId": "req-123",
        }

        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"signature": "sig-abc"}

        strat = JupiterUltraSwap(keypair, rpc, api_key="test-key")
        sig = strat.execute_swap(
            MAINNET_TOKENS.sol, MAINNET_TOKENS.usdc, amount_lamports=1_000_000_000, slippage_bps=50
        )
        assert sig == "sig-abc"

    @patch("tools.swap_tool.httpx.get")
    def test_ultra_mainnet_order_error_raises(self, mock_get) -> None:
        keypair = Keypair()
        rpc = MagicMock()

        mock_get.return_value.status_code = 500
        mock_get.return_value.text = "Internal Server Error"

        strat = JupiterUltraSwap(keypair, rpc, api_key="test-key")
        with pytest.raises(RuntimeError, match="Ultra order error 500"):
            strat.execute_swap(
                MAINNET_TOKENS.sol,
                MAINNET_TOKENS.usdc,
                amount_lamports=1_000_000_000,
                slippage_bps=50,
            )

    @patch("tools.swap_tool.httpx.post")
    @patch("tools.swap_tool.httpx.get")
    def test_devnet_v6_happy_path(self, mock_get, mock_post) -> None:
        keypair = Keypair()
        rpc = MagicMock()

        # Quote response
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"routePlan": [], "other": "fields"}

        # Swap response with a base64 tx
        import base64
        from solders.transaction import VersionedTransaction

        dummy_tx = VersionedTransaction.default()
        unsigned_b64 = base64.b64encode(bytes(dummy_tx)).decode("utf-8")
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"swapTransaction": unsigned_b64}

        # RPC send_raw_transaction returns an object with a .value attribute
        rpc.send_raw_transaction.return_value = MagicMock(value="devnet-sig")

        strat = JupiterV6Swap(keypair, rpc)
        sig = strat.execute_swap(
            DEVNET_TOKENS.sol,
            DEVNET_TOKENS.usdc,
            amount_lamports=1_000_000_000,
            slippage_bps=50,
        )
        assert sig == "devnet-sig"

    @patch("tools.swap_tool.httpx.get")
    def test_devnet_v6_no_pool_raises_clear_error(self, mock_get) -> None:
        keypair = Keypair()
        rpc = MagicMock()

        mock_get.return_value.status_code = 404
        mock_get.return_value.text = "Not Found"

        strat = JupiterV6Swap(keypair, rpc)
        with pytest.raises(RuntimeError, match="No liquidity pool"):
            strat.execute_swap(
                DEVNET_TOKENS.sol,
                DEVNET_TOKENS.usdc,
                amount_lamports=1_000_000_000,
                slippage_bps=50,
            )


class TestSwapToolWrapper:
    def test_swap_zero_lamports_raises(self) -> None:
        keypair = Keypair()
        tool = SwapTool(keypair, "https://api.devnet.solana.com")
        with pytest.raises(ValueError, match="amount_lamports must be positive"):
            tool.swap("SOL", "USDC", amount_lamports=0)

    @patch("tools.swap_tool.JupiterV6Swap.execute_swap")
    def test_devnet_falls_back_to_mock_on_no_pool(self, mock_exec) -> None:
        keypair = Keypair()
        tool = SwapTool(keypair, "https://api.devnet.solana.com")

        mock_exec.side_effect = RuntimeError("No liquidity pool on devnet")

        sig = tool.swap("SOL", "USDC", amount_lamports=1_000_000_000)
        assert sig.startswith("DEVNET-MOCK-SWAP-")

