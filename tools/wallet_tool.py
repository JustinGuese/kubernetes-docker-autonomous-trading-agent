"""Solana devnet wallet: balance, send, history.  Policy-unaware — caller must gate."""

from __future__ import annotations

import logging
import time

import base58
from solana.rpc.api import Client
from solana.rpc.types import TokenAccountOpts
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction

from core.network_config import NetworkDetector, NetworkTokens, NetworkType

logger = logging.getLogger(__name__)

_LAMPORTS_PER_SOL = 1_000_000_000

TOKEN_DECIMALS = {"SOL": 9, "USDC": 6, "WBTC": 8}


class WalletTool:
    def __init__(self, private_key_b58: str, rpc_url: str):
        raw = base58.b58decode(private_key_b58)
        self.keypair = Keypair.from_bytes(raw)
        self.pubkey = self.keypair.pubkey()
        self.client = Client(rpc_url)
        self._rpc_url = rpc_url
        self._network: NetworkType = NetworkDetector.detect(rpc_url)
        self._tokens: NetworkTokens = NetworkDetector.get_tokens(self._network)
        # Logical symbols the wallet exposes; some may not be supported on all
        # networks (e.g. WBTC on devnet).
        self._supported_symbols: tuple[str, ...] = ("SOL", "USDC", "WBTC")

    # ── queries ───────────────────────────────────────────────────

    def balance_sol(self) -> float:
        """Return current balance in SOL (float)."""
        logger.info("fetching balance for %s", self.pubkey)
        resp = self.client.get_balance(self.pubkey)
        sol = resp.value / _LAMPORTS_PER_SOL
        logger.info("  → %.6f SOL (%d lamports)", sol, resp.value)
        return sol

    def balance_token(self, symbol: str) -> float:
        """Return the current balance for *symbol* as a float.

        - For SOL, this delegates to balance_sol().
        - For SPL tokens, this queries the owner's token accounts by mint
          and returns the sum of all balances (in human units, e.g. USDC).
        - If no token account exists yet, 0.0 is returned.
        """
        sym = symbol.upper()
        if sym == "SOL":
            return self.balance_sol()

        if sym not in self._supported_symbols:
            raise ValueError(
                f"Unsupported token symbol for balance lookup: {symbol}"
            )

        # Resolve network-specific mint. Some tokens (e.g. WBTC on devnet) may
        # not exist on a given network; in that case we treat the balance as 0.
        try:
            mint = self._tokens.mint_for_symbol(sym)
        except ValueError as exc:
            logger.warning(
                "token %s is not supported on %s network for wallet balance lookup: %s",
                sym,
                self._network.value,
                exc,
            )
            return 0.0

        logger.info("fetching SPL token balance for %s (%s)", sym, mint)
        # solana-py expects a Pubkey for the mint field inside TokenAccountOpts.
        # We keep KNOWN_MINTS as base58 strings for readability and convert
        # them at call time. On devnet, some mainnet mints may not exist; in
        # that case treat RPC errors as "no balance" rather than surfacing
        # low-level InvalidParamsMessage exceptions to callers.
        try:
            resp = self.client.get_token_accounts_by_owner(
                self.pubkey,
                TokenAccountOpts(mint=Pubkey.from_string(mint)),
            )
        except Exception as exc:
            logger.warning(
                "failed to fetch token accounts for %s (mint=%s): %s", sym, mint, exc
            )
            return 0.0

        accounts = getattr(resp, "value", []) or []
        if not accounts:
            logger.info("  → no token accounts found for %s", sym)
            return 0.0

        total = 0.0
        for acc in accounts:
            try:
                acct_pubkey = getattr(acc, "pubkey", None) or getattr(acc, "pubkey", None)
                if acct_pubkey is None:
                    continue
                balance_resp = self.client.get_token_account_balance(acct_pubkey)
                val = getattr(balance_resp, "value", None)
                if val is None:
                    continue
                amount_str = getattr(val, "amount", None) or getattr(
                    val, "ui_amount_string", None
                )
                decimals = getattr(val, "decimals", TOKEN_DECIMALS.get(sym, 0))
                if amount_str is None:
                    continue
                raw = float(amount_str)
                total += raw / (10**decimals) if decimals else raw
            except Exception as exc:
                logger.warning(
                    "  error while fetching SPL balance for %s account: %s", sym, exc
                )
                continue

        logger.info("  → %.6f %s", total, sym)
        return total

    def get_all_balances(self) -> dict[str, float]:
        """Return a mapping of known token symbols to their balances."""
        balances: dict[str, float] = {}
        for symbol in self._supported_symbols:
            try:
                balances[symbol] = self.balance_token(symbol)
            except Exception as exc:
                logger.warning("failed to fetch balance for %s: %s", symbol, exc)
        return balances

    def recent_history(self, limit: int = 5) -> list[dict]:
        """Return the most recent transaction signatures + basic info."""
        resp = self.client.get_signatures_for_address(self.pubkey, limit=limit)
        return [
            {
                "signature": str(sig.signature),
                "slot": sig.slot,
                "confirmation_status": str(sig.confirmation_status),
            }
            for sig in resp.value
        ]

    # ── mutations ─────────────────────────────────────────────────

    def send(self, destination_b58: str, amount_sol: float, confirm: bool = True) -> str:
        """Send *amount_sol* SOL to *destination_b58*.  Returns transaction signature.

        If *confirm* is True (default), this method will poll the RPC node for
        signature confirmation before returning. This makes higher-level logic
        simpler and reduces the risk of acting on unconfirmed transfers.
        """
        lamports = int(amount_sol * _LAMPORTS_PER_SOL)
        logger.info("sending %d lamports (%.6f SOL) → %s", lamports, amount_sol, destination_b58)
        dest_pubkey = Pubkey.from_string(destination_b58)
        transfer_ix = transfer(
            TransferParams(
                from_pubkey=self.pubkey,
                to_pubkey=dest_pubkey,
                lamports=lamports,
            )
        )
        txn = Transaction.new_with_payer([transfer_ix], payer=self.pubkey)
        blockhash = self.client.get_latest_blockhash().value.blockhash
        logger.info("  signing with blockhash %s …", blockhash)
        txn.sign([self.keypair], blockhash)
        resp = self.client.send_transaction(txn)
        sig = str(resp.value)
        logger.info("  → tx sig: %s", sig)

        if confirm:
            self._wait_for_confirmation(sig)

        return sig

    # ── helpers ────────────────────────────────────────────────────

    def _wait_for_confirmation(self, signature: str, timeout: int = 30) -> None:
        """Block until the given signature is confirmed or *timeout* seconds elapse.

        Logs confirmation status; does not raise on timeout to avoid surprising
        callers in environments with slow RPC propagation.
        """
        logger.info("  waiting for confirmation of %s (timeout=%ss) …", signature, timeout)
        start = time.time()
        while True:
            try:
                resp = self.client.get_signature_statuses([signature])
                info = resp.value[0]
                if info is not None:
                    if info.err is not None:
                        logger.warning("  transaction %s failed: %s", signature, info.err)
                        return
                    status = getattr(info, "confirmation_status", None)
                    logger.info("  confirmation_status=%s", status)
                    if status in ("confirmed", "finalized"):
                        logger.info("  transaction %s confirmed", signature)
                        return
            except Exception as exc:
                logger.warning("  error while polling confirmation for %s: %s", signature, exc)

            if time.time() - start > timeout:
                logger.warning("  timeout waiting for confirmation of %s", signature)
                return

            time.sleep(1)
