"""Social sentiment aggregation for crypto symbols.

This tool is intentionally conservative: it focuses on a normalized output
schema and uses simple, pluggable data sources so that operators can enable or
disable providers (e.g. LunarCrush, Reddit) via configuration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SentimentConfig:
    # Flags for optional external providers; currently used as placeholders.
    enable_lunarcrush: bool = False
    enable_twitter: bool = False
    enable_reddit: bool = True


class SentimentTool:
    """Aggregate social sentiment signals into a normalized schema.

    Output schema (per symbol):
        {
            \"social_volume_score\": float,   # relative 0–1 score
            \"sentiment_score\": float,       # -1 (bearish) .. +1 (bullish)
            \"top_mentions\": list[str],      # short phrases/hashtags
        }

    At the moment this implementation only provides stubbed values; it can be
    extended to call real APIs (LunarCrush, Twitter, Reddit) obeying policy
    constraints.
    """

    def __init__(self, config: SentimentConfig | None = None) -> None:
        self._config = config or SentimentConfig()

    def get_sentiment(self, symbols: List[str]) -> Dict[str, Dict]:
        """Return a normalized sentiment snapshot per symbol.

        Currently returns neutral placeholder data to keep the interface stable
        while avoiding external dependencies.
        """
        result: Dict[str, Dict] = {}
        for sym in symbols:
            key = sym.upper()
            # Neutral placeholder: zero sentiment, low volume.
            result[key] = {
                "social_volume_score": 0.1,
                "sentiment_score": 0.0,
                "top_mentions": [],
            }
        return result

    def summarize_sentiment(self, symbols: List[str]) -> str:
        """Produce a compact human-readable sentiment summary."""
        data = self.get_sentiment(symbols)
        if not data:
            return "sentiment: no symbols provided"

        parts: List[str] = []
        for sym in symbols:
            info = data.get(sym.upper()) or {}
            vol = float(info.get("social_volume_score", 0.0))
            score = float(info.get("sentiment_score", 0.0))
            if score > 0.2:
                mood = "bullish"
            elif score < -0.2:
                mood = "bearish"
            else:
                mood = "neutral"
            parts.append(f"{sym}: volume={vol:.2f}, mood={mood}")

        return "sentiment: " + "; ".join(parts)

