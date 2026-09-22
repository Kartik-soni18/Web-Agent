import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


METRICS_DIR = Path(__file__).resolve().parents[2] / "output" / "metrics"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class RunTrace:
    step: int
    agent: str
    started_at: str = field(default_factory=_utc_now)
    action: str | None = None
    action_payload: dict[str, object] = field(default_factory=dict)
    llm_duration_seconds: float = 0.0
    model_attempts: int = 0
    execution_duration_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    response_model: str | None = None
    llm_request: dict[str, object] | None = None
    llm_response: dict[str, object] | None = None
    success: bool | None = None
    error_type: str | None = None
    error_message: str | None = None
    execution_result: dict[str, object] | None = None


@dataclass
class RunMetrics:
    task: str
    models: dict[str, str]
    run_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: str = field(default_factory=_utc_now)
    ended_at: str | None = None
    total_duration_seconds: float = 0.0
    steps: int = 0
    llm_calls: int = 0
    llm_duration_seconds: float = 0.0
    execution_duration_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    execution_failures: int = 0
    model_failures: int = 0
    action_counts: dict[str, int] = field(default_factory=dict)
    error_counts: dict[str, int] = field(default_factory=dict)
    success: bool = False
    final_answer: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    cleanup_error_type: str | None = None
    cleanup_error_message: str | None = None
    traces: list[RunTrace] = field(default_factory=list)

    def add_trace(self, trace: RunTrace) -> None:
        self.traces.append(trace)
        self.steps = len(self.traces)
        self.llm_calls += trace.model_attempts
        self.llm_duration_seconds += trace.llm_duration_seconds
        self.execution_duration_seconds += trace.execution_duration_seconds
        self.input_tokens += trace.input_tokens
        self.output_tokens += trace.output_tokens
        self.total_tokens += trace.total_tokens
        self.cost_usd += trace.cost_usd
        if trace.action is not None:
            self.action_counts[trace.action] = (
                self.action_counts.get(trace.action, 0) + 1
            )
        if trace.error_type is not None:
            self.error_counts[trace.error_type] = (
                self.error_counts.get(trace.error_type, 0) + 1
            )
        if trace.error_type == "model_error":
            self.model_failures += 1
        if trace.action == "execute_browser_code" and trace.success is False:
            self.execution_failures += 1
        self.save()

    def record_cleanup_error(self, error: BaseException) -> None:
        self.cleanup_error_type = type(error).__name__
        self.cleanup_error_message = str(error)

    def finish(
        self,
        *,
        duration_seconds: float,
        success: bool,
        answer: str | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.ended_at = _utc_now()
        self.total_duration_seconds = duration_seconds
        self.success = success
        self.final_answer = answer
        if error is not None:
            self.error_type = type(error).__name__
            self.error_message = str(error)

    def save(self, path: Path | None = None) -> None:
        if path is None:
            path = METRICS_DIR / f"{self.run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
