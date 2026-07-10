"""
Example 10 — durable task state: a queryable log of every run.
==============================================================

Checkpointing (example 09) is about resuming ONE run. The same persisted state
gives you the other half of durable execution for free: a **task-state log** you
can query. Each run carries a status through its lifecycle —

    queued -> running -> done            (finished with an answer)
                      -> failed          (gave up — e.g. hit the step limit)
                      -> running (stuck) (the process crashed mid-run)

— and because every run is a file on disk, you can list them all: which finished,
which are still going, and which crashed and need resuming. That's exactly what a
job queue, a cron dashboard, or Managed Agents' deployment-run records give you.

We run three jobs — one completes, one is capped so it fails, one 'crashes'
mid-run — then print the durable log, and resume the crashed one from that log.

Offline and deterministic. Run:

    python examples/10_run_records.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from harness import (
    Checkpointer,
    Harness,
    RUNNING,
    Sandbox,
    ToolFinished,
    describe,
    ensure_ready,
)
from harness.tools import CALCULATOR, READ_FILE

load_dotenv()
ensure_ready()
print(f"Provider: {describe()}\n")

sandbox = Sandbox("workspace")
sandbox.write("notes.txt", "Remember: the launch is Friday.")
cp = Checkpointer("runs")
for rid in ("done-1", "failed-1", "crashed-1"):
    cp.delete(rid)  # clean slate for the demo

tools = [READ_FILE, CALCULATOR]


def drain(harness, task, run_id, crash_after_tool=False):
    for event in harness.run(task, run_id=run_id, checkpointer=cp):
        if crash_after_tool and isinstance(event, ToolFinished):
            return  # simulate the process dying mid-run


# 1. A job that completes cleanly -> done.
drain(Harness("You are careful.", tools, sandbox=sandbox), "compute (2 + 2).", "done-1")

# 2. A job capped at one step but given a two-step task -> gives up -> failed.
drain(
    Harness("You are careful.", tools, sandbox=sandbox, max_steps=1),
    "read the file notes.txt and compute (5 * 5).",
    "failed-1",
)

# 3. A job whose process 'crashes' after the first tool -> left running.
drain(
    Harness("You are careful.", tools, sandbox=sandbox),
    "read the file notes.txt and compute (9 * 9).",
    "crashed-1",
    crash_after_tool=True,
)

print("The durable run-state log (what a queue or dashboard would show):\n")
print(f"  {'run_id':<12} {'status':<9} {'steps':>5}  answer")
print(f"  {'-' * 12} {'-' * 9} {'-' * 5}  {'-' * 30}")
for r in cp.records():
    print(f"  {r.run_id:<12} {r.status:<9} {r.steps:>5}  {r.answer[:40]}")

# Find the crashed run and resume it — no need to know anything but its id.
stuck = [r for r in cp.records() if r.status == RUNNING]
print(
    f"\n{len(stuck)} run(s) are stuck in 'running' (a crashed process). Resuming them:\n"
)
for r in stuck:
    resumed = Harness("You are careful.", tools, sandbox=sandbox)
    for event in resumed.run(r.task, run_id=r.run_id, checkpointer=cp):
        print(f"  [{r.run_id}] {event.line()}")

print("\nThe log after resuming:\n")
print(f"  {'run_id':<12} {'status':<9} {'steps':>5}")
print(f"  {'-' * 12} {'-' * 9} {'-' * 5}")
for r in cp.records():
    print(f"  {r.run_id:<12} {r.status:<9} {r.steps:>5}")

print(
    "\nSame persisted state, two uses: resume one run (example 09) and monitor ALL of\n"
    "them here. 'done' is finished, 'failed' gave up and needs a fix or a bigger step\n"
    "budget, and a run stuck in 'running' is a crashed process to resume. That status\n"
    "column is the difference between an agent you hope finished and one you can prove\n"
    "did — the durable task state production agent systems are built on."
)
