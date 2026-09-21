import asyncio
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


SAFE_ENVIRONMENT_NAMES = {
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "PLAYWRIGHT_BROWSERS_PATH",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "WINDIR",
}
# ponytail: 1 MiB supports typical pruned AX trees; use framed IPC for unbounded responses.
WORKER_RESPONSE_LIMIT = 1024 * 1024


def _worker_environment(project_root: Path) -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if name in SAFE_ENVIRONMENT_NAMES or name.startswith("LC_")
    }
    environment["PYTHONPATH"] = str(project_root)
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


class WorkerClient:
    def __init__(self) -> None:
        self.process: asyncio.subprocess.Process | None = None
        self._temporary_directory: TemporaryDirectory[str] | None = None
        self._request_lock = asyncio.Lock()
        self._stderr_chunks: list[bytes] = []
        self._stderr_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "WorkerClient":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        try:
            await self.close()
        except Exception:
            if exc_type is None:
                raise

    @property
    def stderr(self) -> str:
        return b"".join(self._stderr_chunks).decode(errors="replace")

    async def _collect_stderr(self, stream: asyncio.StreamReader) -> None:
        while chunk := await stream.read(8192):
            self._stderr_chunks.append(chunk)

    def _require_process(self) -> asyncio.subprocess.Process:
        if self.process is None:
            raise RuntimeError("worker process has not been started")
        if self.process.returncode is not None:
            raise RuntimeError(
                f"worker exited with code {self.process.returncode}: {self.stderr}"
            )
        return self.process

    async def _request(self, message: dict[str, object]) -> dict[str, object]:
        async with self._request_lock:
            process = self._require_process()
            assert process.stdin is not None
            assert process.stdout is not None

            process.stdin.write(
                json.dumps(message, separators=(",", ":")).encode() + b"\n"
            )
            try:
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as error:
                raise RuntimeError("worker closed its input pipe") from error

            line = await process.stdout.readline()
            if not line:
                await process.wait()
                raise RuntimeError(
                    f"worker exited with code {process.returncode}: {self.stderr}"
                )

            try:
                response = json.loads(line)
            except json.JSONDecodeError as error:
                raise RuntimeError("worker returned invalid JSON") from error
            if not isinstance(response, dict):
                raise RuntimeError("worker response must be a JSON object")
            if response.get("ok") is not True:
                raise RuntimeError(str(response.get("error", "unknown worker error")))
            return response

    async def start(self) -> dict[str, object]:
        if self.process is not None:
            raise RuntimeError("worker process is already started")

        project_root = Path(__file__).resolve().parents[2]
        temporary_directory = TemporaryDirectory(prefix="web-agent-worker-")
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "src.worker.worker",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=WORKER_RESPONSE_LIMIT,
                cwd=temporary_directory.name,
                env=_worker_environment(project_root),
            )
        except Exception:
            temporary_directory.cleanup()
            raise

        self.process = process
        self._temporary_directory = temporary_directory
        self._stderr_chunks.clear()
        assert process.stderr is not None
        self._stderr_task = asyncio.create_task(self._collect_stderr(process.stderr))

        try:
            return await self._request({"type": "start"})
        except Exception:
            await self._stop_process(terminate=True)
            raise

    async def execute(self, code: str) -> dict[str, object]:
        if not isinstance(code, str):
            raise TypeError("code must be a string")
        return await self._request({"type": "execute", "code": code})

    async def observe(self) -> dict[str, object]:
        return await self._request({"type": "observe"})

    async def close(self) -> dict[str, object] | None:
        if self.process is None:
            return None

        try:
            response = await self._request({"type": "close"})
        except Exception:
            await self._stop_process(terminate=True)
            raise

        await self._stop_process(terminate=False)
        return response

    async def _stop_process(self, *, terminate: bool) -> None:
        process = self.process
        stderr_task = self._stderr_task
        temporary_directory = self._temporary_directory
        self.process = None
        self._stderr_task = None
        self._temporary_directory = None

        if process is not None:
            if process.stdin is not None:
                process.stdin.close()
            if terminate and process.returncode is None:
                process.terminate()
            await process.wait()

        if stderr_task is not None:
            await stderr_task
        if temporary_directory is not None:
            temporary_directory.cleanup()
