"""Browser worker on its own: code execution, error reports, page outline, isolation and
cleanup. Starts a private headless Chrome (or set EVAL_CDP_URL). Pages are served with
page.route, so no internet is needed. Run: uv run python -m eval.observation_eval"""
import asyncio
import json
import time

from eval.common import finish, headless_chrome, open_pages, run_cases
from src.accessibility import render_accessibility_tree
from src.models.state import Limits
from src.worker.client import WorkerClient

SHOP = """<title>Shop</title>
<header><a href="/">Home</a><a href="/cart">Cart</a></header>
<main><h1>Blue Mug</h1><p>Price: $12.50</p><button>Add to cart</button>
<a href="/next">Next page</a></main>
<footer><p>Copyright</p></footer>"""


def serve(html, url="http://eval.test/"):
    """Snippet that serves `html` for eval.test from the context's router, then opens `url`."""
    return (f"await context.route('http://eval.test/**', route => route.fulfill("
            f"{{ contentType: 'text/html', body: {json.dumps(html)} }}));\n"
            f"await page.goto({json.dumps(url)});\n")


async def worker(cdp_url):
    w = WorkerClient(cdp_url)
    await w.start()
    return w


async def outline_and_result(cdp_url):
    """returned values come back and the outline shows main first, keeps the price and
    button, and prunes footer text"""
    w = await worker(cdp_url)
    try:
        r = await w.execute(serve(SHOP) + "return await page.title();")
    finally:
        await w.close()
    outline = render_accessibility_tree(r["observation"]["accessibility_tree"])
    assert "Shop" in r["execution"]["result"], r["execution"]
    assert outline.startswith("main"), outline[:100]
    assert 'button "Add to cart"' in outline and "$12.50" in outline, outline
    assert "Copyright" not in outline, outline


async def failing_line(cdp_url):
    """a failed batch names the failing line and says earlier lines already ran"""
    w = await worker(cdp_url)
    try:
        r = await w.execute(serve(SHOP) + "state.seen = 1;\n"
                            "await page.getByRole('button', { name: 'Missing' }).click({ timeout: 300 });")
    finally:
        await w.close()
    tb = r["execution"]["traceback"]
    assert "Failed at snippet line 4: await page.getByRole('button', { name: 'Missing' })" in tb, tb
    assert "Earlier lines already ran" in tb and "worker.cjs" not in tb, tb


async def failing_first_line(cdp_url):
    """a failure on line 1 does not claim earlier lines ran; syntax errors are reported"""
    w = await worker(cdp_url)
    try:
        first = (await w.execute("throw new Error('boom')"))["execution"]["traceback"]
        syntax = (await w.execute("const x = ;"))["execution"]
    finally:
        await w.close()
    assert "Failed at snippet line 1" in first and "Earlier lines" not in first, first
    assert not syntax["success"] and "SyntaxError" in syntax["traceback"], syntax


async def state_persists(cdp_url):
    """`state` survives between snippets, local variables do not"""
    w = await worker(cdp_url)
    try:
        await w.execute("state.price = '$12.50'; const local = 1;")
        r = await w.execute("return [state.price, typeof local];")
    finally:
        await w.close()
    assert r["execution"]["result"] == "[ '$12.50', 'undefined' ]", r["execution"]


async def node_vs_page_hint(cdp_url):
    """using browser globals in Node code returns a hint to use page.evaluate
    (seen: 'document is not defined', 'window is not defined', 'DOMParser is not defined',
    'Chart is not defined' in 6 steps)"""
    w = await worker(cdp_url)
    try:
        tb = (await w.execute("return document.title;"))["execution"]["traceback"]
    finally:
        await w.close()
    assert "page.evaluate" in tb, tb


async def huge_output(cdp_url):
    """a snippet that prints megabytes does not break the worker pipe
    (seen: 'Separator is not found, and chunk exceed the limit' killed 2 runs)"""
    w = WorkerClient(cdp_url, Limits(worker_response_bytes=1024 * 1024))
    await w.start()
    try:
        big = await w.execute("console.log('x'.repeat(2_000_000)); return 1;")
        after = await w.execute("return 2;")
    finally:
        await w.close()
    assert big["execution"]["result"] == "1" and after["execution"]["result"] == "2"


async def chrome_unreachable(cdp_url):
    """a dead CDP address fails fast with a clear error
    (seen: 5 runs 'connectOverCDP: connect ECONNREFUSED')"""
    started = time.monotonic()
    try:
        await WorkerClient("http://127.0.0.1:9").start()
    except RuntimeError as error:
        assert "127.0.0.1:9" in str(error), str(error)
    else:
        raise AssertionError("start() succeeded against a closed port")
    assert time.monotonic() - started < 15


async def isolated_tasks(cdp_url):
    """each worker gets a fresh context: cookies and localStorage do not leak to the next task
    (seen: saucedemo checkout failed 3/4 runs on a cart left by earlier runs)"""
    page = "<title>t</title><main>x</main>"
    first = await worker(cdp_url)
    try:
        await first.execute(serve(page) + "await page.evaluate(() => { "
                            "localStorage.setItem('cart', '4'); document.cookie = 'session=old'; });")
    finally:
        await first.close()
    second = await worker(cdp_url)
    try:
        r = await second.execute(serve(page) + "return await page.evaluate(() => "
                                 "[localStorage.getItem('cart'), document.cookie]);")
    finally:
        await second.close()
    assert r["execution"]["result"] == "[ null, '' ]", r["execution"]


async def no_orphan_tabs(cdp_url):
    """close and abort both leave no agent tabs behind, popups included"""
    before = open_pages(cdp_url)
    w = await worker(cdp_url)
    await w.execute(serve(SHOP) + "await context.newPage();")
    await w.close()
    w = await worker(cdp_url)
    await w.execute(serve(SHOP))
    await w.abort()
    assert open_pages(cdp_url) == before, open_pages(cdp_url)


async def navigation_mid_evaluate(cdp_url):
    """a snippet whose page navigates away still returns a fresh observation
    (seen: 'Execution context was destroyed, most likely because of a navigation')"""
    w = await worker(cdp_url)
    try:
        r = await w.execute(serve(SHOP) + "await page.evaluate(() => { location.href = '/next'; "
                            "return new Promise(() => {}); });")
    finally:
        await w.close()
    assert r["observation"]["url"] == "http://eval.test/next", r["observation"]["url"]


CASES = [outline_and_result, failing_line, failing_first_line, state_persists,
         node_vs_page_hint, huge_output, chrome_unreachable, isolated_tasks, no_orphan_tabs,
         navigation_mid_evaluate]

if __name__ == "__main__":
    with headless_chrome() as cdp_url:
        finish([asyncio.run(run_cases("browser worker", CASES, cdp_url))])
