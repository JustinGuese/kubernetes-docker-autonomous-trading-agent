"""Load and validate application configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


# Hardcoded domain allowlist — security boundary, not env-driven.
ALLOWED_SCRAPE_DOMAINS: frozenset[str] = frozenset(
    {
        "dexscreener.com",
        "coingecko.com",
        "coinmarketcap.com",
        "solana.com",
        "solprice.com",
    }
)


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    heavy_model: str = "deepseek/deepseek-v3.2"
    light_model: str = "openai/gpt-oss-20b"
    base_url: str = "https://openrouter.ai/api/v1"


@dataclass(frozen=True)
class SolanaConfig:
    private_key: str  # base58-encoded 64-byte keypair
    rpc_url: str = "https://api.devnet.solana.com"


@dataclass(frozen=True)
class PolicyConfig:
    confidence_threshold: float = 0.6
    max_sol_per_tx: float = 0.1
    daily_spend_cap_sol: float = 0.5
    max_loc_delta: int = 200


@dataclass(frozen=True)
class GitConfig:
    token: str
    repo: str  # owner/repo
    branch: str = "main"


@dataclass(frozen=True)
class AppConfig:
    llm: LLMConfig
    solana: SolanaConfig
    policy: PolicyConfig
    git: GitConfig
    allowed_domains: frozenset[str] = ALLOWED_SCRAPE_DOMAINS


def _getenv(name: str, default: str | None = None) -> str | None:
    """os.getenv wrapper that strips inline comments (e.g. '0.6  # note' → '0.6')."""
    raw = os.getenv(name, default)
    if raw is None:
        return None
    # Split on first ' #' (space-hash) to drop inline comments, then strip
    return raw.split(" #")[0].strip()


def _require(name: str) -> str:
    value = _getenv(name)
    if not value:
        raise EnvironmentError(f"Required environment variable {name} is not set")
    return value


def load_config() -> AppConfig:
    """Build AppConfig from environment. Raises EnvironmentError on missing keys."""
    return AppConfig(
        llm=LLMConfig(api_key=_require("OPENROUTER_API_KEY")),
        solana=SolanaConfig(
            private_key=_require("SOLANA_PRIVATE_KEY"),
            rpc_url=_getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com"),  # type: ignore[arg-type]
        ),
        policy=PolicyConfig(
            confidence_threshold=float(_getenv("CONFIDENCE_THRESHOLD", "0.6")),  # type: ignore[arg-type]
            max_sol_per_tx=float(_getenv("MAX_SOL_PER_TX", "0.1")),  # type: ignore[arg-type]
            daily_spend_cap_sol=float(_getenv("DAILY_SPEND_CAP_SOL", "0.5")),  # type: ignore[arg-type]
            max_loc_delta=int(_getenv("MAX_LOC_DELTA", "200")),  # type: ignore[arg-type]
        ),
        git=GitConfig(
            token=_require("GITHUB_TOKEN"),
            repo=_require("GITHUB_REPO"),
            branch=_getenv("GITHUB_BRANCH", "main"),  # type: ignore[arg-type]
        ),
    )
