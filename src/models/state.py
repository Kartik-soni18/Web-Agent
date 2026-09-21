from dataclasses import dataclass, field

from .execution import ExecutionResult
from .observations import BrowserObservation


@dataclass
class AgentState:
    task: str
    clarifications: list[str] = field(default_factory=list)
    observation: BrowserObservation | None = None
    last_execution: ExecutionResult | None = None
    facts: list[str] = field(default_factory=list)
    remaining_requirements: list[str] = field(default_factory=list)
    step: int = 0
    consecutive_failures: int = 0
