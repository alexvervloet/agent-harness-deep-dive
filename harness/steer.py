"""
harness/steer.py: steering a running agent: interrupt, inject, queue.

The permission policy (policy.py) gates a tool *before* it runs: a synchronous
yes/no. Steering is the other half of operator control: acting on a run *while it's
in flight*. Three moves, all of which a good harness supports and a bare loop
can't:

  - INJECT: drop a message into the run mid-flight ("actually, use the Pro plan")
              so it changes the *next* step, without restarting.
  - QUEUE: send follow-up messages while the agent is busy; they're processed in
              order at the next safe boundary.
  - INTERRUPT: tell the run to stop. A good agent doesn't die mid-tool; it finishes
              the current step and halts at the next boundary.

The harness polls a **controller** at each step boundary (between model turns,
after any tool results are in, a safe place to change course). This file gives you
two controllers: a live `QueueController` you drive from your app, and a
`ScriptedController` that's deterministic for demos and tests. This is the
from-scratch shape of Managed Agents' message queue + `user.interrupt` +
mid-session steering.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SteerSignal:
    """What the harness should do at a step boundary: inject these messages, and/or
    stop if `interrupt_reason` is set."""

    messages: list[str] = field(default_factory=list)
    interrupt_reason: str | None = None


class SteerController:
    """Base control channel. The harness calls `poll(step)` between steps; return a
    SteerSignal to inject messages or interrupt. Default: do nothing."""

    def poll(self, step: int) -> SteerSignal:
        return SteerSignal()


class QueueController(SteerController):
    """A live queue: call `steer(msg)` / `interrupt()` from your application (an
    operator UI, a chat bridge); the harness drains them at the next boundary."""

    def __init__(self) -> None:
        self._messages: list[str] = []
        self._interrupt: str | None = None

    def steer(self, message: str) -> None:
        self._messages.append(message)

    def interrupt(self, reason: str = "operator interrupt") -> None:
        self._interrupt = reason

    def poll(self, step: int) -> SteerSignal:
        signal = SteerSignal(
            messages=self._messages[:], interrupt_reason=self._interrupt
        )
        self._messages = []  # drained
        return signal


class ScriptedController(SteerController):
    """Deterministic steering for demos/tests: inject a message at a given step
    number, and/or interrupt at one. `step` is how many tool-steps have completed,
    so step=1 acts after the first step, before the second model turn."""

    def __init__(
        self, *, inject: dict[int, str] | None = None, interrupt_at: int | None = None
    ):
        self.inject = inject or {}
        self.interrupt_at = interrupt_at

    def poll(self, step: int) -> SteerSignal:
        return SteerSignal(
            messages=[self.inject[step]] if step in self.inject else [],
            interrupt_reason="operator said stop"
            if step == self.interrupt_at
            else None,
        )
