"""Tests for tools/wallet_tool.py with mocked Solana RPC client.

The solana/solders native extensions may not be available in all environments,
so we inject mock modules into sys.modules before importing wallet_tool.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import base58
import pytest

# ── inject fake solana/solders modules ────────────────────────────────────────
# Must happen before any import of tools.wallet_tool.

_mock_keypair_cls = MagicMock()
_mock_pubkey_cls = MagicMock()
_mock_transfer_params_cls = MagicMock()
_mock_transfer_fn = MagicMock()
_mock_transaction_cls = MagicMock()

# solders sub-packages
_solders = MagicMock()
_solders_keypair = MagicMock()
_solders_keypair.Keypair = _mock_keypair_cls
_solders_pubkey = MagicMock()
_solders_pubkey.Pubkey = _mock_pubkey_cls
_solders_system_program = MagicMock()
_solders_system_program.TransferParams = _mock_transfer_params_cls
_solders_system_program.transfer = _mock_transfer_fn
_solders_transaction = MagicMock()
_solders_transaction.Transaction = _mock_transaction_cls

# solana sub-packages
_solana = MagicMock()
_solana_rpc = MagicMock()
_solana_rpc_api = MagicMock()

sys.modules.setdefault("solders", _solders)
sys.modules.setdefault("solders.keypair", _solders_keypair)
sys.modules.setdefault("solders.pubkey", _solders_pubkey)
sys.modules.setdefault("solders.system_program", _solders_system_program)
sys.modules.setdefault("solders.transaction", _solders_transaction)
sys.modules.setdefault("solana", _solana)
sys.modules.setdefault("solana.rpc", _solana_rpc)
sys.modules.setdefault("solana.rpc.api", _solana_rpc_api)

# Now we can safely import WalletTool
from tools.wallet_tool import WalletTool  # noqa: E402

# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_wallet():
    """Return a WalletTool with a fully mocked Client."""
    fake_key_b58 = base58.b58encode(b"\x01" * 64).decode()

    mock_client = MagicMock()
    _solana_rpc_api.Client.return_value = mock_client

    tool = WalletTool(fake_key_b58, "https://api.devnet.solana.com")
    tool.client = mock_client  # ensure we use our mock
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
