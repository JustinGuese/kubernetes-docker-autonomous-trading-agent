"""Tests for core/sandbox.py — rollback on failure, path-traversal blocks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.config import AppConfig, GitConfig, LLMConfig, MemoryConfig, PolicyConfig, SolanaConfig
from core.memory import MemoryStore
from core.policy_engine import PolicyEngine, PolicyViolation
from core.sandbox import Sandbox, SandboxError


def _make_config(max_loc_delta: int = 200) -> AppConfig:
    return AppConfig(
        llm=LLMConfig(api_key="k"),
        solana=SolanaConfig(private_key="k", rpc_url="https://x"),
        policy=PolicyConfig(max_loc_delta=max_loc_delta),
        git=GitConfig(token="t", repo="o/r"),
        memory=MemoryConfig(),
    )


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sandbox:
    monkeypatch.chdir(tmp_path)
    # Create the tools/ dir so path validation works
    (tmp_path / "tools").mkdir()
    (tmp_path / "tests").mkdir()
    config = _make_config()
    memory = MemoryStore(path=tmp_path / "agent_memory.json")
    policy = PolicyEngine(config, memory)
    return Sandbox(config, policy)


class TestPathValidation:
    def test_core_path_blocked(self, sandbox: Sandbox, tmp_path: Path) -> None:
        (tmp_path / "core").mkdir(exist_ok=True)
        with pytest.raises(PolicyViolation, match="outside allowed"):
            sandbox.apply("core/evil.py", "print('pwned')", "bad commit")

    def test_root_path_blocked(self, sandbox: Sandbox) -> None:
        with pytest.raises(PolicyViolation, match="outside allowed"):
            sandbox.apply("main.py", "x = 1", "bad commit")


class TestLocDelta:
    def test_large_delta_blocked(self, sandbox: Sandbox) -> None:
        # 201 lines > default 200 limit
        big_code = "\n".join(f"x = {i}" for i in range(202))
        with pytest.raises(PolicyViolation, match="LOC delta"):
            sandbox.apply("tools/big.py", big_code, "too big")


class TestRollback:
    @patch("core.sandbox.subprocess.run")
    def test_rollback_on_pytest_failure(
        self, mock_run: MagicMock, sandbox: Sandbox, tmp_path: Path
    ) -> None:
        original_content = "# original"
        target = tmp_path / "tools" / "rollback_test.py"
        target.write_text(original_content)

        # pytest fails (returncode=1), ruff never called
        mock_run.return_value = MagicMock(returncode=1, stdout="FAILED", stderr="err")

        with pytest.raises(SandboxError, match="pytest failed"):
            sandbox.apply("tools/rollback_test.py", "# new code\n", "commit msg")

        # File should be rolled back
        assert target.read_text() == original_content

    @patch("core.sandbox.subprocess.run")
    def test_rollback_deletes_new_file_on_failure(
        self, mock_run: MagicMock, sandbox: Sandbox, tmp_path: Path
    ) -> None:
        target = tmp_path / "tools" / "brand_new.py"
        assert not target.exists()

        mock_run.return_value = MagicMock(returncode=1, stdout="FAILED", stderr="")

        with pytest.raises(SandboxError):
            sandbox.apply("tools/brand_new.py", "x = 1\n", "new file")

        # File should be removed since it didn't exist before
        assert not target.exists()

    @patch("core.sandbox.subprocess.run")
    def test_successful_pipeline_calls_git(
        self, mock_run: MagicMock, sandbox: Sandbox, tmp_path: Path
    ) -> None:
        # All subprocess calls succeed
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch.object(sandbox.git, "commit_and_push", return_value="push succeeded"):
            result = sandbox.apply("tools/good.py", "x = 1\n", "good commit")

        assert result == "push succeeded"
