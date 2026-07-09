"""
harness — a small, from-scratch agent *harness*, built to be read.

The Agents dive taught the loop. This teaches the layer that runs the loop for you
and adds the things production agent work is actually made of:

  providers.py — the ONLY provider file: a deterministic mock (default) + openai/claude
  tools.py     — what a tool is + a sandboxed toolbox
  sandbox.py   — the boundary tools execute inside (path jail + command allowlist)
  policy.py    — a declarative allow/ask/deny permission policy
  events.py    — the typed event stream the harness emits
  checkpoint.py— durable run state: persist the transcript, resume after a crash
  steer.py     — steering controllers: inject / queue / interrupt a running run
  orchestrate.py— fan out to many subagents concurrently, then join (map-reduce)
  graph.py     — orchestration as a graph: nodes, conditional routing, cycles
  core.py      — the Harness: the loop, wrapped, with hooks + policy + sandbox + subagents

Typical use:

    from harness import Harness, default_tools
    h = Harness("You are a helpful assistant.", default_tools())
    for event in h.run("What is (23 * 47) + 100?"):
        print(event.line())
"""

from .checkpoint import DONE, FAILED, INTERRUPTED, QUEUED, RUNNING, Checkpointer, RunState
from .core import HookBlock, Harness, Subagent, run_to_completion
from .graph import END, Graph
from .orchestrate import WorkerResult, fan_out
from .events import (
    Event,
    Interrupted,
    ModelTurn,
    PermissionAsked,
    Resumed,
    RunFinished,
    RunStarted,
    Steered,
    SubagentFinished,
    SubagentStarted,
    ToolBlocked,
    ToolFinished,
)
from .policy import ALLOW, ASK, DENY, PermissionPolicy, always_allow
from .steer import QueueController, ScriptedController, SteerController, SteerSignal
from .providers import Message, ToolCall, Transcript, Turn, describe, ensure_ready, provider_name, run_turn
from .sandbox import Sandbox, SandboxError
from .tools import (
    CALCULATOR,
    READ_FILE,
    RUN_COMMAND,
    SEARCH_NOTES,
    WRITE_FILE,
    Tool,
    default_tools,
)

__all__ = [
    "Harness",
    "Subagent",
    "HookBlock",
    "run_to_completion",
    "fan_out",
    "WorkerResult",
    "Graph",
    "END",
    "Event",
    "RunStarted",
    "ModelTurn",
    "PermissionAsked",
    "ToolBlocked",
    "ToolFinished",
    "SubagentStarted",
    "SubagentFinished",
    "Resumed",
    "Steered",
    "Interrupted",
    "RunFinished",
    "Checkpointer",
    "RunState",
    "QUEUED",
    "RUNNING",
    "DONE",
    "FAILED",
    "INTERRUPTED",
    "SteerController",
    "QueueController",
    "ScriptedController",
    "SteerSignal",
    "PermissionPolicy",
    "always_allow",
    "ALLOW",
    "ASK",
    "DENY",
    "Sandbox",
    "SandboxError",
    "Tool",
    "default_tools",
    "CALCULATOR",
    "READ_FILE",
    "WRITE_FILE",
    "RUN_COMMAND",
    "SEARCH_NOTES",
    "ToolCall",
    "Turn",
    "Message",
    "Transcript",
    "run_turn",
    "provider_name",
    "describe",
    "ensure_ready",
]
