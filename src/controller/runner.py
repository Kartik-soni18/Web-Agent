import asyncio
from collections.abc import Callable
from dataclasses import asdict
from time import perf_counter
from typing import TypeVar

from ..metrics import RunMetrics, RunTrace
from ..models.actions import AskUser, ExecuteBrowserCode, Finish
from ..models.execution import ExecutionResult
from ..models.observations import BrowserObservation
from ..models.state import AgentState
from ..worker.client import WorkerClient
from .api import ACTION_NAMES, Action, ActionProvider, AskUserCallback
from .context import build_model_context
from .evidence import apply_state_update, store_execution, store_observation


Response = TypeVar("Response")


def _response_dataclass(
    response: dict[str, object], key: str, response_type: type[Response]
) -> Response:
    payload = response.get(key)
    if not isinstance(payload, dict):
        raise RuntimeError(f"worker response is missing a {key} object")
    try:
        return response_type(**payload)
    except TypeError as error:
        raise RuntimeError(f"worker returned an invalid {key} object") from error


def _record_exception(trace: RunTrace, error: BaseException, error_type: str) -> None:
    trace.success = False
    trace.error_type = (
        "cancelled" if isinstance(error, asyncio.CancelledError) else error_type
    )
    trace.error_message = f"{type(error).__name__}: {error}"


async def prompt_user(question: str) -> str:
    return await asyncio.to_thread(input, f"{question}\n> ")


class Controller:
    def __init__(
        self,
        action_provider: ActionProvider,
        *,
        ask_user: AskUserCallback = prompt_user,
        worker_factory: Callable[[], WorkerClient] = WorkerClient,
    ) -> None:
        self.action_provider = action_provider
        self.ask_user = ask_user
        self.worker_factory = worker_factory
        self.state: AgentState | None = None
        self.metrics: RunMetrics | None = None

    async def run(self, task: str) -> Finish:
        if not task.strip():
            raise ValueError("task must not be empty")

        state = AgentState(task=task, remaining_requirements=[task])
        self.state = state
        worker = self.worker_factory()
        metrics = RunMetrics(
            task=task,
            model=str(getattr(self.action_provider, "model", "unknown")),
        )
        self.metrics = metrics
        run_started = perf_counter()
        final_answer = None
        final_success = False
        run_error: BaseException | None = None

        try:
            started = await worker.start()
            observation = _response_dataclass(
                started, "observation", BrowserObservation
            )
            store_observation(state, observation, step=0)
            result = await self._run_steps(state, worker, metrics)
            final_answer = result.answer
            final_success = result.success
            return result
        except BaseException as error:
            run_error = error
            raise
        finally:
            try:
                await worker.close()
            except BaseException as error:
                metrics.record_cleanup_error(error)
                if run_error is None:
                    run_error = error
                    raise
            finally:
                metrics.finish(
                    duration_seconds=perf_counter() - run_started,
                    success=final_success and run_error is None,
                    answer=final_answer,
                    error=run_error,
                )
                try:
                    metrics.save()
                except Exception as save_error:
                    if run_error is None:
                        raise
                    run_error.add_note(f"Metrics save failed: {save_error}")

    async def _run_steps(
        self, state: AgentState, worker: WorkerClient, metrics: RunMetrics
    ) -> Finish:
        while True:
            state.step += 1
            trace = RunTrace(step=state.step)
            action = await self._next_action(state, trace, metrics)
            apply_state_update(action.state_update, state)

            if isinstance(action, ExecuteBrowserCode):
                await self._execute_browser_code(action, state, worker, trace, metrics)
                continue
            if isinstance(action, AskUser):
                await self._ask_for_clarification(action, state)
                trace.success = True
                metrics.add_trace(trace)
                continue
            if isinstance(action, Finish):
                trace.success = action.success
                metrics.add_trace(trace)
                return action

            trace.success = False
            trace.error_type = "unsupported_action"
            metrics.add_trace(trace)
            raise TypeError(f"unsupported controller action: {type(action).__name__}")

    async def _next_action(
        self, state: AgentState, trace: RunTrace, metrics: RunMetrics
    ) -> Action:
        started = perf_counter()
        try:
            action = await self.action_provider.next_action(build_model_context(state))
        except BaseException as error:
            trace.llm_duration_seconds = perf_counter() - started
            _record_exception(trace, error, "model_error")
            self._record_usage(trace)
            try:
                metrics.add_trace(trace)
            except Exception as save_error:
                error.add_note(f"Metrics save failed: {save_error}")
            raise

        trace.llm_duration_seconds = perf_counter() - started
        trace.action = ACTION_NAMES.get(type(action), type(action).__name__)
        trace.action_payload = asdict(action)
        self._record_usage(trace)
        return action

    async def _execute_browser_code(
        self,
        action: ExecuteBrowserCode,
        state: AgentState,
        worker: WorkerClient,
        trace: RunTrace,
        metrics: RunMetrics,
    ) -> None:
        started = perf_counter()
        try:
            response = await worker.execute(action.code)
        except BaseException as error:
            trace.execution_duration_seconds = perf_counter() - started
            _record_exception(trace, error, "worker_error")
            try:
                metrics.add_trace(trace)
            except Exception as save_error:
                error.add_note(f"Metrics save failed: {save_error}")
            raise

        trace.execution_duration_seconds = perf_counter() - started
        execution = _response_dataclass(response, "execution", ExecutionResult)
        observation = _response_dataclass(response, "observation", BrowserObservation)
        store_execution(state, execution, step=state.step)
        store_observation(state, observation, step=state.step)
        state.consecutive_failures = (
            0 if execution.success else state.consecutive_failures + 1
        )

        trace.success = execution.success
        trace.execution_result = asdict(execution)
        if not trace.success:
            trace.error_type = "execution_error"
            trace.error_message = execution.traceback
        metrics.add_trace(trace)

    async def _ask_for_clarification(
        self, action: AskUser, state: AgentState
    ) -> None:
        answer = await self.ask_user(action.question)
        if not isinstance(answer, str):
            raise TypeError("ask_user callback must return a string")
        state.clarifications.append(f"Question: {action.question}\nAnswer: {answer}")

    def _record_usage(self, trace: RunTrace) -> None:
        trace.llm_request = getattr(self.action_provider, "last_request", None)
        trace.llm_response = getattr(self.action_provider, "last_response", None)
        usage = getattr(self.action_provider, "last_usage", {})
        if not isinstance(usage, dict):
            return
        trace.input_tokens = int(usage.get("input_tokens", 0))
        trace.output_tokens = int(usage.get("output_tokens", 0))
        trace.total_tokens = int(usage.get("total_tokens", 0))
        trace.cost_usd = float(usage.get("cost_usd", 0.0))
        response_model = usage.get("response_model")
        trace.response_model = (
            response_model if isinstance(response_model, str) else None
        )
