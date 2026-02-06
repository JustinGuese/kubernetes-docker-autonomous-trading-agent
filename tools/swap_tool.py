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
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import httpx
from solana.rpc.api import Client as SolanaClient
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from tenacity import retry, stop_after_attempt, wait_exponential

from core.network_config import (
    DEVNET_TOKENS,
    MAINNET_TOKENS,
    NetworkDetector,
    NetworkTokens,
    NetworkType,
)

logger = logging.getLogger(__name__)

JUP_ULTRA_BASE_URL = "https://api.jup.ag"
# Jupiter's documented swap API host; we use /swap/v1/quote and /swap/v1/swap.
JUP_SWAP_BASE_URL = "https://api.jup.ag"
_DEBUG_LOG_PATH = Path(".cursor/debug.log")


def _debug_log(hypothesis_id: str, location: str, message: str, data: Dict[str, Any]) -> None:
    """Append a single NDJSON debug line for swap-related instrumentation."""
    # region agent log
    payload = {
        "sessionId": "debug-session",
        "runId": "swap-debug-pre-fix",
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(datetime.now().timestamp() * 1000),
    }
    try:
        _DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except Exception:
        # Never let debug logging break swaps.
        pass
    # endregion


class SwapStrategy(ABC):
    """Abstract swap execution strategy."""

    @abstractmethod
    def execute_swap(
        self,
        from_mint: str,
        to_mint: str,
        amount_lamports: int,
        slippage_bps: int,
    ) -> str:
        """Execute swap and return transaction signature."""
        raise NotImplementedError


class JupiterUltraSwap(SwapStrategy):
    """Mainnet Jupiter Ultra API implementation."""

    def __init__(
        self,
        keypair: Keypair,
        rpc: SolanaClient,
        api_key: str | None,
    ) -> None:
        self._keypair = keypair
        self._rpc = rpc
        self._api_key = api_key

    def _owner_pubkey_str(self) -> str:
        return str(self._keypair.pubkey())

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def _execute_ultra(
        self,
        request_id: str,
        signed_tx_b64: str,
        headers: Dict[str, str] | None,
    ) -> Dict[str, Any]:
        exec_resp = httpx.post(
            f"{JUP_ULTRA_BASE_URL}/ultra/v1/execute",
            json={"requestId": request_id, "signedTransaction": signed_tx_b64},
            headers=headers or None,
            timeout=20.0,
        )
        if exec_resp.status_code != 200:
            raise RuntimeError(
                f"Ultra execute error {exec_resp.status_code}: {exec_resp.text}"
            )
        return exec_resp.json()

    def execute_swap(
        self,
        from_mint: str,
        to_mint: str,
        amount_lamports: int,
        slippage_bps: int,
    ) -> str:
        taker = self._owner_pubkey_str()

        logger.info(
            "JupiterUltraSwap: requesting Ultra order %s -> %s amount=%d (slippage_bps=%d)",
            from_mint,
            to_mint,
            amount_lamports,
            slippage_bps,
        )

        headers: Dict[str, str] = {}
        if self._api_key:
            headers["x-api-key"] = self._api_key

        order_resp = httpx.get(
            f"{JUP_ULTRA_BASE_URL}/ultra/v1/order",
            params={
                "inputMint": from_mint,
                "outputMint": to_mint,
                "amount": str(amount_lamports),
                "slippageBps": str(slippage_bps),
                "taker": taker,
            },
            headers=headers or None,
            timeout=20.0,
        )
        if order_resp.status_code != 200:
            raise RuntimeError(
                f"Ultra order error {order_resp.status_code}: {order_resp.text}"
            )

        order_json: Dict[str, Any] = order_resp.json()
        unsigned_tx_b64 = order_json.get("transaction") or order_json.get(
            "swapTransaction"
        )
        request_id = order_json.get("requestId")
        if not request_id:
            body_preview = order_resp.text[:500] if order_resp.text else str(order_json)
            raise RuntimeError(
                "Ultra order response missing requestId. " f"Response: {body_preview}"
            )
        if not unsigned_tx_b64:
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
                "Ultra order returned no transaction. "
                f"errorCode={err_code} response_keys={list(order_json.keys())}"
            )

        unsigned_bytes = base64.b64decode(unsigned_tx_b64)
        tx = VersionedTransaction.from_bytes(unsigned_bytes)
        signature = self._keypair.sign_message(bytes(tx.message))
        signed_tx = VersionedTransaction.populate(tx.message, [signature])
        signed_b64 = base64.b64encode(bytes(signed_tx)).decode("utf-8")

        exec_json = self._execute_ultra(request_id, signed_b64, headers)
        signature = exec_json.get("signature") or exec_json.get("txid")
        if not signature:
            raise RuntimeError(
                f"Ultra execute response missing signature: {exec_json}"
            )

        logger.info("JupiterUltraSwap: swap executed, signature=%s", signature)
        return str(signature)


