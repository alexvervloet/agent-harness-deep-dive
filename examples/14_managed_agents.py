"""
Example 14: Managed Agents, or what it looks like when you own none of it.

This repo has spent thirteen examples building a harness: an event stream (§3),
hooks (§4), permission policies (§5), a sandbox (§6), subagents (§7), headless
runs (§8), checkpointing (§10), run records (§11), steering (§13). Every one of
those is a real piece of infrastructure that somebody has to run.

Managed Agents is Anthropic running all of it. You do not write the loop, you do
not host the container, and you do not persist the run. You describe an agent,
start a session, and read events off a stream. It is the far end of the axis
this dive has been walking:

    your own loop  ->  your own harness  ->  a harness you host  ->  hosted entirely
    (§2)               (§3-13)              (Claude Agent SDK)      (Managed Agents)

THE ONE STRUCTURAL RULE
    An **Agent** is a persisted, versioned config: model, system prompt, tools.
    A **Session** is one run of it. `model`/`system`/`tools` live on the agent,
    never on the session, and the session just points at it:

        agent   = client.beta.agents.create(...)        # ONCE, at setup
        session = client.beta.sessions.create(           # every run
            agent={"type": "agent", "id": agent.id, "version": agent.version},
            environment_id=env.id,
        )

    Calling `agents.create()` on every run is the mistake to avoid. It
    accumulates orphaned agents, pays creation latency per request, and throws
    away the versioning that is the entire reason agents are separate objects.
    Create once, store the id, reuse it. This is the hosted equivalent of not
    re-instantiating your harness inside the request handler.

WHAT MAPS TO WHAT
    | This dive                  | Managed Agents                          |
    |----------------------------|-----------------------------------------|
    | your event stream (§3)     | `sessions.events.stream()`              |
    | permission policies (§5)   | `always_allow` / `always_ask` per tool  |
    | the sandbox (§6)           | the session's container, Anthropic-run  |
    | subagents (§7)             | a `multiagent` roster on the agent      |
    | checkpoint/resume (§10)    | the session, which is durable already   |
    | run records (§11)          | deployment runs                         |
    | steering (§13)             | `user.message` / `user.interrupt` events|

    Reading that table is the point of the example. Nothing here is a new idea;
    it is the same list of problems with somebody else's answers plugged in.

WHAT YOU GIVE UP
    It is Anthropic's harness on Anthropic's infrastructure. You cannot reach
    into the loop the way §4's hooks let you, your tools execute in a container
    you do not own, and the whole thing is one vendor. That is a real trade, and
    it is worth making when the alternative is maintaining §3 through §13
    yourself, and a bad trade when your value is *in* that layer.

COSTS REAL MONEY, SO IT IS OPT-IN
    A session provisions a container and bills for running time plus tokens.
    This example therefore does nothing by default. Pass --real to provision an
    environment, an agent and a session, run one task, and clean all three up:

    python examples/14_managed_agents.py            # explain only, free
    secrun python examples/14_managed_agents.py --real   # provisions, then deletes
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

REAL = "--real" in sys.argv


def explain() -> None:
    print(__doc__.strip())
    print(
        "\n"
        "----------------------------------------------------------------------\n"
        "Nothing was provisioned. Re-run with --real (and a key, via secrun) to\n"
        "watch the flow actually execute:\n"
        "    secrun python examples/14_managed_agents.py --real\n"
    )


def run_for_real() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("--real needs ANTHROPIC_API_KEY (see ../SECRETS.md, run under secrun).")

    import anthropic

    client = anthropic.Anthropic()
    env = agent = session = None

    try:
        # 1. An environment is a reusable template for the container the agent's
        #    tools run inside. This is §6's sandbox, except you don't run it.
        env = client.beta.environments.create(
            name="deepdives-harness-demo",
            config={"type": "cloud", "networking": {"type": "unrestricted"}},
        )
        print(f"environment: {env.id}")

        # 2. The agent. Note what lives here and not on the session.
        agent = client.beta.agents.create(
            name="Harness Demo",
            model="claude-haiku-4-5",
            system="You are terse. Do exactly what is asked, then stop.",
            tools=[{"type": "agent_toolset_20260401"}],
        )
        print(f"agent:       {agent.id} (version {agent.version})")

        # 3. The session. It carries a POINTER to the agent, plus the kickoff.
        session = client.beta.sessions.create(
            agent={"type": "agent", "id": agent.id, "version": agent.version},
            environment_id=env.id,
            title="harness dive demo",
            initial_events=[
                {
                    "type": "user.message",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Write a file hello.txt containing the word hello, "
                                "then tell me you did it."
                            ),
                        }
                    ],
                }
            ],
        )
        print(f"session:     {session.id} ({session.status})")
        print(f"trace:       https://platform.claude.com/workspaces/default/sessions/{session.id}")
        print("\n--- the event stream (this is §3, hosted) ---")

        # 4. The stream. Compare examples/02_harness_events.py: same idea, same
        #    shape of consumer loop, except these events crossed a network.
        with client.beta.sessions.events.stream(session_id=session.id) as stream:
            for event in stream:
                if event.type == "agent.message":
                    for block in event.content:
                        if block.type == "text":
                            print(f"  agent: {block.text}")
                elif event.type == "agent.tool_use":
                    print(f"  tool:  {event.name}")
                elif event.type == "session.status_idle":
                    # Do NOT break on idle alone: a session goes idle whenever it
                    # is waiting on YOU (a tool confirmation, a custom tool
                    # result). Only a non-requires_action stop reason means done.
                    if event.stop_reason.type == "requires_action":
                        continue
                    print(f"  [idle: {event.stop_reason.type}]")
                    break
                elif event.type == "session.status_terminated":
                    print("  [terminated]")
                    break
    finally:
        # 5. Clean up. Sessions are disposable; agents and environments are not,
        #    which is exactly why you would normally KEEP the last two and reuse
        #    them. We delete here only because this is a demo.
        print("\n--- cleanup ---")
        for label, fn in (
            ("session", lambda: session and client.beta.sessions.delete(session_id=session.id)),
            ("environment", lambda: env and client.beta.environments.delete(env.id)),
            ("agent", lambda: agent and client.beta.agents.archive(agent.id)),
        ):
            try:
                fn()
                print(f"  {label} removed")
            except Exception as e:  # noqa: BLE001
                print(f"  {label} cleanup failed: {str(e)[:80]}")

        print(
            "\nNote which of those you would keep in a real system: the agent and\n"
            "the environment. Only the session is per-run. If your code creates\n"
            "all three every time, you have rebuilt the anti-pattern this example\n"
            "opened with."
        )


if __name__ == "__main__":
    if REAL:
        run_for_real()
    else:
        explain()
