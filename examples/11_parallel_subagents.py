"""
Example 11: parallel subagents: fan out to many workers, then join.

Example 06 delegated to ONE subagent. But a coordinator often has *independent*
work to spread out: research several topics, review several files, check several
candidates. Running those serially wastes wall-clock: the batch should cost the
SLOWEST worker, not the SUM.

`fan_out` (harness/orchestrate.py) is the coordinator's map step: hand it a list of
(subagent, task) workers and it runs them concurrently, each in its own harness
with its own context window, returning every result. The reduce, aggregating the
answers, is up to you.

We give three research workers a slow lookup tool (a stand-in for real model/tool
latency) and run the same batch two ways, timed: serial vs concurrent. The
concurrent run finishes in about the time of one worker, not three.

Offline and deterministic (the timing gap is real wall-clock). Run:

    python examples/11_parallel_subagents.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from harness import Sandbox, Subagent, Tool, describe, ensure_ready, fan_out
from harness.tools import SEARCH_NOTES

load_dotenv()
ensure_ready()
print(f"Provider: {describe()}\n")

WORKER_LATENCY = 0.4  # seconds; a stand-in for a real worker's model + tool time


def slow_lookup(args: dict, sandbox) -> str:
    time.sleep(WORKER_LATENCY)  # simulate a worker that takes real time
    return SEARCH_NOTES.func(args, sandbox)


# One worker profile (its own persona + a single lookup tool), reused per topic.
def worker() -> Subagent:
    tool = Tool(
        name="search_notes",
        description=SEARCH_NOTES.description,
        parameters=SEARCH_NOTES.parameters,
        func=slow_lookup,
    )
    return Subagent(
        name="researcher",
        description="Look up one topic.",
        system="You answer one factual question using search_notes.",
        tools=[tool],
    )


sandbox = Sandbox("workspace")
topics = ["the plans and prices", "the refunds policy", "the support hours"]
workers = [(worker(), f"Look up {t}.") for t in topics]

print(f"Fanning out {len(workers)} research workers (each ~{WORKER_LATENCY:.1f}s):\n")

t0 = time.perf_counter()
serial = fan_out(workers, sandbox=sandbox, concurrent=False)
serial_s = time.perf_counter() - t0

t0 = time.perf_counter()
concurrent = fan_out(workers, sandbox=sandbox, concurrent=True)
conc_s = time.perf_counter() - t0

print("  Aggregated results (the coordinator's 'reduce'):")
for r in concurrent:
    print(f"    • {r.task}  ->  {r.answer}")

print(f"\n  serial:     {serial_s:.2f}s  (sum of all {len(workers)} workers)")
print(f"  concurrent: {conc_s:.2f}s  (about one worker, the slowest)")
print(f"  speedup:    {serial_s / conc_s:.1f}x")

print(
    "\nThat's fan-out/join orchestration: independent work spread across workers, each\n"
    "with its own isolated context, joined back by the coordinator. Concurrency turns\n"
    "the batch cost from the SUM into the MAX: the same win as parallel tool calls in\n"
    "the Agents dive, one level up at the agent. Keep parallel workers independent and\n"
    "read-mostly (they share the sandbox); for dependent steps, delegate serially\n"
    "(example 06). Real systems do this with LangGraph parallel branches or a Managed\n"
    "Agents multiagent coordinator."
)
