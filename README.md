# Web Agent

A CodeAct-style browser agent with a persistent Playwright worker. The parent
controller sends one model-selected action at a time while the child process keeps
the same browser page and Python namespace alive.

Run it with:

```bash
uv run python main.py \
  "Find information on the web" \
  --model provider/model-name \
  --allow-unsafe-exec
```

Set `OPENROUTER_API_KEY` in the environment or `.env`. You can set
`OPENROUTER_MODEL` instead of passing `--model`.

`--allow-unsafe-exec` is required because model-generated Python runs as your OS
user. The worker has a temporary working directory and sanitized environment, but it
is not a security sandbox and can still access files your user can access.

The controller and adapter can be checked without using OpenRouter:

```bash
uv run python -m src.controller
uv run python -m src.openrouter_adapter
```
