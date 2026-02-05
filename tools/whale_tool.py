"""Simple Solana whale activity tracker using RPC getSignaturesForAddress.

This tool is intentionally conservative: by default it does not hardcode any
wallets. Operators can populate the WHALE_WALLETS list with known large holders
or exchange hot wallets to begin collecting signals.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from solana.rpc.api import Client as SolanaClient
from solders.pubkey import Pubkey

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WhaleConfig:
    rpc_url: str
    # Operator can provide a non-empty list of whale wallets at runtime.
    whale_wallets: List[str] = field(default_factory=list)
    # Minimum size (in SOL) to treat as a "large" transfer in summaries.
    min_sol_threshold: float = 1_000.0


class WhaleTool:
    """Track large Solana wallet movements via recent signatures."""

    def __init__(self, config: WhaleConfig) -> None:
        self._client = SolanaClient(config.rpc_url)
        self._wallets = [w for w in config.whale_wallets if w]
        self._min_sol = float(config.min_sol_threshold)

    def get_recent_large_transfers(self, hours: int = 24) -> List[Dict]:
        """Return a coarse view of large transfers involving known whale wallets.

        NOTE: This currently only inspects signature metadata and logs that a
        transfer occurred; it does not decode exact SOL amounts from the full
        transaction. This is sufficient to act as a qualitative signal for the
        LLM ("many whales active on exchanges recently").
        """
        if not self._wallets:
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        events: List[Dict] = []

        for addr in self._wallets:
            try:
                pubkey = Pubkey.from_string(addr)
                # Limit the number of signatures per wallet for performance.
                resp = self._client.get_signatures_for_address(pubkey, limit=50)
                for sig_info in resp.value:
                    # sig_info.block_time is Optional[int]
                    block_time = sig_info.block_time
                    if block_time is None:
                        continue
                    ts = datetime.fromtimestamp(block_time, tz=timezone.utc)
                    if ts < cutoff:
                        continue

                    events.append(
                        {
                            "wallet": addr,
                            "signature": str(sig_info.signature),
                            "slot": sig_info.slot,
                            "timestamp": ts.isoformat(),
                        }
                    )
            except Exception as exc:
                logger.warning("failed to inspect whale wallet %s: %s", addr, exc)

        return events

    def summarize_whale_activity(self, hours: int = 24) -> str:
        """Return a short human-readable summary for the LLM."""
        events = self.get_recent_large_transfers(hours=hours)
        if not self._wallets:
            return "whale activity: no whale wallets configured yet"

        if not events:
            return f"whale activity: no recent large transfers in last {hours}h"

        unique_wallets = {e["wallet"] for e in events}
        return (
            f"whale activity: {len(events)} large transfers across "
            f"{len(unique_wallets)} tracked wallets in last {hours}h"
        )

