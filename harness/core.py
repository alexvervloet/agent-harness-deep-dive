"""
harness/core.py: the harness: the loop, wrapped, with places to intervene.

This is the payoff of the whole dive. In the Agents dive you *wrote* the loop. A
harness runs the loop for you and gives you five things a bare loop doesn't:

  1. an event stream        you observe/react instead of reading print()s
  2. hooks                  intercept each tool call (block it, or edit its result)
  3. a permission policy    declarative allow/ask/deny, lifted out of the loop
  4. a sandbox              the boundary tools execute inside
  5. subagents              delegate to a nested harness with its own context

`Harness.run(task)` is a generator: it yields typed events (see events.py) and
threads every tool call through policy → hooks → sandbox. Read it once and the
real harnesses (Claude Agent SDK, OpenAI Agents SDK, Managed Agents) stop being
magic; they're this, hardened and hosted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterator

from . import providers
from .checkpoint import DONE, FAILED, INTERRUPTED, RUNNING, Checkpointer, RunState
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
from .steer import SteerController
from .providers import ToolCall, Transcript
from .sandbox import Sandbox
from .tools import Tool


class HookBlock(Exception):
    """Raise this from a pre-tool hook to block a tool call with a reason."""


@dataclass
class Subagent:
    """A delegate the harness can spawn: its own persona and toolset, sharing the
    parent's sandbox (subagents share the filesystem, not the conversation)."""

    name: str
    description: str
    system: str
    tools: list[Tool]
    policy: PermissionPolicy = field(default_factory=always_allow)
    max_steps: int = 6


