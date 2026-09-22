| Agent | What can it do? | What context does it receive? | Available tools |
|---|---|---|---|
| Starter | It will be a low level smaller and faster LLM(less context window) | Only the minimised system prompt and original task so that it can generate small async js code and the user question so it can generate the easy first request efficiently | Just exec code so it calls exec code with its written smaller faster code code |
| Mid | Fast main browser agent for routine navigation, extraction, forms, and multi-step tasks. Batches actions grounded in observed controls, repairs ordinary locator/validation errors, resumes unfinished work after partial execution, and finishes directly when evidence supports completion. Requests Strong for unresolved reasoning or planning difficulty. | Short operational instructions; original task; all user clarifications; complete remaining checklist; all saved facts initially (small in the measured runs); current URL/title and page content relevant to the operation; latest execution status and useful output/error. On recovery, also include the failed action/code so it can correct rather than repeat it. Focused page views and failed-code context are proposed additions, not current behavior. | `execute_browser_code`, `ask_user`, `finish`; proposed `escalate` action to request Strong with a reason. |
| Strong | Takes over difficult reasoning, ambiguous page interactions, and recovery when Mid is stuck. Can continue browser work through completion, ask the user for information, or report an unsuccessful result when blocked. | Everything Mid receives, plus all saved facts and the escalation reason. Proposed additional context: a short record of recent attempted actions and outcomes so it can avoid repeating failed approaches. This attempt history is not currently included in model context. | `execute_browser_code`, `ask_user`, `finish`. No further agent tier to escalate to. |

## Suggested behavior and decisions still open

The Mid and Strong rows are proposals for discussion; they are not implemented yet.

- **Starter runs once:** use it for a small first action that can be determined from the task alone, such as navigating to an explicitly supplied URL. Then give Mid the resulting page observation and execution result. Starter should not guess page-specific selectors or interactions before seeing the page.
- **Starter needs a skip path:** some tasks have no clear first browser action. Decide how Starter can decline execution and hand control to Mid without generating dummy code. Its proposed execute-only interface does not currently express this. - Lets skip this for now as there are going to be mostly some tasks for implemmentation 

- **Keep Starter's instructions short but sufficient:** include the available JavaScript runtime, async execution rules, and the existing rules for untrusted page content and consequential actions. The original task already contains the user's initial question; it does not need to be duplicated. - I do not think that it will just generate a quey for empty chrome tab with a search engine query or directly query a web page when told to so 
- **Share one task memory and browser session:** context subsets are views of shared state. Give Mid and Strong the complete remaining-requirements checklist because the current memory contract replaces that list on each action. Starter should leave the initial task checklist intact. Facts omitted from a model request must remain in shared memory.
- **Proposed handoff:** Starter → Mid, then Mid → Strong when needed. Strong stays active through completion for the first version. The choice of explicit escalation, automatic failure thresholds, or both remains open.
- **Tools versus actions:** the current implementation exposes one tool, `act`, with three action choices. The table names those choices. `escalate` would be a new action; there is no need to create separate tools just to represent the tiers.

## Metrics findings for designing Mid

Analysis of the four saved runs (11 model calls) in `output/metrics`, recorded on September 21, 2026. These are individual samples, not a benchmark establishing ideal completion times. Two runs report success; two terminate with worker-response errors. Reported success is not an independent correctness evaluation.

| Task / run ID prefix | Total time | Model-call time | Execution time | Calls / largest input | Main finding |
|---|---:|---:|---:|---|---|
| Fill practice forms — `b6b00170` | 181.0 s | 109.2 s | 70.4 s | 5 / 2,699 tokens | Modest context, but three execution errors and repeated work. Best example for improving Mid's execution reliability. |
| Find iPhones under ₹1,50,000 — `10deb2cc` | 128.5 s | 33.4 s | 94.2 s | 2 / 6,196 tokens | Four-page extraction took 88.1 s before a worker-response failure. Broad extraction and swallowed waits are candidates for improvement. |
| Most important person — `7d9491b5` | 50.4 s | 38.4 s | 10.6 s | 3 / 22,703 tokens | Largest context excess: full search-page outline alongside extracted search results. |
| Grace Hopper → university founding year — `ec41f934` | 19.6 s, failed | 15.8 s | 2.4 s | 1 / 1,008 tokens | Failed before receiving the article observation. Does not measure Mid's ability to do the lookup. |

Execution time includes the worker request, JavaScript, observation collection, and response handling. Model-call time includes context construction and the API request; there is no time-to-first-token or per-browser-command breakdown. Startup/cleanup account for the remaining wall time.

The first three runs by timestamp (search, iPhones, Wikipedia) precede commit `d299d09`, which moved accessibility-tree pruning into Node before transmission. The form run is later. The logs do not record a code revision, so the old oversized-response errors need reproduction on current code before treating them as current defects.

### Where time and context can be reduced

