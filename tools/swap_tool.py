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

from tenacity import retry, stop_after_attempt, wait_exponential

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
        self._rpc_url = rpc_url
        self._tokens = SwapTokens()
        self._api_key = api_key

    # ── helpers ────────────────────────────────────────────────────

    def _owner_pubkey_str(self) -> str:
        return str(self._keypair.pubkey())

    def _is_devnet(self) -> bool:
        """Return True if the configured RPC URL points to a devnet cluster."""
        return "devnet" in self._rpc_url.lower()

    # ── internal Ultra helpers ──────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _execute_ultra(
        self,
        request_id: str,
        signed_tx_b64: str,
        headers: Dict[str, str] | None,
    ) -> Dict[str, Any]:
        """Execute a previously-built Ultra swap transaction with retry/backoff.

        Network issues or transient HTTP failures will be retried up to 3 times
        with exponential backoff before surfacing as an exception.
        """
        exec_resp = httpx.post(
            f"{JUP_ULTRA_BASE_URL}/ultra/v1/execute",
            json={"requestId": request_id, "signedTransaction": signed_tx_b64},
            headers=headers or None,
            timeout=20.0,
        )
        if exec_resp.status_code != 200:
            raise RuntimeError(f"Ultra execute error {exec_resp.status_code}: {exec_resp.text}")
        return exec_resp.json()

    def _swap_devnet_mock(
        self,
        from_token: str,
        to_token: str,
        amount_lamports: int,
        slippage_bps: int,
    ) -> str:
        """Devnet-safe mock swap implementation.

        On Solana devnet, Jupiter Ultra is not available and we do not want to
        risk mainnet funds. Instead of attempting a real swap, we log the
        requested parameters and return a synthetic signature string.

        This keeps the agent's control flow and position tracking exercised in
        tests without touching real liquidity.
        """
        logger.info(
            "SwapTool (devnet mock): requested swap %s -> %s amount=%d (slippage_bps=%d)",
            from_token,
            to_token,
            amount_lamports,
            slippage_bps,
        )
        # Encode a deterministic-but-fake signature so downstream logs/tests can
        # still correlate actions.
        fake_sig = (
            f"DEVNET-MOCK-SWAP-{from_token}-{to_token}-"
            f"{amount_lamports}-{slippage_bps}"
        )
        logger.info("SwapTool (devnet mock): returning synthetic signature=%s", fake_sig)
        return fake_sig

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

        # Validate supported symbols up-front so we fail fast even when running
        # in devnet mock mode.
        self._tokens.mint_for_symbol(from_token)
        self._tokens.mint_for_symbol(to_token)

        # On devnet we cannot safely call Jupiter Ultra (mainnet-only). Instead
        # of raising and blocking all swap tests, we return a deterministic
        # synthetic signature so the rest of the pipeline (position tracking,
        # logging, reflections) can still be exercised without real funds.
        if self._is_devnet():
            return self._swap_devnet_mock(from_token, to_token, amount_lamports, slippage_bps)

        input_mint = self._tokens.mint_for_symbol(from_token)
        output_mint = self._tokens.mint_for_symbol(to_token)
        taker = self._owner_pubkey_str()

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
                "taker": taker,
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

        exec_json = self._execute_ultra(request_id, signed_b64, headers)
        signature = exec_json.get("signature") or exec_json.get("txid")
        if not signature:
            raise RuntimeError(f"Ultra execute response missing signature: {exec_json}")

        logger.info("SwapTool: swap executed, signature=%s", signature)
        return str(signature)

