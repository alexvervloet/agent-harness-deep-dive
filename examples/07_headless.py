"""
Example 07 — headless automation: one-shot, scriptable, structured output.
==========================================================================

Interactive chat is one way to run an agent. The other — the one that shows up in
job descriptions as "agentic automation" — is **headless**: no human in the loop,
kicked off by a cron job or a CI step, emitting structured output another program
consumes. A harness is built for this: `run_to_completion` drives it to the final
answer, and because everything is events, you can fold the run into a machine-
readable record as it goes.

Here we run a task with no interaction and print a JSON summary — the shape you'd
write to a log, post to a webhook, or assert on in CI.

Run it:

    python examples/07_headless.py
    python examples/07_headless.py "What is 19 * 21?"
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from harness import (
    Harness,
    RunFinished,
    Sandbox,
    ToolBlocked,
    ToolFinished,
    default_tools,
    describe,
    ensure_ready,
    run_to_completion,
)

load_dotenv()
ensure_ready()

task = sys.argv[1] if len(sys.argv) > 1 else "What is (23 * 47) + 100?"

agent = Harness(
    "You are a batch worker. Use tools; be terse.",
    default_tools(),
    sandbox=Sandbox("workspace"),
)

# Fold the event stream into a structured record — no printing mid-run.
record = {
    "provider": describe(),
    "task": task,
    "tools_run": [],
    "blocked": [],
    "answer": "",
    "steps": 0,
}


def collect(event):
    if isinstance(event, ToolFinished):
        record["tools_run"].append(event.call.name)
    elif isinstance(event, ToolBlocked):
        record["blocked"].append(event.call.name)
    elif isinstance(event, RunFinished) and event.depth == 0:
        record["answer"] = event.answer
        record["steps"] = event.steps


record["answer"] = run_to_completion(agent, task, on_event=collect) or record["answer"]

# The only thing a headless run emits: a machine-readable result.
print(json.dumps(record, indent=2))

print(
    "\nNo prompts, no chat — just JSON another program can act on. This is the harness\n"
    "as a building block in a pipeline: a scheduled report generator, a CI check that\n"
    "fails the build on a `blocked` tool, a webhook worker. Same harness as the\n"
    "interactive examples; you just consume the result instead of narrating it.",
    file=sys.stderr,
)
