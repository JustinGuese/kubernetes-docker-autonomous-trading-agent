"""Git operations via subprocess — ephemeral token injection, never persisted."""

from __future__ import annotations

import subprocess

from core.config import AppConfig
from core.policy_engine import PolicyEngine


class GitTool:
    def __init__(self, config: AppConfig, policy: PolicyEngine):
        self.config = config
        self.policy = policy

    def commit_and_push(self, paths: list[str], message: str) -> str:
        """Stage *paths*, commit with *message*, push.  Raises on policy violation."""
        self.policy.check_git_paths(paths)

        # Stage only the declared files — never git add -A
        subprocess.run(["git", "add", "--"] + paths, check=True)

        subprocess.run(
            ["git", "commit", "-m", message],
            check=True,
        )

        # Inject token into remote URL only at push time
        owner_repo = self.config.git.repo
        token = self.config.git.token
        remote_url = f"https://{token}@github.com/{owner_repo}.git"

        subprocess.run(
            ["git", "push", remote_url, self.config.git.branch],
            check=True,
            # Suppress token from appearing in stdout/stderr
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Reset remote to the non-token URL so it is never persisted
        subprocess.run(
            ["git", "remote", "set-url", "origin", f"https://github.com/{owner_repo}.git"],
            check=True,
        )

        return "push succeeded"
