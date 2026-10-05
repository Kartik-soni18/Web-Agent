from dataclasses import dataclass, field

from .actions import Finish
from .execution import ExecutionResult
from .observations import BrowserObservation


# ponytail: fixed budgets can cut off valid long tasks; expose per-task limits if measured tasks need them.
@dataclass(frozen=True)
class Limits:
    max_steps: int = 16
    max_run_seconds: int = 300
    model_call_seconds: float = 90
    worker_call_seconds: float = 45
    cleanup_seconds: float = 10
    recent_actions: int = 5
    stall_after: int = 2  # unchanged observations before a step counts as no progress
    result_chars: int = 3_000
    stdout_chars: int = 3_000
    traceback_chars: int = 2_000
    outline_chars: int = 10_000
    worker_response_bytes: int = 8 * 1024 * 1024
    # Worker (Playwright) timeouts in ms: a missed locator fails fast, navigations get longer.
    action_timeout_ms: int = 5_000
    navigation_timeout_ms: int = 30_000
    screenshot_timeout_ms: int = 10_000


@dataclass
class AgentState:
    task: str
    agent: str = ""
    result: Finish | None = None
    clarifications: list[str] = field(default_factory=list)
    observation: BrowserObservation | None = None
    screenshot: str | None = None
    last_execution: ExecutionResult | None = None
    facts: list[str] = field(default_factory=list)
    remaining_requirements: list[str] = field(default_factory=list)
    recent_actions: list[str] = field(default_factory=list)
    unchanged_observations: int = 0
    step: int = 0
