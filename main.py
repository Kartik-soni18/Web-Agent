import argparse
import asyncio
import os

from dotenv import load_dotenv

from src.controller import Controller
from src.llm_adapter import OpenRouterActionProvider
from src.models.state import Limits
from src.worker.client import DEFAULT_CDP_URL, WorkerClient


# Tiers in escalation order. The first entry starts the task. role "starter" only picks the
# first URL; role "worker" runs the act loop. A worker escalates to the next entry when its
# code fails or stalls, or to the next entry with screenshots when the page needs vision.
TIERS = {
    "starter": dict(model="openai/gpt-oss-20b", role="starter", screenshots=False,
                    max_tokens=2_048, effort=None, sort="latency"),
    "big": dict(model="z-ai/glm-5.3-flash", role="worker", screenshots=True,
                max_tokens=4_096, effort="low", sort="throughput"),
}
LIMITS = Limits()


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
        name: OpenRouterActionProvider(api_key=api_key, **tier) for name, tier in TIERS.items()
    }
    controller = Controller(
        providers, limits=LIMITS, worker_factory=lambda: WorkerClient(cdp_url, LIMITS)
    )
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
