"""Harness mechanics across controller + worker + headless Chrome, with scripted models:
failures a real model cannot be made to trigger on demand (timeouts, cleanup, error plumbing).
Free, no API key. Run: uv run python -m eval.harness_eval"""
import asyncio
import json

from eval.common import finish, headless_chrome, open_pages, run_cases
from src.controller import Controller, ScriptedActionProvider
from src.models.actions import ExecuteBrowserCode, Finish
from src.models.state import Limits
from src.worker.client import WorkerClient

PAGE = "<title>Form</title><main><h1>Checkout</h1><button>Pay</button></main>"
SERVE = ("await context.route('http://eval.test/**', route => route.fulfill("
         f"{{ contentType: 'text/html', body: {json.dumps(PAGE)} }}));\n"
         "await page.goto('http://eval.test/');")


def scripted_agent(cdp_url, big, limits=Limits()):
    providers = {"starter": ScriptedActionProvider([ExecuteBrowserCode(SERVE, "open")], role="starter"),
                 "big": ScriptedActionProvider(big, screenshots=True)}
    return Controller(providers, limits=limits,
                      worker_factory=lambda: WorkerClient(cdp_url, limits)), providers["big"]


async def failure_reaches_model(cdp_url):
    """worker -> controller -> context: the failing line of a real batch reaches the model"""
    batch = "state.a = 1;\nstate.b = 2;\nawait page.getByRole('button', { name: 'Missing' }).click({ timeout: 300 });"
    c, big = scripted_agent(cdp_url, [ExecuteBrowserCode(batch, "batch"), Finish("x", False)])
    await c.run("pay")
    last = big.contexts[-1]
    assert "Failed at snippet line 3" in last["last_execution_result"]["traceback"], last["last_execution_result"]
    assert "Failed at snippet line 3" in last["recent_actions"][-1], last["recent_actions"][-1]


async def worker_timeout_cleans_up(cdp_url):
    """controller timeout -> client abort -> worker: a hung snippet ends the run and
    leaves no tab behind (seen: 7 runs 'worker call exceeded N seconds'; leaked tabs broke
    the next task)"""
    before = open_pages(cdp_url)
    c, _ = scripted_agent(cdp_url, [ExecuteBrowserCode("await new Promise(() => {});", "hang")],
                          Limits(worker_call_seconds=3))
    try:
        await c.run("hang")
    except TimeoutError:
        pass
    assert open_pages(cdp_url) == before, open_pages(cdp_url)


async def deadline_mid_browser_call(cdp_url):
    """the run deadline cutting a real browser call ends the run with success=false
    instead of raising (seen: 7 runs 'Task failed: TimeoutError')"""
    c, _ = scripted_agent(cdp_url, [ExecuteBrowserCode("await page.waitForTimeout(8000);", "slow")] * 3,
                          Limits(max_run_seconds=5))
    result = await c.run("slow")
    assert result.success is False, result


HARNESS = [failure_reaches_model, worker_timeout_cleans_up, deadline_mid_browser_call]


if __name__ == "__main__":
    with headless_chrome() as cdp_url:
        finish([asyncio.run(run_cases("harness (scripted models, real browser)", HARNESS, cdp_url))])
