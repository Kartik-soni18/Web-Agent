from dataclasses import dataclass


@dataclass
class ExecutionResult:
    success: bool
    stdout: str = ""
    result: str | None = None
    traceback: str | None = None
