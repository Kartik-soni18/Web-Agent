"""Convert Chromium's raw accessibility protocol response into a compact tree."""

from typing import Any

from .constants import ACTIONABLE_ROLES, SKIPPED_ROLES, STATE_NAMES


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


def prune_full_accessibility_tree(
    tree: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
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
            return children

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
