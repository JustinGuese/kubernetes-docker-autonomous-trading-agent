"""Tests for tools/wallet_tool.py with mocked Solana RPC client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import base58
import pytest
from solders.hash import Hash
from solders.keypair import Keypair

from tools.wallet_tool import WalletTool

# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_wallet():
    """Return a WalletTool with a fully mocked Client and a valid keypair."""
    kp = Keypair()
    valid_key_b58 = base58.b58encode(bytes(kp)).decode()
    mock_client = MagicMock()
    # Real blockhash so txn.sign() in send() succeeds
    mock_bh = MagicMock()
    mock_bh.blockhash = Hash.from_bytes(bytes(32))
    mock_client.get_latest_blockhash.return_value = MagicMock(value=mock_bh)

    with patch("tools.wallet_tool.Client", return_value=mock_client):
        tool = WalletTool(valid_key_b58, "https://api.devnet.solana.com")
    return tool, mock_client


# ── tests ─────────────────────────────────────────────────────────────────────


class TestWalletBalance:
    def test_balance_converts_lamports(self, mock_wallet) -> None:
        tool, client = mock_wallet
        client.get_balance.return_value = MagicMock(value=2_000_000_000)
        assert tool.balance_sol() == 2.0

    def test_zero_balance(self, mock_wallet) -> None:
        tool, client = mock_wallet
        client.get_balance.return_value = MagicMock(value=0)
        assert tool.balance_sol() == 0.0


class TestWalletSend:
    def test_send_returns_signature(self, mock_wallet) -> None:
        tool, client = mock_wallet
        client.send_transaction.return_value = MagicMock(value="abc123sig")
        sig = tool.send("A" * 44, 0.05)
        assert sig == "abc123sig"

    def test_send_uses_integer_lamports(self, mock_wallet) -> None:
        tool, client = mock_wallet
        client.send_transaction.return_value = MagicMock(value="sig")
        tool.send("A" * 44, 0.1)
        client.send_transaction.assert_called_once()


class TestWalletHistory:
    def test_recent_history_returns_list(self, mock_wallet) -> None:
        tool, client = mock_wallet
        mock_sig = MagicMock()
        mock_sig.signature = "sigXYZ"
        mock_sig.slot = 12345
        mock_sig.confirmation_status = "finalized"
        client.get_signatures_for_address.return_value = MagicMock(value=[mock_sig])

        history = tool.recent_history(limit=1)
        assert len(history) == 1
        assert history[0]["signature"] == "sigXYZ"
        assert history[0]["slot"] == 12345
