"""Save a full-page browser screenshot."""

from pathlib import Path

from playwright.async_api import Page

DEFAULT_OUTPUT = Path("output/ss.png")


async def save_full_page_screenshot(page: Page, output_path: Path = DEFAULT_OUTPUT) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(output_path), full_page=True)
