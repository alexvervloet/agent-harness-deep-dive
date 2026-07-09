"""
harness/tools.py — what a tool is, and a small sandboxed toolbox.
=================================================================

Same definition as the Agents dive: to your code a tool is a function; to the
model it's a name, a description, and a JSON Schema. The one addition here is that
a tool receives the **sandbox** as a second argument, so file and command tools
act *through* the boundary rather than straight at the filesystem. The harness
decides whether a tool even runs (permission policy) and what happens around it
(hooks); the tool just does its job inside the sandbox it's handed.
"""

from __future__ import annotations

import ast
import operator
import subprocess
from dataclasses import dataclass
from typing import Callable

from .sandbox import Sandbox


@dataclass
class Tool:
    """A callable the model can request. `func(args, sandbox) -> str`.

    `dangerous=True` marks tools with real-world consequences (writing files,
    running commands, spending money) — the permission policy and the capstone
    use it to decide what needs a human in the loop."""

    name: str
    description: str
    parameters: dict  # JSON Schema for the inputs
    func: Callable[[dict, Sandbox], str]
    dangerous: bool = False

    def run(self, args: dict, sandbox: Sandbox) -> str:
        return self.func(args, sandbox)


# --- A safe arithmetic evaluator (no eval of arbitrary Python). -------------
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.Mod: operator.mod,
}


def _safe_eval(expr: str) -> float:
    def ev(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ValueError("unsupported expression")

    return ev(ast.parse(expr, mode="eval").body)


def _calculator(args: dict, _sandbox: Sandbox) -> str:
    expr = str(args.get("expression", ""))
    result = _safe_eval(expr)
    return str(int(result) if float(result).is_integer() else round(result, 6))


def _read_file(args: dict, sandbox: Sandbox) -> str:
    # sandbox.read resolves the path under the jail and raises on escape.
    return sandbox.read(str(args.get("path", "")))


def _write_file(args: dict, sandbox: Sandbox) -> str:
    rel = sandbox.write(str(args.get("path", "")), str(args.get("content", "")))
    return f"{rel} ({len(str(args.get('content', '')))} chars)"


# A tiny read-only knowledge base, so a "research" subagent has something to look
# up offline (mirrors the Agents dive's search_notes).
_NOTES = {
    "plans and prices": "Plans: Free ($0), Plus ($10/mo), and Pro ($30/mo).",
    "refunds policy": "Refunds are available within 30 days of purchase.",
    "data export": "Export all notes as Markdown under Settings > Data > Export.",
    "support hours": "Support is staffed weekdays, 9am-6pm Pacific.",
}


def _words(text: str) -> set[str]:
    """Lowercase alphanumeric words — so 'plans,' and 'Plans:' both match 'plans'
    (punctuation stuck to a word must not defeat the lookup)."""
    import re

    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def _search_notes(args: dict, _sandbox: Sandbox) -> str:
    qwords = _words(str(args.get("query", "")))
    best, best_score = None, 0
    for key, text in _NOTES.items():
        score = len(qwords & _words(key)) + len(qwords & _words(text))
        if score > best_score:
            best, best_score = text, score
    return best or "No matching note found."


def _run_command(args: dict, sandbox: Sandbox) -> str:
    command = str(args.get("command", ""))
    sandbox.check_command(command)  # raises if not on the allowlist
    out = subprocess.run(
        command, shell=True, cwd=sandbox.root, capture_output=True, text=True, timeout=5
    )
    return (out.stdout + out.stderr).strip() or "(no output)"


CALCULATOR = Tool(
    name="calculator",
    description="Evaluate a basic arithmetic expression, e.g. '(23 * 47) + 100'.",
    parameters={
        "type": "object",
        "properties": {"expression": {"type": "string"}},
        "required": ["expression"],
    },
    func=_calculator,
)

READ_FILE = Tool(
    name="read_file",
    description="Read a UTF-8 text file from the workspace by relative path.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    func=_read_file,
)

WRITE_FILE = Tool(
    name="write_file",
    description="Write text to a file in the workspace by relative path. Overwrites.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
    func=_write_file,
    dangerous=True,
)

RUN_COMMAND = Tool(
    name="run_command",
    description="Run a shell command in the workspace (subject to the sandbox allowlist).",
    parameters={
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
    func=_run_command,
    dangerous=True,
)

SEARCH_NOTES = Tool(
    name="search_notes",
    description="Search a small internal knowledge base and return the best matching note.",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
    func=_search_notes,
)


def default_tools() -> list[Tool]:
    """The standard toolbox: read-only calculator + file read, plus the two
    dangerous tools (write, command) the permission policy will gate."""
    return [CALCULATOR, READ_FILE, WRITE_FILE, RUN_COMMAND]
