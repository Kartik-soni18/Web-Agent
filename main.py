import argparse
import asyncio
import os

from dotenv import load_dotenv

from src.controller import Controller
from src.llm_adapter import OpenRouterActionProvider
from src.worker.client import DEFAULT_CDP_URL, WorkerClient


MODELS = {
    "starter": "openai/gpt-oss-20b",
    "mid": "z-ai/glm-5.3-flash",
    "big": "z-ai/glm-5.3-flash",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the browser agent in an attached Chrome")
    parser.add_argument("tasks", nargs="+", metavar="TASK", help="tasks to run in order")
    parser.add_argument(
        "--allow-unsafe-exec",
        action="store_true",
        help="allow model-generated JavaScript to run with your OS user permissions",
    )
    parser.add_argument(
        "--cdp", default=DEFAULT_CDP_URL, help=f"Chrome DevTools URL to attach to (default {DEFAULT_CDP_URL})"
    )
    return parser


async def _run(api_key: str, tasks: list[str], cdp_url: str) -> int:
    providers = {
        agent: OpenRouterActionProvider(api_key=api_key, model=model, starter=agent == "starter")
        for agent, model in MODELS.items()
    }
    controller = Controller(providers, worker_factory=lambda: WorkerClient(cdp_url))
    exit_code = 0
    try:
        for index, task in enumerate(tasks, start=1):
            print(f"Task {index}/{len(tasks)}: {task}", flush=True)
            try:
                result = await controller.run(task)
            except Exception as error:
                print(f"Task failed: {type(error).__name__}: {error}", flush=True)
                exit_code = 1
                continue
            print(result.answer, flush=True)
            if not result.success:
                exit_code = 1
    finally:
        await asyncio.gather(*(provider.close() for provider in providers.values()))
    return exit_code


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if not args.allow_unsafe_exec:
        parser.error("--allow-unsafe-exec is required because generated JavaScript is not sandboxed")

    load_dotenv()
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        parser.error("set OPENROUTER_API_KEY")

    return asyncio.run(_run(api_key, args.tasks, args.cdp))


if __name__ == "__main__":
    raise SystemExit(main())
