"""Solana devnet wallet: balance, send, history.  Policy-unaware — caller must gate."""

from __future__ import annotations

import logging

import base58
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction

logger = logging.getLogger(__name__)

_LAMPORTS_PER_SOL = 1_000_000_000


class WalletTool:
    def __init__(self, private_key_b58: str, rpc_url: str):
        raw = base58.b58decode(private_key_b58)
        self.keypair = Keypair.from_bytes(raw)
        self.pubkey = self.keypair.pubkey()
        self.client = Client(rpc_url)

    # ── queries ───────────────────────────────────────────────────

    def balance_sol(self) -> float:
        """Return current balance in SOL (float)."""
        logger.info("fetching balance for %s", self.pubkey)
        resp = self.client.get_balance(self.pubkey)
        sol = resp.value / _LAMPORTS_PER_SOL
        logger.info("  → %.6f SOL (%d lamports)", sol, resp.value)
        return sol

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

    def send(self, destination_b58: str, amount_sol: float) -> str:
        """Send *amount_sol* SOL to *destination_b58*.  Returns transaction signature."""
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
        logger.info("  → tx sig: %s", resp.value)
        return str(resp.value)
