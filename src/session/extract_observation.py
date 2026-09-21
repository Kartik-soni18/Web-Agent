from typing import Any

from ..accessibility import prune_full_accessibility_tree, simplify_accessibility_tree
from ..models.observations import BrowserObservation


def count_nodes(nodes: list[dict[str, Any]]) -> int:
    return len(nodes) + sum(count_nodes(node.get("children", [])) for node in nodes)


def browser_observation(
    url: str,
    title: str,
    tree: dict[str, Any],
    previous_tree: dict[str, list[dict[str, Any]]] | None = None,
) -> BrowserObservation:
    pruned_tree = prune_full_accessibility_tree(tree)
    accessibility_tree = simplify_accessibility_tree(pruned_tree, previous_tree)
    return BrowserObservation(
        url=url,
        title=title,
        accessibility_tree=accessibility_tree,
        raw_node_count=len(tree.get("nodes", [])),
        kept_node_count=count_nodes(accessibility_tree["nodes"]),
    )
