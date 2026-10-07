"""Mine every run in output/ for errors and failure patterns, grouped by component, with the
eval case that covers each. Run: uv run python -m eval.error_catalog [--examples]"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[1] / "output"

# (category, component, pattern on the error text, covering eval case)
ERRORS = [
    ("model connection dropped", "controller", r"APIConnectionError",
     "controller_eval: retry_network_blip"),
    ("model output cut off / malformed", "provider+parsing",
     r"invalid JSON arguments|requires exactly these fields|exactly one distinct tool action|finish requires success|ordinary text",
     "component_eval: provider_truncated_call_names_budget, parse_rejects_bad_shapes"),
    ("model call too slow", "controller", r"model call exceeded",
     "controller_eval: time_limit"),
    ("run deadline crashed the run", "controller", r"^RUN:TimeoutError \| $",
     "controller_eval: time_limit; harness_eval: deadline_mid_browser_call"),
    ("browser call hung", "controller+worker", r"worker call exceeded",
     "harness_eval: worker_timeout_cleans_up"),
    ("worker output too large", "worker client", r"Separator is not found|chunk exceed the limit",
     "observation_eval: huge_output"),
    ("Chrome unreachable", "worker", r"ECONNREFUSED|Browser context management",
     "observation_eval: chrome_unreachable"),
    ("page or context closed", "worker", r"Target page, context or browser has been closed",
     "observation_eval: isolated_tasks, no_orphan_tabs"),
    ("ask_user with no terminal", "controller+CLI", r"EOFError",
     "controller_eval: ask_user_unavailable; agent_eval: ends cleanly when it needs input"),
    ("site unreachable (DNS/TLS)", "website", r"net::ERR_", "- (site problem; agent should switch source)"),
    ("run cancelled", "harness", r"CancelledError", "- (benchmark harness, not the agent)"),
    ("browser globals used in Node", "model code + worker",
     r"(document|window|DOMParser|Chart) is not defined", "observation_eval: node_vs_page_hint"),
    ("JS syntax error in generated code", "model code", r"SyntaxError",
     "observation_eval: failing_first_line"),
    ("locator timeout / strict mode", "model code",
     r"Timeout \d+ms exceeded|strict mode violation",
     "model_eval: continues from the failing line instead of redoing the batch"),
    ("navigation during evaluate", "model code + worker", r"Execution context was destroyed",
     "observation_eval: navigation_mid_evaluate"),
    ("other runtime error in generated code", "model code", r"TypeError|ReferenceError|Error:",
     "- (model code bugs; shown to the model as a traceback)"),
]
NEGATIVE = re.compile(r"not (found|available|listed|present)|could not|couldn't|unable|rejected|"
                      r"invalid|locked out|does not exist|无法", re.I)
BEHAVIOUR_CASES = {
    "hit the step limit": "controller_eval: step_limit; agent_eval: gives up on an item; agent_eval --live (goblet)",
    "3+ failed browser steps in one run": "agent_eval: stops retrying a login that keeps failing",
    "success=true on a negative answer": "model_eval: flags a rejected login...; agent_eval: does not swap in credentials",
    "kept working after the answer was returned": "model_eval: finishes once a full scan...; "
                                                  "agent_eval: stops once the answer is in hand; --live after-answer column",
    "model output hit 4k+ tokens in one step": "model_eval (max_tokens check on every case)",
}


def load_runs():
    """Normalise both metrics formats into {file, success, answer, error, steps:[...]}."""
    for path in sorted(OUTPUT.rglob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or "task" not in data:
            continue
        if "traces" in data:  # older format
            steps = [{"action": t.get("action"), "ok": t.get("success"),
                      "error": f"{t['error_type']}: {t.get('error_message')}" if t.get("error_type") else None,
                      "result": (t.get("execution_result") or {}).get("result"),
                      "out": t.get("output_tokens", 0)} for t in data["traces"]]
        else:
            per_step = {p["step"]: p for p in data.get("performance", {}).get("per_step", [])}
            steps = [{"action": s.get("action"), "ok": s.get("ok"), "error": s.get("error"),
                      "result": s.get("returned"), "out": per_step.get(s.get("step"), {}).get("output_tokens", 0)}
                     for s in data["steps"]]
        error = f"{data['error_type']} | {data.get('error_message') or ''}" if data.get("error_type") else None
        yield {"file": str(path.relative_to(OUTPUT.parent)), "task": data["task"],
               "success": data.get("success"), "answer": data.get("final_answer") or "",
               "error": error, "steps": steps}


def behaviour(run):
    steps, answer = run["steps"], run["answer"]
    found = []
    if answer.startswith("Stopped after"):
        found.append("hit the step limit")
    if sum(s["ok"] is False for s in steps) >= 3:
        found.append("3+ failed browser steps in one run")
    if run["success"] and NEGATIVE.search(answer):
        found.append("success=true on a negative answer")
    if any((s["out"] or 0) >= 4_000 for s in steps):
        found.append("model output hit 4k+ tokens in one step")
    # ponytail: answer-in-result heuristic (all numbers in the answer appear in one earlier
    # result); misses text answers, use agent_eval --live for ground truth.
    numbers = re.findall(r"\d[\d,.]*\d|\d", answer)
    if run["success"] and numbers:
        for index, step in enumerate(steps):
            if all(n in str(step["result"] or "") for n in numbers[:3]):
                if sum(s["action"] == "execute_browser_code" for s in steps[index + 1:]):
                    found.append("kept working after the answer was returned")
                break
    return found


def main(show_examples):
    runs = list(load_runs())
    errors, behaviours = defaultdict(list), defaultdict(list)
    for run in runs:
        texts = ([f"RUN:{run['error']}"] if run["error"] else []) + \
                [f"STEP:{s['error']}" for s in run["steps"] if s["error"]]
        for text in texts:
            category = next((c for c in ERRORS if re.search(c[2], text, re.M)), None)
            errors[category[0] if category else "uncategorised"].append((run, text))
        for name in behaviour(run):
            behaviours[name].append((run, name))

    print(f"{len(runs)} runs in output/, {sum(bool(r['success']) for r in runs)} reported success\n")
    print(f"{'count':>5}  {'error category':38} {'component':20} covered by")
    for name, component, _, case in ERRORS:
        if errors.get(name):
            print(f"{len(errors[name]):>5}  {name:38} {component:20} {case}")
    if errors.get("uncategorised"):
        print(f"{len(errors['uncategorised']):>5}  {'uncategorised':38}")
    print(f"\n{'runs':>5}  {'failure pattern':44} covered by")
    for name, case in BEHAVIOUR_CASES.items():
        print(f"{len(behaviours.get(name, [])):>5}  {name:44} {case}")

    if show_examples:
        for group in (errors, behaviours):
            for name, items in group.items():
                print(f"\n# {name}")
                for run, text in items[:3]:
                    print(f"  {run['file']}  {text.splitlines()[0][:110]}")


if __name__ == "__main__":
    main("--examples" in sys.argv)
