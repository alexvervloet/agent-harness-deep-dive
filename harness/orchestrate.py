"""
harness/orchestrate.py — fan out to many subagents at once, then join.
======================================================================

Example 06's subagents run one at a time, one level deep — the coordinator waits
for each before starting the next. That's fine when steps depend on each other, but
a lot of agent work is *independent*: research five topics, review ten files, check
three candidates. Running those serially wastes wall-clock — the batch should cost
the SLOWEST worker, not the SUM.

`fan_out` is the coordinator's map step: hand it a list of (subagent, task) workers
and it runs them **concurrently**, each in its own harness with its own context
window (isolation), returning every result plus its timing. The caller does the
reduce — aggregate the answers however the task needs. This is the from-scratch
shape of a coordinator/worker (map-reduce) orchestration: LangGraph's parallel
branches, Managed Agents' multiagent coordinator, or a plain thread pool over agent
runs.

Workers share the sandbox (subagents share the filesystem, not the conversation),
so keep parallel workers to independent, read-mostly tasks — the same rule as
parallel tool calls in the Agents dive.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .core import Harness, Subagent, run_to_completion
from .sandbox import Sandbox


@dataclass
class WorkerResult:
    """One worker's outcome: which subagent, its task, its answer, and how long it
    took (so you can see the concurrency win)."""

    name: str
    task: str
    answer: str
    elapsed_ms: float


def _run_worker(sub: Subagent, task: str, sandbox: Sandbox) -> WorkerResult:
    start = time.perf_counter()
    worker = Harness(sub.system, sub.tools, policy=sub.policy, sandbox=sandbox, max_steps=sub.max_steps)
    answer = run_to_completion(worker, task)
    return WorkerResult(sub.name, task, answer, (time.perf_counter() - start) * 1000)


def fan_out(
    workers: list[tuple[Subagent, str]],
    *,
    sandbox: Sandbox,
    concurrent: bool = True,
    max_workers: int = 8,
) -> list[WorkerResult]:
    """Run each (subagent, task) worker to completion, returning all results in
    order. Concurrent by default — the batch takes about as long as the slowest
    worker. Set `concurrent=False` to run them serially (to compare, or when a
    downstream limit forbids parallelism)."""
    if not concurrent:
        return [_run_worker(sub, task, sandbox) for sub, task in workers]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_run_worker, sub, task, sandbox) for sub, task in workers]
        return [f.result() for f in futures]
