"""Apply model-focused reductions to a pruned accessibility tree."""

import json
from typing import Any

from .constants import (
    ACTIONABLE_ROLES,
    FOOTER_ESSENTIAL_ROLES,
    MAX_STATIC_TEXT_LENGTH,
    PROTECTED_ROLES,
    STRUCTURAL_ROLES,
)


def _role(node: dict[str, Any]) -> str:
    return str(node["role"])


def _is_interactive(node: dict[str, Any]) -> bool:
    return _role(node).lower() in ACTIONABLE_ROLES


def _has_unique_semantics(node: dict[str, Any]) -> bool:
    state = node.get("state", {})
    return bool(node.get("name")) or any(key != "level" for key in state)


def _cap_text(text: str) -> str:
    if len(text) <= MAX_STATIC_TEXT_LENGTH:
        return text
    return text[: MAX_STATIC_TEXT_LENGTH - 1].rstrip() + "…"


def _merge_adjacent_text(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for node in nodes:
        if (
            merged
            and _role(node) == "StaticText"
            and _role(merged[-1]) == "StaticText"
            and not node.get("state")
            and not merged[-1].get("state")
        ):
            merged[-1]["name"] = _cap_text(
                f'{merged[-1]["name"]} {node["name"]}'.strip()
            )
            continue
        merged.append(node)
    return merged


def _interactive_descendants(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    for node in nodes:
        if _is_interactive(node):
            controls.append(node)
        else:
            controls.extend(_interactive_descendants(node.get("children", [])))
    return _merge_adjacent_text(controls)


def _footer_essentials(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    essentials: list[dict[str, Any]] = []
    for node in nodes:
        if _role(node).lower() in FOOTER_ESSENTIAL_ROLES:
            essentials.append(node)
        else:
            essentials.extend(_footer_essentials(node.get("children", [])))
    return essentials


def _fingerprint(node: dict[str, Any]) -> str:
    return json.dumps(
        {
            "role": _role(node),
            "name": node.get("name"),
            "state": node.get("state", {}),
            "children": [_fingerprint(child) for child in node.get("children", [])],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _navigation_fingerprints(tree: dict[str, list[dict[str, Any]]]) -> set[str]:
    fingerprints: set[str] = set()

    def visit(node: dict[str, Any]) -> None:
        if _role(node).lower() == "navigation":
            fingerprints.add(_fingerprint(node))
        for child in node.get("children", []):
            visit(child)

    for root in tree.get("nodes", []):
        visit(root)
    return fingerprints


def simplify_accessibility_tree(
    tree: dict[str, list[dict[str, Any]]],
    previous_tree: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Remove repeated and low-value page structure before model rendering."""

    previous_navigation = (
        _navigation_fingerprints(previous_tree) if previous_tree else set()
    )

    def simplify_node(
        node: dict[str, Any], parent_name: str, parent_is_interactive: bool
    ) -> list[dict[str, Any]]:
        role = _role(node)
        role_key = role.lower()
        name = str(node.get("name", "")).strip()
        state = dict(node.get("state", {}))

        if role_key == "image" and not (name and parent_is_interactive):
            return []
        if role == "StaticText":
            if not name or (parent_name and name.casefold() in parent_name.casefold()):
                return []
            return [{"role": role, "name": _cap_text(name)}]

        children = _merge_adjacent_text(
            [
                simplified
                for child in node.get("children", [])
                for simplified in simplify_node(
                    child, name or parent_name, _is_interactive(node)
                )
            ]
        )

        if role_key == "banner":
            controls = _interactive_descendants(children)
            return [{"role": "navigation", "children": controls}] if controls else []
        if role_key == "contentinfo":
            return _footer_essentials(children)
        if role_key in STRUCTURAL_ROLES and not _has_unique_semantics(node):
            return children

        simplified_node: dict[str, Any] = {"role": role}
        if name:
            simplified_node["name"] = name
        if "id" in node:
            simplified_node["id"] = node["id"]
        if state:
            simplified_node["state"] = state
        if children:
            simplified_node["children"] = children

        if (
            role_key not in PROTECTED_ROLES
            and not _is_interactive(node)
            and not _has_unique_semantics(simplified_node)
            and len(children) == 1
        ):
            return children
        return [simplified_node]

    def discard_seen_navigation(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        retained: list[dict[str, Any]] = []
        for node in nodes:
            if (
                _role(node).lower() == "navigation"
                and _fingerprint(node) in previous_navigation
            ):
                continue
            if children := node.get("children"):
                node = {**node, "children": discard_seen_navigation(children)}
            retained.append(node)
        return retained

    simplified = [
        simplified_node
        for node in tree.get("nodes", [])
        for simplified_node in simplify_node(node, "", False)
    ]
    return {"nodes": discard_seen_navigation(_merge_adjacent_text(simplified))}