1. **Forms: prioritize reliable actions over cutting facts.** The first filling call took 54.45 s with only 2,344 input tokens and 607 output tokens. Its code then spent a recorded 30 s waiting for `getByLabel('Day')`, although the observation showed a date control with spinbuttons. The next attempt took 34.42 s to execute: it re-clicked a successful Login and queried the HTML tag `alert` instead of the alert role, swallowing the resulting error. A hidden wait there is plausible, but not separately timed. It later failed because `getByLabel('Password *')` matched both password fields. A third attempt completed the remaining forms but its final `locator('main').innerText()` matched two elements. Mid should use observed, scoped, exact locators where appropriate; inspect native input types/constraints when needed; preserve partial progress; and verify through specific status elements. [Playwright locator guidance](https://playwright.dev/docs/locators)
2. **Search: focus the observation before considering a smaller memory.** The second call received 22,703 input tokens. Its page outline was 37,121 characters, including 23,553 characters of URLs; Bing redirect URLs alone occupied 19,833 characters. It also received eight extracted results with titles, URLs, and snippets. For choosing a source, a focused result list is a better candidate than the full page with navigation and video cards. Removing only the outline from the saved user JSON reduces its serialized length from 43,708 to 5,170 characters (88.2%). This is an illustrative character reduction, not a measured token/latency improvement or proof that every removed fact is unnecessary. Preserve source identity and usable links; request more page content if the extracted results are insufficient.
3. **Forms need a focused but sufficiently detailed page view.** Keeping the existing form-scenarios region reduces the initial outline from 5,023 to 3,184 characters (36.6%), before restoring a small URL/title wrapper and any relevant global alerts. Preserve control names, roles, values, options, validation messages, and nearby success text. A generic first-N-characters cutoff could remove exactly the evidence needed to recover or finish. Current accessibility output does not expose every native input constraint; a targeted DOM inspection can supply missing details.
4. **iPhones: reduce unrelated extraction and avoid silent waiting.** The first result contained the first 60 page links, mostly global navigation, in addition to a 12,151-character page outline. The next code visited four product pages and allowed a 20 s price-locator wait on each, swallowing failures. The log does not reveal which waits expired. Mid should extract task-specific model/variant/price/availability evidence and record missing results explicitly. This multi-page task is not a clean easy-task baseline. The search run also explicitly slept for 5 s across two pages. Prefer readiness conditions over fixed sleeps. [Playwright wait guidance](https://playwright.dev/docs/api/class-page#page-wait-for-timeout)
5. **Small prompts alone do not guarantee fast calls.** Initial requests had only 961–1,008 input tokens but took 5.55–15.78 s. All requests named the same model, but responses came from CoreWeave, Together, and Wafer. The slow 54.45 s form call was served by Wafer and reported only one reasoning token. A later CoreWeave call produced 3,225 output tokens in 14.84 s. These unequal calls cannot establish a provider ranking, but they show why latency should not be attributed to context size or reasoning alone. Compare repeated equivalent tasks before choosing Mid's model/provider.

### Mid design recommendations from these samples

- **Keep small task memory intact initially.** Across post-navigation calls, serialized `memory` was only 59–712 characters. Across all calls, page observations account for about 82% of serialized context-field characters, while memory accounts for about 2.3% (excluding system instructions and tool definitions). A fact-selection model would add another call to optimize a small part of these requests.
- **Select page context by the operation.** For search/source selection, provide focused result records. For interactions, provide the relevant controls and surrounding labels/constraints. For completion, provide evidence covering every remaining requirement. Keep a way to obtain broader page content when needed. Start with deterministic extraction rather than an extra LLM summarizer/router on every step.
- **Let Mid finish easy tasks itself.** Do not require Strong to approve every successful result. Keep batching predictable actions, but stop before a step that depends on unseen content. A stronger model should receive genuinely unresolved reasoning work; a missing locator, a page timeout, or an oversized worker response is not by itself evidence that Strong is needed.
- **Give recovery the right evidence.** Add the failed code/action to recovery context; the current builder supplies only the result/error and page. Preserve useful selector-match details from errors. Avoid replaying completed submissions merely because a later read failed.
- **Distinguish plans from observed progress.** In the form run, the model wrote that F02–F05 were completed before executing the code that would attempt them. The controller applies memory before execution, so that claim survived a failure. Mid's facts and checklist updates must describe observed outcomes, not assumed success of the action it is about to execute.
- **Validate the design on equivalent reruns.** Compare end-to-end time, model time, input tokens, retries, and evidence-backed completion on the same tasks. The form run is the strongest current sample; repeat the older tasks against today's observation pipeline. Do not choose hard context caps or promise a speedup from these four runs alone.

These findings refine the proposed Mid row only. No runtime changes or new benchmarks were performed for this analysis.

## What the current agent receives

Every model call receives the same system instructions, the `act` tool definition, and a freshly built JSON context as a user message.

| Context | What the agent sees |
|---|---|
| System instructions | Browser-agent role, how to use Playwright and persistent JavaScript `state`, memory-writing rules, instructions to treat webpage content as untrusted, and when to ask for confirmation. |
| Available actions | The `act` tool schema: execute browser code, ask the user a question, or finish with an answer and success status. Every action includes a memory update. |
| `original_task` | The complete original task text. |
| `user_clarifications` | All questions asked and answers received during this task. |
| `memory.facts` | All accumulated facts saved by the agent. New facts are merged and exact duplicates removed. |
| `memory.remaining` | The complete current unresolved-task checklist. Each action replaces this checklist with the model's updated list. |
| `last_execution_result` | Only the latest browser-code execution: `success`, captured console output (`stdout`), returned value (`result`), error traceback, and `timed_out`. Null before any execution. |
| `current_browser_observation` | Current page URL, title, and a text outline of the pruned accessibility tree, including retained element roles, names, states, and hierarchy. Includes an explicit untrusted-webpage-content warning. |

The request does not include the full conversation or action history, previous code snippets, earlier execution results, screenshots, raw HTML, metrics, step count, or consecutive-failure count. Older information reaches the model through saved facts and user clarifications.

The browser worker also keeps a separate JavaScript `state` object across executions. Its contents are not automatically included in model context; generated code can read them and expose them through a return value or console output.
