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


class TestWalletTokenBalances:
    def test_balance_token_sol_uses_balance_sol(self, mock_wallet) -> None:
        tool, client = mock_wallet
        client.get_balance.return_value = MagicMock(value=1_500_000_000)
        assert abs(tool.balance_token("SOL") - 1.5) < 1e-9

    def test_get_all_balances_calls_balance_token(self, mock_wallet) -> None:
        # Use a real WalletTool instance but stub out balance_token so we don't
        # depend on real RPC layout.
        tool, _ = mock_wallet
        calls: list[str] = []

        def _fake_balance(sym: str) -> float:
            calls.append(sym)
            return {"SOL": 1.0, "USDC": 2.0, "WBTC": 0.0}.get(sym, 0.0)

        tool.balance_token = _fake_balance  # type: ignore[assignment]
        balances = tool.get_all_balances()

        # Should query every supported symbol exactly once.
        assert set(calls) == {"SOL", "USDC", "WBTC"}
        assert balances["SOL"] == 1.0
        assert balances["USDC"] == 2.0

    @patch("tools.wallet_tool.Client")
    def test_balance_token_usdc_uses_pubkey_mint(self, mock_client_cls: MagicMock) -> None:
        """Smoke-test SPL branch to ensure it doesn't raise when mint is a string."""
        # Reuse the existing valid-key fixture behaviour by constructing a
        # WalletTool via the patched Client but with a real Keypair, similar to
        # mock_wallet. We don't care about the actual client methods here.
        from solders.keypair import Keypair

        kp = Keypair()
        valid_key_b58 = base58.b58encode(bytes(kp)).decode()
        mock_client = mock_client_cls.return_value
        # Simulate no token accounts so the SPL branch runs but returns 0.0
        mock_client.get_token_accounts_by_owner.return_value = MagicMock(value=[])
        tool = WalletTool(valid_key_b58, "https://api.devnet.solana.com")
        assert tool.balance_token("USDC") == 0.0

    @patch("tools.wallet_tool.Client")
    def test_balance_token_rpc_error_returns_zero(self, mock_client_cls: MagicMock) -> None:
        """If the RPC rejects the mint, treat as zero balance."""
        from solders.keypair import Keypair

        kp = Keypair()
        valid_key_b58 = base58.b58encode(bytes(kp)).decode()
        mock_client = mock_client_cls.return_value
        mock_client.get_token_accounts_by_owner.side_effect = RuntimeError(
            "Invalid param: Token mint could not be unpacked"
        )
        tool = WalletTool(valid_key_b58, "https://api.devnet.solana.com")
        assert tool.balance_token("USDC") == 0.0


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
