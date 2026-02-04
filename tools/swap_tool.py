"""Token swap tool using Jupiter Ultra API on Solana.

This tool is deliberately minimal and synchronous from the caller's point of view.
It:
  - Builds a swap transaction via Jupiter Ultra `/order`
  - Signs it with the existing wallet keypair
  - Executes it via `/execute`

Network errors and Jupiter errors are surfaced as exceptions; the agent's
`act_node` will catch them and record a failed action result.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any, Dict

import httpx
from solana.rpc.api import Client as SolanaClient
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

logger = logging.getLogger(__name__)

JUP_ULTRA_BASE_URL = "https://api.jup.ag"


@dataclass(frozen=True)
class SwapTokens:
    """Simple mapping of logical token symbols to mint addresses."""

    sol_mint: str = "So11111111111111111111111111111111111111112"
    usdc_mint: str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    wbtc_mint: str = "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh"

    def mint_for_symbol(self, symbol: str) -> str:
        s = symbol.upper()
        if s == "SOL":
            return self.sol_mint
        if s == "USDC":
            return self.usdc_mint
        if s in {"WBTC", "BTC"}:
            return self.wbtc_mint
        raise ValueError(f"Unsupported token symbol for swap: {symbol}")


class SwapTool:
    """Jupiter Ultra-based swap executor.

    This is intentionally conservative: it does not try to expose every Ultra
    feature, just enough for the agent to move between SOL, USDC, and WBTC.

    Jupiter Ultra requires an API key (x-api-key header). Get one at portal.jup.ag.
    """

    def __init__(
        self,
        keypair: Keypair,
        rpc_url: str,
        *,
        api_key: str | None = None,
    ) -> None:
        self._keypair = keypair
        self._rpc = SolanaClient(rpc_url)
        self._tokens = SwapTokens()
        self._api_key = api_key

    # ── helpers ────────────────────────────────────────────────────

    def _owner_pubkey_str(self) -> str:
        return str(self._keypair.pubkey())

    # ── public API ─────────────────────────────────────────────────

    def swap(
        self,
        from_token: str,
        to_token: str,
        amount_lamports: int,
        slippage_bps: int = 50,
    ) -> str:
        """Execute a token swap and return the transaction signature.

        Raises RuntimeError on failure.
        """
        if amount_lamports <= 0:
            raise ValueError("amount_lamports must be positive")

        input_mint = self._tokens.mint_for_symbol(from_token)
        output_mint = self._tokens.mint_for_symbol(to_token)
        owner = self._owner_pubkey_str()

        logger.info(
            "SwapTool: requesting Ultra order %s -> %s amount=%d (slippage_bps=%d)",
            from_token,
            to_token,
            amount_lamports,
            slippage_bps,
        )

        headers = {}
        if self._api_key:
            headers["x-api-key"] = self._api_key

        order_resp = httpx.get(
            f"{JUP_ULTRA_BASE_URL}/ultra/v1/order",
            params={
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": str(amount_lamports),
                "slippageBps": str(slippage_bps),
                "owner": owner,
            },
            headers=headers or None,
            timeout=20.0,
        )
        if order_resp.status_code != 200:
            raise RuntimeError(f"Ultra order error {order_resp.status_code}: {order_resp.text}")

        order_json: Dict[str, Any] = order_resp.json()
        # API returns "transaction" (not "swapTransaction"); accept both for compatibility
        unsigned_tx_b64 = order_json.get("transaction") or order_json.get("swapTransaction")
        request_id = order_json.get("requestId")
        if not request_id:
            body_preview = order_resp.text[:500] if order_resp.text else str(order_json)
            raise RuntimeError(
                "Ultra order response missing requestId. " f"Response: {body_preview}"
            )
        if not unsigned_tx_b64:
            # No transaction = quote error (e.g. insufficient funds, min amount)
            err_code = order_json.get("errorCode")
            err_msg = order_json.get("errorMessage") or order_json.get("error")
            logger.warning(
                "Ultra order returned no transaction. errorCode=%s errorMessage=%s full_response=%s",
                err_code,
                err_msg,
                order_json,
            )
            if isinstance(err_msg, str):
                raise RuntimeError(f"Ultra order failed: {err_msg}")
            raise RuntimeError(
                f"Ultra order returned no transaction. errorCode={err_code} response_keys={list(order_json.keys())}"
            )

        # Deserialize, sign, and re-serialize the transaction. Ultra provides an
        # unsigned VersionedTransaction; we sign its message with our keypair.
        unsigned_bytes = base64.b64decode(unsigned_tx_b64)
        tx = VersionedTransaction.from_bytes(unsigned_bytes)
        signature = self._keypair.sign_message(bytes(tx.message))
        signed_tx = VersionedTransaction.populate(tx.message, [signature])
        signed_b64 = base64.b64encode(bytes(signed_tx)).decode("utf-8")

        exec_resp = httpx.post(
            f"{JUP_ULTRA_BASE_URL}/ultra/v1/execute",
            json={"requestId": request_id, "signedTransaction": signed_b64},
            headers=headers or None,
            timeout=20.0,
        )
        if exec_resp.status_code != 200:
            raise RuntimeError(f"Ultra execute error {exec_resp.status_code}: {exec_resp.text}")

        exec_json: Dict[str, Any] = exec_resp.json()
        signature = exec_json.get("signature") or exec_json.get("txid")
        if not signature:
            raise RuntimeError(f"Ultra execute response missing signature: {exec_json}")

        logger.info("SwapTool: swap executed, signature=%s", signature)
        return str(signature)

