"""On-chain data helper for Solana tokens and wallets.

This module intentionally provides a *minimal*, high-level view over on-chain
activity that is useful for the trading agent, without trying to be a full
blockchain indexer.

Where possible it relies on public RPC methods; for richer data (DEX volume,
holder counts) it can be extended to call third-party indexers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from solana.rpc.api import Client as SolanaClient
from solders.pubkey import Pubkey

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OnchainConfig:
    rpc_url: str


class OnchainTool:
    """Lightweight Solana on-chain data accessor.

    Current capabilities:
    - Large transfer activity for selected addresses via getSignaturesForAddress.

    The methods for whale holders, DEX volume and holder counts are left as
    extension points so they can be wired to specific indexer APIs without
    hardcoding a provider here.
    """

    def __init__(self, config: OnchainConfig) -> None:
        self._client = SolanaClient(config.rpc_url)

    # ── extension points (stubs) ───────────────────────────────────

    def get_whale_holders(self, token_mint: str, top_n: int = 100) -> List[Dict]:
        """Placeholder for querying top token holders via an indexer.

        This is not implemented against a specific provider yet; returning an
        empty list keeps the agent functional while signalling the absence of
        data.
        """
        logger.info(
            "OnchainTool.get_whale_holders called for mint=%s top_n=%d (not yet implemented)",
            token_mint,
            top_n,
        )
        return []

    def get_dex_volume_by_pool(self, protocol: str, lookback_hours: int = 24) -> Dict[str, float]:
        """Placeholder for querying DEX volume per pool from an external indexer."""
        logger.info(
            "OnchainTool.get_dex_volume_by_pool called for protocol=%s lookback_hours=%d "
            "(not yet implemented)",
            protocol,
            lookback_hours,
        )
        return {}

    def get_holder_count_change(self, token_mint: str, window_days: int = 7) -> Dict[str, int]:
        """Placeholder for approximating holder count change over a window."""
        logger.info(
            "OnchainTool.get_holder_count_change called for mint=%s window_days=%d "
            "(not yet implemented)",
            token_mint,
            window_days,
        )
        return {}

    # ── implemented: large transfers (signature-based) ────────────

    def get_large_transfers(
        self,
        addresses: List[str],
        min_slot: int | None = None,
        lookback_hours: int = 24,
    ) -> List[Dict]:
        """Return recent transaction signatures for the given addresses.

        This does not decode exact amounts; instead it surfaces *activity* that
        the LLM can treat as a qualitative \"whales are moving\" signal.
        """
        if not addresses:
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        events: List[Dict] = []

        for addr in addresses:
            try:
                pubkey = Pubkey.from_string(addr)
                resp = self._client.get_signatures_for_address(pubkey, limit=50)
                for sig_info in resp.value:
                    if min_slot is not None and sig_info.slot < min_slot:
                        continue
                    block_time = sig_info.block_time
                    if block_time is None:
                        continue
                    ts = datetime.fromtimestamp(block_time, tz=timezone.utc)
                    if ts < cutoff:
                        continue
                    events.append(
                        {
                            "address": addr,
                            "signature": str(sig_info.signature),
                            "slot": sig_info.slot,
                            "timestamp": ts.isoformat(),
                        }
                    )
            except Exception as exc:
                logger.warning("OnchainTool: failed to inspect address %s: %s", addr, exc)

        return events

    def summarize_large_transfers(
        self,
        addresses: List[str],
        lookback_hours: int = 24,
    ) -> str:
        """Summarize large transfer activity for a set of addresses."""
        events = self.get_large_transfers(addresses, lookback_hours=lookback_hours)
        if not addresses:
            return "onchain: no tracked addresses configured for large transfer monitoring"
        if not events:
            return f"onchain: no recent large transfers in last {lookback_hours}h"

        unique_addrs = {e["address"] for e in events}
        return (
            f"onchain: {len(events)} recent transfers across "
            f"{len(unique_addrs)} tracked addresses in last {lookback_hours}h"
        )

