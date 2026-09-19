from dataclasses import dataclass
@dataclass
class BrowserObservation:
    url: str
    title: str
    accessibility_tree: str
    raw_node_count: int
    kept_node_count: int
    truncated: bool
    screenshot: str | None = None