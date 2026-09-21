from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from typing import Protocol, TypeAlias

from ..models.actions import AskUser, ExecuteBrowserCode, Finish


Action: TypeAlias = ExecuteBrowserCode | AskUser | Finish
ModelContext: TypeAlias = dict[str, object]
AskUserCallback: TypeAlias = Callable[[str], Awaitable[str]]

ACTION_NAMES = {
    ExecuteBrowserCode: "execute_browser_code",
    AskUser: "ask_user",
    Finish: "finish",
}


class ActionProvider(Protocol):
    async def next_action(self, context: ModelContext) -> Action: ...


class ScriptedActionProvider:
    """A deterministic model substitute for exercising the controller loop."""

    def __init__(self, actions: Iterable[Action]) -> None:
        self._actions = deque(actions)
        self.contexts: list[ModelContext] = []

    async def next_action(self, context: ModelContext) -> Action:
        self.contexts.append(context)
        if not self._actions:
            raise RuntimeError("scripted action provider ran out of actions")
        return self._actions.popleft()
