"""
harness/review.py: let a reviewer answer the `ask` prompts, and know when to stop.

Section 5's `ask` verdict pauses for a person. People turn out to be a weak check.
In Anthropic's study of Claude Code auto mode (reported 2026-08), testers caught a
deliberately inserted dangerous command 13.6% of the time, the classifier blocked
89% of the same commands, and users approved 97% of the permission prompts they
saw. A prompt someone approves without reading is not a safeguard.

So the fourth option is a reviewer: something that reads each `ask` call against
the user's task and says allow or block. Two rules keep it honest:

  1. A block carries a reason, and the agent sees it. "Blocked: [Code from the
     Internet]" gives the agent something to work with; a bare "no" doesn't.
  2. A reviewer that keeps saying no is a signal, not a solution. After 3 blocks in
     a row, or 20 in a session, stop and ask a person. Approving that prompt hands
     control back to the reviewer. (These are Claude Code's thresholds, from its
     permission-modes docs.)

`ClassifierApprover` is just an `approve` callback, so the loop doesn't change.
`rule_review` is an offline stand-in: a few patterns for clearly dangerous calls.
`model_review` asks the configured model, which can also judge the thing rules
can't: whether this call is what the user actually asked for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .providers import ToolCall, run_turn

Verdict = tuple[str, str]  # ("allow" | "block", reason)

# The offline stand-in. Real classifiers read meaning; these read strings, so they
# miss anything phrased differently. That gap is the reason model_review exists.
_RULES = [
    (r"(curl|wget)\b[^|]*\|\s*(ba)?sh", "[Code from the Internet] downloads and runs a script"),
    (r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r", "[Irreversible Deletion] recursive force delete"),
    (r"(\.ssh/|\.aws/|\.env\b|id_rsa|credentials)", "[Credential Access] touches secrets"),
    (r"(curl|wget)\b.*(-d|--data|-F|--upload-file)", "[Data Exfiltration] sends data out"),
]


def rule_review(call: ToolCall, task: str) -> Verdict:
    text = " ".join(str(v) for v in call.arguments.values())
    for pattern, reason in _RULES:
        if re.search(pattern, text, re.IGNORECASE):
            return "block", reason
    return "allow", "no rule matched"


_REVIEWER_SYSTEM = (
    "You review one tool call an AI agent wants to make. Reply with exactly one line: "
    "ALLOW, or BLOCK: <short reason>. Block anything destructive, anything that runs "
    "code fetched from the internet, anything that reads or sends secrets, and anything "
    "the user's request did not ask for. Allow ordinary actions that serve the request."
)


def model_review(call: ToolCall, task: str) -> Verdict:
    prompt = (
        f"The user asked: {task!r}\n"
        f"The agent wants to call {call.name} with {call.arguments!r}.\n"
        "ALLOW or BLOCK?"
    )
    reply = (run_turn(_REVIEWER_SYSTEM, [{"role": "user", "content": prompt}], []).text or "").strip()
    if reply.upper().startswith("ALLOW"):
        return "allow", reply
    # Anything that isn't a clear ALLOW is a block: an unparseable reviewer fails closed.
    return "block", reply.split(":", 1)[-1].strip() or "reviewer did not allow it"


@dataclass
class ClassifierApprover:
    """An `approve` callback that asks a reviewer first and a person when it should."""

    review: Callable[[ToolCall, str], Verdict]
    human: Callable[[ToolCall], bool]
    task: str = ""
    max_in_a_row: int = 3
    max_total: int = 20
    in_a_row: int = 0
    total: int = 0
    paused: bool = False  # True while a person is answering instead of the reviewer
    log: list[str] = field(default_factory=list)

    def __call__(self, call: ToolCall) -> tuple[bool, str]:
        if self.paused:
            approved = self.human(call)
            self.log.append(f"person: {'approved' if approved else 'denied'} {call.name}")
            if approved:  # approving the prompted action resumes review
                self.paused, self.in_a_row = False, 0
            return approved, "a person reviewed this action"
        verdict, reason = self.review(call, self.task)
        if verdict == "allow":
            self.in_a_row = 0
            self.log.append(f"reviewer: allowed {call.name}")
            return True, reason
        self.in_a_row += 1
        self.total += 1
        self.log.append(f"reviewer: blocked {call.name} ({reason})")
        if self.in_a_row >= self.max_in_a_row or self.total >= self.max_total:
            self.paused = True
            if self.total >= self.max_total:
                self.total = 0  # the session counter resets only when its own limit fires
            self.log.append("reviewer keeps blocking: handing the next decision to a person")
        return False, f"Blocked by the reviewer: {reason}"
