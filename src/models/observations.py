from dataclasses import dataclass, field
from typing import Any


@dataclass
class BrowserObservation:
    url: str
    title: str
    accessibility_tree: dict[str, list[dict[str, Any]]]
    page_geometry: dict[str, Any] = field(default_factory=dict)