class JupiterV6Swap(SwapStrategy):
    """Devnet Jupiter Swap API implementation (real swaps)."""

    def __init__(self, keypair: Keypair, rpc: SolanaClient, api_key: str | None) -> None:
        self._keypair = keypair
        self._rpc = rpc
        self._api_key = api_key

    def execute_swap(
        self,
        from_mint: str,
        to_mint: str,
        amount_lamports: int,
        slippage_bps: int,
    ) -> str:
        _debug_log(
            "H1",
            "tools/swap_tool.py:JupiterV6Swap.execute_swap:entry",
            "enter devnet v6 swap",
            {
                "from_mint": from_mint,
                "to_mint": to_mint,
                "amount_lamports": amount_lamports,
                "slippage_bps": slippage_bps,
                "base_url": JUP_SWAP_BASE_URL,
            },
        )
        logger.info(
            "JupiterV6Swap: requesting quote %s -> %s amount=%d (slippage_bps=%d)",
            from_mint,
            to_mint,
            amount_lamports,
            slippage_bps,
        )
        headers: Dict[str, str] = {}
        if self._api_key:
            headers["x-api-key"] = self._api_key
        try:
            quote_resp = httpx.get(
                f"{JUP_SWAP_BASE_URL}/swap/v1/quote",
                params={
                    "inputMint": from_mint,
                    "outputMint": to_mint,
                    "amount": str(amount_lamports),
                    "slippageBps": str(slippage_bps),
                },
                headers=headers or None,
                timeout=10.0,
            )
        except Exception as exc:
            _debug_log(
                "H1",
                "tools/swap_tool.py:JupiterV6Swap.execute_swap:quote_error",
                "exception during v6 quote",
                {"error_type": type(exc).__name__, "error_str": str(exc)},
            )
            raise

        if quote_resp.status_code == 404:
            raise RuntimeError(
                "No liquidity pool found on devnet for this token pair. "
                "Available devnet pairs are limited."
            )
        if quote_resp.status_code != 200:
            raise RuntimeError(
                f"Jupiter v6 quote error {quote_resp.status_code}: {quote_resp.text}"
            )

        quote = quote_resp.json()

        try:
            swap_resp = httpx.post(
                f"{JUP_SWAP_BASE_URL}/swap/v1/swap",
                json={
                    "quoteResponse": quote,
                    "userPublicKey": str(self._keypair.pubkey()),
                    "wrapAndUnwrapSol": True,
                },
                headers=headers or None,
                timeout=10.0,
            )
        except Exception as exc:
            _debug_log(
                "H1",
                "tools/swap_tool.py:JupiterV6Swap.execute_swap:swap_error",
                "exception during v6 swap",
                {"error_type": type(exc).__name__, "error_str": str(exc)},
            )
            raise
        if swap_resp.status_code != 200:
            raise RuntimeError(
                f"Jupiter v6 swap error {swap_resp.status_code}: {swap_resp.text}"
            )

        unsigned_tx_b64 = swap_resp.json().get("swapTransaction")
        if not unsigned_tx_b64:
            raise RuntimeError("Jupiter v6 swap response missing swapTransaction")

        unsigned_bytes = base64.b64decode(unsigned_tx_b64)
        tx = VersionedTransaction.from_bytes(unsigned_bytes)
        signature = self._keypair.sign_message(bytes(tx.message))
        signed_tx = VersionedTransaction.populate(tx.message, [signature])

        # Submit directly to the configured RPC rather than via Jupiter execute.
        resp = self._rpc.send_raw_transaction(bytes(signed_tx))
        return str(resp.value)


class MockSwap(SwapStrategy):
    """Synthetic swap implementation for tests / devnet fallback."""

    def __init__(self, network: NetworkType) -> None:
        self._network = network

    def execute_swap(
        self,
        from_mint: str,
        to_mint: str,
        amount_lamports: int,
        slippage_bps: int,
    ) -> str:
        logger.info(
            "MockSwap (%s): requested swap %s -> %s amount=%d (slippage_bps=%d)",
            self._network.value,
            from_mint,
            to_mint,
            amount_lamports,
            slippage_bps,
        )
        fake_sig = (
            f"DEVNET-MOCK-SWAP-{from_mint}-{to_mint}-"
            f"{amount_lamports}-{slippage_bps}"
        )
        logger.info("MockSwap: returning synthetic signature=%s", fake_sig)
        return fake_sig


class SwapTool:
    """Network-aware swap executor using strategy pattern.

    - Mainnet: Jupiter Ultra API (requires JUPITER_API_KEY)
    - Devnet:  Jupiter v6 Swap API (real swaps where pools exist)
    - Devnet fallback: mock strategy if v6 has no liquidity
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
        self._network = NetworkDetector.detect(rpc_url)
        self._tokens: NetworkTokens = (
            DEVNET_TOKENS if self._network == NetworkType.DEVNET else MAINNET_TOKENS
        )
        self._strategy: SwapStrategy = self._select_strategy(api_key)

    def _select_strategy(self, api_key: str | None) -> SwapStrategy:
        if self._network == NetworkType.MAINNET:
            if not api_key:
                raise ValueError("JUPITER_API_KEY required for mainnet swaps")
            return JupiterUltraSwap(self._keypair, self._rpc, api_key)

        # Devnet: prefer real swaps via Jupiter swap API; caller may catch
        # RuntimeError and fall back to mock if desired.
        return JupiterV6Swap(self._keypair, self._rpc, api_key)

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

        # Resolve mints via network-aware token configuration.
        from_mint = self._tokens.mint_for_symbol(from_token)
        to_mint = self._tokens.mint_for_symbol(to_token)

        try:
            return self._strategy.execute_swap(
                from_mint, to_mint, amount_lamports, slippage_bps
            )
        except RuntimeError as exc:
            # On devnet, gracefully fall back to mock for missing pools, but
            # preserve the error message for logging.
            if self._network == NetworkType.DEVNET and "No liquidity pool" in str(exc):
                logger.warning(
                    "Devnet pool not found, falling back to mock swap: %s", exc
                )
                mock = MockSwap(self._network)
                return mock.execute_swap(
                    from_mint, to_mint, amount_lamports, slippage_bps
                )
            raise


