import json
from urllib.parse import urlsplit

from ..models.actions import AskUser, ExecuteBrowserCode, Finish, Memory


class ModelActionError(RuntimeError):
    pass


def _require_exact_keys(
    payload: dict[str, object], keys: set[str], label: str
) -> None:
    if set(payload) != keys:
        raise ModelActionError(
            f"{label} requires exactly these fields: {', '.join(sorted(keys))}"
        )


def _parse_memory(payload: object) -> Memory:
    if not isinstance(payload, dict):
        raise ModelActionError("memory must be an object")
    _require_exact_keys(payload, {"facts", "remaining"}, "memory")
    facts = payload["facts"]
    remaining = payload["remaining"]
    if not isinstance(facts, list) or not all(isinstance(fact, str) for fact in facts):
        raise ModelActionError("memory facts must be an array of strings")
    if not isinstance(remaining, list) or not all(
        isinstance(requirement, str) for requirement in remaining
    ):
        raise ModelActionError("memory remaining must be an array of strings")
    return Memory(facts=facts, remaining=remaining)


def _parse_action(raw_arguments: str) -> ExecuteBrowserCode | AskUser | Finish:
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as error:
        raise ModelActionError("act returned invalid JSON arguments") from error
    if not isinstance(arguments, dict):
        raise ModelActionError("act arguments must be a JSON object")

    expected = {
        "execute_browser_code": {
            "action": str,
            "code": str,
            "intent": str,
            "memory": dict,
        },
        "ask_user": {"action": str, "question": str, "intent": str, "memory": dict},
        "finish": {"action": str, "answer": str, "success": bool, "memory": dict},
    }
    action_name = arguments.get("action")
    if not isinstance(action_name, str):
        raise ModelActionError("act.action must be a string")
    action_fields = expected.get(action_name)
    if action_fields is None:
        raise ModelActionError(f"act has unknown action: {action_name}")
    if action_name == "finish" and "success" not in arguments:
        arguments["success"] = True
    if action_name == "ask_user" and "question" not in arguments and "intent" in arguments:
        arguments["question"] = arguments["intent"]
    _require_exact_keys(arguments, set(action_fields), f"act.{action_name}")
    for field, field_type in action_fields.items():
        if type(arguments[field]) is not field_type:
            raise ModelActionError(
                f"act.{action_name}.{field} must be a {field_type.__name__}"
            )

    memory = _parse_memory(arguments["memory"])
    if action_name == "execute_browser_code":
        return ExecuteBrowserCode(
            code=arguments["code"], intent=arguments["intent"], memory=memory
        )
    if action_name == "ask_user":
        return AskUser(
            question=arguments["question"], intent=arguments["intent"], memory=memory
        )
    return Finish(answer=arguments["answer"], success=arguments["success"], memory=memory)


def _parse_starter_action(raw_arguments: str) -> ExecuteBrowserCode:
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as error:
        raise ModelActionError("act returned invalid JSON arguments") from error
    if not isinstance(arguments, dict):
        raise ModelActionError("act arguments must be a JSON object")
    _require_exact_keys(arguments, {"action", "url", "intent"}, "starter act")
    if arguments["action"] != "execute_browser_code":
        raise ModelActionError("starter must open a page")
    if not isinstance(arguments["intent"], str) or not isinstance(arguments["url"], str):
        raise ModelActionError("starter intent and url must be strings")
    try:
        url = urlsplit(arguments["url"])
    except ValueError as error:
        raise ModelActionError("starter returned an invalid URL") from error
    if url.scheme not in {"http", "https"} or not url.netloc:
        raise ModelActionError("starter URL must be http(s)")
    code = (
        f"await page.goto({json.dumps(arguments['url'])}, "
        "{ waitUntil: 'commit', timeout: 20000 }); "
        "await page.waitForLoadState('domcontentloaded', { timeout: 5000 }).catch(() => {});"
    )
    return ExecuteBrowserCode(code=code, intent=arguments["intent"])
