"""Apply technical-analysis indicators via the `ta` library and format for the LLM."""

from __future__ import annotations

import re

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

    # ── sentiment helpers ──────────────────────────────────────────

    @staticmethod
    def parse_fear_greed(html: str) -> dict:
        """Extract structured fear/greed data from alternative.me HTML.

        Returns a dict like:
        {"value": 25, "classification": "Extreme Fear", "delta_7d": -10}
        """
        if not html:
            return {}

        try:
            value_match = re.search(r'data-value="(\d+)"', html)
            value = int(value_match.group(1)) if value_match else None

            prev_match = re.search(r'data-value-previous="(\d+)"', html)
            prev = int(prev_match.group(1)) if prev_match else None

            class_match = re.search(r"Fear &amp; Greed Index is (\w+(?: \w+)*)", html)
            classification = class_match.group(1) if class_match else ""

            delta = None
            if value is not None and prev is not None:
                delta = value - prev

            result: dict = {}
            if value is not None:
                result["value"] = value
            if classification:
                result["classification"] = classification
            if delta is not None:
                result["delta_7d"] = delta

            return result
        except Exception:
            # Best-effort parsing only; failures are non-fatal.
            return {}

    @staticmethod
    def detect_trend_alignment(df_fast: pd.DataFrame, df_slow: pd.DataFrame, symbol: str) -> str:
        """Describe whether lower and higher timeframe trends are aligned."""
        if df_fast.empty or df_slow.empty:
            return f"[{symbol}] trend alignment: insufficient data"

        last_fast = df_fast.iloc[-1]
        last_slow = df_slow.iloc[-1]

        fast_tag = last_fast.get("trend_tag", "unknown")
        slow_tag = last_slow.get("trend_tag", "unknown")

        if fast_tag == "uptrend" and slow_tag == "uptrend":
            status = "1h uptrend aligned with 4h uptrend"
        elif fast_tag == "downtrend" and slow_tag == "downtrend":
            status = "1h downtrend aligned with 4h downtrend"
        elif fast_tag == "unknown" or slow_tag == "unknown":
            status = "trend unclear across timeframes"
        else:
            status = f"short-term {fast_tag} vs higher timeframe {slow_tag} (divergent)"

        return f"[{symbol}] trend alignment: {status}"

    # ── cross-asset analytics ──────────────────────────────────────

    @staticmethod
    def compute_btc_dominance(
        btc_df: pd.DataFrame,
        others: dict[str, pd.DataFrame],
    ) -> str:
        """Approximate BTC dominance trend over the latest window.

        This is a rough indicator based on relative USD moves of BTC vs a
        basket of other assets.
        """
        if btc_df.empty or not others:
            return "[correlation] BTC dominance: insufficient data"

        btc_ret = btc_df["close"].pct_change().tail(50)
        if btc_ret.empty:
            return "[correlation] BTC dominance: insufficient data"

        basket_moves = []
        for symbol, df in others.items():
            if df is None or df.empty or "close" not in df:
                continue
            basket_moves.append(df["close"].pct_change().tail(50))

        if not basket_moves:
            return "[correlation] BTC dominance: insufficient data"

        # Simple heuristic: compare average returns.
        btc_avg = btc_ret.mean()
        others_avg = sum(s.mean() for s in basket_moves) / len(basket_moves)

        if btc_avg > others_avg * 1.02:
            msg = "BTC gaining dominance vs majors"
        elif btc_avg < others_avg * 0.98:
            msg = "alts gaining vs BTC (dominance softening)"
        else:
            msg = "BTC dominance roughly stable"

        return f"[correlation] {msg}"

    @staticmethod
    def summarize_correlations(
        price_series: dict[str, pd.Series],
    ) -> str:
        """Summarize SOL/BTC correlation over a recent window."""
        sol = price_series.get("SOLUSDT")
        btc = price_series.get("BTCUSDT")
        if sol is None or btc is None:
            return "[correlation] SOL/BTC: insufficient data"

        # Align on index and compute rolling correlation over the last ~7 days
        joined = sol.pct_change().tail(168).corr(btc.pct_change().tail(168))
        if pd.isna(joined):
            return "[correlation] SOL/BTC: insufficient data"

        if joined > 0.8:
            regime = "highly coupled"
        elif joined > 0.4:
            regime = "moderately correlated"
        elif joined > 0.1:
            regime = "weakly correlated / some decoupling"
        else:
            regime = "largely decoupled"

        return f"[correlation] SOL/BTC correlation={joined:.2f} ({regime})"
