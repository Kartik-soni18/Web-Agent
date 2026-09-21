from dataclasses import dataclass, field

from .evidence import StateUpdate


@dataclass
class ExecuteBrowserCode:
    code: str
    intent: str
    state_update: StateUpdate = field(default_factory=StateUpdate)


@dataclass
class AskUser:
    question: str
    intent: str
    state_update: StateUpdate = field(default_factory=StateUpdate)


@dataclass
class Finish:
    answer: str
    success: bool
    state_update: StateUpdate = field(default_factory=StateUpdate)
