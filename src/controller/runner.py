import asyncio
from collections.abc import Callable
from dataclasses import asdict
from time import perf_counter
from typing import TypeVar

from langgraph.graph import END, START, StateGraph

from ..metrics import RunMetrics, RunTrace
from ..models.actions import AskUser, ExecuteBrowserCode, Finish, Memory
from ..models.execution import ExecutionResult
from ..models.observations import BrowserObservation
from ..models.state import AgentState
from ..openrouter_adapter import ModelActionError
from ..worker.client import WorkerClient
from .api import ACTION_NAMES, Action, ActionProvider, AskUserCallback
from .context import build_model_context


Response = TypeVar("Response")
# ponytail: fixed budgets can cut off valid long tasks; expose per-task limits if measured tasks need them.
MAX_STEPS = 16
MAX_RUN_SECONDS = 300
MODEL_CALL_SECONDS = 90
WORKER_CALL_SECONDS = 45


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


def _apply_memory(memory: Memory, state: AgentState) -> None:
    state.facts = list(dict.fromkeys([*state.facts, *memory.facts]))
    state.remaining_requirements = list(memory.remaining)


async def prompt_user(question: str) -> str:
    return await asyncio.to_thread(input, f"{question}\n> ")


class Controller:
    def __init__(
        self,
        action_providers: dict[str, ActionProvider],
        *,
        ask_user: AskUserCallback = prompt_user,
        worker_factory: Callable[[], WorkerClient] = WorkerClient,
    ) -> None:
        self.action_providers = action_providers
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
            models={
                agent: str(getattr(provider, "model", "unknown"))
                for agent, provider in self.action_providers.items()
            },
        )
        self.metrics = metrics
        run_started = perf_counter()
        deadline = run_started + MAX_RUN_SECONDS
        final_answer = None
        final_success = False
        run_error: BaseException | None = None

        try:
            started = await asyncio.wait_for(worker.start(), timeout=WORKER_CALL_SECONDS)
            observation = _response_dataclass(
                started, "observation", BrowserObservation
            )
            state.observation = observation
            result = await self._run_steps(state, worker, metrics, deadline)
            final_answer = result.answer
            final_success = result.success
            return result
        except BaseException as error:
            run_error = error
            raise
        finally:
            try:
                await asyncio.wait_for(worker.close(), timeout=10)
            except BaseException as error:
                if isinstance(error, TimeoutError):
                    await worker.abort()
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
        self, state: AgentState, worker: WorkerClient, metrics: RunMetrics,
        deadline: float,
    ) -> Finish:
        async def step(state: AgentState) -> dict[str, object]:
            self.state = state
            if state.step >= MAX_STEPS or perf_counter() >= deadline:
                reason = (
                    f"{MAX_STEPS} steps" if state.step >= MAX_STEPS
                    else f"{MAX_RUN_SECONDS} seconds"
                )
                state.result = Finish(
                    answer=f"Stopped after {reason} without completing the task.",
                    success=False,
                )
                return vars(state)
            state.step += 1
            trace = RunTrace(step=state.step, agent=state.agent)
            state.screenshot = (
                await asyncio.wait_for(worker.screenshot(), timeout=WORKER_CALL_SECONDS)
                if state.agent == "big" else None
            )
            action = await self._next_action(state, trace, metrics, deadline)

            if isinstance(action, ExecuteBrowserCode):
                await self._execute_browser_code(action, state, worker, trace, metrics, deadline)
                # Code that ran but left the page unchanged twice in a row is a silent no-op,
                # not progress: keep its claimed facts out of memory and escalate.
                made_progress = trace.success and state.unchanged_observations < 2
                if made_progress and state.agent != "starter":
                    _apply_memory(action.memory, state)
            elif isinstance(action, AskUser):
                await self._ask_for_clarification(action, state)
                _apply_memory(action.memory, state)
                trace.success = True
                metrics.add_trace(trace)
            elif isinstance(action, Finish):
                _apply_memory(action.memory, state)
                trace.success = action.success
                metrics.add_trace(trace)
                state.result = action
            else:
                trace.success = False
                trace.error_type = "unsupported_action"
                metrics.add_trace(trace)
                raise TypeError(f"unsupported controller action: {type(action).__name__}")

            # Canvas-like surfaces need eyes; big is the vision model.
            # ponytail: big is sticky; drop back to mid after clean steps if screenshot cost matters.
            needs_vision = bool(
                state.observation and state.observation.page_geometry.get("surfaces")
            )
            if state.agent == "starter":
                state.agent = "big" if needs_vision else "mid"
                state.result = None
            elif isinstance(action, ExecuteBrowserCode) and (not made_progress or needs_vision):
                state.agent = "big"
            return vars(state)

        graph = StateGraph(AgentState)
        for agent in ("starter", "mid", "big"):
            graph.add_node(agent, step)
            graph.add_conditional_edges(
                agent,
                lambda state: END if state.result is not None else state.agent,
                ["mid", "big", END],
            )
        graph.add_edge(START, state.agent)
        result = await graph.compile().ainvoke(vars(state))
        self.state = AgentState(**result)
        return result["result"]

    async def _next_action(
        self, state: AgentState, trace: RunTrace, metrics: RunMetrics,
        deadline: float,
    ) -> Action:
        started = perf_counter()
        provider = self.action_providers[state.agent]
        context = build_model_context(state)
        try:
            for attempt in range(2):
                timeout = min(MODEL_CALL_SECONDS, max(0, deadline - perf_counter()))
                trace.model_attempts += 1
                try:
                    action = await asyncio.wait_for(
                        provider.next_action(context), timeout=timeout,
                    )
                    break
                except (TimeoutError, ModelActionError) as error:
                    if attempt or perf_counter() >= deadline:
                        if isinstance(error, TimeoutError):
                            raise TimeoutError(f"model call exceeded {timeout:.0f} seconds") from error
                        raise
                    context = {
                        **context,
                        "previous_model_error": str(error) or "model response timed out",
                    }
                finally:
                    self._record_usage(trace, provider)
        except BaseException as error:
            trace.llm_duration_seconds = perf_counter() - started
            _record_exception(trace, error, "model_error")
            try:
                metrics.add_trace(trace)
            except Exception as save_error:
                error.add_note(f"Metrics save failed: {save_error}")
            raise

        trace.llm_duration_seconds = perf_counter() - started
        trace.action = ACTION_NAMES.get(type(action), type(action).__name__)
        trace.action_payload = asdict(action)
        return action

    async def _execute_browser_code(
        self,
        action: ExecuteBrowserCode,
        state: AgentState,
        worker: WorkerClient,
        trace: RunTrace,
        metrics: RunMetrics,
        deadline: float,
    ) -> None:
        started = perf_counter()
        timeout = min(WORKER_CALL_SECONDS, max(0, deadline - perf_counter()))
        try:
            response = await asyncio.wait_for(
                worker.execute(action.code), timeout=timeout,
            )
        except BaseException as error:
            trace.execution_duration_seconds = perf_counter() - started
            _record_exception(trace, error, "worker_error")
            if isinstance(error, TimeoutError):
                trace.error_message = f"worker call exceeded {timeout:.0f} seconds"
                try:
                    await worker.abort()
                except Exception as abort_error:
                    error.add_note(f"Worker abort failed: {abort_error}")
            try:
                metrics.add_trace(trace)
            except Exception as save_error:
                error.add_note(f"Metrics save failed: {save_error}")
            raise

        trace.execution_duration_seconds = perf_counter() - started
        execution = _response_dataclass(response, "execution", ExecutionResult)
        observation = _response_dataclass(response, "observation", BrowserObservation)
        previous = state.observation
        state.last_execution = execution
        state.observation = observation
        state.unchanged_observations = (
            state.unchanged_observations + 1
            if previous is not None
            and previous.url == observation.url
            and previous.title == observation.title
            and previous.accessibility_tree == observation.accessibility_tree
            and previous.page_geometry == observation.page_geometry
            else 0
        )
        # Keep what each recent attempt ran and returned, so a repeated dead end is visible.
        outcome = execution.traceback or execution.result or execution.stdout or ""
        state.recent_actions = [
            *state.recent_actions[-4:],
            f"{action.intent}: code {'ran' if execution.success else 'failed'}; "
            f"now at {observation.url}"
            + ("; page unchanged" if state.unchanged_observations else "")
            + f"\n  code: {' '.join(action.code.split())[:200]}"
            + f"\n  returned: {' '.join(outcome.split())[:200]}",
        ]

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

    def _record_usage(self, trace: RunTrace, provider: ActionProvider) -> None:
        trace.llm_request = getattr(provider, "last_request", None)
        trace.llm_response = getattr(provider, "last_response", None)
        usage = getattr(provider, "last_usage", {})
        if not isinstance(usage, dict):
            return
        trace.input_tokens += int(usage.get("input_tokens", 0))
        trace.output_tokens += int(usage.get("output_tokens", 0))
        trace.total_tokens += int(usage.get("total_tokens", 0))
        trace.cost_usd += float(usage.get("cost_usd", 0.0))
        response_model = usage.get("response_model")
        trace.response_model = (
            response_model if isinstance(response_model, str) else None
        )
