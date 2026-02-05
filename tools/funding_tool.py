"""Funding rates and open interest from Binance Futures public endpoints."""

from __future__ import annotations

import logging
from typing import Dict, List

import httpx

logger = logging.getLogger(__name__)

_FAPI_BASE_URL = "https://fapi.binance.com/fapi/v1"


class FundingTool:
    """Fetch perpetual funding rates and open interest from Binance Futures.

    This uses public endpoints only and does not require API keys.
    """

    def get_funding_rates(self, symbols: List[str]) -> Dict[str, float]:
        """Return a mapping symbol → current funding rate (as a fraction per 8h)."""
        rates: Dict[str, float] = {}
        for symbol in symbols:
            try:
                resp = httpx.get(
                    f"{_FAPI_BASE_URL}/premiumIndex",
                    params={"symbol": symbol},
                    timeout=10.0,
                )
                resp.raise_for_status()
                data = resp.json()
                raw = data.get("lastFundingRate")
                if raw is None:
                    logger.warning("no lastFundingRate in premiumIndex response for %s: %s", symbol, data)
                    continue
                rate = float(raw)
                rates[symbol] = rate
            except Exception as exc:
                logger.warning("failed to fetch funding rate for %s: %s", symbol, exc)
        return rates

    def get_open_interest(self, symbol: str) -> float:
        """Return current open interest (base asset amount) for *symbol*."""
        try:
            resp = httpx.get(
                f"{_FAPI_BASE_URL}/openInterest",
                params={"symbol": symbol},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            raw = data.get("openInterest")
            return float(raw) if raw is not None else 0.0
        except Exception as exc:
            logger.warning("failed to fetch open interest for %s: %s", symbol, exc)
            return 0.0

