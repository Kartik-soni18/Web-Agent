from dataclasses import dataclass, field


@dataclass
class Memory:
    facts: list[str] = field(default_factory=list)
    remaining: list[str] = field(default_factory=list)


@dataclass
class ExecuteBrowserCode:
    code: str
    intent: str
    memory: Memory = field(default_factory=Memory)


@dataclass
class AskUser:
    question: str
    intent: str
    memory: Memory = field(default_factory=Memory)


@dataclass
class Finish:
    answer: str
    success: bool
    memory: Memory = field(default_factory=Memory)
