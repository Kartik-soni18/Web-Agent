# Web Agent

Web Agent is an experimental AI browser agent for automating everyday web-based
tasks. It asks a model to write async Playwright JavaScript and executes that
code in a Node.js child worker. The browser and a shared `state` object stay
alive across steps; local variables belong to each snippet. Python manages the
agent loop, model calls, memory, metrics, and model-context formatting. The same
Node worker collects, prunes, and simplifies accessibility trees before sending
observations to Python.

See [SETUP.md](SETUP.md) to install and run it.

> [!WARNING]
> The model generates and executes arbitrary JavaScript code. It may execute unwanted
> code, access or modify files available to your OS user, or perform unintended web
> actions. The child worker is not a security sandbox. Run this project only in an
> environment where that risk is acceptable.

## Challenges & Improvements

### 1. Browser-context extraction

- **Accessibility tree over DOM:** The AX tree gives roles, names and states (button, link, checked). The raw DOM is noisy markup. For example, Wikipedia's DOM is 510 KB of HTML.
- **Pruning was essential:** The raw CDP AX tree is larger than the DOM (1.9 MB JSON for Wikipedia). Pruning and simplifying cut it by about 95% (4.6 MB → 222 KB across 5 sites) and drop about 81% of nodes (12.4k → 2.3k).
- **Pruning in the JS worker, not Python:** The tree is pruned next to the browser, so only the small tree crosses the stdio pipe to Python. That is about 20x less data moved, and pruning takes at most 8 ms per page.
- **Pruning strategy:**
  - Drop ignored, presentational and empty generic nodes, and text that repeats its parent's name.
  - Collapse single-child wrappers, but keep dialog, alert, form, main and headings.
  - Reduce headers to their controls and footers to forms, alerts and dialogs. Skip navigation that hasn't changed since the last step.
  - Give actionable elements short IDs (`e1`, `e2`, …), cap each text node at 500 characters, and render the outline with dialog, alert and main first, capped at 10k characters (about 2.5k tokens).

_Measured headless on Wikipedia, Hacker News, GitHub, BBC News and the Python docs._

### 2. Model orchestration

Sending every step to one model wastes a large model on easy steps and leaves a small one stuck on hard ones. The plan is three tiered agents:

- **Starter:** a fast, cheap model for the opening moves (open the site, search, first navigation), since an empty page gives a large model nothing useful to reason over.
- **Mid:** the default worker for routine page steps (filling forms, clicking through lists, extracting data), so the large model's cost and latency are spent only where they matter.
- **Big:** called in only for planning, recovery after repeated failures, and the final check of the combined result, which is where a single small model tends to loop or stop early.
