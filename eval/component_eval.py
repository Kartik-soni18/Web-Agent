"""Subcomponents in isolation: action parsing, the OpenRouter provider (fake client), model
context, and outline rendering. No network, no browser.
Run: uv run python -m eval.component_eval"""
import asyncio
import json
from dataclasses import replace

from openai.types.chat import ChatCompletion

from eval.common import finish, run_cases
from src.accessibility import render_accessibility_tree
from src.controller.context import build_model_context
from src.llm_adapter import ModelActionError, OpenRouterActionProvider
from src.llm_adapter.parsing import _parse_action, _parse_starter_action
from src.models.actions import AskUser, ExecuteBrowserCode, Finish
from src.models.execution import ExecutionResult
from src.models.observations import BrowserObservation
from src.models.state import AgentState, Limits

MEMORY = {"facts": [], "remaining": []}


def args(**fields):
    return json.dumps({**fields, "memory": MEMORY})


def raises(call, text=""):
    try:
        call()
    except ModelActionError as error:
        assert text in str(error), f"error {error!r} lacks {text!r}"
        return
    raise AssertionError("expected ModelActionError")


# ---- parsing --------------------------------------------------------------------------

async def parse_execute():
    """parsing: execute_browser_code becomes ExecuteBrowserCode"""
    action = _parse_action(args(action="execute_browser_code", code="return 1", intent="probe"))
    assert isinstance(action, ExecuteBrowserCode) and action.code == "return 1"


async def parse_null_fields():
    """parsing: OpenAI-style null placeholders for unused fields are ignored"""
    action = _parse_action(args(action="execute_browser_code", code="return 1", intent="probe",
                                question=None, answer=None, success=None))
    assert isinstance(action, ExecuteBrowserCode)


async def parse_success_false():
    """parsing: finish keeps an explicit success=false"""
    action = _parse_action(args(action="finish", answer="not found", success=False))
    assert isinstance(action, Finish) and action.success is False


async def parse_ask_user_intent():
    """parsing: ask_user without question falls back to its intent"""
    action = _parse_action(args(action="ask_user", intent="Which size?"))
    assert isinstance(action, AskUser) and action.question == "Which size?"


async def parse_rejects_bad_shapes():
    """parsing: invalid JSON, unknown actions, extra fields and wrong types are rejected
    (seen: 'act returned invalid JSON arguments', 'requires exactly these fields')"""
    raises(lambda: _parse_action('{"action": "finish", "answer": "x'), "invalid JSON")
    raises(lambda: _parse_action(args(action="click")), "unknown action")
    raises(lambda: _parse_action(args(action="execute_browser_code", code="1", intent="x",
                                      success=True)), "exactly these fields")
    raises(lambda: _parse_action(args(action="finish", answer=5)), "must be a str")


async def parse_starter_url():
    """parsing: starter only opens http(s) URLs and escapes them safely into code"""
    action = _parse_starter_action(json.dumps({
        "action": "execute_browser_code", "url": "https://a.com/?q=\"); evil(); //",
        "intent": "open"}))
    assert 'page.goto("https://a.com/?q=\\"); evil(); //"' in action.code, action.code
    raises(lambda: _parse_starter_action(json.dumps({
        "action": "execute_browser_code", "url": "file:///etc/passwd", "intent": "x"})), "http(s)")


# ---- provider (fake OpenAI client) -----------------------------------------------------

