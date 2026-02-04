"""Apply technical-analysis indicators via the `ta` library and format for the LLM."""

from __future__ import annotations

import pandas as pd
import ta


class TATool:
    """Enrich an OHLCV DataFrame with all TA indicators and produce an LLM-friendly summary."""

    @staticmethod
    def enrich(df: pd.DataFrame) -> pd.DataFrame:
        """Add all TA features in-place and return the enriched DataFrame.

        Expects columns: open, high, low, close, volume  (float).
        """
        return ta.add_all_ta_features(
            df,
            open="open",
            high="high",
            low="low",
            close="close",
            volume="volume",
            fillna=True,
        )

    @staticmethod
    def summarize(df: pd.DataFrame, symbol: str = "") -> str:
        """Return a concise text summary of the latest candle's key indicators.

        This is what gets fed into the LLM observation — keeps it short and scannable.
        """
        if df.empty:
            return f"[{symbol}] no data"

        last = df.iloc[-1]
        close = last.get("close", 0.0)

        # ── helpers ───────────────────────────────────────────────────
        def _val(col: str) -> str:
            v = last.get(col)
            return f"{v:.4f}" if pd.notna(v) else "N/A"

        # Simple qualitative tags derived from core indicators to help the LLM
        # map numbers into rough regimes (trend + momentum).
        sma_fast = last.get("trend_sma_fast")
        sma_slow = last.get("trend_sma_slow")
        rsi = last.get("momentum_rsi")

        if pd.notna(sma_fast) and pd.notna(sma_slow):
            if sma_fast > sma_slow * 1.01:
                trend_tag = "uptrend"
            elif sma_fast < sma_slow * 0.99:
                trend_tag = "downtrend"
            else:
                trend_tag = "sideways"
        else:
            trend_tag = "unknown"

        if pd.notna(rsi):
            if rsi >= 70:
                momentum_tag = "overbought"
            elif rsi <= 30:
                momentum_tag = "oversold"
            else:
                momentum_tag = "neutral"
        else:
            momentum_tag = "unknown"

        # ── build summary ─────────────────────────────────────────────
        lines = [
            f"[{symbol}] close={close:.4f}",
            # Trend
            f"  SMA20={_val('trend_sma_fast')}  SMA50={_val('trend_sma_slow')}",
            f"  EMA20={_val('trend_ema_fast')}  MACD={_val('trend_macd')}",
            f"  MACD_signal={_val('trend_macd_signal')}  MACD_hist={_val('trend_macd_diff')}",
            # Momentum
            f"  RSI={_val('momentum_rsi')}  Stoch_K={_val('momentum_stoch')}",
            f"  Stoch_D={_val('momentum_stoch_signal')}",
            # Volatility
            f"  BB_upper={_val('volatility_bbh')}  BB_lower={_val('volatility_bbl')}",
            f"  ATR={_val('volatility_atr')}",
            # Volume
            f"  OBV={_val('volume_obv')}  VWAP={_val('volume_vwap')}",
            # Qualitative regimes
            f"  trend_tag={trend_tag}  momentum_tag={momentum_tag}",
        ]
        return "\n".join(lines)
