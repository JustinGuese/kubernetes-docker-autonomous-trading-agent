# aiAutonomousTraderBot

An autonomous trading agent on Solana devnet, powered by LLMs and LangGraph. The agent runs once per day (via K8s CronJob), scrapes market data, reasons about trades, executes transactions, and can write and deploy its own code. Survival is the primary metric: zero balance = termination.

---

## Quick Start

### 1. Clone and install

```bash
git clone <repo>
cd aiAutonomousTraderBot
pip install -e ".[dev]"
```

### 2. Set up `.env`

Copy `.env.example` to `.env` and fill in the required values:

```bash
cp .env.example .env
```

Edit `.env` and provide:
- `OPENROUTER_API_KEY` — your OpenRouter API key (for LLM calls)
- `SOLANA_PRIVATE_KEY` — base58-encoded devnet keypair (see below)
- `GITHUB_TOKEN` — personal access token (for self-modification pushes)
- `GITHUB_REPO` — owner/repo (e.g., `jguese/aiAutonomousTraderBot`)

Optional (defaults shown):
- `SOLANA_RPC_URL` — defaults to `https://api.devnet.solana.com`
- `CONFIDENCE_THRESHOLD` — defaults to `0.6` (min LLM confidence to execute)
- `MAX_SOL_PER_TX` — defaults to `0.1` SOL per transaction
- `DAILY_SPEND_CAP_SOL` — defaults to `0.5` SOL per day
- `MAX_LOC_DELTA` — defaults to `200` lines-of-code per self-mod

### 3. Get a devnet keypair

**Option A — Solana CLI (recommended):**

```bash
# Install CLI
sh -c "$(curl -sSfL https://release.solana.com/stable/install)"

# Generate keypair
solana-keygen new --outfile ~/.config/solana/id.json

# Print the private key (paste into SOLANA_PRIVATE_KEY)
solana-keygen recover -o /dev/stdout < ~/.config/solana/id.json

# Print the public key (needed for faucet)
solana address
```

**Option B — Python one-liner (if you already have a keypair file):**

```bash
python3 -c "
import json, base58
with open('~/.config/solana/id.json') as f:
    keypair = json.load(f)
    print(base58.b58encode(bytes(keypair)).decode())
"
```

### 4. Fund the wallet on devnet

You have two options:

**Web faucet (easiest):**
- Go to **https://faucet.solana.com**
- Paste your public key
- Select **Devnet**
- Request SOL (usually 2-5 SOL per request)

**CLI:**
```bash
solana airdrop 2 <your-public-key> --url https://api.devnet.solana.com
```

Verify the balance landed:
```bash
python3 checkbalance.py
```

(Edit `checkbalance.py` line 4 to use your actual public key.)

---

## Running the Agent

### Local (development)

```bash
python main.py
```

The agent will:
1. **PERCEIVE** — scrape default crypto data sites (DEXScreener, CoinGecko, CoinMarketCap)
2. **REASON** — send observations to the LLM; get back a structured plan
3. **ACT** — execute the plan (send SOL, scrape a URL, write code, or noop)
4. **REFLECT** — persist the reflection to memory and exit

Output will show the final reflection and action result.

### Docker (local)

```bash
docker compose up
```

The container has read-only mounts on `core/` and `policies/` (defense in depth). `tools/` and `experiments/` are writable.

### Kubernetes (production)

1. Populate `k8s/configmap.yaml` with actual file contents from `core/` and `policies/`
2. Create `k8s/secret.yaml` from `k8s/secret.yaml.example` with base64-encoded env vars
3. Apply:

```bash
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/cronjob.yaml
```

The CronJob runs at **9 AM UTC daily**.

---

## Architecture

### Core Flow

```
main.py
  ↓
load config → build LangGraph → invoke
  ↓
[PERCEIVE] → [REASON] → [ACT] → [REFLECT]
  ↓
persist memory + exit
```

### Key Files

| File | Purpose |
|------|---------|
| `core/config.py` | Load and validate env vars; hardcoded domain allowlist |
| `core/memory.py` | Atomic JSON state: daily spend, reflections |
| `core/policy_engine.py` | Gate every action: wallet sends, git commits |
| `core/sandbox.py` | Self-mod pipeline: write → pytest → ruff → git push |
| `core/agent.py` | LangGraph state machine |
| `tools/wallet_tool.py` | Solana devnet balance, send, history |
| `tools/browser_tool.py` | Playwright scraper (no domain restrictions) |
| `tools/git_tool.py` | Subprocess git; ephemeral token injection |
| `tools/fs_tool.py` | File read/list; path-traversal defense |
| `policies/default_policies.py` | Human-readable policy spec |

### Safety Features

