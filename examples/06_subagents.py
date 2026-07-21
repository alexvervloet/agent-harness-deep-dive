"""
Example 06: subagents: delegate to a nested harness with its own context.

The Agents dive showed a subagent as "a tool whose function runs its own loop."
A harness makes that first-class: you register a `Subagent` (its own persona and
toolset), and to the model it appears as an ordinary tool taking a `task` string.
When the model calls it, the harness spawns a *nested harness*, a fresh context
window with only that subagent's tools, runs it, and hands the result back.

Why it matters: **context isolation**. The orchestrator's window doesn't fill up
with the subagent's tool calls and intermediate junk; it only sees the final
answer. Each agent stays focused. (They share the sandbox: subagents share the
filesystem, not the conversation, just like real multi-agent harnesses.)

Here an orchestrator that can only do arithmetic delegates a factual lookup to a
`research` subagent that owns the knowledge-base tool. Watch the nested run appear
indented in the stream.

Run it:

    python examples/06_subagents.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from harness import Harness, Subagent, describe, ensure_ready
from harness.tools import CALCULATOR, SEARCH_NOTES

load_dotenv()
ensure_ready()
print(f"Provider: {describe()}\n")

research = Subagent(
    name="research",
    description="Delegate a factual lookup. Input: a `task` describing what to find.",
    system="You answer factual questions using the search_notes tool, then report back.",
    tools=[SEARCH_NOTES],  # the orchestrator does NOT have this tool
)

orchestrator = Harness(
    "You coordinate. Do arithmetic yourself; delegate factual lookups to the research subagent.",
    [CALCULATOR],
)
orchestrator.add_subagent(research)

print("Event stream (subagent work is indented):")
for event in orchestrator.run("Look up the plans and prices."):
    print("  " + event.line())

print(
    "\nThe orchestrator never had the knowledge-base tool. It delegated, and only the\n"
    "subagent's final answer came back into its context, not the search step. That's\n"
    "context isolation: focused agents composing through the tool interface, each with\n"
    "its own window and toolset. Scale this up and it's how large agent systems are\n"
    "built (Claude Agent SDK subagents, Managed Agents' multiagent coordinator)."
)
