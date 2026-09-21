"""Render simplified accessibility trees for the model context."""

import json
from typing import Any


def render_accessibility_tree(tree: dict[str, list[dict[str, Any]]]) -> str:
    lines = []

    def visit(node: dict[str, Any], depth: int) -> None:
        parts = [node["role"]]

        if node.get("name"):
            parts.append(json.dumps(node["name"], ensure_ascii=False))

        if node.get("state"):
            states = ", ".join(
                f"{key}={json.dumps(value, ensure_ascii=False)}"
                for key, value in node["state"].items()
            )
            parts.append(f"[{states}]")

        lines.append("  " * depth + " ".join(parts))

        for child in node.get("children", []):
            visit(child, depth + 1)

    for node in tree["nodes"]:
        visit(node, 0)

    return "\n".join(lines)
