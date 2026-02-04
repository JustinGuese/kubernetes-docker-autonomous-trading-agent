"""Tests for tools/browser_tool.py — scrape and truncation behaviour."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tools.browser_tool import BrowserTool


@pytest.fixture
def browser_tool() -> BrowserTool:
    return BrowserTool()


class TestScrapeAsync:
    """Smoke-test that scrape() calls playwright and truncates."""

    @pytest.mark.asyncio
    async def test_scrape_truncates_to_8k(self, browser_tool: BrowserTool) -> None:
        long_text = "x" * 20000
        mock_page = AsyncMock()
        mock_page.inner_text.return_value = long_text
        mock_page.goto = AsyncMock()

        mock_browser = AsyncMock()
        mock_browser.new_page.return_value = mock_page
        mock_browser.close = AsyncMock()

        mock_playwright = AsyncMock()
        mock_playwright.chromium.launch.return_value = mock_browser

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_playwright
        mock_ctx.__aexit__.return_value = False

        with patch("tools.browser_tool.async_playwright", return_value=mock_ctx):
            result = await browser_tool.scrape("https://anything.example.com/page")

        assert len(result) == 8000

    @pytest.mark.asyncio
    async def test_scrape_short_text_not_truncated(self, browser_tool: BrowserTool) -> None:
        short_text = "hello world"
        mock_page = AsyncMock()
        mock_page.inner_text.return_value = short_text
        mock_page.goto = AsyncMock()

        mock_browser = AsyncMock()
        mock_browser.new_page.return_value = mock_page
        mock_browser.close = AsyncMock()

        mock_playwright = AsyncMock()
        mock_playwright.chromium.launch.return_value = mock_browser

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_playwright
        mock_ctx.__aexit__.return_value = False

        with patch("tools.browser_tool.async_playwright", return_value=mock_ctx):
            result = await browser_tool.scrape("https://anything.example.com")

        assert result == short_text
