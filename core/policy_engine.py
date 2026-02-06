"""Runtime policy gate.  Every wallet / browser / git action passes through here."""

from __future__ import annotations

from urllib.parse import urlparse

from core.config import AppConfig
from core.memory import MemoryStore
from core.network_config import NetworkType


class PolicyViolation(Exception):
    """Raised when an action is blocked by policy."""


class PolicyEngine:
    def __init__(self, config: AppConfig, memory: MemoryStore):
        self.config = config
        self.memory = memory

    # ── wallet ────────────────────────────────────────────────────

    def check_wallet_send(self, amount_sol: float, destination: str) -> None:
        """Raise PolicyViolation if the send is not permitted."""
        if amount_sol <= 0:
            raise PolicyViolation("amount_sol must be positive")
        if amount_sol > self.config.policy.max_sol_per_tx:
            raise PolicyViolation(
                f"amount_sol {amount_sol} exceeds MAX_SOL_PER_TX "
                f"{self.config.policy.max_sol_per_tx}"
            )
        # Re-read memory from disk every time — prevents TOCTOU race
        state = self.memory.load()
        projected = state.get("daily_spend_sol", 0.0) + amount_sol
        if projected > self.config.policy.daily_spend_cap_sol:
            raise PolicyViolation(
                f"Projected daily spend {projected} SOL exceeds cap "
                f"{self.config.policy.daily_spend_cap_sol}"
            )
        if not destination or len(destination) < 32:
            raise PolicyViolation("destination does not look like a valid Solana address")

    # ── swaps ─────────────────────────────────────────────────────

    def check_swap(
        self,
        from_token: str,
        to_token: str,
        amount_usd: float,
        network: NetworkType,
    ) -> None:
        """Validate a proposed swap against policy rules.

        We approximate risk in USD terms; callers should pass an estimated USD
        notional for the swap, based on current prices.
        """
        cfg = self.config.policy
        if from_token == to_token:
            raise PolicyViolation("swap from_token and to_token must differ")
        if amount_usd <= 0:
            raise PolicyViolation("swap amount_usd must be positive")
        if amount_usd > cfg.max_swap_usd_per_tx:
            raise PolicyViolation(
                f"swap notional {amount_usd} exceeds MAX_SWAP_USD_PER_TX {cfg.max_swap_usd_per_tx}"
            )

        state = self.memory.load()
        daily_swap = state.get("daily_swap_usd", 0.0)
        projected = daily_swap + amount_usd
        if projected > cfg.daily_swap_cap_usd:
            raise PolicyViolation(
                f"Projected daily swap volume {projected} exceeds cap {cfg.daily_swap_cap_usd}"
            )

        # Mainnet-specific safeguard: prevent draining SOL below configured minimum.
        if network == NetworkType.MAINNET and from_token.upper() == "SOL":
            positions = state.get("positions", {}) or {}
            current_sol = float(positions.get("SOL", {}).get("amount", 0.0))
            min_balance = float(self.config.solana.mainnet_min_balance_sol)

            # amount_usd is derived from SOL price in the agent; treat it as SOL
            # notional for this safety check.
            if current_sol - amount_usd < min_balance:
                raise PolicyViolation(
                    "Mainnet safety: swap would leave SOL balance below minimum "
                    f"({min_balance} SOL). Current: {current_sol:.3f}, "
                    f"requested: {amount_usd:.3f}"
                )

    def check_swap_balance(self, wallet_tool, from_token: str, amount: float) -> None:
        """Optional policy-level pre-swap balance check.

        Callers may use this instead of or in addition to direct wallet-level
        balance checks to ensure insufficient balance errors surface as
        PolicyViolation.
        """
        if amount <= 0:
            raise PolicyViolation("swap amount must be positive")
        available = wallet_tool.balance_token(from_token)
        if available < amount:
            raise PolicyViolation(
                f"Insufficient {from_token} balance for swap: have {available}, need {amount}"
            )

    # ── browser ───────────────────────────────────────────────────

    def check_browser_url(self, url: str) -> None:
        """Raise PolicyViolation if the URL's domain is not allowlisted."""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Strip port if present
        if ":" in domain:
            domain = domain.split(":")[0]
        if domain not in self.config.allowed_domains:
            raise PolicyViolation(
                f"Domain '{domain}' is not in the allowed scrape list"
            )

    # ── git / self-modification ───────────────────────────────────

    def check_git_paths(self, paths: list[str]) -> None:
        """Only tools/ and experiments/ paths are allowed."""
        from pathlib import Path

        allowed_prefixes = ("tools/", "experiments/")
        for p in paths:
            resolved = str(Path(p).resolve().relative_to(Path.cwd()))
            if not any(resolved.startswith(prefix) for prefix in allowed_prefixes):
                raise PolicyViolation(
                    f"Path '{p}' (resolved: '{resolved}') is outside allowed directories"
                )

    def check_loc_delta(self, delta: int) -> None:
        if abs(delta) > self.config.policy.max_loc_delta:
            raise PolicyViolation(
                f"LOC delta {delta} exceeds MAX_LOC_DELTA {self.config.policy.max_loc_delta}"
            )
