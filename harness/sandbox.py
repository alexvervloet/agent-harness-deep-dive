"""
harness/sandbox.py: the boundary tools execute inside.

An agent's tools act on the world with arguments the *model* chose, and the model
is acting on text that may be attacker-controlled (the lesson of the Prompt
Injection dive). So tool execution needs a boundary the model can't argue its way
past. A harness owns that boundary; your bare loop didn't have one.

This is a tiny, teachable version: a **path jail** for file tools (every path is
resolved and must stay under one root: no `..`, no absolute escapes, no symlink
tricks) and a **command allowlist** for a shell tool (only named executables run).
Both reject-by-default. Real harnesses sandbox far harder (containers, seccomp,
network egress rules, a per-session workspace the provider hosts) but the shape is
this: the model proposes, the sandbox disposes.
"""

from __future__ import annotations

import os


class SandboxError(RuntimeError):
    """Raised when a tool tries to act outside the sandbox boundary."""


class Sandbox:
    """A path-jailed workspace plus a command allowlist."""

    def __init__(self, root: str, allowed_commands: set[str] | None = None):
        self.root = os.path.realpath(root)
        os.makedirs(self.root, exist_ok=True)
        self.allowed_commands = allowed_commands or set()

    # --- File jail: resolve the model-supplied path and confirm it stays inside. ---
    def resolve(self, path: str) -> str:
        """Resolve `path` under the sandbox root, or raise if it escapes.

        `os.path.realpath` collapses `..` and follows symlinks, so we check the
        *canonical* location: the check a naive `startswith` on the raw string
        would miss."""
        candidate = os.path.realpath(os.path.join(self.root, path))
        if candidate != self.root and not candidate.startswith(self.root + os.sep):
            raise SandboxError(
                f"path {path!r} escapes the sandbox ({self.root}). Refused."
            )
        return candidate

    def read(self, path: str) -> str:
        real = self.resolve(path)
        if not os.path.isfile(real):
            raise SandboxError(f"no such file in sandbox: {path!r}")
        with open(real, encoding="utf-8") as f:
            return f.read()

    def write(self, path: str, content: str) -> str:
        real = self.resolve(path)
        os.makedirs(os.path.dirname(real), exist_ok=True)
        with open(real, "w", encoding="utf-8") as f:
            f.write(content)
        return os.path.relpath(real, self.root)

    # --- Command allowlist: only named executables may run. ---
    def check_command(self, command: str) -> str:
        """Return the executable name if it's allowlisted, else raise.

        A blocklist ('reject rm') is a losing game: an attacker has infinite
        phrasings. An allowlist names the few commands you trust and refuses the
        rest by default."""
        exe = command.strip().split()[0] if command.strip() else ""
        if exe not in self.allowed_commands:
            raise SandboxError(
                f"command {exe!r} is not on the allowlist "
                f"({', '.join(sorted(self.allowed_commands)) or 'empty'}). Refused."
            )
        return exe
