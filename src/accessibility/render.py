"""Render simplified accessibility trees for the model context."""

import json
from typing import Any


OUTLINE_LIMIT = 10_000
TRUNCATED_OUTLINE = "[Page outline truncated; inspect a specific locator for more detail.]"


def render_accessibility_tree(tree: dict[str, list[dict[str, Any]]]) -> str:
    lines = []

    def find_role(nodes: list[dict[str, Any]], role: str) -> dict[str, Any] | None:
        for node in nodes:
            if node["role"].lower() == role:
                return node
            found = find_role(node.get("children", []), role)
            if found is not None:
                return found
        return None

    def state_value(key: str, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        if key == "url":
            value = value.partition("?")[0].partition("#")[0]
        return value[:160]

    def visit(node: dict[str, Any], depth: int, *, skip_focus: bool = False) -> None:
        if skip_focus and node is focus:
            return
        parts = [node["role"]]

        if node.get("name"):
            parts.append(json.dumps(node["name"], ensure_ascii=False))

        if node.get("state"):
            states = ", ".join(
                f"{key}={json.dumps(state_value(key, value), ensure_ascii=False)}"
                for key, value in node["state"].items()
            )
            parts.append(f"[{states}]")

        lines.append("  " * depth + " ".join(parts))

        for child in node.get("children", []):
            visit(child, depth + 1, skip_focus=skip_focus)

    # ponytail: one priority region can omit another on huge pages; inspect a specific locator for more detail.
    focus = None
    for role in ("dialog", "alert", "main"):
        focus = find_role(tree["nodes"], role)
        if focus is not None:
            break
    if focus is not None:
        visit(focus, 0)
    for node in tree["nodes"]:
        visit(node, 0, skip_focus=True)

    outline = "\n".join(lines)
    if len(outline) > OUTLINE_LIMIT:
        outline = outline[: OUTLINE_LIMIT - len(TRUNCATED_OUTLINE) - 1].rsplit("\n", 1)[0]
        return f"{outline}\n{TRUNCATED_OUTLINE}"
    return outline
