"""Turn Chromium's verbose raw accessibility tree into an agent observation."""

import json
from typing import Any

ACTIONABLE_ROLES = {
    "button",
    "checkbox",
    "combobox",
    "link",
    "menuitem",
    "menuitemcheckbox",
    "menuitemradio",
    "option",
    "radio",
    "searchbox",
    "slider",
    "spinbutton",
    "switch",
    "tab",
    "textbox",
    "treeitem",
}
SKIPPED_ROLES = {"InlineTextBox", "LineBreak", "ListMarker", "none", "presentation"}
STATE_NAMES = {
    "checked",
    "disabled",
    "expanded",
    "focused",
    "hasPopup",
    "level",
    "pressed",
    "required",
    "selected",
    "url",
}


def _value(item: dict[str, Any], key: str = "value") -> Any:
    value = item.get(key)
    return value.get("value") if isinstance(value, dict) else None


def _state(node: dict[str, Any]) -> dict[str, Any]:
    state = {
        property_["name"]: _value(property_)
        for property_ in node.get("properties", [])
        if property_.get("name") in STATE_NAMES and _value(property_) is not None
    }
    if (value := _value(node)) is not None:
        state["value"] = value
    return state


def prune_accessibility_tree(tree: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    nodes = {node["nodeId"]: node for node in tree.get("nodes", [])}
    references = 0

    def visit(
        node_id: str, parent_name: str, ancestors: frozenset[str]
    ) -> list[dict[str, Any]]:
        nonlocal references
        if node_id in ancestors or (node := nodes.get(node_id)) is None:
            return []

        role = str(_value(node, "role") or "")
        name = str(_value(node, "name") or "").strip()
        state = _state(node)
        skip = (
            node.get("ignored", False)
            or role in SKIPPED_ROLES
            or (role == "generic" and not name and not state)
            or (role == "StaticText" and name and name in parent_name)
        )
        children = [
            child
            for child_id in node.get("childIds", [])
            for child in visit(child_id, name or parent_name, ancestors | {node_id})
        ]
        if skip:
            return children  # Preserve descendants when this node is only noise.

        observation: dict[str, Any] = {"role": role}
        if name:
            observation["name"] = name
        if role.lower() in ACTIONABLE_ROLES:
            references += 1
            observation["id"] = f"e{references}"
        if state:
            observation["state"] = state
        if children:
            observation["children"] = children
        return [observation]

    roots = [node_id for node_id, node in nodes.items() if "parentId" not in node]
    return {
        "nodes": [child for root in roots for child in visit(root, "", frozenset())]
    }


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
