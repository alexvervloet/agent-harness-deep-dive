"""
harness/checkpoint.py — durable run state: survive a crash, resume where you left off.
======================================================================================

A long-horizon agent can run for minutes or hours. If the process dies — a deploy,
an out-of-memory kill, a timeout, a machine reboot — an in-memory loop loses
*everything* and has to start over, re-paying for every tool call and model turn it
already completed. Production agents don't accept that. They **checkpoint**: after
each step they persist enough state to resume exactly where they stopped, in a
fresh process, having redone nothing.

The elegant part is that the harness already carries the resumable state — the
**transcript** (every user turn, tool call, and tool result so far). Because the
loop feeds each tool result back into the transcript, persisting the transcript IS
the checkpoint: reload it into a new harness and keep looping, and the model, seeing
the results already there, moves on instead of re-running the completed tools. This
is exactly how real durable-execution systems work (LangGraph checkpointers,
Temporal-style durable workflows, Managed Agents' server-side session state).

This file is a tiny, teachable version: one JSON file per run under a directory.
`save` after each step, `load` to resume, `records` to list every run's task state
(queued / running / done / failed) — the durable "run log" a queue or dashboard
would query.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from .providers import ToolCall

# Run-status values — the durable task-state lifecycle.
QUEUED = "queued"            # created, not started
RUNNING = "running"          # in progress (or crashed mid-run — a checkpoint to resume)
DONE = "done"                # finished with an answer
FAILED = "failed"            # gave up (e.g. hit the step limit) without completing
INTERRUPTED = "interrupted"  # stopped early by an operator (steering); resumable


@dataclass
class RunState:
    """Everything needed to resume a run — the checkpoint payload."""

    run_id: str
    task: str
    status: str = QUEUED
    steps: int = 0
    answer: str = ""
    transcript: list[dict] = field(default_factory=list)
    updated_at: float = 0.0


# The transcript holds ToolCall dataclasses inside assistant turns; JSON can't. We
# convert them to/from plain dicts on save/load.
def _encode_transcript(transcript: list[dict]) -> list[dict]:
    out = []
    for entry in transcript:
        entry = dict(entry)
        if entry.get("role") == "assistant" and entry.get("tool_calls"):
            entry["tool_calls"] = [
                {"id": c.id, "name": c.name, "arguments": c.arguments} for c in entry["tool_calls"]
            ]
        out.append(entry)
    return out


def _decode_transcript(raw: list[dict]) -> list[dict]:
    out = []
    for entry in raw:
        entry = dict(entry)
        if entry.get("role") == "assistant" and entry.get("tool_calls"):
            entry["tool_calls"] = [
                ToolCall(c["id"], c["name"], c["arguments"]) for c in entry["tool_calls"]
            ]
        out.append(entry)
    return out


class Checkpointer:
    """Persists run state to one JSON file per run under `root`.

    This toy uses the local filesystem so you can open the files and read them; a
    real system would use a database or a durable-workflow engine, but the contract
    is the same: save after each step, load to resume, list to see task state."""

    def __init__(self, root: str = "runs"):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _path(self, run_id: str) -> str:
        return os.path.join(self.root, f"{run_id}.json")

    def save(self, state: RunState) -> None:
        state.updated_at = time.time()
        data = {
            "run_id": state.run_id,
            "task": state.task,
            "status": state.status,
            "steps": state.steps,
            "answer": state.answer,
            "updated_at": state.updated_at,
            "transcript": _encode_transcript(state.transcript),
        }
        with open(self._path(state.run_id), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load(self, run_id: str) -> RunState | None:
        path = self._path(run_id)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data["transcript"] = _decode_transcript(data.get("transcript", []))
        return RunState(**data)

    def delete(self, run_id: str) -> None:
        try:
            os.remove(self._path(run_id))
        except FileNotFoundError:
            pass

    def records(self) -> list[RunState]:
        """Every persisted run, oldest first — the durable task-state log."""
        states = []
        for name in os.listdir(self.root):
            if name.endswith(".json"):
                state = self.load(name[:-5])
                if state:
                    states.append(state)
        return sorted(states, key=lambda s: s.updated_at)
