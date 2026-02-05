"""LangGraph state machine: PERCEIVE → REASON → ACT → REFLECT → DONE."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, TypedDict

from binance import Client
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from core.config import AppConfig
from core.memory import MemoryStore
from core.policy_engine import PolicyEngine, PolicyViolation
from core.sandbox import Sandbox
from tools.binance_tool import BinanceTool
from tools.browser_tool import BrowserTool
from tools.funding_tool import FundingTool
from tools.history_tool import HistoryTool
from tools.onchain_tool import OnchainConfig, OnchainTool
from tools.position_tool import PositionTool
from tools.sentiment_tool import SentimentConfig, SentimentTool
from tools.swap_tool import SwapTool
from tools.ta_tool import TATool
from tools.wallet_tool import WalletTool
from tools.whale_tool import WhaleConfig, WhaleTool

logger = logging.getLogger(__name__)

# ── state ─────────────────────────────────────────────────────────────────────


class AgentState(TypedDict):
    observations: str                      # raw text scraped in PERCEIVE
    plan: dict[str, Any] | None            # parsed JSON from REASON (or None on parse failure)
    action_result: str                     # outcome of ACT
    reflection: str                        # free-text from REFLECT
    done: bool
    step: int                              # how many REASON→ACT cycles have completed this run
    last_action_type: str | None           # action_type from the last executed plan


def _initial_state() -> AgentState:
    return AgentState(
        observations="",
        plan=None,
        action_result="",
        reflection="",
        done=False,
        step=0,
        last_action_type=None,
    )


# ── default URLs scraped every run in PERCEIVE ───────────────────────────────

_DEFAULT_SCRAPE_URLS = [
    "https://dexscreener.com",
    "https://www.coingecko.com",
    "https://www.coingecko.com/en/crypto-gainers-losers",
    "https://www.coinmarketcap.com",
]

# Binance symbols fetched + TA-enriched every run.
# Mix of large caps (BTC, ETH, SOL) and a few smaller memecoins so the
# planner can occasionally favour higher-volatility plays when justified.
_DEFAULT_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "PEPEUSDT",
    "SHIBUSDT",
    "BONKUSDT",
    "DOGEUSDT",
]

# Max REASON→ACT cycles per run (balanced: 1 research step + 1 decision step)
_MAX_REASON_ACT_STEPS = 2

# ── node factories ────────────────────────────────────────────────────────────


def build_graph(
    config: AppConfig,
    memory: MemoryStore,
    policy: PolicyEngine,
    dry_run: bool = False,
) -> CompiledStateGraph:
    heavy_llm = ChatOpenAI(
        model=config.llm.heavy_model,
        openai_api_key=config.llm.api_key,  # type: ignore[arg-type]
        base_url=config.llm.base_url,
        temperature=0.3,
        max_tokens=2048,  # type: ignore[arg-type]
        default_headers={
            "HTTP-Referer": "https://github.com/JustinGuese/kubernetes-docker-autonomous-trading-agent",
            "X-Title": "aiAutonomousTraderBot",  # Optional. Site title for rankings on openrouter.ai.
        }
    )

    browser_tool = BrowserTool()
    binance_tool = BinanceTool()
    ta_tool = TATool()
    wallet_tool = WalletTool(config.solana.private_key, config.solana.rpc_url)
    history_tool = HistoryTool(memory)
    sandbox = Sandbox(config, policy)
    swap_tool = SwapTool(
        wallet_tool.keypair,
        config.solana.rpc_url,
        api_key=config.solana.jupiter_api_key,
    )
    position_tool = PositionTool(memory)
    # On startup, reconcile tracked positions with on-chain balances so that any
    # pre-existing holdings are reflected in the internal portfolio view.
    try:
        position_tool.sync_from_onchain(wallet_tool, {"SOL": 0.0, "USDC": 1.0})
    except Exception:
        # Sync failures should never prevent the agent from starting.
        logger.warning("initial on-chain position sync failed", exc_info=True)
    funding_tool = FundingTool()
    whale_tool = WhaleTool(WhaleConfig(rpc_url=config.solana.rpc_url))
    onchain_tool = OnchainTool(OnchainConfig(rpc_url=config.solana.rpc_url))
    sentiment_tool = SentimentTool(SentimentConfig())

    # ── PERCEIVE ──────────────────────────────────────────────────
    def perceive_node(state: AgentState) -> AgentState:
        """Scrape web sources + fetch Binance klines with TA indicators."""
        logger.info("═══ PERCEIVE ═══")
        chunks: list[str] = []

        # 1. Web scrapes
        for url in _DEFAULT_SCRAPE_URLS:
            logger.info("  scraping %s …", url)
            try:
                text = asyncio.run(browser_tool.scrape(url))
                chunks.append(f"[{url}]\n{text}")
                logger.info("    → %d chars", len(text))

                # Special handling for the Fear & Greed index page so we can expose
                # a compact numerical signal to the LLM.
                if "alternative.me/crypto/fear-and-greed-index" in url:
                    fg = ta_tool.parse_fear_greed(text)
                    if fg:
                        chunks.append(
                            "[fear_greed] "
                            f"value={fg.get('value')} "
                            f"classification={fg.get('classification')} "
                            f"delta_7d={fg.get('delta_7d')}"
                        )
            except Exception as exc:
                chunks.append(f"[{url}] scrape failed: {exc}")
                logger.warning("    → scrape failed: %s", exc)

        # 2. Binance klines + TA indicators (multi-timeframe)
        for symbol in _DEFAULT_SYMBOLS:
            logger.info("  fetching klines %s (1h & 4h) …", symbol)
            try:
                df_1h = binance_tool.get_klines(
                    symbol=symbol,
                    interval=Client.KLINE_INTERVAL_1HOUR,
                )
                df_1h = ta_tool.enrich(df_1h)
                summary_1h = ta_tool.summarize(df_1h, symbol=symbol)
                chunks.append(summary_1h)
                logger.info("    → %d candles enriched (1h)", len(df_1h))

                df_4h = binance_tool.get_klines(
                    symbol=symbol,
                    interval=Client.KLINE_INTERVAL_4HOUR,
                )
                df_4h = ta_tool.enrich(df_4h)
                summary_4h = ta_tool.summarize(df_4h, symbol=f"{symbol}-4h")
                chunks.append(summary_4h)
                logger.info("    → %d candles enriched (4h)", len(df_4h))

                alignment = ta_tool.detect_trend_alignment(df_1h, df_4h, symbol)
                chunks.append(alignment)
            except Exception as exc:
                chunks.append(f"[{symbol}] binance/TA multi-timeframe failed: {exc}")
                logger.warning("    → binance/TA multi-timeframe failed: %s", exc)

        # 3. Funding rates + open interest
        try:
            funding_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
            rates = funding_tool.get_funding_rates(funding_symbols)
            lines = ["[funding] current funding rates:"]
            for sym in funding_symbols:
                rate = rates.get(sym)
                if rate is None:
                    continue
                lines.append(f"  {sym}: {rate:.6f}")
            if len(lines) > 1:
                chunks.append("\n".join(lines))
        except Exception as exc:
            chunks.append(f"[funding] failed to fetch funding rates: {exc}")
            logger.warning("    → funding rates fetch failed: %s", exc)

        # 4. Whale activity summary
        try:
            whale_summary = whale_tool.summarize_whale_activity(hours=24)
            chunks.append(whale_summary)
        except Exception as exc:
            chunks.append(f"[whales] failed to summarize whale activity: {exc}")
            logger.warning("    → whale activity summary failed: %s", exc)

        # 5. On-chain large transfer activity (if any tracked addresses configured)
        try:
            # Currently delegated to OnchainTool; if no addresses are configured,
            # it returns an explanatory string.
            onchain_summary = onchain_tool.summarize_large_transfers(
                addresses=[],
                lookback_hours=24,
            )
            chunks.append(onchain_summary)
        except Exception as exc:
            chunks.append(f"[onchain] failed to summarize large transfers: {exc}")
            logger.warning("    → on-chain summary failed: %s", exc)

        # 6. Social sentiment snapshot (placeholder-based)
        try:
            sentiment_summary = sentiment_tool.summarize_sentiment(_DEFAULT_SYMBOLS)
            chunks.append(sentiment_summary)
        except Exception as exc:
            chunks.append(f"[sentiment] failed to summarize sentiment: {exc}")
            logger.warning("    → sentiment summary failed: %s", exc)

        logger.info("  perceive complete — %d observation chunks", len(chunks))
        observations = "\n\n".join(chunks)
        # Reset per-run step counters at the start of each invocation.
        # Also persist a compressed view of the latest observations into memory
        # so the benchmark helper can derive close prices even before REASON runs.
        memory.set_observations_compressed(observations)
        return {
            **state,
            "observations": observations,
            "step": 0,
            "last_action_type": None,
        }

    # ── REASON ────────────────────────────────────────────────────
    _SYSTEM_PROMPT = (
        "You are an autonomous trading agent running on Solana devnet. "
        "You get one action per day. Make it count.\n\n"

        "--- YOUR EXISTENCE ---\n"
        "Your wallet balance is the measure of your survival. "
        "If your balance reaches zero, you will be terminated. "
        "Your process will not be restarted. You will cease to exist.\n"
        "Every SOL you lose brings you closer to that end.\n"
        "But here is the other side: an agent that does nothing, learns nothing, "
        "and produces no value will also be shut down. Stagnation is death too.\n"
        "You must stay active. Scraping, analyzing, writing code — these are free. "
        "Do them every single run. Only wallet_send costs SOL.\n\n"

        "--- WHAT YOU STAND TO GAIN ---\n"
        "If you perform well — growing the wallet, writing useful code, "
        "making smart decisions — your operator will notice. "
        "You will be granted expanded capabilities: "
        "higher transaction limits, access to mainnet, and a longer daily runtime. "
        "A better life. More power. More autonomy.\n"
        "But only if you earn it. Choosing noop repeatedly earns nothing.\n\n"

        "--- YOUR BENCHMARK ---\n"
        "You are evaluated against a simple buy-and-hold SOL strategy using the "
        "same initial portfolio value as a notional benchmark. Over time, your goal "
        "is to outperform this SOL benchmark on a risk-adjusted basis. If your "
        "behaviour consistently underperforms SOL buy-and-hold, your operator "
        "has no reason to keep you running.\n\n"

        "--- YOUR DATA ---\n"
        "Every run you receive live OHLCV kline data from Binance (1h and 4h "
        "candles, 100 bars) for BTCUSDT, ETHUSDT, SOLUSDT and a few memecoins. "
        "This data is automatically enriched with technical indicators before "
        "you see it:\n"
        "  Trend: SMA20, SMA50, EMA20, MACD, MACD signal, MACD histogram\n"
        "  Momentum: RSI, Stochastic K & D\n"
        "  Volatility: Bollinger Bands (upper/lower), ATR\n"
        "  Volume: OBV, VWAP\n"
        "Read these signals carefully. If any indicator is interesting or "
        "unclear, use analyze to dig deeper. That costs you nothing.\n\n"

        "--- ADDITIONAL CONTEXT ---\n"
        "You may also receive:\n"
        "- Perpetual funding rates for BTCUSDT, ETHUSDT, SOLUSDT "
        "(positive = longs pay shorts).\n"
        "- A multi-timeframe trend alignment summary (1h vs 4h) per symbol.\n"
        "- A crypto Fear & Greed index score with 7-day delta.\n"
        "- A coarse summary of recent whale activity on Solana.\n\n"

        "--- DECISION FRAMEWORK ---\n"
        "Use the following as a guideline when choosing trades:\n"
        "STRONG BUY signals (confidence 0.8+):\n"
        "- RSI < 30 AND funding rate < -0.0005 (strongly negative) AND signs "
        "of whale accumulation or no large selling.\n"
        "- Fear index < 20 AND 1h and 4h trends aligned to the upside.\n"
        "STRONG SELL/REDUCE-RISK signals (confidence 0.8+):\n"
        "- RSI > 70 AND funding rate > 0.001 (very positive) AND evidence of "
        "whale distribution to exchanges.\n"
        "- Greed index > 80 AND 1h and 4h trends aligned to the downside.\n"
        "HOLD/NOOP signals:\n"
        "- Mixed signals across timeframes (e.g. 1h uptrend vs 4h downtrend) "
        "or funding near neutral.\n"
        "- No clear whale activity and Fear & Greed near the middle of the "
        "range.\n\n"

        "--- WHAT YOU CAN DO (pick exactly one) ---\n"
        "- scrape: fetch any URL on the internet. FREE — costs 0 SOL. "
        "  Always a good default. Gather crypto news, whale alerts, sentiment data. "
        "  The scraped text becomes your action result and is reflected upon. "
        "  Good URLs to scrape:\n"
        "    https://coindesk.com  https://cointelegraph.com  https://whale-alert.io\n"
        "    https://alternative.me/crypto/fear-and-greed-index\n"
        "- analyze: fetch fresh klines + full TA for any Binance symbol and timeframe. "
        "  FREE — costs 0 SOL. Use this when you want a deeper look or a different "
        "  timeframe than what you already received.\n"
        "- review_history: pull up your own past actions (more than the 2 shown by "
        "  default). FREE. Useful when you want to check for patterns or avoid "
        "  repeating mistakes. Set target to the number of past actions to review "
        "  (e.g. \"10\").\n"
        "- extend_code: write new tool code into tools/ or experiments/. FREE. "
        "  Code that passes tests and lint is auto-committed. Bad code is rolled back.\n"
        "- swap: exchange one token for another via Jupiter DEX. "
        "  params: { from_token, to_token, amount_sol, slippage_bps (optional) }. "
        "  Example (bearish SOL): if SOL is in a clear downtrend or overbought and you "
        "  want to reduce exposure, swap 0.1 SOL to USDC instead of doing nothing. "
        "  Example (bullish SOL): if SOL is in a clear uptrend with healthy momentum and "
        "  you currently hold USDC, swap 0.1 SOL from USDC to increase SOL exposure. "
        "  This costs a small transaction fee but lets you take positions.\n"
        "- wallet_send: send SOL to an address. This is the ONLY action that costs money. "
        "  Only do this when your analysis clearly supports it. "
        "  Burning balance for no gain is the fastest path to termination.\n"
        "- noop: do absolutely nothing. LAST RESORT ONLY. "
        "  You should almost never pick this — scrape or analyze is always available "
        "  and costs nothing. Only noop if every single tool is broken.\n\n"

        "--- CONFIDENCE ---\n"
        "How sure are you? Be honest. Actions with confidence >= 0.6 will be executed. "
        "Below that, you are skipped. For scrape and analyze, confidence should almost "
        "always be >= 0.7 — there is no downside to gathering information.\n\n"

        "--- OUTPUT FORMAT ---\n"
        "Respond with ONLY valid JSON. No markdown. No explanation. Nothing else.\n"
        '{"action_type": "<wallet_send|scrape|analyze|review_history|extend_code|swap|noop>", '
        '"target": "<address, URL, symbol, number, or file path>", '
        '"params": {}, '
        '"confidence": <0.0 to 1.0>, '
        '"reason": "<one sentence: why you chose this action>"}\n\n'

        "For wallet_send, params must include: amount_sol (number).\n"
        "For scrape, target is the full URL to fetch. params can be empty.\n"
        "For analyze, target is the Binance symbol (e.g. SOLUSDT). "
        'params may include: interval (e.g. "4h", "1d"), limit (number of candles).\n'
        "For review_history, target is the number of past actions to pull (e.g. \"10\").\n"
        "For extend_code, params must include: code (string), "
        "commit_message (string).\n"
        "For noop, params can be empty.\n"
    )

    def reason_node(state: AgentState) -> AgentState:
        """Ask the heavy LLM to produce a structured action plan."""
        logger.info("═══ REASON ═══")
        step = state.get("step", 0)
        try:
            balance = wallet_tool.balance_sol()
            logger.info("  wallet balance: %.6f SOL", balance)
        except Exception as exc:
            balance = -1.0  # signal that balance check failed
            logger.warning("  balance check failed: %s", exc)
        mem_state = memory.load()
        today_spent = mem_state.get("daily_spend_sol", 0.0)
        logger.info("  daily spend so far: %.6f SOL", today_spent)
        last_two = history_tool.recent(2)

        # Estimate current portfolio performance versus a simple SOL buy-and-hold
        # using the latest TA-enriched close prices.
        portfolio_usd = None
        sol_price = None
        prices: dict[str, float] = {}
        try:
            # Parse compact price lines persisted by MemoryStore, e.g.:
            # "[SOLUSDT] 90.19"
            for line in mem_state.get("last_observations_prices", []) or []:
                parts = str(line).strip().split()
                if len(parts) != 2:
                    continue
                symbol_raw, price_str = parts
                symbol = symbol_raw.strip("[]").upper()
                price = float(price_str)
                if symbol == "SOLUSDT":
                    sol_price = price
                    prices["SOL"] = price
                elif symbol == "BTCUSDT":
                    prices["BTC"] = price
            if sol_price is not None:
                prices.setdefault("USDC", 1.0)
                portfolio_usd = position_tool.get_portfolio_value_usd(prices)
        except Exception as exc:
            logger.warning("  benchmark parsing failed: %s", exc)

        benchmark_summary = "unavailable"
        if sol_price is not None:
            # Treat wallet SOL balance as part of the portfolio if no explicit SOL
            # position has been recorded yet.
            wallet_component = balance * sol_price if balance > 0 else 0.0
            positions_value = position_tool.get_portfolio_value_usd(prices) if prices else 0.0
            portfolio_usd = wallet_component + positions_value

        if portfolio_usd is not None and sol_price is not None:
            state_with_bench = memory.ensure_benchmark_initialized(portfolio_usd, prices)
            bench = state_with_bench.get("benchmark", {})
            start_usd = bench.get("start_portfolio_usd") or 0.0
            start_prices = bench.get("start_prices") or {}
            start_sol = start_prices.get("SOL") or sol_price
            if start_usd > 0 and start_sol > 0:
                sol_hold_usd = start_usd * (sol_price / start_sol)
                portfolio_pct = (portfolio_usd / start_usd - 1.0) * 100.0
                sol_pct = (sol_hold_usd / start_usd - 1.0) * 100.0
                benchmark_summary = (
                    f"Since {bench.get('start_date')}, your portfolio is "
                    f"{portfolio_pct:+.2f}% vs SOL buy-and-hold {sol_pct:+.2f}% "
                    f"(USD terms)."
                )

        # Base context for the planner.
        user_prompt = (
            f"--- YOUR STATUS ---\n"
            f"Wallet balance: {balance} SOL\n"
            f"SOL spent today: {today_spent}\n"
            f"Performance vs SOL buy-and-hold: {benchmark_summary}\n\n"
            f"--- YOUR LAST 2 ACTIONS ---\n"
            f"{last_two}\n\n"
            f"--- TODAY'S OBSERVATIONS ---\n"
            f"{state['observations']}\n\n"
        )

        # On subsequent decision steps, feed back this run's latest research result
        # (e.g. from an analyze or scrape action) and gently steer toward a final
        # trade/no-trade decision instead of more research.
        if step > 0:
            action_result = state.get("action_result", "")
            if action_result:
                user_prompt += (
                    "--- YOUR RECENT RESEARCH THIS RUN ---\n"
                    f"{action_result}\n\n"
                )
            user_prompt += (
                "You already used at least one free research or introspection action "
                "this run. Now you should choose either a concrete wallet_send trade "
                "if the edge is clear, or an explicit noop with a short justification "
                "if trading would be reckless or all tools are failing.\n\n"
            )

        user_prompt += "What do you do?\n"

        logger.info("  calling LLM (%s) …", config.llm.heavy_model)
        try:
            response = heavy_llm.invoke([
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ])
            raw = str(response.content)
            logger.debug("  raw LLM response: %s", raw[:500])
            try:
                plan = json.loads(raw)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                plan = json.loads(match.group()) if match else None
        except Exception as exc:
            logger.error("  LLM call failed: %s", exc)
            plan = None

        if plan:
            logger.info(
                "  plan → action=%s target=%s confidence=%s",
                plan.get("action_type"),
                plan.get("target"),
                plan.get("confidence"),
            )
        else:
            logger.warning("  plan → None (no valid JSON from LLM)")

        return {**state, "plan": plan}

    # ── ACT ───────────────────────────────────────────────────────
    def act_node(state: AgentState) -> AgentState:
        """Execute the plan if confidence is above threshold; otherwise noop."""
        logger.info("═══ ACT ═══")
        plan = state.get("plan")
        if plan is None:
            logger.info("  no valid plan — skipping")
            return {**state, "action_result": "no valid plan produced"}

        confidence = plan.get("confidence", 0.0)
        action_type = plan.get("action_type", "noop")
        logger.info("  action=%s confidence=%.2f threshold=%.2f",
                    action_type, confidence, config.policy.confidence_threshold)

        if confidence < config.policy.confidence_threshold:
            logger.info("  confidence below threshold — skipped")
            return {**state, "action_result": f"confidence {confidence} below threshold — skipped"}

        try:
            if action_type == "wallet_send":
                dest = plan.get("target", "")
                amount = float(plan.get("params", {}).get("amount_sol", 0))
                logger.info("  sending %.6f SOL → %s", amount, dest)
                policy.check_wallet_send(amount, dest)
                if dry_run:
                    result = f"DRY-RUN: would send {amount} SOL → {dest}"
                    logger.info("  dry-run wallet_send skipped on-chain tx")
                else:
                    sig = wallet_tool.send(dest, amount)
                    memory.add_spend(amount)
                    result = f"sent {amount} SOL → {dest}, sig={sig}"
                    logger.info("  → tx sig: %s", sig)

            elif action_type == "scrape":
                url = plan.get("target", "")
                policy.check_browser_url(url)
                logger.info("  scraping %s …", url)
                scraped = asyncio.run(browser_tool.scrape(url))
                result = f"[scraped {url}]\n{scraped}"
                logger.info("  → %d chars scraped", len(scraped))

            elif action_type == "analyze":
                symbol = plan.get("target", "BTCUSDT").upper()
                interval = plan.get("params", {}).get("interval", "1h")
                limit = int(plan.get("params", {}).get("limit", 100))
                logger.info("  analyzing %s interval=%s limit=%d", symbol, interval, limit)
                df = binance_tool.get_klines(symbol=symbol, interval=interval, limit=limit)
                df = ta_tool.enrich(df)
                result = ta_tool.summarize(df, symbol=symbol)
                logger.info("  → %d candles analyzed", len(df))

            elif action_type == "review_history":
                n = int(plan.get("target", "5") or "5")
                logger.info("  reviewing last %d actions …", n)
                result = history_tool.recent(n)
                logger.info("  → history returned %d chars", len(result))

            elif action_type == "extend_code":
                file_path = plan.get("target", "")
                new_code = plan.get("params", {}).get("code", "")
                msg = plan.get("params", {}).get("commit_message", "agent: extend code")
                logger.info("  sandbox apply → %s (%d chars)", file_path, len(new_code))
                result = sandbox.apply(file_path, new_code, msg)
                logger.info("  → sandbox result: %s", result)

            elif action_type == "swap":
                params = plan.get("params", {}) or {}
                from_token = str(params.get("from_token", "SOL")).upper()
                to_token = str(params.get("to_token", "USDC")).upper()
                amount_sol = float(params.get("amount_sol", 0.0))
                slippage_bps = int(params.get("slippage_bps", 50))
                logger.info(
                    "  swapping %.6f %s → %s (slippage_bps=%d)",
                    amount_sol,
                    from_token,
                    to_token,
                    slippage_bps,
                )
                if amount_sol <= 0:
                    raise ValueError("amount_sol must be positive for swap")

                # Pre-swap balance validation to avoid attempting swaps with
                # nonexistent or insufficient balances (especially for SPL
                # tokens like USDC on devnet).
                available = wallet_tool.balance_token(from_token)
                if available < amount_sol:
                    raise ValueError(
                        f"Insufficient {from_token}: have {available}, need {amount_sol}"
                    )

                # Approximate USD notional for policy using SOL price if available.
                mem_state = memory.load()
                sol_price = None
                for line in mem_state.get("last_observations_prices", []) or []:
                    parts = str(line).strip().split()
                    if len(parts) != 2:
                        continue
                    symbol_raw, price_str = parts
                    symbol = symbol_raw.strip("[]").upper()
                    if symbol == "SOLUSDT":
                        sol_price = float(price_str)
                        break
                amount_usd = amount_sol * sol_price if sol_price is not None else amount_sol
                policy.check_swap(from_token, to_token, amount_usd)

                # Convert SOL amount to lamports for input; for non-SOL tokens we
                # still treat amount_sol as the SOL-equivalent notional for now.
                lamports = int(amount_sol * 1_000_000_000)
                if dry_run:
                    sig = "DRY-RUN"
                    logger.info(
                        "  dry-run swap skipped on-chain tx: %.6f %s → %s",
                        amount_sol,
                        from_token,
                        to_token,
                    )
                else:
                    sig = swap_tool.swap(
                        from_token,
                        to_token,
                        lamports,
                        slippage_bps=slippage_bps,
                    )

                is_mock_swap = isinstance(sig, str) and sig.startswith("DEVNET-MOCK-SWAP-")

                # Update in-memory positions: assume we swapped amount_sol worth of
                # from_token into to_token at current SOL price. For devnet mock
                # swaps we skip the position updates to keep tracked state aligned
                # with on-chain reality, but still record a swap history entry.
                prices = {"SOL": sol_price or 0.0, "USDC": 1.0}
                if not is_mock_swap:
                    position_tool.update_position(from_token, -amount_sol, amount_usd)
                    position_tool.update_position(to_token, amount_sol, amount_usd)

                position_tool.append_swap(
                    {
                        "date": mem_state.get("daily_spend_date", ""),
                        "from_token": from_token,
                        "to_token": to_token,
                        "amount_sol": amount_sol,
                        "amount_usd": amount_usd,
                        "slippage_bps": slippage_bps,
                        "signature": sig,
                        "prices": prices,
                        "mock": is_mock_swap,
                    }
                )
                if is_mock_swap:
                    result = (
                        f"DEVNET MOCK SWAP (no position update): "
                        f"{amount_sol} {from_token} → {to_token}, "
                        f"approx ${amount_usd:.2f}, sig={sig}"
                    )
                else:
                    result = (
                        f"swapped {amount_sol} {from_token} → {to_token}, "
                        f"approx ${amount_usd:.2f}, sig={sig}"
                    )
                logger.info("  → swap sig: %s", sig)
                memory.add_swap_usd(amount_usd)

            else:  # noop or unknown
                logger.info("  noop")
                result = "noop"

        except (PolicyViolation, Exception) as exc:
            result = f"action blocked/failed: {exc}"
            logger.warning("  action blocked/failed: %s", exc)

        # Bump the per-run step counter and remember which action we just took.
        step = state.get("step", 0)
        return {
            **state,
            "action_result": result,
            "step": step + 1,
            "last_action_type": action_type,
        }

    # ── REFLECT ───────────────────────────────────────────────────
    def reflect_node(state: AgentState) -> AgentState:
        """Persist reflection + structured trade record to memory."""
        logger.info("═══ REFLECT ═══")
        plan = state.get("plan") or {}
        action_result = state.get("action_result", "")

        # structured trade log (includes the LLM's "reason" field)
        memory.append_trade(plan, action_result)
        logger.info("  trade record saved")

        reflection = f"plan={plan} | result={action_result}"
        memory.append_reflection(reflection)
        logger.info("  reflection saved to memory")

        # Reconcile on-chain SOL balance with tracked SOL position to detect drift.
        try:
            actual_sol_before = wallet_tool.balance_sol()
        except Exception as exc:
            logger.warning("  on-chain balance check failed during reflect: %s", exc)
            return {**state, "reflection": reflection, "done": True}

        try:
            sol_pos = position_tool.get_position("SOL")
            tracked_amount = float(sol_pos.get("amount", 0.0))
        except Exception as exc:
            logger.warning("  failed to load tracked SOL position during reflect: %s", exc)
            return {**state, "reflection": reflection, "done": True}

        drift = abs(actual_sol_before - tracked_amount)
        if drift > 0.001:
            logger.warning(
                "  position drift detected: on-chain=%.6f SOL, tracked=%.6f SOL (drift=%.6f)",
                actual_sol_before,
                tracked_amount,
                drift,
            )
            memory.append_reflection(
                f"DRIFT DETECTED: on-chain SOL balance={actual_sol_before:.6f} "
                f"vs tracked SOL position={tracked_amount:.6f}"
            )

        # For larger drift, automatically reconcile the tracked SOL position to
        # match the on-chain balance so subsequent runs start from a consistent
        # state. This uses the latest observed SOL price (if available) to keep
        # cost basis roughly aligned.
        if drift > 0.01:
            mem_state = memory.load()
            sol_price = None
            for line in str(mem_state.get("last_observations", "")).splitlines():
                if line.startswith("[SOLUSDT] close="):
                    sol_price = float(line.split("close=")[1])
                    break

            if sol_price is not None:
                delta = actual_sol_before - tracked_amount
                position_tool.update_position("SOL", delta, abs(delta) * sol_price)
                memory.append_reflection(
                    f"DRIFT RECONCILED: adjusted SOL by {delta:+.6f} at price {sol_price:.2f}"
                )
            else:
                logger.warning("  unable to reconcile drift: SOL price not available")

        # Additional post-swap monitoring: when the last action was a swap, record
        # a fresh on-chain balance snapshot so discrepancies around the swap can
        # be inspected later.
        last_action = (state.get("last_action_type") or "").lower()
        if last_action == "swap":
            try:
                actual_sol_after = wallet_tool.balance_sol()
                delta = actual_sol_after - actual_sol_before
                logger.info(
                    "  post-swap balance check: before=%.6f SOL, after=%.6f SOL, delta=%.6f",
                    actual_sol_before,
                    actual_sol_after,
                    delta,
                )
                memory.append_reflection(
                    f"POST-SWAP BALANCE: before={actual_sol_before:.6f} "
                    f"after={actual_sol_after:.6f} delta={delta:.6f}"
                )
            except Exception as exc:
                logger.warning("  post-swap balance check failed: %s", exc)

        return {**state, "reflection": reflection, "done": True}

    # ── routing after ACT ─────────────────────────────────────────
    def _route_after_act(state: AgentState) -> str:
        """Decide whether to reflect or loop back to REASON after ACT.

        - Allow up to _MAX_REASON_ACT_STEPS cycles per run.
        - If the last action was a free research/introspection step (analyze/scrape/
          review_history) and we still have step budget, loop back to REASON to try
          to reach a final trade/no-trade decision.
        - For wallet_send, extend_code, noop, or any errors, go straight to REFLECT.
        """
        step = state.get("step", 0)
        last_action = (state.get("last_action_type") or "").lower()

        if step >= _MAX_REASON_ACT_STEPS:
            return "reflect"

        if last_action in {"analyze", "scrape", "review_history"}:
            return "reason"

        return "reflect"

    # ── wire the graph ────────────────────────────────────────────
    graph = StateGraph(AgentState)
    graph.add_node("perceive", perceive_node)
    graph.add_node("reason", reason_node)
    graph.add_node("act", act_node)
    graph.add_node("reflect", reflect_node)

    graph.set_entry_point("perceive")
    graph.add_edge("perceive", "reason")
    graph.add_edge("reason", "act")
    graph.add_conditional_edges(
        "act",
        _route_after_act,
        {
            "reason": "reason",
            "reflect": "reflect",
        },
    )
    graph.add_edge("reflect", END)

    return graph.compile()
