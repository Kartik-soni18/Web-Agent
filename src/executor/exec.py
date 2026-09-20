import ast
import asyncio
import inspect
import traceback
from collections.abc import Mapping
from contextlib import redirect_stdout
from io import StringIO
from types import CodeType

from ..models.execution import ExecutionResult


FILENAME = "<agent-code>"


def _compile(code: str) -> tuple[CodeType, CodeType | None]:
    tree = ast.parse(code, filename=FILENAME, mode="exec")
    expression = None

    if tree.body and isinstance(tree.body[-1], ast.Expr):
        expression = ast.Expression(tree.body.pop().value)
        ast.fix_missing_locations(expression)

    statements = compile(
        tree,
        FILENAME,
        "exec",
        flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
    )
    final_expression = (
        compile(
            expression,
            FILENAME,
            "eval",
            flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
        )
        if expression is not None
        else None
    )
    return statements, final_expression


class AsyncExecutor:
    def __init__(self, namespace: Mapping[str, object] | None = None) -> None:
        self.namespace = dict(namespace or {})

    async def _evaluate(self, compiled: CodeType) -> object:
        value = eval(compiled, self.namespace, self.namespace)
        return await value if inspect.isawaitable(value) else value

    async def execute(self, code: str) -> ExecutionResult:
        output = StringIO()

        try:
            statements, expression = _compile(code)
            with redirect_stdout(output):
                await self._evaluate(statements)
                value = await self._evaluate(expression) if expression is not None else None
        except Exception:
            return ExecutionResult(
                success=False,
                stdout=output.getvalue(),
                traceback=traceback.format_exc(),
            )

        return ExecutionResult(
            success=True,
            stdout=output.getvalue(),
            result=repr(value) if expression is not None else None,
        )

