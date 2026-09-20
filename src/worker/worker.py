import asyncio
import json
import sys
from contextlib import AsyncExitStack
from dataclasses import asdict
from io import StringIO
from typing import TextIO

from ..executor.exec import AsyncExecutor
from ..session.extract_observation import browser_observation
from ..session.runtime import START_URL, Runtime, browser_runtime


class BrowserWorker:
    def __init__(self, start_url: str | None = START_URL) -> None:
        self.start_url = start_url
        self._stack: AsyncExitStack | None = None
        self.runtime: Runtime | None = None
        self.executor: AsyncExecutor | None = None

    async def start(self) -> dict[str, object]:
        if self.runtime is not None:
            raise ValueError("worker is already started")

        stack = AsyncExitStack()
        try:
            runtime = await stack.enter_async_context(browser_runtime(self.start_url))
            executor = AsyncExecutor(runtime.execution_namespace())
            observation = await browser_observation(runtime.page)
        except Exception:
            await stack.aclose()
            raise

        self._stack = stack
        self.runtime = runtime
        self.executor = executor
        return {
            "ok": True,
            "type": "started",
            "observation": asdict(observation),
        }

    def _require_started(self) -> tuple[Runtime, AsyncExecutor]:
        if self.runtime is None or self.executor is None:
            raise ValueError("worker has not been started")
        return self.runtime, self.executor

    async def execute(self, code: str) -> dict[str, object]:
        runtime, executor = self._require_started()
        execution = await executor.execute(code)
        observation = await browser_observation(runtime.page)
        return {
            "ok": True,
            "type": "executed",
            "execution": asdict(execution),
            "observation": asdict(observation),
        }

    async def observe(self) -> dict[str, object]:
        runtime, _ = self._require_started()
        observation = await browser_observation(runtime.page)
        return {
            "ok": True,
            "type": "observed",
            "observation": asdict(observation),
        }

    async def close(self) -> dict[str, object]:
        stack = self._stack
        self._stack = None
        self.runtime = None
        self.executor = None
        if stack is not None:
            await stack.aclose()
        return {"ok": True, "type": "closed"}

    async def handle(self, message: dict[str, object]) -> dict[str, object]:
        message_type = message.get("type")
        if not isinstance(message_type, str):
            raise ValueError("message type must be a string")

        if message_type == "start":
            return await self.start()
        if message_type == "execute":
            code = message.get("code")
            if not isinstance(code, str):
                raise ValueError("execute requires a string code field")
            return await self.execute(code)
        if message_type == "observe":
            return await self.observe()
        if message_type == "close":
            return await self.close()
        raise ValueError(f"unknown message type: {message_type}")


def _write_response(stream: TextIO, response: dict[str, object]) -> None:
    stream.write(json.dumps(response, separators=(",", ":")))
    stream.write("\n")
    stream.flush()


async def serve(
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    *,
    start_url: str | None = START_URL,
) -> None:
    worker = BrowserWorker(start_url)
    try:
        while line := await asyncio.to_thread(stdin.readline):
            if not line.strip():
                continue

            close_requested = False
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("message must be a JSON object")
                close_requested = message.get("type") == "close"
                response = await worker.handle(message)
            except (json.JSONDecodeError, ValueError) as error:
                response = {"ok": False, "type": "error", "error": str(error)}
            except Exception as error:
                response = {
                    "ok": False,
                    "type": "error",
                    "error": f"{type(error).__name__}: {error}",
                }

            _write_response(stdout, response)
            if close_requested and response["ok"]:
                break
    finally:
        await worker.close()


if __name__ == "__main__":
    asyncio.run(serve())

