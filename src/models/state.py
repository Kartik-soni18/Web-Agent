from dataclasses import dataclass, field

from .evidence import Artifact, Fact
from .execution import ExecutionResult
from .observations import BrowserObservation


@dataclass
class AgentState:
    task: str
    clarifications: list[str] = field(default_factory=list)
    observation: BrowserObservation | None = None
    last_execution: ExecutionResult | None = None
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    facts: list[Fact] = field(default_factory=list)
    remaining_requirements: list[str] = field(default_factory=list)
    current_observation_id: str | None = None
    last_execution_id: str | None = None
    last_evidence_validation_errors: list[str] = field(default_factory=list)
    step: int = 0
    consecutive_failures: int = 0
