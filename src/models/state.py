from dataclasses import dataclass, field

from .execution import ExecutionResult
from .observations import BrowserObservation


@dataclass
class AgentState:
    task: str
    memory: str = ""
    clarifications: list[str] = field(default_factory=list)
    observation: BrowserObservation | None = None
    last_execution: ExecutionResult | None = None
    step: int = 0
    consecutive_failures: int = 0
