"""
Example 03 — hooks: intercept the loop without editing it.
==========================================================

A hook is a function the harness calls at a fixed point in every tool cycle. Two
kinds here:

  pre-tool  — runs before a tool executes. Return a string to substitute a result
              (short-circuit the tool), or raise HookBlock(reason) to block it.
  post-tool — runs after a tool executes. Transform the result before it re-enters
              the model's context — the natural place to REDACT secrets.

Hooks are how a harness lets you enforce policy that the loop knows nothing about.
Here: a pre-tool hook blocks reads of anything that looks like a credentials file,
and a post-tool hook redacts an API key that slips through in a file's contents —
so the model (and your logs) never see the raw secret.

Run it:

    python examples/03_hooks.py
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from harness import Harness, HookBlock, Sandbox, describe, ensure_ready
from harness.tools import READ_FILE

load_dotenv()
ensure_ready()
print(f"Provider: {describe()}\n")

sandbox = Sandbox("workspace")
# Seed two files: one safe, one with a secret in it.
sandbox.write(
    "report.txt",
    "All systems nominal. Deploy went out at 14:02. api_token=sk-live-9F2A7Q secret!",
)


def block_credential_reads(call):
    """pre-tool: refuse to even open files that look like credential stores."""
    if call.name == "read_file" and re.search(
        r"(cred|secret|\.env|password)", str(call.arguments.get("path", "")), re.I
    ):
        raise HookBlock("reading credential files is not permitted")
    return None  # otherwise proceed


def redact_secrets(call, result):
    """post-tool: scrub anything that looks like a key before it re-enters context."""
    return re.sub(r"(sk-[A-Za-z0-9\-]+|api_token=\S+)", "[REDACTED]", result)


agent = (
    Harness("You read files and summarize them.", [READ_FILE], sandbox=sandbox)
    .on_pre_tool(block_credential_reads)
    .on_post_tool(redact_secrets)
)

for task in ["read report.txt", "read secrets.txt"]:
    print(f"Task: {task}")
    for event in agent.run(task):
        print("  " + event.line())
    print()

print(
    "The first read ran but its API token was redacted by the post-tool hook — the\n"
    "model summarized a file it was never shown the secret from. The second read was\n"
    "blocked outright by the pre-tool hook, before the tool touched disk. Neither the\n"
    "loop nor the tool changed; the harness enforced both rules at its seams. This is\n"
    "how real harnesses ship guardrails (the Prompt Injection dive's defenses live\n"
    "here) without every tool re-implementing them."
)
