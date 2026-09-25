import asyncio
import json
import unittest
from dataclasses import asdict
from time import perf_counter
from unittest.mock import patch

from src.controller import Controller, ScriptedActionProvider
from src.controller.context import build_model_context
from src.metrics import RunMetrics, RunTrace
from src.models.actions import ExecuteBrowserCode, Finish, Memory
from src.models.observations import BrowserObservation
from src.models.state import AgentState
from src.openrouter_adapter import ModelActionError, _parse_starter_action


class ControllerBehaviorTest(unittest.IsolatedAsyncioTestCase):
    async def test_starter_only_generates_navigation_from_http_url(self):
        action = _parse_starter_action(json.dumps({
            "action": "execute_browser_code",
            "url": "https://example.com/search?q=books",
            "intent": "open search",
        }))

        self.assertIn("await page.goto", action.code)
        self.assertIn("waitUntil: 'commit'", action.code)
        self.assertNotIn("DOMParser", action.code)
        with self.assertRaises(ModelActionError):
            _parse_starter_action(json.dumps({
                "action": "execute_browser_code", "url": "file:///etc/passwd",
                "intent": "open file",
            }))

    async def test_bad_model_action_is_retried_once_and_usage_is_counted(self):
        class Provider:
            calls = 0
            last_usage = {}

            async def next_action(self, context):
                self.calls += 1
                self.last_usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
                if self.calls == 1:
                    raise ModelActionError("invalid tool arguments")
                self.retry_context = context
                return Finish(answer="done", success=True)

        provider = Provider()
        controller = Controller({"mid": provider})
        trace = RunTrace(step=1, agent="mid")
        metrics = RunMetrics(task="task", models={"mid": "test"})

        action = await controller._next_action(
            AgentState(task="task", agent="mid"), trace, metrics, perf_counter() + 5
        )

        self.assertIsInstance(action, Finish)
        self.assertEqual(provider.calls, 2)
        self.assertEqual(trace.model_attempts, 2)
        self.assertEqual(trace.total_tokens, 30)
        self.assertEqual(provider.retry_context["previous_model_error"], "invalid tool arguments")

    async def test_failed_code_does_not_commit_claimed_memory(self):
        observation = BrowserObservation(
            url="https://example.com", title="Example",
            accessibility_tree={"nodes": []},
        )

        class Worker:
            calls = 0

            async def execute(self, code):
                self.calls += 1
                return {
                    "execution": {"success": self.calls == 1, "traceback": "failed" if self.calls == 2 else None},
                    "observation": asdict(observation),
                }

            async def screenshot(self):
                return None

        starter = ScriptedActionProvider([ExecuteBrowserCode("navigate", "open page")])
        mid = ScriptedActionProvider([
            ExecuteBrowserCode("fail", "try action", Memory(facts=["unverified claim"], remaining=[]))
        ])
        big = ScriptedActionProvider([Finish(answer="blocked", success=False)])
        controller = Controller({"starter": starter, "mid": mid, "big": big})
        state = AgentState(task="task", observation=observation, remaining_requirements=["task"])
        metrics = RunMetrics(task="task", models={})
        metrics.save = lambda: None

        await controller._run_steps(state, Worker(), metrics, perf_counter() + 5)

        self.assertNotIn("unverified claim", big.contexts[0]["memory"]["facts"])
        self.assertEqual(big.contexts[0]["memory"]["remaining"], ["task"])
        self.assertTrue(big.contexts[0]["recent_actions"][-1].startswith(
            "try action: code failed; now at https://example.com; page unchanged"))
        self.assertIsNotNone(big.contexts[0]["stalled_page"])

    async def test_worker_timeout_aborts_stuck_worker(self):
        class Worker:
            aborted = False

            async def execute(self, code):
                await asyncio.Event().wait()

            async def abort(self):
                self.aborted = True

        worker = Worker()
        controller = Controller({})
        metrics = RunMetrics(task="task", models={})
        metrics.save = lambda: None
        trace = RunTrace(step=1, agent="mid")

        with patch("src.controller.runner.WORKER_CALL_SECONDS", 0.01):
            with self.assertRaises(TimeoutError):
                await controller._execute_browser_code(
                    ExecuteBrowserCode("while(true){}", "stuck"),
                    AgentState(task="task", agent="mid"), worker, trace,
                    metrics, perf_counter() + 5,
                )

        self.assertTrue(worker.aborted)
        self.assertEqual(trace.error_type, "worker_error")
