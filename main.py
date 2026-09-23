import argparse
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

from src.controller import Controller
from src.openrouter_adapter import OpenRouterActionProvider
from src.worker.client import WorkerClient


MODELS = {
    "starter": "openai/gpt-oss-20b",
    "mid": "z-ai/glm-5.3-flash",
    "big": "z-ai/glm-5.3-flash",
}
CDP_PORT = 9222
TASKS = [
    "On books.toscrape.com, find a book priced over £100."
]

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the persistent browser agent")
    parser.add_argument(
        "--allow-unsafe-exec",
        action="store_true",
        help="allow model-generated JavaScript to run with your OS user permissions",
    )
    parser.add_argument(
        "--miniwob",
        nargs="+",
        metavar="TASK_ID",
        help="run BrowserGym MiniWoB tasks (e.g. miniwob.click-button) instead of TASKS; needs MINIWOB_URL",
    )
    parser.add_argument("--seed", type=int, default=0, help="MiniWoB task seed")
    return parser


async def _run_miniwob(providers, task_ids: list[str], seed: int) -> int:
    from browsergym.miniwob import ALL_MINIWOB_TASKS
    from playwright.sync_api import sync_playwright

    tasks = {cls.get_task_id(): cls for cls in ALL_MINIWOB_TASKS}
    unknown = [task_id for task_id in task_ids if task_id not in tasks]
    if unknown:
        raise ValueError(f"unknown MiniWoB tasks: {unknown}")

    # Sync Playwright objects must stay on the thread that created them, outside the event loop.
    bgym = ThreadPoolExecutor(max_workers=1)
    loop = asyncio.get_running_loop()
    on_bgym = lambda fn, *args: loop.run_in_executor(bgym, fn, *args)

    def launch():
        pw = sync_playwright().start()
        context = pw.chromium.launch_persistent_context(
            "", headless=False, args=[f"--remote-debugging-port={CDP_PORT}"]
        )
        return pw, context

    def setup(task_id):
        task = tasks[task_id](seed=seed)
        page = context.pages[0]
        page.set_viewport_size(task.viewport)
        goal, _ = task.setup(page)
        return task, goal

    pw, context = await on_bgym(launch)
    controller = Controller(
        providers, worker_factory=lambda: WorkerClient(f"http://127.0.0.1:{CDP_PORT}")
    )
    rewards = []
    try:
        for task_id in task_ids:
            task, goal = await on_bgym(setup, task_id)
            print(f"{task_id}: {goal}", flush=True)
            try:
                await controller.run(
                    f"The task page is already open. Complete it on this page without navigating away: {goal}",
                    page_ready=True,
                )
                reward, _, _, info = await on_bgym(task.validate, task.page, [])
            except Exception as error:
                print(f"Task failed: {type(error).__name__}: {error}", flush=True)
                reward, info = 0.0, {}
            finally:
                await on_bgym(task.teardown)
            rewards.append(reward)
            print(
                f"{task_id}: reward={reward} raw_reward={info.get('RAW_REWARD_GLOBAL')} "
                f"done={info.get('DONE_GLOBAL')} reason={info.get('REWARD_REASON') or info.get('error')}",
                flush=True,
            )
    finally:
        await on_bgym(lambda: (context.close(), pw.stop()))
        bgym.shutdown()
    print(f"MiniWoB success rate: {sum(rewards)}/{len(rewards)}", flush=True)
    return 0 if all(rewards) else 1


async def _run(api_key: str, miniwob: list[str] | None, seed: int) -> int:
    providers = {
        agent: OpenRouterActionProvider(
            api_key=api_key, model=model, starter=agent == "starter"
        )
        for agent, model in MODELS.items()
    }
    exit_code = 0
    try:
        if miniwob:
            return await _run_miniwob(providers, miniwob, seed)
        for index, task in enumerate(TASKS, start=1):
            print(f"Task {index}/{len(TASKS)}: {task}", flush=True)
            try:
                result = await Controller(providers).run(task)
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
        parser.error(
            "--allow-unsafe-exec is required because generated JavaScript is not sandboxed"
        )

    load_dotenv()
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        parser.error("set OPENROUTER_API_KEY")

    return asyncio.run(_run(api_key, args.miniwob, args.seed))


if __name__ == "__main__":
    raise SystemExit(main())
