"""Public accessibility-tree processing API."""

from typing import Any

from .prune import prune_full_accessibility_tree
from .simplify import simplify_accessibility_tree


def prune_accessibility_tree(
    tree: dict[str, Any],
    previous_tree: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Prune Chromium's AX tree, then simplify it for model consumption."""

    return simplify_accessibility_tree(
        prune_full_accessibility_tree(tree), previous_tree
    )
