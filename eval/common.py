"""Shared eval helpers: a tiny case runner, a fake worker, and a throwaway headless Chrome."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from src.metrics import RunMetrics

RunMetrics.save = lambda self, path=None: None  # keep eval runs out of output/metrics

CHROME = os.environ.get(
    "CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)


async def run_cases(title, cases, *args):
    """Run async cases (docstring = name, `assert` = check); returns (passed, total)."""
    print(f"\n== {title}")
    passed = 0
    for case in cases:
        name = " ".join(case.__doc__.split())
        try:
            await case(*args)
            ok, detail = True, ""
        except AssertionError as error:
            ok, detail = False, str(error)
        except Exception as error:
            ok, detail = False, f"{type(error).__name__}: {error}"
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"\n      {detail[:400]}" if detail else ""))
    return passed, len(cases)


def finish(results):
    passed = sum(p for p, _ in results)
    total = sum(n for _, n in results)
    print(f"\n{passed}/{total} passed")
    sys.exit(0 if passed == total else 1)


def observation(url="https://example.com/", nodes=(), **geometry):
    return {"url": url, "title": "Example", "accessibility_tree": {"nodes": list(nodes)},
            "page_geometry": geometry}


class FakeWorker:
    """Worker stand-in. `changes=False` keeps the page identical after every execute."""

    def __init__(self, changes=True, result="ok", traceback=None):
        self.changes, self.result, self.traceback = changes, result, traceback
        self.codes = []

    async def start(self):
        return {"observation": observation()}

    async def execute(self, code):
        self.codes.append(code)
        url = f"https://example.com/{len(self.codes)}" if self.changes else "https://example.com/"
        return {
            "execution": {"success": self.traceback is None, "result": self.result,
                          "traceback": self.traceback},
            "observation": observation(url),
        }

    async def screenshot(self):
        return None

    async def close(self):
        pass

    async def abort(self):
        pass


@contextmanager
def headless_chrome():
    """Yield a CDP URL. Uses EVAL_CDP_URL if set, else starts a private headless Chrome."""
    if url := os.environ.get("EVAL_CDP_URL"):
        yield url
        return
    profile = tempfile.mkdtemp(prefix="eval-chrome-")
    process = subprocess.Popen(
        [CHROME, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={profile}",
         "--no-first-run", "--no-default-browser-check", "--window-size=1280,900"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        port_file = Path(profile, "DevToolsActivePort")
        deadline = time.monotonic() + 20
        while not port_file.exists() or not port_file.read_text().strip():
            if time.monotonic() > deadline or process.poll() is not None:
                raise RuntimeError(f"headless Chrome did not start ({CHROME})")
            time.sleep(0.2)
        yield f"http://127.0.0.1:{port_file.read_text().split()[0]}"
    finally:
        process.terminate()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(profile, ignore_errors=True)


def open_pages(cdp_url):
    """URLs of the browser's open tabs, ignoring Chrome's own new-tab page."""
    with urllib.request.urlopen(f"{cdp_url}/json/list", timeout=5) as response:
        return [t["url"] for t in json.load(response)
                if t["type"] == "page" and not t["url"].startswith("chrome://")]
