"""
harness/events.py: the harness speaks in events, not print statements.

The bare agent loop (from the Agents dive) is a `while` loop that occasionally
`print()`s. A harness turns that loop *inside out*: instead of you writing the
loop and sprinkling prints, the harness runs the loop and emits a **stream of
typed events**, one per thing that happens. You (or a UI, or a log pipeline, or
a test) consume that stream.

That inversion is the whole reason a harness is worth adopting: every event is a
place to observe, gate, or react, without touching the loop. These are the events
this repo's harness emits. Each has a `.line()` for pretty printing; real harnesses
(Claude Agent SDK, OpenAI Agents SDK) emit a richer but structurally identical
stream.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .providers import ToolCall


@dataclass(kw_only=True)
class Event:
    """Base class. Every event carries the run's depth (0 = main agent, 1 = a
    subagent) so a UI can indent nested work."""

    depth: int = 0

    def line(self) -> str:  # pragma: no cover - overridden
        return self.__class__.__name__

    def _indent(self) -> str:
        return "  " * self.depth


@dataclass(kw_only=True)
class RunStarted(Event):
    task: str = ""

    def line(self) -> str:
        return f"{self._indent()}▶ run started: {self.task!r}"


@dataclass(kw_only=True)
class ModelTurn(Event):
    """The model produced a turn: either tool requests or a final answer."""

    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    def line(self) -> str:
        if self.tool_calls:
            names = ", ".join(c.name for c in self.tool_calls)
            return f"{self._indent()}· model wants tool(s): {names}"
        return f"{self._indent()}· model answered"


@dataclass(kw_only=True)
class PermissionAsked(Event):
    call: ToolCall
    decision: str = ""  # "allow" | "deny"

    def line(self) -> str:
        return f"{self._indent()}? permission for {self.call.name}: {self.decision}"


@dataclass(kw_only=True)
class ToolBlocked(Event):
    call: ToolCall
    reason: str = ""

    def line(self) -> str:
        return f"{self._indent()}✗ blocked {self.call.name}: {self.reason}"


@dataclass(kw_only=True)
class ToolFinished(Event):
    call: ToolCall
    result: str = ""
    redacted: bool = False

    def line(self) -> str:
        tag = " (post-hook edited)" if self.redacted else ""
        preview = self.result if len(self.result) <= 80 else self.result[:77] + "..."
        return f"{self._indent()}✓ {self.call.name} -> {preview}{tag}"


@dataclass(kw_only=True)
class SubagentStarted(Event):
    name: str = ""
    task: str = ""

    def line(self) -> str:
        return f"{self._indent()}⇢ subagent {self.name!r} started: {self.task!r}"


@dataclass(kw_only=True)
class SubagentFinished(Event):
    name: str = ""
    answer: str = ""

    def line(self) -> str:
        return f"{self._indent()}⇠ subagent {self.name!r} done"


@dataclass(kw_only=True)
class Resumed(Event):
    """A run was reloaded from a checkpoint and continued, not started fresh."""

    run_id: str = ""
    steps: int = 0

    def line(self) -> str:
        return f"{self._indent()}↻ resumed run {self.run_id!r} from checkpoint (already {self.steps} step(s) in)"


@dataclass(kw_only=True)
class Steered(Event):
    """An operator injected a message mid-run; it steers the next model turn."""

    message: str = ""

    def line(self) -> str:
        return f"{self._indent()}➤ steered mid-run: {self.message!r}"


@dataclass(kw_only=True)
class Interrupted(Event):
    """An operator interrupted the run; it stopped at the next safe boundary."""

    reason: str = ""

    def line(self) -> str:
        note = f" ({self.reason})" if self.reason else ""
        return f"{self._indent()}⏹ interrupted{note}"


@dataclass(kw_only=True)
class RunFinished(Event):
    answer: str = ""
    stopped_early: bool = False
    steps: int = 0

    def line(self) -> str:
        note = "  (stopped early)" if self.stopped_early else ""
        return f"{self._indent()}■ run finished in {self.steps} step(s){note}"
