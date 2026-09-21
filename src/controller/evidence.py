import json
from dataclasses import asdict

from ..models.evidence import Artifact, EvidenceReference, Fact, FactProposal, StateUpdate
from ..models.execution import ExecutionResult
from ..models.observations import BrowserObservation
from ..models.state import AgentState


def apply_state_update(update: StateUpdate, state: AgentState) -> None:
    errors: list[str] = []
    accepted: list[Fact] = []
    for index, proposal in enumerate(update.facts, start=1):
        fact_errors = validate_fact(state, proposal)
        if fact_errors:
            errors.extend(f"fact {index}: {error}" for error in fact_errors)
            continue
        accepted.append(
            Fact(
                claim=proposal.claim,
                kind=proposal.kind,
                context=dict(proposal.context),
                support=list(proposal.support),
                comparison_coverage=list(proposal.comparison_coverage),
            )
        )

    state.remaining_requirements = list(update.remaining_requirements)
    state.facts.extend(accepted)
    state.last_evidence_validation_errors = errors


def store_observation(
    state: AgentState, observation: BrowserObservation, *, step: int
) -> None:
    artifact_id = f"observation:{step}"
    state.artifacts[artifact_id] = Artifact(
        id=artifact_id,
        step=step,
        kind="observation",
        observation=observation,
    )
    state.observation = observation
    state.current_observation_id = artifact_id


def store_execution(
    state: AgentState, execution: ExecutionResult, *, step: int
) -> None:
    artifact_id = f"execution:{step}"
    state.artifacts[artifact_id] = Artifact(
        id=artifact_id,
        step=step,
        kind="execution",
        execution=execution,
    )
    state.last_execution = execution
    state.last_execution_id = artifact_id


def validate_fact(state: AgentState, fact: FactProposal) -> list[str]:
    errors: list[str] = []
    if not fact.claim.strip():
        errors.append("claim must not be empty")
    if fact.kind not in {"observed", "comparison"}:
        errors.append(f"unknown fact kind {fact.kind!r}")
    if not fact.support:
        errors.append("facts require at least one supporting reference")
    for reference in fact.support:
        if error := validate_reference(state, reference):
            errors.append(f"support: {error}")
    if fact.kind == "comparison" and not fact.comparison_coverage:
        errors.append("comparison facts require comparison coverage")
    for reference in fact.comparison_coverage:
        if error := validate_reference(state, reference):
            errors.append(f"comparison coverage: {error}")
    return errors


def validate_reference(state: AgentState, reference: EvidenceReference) -> str | None:
    artifact = state.artifacts.get(reference.source_id)
    if artifact is None:
        return f"source {reference.source_id!r} does not exist"
    if artifact.step >= state.step:
        return f"source {reference.source_id!r} is not from an earlier step"

    has_quote = reference.quote is not None
    has_field = reference.field_path is not None or reference.expected_value is not None
    if has_quote == has_field:
        return "each reference needs exactly one of quote or field_path/expected_value"

    payload = asdict(
        artifact.execution if artifact.kind == "execution" else artifact.observation
    )
    if has_quote:
        if not reference.quote:
            return "evidence quotes must not be empty"
        if reference.quote not in json.dumps(payload, ensure_ascii=False, sort_keys=True):
            return f"quote is not present in source {reference.source_id!r}"
        return None

    if not reference.field_path or reference.expected_value is None:
        return "field references require field_path and expected_value"
    try:
        value = resolve_field(payload, reference.field_path)
    except ValueError as error:
        return str(error)
    if isinstance(value, (dict, list)):
        return f"field path {reference.field_path!r} must resolve to a scalar"
    if str(value) != reference.expected_value:
        return (
            f"field path {reference.field_path!r} in {reference.source_id!r} "
            "does not match expected_value"
        )
    return None


def resolve_field(payload: object, path: str) -> object:
    value = payload
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise ValueError(f"field path {path!r} does not exist")
    return value
