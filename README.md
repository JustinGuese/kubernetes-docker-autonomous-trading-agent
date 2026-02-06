# 🤖💰 aiAutonomousTraderBot

[![ci](https://github.com/JustinGuese/kubernetes-docker-autonomous-trading-agent/actions/workflows/main.yaml/badge.svg)](https://github.com/JustinGuese/kubernetes-docker-autonomous-trading-agent/actions/workflows/main.yaml)

> Want to support this bot and ongoing development? Want to save yourself on the day skynet takes over? Just send funds directly to his address and he will trade with it!

[![Crypto Payment](https://paybadge.profullstack.com/badge.svg)](https://paybadge.profullstack.com/?tickers=btc,eth,usdc&recipient_addresses=btc:bc1qt55phmqcsyq8v9xs68ulgqqgfdnl30dk4lth9m,sol:6rHuYnakzcnshsdm1Kyvr9fqH5pfvMHHd2c17cLazfR9,eth:0x628aFf1C99b22097F1776a135c6c85Bf8D171Bb8,pol:0x628aFf1C99b22097F1776a135c6c85Bf8D171Bb8)

SOLANA WALLET: 6rHuYnakzcnshsdm1Kyvr9fqH5pfvMHHd2c17cLazfR9

An autonomous trading agent on Solana devnet, powered by LLMs and LangGraph. The agent runs once per day (via K8s CronJob), scrapes market data, reasons about trades, executes transactions, and can write and deploy its own code. Survival is the primary metric: zero balance = termination.

He is currently (6.2.26) trading live on Solana mainnet! Watch his trades:

https://solscan.io/account/6rHuYnakzcnshsdm1Kyvr9fqH5pfvMHHd2c17cLazfR9

Started with 0.362377 SOL 

## An Autonomous, Self-Improving Trading Agent — Built for Survival

*Think openclaw / MoltBot — but for finance.*

A real autonomous agent that observes markets, reasons about trades, executes on-chain actions, and can modify and redeploy its own code under strict safety constraints.

## ⭐ Why This Repo Exists

Most “AI trading bots” are:

- rule-based
- overfit backtests
- fragile scripts with API keys

aiAutonomousTraderBot is different.

This project explores what happens when you give an LLM:

- real capital
- long-lived memory
- the ability to change its own tools
- hard survival constraints

…and let it operate autonomously in production.

**Primary metric:**

Survival.  
If the balance hits zero → the agent is terminated.

## 🔴 Live on Mainnet

The agent is currently trading live on Solana mainnet.

- Start date: 2026-02-06
- Wallet: https://solscan.io/account/6rHuYnakzcnshsdm1Kyvr9fqH5pfvMHHd2c17cLazfR9

You can independently verify:

- trades
- balances
- behavior over time

No screenshots. No cherry-picked backtests.

## 🧠 What This Agent Actually Does

Every run (CronJob, once per day):

**PERCEIVE → REASON → ACT → REFLECT**

### PERCEIVE

- Scrapes live market data (DEXs, CoinGecko, CMC, on-chain signals)
- Reads its own portfolio & historical performance

### REASON

- Uses an LLM via LangGraph
- Produces a structured, confidence-scored plan

### ACT

- Executes only if policy & confidence thresholds are satisfied
- Can:
  - send SOL
  - swap tokens (via Jupiter)
  - scrape new data
  - write and test new code
  - deploy changes to GitHub
  - do nothing (noop) if risk is too high

### REFLECT

- Writes a post-mortem into long-term memory
- Updates portfolio state
- Benchmarks itself against buy-and-hold

## 🧬 Key Idea: Constrained Self-Modification

This agent can change its own code — but only inside a sandbox:

- Writes only to tools/ or experiments/
- Runs:
  - tests (pytest)
  - lint (ruff)
- Rolls back automatically on failure
- Hard cap on lines of code per change
- GitHub token injected only at push time

This is not AutoGPT chaos.  
This is policy-driven, auditable autonomy.

🛡️ **Safety & Risk Controls (Non-Negotiable)**

- ✅ Daily spend caps (SOL + USD)
- ✅ Per-transaction limits
- ✅ LLM confidence gating
- ✅ Read-only core logic
- ✅ Atomic memory writes
- ✅ Drift detection between on-chain balance and internal state
- ✅ No shell access
- ✅ No unrestricted file I/O
- ✅ Domain allowlist for critical operations

The agent is incentivized to stay alive, not to YOLO.

## 🧱 Architecture Overview

```text
main.py
  ↓
LangGraph state machine
  ↓
[ PERCEIVE ] → [ REASON ] → [ ACT ] → [ REFLECT ]
  ↓
memory/state.json (atomic, persistent)
```

**Core Components**

| Component            | Purpose                          |
| -------------------- | -------------------------------- |
| core/agent.py        | LangGraph state machine          |
| core/policy_engine.py | Guards every risky action        |
| core/sandbox.py      | Safe self-modification pipeline  |
| core/memory.py       | Long-term agent memory           |
| tools/wallet_tool.py | SOL + SPL token ops              |
| tools/position_tool.py | Portfolio tracking               |
| tools/browser_tool.py | Playwright scraping               |
| tools/git_tool.py    | Controlled self-deployment       |
| policies/            | Human-readable constraints       |

## ⚙️ Quick Start

```bash
git clone <repo>
cd aiAutonomousTraderBot
pip install -e ".[dev]"
cp .env.example .env
```

Set at minimum:

```bash
OPENROUTER_API_KEY=...
SOLANA_PRIVATE_KEY=...
GITHUB_TOKEN=...
GITHUB_REPO=owner/repo
```

Run locally:

```bash
python main.py           # live
python main.py --dry-run # no on-chain actions
```

## 🐳 Docker & ☸️ Kubernetes

- Docker Compose for local runs
- Kubernetes CronJob for production
- Read-only mounts for core logic
- PVC-backed memory for persistence

```bash
docker compose up
```

CronJob runs daily at 09:00 UTC.

## 📈 Portfolio Awareness (Not Just Trades)

The agent tracks:

- per-token positions
- rough USD cost basis
- swap history
- slippage
- benchmark vs buy-and-hold

This portfolio summary is fed back into the LLM every run.

## 🧪 This Is a Research-Grade Codebase

- Extensive test coverage
- Deterministic policy layer
- Explicit threat model
- Designed for:
  - AI agents research
  - autonomous systems
  - on-chain finance
  - infra-aware LLM tooling

If you liked:

- openclaw
- MoltBot
- AutoGPT (the idea, not the chaos)

…this repo is for you.

# Live Output Example

  PERCEIVE — Gathered market data:                                                                           
  - Checked wallet: 0.362 SOL, 0 USDC, 0 WBTC                                                              
  - Scraped dexscreener (timed out), fell back to coinmarketcap (succeeded)                                  
  - Pulled 1h + 4h candles from Binance for 7 pairs (BTC, ETH, SOL, PEPE, SHIB, BONK, DOGE)                  
  - Fetched funding rates for BTC, ETH, SOL                                                                  
                                                                                                             
  REASON — LLM decided to sell a small amount of SOL:                                                        
  - SOL in downtrend on 4h, RSI near 30, negative funding rate                                               
  - Plan: swap 0.05 SOL to USDC at 0.65 confidence (above 0.60 threshold)                                    
                                                                                                             
  ACT — Executed the swap successfully:
  - Jupiter Ultra order + execute went through (HTTP 200)
  - Signature: 3dyvsj...piQ4
  - Swapped 0.05 SOL (~$4.12) to USDC

  REFLECT — Post-trade bookkeeping:
  - Saved trade record + reflection to memory
  - Detected position drift: on-chain shows 0.362 SOL but tracked state expected 0.312 SOL (the 0.05 SOL
  deduction hasn't settled yet or the balance check ran too fast)
  - Post-swap balance delta = 0.00 — the on-chain balance hadn't updated within that ~1 second window


Full Log:
```
15:18:27 [INFO] __main__: starting up (dry_run=False)
15:18:27 [INFO] __main__: config loaded — model=deepseek/deepseek-v3.2 rpc=https://api.mainnet-beta.solana.com
15:18:27 [INFO] tools.browser_tool: BrowserTool: will connect to remote CDP at http://localhost:3000
15:18:28 [INFO] tools.wallet_tool: fetching balance for 6rHuYnakzcnshsdm1Kyvr9fqH5pfvMHHd2c17cLazfR9
15:18:29 [INFO] httpx: HTTP Request: POST https://api.mainnet-beta.solana.com "HTTP/1.1 200 OK"
15:18:29 [INFO] tools.wallet_tool:   → 0.362377 SOL (362376904 lamports)
15:18:29 [INFO] tools.wallet_tool: fetching SPL token balance for USDC (EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v)
15:18:29 [INFO] httpx: HTTP Request: POST https://api.mainnet-beta.solana.com "HTTP/1.1 200 OK"
15:18:29 [INFO] tools.wallet_tool:   → no token accounts found for USDC
15:18:29 [INFO] tools.wallet_tool: fetching SPL token balance for WBTC (3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh)
15:18:29 [INFO] httpx: HTTP Request: POST https://api.mainnet-beta.solana.com "HTTP/1.1 200 OK"
15:18:29 [INFO] tools.wallet_tool:   → no token accounts found for WBTC
15:18:29 [INFO] tools.coingecko_tool: CoingeckoTool: using public CoinGecko API (no key)
15:18:29 [INFO] __main__: graph built — invoking
15:18:29 [INFO] core.agent: ═══ PERCEIVE ═══
15:18:29 [INFO] core.agent:   scraping https://dexscreener.com …
15:18:30 [INFO] tools.browser_tool: connecting to remote browser for https://dexscreener.com
(node:99885) [DEP0169] DeprecationWarning: `url.parse()` behavior is not standardized and prone to errors that have security implications. Use the WHATWG URL API instead. CVEs are not issued for `url.parse()` vulnerabilities.
(Use `node --trace-deprecation ...` to show where the warning was created)
15:19:09 [WARNING] tools.browser_tool: page load failed for https://dexscreener.com: Page.goto: Timeout 30000ms exceeded.
Call log:
  - navigating to "https://dexscreener.com/", waiting until "networkidle"

15:19:44 [WARNING] core.agent:     → scrape failed: Page.goto: Timeout 30000ms exceeded.
Call log:
  - navigating to "https://dexscreener.com/", waiting until "networkidle"

15:19:44 [INFO] core.agent:   scraping https://www.coinmarketcap.com …
15:19:44 [INFO] tools.browser_tool: connecting to remote browser for https://www.coinmarketcap.com
(node:99930) [DEP0169] DeprecationWarning: `url.parse()` behavior is not standardized and prone to errors that have security implications. Use the WHATWG URL API instead. CVEs are not issued for `url.parse()` vulnerabilities.
(Use `node --trace-deprecation ...` to show where the warning was created)
15:19:59 [INFO] tools.browser_tool: page load succeeded for https://www.coinmarketcap.com (status https://coinmarketcap.com/)
15:20:15 [INFO] tools.browser_tool: got 5275 chars
15:20:15 [INFO] core.agent:     → 5275 chars
15:20:15 [INFO] core.agent:   fetching klines BTCUSDT (1h & 4h) …
15:20:15 [INFO] tools.binance_tool: get_klines symbol=BTCUSDT interval=1h limit=100
15:20:15 [INFO] tools.binance_tool:   → 100 raw candles returned
15:20:16 [INFO] core.agent:     → 100 candles enriched (1h)
15:20:16 [INFO] tools.binance_tool: get_klines symbol=BTCUSDT interval=4h limit=100
15:20:16 [INFO] tools.binance_tool:   → 100 raw candles returned
15:20:16 [INFO] core.agent:     → 100 candles enriched (4h)
15:20:16 [INFO] core.agent:   fetching klines ETHUSDT (1h & 4h) …
15:20:16 [INFO] tools.binance_tool: get_klines symbol=ETHUSDT interval=1h limit=100
15:20:16 [INFO] tools.binance_tool:   → 100 raw candles returned
15:20:16 [INFO] core.agent:     → 100 candles enriched (1h)
15:20:16 [INFO] tools.binance_tool: get_klines symbol=ETHUSDT interval=4h limit=100
15:20:16 [INFO] tools.binance_tool:   → 100 raw candles returned
15:20:16 [INFO] core.agent:     → 100 candles enriched (4h)
15:20:16 [INFO] core.agent:   fetching klines SOLUSDT (1h & 4h) …
15:20:16 [INFO] tools.binance_tool: get_klines symbol=SOLUSDT interval=1h limit=100
15:20:16 [INFO] tools.binance_tool:   → 100 raw candles returned
15:20:16 [INFO] core.agent:     → 100 candles enriched (1h)
15:20:16 [INFO] tools.binance_tool: get_klines symbol=SOLUSDT interval=4h limit=100
15:20:16 [INFO] tools.binance_tool:   → 100 raw candles returned
15:20:16 [INFO] core.agent:     → 100 candles enriched (4h)
15:20:16 [INFO] core.agent:   fetching klines PEPEUSDT (1h & 4h) …
15:20:16 [INFO] tools.binance_tool: get_klines symbol=PEPEUSDT interval=1h limit=100
15:20:17 [INFO] tools.binance_tool:   → 100 raw candles returned
15:20:17 [INFO] core.agent:     → 100 candles enriched (1h)
15:20:17 [INFO] tools.binance_tool: get_klines symbol=PEPEUSDT interval=4h limit=100
15:20:17 [INFO] tools.binance_tool:   → 100 raw candles returned
15:20:17 [INFO] core.agent:     → 100 candles enriched (4h)
15:20:17 [INFO] core.agent:   fetching klines SHIBUSDT (1h & 4h) …
15:20:17 [INFO] tools.binance_tool: get_klines symbol=SHIBUSDT interval=1h limit=100
15:20:17 [INFO] tools.binance_tool:   → 100 raw candles returned
15:20:17 [INFO] core.agent:     → 100 candles enriched (1h)
15:20:17 [INFO] tools.binance_tool: get_klines symbol=SHIBUSDT interval=4h limit=100
15:20:18 [INFO] tools.binance_tool:   → 100 raw candles returned
15:20:18 [INFO] core.agent:     → 100 candles enriched (4h)
15:20:18 [INFO] core.agent:   fetching klines BONKUSDT (1h & 4h) …
15:20:18 [INFO] tools.binance_tool: get_klines symbol=BONKUSDT interval=1h limit=100
15:20:18 [INFO] tools.binance_tool:   → 100 raw candles returned
15:20:18 [INFO] core.agent:     → 100 candles enriched (1h)
15:20:18 [INFO] tools.binance_tool: get_klines symbol=BONKUSDT interval=4h limit=100
15:20:18 [INFO] tools.binance_tool:   → 100 raw candles returned
15:20:19 [INFO] core.agent:     → 100 candles enriched (4h)
15:20:19 [INFO] core.agent:   fetching klines DOGEUSDT (1h & 4h) …
15:20:19 [INFO] tools.binance_tool: get_klines symbol=DOGEUSDT interval=1h limit=100
15:20:19 [INFO] tools.binance_tool:   → 100 raw candles returned
15:20:19 [INFO] core.agent:     → 100 candles enriched (1h)
15:20:19 [INFO] tools.binance_tool: get_klines symbol=DOGEUSDT interval=4h limit=100
15:20:19 [INFO] tools.binance_tool:   → 100 raw candles returned
15:20:19 [INFO] core.agent:     → 100 candles enriched (4h)
15:20:21 [INFO] httpx: HTTP Request: GET https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT "HTTP/1.1 200 OK"
15:20:22 [INFO] httpx: HTTP Request: GET https://fapi.binance.com/fapi/v1/premiumIndex?symbol=ETHUSDT "HTTP/1.1 200 OK"
15:20:24 [INFO] httpx: HTTP Request: GET https://fapi.binance.com/fapi/v1/premiumIndex?symbol=SOLUSDT "HTTP/1.1 200 OK"
15:20:25 [INFO] core.agent:   perceive complete — 28 observation chunks
15:20:25 [INFO] core.agent: ═══ REASON ═══
15:20:25 [INFO] tools.wallet_tool: fetching balance for 6rHuYnakzcnshsdm1Kyvr9fqH5pfvMHHd2c17cLazfR9
15:20:25 [INFO] httpx: HTTP Request: POST https://api.mainnet-beta.solana.com "HTTP/1.1 200 OK"
15:20:25 [INFO] tools.wallet_tool:   → 0.362377 SOL (362376904 lamports)
15:20:25 [INFO] core.agent:   wallet balance: 0.362377 SOL
15:20:25 [INFO] core.agent:   daily spend so far: 0.000000 SOL
15:20:25 [INFO] tools.history_tool: history: returning 2 trade(s)
15:20:25 [INFO] tools.wallet_tool: fetching balance for 6rHuYnakzcnshsdm1Kyvr9fqH5pfvMHHd2c17cLazfR9
15:20:26 [INFO] httpx: HTTP Request: POST https://api.mainnet-beta.solana.com "HTTP/1.1 200 OK"
15:20:26 [INFO] tools.wallet_tool:   → 0.362377 SOL (362376904 lamports)
15:20:26 [INFO] tools.wallet_tool: fetching SPL token balance for USDC (EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v)
15:20:27 [INFO] httpx: HTTP Request: POST https://api.mainnet-beta.solana.com "HTTP/1.1 200 OK"
15:20:27 [INFO] tools.wallet_tool:   → no token accounts found for USDC
15:20:27 [INFO] tools.wallet_tool: fetching SPL token balance for WBTC (3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh)
15:20:27 [INFO] httpx: HTTP Request: POST https://api.mainnet-beta.solana.com "HTTP/1.1 200 OK"
15:20:27 [INFO] tools.wallet_tool:   → no token accounts found for WBTC
15:20:27 [INFO] core.agent:   per-token balances: SOL=0.3624, USDC=0.0000, WBTC=0.0000
15:20:27 [INFO] core.agent:   calling LLM (deepseek/deepseek-v3.2) …
15:20:32 [INFO] httpx: HTTP Request: POST https://openrouter.ai/api/v1/chat/completions "HTTP/1.1 200 OK"
15:20:36 [INFO] core.agent:   plan → action=swap target=SOLUSDC confidence=0.65
15:20:36 [INFO] core.agent: ═══ ACT ═══
15:20:36 [INFO] core.agent:   action=swap confidence=0.65 threshold=0.60
15:20:36 [INFO] core.agent:   swapping 0.050000 SOL → USDC (slippage_bps=50)
15:20:36 [INFO] tools.wallet_tool: fetching balance for 6rHuYnakzcnshsdm1Kyvr9fqH5pfvMHHd2c17cLazfR9
15:20:36 [INFO] httpx: HTTP Request: POST https://api.mainnet-beta.solana.com "HTTP/1.1 200 OK"
15:20:36 [INFO] tools.wallet_tool:   → 0.362377 SOL (362376904 lamports)
15:20:36 [INFO] tools.swap_tool: JupiterUltraSwap: requesting Ultra order So11111111111111111111111111111111111111112 -> EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v amount=50000000 (slippage_bps=50)
15:20:37 [INFO] httpx: HTTP Request: GET https://api.jup.ag/ultra/v1/order?inputMint=So11111111111111111111111111111111111111112&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=50000000&slippageBps=50&taker=6rHuYnakzcnshsdm1Kyvr9fqH5pfvMHHd2c17cLazfR9 "HTTP/1.1 200 OK"
15:20:38 [INFO] httpx: HTTP Request: POST https://api.jup.ag/ultra/v1/execute "HTTP/1.1 200 OK"
15:20:38 [INFO] tools.swap_tool: JupiterUltraSwap: swap executed, signature=3dyvsjyi5F3xGb5ELftGjn2kEkkzKzbiNSNcboMjNmA9QEqn3UMsb6PAyNXkG7TVwXGRozFJy3NL7FYHPDcWpiQ4
15:20:38 [INFO] core.agent:   → swap sig: 3dyvsjyi5F3xGb5ELftGjn2kEkkzKzbiNSNcboMjNmA9QEqn3UMsb6PAyNXkG7TVwXGRozFJy3NL7FYHPDcWpiQ4
15:20:38 [INFO] core.agent: ═══ REFLECT ═══
15:20:38 [INFO] core.agent:   trade record saved
15:20:38 [INFO] core.agent:   reflection saved to memory
15:20:38 [INFO] tools.wallet_tool: fetching balance for 6rHuYnakzcnshsdm1Kyvr9fqH5pfvMHHd2c17cLazfR9
15:20:38 [INFO] httpx: HTTP Request: POST https://api.mainnet-beta.solana.com "HTTP/1.1 200 OK"
15:20:38 [INFO] tools.wallet_tool:   → 0.362377 SOL (362376904 lamports)
15:20:38 [WARNING] core.agent:   position drift detected: on-chain=0.362377 SOL, tracked=0.312377 SOL (drift=0.050000)
15:20:38 [WARNING] core.agent:   unable to reconcile drift: SOL price not available
15:20:38 [INFO] tools.wallet_tool: fetching balance for 6rHuYnakzcnshsdm1Kyvr9fqH5pfvMHHd2c17cLazfR9
15:20:39 [INFO] httpx: HTTP Request: POST https://api.mainnet-beta.solana.com "HTTP/1.1 200 OK"
15:20:39 [INFO] tools.wallet_tool:   → 0.362377 SOL (362376904 lamports)
15:20:39 [INFO] core.agent:   post-swap balance check: before=0.362377 SOL, after=0.362377 SOL, delta=0.000000
15:20:39 [INFO] __main__: ─── done ───
15:20:39 [INFO] __main__: action_result: swapped 0.05 SOL → USDC, approx $4.12, sig=3dyvsjyi5F3xGb5ELftGjn2kEkkzKzbiNSNcboMjNmA9QEqn3UMsb6PAyNXkG7TVwXGRozFJy3NL7FYHPDcWpiQ4
15:20:39 [INFO] __main__: reflection:    plan={'action_type': 'swap', 'target': 'SOLUSDC', 'params': {'from_token': 'SOL', 'to_token': 'USDC', 'amount_sol': 0.05, 'slippage_bps': 50}, 'confidence': 0.65, 'reason': 'SOL shows downtrend on 4h, RSI near 30 (oversold), funding rate negative (-0.00066) indicating shorts pay longs, and my SOL balance is low; a small swap to USDC reduces exposure to further downside while preserving most capital for a potential reversal.'} | result=swapped 0.05 SOL → USDC, approx $4.12, sig=3dyvsjyi5F3xGb5ELftGjn2kEkkzKzbiNSNcboMjNmA9QEqn3UMsb6PAyNXkG7TVwXGRozFJy3NL7FYHPDcWpiQ4
```

## 💖 Support the Project

If you find this interesting or useful, consider supporting ongoing development:

⚠️ Disclaimer

This is experimental research software.

- Real money is involved
- Bugs can lose funds
- No financial advice
- Use at your own risk

If the agent dies, it dies.

📜 License

MIT

🚀 If you star only one autonomous-agent repo this year

make it one that actually runs, trades, survives — or fails publicly.