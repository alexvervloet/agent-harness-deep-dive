"""
harness/graph.py — orchestration as a graph: nodes, routing, cycles.
====================================================================

The harness loop lets the *model* drive: it picks the next step. But a lot of
orchestration is the opposite — the path IS knowable, and you want *code* to drive
it: classify a ticket, route it to the right handler, run a quality gate, loop back
to revise if it fails, then send. That's a **graph**: nodes (units of work) wired
by edges, with conditional routing and cycles. It's the model behind LangGraph and
every "agent workflow" builder.

This is a tiny one. A **node** is a function `state -> state` (it can run plain
code, call a tool, or run a whole Harness — the graph doesn't care what's inside).
Edges connect nodes; a **router** picks the next node from the current state, which
is what gives you branching and loops. `END` stops the graph.

When to reach for this vs. the agent loop: if you can draw the flowchart, build a
graph — it's cheaper, predictable, and testable (the "workflow vs. agent" call from
the Agents dive, made concrete). Reach for the model-driven loop only when the path
genuinely can't be known up front. Real systems mix both: graph nodes that each run
an agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

END = "__end__"

# A node transforms the shared state dict; a router reads it and names the next node.
Node = Callable[[dict], dict]
Router = Callable[[dict], str]


@dataclass
class Graph:
    """A directed graph of nodes with conditional routing and cycles."""

    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, str] = field(default_factory=dict)  # unconditional next
    routers: dict[str, Router] = field(default_factory=dict)  # state -> next node

    def node(self, name: str, fn: Node) -> "Graph":
        self.nodes[name] = fn
        return self

    def edge(self, frm: str, to: str) -> "Graph":
        """An unconditional edge: after `frm`, always go to `to`."""
        self.edges[frm] = to
        return self

    def route(self, frm: str, router: Router) -> "Graph":
        """A conditional edge: after `frm`, call `router(state)` to pick the next
        node (return END to stop). This is where branching and cycles come from."""
        self.routers[frm] = router
        return self

    def run(
        self, start: str, state: dict, *, max_visits: int = 50
    ) -> tuple[dict, list[str]]:
        """Execute from `start` until a node routes to END (or `max_visits` guards
        against a runaway cycle). Returns the final state and the path taken."""
        current = start
        path: list[str] = []
        for _ in range(max_visits):
            if current == END:
                break
            if current not in self.nodes:
                raise KeyError(f"no such node: {current!r}")
            state = self.nodes[current](state) or state
            path.append(current)
            if current in self.routers:
                current = self.routers[current](state)
            elif current in self.edges:
                current = self.edges[current]
            else:
                current = END
        return state, path
