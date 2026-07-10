"""
harness/providers.py — the ONLY provider-specific file.
=======================================================

Same keystone as every sibling repo: hide the model call behind a tiny neutral
interface so the harness above it is provider-agnostic. The harness keeps a
*neutral transcript* (plain dicts) and asks for one thing:

    run_turn(system, transcript, tools) -> Turn   # text and/or tool calls

Pick your stack with `PROVIDER` in `.env`:

  PROVIDER=mock   ->  a deterministic, offline tool-calling "model". No key, no
                      cost. **The default** — the harness primitives are
                      provider-neutral, so a mock model shows every one of them.
  PROVIDER=openai ->  OpenAI chat + function calling   (OPENAI_API_KEY)
  PROVIDER=claude ->  Claude messages + tool use       (ANTHROPIC_API_KEY)

Why a mock is the right call here: this dive is about the harness (hooks,
permission policy, sandbox, subagents, headless runs), not the model. A rule-based
planner that reliably asks for the tool each example is about lets you watch the
harness machinery deterministically, offline, for $0. Real models make the same
kinds of requests, just less predictably.

The neutral transcript entries are:
  {"role": "user",      "content": str}
  {"role": "assistant", "text": str|None, "tool_calls": [ToolCall, ...]}
  {"role": "tool",      "tool_call_id": str, "name": str, "content": str}
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

_OPENAI_CHAT = "gpt-4o-mini"
_CLAUDE_CHAT = "claude-haiku-4-5"
_MOCK_MODEL = "mock-1"

_KEYS = {"mock": [], "openai": ["OPENAI_API_KEY"], "claude": ["ANTHROPIC_API_KEY"]}


@dataclass
class ToolCall:
    """A normalized request from the model to run one tool."""

    id: str
    name: str
    arguments: dict


@dataclass
class Turn:
    """One assistant turn, normalized. Empty `tool_calls` means a final answer."""

    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


# The neutral transcript: a list of loosely-typed message dicts. The three shapes
# are documented in the module docstring above (user / assistant / tool). It's
# deliberately `dict[str, Any]` — the harness threads these dicts through unchanged,
# and each provider adapter reshapes them into its own SDK's message format.
Message = dict[str, Any]
Transcript = list[Message]


def _configured_provider() -> str:
    """What .env / the environment *asked* for, verbatim (before any fallback)."""
    return os.getenv("PROVIDER", "mock").strip().lower()


def _has_required_keys(p: str) -> bool:
    return all(os.getenv(k) for k in _KEYS.get(p, []))


_warned_fallback = False


def _warn_mock_fallback(p: str) -> None:
    """Announce — loudly, but only once — that we degraded to the mock, and why."""
    global _warned_fallback
    if _warned_fallback:
        return
    _warned_fallback = True
    missing = ", ".join(_KEYS.get(p, []))
    print(
        f"\n⚠  PROVIDER={p} is set, but {missing} isn't on the environment — did you\n"
        f"   forget `secrun`? Falling back to the offline mock so this still runs.\n"
        f"   Real model:  secrun python <script>   |   Hard error instead:  PROVIDER_STRICT=1\n",
        file=sys.stderr,
    )


def provider_name() -> str:
    """The active stack: 'mock' (default), 'openai', or 'claude'.

    If a real provider is selected but its key isn't on the environment (the
    classic "forgot `secrun`"), degrade to the offline mock — loudly, and only
    once — so a demo keeps running instead of dying on a missing key. This is the
    *opposite* of a silent fallback: a stderr banner and `describe()` both announce
    it, so you can never mistake a keyless mock run for a real one. Set
    PROVIDER_STRICT=1 to make the missing key a hard error instead (recommended for
    CI and any real eval/cost run, where a silent mock would be dangerous)."""
    p = _configured_provider()
    if p in _KEYS and p != "mock" and not _has_required_keys(p):
        if os.getenv("PROVIDER_STRICT"):
            return p  # let ensure_ready()/the SDK raise the explicit missing-key error
        _warn_mock_fallback(p)
        return "mock"
    return p


def required_keys() -> list[str]:
    return _KEYS.get(provider_name(), [])


def describe() -> str:
    configured = _configured_provider()
    p = provider_name()
    if p == "mock" and configured != "mock":
        return (
            f"mock  (FALLBACK: PROVIDER={configured} is set but its key isn't on the "
            f"environment — run under `secrun` for the real model)"
        )
    if p == "mock":
        return f"mock  (offline, deterministic, model={_MOCK_MODEL}, no key)"
    if p == "openai":
        return f"openai  (chat={_OPENAI_CHAT})"
    if p == "claude":
        return f"claude  (chat={_CLAUDE_CHAT})"
    return f"unknown provider {p!r}"


def ensure_ready() -> None:
    import sys

    p = provider_name()
    if p not in _KEYS:
        sys.exit(
            f"PROVIDER={p!r} is not recognized. Set PROVIDER=mock (default), openai, or claude in .env."
        )
    missing = [k for k in required_keys() if not os.getenv(k)]
    if missing:
        sys.exit(
            f"PROVIDER={p} needs {', '.join(missing)} in the environment. "
            f"Provide them via secrun (see SECRETS.md), or run `secrun python check_setup.py`. "
            f"(Tip: PROVIDER=mock needs no key and runs everything offline.)"
        )


# ---------------------------------------------------------------------------
# The mock planner — deterministic, rule-based tool selection.
# ---------------------------------------------------------------------------
def _last_user(transcript: Transcript) -> str:
    for e in reversed(transcript):
        if e.get("role") == "user":
            return e.get("content", "")
    return ""


_MATH_RE = re.compile(r"[-+]?[(\d][\d\s+\-*/().]*[\d)]")


def _detect_intents(user: str, tool_names: set[str]) -> list[ToolCall]:
    """Parse a request into an ORDERED list of tool calls, one per detected intent,
    sorted by where each trigger appears in the text. This is what lets the mock
    chain steps deterministically — 'look up X, then compute Y' becomes
    [research, calculator] in that order. Conservative: an intent is added only
    when its arguments parse cleanly.

    The mock issues these one per turn (see `_mock_turn`), so a real multi-step
    request completes honestly instead of stopping after the first tool."""
    low = user.lower()
    cands: list[tuple[int, ToolCall]] = []

    if "calculator" in tool_names and re.search(r"\d\s*[-+*/]\s*\d", user):
        m = _MATH_RE.search(user.replace("x", "*"))
        if m:
            cands.append(
                (
                    m.start(),
                    ToolCall(
                        "call_calc", "calculator", {"expression": m.group(0).strip()}
                    ),
                )
            )

    if "read_file" in tool_names:
        m = re.search(
            r"(?:read|cat|open)\s+(?:the\s+file\s+)?([^\s]+)", user, re.IGNORECASE
        )
        if m:
            cands.append(
                (
                    m.start(),
                    ToolCall(
                        "call_read", "read_file", {"path": m.group(1).strip("'\"")}
                    ),
                )
            )

    if "write_file" in tool_names:
        m = re.search(
            r"file\s+([^\s]+)\s+(?:containing|with|saying)[:\s]+(.+)",
            user,
            re.IGNORECASE,
        ) or re.search(
            r"(?:note|file)\s+(?:called|titled|named)\s+([^\s]+).*?(?:saying|body|:)\s+(.+)",
            user,
            re.IGNORECASE,
        )
        if m:
            cands.append(
                (
                    m.start(),
                    ToolCall(
                        "call_write",
                        "write_file",
                        {
                            "path": m.group(1).strip("'\""),
                            "content": m.group(2).strip(),
                        },
                    ),
                )
            )

    if "run_command" in tool_names and (
        "run " in low or "exec" in low or "shell" in low
    ):
        m = re.search(
            r"(?:run|exec(?:ute)?)\s+(?:the\s+command\s+)?[`'\"]?(.+?)[`'\"]?$",
            user,
            re.IGNORECASE,
        )
        if m:
            cands.append(
                (
                    m.start(),
                    ToolCall(
                        "call_cmd", "run_command", {"command": m.group(1).strip()}
                    ),
                )
            )

    if "research" in tool_names:
        m = re.search(r"look up|research|find out|search", low)
        if m:
            task = re.sub(
                r"^.*?(?:look up|research|find out|search for|search)\s+",
                "",
                user,
                flags=re.IGNORECASE,
            )
            cands.append(
                (
                    m.start(),
                    ToolCall(
                        "call_research", "research", {"task": task.strip() or user}
                    ),
                )
            )

    cands.sort(key=lambda pair: pair[0])
    intents = [tc for _, tc in cands]

    # search_notes is the fallback lookup tool (used inside the research subagent):
    # if nothing more specific matched and it's available, search the notes.
    if not intents and "search_notes" in tool_names:
        intents.append(ToolCall("call_notes", "search_notes", {"query": user}))
    return intents


def _mock_final(transcript: Transcript, intents: list[ToolCall]) -> str:
    """Compose the final answer from every tool result, in intent order — so a
    lookup-then-compute request reports BOTH the lookup and the computation."""
    results: dict[str, str] = {}
    for e in transcript:
        if e.get("role") == "tool":
            results[e.get("name", "")] = e.get("content", "")
    parts: list[str] = []
    for tc in intents:
        r = results.get(tc.name)
        if r is None:
            continue
        if tc.name == "calculator":
            parts.append(f"That works out to {r}.")
        elif tc.name == "read_file":
            parts.append(f"The file contains: {r}")
        elif tc.name == "write_file":
            parts.append(f"Done — wrote {r}.")
        else:  # research / search_notes already phrase a full answer
            parts.append(r)
    return " ".join(parts) if parts else "I don't have a tool that fits that request."


def _mock_turn(system: str, transcript: Transcript, tools: list) -> Turn:
    tool_names = {t.name for t in tools}
    intents = _detect_intents(_last_user(transcript), tool_names)
    already_called = {
        c.name
        for e in transcript
        if e.get("role") == "assistant"
        for c in (e.get("tool_calls") or [])
    }
    for tc in intents:  # issue the next un-run intent — this is what chains steps
        if tc.name not in already_called:
            return Turn(text=None, tool_calls=[tc])
    return Turn(text=_mock_final(transcript, intents), tool_calls=[])


# ---------------------------------------------------------------------------
# Real providers — created lazily; translate the neutral transcript to each
# provider's tool-calling shape (the same normalization as the Agents dive).
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _openai_client():
    from openai import OpenAI

    return OpenAI()


@lru_cache(maxsize=1)
def _anthropic_client():
    import anthropic

    return anthropic.Anthropic()


def _openai_messages(system: str, transcript: Transcript) -> list[dict]:
    msgs: list[dict] = [{"role": "system", "content": system}]
    for e in transcript:
        if e["role"] == "user":
            msgs.append({"role": "user", "content": e["content"]})
        elif e["role"] == "assistant":
            m: dict = {"role": "assistant", "content": e.get("text")}
            if e.get("tool_calls"):
                m["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.name,
                            "arguments": json.dumps(c.arguments),
                        },
                    }
                    for c in e["tool_calls"]
                ]
            msgs.append(m)
        elif e["role"] == "tool":
            msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": e["tool_call_id"],
                    "content": e["content"],
                }
            )
    return msgs


def _claude_messages(system: str, transcript: Transcript) -> list[dict]:
    msgs: list[dict] = []
    pending_results: list[dict] = []

    def flush_results():
        nonlocal pending_results
        if pending_results:
            msgs.append({"role": "user", "content": pending_results})
            pending_results = []

    for e in transcript:
        if e["role"] == "user":
            flush_results()
            msgs.append({"role": "user", "content": e["content"]})
        elif e["role"] == "assistant":
            flush_results()
            blocks: list[dict] = []
            if e.get("text"):
                blocks.append({"type": "text", "text": e["text"]})
            for c in e.get("tool_calls", []):
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": c.id,
                        "name": c.name,
                        "input": c.arguments,
                    }
                )
            msgs.append({"role": "assistant", "content": blocks})
        elif e["role"] == "tool":
            pending_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": e["tool_call_id"],
                    "content": e["content"],
                }
            )
    flush_results()
    return msgs


def run_turn(system: str, transcript: Transcript, tools: list) -> Turn:
    """Run one assistant turn and normalize the result to a Turn."""
    ensure_ready()
    p = provider_name()
    if p == "mock":
        return _mock_turn(system, transcript, tools)

    if p == "openai":
        schema = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]
        resp = _openai_client().chat.completions.create(
            model=_OPENAI_CHAT,
            messages=_openai_messages(system, transcript),  # type: ignore[arg-type]
            tools=schema or None,  # type: ignore[arg-type]
        )
        msg = resp.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            if tc.type != "function":
                continue
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        return Turn(text=msg.content, tool_calls=calls)

    if p == "claude":
        schema = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in tools
        ]
        resp = _anthropic_client().messages.create(
            model=_CLAUDE_CHAT,
            max_tokens=1024,
            system=system,
            messages=_claude_messages(system, transcript),  # type: ignore[arg-type]
            tools=schema,  # type: ignore[arg-type]
        )
        calls, text_parts = [], []
        for block in resp.content:
            if block.type == "tool_use":
                calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                )
            elif block.type == "text":
                text_parts.append(block.text)
        return Turn(text="".join(text_parts) or None, tool_calls=calls)

    raise ValueError(f"Unknown PROVIDER={p!r}.")
