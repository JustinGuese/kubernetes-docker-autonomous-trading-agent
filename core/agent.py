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
from tools.ta_tool import TATool
from tools.wallet_tool import WalletTool

logger = logging.getLogger(__name__)

# ── state ─────────────────────────────────────────────────────────────────────


class AgentState(TypedDict):
    observations: str                     # raw text scraped in PERCEIVE
    plan: dict[str, Any] | None           # parsed JSON from REASON (or None on parse failure)
    action_result: str                    # outcome of ACT
    reflection: str                       # free-text from REFLECT
    done: bool


def _initial_state() -> AgentState:
    return AgentState(
        observations="",
        plan=None,
        action_result="",
        reflection="",
        done=False,
    )


# ── default URLs scraped every run in PERCEIVE ───────────────────────────────

_DEFAULT_SCRAPE_URLS = [
    "https://dexscreener.com",
    "https://www.coingecko.com",
    "https://www.coinmarketcap.com",
]

# Binance symbols fetched + TA-enriched every run
_DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

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
        return {**state, "observations": "\n\n".join(chunks)}

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
        '{"action_type": "<wallet_send|scrape|analyze|review_history|extend_code|noop>", '
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

        user_prompt = (
            f"--- YOUR STATUS ---\n"
            f"Wallet balance: {balance} SOL\n"
            f"SOL spent today: {today_spent}\n\n"
            f"--- YOUR LAST 2 ACTIONS ---\n"
            f"{last_two}\n\n"
            f"--- TODAY'S OBSERVATIONS ---\n"
            f"{state['observations']}\n\n"
            f"What do you do?\n"
        )

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

            else:  # noop or unknown
                logger.info("  noop")
                result = "noop"

        except (PolicyViolation, Exception) as exc:
            result = f"action blocked/failed: {exc}"
            logger.warning("  action blocked/failed: %s", exc)

        return {**state, "action_result": result}

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

    # ── wire the graph ────────────────────────────────────────────
    graph = StateGraph(AgentState)
    graph.add_node("perceive", perceive_node)
    graph.add_node("reason", reason_node)
    graph.add_node("act", act_node)
    graph.add_node("reflect", reflect_node)

    graph.set_entry_point("perceive")
    graph.add_edge("perceive", "reason")
    graph.add_edge("reason", "act")
    graph.add_edge("act", "reflect")
    graph.add_edge("reflect", END)

    return graph.compile()
