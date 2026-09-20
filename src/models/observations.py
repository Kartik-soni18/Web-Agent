from dataclasses import dataclass
from typing import Any


@dataclass
class BrowserObservation:
    url: str
    title: str
    accessibility_tree: dict[str, list[dict[str, Any]]]
    raw_node_count: int
    kept_node_count: int
