"""Create a compact accessibility-tree observation for a web agent."""

import json
from pathlib import Path
from typing import TYPE_CHECKING

from page_capture.accessibility_pruner import prune_accessibility_tree

if TYPE_CHECKING:
    from playwright.async_api import Page


DEFAULT_OUTPUT = Path("output/access.json")

async def save_accessibility_tree(page: Page, output_path: Path = DEFAULT_OUTPUT) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    session = await page.context.new_cdp_session(page)
    try:
        tree = await session.send("Accessibility.getFullAXTree")
    finally:
        await session.detach()
    output_path.write_text(json.dumps(prune_accessibility_tree(tree), indent=2), encoding="utf-8")
