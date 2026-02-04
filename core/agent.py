"""LangGraph state machine: PERCEIVE → REASON → ACT → REFLECT → DONE."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from core.config import AppConfig
from core.memory import MemoryStore
from core.policy_engine import PolicyEngine, PolicyViolation
from core.sandbox import Sandbox
from tools.binance_tool import BinanceTool
from tools.browser_tool import BrowserTool
from tools.history_tool import HistoryTool
from tools.position_tool import PositionTool
from tools.swap_tool import SwapTool
from tools.ta_tool import TATool
from tools.wallet_tool import WalletTool

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
) -> CompiledStateGraph:
    heavy_llm = ChatOpenAI(
        model=config.llm.heavy_model,
        openai_api_key=config.llm.api_key,  # type: ignore[arg-type]
        base_url=config.llm.base_url,
        temperature=0.3,
        max_tokens=2048,  # type: ignore[arg-type]
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
            except Exception as exc:
                chunks.append(f"[{url}] scrape failed: {exc}")
                logger.warning("    → scrape failed: %s", exc)

        # 2. Binance klines + TA indicators
        for symbol in _DEFAULT_SYMBOLS:
            logger.info("  fetching klines %s …", symbol)
            try:
                df = binance_tool.get_klines(symbol=symbol)
                df = ta_tool.enrich(df)
                summary = ta_tool.summarize(df, symbol=symbol)
                chunks.append(summary)
                logger.info("    → %d candles enriched", len(df))
            except Exception as exc:
                chunks.append(f"[{symbol}] binance/TA failed: {exc}")
                logger.warning("    → binance/TA failed: %s", exc)

        logger.info("  perceive complete — %d observation chunks", len(chunks))
        observations = "\n\n".join(chunks)
        # Reset per-run step counters at the start of each invocation.
        # Also persist the latest observations into memory so the benchmark
        # helper can derive close prices for BTC/SOL even before REASON runs.
        mem_state = memory.load()
        mem_state["last_observations"] = observations
        memory.save(mem_state)
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
        "Every run you receive live OHLCV kline data from Binance (1h candles, 100 bars) "
        "for BTCUSDT, ETHUSDT, and SOLUSDT. This data is automatically enriched with "
        "technical indicators before you see it:\n"
        "  Trend: SMA20, SMA50, EMA20, MACD, MACD signal, MACD histogram\n"
        "  Momentum: RSI, Stochastic K & D\n"
        "  Volatility: Bollinger Bands (upper/lower), ATR\n"
        "  Volume: OBV, VWAP\n"
        "Read these signals carefully. If any indicator is interesting or unclear, "
        "use analyze to dig deeper. That costs you nothing.\n\n"

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
            # Very lightweight parsing: look for lines like
            # "[SOLUSDT] close=123.4567" etc. in today's observations.
            for line in str(mem_state.get("last_observations", "")).splitlines():
                if line.startswith("[SOLUSDT] close="):
                    sol_price = float(line.split("close=")[1])
                elif line.startswith("[BTCUSDT] close="):
                    prices["BTC"] = float(line.split("close=")[1])
            if sol_price is not None:
                prices["SOL"] = sol_price
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

                # Approximate USD notional for policy using SOL price if available.
                mem_state = memory.load()
                sol_price = None
                for line in str(mem_state.get("last_observations", "")).splitlines():
                    if line.startswith("[SOLUSDT] close="):
                        sol_price = float(line.split("close=")[1])
                        break
                amount_usd = amount_sol * sol_price if sol_price is not None else amount_sol
                policy.check_swap(from_token, to_token, amount_usd)

                # Convert SOL amount to lamports for input; for non-SOL tokens we
                # still treat amount_sol as the SOL-equivalent notional for now.
                lamports = int(amount_sol * 1_000_000_000)
                sig = swap_tool.swap(from_token, to_token, lamports, slippage_bps=slippage_bps)

                # Update in-memory positions: assume we swapped amount_sol worth of
                # from_token into to_token at current SOL price.
                prices = {"SOL": sol_price or 0.0, "USDC": 1.0}
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
                    }
                )
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
