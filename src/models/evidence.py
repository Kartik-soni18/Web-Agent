from dataclasses import dataclass, field
from typing import Literal

from .execution import ExecutionResult
from .observations import BrowserObservation


ArtifactKind = Literal["execution", "observation"]
FactKind = Literal["observed", "comparison"]


@dataclass
class EvidenceReference:
    source_id: str
    quote: str | None = None
    field_path: str | None = None
    expected_value: str | None = None


@dataclass
class FactProposal:
    claim: str
    kind: FactKind
    context: dict[str, str] = field(default_factory=dict)
    support: list[EvidenceReference] = field(default_factory=list)
    comparison_coverage: list[EvidenceReference] = field(default_factory=list)


@dataclass
class Fact:
    claim: str
    kind: FactKind
    context: dict[str, str]
    support: list[EvidenceReference]
    comparison_coverage: list[EvidenceReference]


@dataclass
class StateUpdate:
    facts: list[FactProposal] = field(default_factory=list)
    remaining_requirements: list[str] = field(default_factory=list)


@dataclass
class Artifact:
    id: str
    step: int
    kind: ArtifactKind
    execution: ExecutionResult | None = None
    observation: BrowserObservation | None = None
