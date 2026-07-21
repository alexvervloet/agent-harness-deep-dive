"""
Example 12: steering a running agent: inject and interrupt, mid-run.

The permission policy (example 04) gates a tool *before* it runs. Steering is the
other half of operator control: acting on a run *while it's in flight*. Two moves
here, both of which a bare loop can't do:

  - INJECT: drop a message into the run mid-flight so it changes the NEXT step,
              without restarting ("actually, I only care about Pro").
  - INTERRUPT: tell the run to stop. A good agent doesn't die mid-tool; it finishes
              the current step and halts at the next safe boundary.

The harness polls a **controller** at each step boundary (between model turns,
after any tool results are in). We use a deterministic `ScriptedController` so the
demo is reproducible; a real app would use the live `QueueController` (call
`.steer(msg)` / `.interrupt()` from an operator UI or chat bridge, and the harness
drains them at the next boundary). This is the from-scratch shape of Managed Agents'
message queue + `user.interrupt`.

Watch: the agent looks up the plans; we inject a follow-up that sends it to the
calculator; then we interrupt before it can wander further.

Offline and deterministic. Run:

    python examples/12_steering.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from harness import Harness, Interrupted, Sandbox, Steered, describe, ensure_ready
from harness.steer import ScriptedController
from harness.tools import CALCULATOR, SEARCH_NOTES

load_dotenv()
ensure_ready()
print(f"Provider: {describe()}\n")

# After step 1 (the lookup), inject a follow-up; after step 2, interrupt.
controller = ScriptedController(
    inject={1: "Now compute a year of Pro: 30 * 12."},
    interrupt_at=2,
)

agent = Harness(
    "You are a support assistant. Look things up, then help with the numbers.",
    [SEARCH_NOTES, CALCULATOR],
    sandbox=Sandbox("workspace"),
)

print("Event stream (operator steers, then interrupts):")
for event in agent.run("Look up the plans and prices.", controller=controller):
    print("  " + event.line())
    if isinstance(event, Steered):
        print(
            "     -> the injected message becomes the newest user turn; it steers the next step."
        )
    if isinstance(event, Interrupted):
        print("     ↳ the run stopped at a step boundary, not mid-tool.")

print(
    "\nTwo operator controls the bare loop never had: the agent changed course from the\n"
    "injected message (lookup → calculation) without a restart, and it stopped cleanly\n"
    "when interrupted rather than being killed mid-tool. In a real app you'd drive a\n"
    "live QueueController, steer() and interrupt() from a UI or chat bridge, and the\n"
    "harness would drain it at each safe boundary. An interrupted run is checkpointed\n"
    "as 'interrupted' (resumable), not lost: the same durable state as a crash."
)
