"""Tests for tools/swap_tool.py.

These tests mock HTTP calls so no real Jupiter API traffic is generated.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from solders.keypair import Keypair

from tools.swap_tool import SwapTokens, SwapTool


class TestSwapTokens:
    def test_mint_for_symbol_basic(self) -> None:
        tokens = SwapTokens()
        assert tokens.mint_for_symbol("SOL") == tokens.sol_mint
        assert tokens.mint_for_symbol("USDC") == tokens.usdc_mint
        assert tokens.mint_for_symbol("WBTC") == tokens.wbtc_mint

        with pytest.raises(ValueError):
            tokens.mint_for_symbol("FOO")


class TestSwapTool:
    @patch("tools.swap_tool.httpx.post")
    @patch("tools.swap_tool.httpx.get")
    @patch("tools.swap_tool.SolanaClient.get_latest_blockhash")
    def test_swap_happy_path(
        self,
        mock_blockhash,
        mock_get,
        mock_post,
    ) -> None:
        # Fake keypair (random; not used against real cluster)
        keypair = Keypair()
        tool = SwapTool(keypair, "https://api.devnet.solana.com")

        # Mock Ultra /order response
        import base64
        from solders.transaction import VersionedTransaction

        # Build a minimal-but-valid empty transaction to satisfy from_bytes.
        dummy_tx = VersionedTransaction.default()
        unsigned_b64 = base64.b64encode(bytes(dummy_tx)).decode("utf-8")
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "swapTransaction": unsigned_b64,
            "requestId": "req-123",
        }

        # Mock latest blockhash
        class _BH:
            blockhash = "dummy"

        mock_blockhash.return_value.value = _BH()

        # Mock Ultra /execute response
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"signature": "sig-abc"}

        sig = tool.swap("SOL", "USDC", amount_lamports=1_000_000_000, slippage_bps=50)
        assert sig == "sig-abc"

    @patch("tools.swap_tool.httpx.get")
    def test_swap_order_api_error_raises(self, mock_get: object) -> None:
        keypair = Keypair()
        tool = SwapTool(keypair, "https://api.devnet.solana.com")
        mock_get.return_value.status_code = 500
        mock_get.return_value.text = "Internal Server Error"
        with pytest.raises(RuntimeError, match="Ultra order error 500"):
            tool.swap("SOL", "USDC", amount_lamports=1_000_000_000)

    @patch("tools.swap_tool.httpx.get")
    def test_swap_order_missing_swap_transaction_raises(self, mock_get: object) -> None:
        keypair = Keypair()
        tool = SwapTool(keypair, "https://api.devnet.solana.com")
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"requestId": "req-1"}
        with pytest.raises(RuntimeError, match="no transaction"):
            tool.swap("SOL", "USDC", amount_lamports=1_000_000_000)

    def test_swap_invalid_symbol_raises(self) -> None:
        keypair = Keypair()
        tool = SwapTool(keypair, "https://api.devnet.solana.com")
        with pytest.raises(ValueError, match="Unsupported token symbol"):
            tool.swap("INVALID", "USDC", amount_lamports=1_000_000_000)

    def test_swap_zero_lamports_raises(self) -> None:
        keypair = Keypair()
        tool = SwapTool(keypair, "https://api.devnet.solana.com")
        with pytest.raises(ValueError, match="amount_lamports must be positive"):
            tool.swap("SOL", "USDC", amount_lamports=0)