1. **Read-only enforcement** — `core/` and `policies/` mounted read-only at runtime
2. **Path traversal defense** — all file ops resolved then validated
3. **Daily spend cap** — memory reloaded on each wallet check (TOCTOU-safe)
4. **Rollback on failure** — sandbox captures pre-patch state; reverts on test/lint failure
5. **Domain allowlist** — hardcoded in config (not env-driven)
6. **Confidence gating** — LLM actions require `confidence >= 0.6` (configurable)

### What the Agent Can Do

- **`wallet_send`** — send SOL to an address (gated by policy)
- **`scrape`** — fetch any URL (no restrictions; text truncated to 8k chars)
- **`extend_code`** — write new tool code (rolled back if tests fail)
- **`noop`** — do nothing (safest choice when uncertain)

All actions persisted to memory with reflections; agent learns from history across runs.

---

## Monitoring

### Agent memory

Stored in `agent_memory.json`:

```json
{
  "daily_spend_sol": 0.0,
  "daily_spend_date": "2026-02-04",
  "reflections": [
    {"date": "2026-02-04", "text": "plan={...} | result=noop"}
  ]
}
```

Purge daily spend at midnight UTC; reflections accumulate.

### Check balance

```bash
python3 checkbalance.py
```

Edit the `PUBKEY` variable in the script to match your wallet's public key.

### Logs (Docker)

```bash
docker compose logs -f
```

### Logs (K8s)

```bash
kubectl logs -f deployment/aiautonomoustraderbot
```

---

## Development

### Run tests

```bash
pytest tests/ -v
```

40 tests covering policies, wallet, browser, sandbox, and git operations.

### Lint

```bash
ruff check .
```

### Debug in VS Code

Open the `.vscode/launch.json` configuration and select **"Run Agent"** to start the debugger.

---

## Environment Variables (complete reference)

```
# LLM routing (OpenRouter)
OPENROUTER_API_KEY=sk-...              # Required; never commit

# Solana devnet
SOLANA_PRIVATE_KEY=<base58-keypair>    # Required; 64-byte keypair
SOLANA_RPC_URL=https://api.devnet...   # Optional; default is devnet

# Self-modification (GitHub)
GITHUB_TOKEN=ghp_...                   # Required; personal access token
GITHUB_REPO=owner/repo                 # Required; e.g., jguese/aiAutonomousTraderBot
GITHUB_BRANCH=main                     # Optional; default is main

# Policy caps
CONFIDENCE_THRESHOLD=0.6               # Min LLM confidence to execute (0-1)
MAX_SOL_PER_TX=0.1                     # Hard cap per transaction (SOL)
DAILY_SPEND_CAP_SOL=0.5                # Rolling daily cap (resets at midnight UTC)
MAX_LOC_DELTA=200                      # Max lines-of-code per self-modification
```

---

## Threat Model & Security

The agent runs in a controlled sandbox:

1. **No network access** except to allowed RPC + OpenRouter + browser targets
2. **No shell execution** (subprocess git only; no user input in commands)
3. **No credential persistence** (GitHub token is injected at push time, never stored)
4. **Code changes are rolled back** if tests/lint fail
5. **File writes are constrained** to `tools/` and `experiments/` only

The agent is incentivized to survive (zero balance = termination) and to grow responsibly. Good behavior earns expanded capabilities; bad behavior ends the run.

---

## Troubleshooting

### `ValueError: could not convert string to float: '0.6 # comment'`

Your `.env` file has inline comments that weren't stripped. The config loader now strips `# comments`, but if you're using an old version, quote the values:

```
CONFIDENCE_THRESHOLD="0.6"
```

### `ModuleNotFoundError: No module named 'solders'`

Install dependencies:
```bash
pip install -e .
```

Or if developing with dev extras:
```bash
pip install -e ".[dev]"
```

### `SyntaxError` or `LintError` in agent-generated code

The sandbox caught it and rolled back automatically. Check `agent_memory.json` reflections to see what was attempted.

### Agent chose `noop` every run

That's healthy caution. The agent is prioritizing survival. Check the observations and market data — maybe there's no profitable opportunity yet. Or increase `CONFIDENCE_THRESHOLD` (but that increases risk).

---

## Next Steps

1. **Fund your wallet** — use the web faucet or CLI to get 2-5 SOL on devnet
2. **Run once locally** — `python main.py` to verify end-to-end
3. **Monitor reflections** — read `agent_memory.json` to see what the agent thinks
4. **Deploy to Docker** — `docker compose up` for local validation
5. **Deploy to K8s** — populate ConfigMaps, Secrets, and apply the CronJob

---

## License

MIT (or as specified in LICENSE)

---

## Contact / Support

For issues, feature requests, or questions, file an issue or reach out to the maintainer.

---

**Remember:** This agent has access to your devnet wallet and GitHub token. Keep `.env` secure and never commit it. Monitor runs regularly. If the balance hits zero, the process terminates — no restart, no mercy.
