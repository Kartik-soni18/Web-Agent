from .observations import BrowserObservation
from .execution import ExecutionResult
from dataclasses import dataclass,field
@dataclass
class AgentState:
    task: str
    memory: str = ""
    clarifications: list[str] = field(default_factory=list)
    observation: BrowserObservation | None = None
    last_execution: ExecutionResult | None = None
    step: int = 0
    consecutive_failures: int = 0