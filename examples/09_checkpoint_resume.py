"""
Example 09 — durable runs: checkpoint, crash, resume without redoing work.
==========================================================================

A long-horizon agent runs for minutes or hours. If the process dies mid-run — a
deploy, an OOM kill, a timeout, a reboot — an in-memory loop loses everything and
starts over, re-paying for every model turn and tool call it already finished. A
production harness won't accept that: it **checkpoints** after each step and can
**resume** in a fresh process, redoing nothing.

The trick is that the harness's own transcript IS the checkpoint — every tool
result is already fed back into it, so persisting the transcript is all it takes
(harness/checkpoint.py). Reload it into a new harness and keep looping; the model,
seeing the results already there, moves on to the next step.

We prove it with a two-step task (read a file, then do a calculation). We let
"process 1" crash right after the first tool finishes, then have a brand-new
"process 2" resume from the checkpoint. A counter shows each tool runs exactly
ONCE across both processes — the resumed run does not redo the completed read.

Offline and deterministic. Run:

    python examples/09_checkpoint_resume.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from harness import Checkpointer, Harness, Sandbox, Tool, ToolFinished, describe, ensure_ready
from harness.tools import CALCULATOR, READ_FILE

load_dotenv()
ensure_ready()
print(f"Provider: {describe()}\n")

sandbox = Sandbox("workspace")
sandbox.write("launch.txt", "Launch is on Friday.")
checkpointer = Checkpointer("runs")

# Count REAL tool executions so we can prove the resumed run redoes nothing.
executed: list[str] = []


def counting(tool: Tool) -> Tool:
    return Tool(
        name=tool.name, description=tool.description, parameters=tool.parameters,
        func=lambda args, sb: (executed.append(tool.name), tool.func(args, sb))[1],
        dangerous=tool.dangerous,
    )


tools = [counting(READ_FILE), counting(CALCULATOR)]
TASK = "read the file launch.txt and compute (23 * 47) + 100."
RUN_ID = "job-42"
checkpointer.delete(RUN_ID)  # start clean each run of this demo

print("=== Process 1 — runs, then 'crashes' after the first tool finishes ===")
proc1 = Harness("You are a careful assistant.", tools, sandbox=sandbox)
for event in proc1.run(TASK, run_id=RUN_ID, checkpointer=checkpointer):
    print("  " + event.line())
    if isinstance(event, ToolFinished):
        print("  ‼ CRASH — the process dies here. But the step was checkpointed to disk.")
        break

saved = checkpointer.load(RUN_ID)
print(f"\nOn disk: runs/{RUN_ID}.json — status={saved.status}, {saved.steps} step(s) done.\n")

print("=== Process 2 — a brand-new harness resumes from the checkpoint ===")
proc2 = Harness("You are a careful assistant.", tools, sandbox=sandbox)
for event in proc2.run(TASK, run_id=RUN_ID, checkpointer=checkpointer):
    print("  " + event.line())

print(f"\nTool executions across BOTH processes: {executed}")
print(f"  read_file ran {executed.count('read_file')}x, calculator ran {executed.count('calculator')}x "
      f"— each exactly once.")
print(
    "\nThat's durable execution: the crash cost nothing. Process 2 didn't re-read the\n"
    "file — it loaded the completed step from the checkpoint and continued at the\n"
    "calculation. Persisting the transcript after each step is the whole mechanism;\n"
    "real systems (LangGraph checkpointers, Temporal-style durable workflows, Managed\n"
    "Agents' server-side sessions) do the same thing with a database instead of a\n"
    "JSON file. The final run record is marked 'done' — which the next example turns\n"
    "into a queryable task-state log."
)
