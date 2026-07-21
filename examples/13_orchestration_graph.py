"""
Example 13: orchestration as a graph: routing, branching, and a cycle.

The agent loop lets the MODEL choose the next step. When the path is knowable, you
often want CODE to choose it instead: a graph of nodes wired by conditional edges.
This example builds a support-ticket workflow with `harness/graph.py`:

    classify ─▶ (route by category) ─▶ handler ─▶ review ─▶ (route)
                                                    ▲            │ pass -> send (END)
                                                    └── revise ──┘ fail -> revise, loop

Two things a plain loop doesn't give you cleanly: **branching** (a billing ticket
and a technical ticket visit different handler nodes) and a **cycle** (a draft that
fails review loops back through `revise` until it passes). We run two different
tickets and print the path each one takes; the path depends on the state.

A node here is plain deterministic code, but a node can just as well run a whole
Harness (an agent as one step of the graph). The graph owns the control flow; what's
inside a node is up to you.

Offline and deterministic. Run:

    python examples/13_orchestration_graph.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from harness import END, Graph, describe, ensure_ready

load_dotenv()
ensure_ready()
print(f"Provider: {describe()}\n")

# A tiny keyword classifier: one node's worth of work.
_HINTS = {
    "billing": ["refund", "charge", "invoice", "plan", "pay"],
    "account": ["password", "login", "sign in", "member", "team"],
    "technical": ["error", "crash", "export", "load", "bug", "save"],
}


def classify(state: dict) -> dict:
    text = state["ticket"].lower()
    state["category"] = next(
        (c for c, ws in _HINTS.items() if any(w in text for w in ws)), "general"
    )
    return state


def handle(state: dict) -> dict:
    # A handler drafts a reply for its category (a terse first draft). We register
    # this under one node PER category, so the path shows which handler ran.
    state["reply"] = f"({state['category']}) Thanks for reaching out, here's help."
    return state


CATEGORIES = ["billing", "account", "technical", "general"]


def review(state: dict) -> dict:
    # A quality gate: a complete reply must be marked resolved.
    state["ok"] = "[resolved]" in state["reply"]
    return state


def revise(state: dict) -> dict:
    state["attempts"] = state.get("attempts", 0) + 1
    state["reply"] += " Follow these steps and it's [resolved]."
    return state


def route_after_review(state: dict) -> str:
    if state["ok"]:
        return "send"
    if state.get("attempts", 0) >= 2:
        return "escalate"
    return "revise"  # the cycle: back through revise -> review


def send(state: dict) -> dict:
    state["outcome"] = "sent"
    return state


def escalate(state: dict) -> dict:
    state["outcome"] = "escalated to a human"
    return state


graph = (
    Graph()
    .node("classify", classify)
    .node("review", review)
    .node("revise", revise)
    .node("send", send)
    .node("escalate", escalate)
    .route(
        "classify", lambda s: f"handle_{s['category']}"
    )  # BRANCH: one handler per category
    .route("review", route_after_review)  # branch: send / revise / escalate
    .edge("revise", "review")  # cycle back to the gate
    .edge("send", END)
    .edge("escalate", END)
)
# One handler node per category, each flowing into the review gate.
for _cat in CATEGORIES:
    graph.node(f"handle_{_cat}", handle).edge(f"handle_{_cat}", "review")

for ticket in [
    "I want a refund on my last charge",
    "the page throws an error when I export",
]:
    final, path = graph.run("classify", {"ticket": ticket})
    print(f"Ticket: {ticket!r}")
    print(f"  category: {final['category']}")
    print(f"  path:     {' -> '.join(path)}")
    print(f"  outcome:  {final['outcome']}\n")

print(
    "Each ticket took a path decided by CODE, not the model: classify routed by\n"
    "category, and the review gate looped back through `revise` (a cycle) until the\n"
    "draft passed, then routed to `send`. That's graph orchestration: nodes, edges,\n"
    "conditional routing, cycles. Reach for it when you can draw the flowchart (it's\n"
    "cheaper, predictable, and testable); reach for the agent loop only when the path\n"
    "genuinely can't be known up front. Real systems mix them: a graph whose nodes\n"
    "each run a Harness."
)
