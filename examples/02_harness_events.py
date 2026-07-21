"""
Example 02: the same task, but the harness runs the loop and emits events.

Example 01 wrote the loop. Here we hand the same task to a `Harness` and stop
writing loops: we configure it, then *consume its event stream*. The loop is gone
from your code. It's inside `Harness.run()`, which yields one typed event per
thing that happens (see harness/events.py). That inversion is the point of a
harness: every event is a place to observe, react, or record.

This is the "throw away your loop for the SDK" moment in miniature. You give up
writing the `while`; you get back a stream you can render in a UI, pipe to a log,
assert on in a test, or (next examples) intercept and gate.

Run it:

    python examples/02_harness_events.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from harness import Harness, RunFinished, default_tools, describe, ensure_ready

load_dotenv()
ensure_ready()
print(f"Provider: {describe()}\n")

tools = [t for t in default_tools() if t.name == "calculator"]
agent = Harness("You are a careful assistant. Use tools; don't guess.", tools)

print("Event stream:")
answer = ""
for event in agent.run("What is (23 * 47) + 100?"):
    print("  " + event.line())
    if isinstance(event, RunFinished):
        answer = event.answer

print(f"\nFinal answer: {answer}")
print(
    "\nYou never wrote a loop. You iterated an event stream, and the harness handled\n"
    "the mechanics. Same result as example 01, but now there are seams: the next\n"
    "three examples slot hooks, a permission policy, and a sandbox into those seams\n"
    "without touching the loop at all."
)
