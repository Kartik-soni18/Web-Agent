import argparse
import asyncio
import os

from dotenv import load_dotenv

from src.controller import Controller
from src.openrouter_adapter import OpenRouterActionProvider


MODEL = "deepseek/deepseek-v4.1-flash"
TASK = (
    "Search DuckDuckGo for the official Python asyncio documentation, open the official Python documentation result, and return the page title, URL, and first three section headings"
)


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
    try:
        result = await Controller(provider).run(TASK)
    finally:
        await provider.close()
    print(result.answer)
    return 0 if result.success else 1


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
