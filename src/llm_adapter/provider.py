import json
from copy import deepcopy

from openai import APIStatusError, AsyncOpenAI

from ..models.actions import AskUser, ExecuteBrowserCode, Finish
from .parsing import ModelActionError, _parse_action, _parse_starter_action
from .prompts import STARTER_SYSTEM_PROMPT, SYSTEM_PROMPT
from .tools import TOOLS


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterActionProvider:
    def __init__(self, *, api_key: str, model: str, starter: bool = False) -> None:
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is required")
        if not model:
            raise ValueError("an OpenRouter model is required")
        self.model = model
        self.starter = starter
        self.tools = deepcopy(TOOLS)
        if starter:
            self.tools[0]["function"]["description"] = "Choose the first page URL only."
            parameters = self.tools[0]["function"]["parameters"]
            parameters["properties"] = {
                key: value for key, value in parameters["properties"].items()
                if key in {"action", "intent"}
            }
            parameters["properties"]["url"] = {
                "type": "string", "description": "Full http(s) URL of the first page to open."
            }
            parameters["properties"]["action"]["enum"] = ["execute_browser_code"]
            parameters["required"] = ["action", "url", "intent"]
        self.client = AsyncOpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
        self.last_usage: dict[str, int | float | str] = {}
        self.last_request: dict[str, object] | None = None
        self.last_response: dict[str, object] | None = None

    async def next_action(
        self, context: dict[str, object]
    ) -> ExecuteBrowserCode | AskUser | Finish:
        context = dict(context)
        screenshot = context.pop("screenshot", None)
        # ponytail: screenshots are stored in metrics traces via llm_request; strip them if traces grow too large.
        user_content: str | list[dict[str, object]] = json.dumps(context)
        if screenshot:
            user_content = [
                {"type": "text", "text": user_content},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{screenshot}"},
                },
            ]
        self.last_usage = {}
        self.last_response = None
        self.last_request = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": STARTER_SYSTEM_PROMPT if self.starter else SYSTEM_PROMPT,
                },
                {"role": "user", "content": user_content},
            ],
            "tools": self.tools,
            "tool_choice": "required",
            "parallel_tool_calls": False,
            "max_completion_tokens": 2_048 if self.starter else 4_096,
            "extra_body": {
                "usage": {"include": True},
                "provider": {"sort": "latency" if self.starter else "throughput"},
                **({"reasoning": {"effort": "low"}} if not self.starter else {}),
            },
        }
        try:
            completion = await self.client.chat.completions.create(**self.last_request)
        except APIStatusError as error:
            self.last_response = {
                "error": error.body,
                "status_code": error.status_code,
                "request_id": error.request_id,
            }
            raise
        self.last_response = completion.model_dump(mode="json")
        if completion.usage is not None:
            usage = completion.usage.model_dump()
            self.last_usage = {
                "input_tokens": int(usage.get("prompt_tokens") or 0),
                "output_tokens": int(usage.get("completion_tokens") or 0),
                "total_tokens": int(usage.get("total_tokens") or 0),
                "cost_usd": float(usage.get("cost") or 0.0),
                "response_model": completion.model,
            }
        if not completion.choices:
            raise ModelActionError("model returned no choices")

        choice = completion.choices[0]
        message = choice.message
        tool_calls = message.tool_calls or []
        if not tool_calls:
            if choice.finish_reason == "length":
                raise ModelActionError(
                    "model used its completion budget before producing a tool call; "
                    "return a shorter action"
                )
            raise ModelActionError(
                "model returned ordinary text instead of a tool call; choose an "
                "OpenRouter model that supports tool calling"
            )
        actions = []
        for tool_call in tool_calls:
            if tool_call.type != "function" or tool_call.function.name != "act":
                raise ModelActionError("model returned an unexpected function tool call")
            actions.append(
                _parse_starter_action(tool_call.function.arguments)
                if self.starter else _parse_action(tool_call.function.arguments)
            )
        # Extra calls (repeats, or a premature finish after code) wait for the first one's result.
        if self.starter and not isinstance(actions[0], ExecuteBrowserCode):
            raise ModelActionError("starter must execute browser code")
        return actions[0]

    async def close(self) -> None:
        await self.client.close()
