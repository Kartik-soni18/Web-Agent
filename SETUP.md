# Setup and run

Install Node.js 24 or newer, and create a `.env` file containing:

```env
OPENROUTER_API_KEY=your_key_here
```

Install the project, start Chrome with a dedicated agent profile, then run the agent:

```bash
uv sync
npm ci
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.chrome-agent"
uv run python main.py --allow-unsafe-exec "your task"
```

Use `--cdp URL` to attach to a different browser.
