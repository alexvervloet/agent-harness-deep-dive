"""
Capstone: a configured harness you can actually drive.

Everything assembled: a harness with a real permission policy, a sandboxed
workspace, a redaction hook, a research subagent, and a choice of live event trace
or headless JSON. It's the library from this dive wired to a CLI; read it to see
how the pieces compose.

    # One-off task with a live event trace (offline on the mock): the agent
    # delegates the lookup to a subagent, then computes with the calculator.
    python hands_on/agent_harness.py "Look up the plans and prices, then compute a year of Pro (30 * 12)."

    # Auto-approve the `ask` tools (non-interactive):
    python hands_on/agent_harness.py "write file todo.txt containing: ship it" --yes

    # Headless: emit a JSON record instead of a trace (for CI / cron):
    python hands_on/agent_harness.py "What is (23 * 47) + 100?" --json

    # Durable run: checkpoint under an id. Re-run with the same id to RESUME (if the
    # first run was interrupted); completed steps are loaded from disk, not redone.
    python hands_on/agent_harness.py "read the file plan.txt and compute (2 + 2)." --run-id job1

    # Raise the step ceiling:
    python hands_on/agent_harness.py "..." --max-steps 12

By default `write_file` is gated (ask) and `run_command` is denied; deny wins even
with --yes, because --yes only auto-answers `ask`, it doesn't override `deny`.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from harness import (
    ALLOW,
    Checkpointer,
    Harness,
    PermissionPolicy,
    RunFinished,
    Sandbox,
    Subagent,
    ToolBlocked,
    ToolFinished,
    default_tools,
    describe,
    ensure_ready,
)
from harness.tools import SEARCH_NOTES


def build_agent(*, auto_approve: bool, max_steps: int) -> Harness:
    policy = PermissionPolicy(default=ALLOW).ask("write_file").deny("run_command")
    sandbox = Sandbox("workspace", allowed_commands={"echo"})

    def approve(call) -> bool:
        if auto_approve:
            print(f"  [auto-approved] {call.name}({call.arguments})", file=sys.stderr)
            return True
        answer = (
            input(f"  Approve {call.name}({call.arguments})? [y/N] ").strip().lower()
        )
        return answer in ("y", "yes")

    def redact(_call, result):  # post-tool hook: never surface secrets
        return re.sub(
            r"(sk-[A-Za-z0-9\-]+|api_token=\S+|password=\S+)", "[REDACTED]", result
        )

    agent = Harness(
        "You are a capable assistant. Do arithmetic yourself; delegate lookups to research.",
        default_tools(),
        policy=policy,
        sandbox=sandbox,
        approve=approve,
        max_steps=max_steps,
    )
    agent.on_post_tool(redact)
    agent.add_subagent(
        Subagent(
            name="research",
            description="Delegate a factual lookup. Input: a `task` string.",
            system="You answer factual questions using search_notes, then report back.",
            tools=[SEARCH_NOTES],
        )
    )
    return agent


def main() -> int:
    parser = argparse.ArgumentParser(
        description="A configured agent harness (offline on the mock by default)."
    )
    parser.add_argument(
        "task",
        nargs="?",
        default="Look up the plans and prices, then compute a year of Pro (30 * 12).",
    )
    parser.add_argument(
        "--yes", action="store_true", help="auto-approve tools with an `ask` policy"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a headless JSON record instead of a live trace",
    )
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument(
        "--run-id",
        help="checkpoint under this id; re-run with the same id to RESUME a crashed run",
    )
    args = parser.parse_args()

    load_dotenv()
    ensure_ready()

    agent = build_agent(auto_approve=args.yes, max_steps=args.max_steps)

    # A --run-id turns on durable checkpointing: the run is persisted after each
    # step, and re-invoking with the same id resumes it instead of starting over.
    checkpointer = Checkpointer("runs") if args.run_id else None

    if not args.json:
        print(f"Provider: {describe()}\nTask: {args.task}\n\nEvent stream:")

    record = {
        "provider": describe(),
        "task": args.task,
        "tools_run": [],
        "blocked": [],
        "answer": "",
        "steps": 0,
    }
    for event in agent.run(args.task, run_id=args.run_id, checkpointer=checkpointer):
        if not args.json:
            print("  " + event.line())
        if isinstance(event, ToolFinished):
            record["tools_run"].append(event.call.name)
        elif isinstance(event, ToolBlocked):
            record["blocked"].append(event.call.name)
        elif isinstance(event, RunFinished) and event.depth == 0:
            record["answer"], record["steps"] = event.answer, event.steps

    if args.json:
        print(json.dumps(record, indent=2))
    else:
        print(f"\nFinal answer: {record['answer']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
