"""
Example 01 — the bare loop, recapped, and everything it's missing (offline).
============================================================================

You built this loop by hand in the Agents dive: ask the model, run the tool it
requests, feed the result back, repeat. Here it is again in ~15 lines, driving the
offline mock. It works — and that's exactly the point of this dive: it works, but
it's naked. There's nowhere to gate a dangerous call, nowhere to see what happened
except `print`, no boundary on where a tool acts, and no way to delegate.

Run it:

    python examples/01_bare_loop_recap.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from harness import Sandbox, default_tools, describe, ensure_ready, run_turn

load_dotenv()
ensure_ready()
print(f"Provider: {describe()}\n")

SYSTEM = "You are a careful assistant. Use tools; don't guess."
tools = [t for t in default_tools() if t.name == "calculator"]
sandbox = Sandbox("workspace")
by_name = {t.name: t for t in tools}

# --- The whole agent, hand-written, exactly as in the Agents dive. ----------
transcript = [{"role": "user", "content": "What is (23 * 47) + 100?"}]
for _ in range(8):  # a bare step cap; nothing else guards this loop
    turn = run_turn(SYSTEM, transcript, tools)
    if not turn.tool_calls:
        print("Final answer:", turn.text)
        break
    transcript.append({"role": "assistant", "text": turn.text, "tool_calls": turn.tool_calls})
    for call in turn.tool_calls:
        print(f"  [loop] running {call.name}({call.arguments})")
        result = by_name[call.name].run(call.arguments, sandbox)  # no gate, no hook, no policy
        transcript.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": result})

print(
    "\nThat's the loop — and it's fine for a calculator. But notice what it CAN'T do:\n"
    "  1. Observe — the only visibility is print(); there's no structured event stream.\n"
    "  2. Gate — every tool runs unconditionally; a `write_file` would just happen.\n"
    "  3. Intercept — no place to block a bad call or redact a secret in a result.\n"
    "  4. Contain — the tool acts on the raw filesystem; nothing jails where it writes.\n"
    "  5. Delegate — one loop, one context; no subagents.\n"
    "A HARNESS is the loop plus those five. The rest of this dive adds them one at a\n"
    "time — and every one is a small wrapper around this exact loop, not a new idea."
)
