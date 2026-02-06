"""CoinGecko API helper focused on trending coins.

Uses the public API by default and optionally a demo API key when
``COINGECKO_DEMO_API_KEY`` is set in the environment.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from pycoingecko import CoinGeckoAPI

logger = logging.getLogger(__name__)


class CoingeckoTool:
    """Lightweight wrapper around CoinGeckoAPI for trending searches."""

    def __init__(self) -> None:
        demo_key = os.getenv("COINGECKO_DEMO_API_KEY")
        self._demo_key = demo_key
        if demo_key:
            logger.info("CoingeckoTool: using demo API key for CoinGecko")
            self._client = CoinGeckoAPI(demo_api_key=demo_key)
        else:
            logger.info("CoingeckoTool: using public CoinGecko API (no key)")
            self._client = CoinGeckoAPI()

    def get_trending_raw(self) -> dict[str, Any] | None:
        """Return raw JSON from /search/trending or None on failure."""
        try:
            return self._client.get_search_trending()
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("CoingeckoTool: get_search_trending failed: %s", exc)
            return None

    def get_trending_summary(self) -> str:
        """Return a compact multi-line summary of trending coins.

        Lines look like:
        [coingecko_trending] rank=1 id=bitcoin symbol=btc market_cap_rank=1 score=0
        """
        data = self.get_trending_raw()
        if not data:
            return "[coingecko_trending] unavailable (API error or empty response)"

        coins = data.get("coins") or []
        if not coins:
            return "[coingecko_trending] no trending coins returned"

        lines: list[str] = []
        for idx, entry in enumerate(coins, start=1):
            item = entry.get("item") or {}
            coin_id = item.get("id") or "unknown"
            symbol = (item.get("symbol") or "").lower()
            name = item.get("name") or ""
            score = item.get("score")
            mcap_rank = item.get("market_cap_rank")
            line_parts = [
                f"rank={idx}",
                f"id={coin_id}",
                f"symbol={symbol}",
            ]
            if name:
                line_parts.append(f"name={name}")
            if isinstance(mcap_rank, int):
                line_parts.append(f"market_cap_rank={mcap_rank}")
            if isinstance(score, int):
                line_parts.append(f"score={score}")
            lines.append("[coingecko_trending] " + " ".join(line_parts))

        return "\n".join(lines)

