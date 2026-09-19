"""Shared Playwright Chromium session for local capture runs."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from playwright.async_api import Page, async_playwright


@asynccontextmanager
async def chromium_test_page() -> AsyncIterator[Page]:
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False,slow_mo=1000)
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto("https://browser-use.com/posts/bitter-lesson-browser-agents")
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()
