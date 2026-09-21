import argparse
import asyncio
import os

from dotenv import load_dotenv

from src.controller import Controller
from src.openrouter_adapter import OpenRouterActionProvider


MODEL = "z-ai/glm-5.3-flash"
TASKS = [
    "FInd out detail of next codeforces contest and the last codeforces contest"
]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the persistent browser agent")
    parser.add_argument(
        "--allow-unsafe-exec",
        action="store_true",
        help="allow model-generated Python to run with your OS user permissions",
    )
    return parser


async def _run(api_key: str) -> int:
    provider = OpenRouterActionProvider(api_key=api_key, model=MODEL)
    exit_code = 0
    try:
        for index, task in enumerate(TASKS, start=1):
            print(f"Task {index}/{len(TASKS)}: {task}", flush=True)
            try:
                result = await Controller(provider).run(task)
            except Exception as error:
                print(f"Task failed: {type(error).__name__}: {error}", flush=True)
                exit_code = 1
                continue
            print(result.answer, flush=True)
            if not result.success:
                exit_code = 1
    finally:
        await provider.close()
    return exit_code


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if not args.allow_unsafe_exec:
        parser.error(
            "--allow-unsafe-exec is required because generated Python is not sandboxed"
        )

    load_dotenv()
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        parser.error("set OPENROUTER_API_KEY")

    return asyncio.run(_run(api_key))


if __name__ == "__main__":
    raise SystemExit(main())
