import asyncio
from typing import Any

from playwright.async_api import Page

from ..clean_tree.accessibility_tree import prune_accessibility_tree
from ..models.observations import BrowserObservation
from .runtime import browser_runtime


def count_nodes(nodes: list[dict[str, Any]]) -> int:
    return len(nodes) + sum(count_nodes(node.get("children", [])) for node in nodes)


async def browser_observation(page: Page) -> BrowserObservation:
    session = await page.context.new_cdp_session(page)
    try:
        tree = await session.send("Accessibility.getFullAXTree")
    finally:
        await session.detach()

    clean_tree = prune_accessibility_tree(tree)
    return BrowserObservation(
        url=page.url,
        title=await page.title(),
        accessibility_tree=clean_tree,
        raw_node_count=len(tree.get("nodes", [])),
        kept_node_count=count_nodes(clean_tree["nodes"]),
    )


async def main() -> None:
    async with browser_runtime() as runtime:
        observed = await browser_observation(runtime.page)
        print(observed.kept_node_count)


if __name__ == "__main__":
    asyncio.run(main())