def completion(*tool_args, finish_reason="tool_calls", content=None, completion_tokens=50):
    return ChatCompletion.model_validate({
        "id": "c1", "object": "chat.completion", "created": 0, "model": "test/model",
        "choices": [{"index": 0, "finish_reason": finish_reason, "message": {
            "role": "assistant", "content": content,
            "tool_calls": [{"id": str(i), "type": "function",
                            "function": {"name": "act", "arguments": a}}
                           for i, a in enumerate(tool_args)] or None}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": completion_tokens,
                  "total_tokens": 100 + completion_tokens, "cost": 0.001},
    })


def provider(response, model="test/model", role="worker", max_tokens=1_000):
    p = OpenRouterActionProvider(api_key="test", model=model, role=role, screenshots=True,
                                 max_tokens=max_tokens, effort="low", sort="latency")

    async def create(**request):
        p.sent = request
        return response

    p.client.chat.completions.create = create
    return p


CONTEXT = {"original_task": "t", "screenshot": "AAAA"}


async def provider_first_tool_call():
    """provider: with several tool calls, the first one is used and usage is recorded"""
    p = provider(completion(args(action="execute_browser_code", code="return 1", intent="a"),
                            args(action="finish", answer="done", success=True)))
    action = await p.next_action(CONTEXT)
    assert isinstance(action, ExecuteBrowserCode), action
    assert p.last_usage["output_tokens"] == 50 and p.last_usage["cost_usd"] == 0.001


async def provider_screenshot_as_image():
    """provider: the screenshot is sent as an image part, not inside the JSON text"""
    p = provider(completion(args(action="finish", answer="x", success=True)))
    await p.next_action(CONTEXT)
    text, image = p.sent["messages"][1]["content"]
    assert "AAAA" not in text["text"] and image["image_url"]["url"].endswith("AAAA")


async def provider_no_tool_call():
    """provider: plain text or an exhausted budget without a tool call raise ModelActionError"""
    for response, text in ((completion(content="hi"), "ordinary text"),
                           (completion(finish_reason="length"), "completion budget")):
        try:
            await provider(response).next_action(CONTEXT)
        except ModelActionError as error:
            assert text in str(error), str(error)
        else:
            raise AssertionError("expected ModelActionError")


async def provider_truncated_call_names_budget():
    """provider: a tool call cut off by max_tokens says the budget ran out, so the retry
    is shorter (seen: 3 runs died on 'act returned invalid JSON arguments' after runaway
    reasoning hit max_tokens, e.g. output/metrics/051020262149.json)"""
    p = provider(completion('{"action": "execute_browser_code", "code": "for (',
                            finish_reason="length", completion_tokens=1_000))
    try:
        await p.next_action(CONTEXT)
    except ModelActionError as error:
        assert "budget" in str(error), f"retry hint is {str(error)!r}"
    else:
        raise AssertionError("expected ModelActionError")


async def provider_openai_nullable_schema():
    """provider: openai/* models get nullable fields; others keep the strict schema"""
    openai_props = provider(completion(), model="openai/x").tools[0]["function"]["parameters"]["properties"]
    other_props = provider(completion()).tools[0]["function"]["parameters"]["properties"]
    assert openai_props["code"]["type"] == ["string", "null"], openai_props["code"]
    assert other_props["code"]["type"] == "string"


# ---- context ---------------------------------------------------------------------------

def state(**overrides):
    return AgentState(task="Find a price", agent="big", remaining_requirements=["Find a price"],
                      observation=BrowserObservation("https://shop.test/", "Shop", {"nodes": []}),
                      **overrides)


async def context_truncates_execution():
    """context: oversized result, stdout and traceback are cut with a hint; state untouched"""
    s = state(last_execution=ExecutionResult(True, "s" * 9_000, "r" * 9_000, "t" * 9_000))
    execution = build_model_context(s)["last_execution_result"]
    limits = Limits()
    assert len(execution["result"]) < limits.result_chars + 100 and "Truncated" in execution["result"]
    assert len(execution["traceback"]) < limits.traceback_chars + 100
    assert len(s.last_execution.result) == 9_000


async def context_flags():
    """context: stalled_page and captcha_present appear only when they apply"""
    quiet = build_model_context(state(unchanged_observations=1))
    assert quiet["stalled_page"] is None and quiet["captcha_present"] is None
    s = state(unchanged_observations=2)
    s.observation = replace(s.observation, page_geometry={"captcha": True})
    loud = build_model_context(s)
    assert loud["stalled_page"] and loud["captcha_present"]


async def context_untrusted_page():
    """context: page data is wrapped as untrusted and the screenshot is only sent when taken"""
    c = build_model_context(state())
    assert "UNTRUSTED" in c["current_browser_observation"]["trust"]
    assert "screenshot" not in c and "screenshot" in build_model_context(state(screenshot="AAAA"))


# ---- render ----------------------------------------------------------------------------

async def render_priority_and_bounds():
    """render: dialog comes first, link query strings are dropped, outline is bounded"""
    tree = {"nodes": [
        {"role": "main", "children": [{"role": "StaticText", "name": "x" * 200}] * 100},
        {"role": "dialog", "children": [
            {"role": "link", "name": "Go", "state": {"url": "https://a.test/p?track=" + "y" * 500}}]},
    ]}
    outline = render_accessibility_tree(tree, 2_000)
    assert outline.startswith("dialog"), outline[:80]
    assert 'url="https://a.test/p"' in outline and "track=" not in outline
    assert len(outline) <= 2_000 and "truncated" in outline


CASES = [parse_execute, parse_null_fields, parse_success_false, parse_ask_user_intent,
         parse_rejects_bad_shapes, parse_starter_url,
         provider_first_tool_call, provider_screenshot_as_image, provider_no_tool_call,
         provider_truncated_call_names_budget, provider_openai_nullable_schema,
         context_truncates_execution, context_flags, context_untrusted_page,
         render_priority_and_bounds]

if __name__ == "__main__":
    finish([asyncio.run(run_cases("components", CASES))])
