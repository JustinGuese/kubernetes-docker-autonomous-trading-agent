"""Self-modification sandbox: propose → policy-check → write → pytest → ruff → git commit.

Rollback on any failure: the original file content is restored.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from core.config import AppConfig
from core.policy_engine import PolicyEngine
from tools.git_tool import GitTool

logger = logging.getLogger(__name__)


class SandboxError(Exception):
    """Any failure inside the sandbox pipeline."""


class Sandbox:
    def __init__(self, config: AppConfig, policy: PolicyEngine):
        self.config = config
        self.policy = policy
        self.git = GitTool(config, policy)

    def apply(self, path: str, new_content: str, commit_message: str) -> str:
        """Full pipeline.  Returns git signature on success.  Rolls back on failure."""
        logger.info("sandbox apply: %s (%d chars)", path, len(new_content))

        # ── 1. Validate path ──────────────────────────────────────
        self.policy.check_git_paths([path])
        logger.info("  path validated")

        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # ── 2. Capture pre-patch state for rollback ───────────────
        original: str | None = None
        if file_path.exists():
            original = file_path.read_text()

        # ── 3. LOC delta check ────────────────────────────────────
        old_lines = original.count("\n") if original else 0
        new_lines = new_content.count("\n")
        delta = new_lines - old_lines
        self.policy.check_loc_delta(delta)
        logger.info("  LOC delta: %+d (old=%d new=%d)", delta, old_lines, new_lines)

        # ── 4. Write ──────────────────────────────────────────────
        file_path.write_text(new_content)
        logger.info("  wrote %s", path)

        try:
            # ── 5. pytest ─────────────────────────────────────────
            logger.info("  running pytest …")
            result = subprocess.run(
                ["python", "-m", "pytest", "tests/", "-x", "-q"],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise SandboxError(f"pytest failed:\n{result.stdout}\n{result.stderr}")
            logger.info("  pytest passed")

            # ── 6. ruff ───────────────────────────────────────────
            logger.info("  running ruff …")
            result = subprocess.run(
                ["python", "-m", "ruff", "check", path],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise SandboxError(f"ruff failed:\n{result.stdout}\n{result.stderr}")
            logger.info("  ruff clean")

            # ── 7. git commit + push ──────────────────────────────
            logger.info("  committing and pushing …")
            sig = self.git.commit_and_push([path], commit_message)
            logger.info("  → committed: %s", sig)
            return sig

        except Exception as exc:
            # ── Rollback ──────────────────────────────────────────
            logger.warning("  rolling back %s — %s", path, exc)
            if original is not None:
                file_path.write_text(original)
            else:
                file_path.unlink(missing_ok=True)
            raise
