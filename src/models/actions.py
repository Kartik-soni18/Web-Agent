from dataclasses import dataclass
@dataclass
class ExecuteBrowserCode:
    code: str
    memory: str

@dataclass
class AskUser:
    question: str
    memory: str

@dataclass
class Finish:
    answer: str
    success: bool