class Harness:
    """Runs the agent loop and emits events. Configure it, then iterate `run()`."""

    def __init__(
        self,
        system: str,
        tools: list[Tool],
        *,
        policy: PermissionPolicy | None = None,
        sandbox: Sandbox | None = None,
        approve: Callable[[ToolCall], bool] | None = None,
        max_steps: int = 8,
    ):
        self.system = system
        self.tools = list(tools)
        self.policy = policy or always_allow()
        self.sandbox = sandbox or Sandbox("workspace")
        self.approve = approve
        self.max_steps = max_steps
        self.pre_tool_hooks: list[Callable[[ToolCall], str | None]] = []
        self.post_tool_hooks: list[Callable[[ToolCall, str], str]] = []
        self.subagents: dict[str, Subagent] = {}
        self.last_answer: str = ""

    # --- Configuration --------------------------------------------------------
    def on_pre_tool(self, fn: Callable[[ToolCall], str | None]) -> "Harness":
        """Register a pre-tool hook. Return a string to substitute a result (short-
        circuit the tool), or raise HookBlock(reason) to block it. Return None to
        proceed."""
        self.pre_tool_hooks.append(fn)
        return self

    def on_post_tool(self, fn: Callable[[ToolCall, str], str]) -> "Harness":
        """Register a post-tool hook that can transform a tool's result (e.g. redact
        a secret before it re-enters the model's context)."""
        self.post_tool_hooks.append(fn)
        return self

    def add_subagent(self, sub: Subagent) -> "Harness":
        """Register a subagent. It appears to the model as an ordinary tool that
        takes a `task` string; the harness intercepts the call and runs a nested
        harness for it."""
        self.subagents[sub.name] = sub
        return self

    # --- The tool set the model sees (real tools + subagents-as-tools). -------
    def _visible_tools(self) -> list[Tool]:
        subagent_tools = [
            Tool(
                name=s.name,
                description=s.description,
                parameters={
                    "type": "object",
                    "properties": {"task": {"type": "string"}},
                    "required": ["task"],
                },
                func=lambda *_: "",  # never called directly; the harness intercepts
            )
            for s in self.subagents.values()
        ]
        return self.tools + subagent_tools

    def _tool_by_name(self, name: str) -> Tool | None:
        for t in self.tools:
            if t.name == name:
                return t
        return None

    # --- The loop ------------------------------------------------------------
    def run(
        self,
        task: str,
        *,
        run_id: str | None = None,
        checkpointer: "Checkpointer | None" = None,
        controller: "SteerController | None" = None,
        _depth: int = 0,
    ) -> Iterator[Event]:
        # Resume from a checkpoint if one exists for this run_id and it isn't done.
        resumed = None
        if checkpointer is not None and run_id is not None and _depth == 0:
            resumed = checkpointer.load(run_id)

        if resumed is not None and resumed.status == DONE:
            # Already finished in a previous process, so nothing to redo.
            yield RunFinished(depth=_depth, answer=resumed.answer, steps=resumed.steps)
            self.last_answer = resumed.answer
            return

        transcript: Transcript
        if resumed is not None and resumed.transcript:
            transcript = resumed.transcript  # the completed work, off disk
            steps = resumed.steps
            task = resumed.task
            yield Resumed(depth=_depth, run_id=run_id or "", steps=steps)
        else:
            transcript = [{"role": "user", "content": task}]
            steps = 0
            yield RunStarted(depth=_depth, task=task)
            self._checkpoint(checkpointer, run_id, task, transcript, steps, RUNNING)

        stopped_early = False
        interrupted = False
        answer = ""

        while True:
            # A step boundary: safe to steer. Poll the control channel for injected
            # messages (they change the next turn) or an interrupt (stop cleanly).
            if controller is not None:
                signal = controller.poll(steps)
                for message in signal.messages:
                    transcript.append({"role": "user", "content": message})
                    self._checkpoint(
                        checkpointer, run_id, task, transcript, steps, RUNNING
                    )
                    yield Steered(depth=_depth, message=message)
                if signal.interrupt_reason:
                    interrupted = True
                    answer = "(interrupted by operator)"
                    yield Interrupted(depth=_depth, reason=signal.interrupt_reason)
                    break

            turn = providers.run_turn(self.system, transcript, self._visible_tools())
            yield ModelTurn(depth=_depth, text=turn.text, tool_calls=turn.tool_calls)

            if not turn.tool_calls:
                answer = turn.text or ""
                break

            transcript.append(
                {"role": "assistant", "text": turn.text, "tool_calls": turn.tool_calls}
            )

            for call in turn.tool_calls:
                # The step ceiling is per tool call, not per turn: a single turn can
                # carry many parallel calls, and each one counts. Check before running
                # the call so the limit bounds a burst, not just a turn boundary.
                if steps >= self.max_steps:
                    stopped_early = True
                    answer = "(stopped: reached the step limit)"
                    break
                steps += 1

                # 1. Subagent? Run a nested harness and re-emit its events.
                if call.name in self.subagents:
                    result = yield from self._run_subagent(call, _depth)
                    transcript.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.name,
                            "content": result,
                        }
                    )
                    self._checkpoint(
                        checkpointer, run_id, task, transcript, steps, RUNNING
                    )
                    continue

                # 2. Permission policy.
                verdict = self.policy.decide(call.name)
                if verdict == DENY:
                    yield ToolBlocked(
                        depth=_depth, call=call, reason="denied by policy"
                    )
                    transcript.append(
                        self._tool_result(
                            call, "Blocked: this action is denied by policy."
                        )
                    )
                    self._checkpoint(
                        checkpointer, run_id, task, transcript, steps, RUNNING
                    )
                    continue
                if verdict == ASK:
                    approved = self.approve(call) if self.approve else False
                    yield PermissionAsked(
                        depth=_depth, call=call, decision=ALLOW if approved else DENY
                    )
                    if not approved:
                        transcript.append(
                            self._tool_result(
                                call, "Blocked: the user did not approve this action."
                            )
                        )
                        self._checkpoint(
                            checkpointer, run_id, task, transcript, steps, RUNNING
                        )
                        continue

                # 3. Pre-tool hooks (block, or substitute a result).
                try:
                    substitute = None
                    for hook in self.pre_tool_hooks:
                        r = hook(call)
                        if r is not None:
                            substitute = r
                except HookBlock as hb:
                    yield ToolBlocked(depth=_depth, call=call, reason=str(hb))
                    transcript.append(self._tool_result(call, f"Blocked by hook: {hb}"))
                    self._checkpoint(
                        checkpointer, run_id, task, transcript, steps, RUNNING
                    )
                    continue

                # 4. Execute (in the sandbox), or use the hook's substitute.
                if substitute is not None:
                    result = substitute
                else:
                    tool = self._tool_by_name(call.name)
                    if tool is None:
                        result = f"Error: no such tool {call.name!r}."
                    else:
                        try:
                            result = tool.run(call.arguments, self.sandbox)
                        except Exception as e:  # noqa: BLE001. Errors go back as results
                            result = f"Error: {e}"

                # 5. Post-tool hooks (transform the result, e.g. redact).
                original = result
                for hook in self.post_tool_hooks:
                    result = hook(call, result)
                # Persist the completed step BEFORE announcing it, so a crash the
                # instant after ToolFinished still has this result on disk to resume
                # from (rather than re-running the tool).
                transcript.append(self._tool_result(call, result))
                self._checkpoint(checkpointer, run_id, task, transcript, steps, RUNNING)
                yield ToolFinished(
                    depth=_depth, call=call, result=result, redacted=result != original
                )

            if stopped_early:
                break

        final_status = INTERRUPTED if interrupted else FAILED if stopped_early else DONE
        self._checkpoint(
            checkpointer, run_id, task, transcript, steps, final_status, answer
        )
        yield RunFinished(
            depth=_depth,
            answer=answer,
            stopped_early=stopped_early or interrupted,
            steps=steps,
        )
        self.last_answer = answer

    # --- Helpers -------------------------------------------------------------
    def _tool_result(self, call: ToolCall, content: str) -> dict:
        return {
            "role": "tool",
            "tool_call_id": call.id,
            "name": call.name,
            "content": content,
        }

    def _checkpoint(
        self, checkpointer, run_id, task, transcript, steps, status, answer=""
    ):
        """Persist the run's resumable state after a step, if a checkpointer is
        attached. No-op otherwise, so non-durable runs pay nothing."""
        if checkpointer is None or run_id is None:
            return
        checkpointer.save(
            RunState(
                run_id=run_id,
                task=task,
                status=status,
                steps=steps,
                answer=answer,
                transcript=list(transcript),
            )
        )

    def _run_subagent(self, call: ToolCall, depth: int) -> Iterator[Event]:
        spec = self.subagents[call.name]
        sub_task = str(call.arguments.get("task", ""))
        yield SubagentStarted(depth=depth, name=spec.name, task=sub_task)
        child = Harness(
            spec.system,
            spec.tools,
            policy=spec.policy,
            sandbox=self.sandbox,
            approve=self.approve,
            max_steps=spec.max_steps,
        )
        sub_answer = ""
        for ev in child.run(sub_task, _depth=depth + 1):
            if isinstance(ev, RunFinished):
                sub_answer = ev.answer
            yield ev
        yield SubagentFinished(depth=depth, name=spec.name, answer=sub_answer)
        return sub_answer


def run_to_completion(
    harness: Harness, task: str, *, on_event: Callable[[Event], None] | None = None
) -> str:
    """Drive a harness to its final answer, optionally handling each event.

    A convenience for headless/scripted use: you don't always want to write the
    `for event in harness.run(...)` loop yourself."""
    answer = ""
    for event in harness.run(task):
        if on_event:
            on_event(event)
        if isinstance(event, RunFinished) and event.depth == 0:
            answer = event.answer
    return answer
