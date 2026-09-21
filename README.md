# Web Agent

Web Agent is an experimental AI browser agent for automating everyday web-based
tasks. It asks an OpenRouter model to write async Playwright JavaScript and executes
that code in a Node.js child worker. The browser and a shared `state` object stay
alive across steps; local variables belong to each snippet. Python manages the
agent loop, model calls, memory, metrics, and accessibility-tree processing.

The project currently:

- launches a visible Chromium browser with a small delay between Playwright actions;
- observes the current URL, title, and a pruned accessibility tree;
- supports three model actions: execute browser code, ask the user, and finish;
- rebuilds a bounded context from the current task, memory, execution result, and page;
- keeps the OpenRouter API key out of the worker environment;
- uses the hardcoded model and example task configured in `main.py`.

## Improvements

- Run generated code inside a real OS or container sandbox.
- Add execution timeouts, step limits, failure limits, and output-size limits.
- Improve observations with screenshots, stronger DOM data, and multi-tab tracking.
- Make the task and model configurable from the command line again.
- Record token usage, cost, latency, steps, and validated task success.
- Add broader automated and browser integration tests.

## Setup and run

Install Node.js 24 or newer, and create a `.env` file containing:

```env
OPENROUTER_API_KEY=your_key_here
```

Install the project and Chromium, then run the agent:

```bash
uv sync
npm ci
npx playwright install chromium
uv run python main.py --allow-unsafe-exec
```

> [!WARNING]
> The model generates and executes arbitrary JavaScript code. It may execute unwanted
> code, access or modify files available to your OS user, or perform unintended web
> actions. The child worker is not a security sandbox. Run this project only in an
> environment where that risk is acceptable.
