"""Tests for tools/onchain_tool.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tools.onchain_tool import OnchainConfig, OnchainTool


class TestOnchainTool:
    @patch("tools.onchain_tool.SolanaClient")
    def test_large_transfers_no_addresses_returns_empty(self, mock_client_cls: MagicMock) -> None:
        tool = OnchainTool(OnchainConfig(rpc_url="https://api.devnet.solana.com"))
        events = tool.get_large_transfers(addresses=[])
        assert events == []

    @patch("tools.onchain_tool.SolanaClient")
    def test_summarize_large_transfers_no_addresses(self, mock_client_cls: MagicMock) -> None:
        tool = OnchainTool(OnchainConfig(rpc_url="https://api.devnet.solana.com"))
        summary = tool.summarize_large_transfers(addresses=[])
        assert "no tracked addresses" in summary

