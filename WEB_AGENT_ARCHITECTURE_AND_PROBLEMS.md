# Web agent architecture and performance review

Reviewed September 23, 2026. This describes the current JavaScript worker and three-model controller, not the older Python worker described in `output/google-flights-failure-analysis.md`. No model configuration was changed.

## Current architecture

```text
main.py (task and fixed starter / mid / big model IDs)
  -> Controller.run() creates AgentState and a persistent WorkerClient
  -> LangGraph step: starter, then mid; a failed browser-code result selects big
  -> build_model_context() sends task, facts, remaining checklist,
     last execution result, and current accessibility outline
  -> OpenRouterActionProvider requests one act tool call
     (execute_browser_code, ask_user, or finish)
  -> WorkerClient sends JSON over stdin/stdout to worker.cjs
  -> worker.cjs executes model-written async JavaScript in Playwright,
     keeps browser/page/state, then reads and simplifies the full CDP AX tree
  -> Controller updates state and saves a trace under output/metrics/
  -> repeat until the model returns finish or an exception aborts the run
```

The key paths are `main.py`, `src/controller/runner.py`, `src/controller/context.py`, `src/openrouter_adapter.py`, `src/worker/client.py`, `src/worker/worker.cjs`, and `src/metrics/__init__.py`.

## Testing and observed behavior

The five saved runs below are trace analysis, not reruns or an independent correctness benchmark. Their tasks differ. “Success” means the model returned `finish(success=true)`; the controller does not independently validate the answer. The live Selenium run used the existing model IDs and a temporary read-only question in `main.py`; the original question was restored immediately afterward. A first sandboxed attempt could not launch Chromium, so the live result below is from the permitted browser run.

| Test / trace | Duration | Model calls | Input / output tokens | Result and relevant observation |
|---|---:|---:|---:|---|
| GIFT Nifty, `f379375a` | 48.9 s | 3 | 23,510 / 3,519 | Failed when the worker could not attach a CDP session to the current page. The preceding page outline alone was 67,966 characters. |
| GIFT Nifty, `9d561842` | 77.9 s | 4 | 35,337 / 2,712 | Failed on multiple distinct `act` calls in one model response; a later request contained a 40,024-character page outline. |
| GIFT Nifty, `67860660` | 115.8 s | 7 | 19,198 / 5,241 | Model reported success after switching among blocked or unavailable sources. Accuracy of the quoted live price was not independently checked. |
| Croma iPhone under ₹20,000, `a02284d7` | 192.1 s | 8 | 10,428 / 12,308 | Manually cancelled. Revisited Croma after access-denied pages, then tried search/proxy routes. No product answer was delivered. |
| MODX laptop under ₹2 lakh, `f4254c66` | 494.9 s | 14 | 41,184 / 41,381 | Manually cancelled. Repeated category, shop, and sitemap exploration without a product answer; 414.8 s was spent in model calls. |
| Live read-only Selenium form question, `49c95098` | 11.7 s | 1 | 371 / 749 | Failed before a browser action: the configured starter model `openai/gpt-oss-20b` returned malformed JSON tool arguments (`ModelActionError`). |

Across the five saved runs: **36 model calls, 929.7 s, 129,657 input tokens, 65,161 output tokens, and one model-reported success**. Model calls accounted for 717.8 s (about 77% of wall time); browser execution and observation accounted for 207.2 s. These are descriptive totals across different tasks, not a before/after comparison. Trace files are in `output/metrics/<run-id>.json`.

## Three highest-priority improvements

| Rank | Current problem and evidence | Recommended change | Main benefit / how to check it |
|---|---|---|---|
| **1. Bound and detect stalled work** | `Controller._run_steps()` loops until `finish`; `AgentState.consecutive_failures` is counted but never used. There is no application-level model deadline, worker-code deadline, maximum step count, or repeated-page/progress check. JavaScript execution can await indefinitely, and `WorkerClient._request()` waits indefinitely for a response. Croma and MODX ran 8 and 14 steps and were stopped manually; successful JavaScript often only confirmed another blocked or empty page. | Give each run a step and wall-time budget, each model call and worker request a deadline, and a small retry budget for repeated failures or unchanged task evidence. Track the last URL/observation and newly verified facts, so a no-progress sequence asks for a different strategy or ends with an explicit blocked result. Make shutdown able to terminate a stuck worker. | **Speed and token efficiency:** prevents long paid loops. Check that the Croma/MODX replay ends with a reason before the external cutoff, and record steps, elapsed time, and tokens to that decision. A timeout must not be treated as task success. |
| **2. Make progress and completion evidence-based** | `runner.py` applies model-written memory **before** executing its browser code. A failed action can therefore leave facts or an emptied checklist that were never observed. `Finish.success` is accepted as the run result without checking requested fields or source evidence. A syntactically valid JavaScript action counts as successful even if it reaches an access-denied page. The live starter response also failed JSON parsing, and the adapter aborts rather than offering a bounded repair. | Commit memory about an action only after execution and observation support it; preserve earlier verified facts on failure. Represent required outputs and their source URLs/values explicitly for comparison tasks. Before accepting `finish(success=true)`, check that each requested item has evidence and the page is not a block/error page. Allow one bounded retry for malformed tool arguments using the parse error. | **Accuracy:** reduces false progress and false success; a malformed tool call need not lose the whole task. Check against known answers on a stable form or scrape site and measure verified completion, not just the model's `success` flag. |
| **3. Send focused observations and cap returned data** | Every mid/big call receives the full simplified page outline plus the complete last execution result. `worker.cjs` collects the full AX tree after every action; `context.py` includes its rendered outline even when the action already returned the needed data. Saved requests contained outlines of 40,024 and 67,966 characters; one GIFT Nifty call used 21,581 input tokens. `stdout` and `result` have no content budget, and the worker response has a 1 MiB stream limit rather than a task-aware cap. | Keep URL/title and a compact page summary by default. Let generated code return a short, structured extraction for the current question; include a bounded accessibility subtree when interaction is needed. Truncate or summarize oversized stdout/results with an explicit “truncated” marker and a way to request a narrower follow-up view. Preserve source links needed for verification. | **Token efficiency and speed:** cuts repeated page text and should reduce model latency. Compare input tokens and answer correctness on the same tasks; do not discard evidence required to select the right control or cite a source. |

### Priority and measurement notes

The first change should come before tuning prompts or model choice because the loop currently has no reliable stopping rule. The second addresses answer correctness and the malformed-tool failure observed live. The third addresses the large contexts visible in traces. Keep the model IDs in `main.py` fixed while measuring these changes. Use a small repeatable set of tasks with expected outputs, a blocked-site case, and a deliberately ambiguous comparison task; report verified success rate, steps, wall time, model time, and input/output tokens for each run. The current saved data cannot establish a percentage speedup or accuracy gain.
