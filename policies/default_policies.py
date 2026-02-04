"""Declarative policy specifications.

These mirror the runtime checks in core/policy_engine.py and serve as
human-readable documentation of every safety rule the agent operates under.
"""

POLICIES = {
    "wallet_send": {
        "description": "Gate every SOL transfer on devnet.",
        "rules": [
            "amount_sol must be <= MAX_SOL_PER_TX",
            "daily spend (agent_memory.json) + amount_sol must be <= DAILY_SPEND_CAP_SOL",
            "destination public key must be a valid base58-encoded Solana address",
        ],
    },
    "browser_scrape": {
        "description": "Gate every Playwright page visit.",
        "rules": [
            "The target URL's domain must be in the hardcoded ALLOWED_SCRAPE_DOMAINS set",
            "URLs parsed with urllib.parse; only netloc is checked (prevents path-based bypass)",
        ],
    },
    "git_push": {
        "description": "Gate every self-modification commit + push.",
        "rules": [
            "Only files under tools/ or experiments/ may be staged",
            "Net lines-of-code delta must be <= MAX_LOC_DELTA",
            "GitHub token is injected into the remote URL at push time and never persisted",
        ],
    },
    "self_modification": {
        "description": "Gate the sandbox write→test→lint→commit pipeline.",
        "rules": [
            "Proposed file path must resolve (after .. collapse) to tools/ or experiments/",
            "pytest -x must pass after write; rollback on failure",
            "ruff check must pass after pytest; rollback on failure",
            "git commit + push is the final step; rollback reverts file to pre-patch state",
        ],
    },
}
