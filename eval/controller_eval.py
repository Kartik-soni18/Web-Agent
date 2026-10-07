"""Controller loop with scripted models and a fake worker: hand-off, budgets, retries, memory,
stalls. No network, no browser. Run: uv run python -m eval.controller_eval"""
import asyncio

import httpx
from openai import APIConnectionError

from eval.common import FakeWorker, finish, run_cases
from src.controller import Controller, ScriptedActionProvider
from src.models.actions import AskUser, ExecuteBrowserCode, Finish, Memory
from src.models.state import Limits


def controller(starter, big, worker=None, limits=Limits(), **kwargs):
    providers = {"starter": ScriptedActionProvider(starter, role="starter"),
                 "big": ScriptedActionProvider(big, screenshots=True)}
    return Controller(providers, limits=limits, worker_factory=lambda: worker or FakeWorker(),
                      **kwargs), providers["big"]


OPEN = [ExecuteBrowserCode("goto", "open")]


async def hand_off():
    """starter opens the first page, then big works and finishes"""
    c, _ = controller(OPEN, [ExecuteBrowserCode("click", "click"), Finish("42", True)])
    result = await c.run("find the answer")
    assert result.answer == "42", result
    assert [t.agent for t in c.metrics.traces] == ["starter", "big", "big"]


async def step_limit():
    """the step limit stops a run that never finishes (seen: 13 runs hit 'Stopped after 16 steps')"""
    c, _ = controller(OPEN, [ExecuteBrowserCode("click", "click")] * 5, limits=Limits(max_steps=3))
    result = await c.run("loop forever")
    assert not result.success and "3 steps" in result.answer, result


async def time_limit():
    """the run deadline stops a slow run with an honest failure, not a crash
    (seen: 7 runs ended on a bare 'TimeoutError' when the deadline cut a browser call)"""
    class Slow(FakeWorker):
        async def execute(self, code):
            await asyncio.sleep(0.6)
            return await super().execute(code)

    c, _ = controller(OPEN, [ExecuteBrowserCode("click", "click")] * 10, Slow(),
                      Limits(max_run_seconds=1))
    result = await c.run("slow task")
    assert not result.success and "seconds" in result.answer, result


async def memory_only_from_progress():
    """facts claimed by failed code are not stored; facts from working code are"""
    c, big = controller(OPEN, [
        ExecuteBrowserCode("ok", "read", Memory(["price is $5"], ["report"])),
        ExecuteBrowserCode("bad", "try", Memory(["unverified claim"], [])),
        Finish("done", True)])
    worker = FakeWorker()
    c.worker_factory = lambda: worker

    async def execute(code):
        response = await FakeWorker.execute(worker, code)
        if code == "bad":
            response["execution"].update(success=False, traceback="Error: boom")
        return response

    worker.execute = execute
    await c.run("find the price")
    facts = big.contexts[-1]["memory"]["facts"]
    assert "price is $5" in facts and "unverified claim" not in facts, facts


async def stall_detected():
    """code that leaves the page unchanged twice is flagged as stalled in the next context"""
    c, big = controller(OPEN, [ExecuteBrowserCode("noop", "wait")] * 3 + [Finish("x", False)],
                        FakeWorker(changes=False))
    await c.run("wait for it")
    assert big.contexts[-1]["stalled_page"], "stalled_page not set after repeated no-ops"


async def failing_line_survives_history():
    """a failed batch keeps its 'Failed at snippet line' note in recent_actions (code is cut
    to 200 chars there, so the note is the only way to see where a long batch stopped)"""
    note = "Failed at snippet line 9: await page.fill('#first-name', 'Test');\nTimeout"
    c, big = controller(OPEN, [ExecuteBrowserCode("x;\n" * 300, "long batch"), Finish("x", False)],
                        FakeWorker(traceback=note))
    await c.run("checkout")
    assert "Failed at snippet line 9" in big.contexts[-1]["recent_actions"][-1]


class Flaky:
    """Provider that raises `error` on its first call, then finishes."""
    role, screenshots = "worker", True

    def __init__(self, error):
        self.error, self.calls, self.contexts = error, 0, []

    async def next_action(self, context):
        self.calls += 1
        self.contexts.append(context)
        if self.calls == 1:
            raise self.error
        return Finish("done", True)


async def retry_bad_model_output():
    """a malformed model action is retried once with the error in the context"""
    from src.llm_adapter import ModelActionError

    big = Flaky(ModelActionError("invalid tool arguments"))
    c = Controller({"starter": ScriptedActionProvider(OPEN, role="starter"), "big": big},
                   worker_factory=FakeWorker)
    assert (await c.run("t")).answer == "done"
    assert big.contexts[1]["previous_model_error"] == "invalid tool arguments"


async def retry_network_blip():
    """a dropped connection to the model is retried instead of killing the run
    (seen: 15 runs ended on 'APIConnectionError: Connection error.')"""
    big = Flaky(APIConnectionError(request=httpx.Request("POST", "https://openrouter.ai")))
    c = Controller({"starter": ScriptedActionProvider(OPEN, role="starter"), "big": big},
                   worker_factory=FakeWorker)
    result = await c.run("t")
    assert result.answer == "done", result


async def ask_user_unavailable():
    """when nobody can answer ask_user, the run ends with success=false instead of crashing
    (seen: 3 runs died on 'EOFError: EOF when reading a line')"""
    async def no_terminal(question):
        raise EOFError("EOF when reading a line")

    c, _ = controller(OPEN, [AskUser("Which account?", "need account")], ask_user=no_terminal)
    result = await c.run("log in")
    assert result.success is False, result


CASES = [hand_off, step_limit, time_limit, memory_only_from_progress, stall_detected,
         failing_line_survives_history, retry_bad_model_output, retry_network_blip,
         ask_user_unavailable]

if __name__ == "__main__":
    finish([asyncio.run(run_cases("controller", CASES))])
