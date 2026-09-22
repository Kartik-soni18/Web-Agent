from dataclasses import dataclass, field
from typing import Literal

from .actions import Finish
from .execution import ExecutionResult
from .observations import BrowserObservation


@dataclass
class AgentState:
    task: str
    agent: Literal["starter", "mid", "big"] = "starter"
    result: Finish | None = None
    clarifications: list[str] = field(default_factory=list)
    observation: BrowserObservation | None = None
    last_execution: ExecutionResult | None = None
    facts: list[str] = field(default_factory=list)
    remaining_requirements: list[str] = field(default_factory=list)
    recent_actions: list[str] = field(default_factory=list)
    unchanged_observations: int = 0
    step: int = 0
    consecutive_failures: int = 0
