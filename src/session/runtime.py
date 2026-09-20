import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)


START_URL = "https://duckduckgo.com/"


@dataclass
class Runtime:
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page

    def execution_namespace(self) -> dict[str, object]:
        return {
            "playwright": self.playwright,
            "browser": self.browser,
            "context": self.context,
            "page": self.page,
        }


@asynccontextmanager
async def browser_runtime(start_url: str | None = START_URL) -> AsyncIterator[Runtime]:
    async with async_playwright() as playwright:
        browser = None
        context = None
        try:
            browser = await playwright.chromium.launch(
                headless=False,
                slow_mo=250,
            )
            context = await browser.new_context()
            page = await context.new_page()
            if start_url is not None:
                await page.goto(start_url)
            yield Runtime(
                playwright=playwright,
                browser=browser,
                context=context,
                page=page,
            )
        finally:
            if context is not None:
                await context.close()
            if browser is not None:
                await browser.close()
