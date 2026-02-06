from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class NetworkType(Enum):
    MAINNET = "mainnet"
    DEVNET = "devnet"


@dataclass(frozen=True)
class NetworkTokens:
    """Mint addresses per network for the tokens the bot cares about."""

    sol: str
    usdc: str
    wbtc: str | None  # May not exist on devnet

    def mint_for_symbol(self, symbol: str) -> str:
        """Return mint address for a given logical token symbol.

        On devnet, some tokens (e.g. WBTC) may be unavailable; callers should
        handle ValueError in those cases.
        """
        sym = symbol.upper()
        if sym == "SOL":
            return self.sol
        if sym == "USDC":
            return self.usdc
        if sym in {"WBTC", "BTC"}:
            if self.wbtc is None:
                raise ValueError(f"Token {sym} is not configured for this network")
            return self.wbtc
        raise ValueError(f"Unsupported token symbol for swap: {symbol}")


MAINNET_TOKENS = NetworkTokens(
    sol="So11111111111111111111111111111111111111112",
    usdc="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    wbtc="3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh",
)

DEVNET_TOKENS = NetworkTokens(
    # Devnet SOL mint is the same wrapped SOL address.
    sol="So11111111111111111111111111111111111111112",
    # USDC devnet mint taken from existing token_utils configuration.
    usdc="4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
    # WBTC is not reliably available on devnet; restrict to SOL/USDC.
    wbtc=None,
)


class NetworkDetector:
    """Helpers for detecting network and resolving token configuration."""

    @staticmethod
    def detect(rpc_url: str) -> NetworkType:
        """Detect network from RPC URL (simple heuristic).

        This mirrors the existing `_is_devnet` logic in SwapTool so we have a
        single source of truth for network detection.
        """
        return NetworkType.DEVNET if "devnet" in rpc_url.lower() else NetworkType.MAINNET

    @staticmethod
    def get_tokens(network: NetworkType) -> NetworkTokens:
        return DEVNET_TOKENS if network == NetworkType.DEVNET else MAINNET_TOKENS

