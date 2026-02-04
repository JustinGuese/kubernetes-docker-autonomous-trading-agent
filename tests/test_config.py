"""Tests for core/config.py — load_config, env parsing, ALLOWED_SCRAPE_DOMAINS."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from core.config import (
    ALLOWED_SCRAPE_DOMAINS,
    AppConfig,
    load_config,
)
from core.config import _getenv  # noqa: PLC2701
from core.config import _require  # noqa: PLC2701


class TestAllowedScrapeDomains:
    def test_contains_expected_domains(self) -> None:
        assert "dexscreener.com" in ALLOWED_SCRAPE_DOMAINS
        assert "coingecko.com" in ALLOWED_SCRAPE_DOMAINS
        assert "coinmarketcap.com" in ALLOWED_SCRAPE_DOMAINS
        assert "solana.com" in ALLOWED_SCRAPE_DOMAINS


class TestGetenv:
    def test_returns_default_when_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert _getenv("MISSING_VAR_XYZ", "default") == "default"

    def test_strips_inline_comment(self) -> None:
        with patch.dict(os.environ, {"TEST_KEY": "0.6  # comment"}, clear=False):
            assert _getenv("TEST_KEY", "fallback") == "0.6"


class TestRequire:
    def test_raises_when_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(EnvironmentError, match="is not set"):
                _require("MISSING_REQUIRED_XYZ")


_REQUIRED_ENV = {
    "OPENROUTER_API_KEY": "test-key",
    "SOLANA_PRIVATE_KEY": "base58fakekey",
    "GITHUB_TOKEN": "ghp_fake",
    "GITHUB_REPO": "owner/repo",
}


class TestLoadConfig:
    def test_returns_app_config_when_all_required_set(self) -> None:
        with patch.dict(os.environ, _REQUIRED_ENV, clear=False):
            config = load_config()
        assert isinstance(config, AppConfig)
        assert config.llm.api_key == "test-key"
        assert config.solana.rpc_url == "https://api.devnet.solana.com"
        assert config.policy.confidence_threshold == 0.6
        assert config.git.repo == "owner/repo"
        assert config.git.branch == "main"

    def test_raises_when_required_var_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(EnvironmentError, match="is not set"):
                load_config()

    def test_uses_env_overrides_when_provided(self) -> None:
        env = {
            **_REQUIRED_ENV,
            "SOLANA_RPC_URL": "https://custom.rpc.com",
            "CONFIDENCE_THRESHOLD": "0.8",
            "GITHUB_BRANCH": "develop",
        }
        with patch.dict(os.environ, env, clear=False):
            config = load_config()
        assert config.solana.rpc_url == "https://custom.rpc.com"
        assert config.policy.confidence_threshold == 0.8
        assert config.git.branch == "develop"
