"""
Example 04 — permission policies: allow / ask / deny, lifted out of the loop.
=============================================================================

The Agents dive gated dangerous tools with an `approve` callback threaded through
the loop. A harness makes the *policy* a declarative object you read, diff, and
version on its own — separate from the loop code. Three verdicts:

  allow — run it (read-only, cheap, reversible)
  ask   — pause and ask a human before running (writes, spends, sends)
  deny  — never run it (out of bounds for this agent)

Here the calculator is `allow`, `write_file` is `ask` (we auto-approve to keep the
demo non-interactive), and `run_command` is `deny`. Watch the harness consult the
policy on every call — and watch the agent adapt when a call is denied, because a
denial comes back as just another tool result.

Run it:

    python examples/04_permissions.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from harness import ALLOW, Harness, PermissionPolicy, Sandbox, default_tools, describe, ensure_ready

load_dotenv()
ensure_ready()
print(f"Provider: {describe()}\n")

policy = (
    PermissionPolicy(default=ALLOW)
    .ask("write_file")     # writes need a human
    .deny("run_command")   # shell is out of bounds for this agent
)

# Auto-approve here so the example runs unattended; a real app would prompt.
agent = Harness(
    "You are an assistant with file and shell tools.",
    default_tools(),
    policy=policy,
    sandbox=Sandbox("workspace"),
    approve=lambda call: True,
)

for task in [
    "write file plan.txt containing: ship the harness dive",   # ask -> approved
    "run the command rm -rf /",                                 # deny -> blocked
]:
    print(f"Task: {task}")
    for event in agent.run(task):
        print("  " + event.line())
    print()

print(
    "The write was gated by an `ask` verdict (approved here, prompted in a real app);\n"
    "the shell command was refused by a `deny` verdict before it ran. The policy is a\n"
    "plain object — you can unit-test it, diff it in review, and swap it per\n"
    "environment (strict in prod, loose in a sandbox) without touching agent code.\n"
    "That's exactly the shape of Claude Agent SDK permission modes and Managed Agents'\n"
    "per-tool always_allow / always_ask config."
)
