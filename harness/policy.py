"""
harness/policy.py: a declarative permission policy.

The Agents dive gated dangerous tools with an ad-hoc `approve` callback threaded
through the loop. That works, but the *policy* (which tools are free, which need a
human, which are forbidden) lived tangled in the loop code. A harness lifts it out
into a **declarative policy** you can read, diff, and version on its own.

Three verdicts, reject-leaning by default:

  allow  run it, no questions asked (read-only, cheap, reversible)
  ask    pause and ask a human before running (writes, spends, sends)
  deny   never run it (out of bounds for this agent)

This is the same idea as Claude Agent SDK / Claude Code permission modes and
Managed Agents' `always_allow` / `always_ask` per-tool config: a policy object
the harness consults on every tool call, separate from the loop itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ALLOW = "allow"
ASK = "ask"
DENY = "deny"


@dataclass
class PermissionPolicy:
    """Per-tool verdicts plus a default for anything unlisted."""

    default: str = ALLOW
    rules: dict[str, str] = field(default_factory=dict)

    def decide(self, tool_name: str) -> str:
        return self.rules.get(tool_name, self.default)

    # Convenience builders so a policy reads like a sentence.
    def allow(self, *names: str) -> "PermissionPolicy":
        for n in names:
            self.rules[n] = ALLOW
        return self

    def ask(self, *names: str) -> "PermissionPolicy":
        for n in names:
            self.rules[n] = ASK
        return self

    def deny(self, *names: str) -> "PermissionPolicy":
        for n in names:
            self.rules[n] = DENY
        return self


def always_allow() -> PermissionPolicy:
    """The permissive default: every tool runs. Fine for read-only agents."""
    return PermissionPolicy(default=ALLOW)
