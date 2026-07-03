# Agent Harnesses — A Guided Deep Dive

A hands-on playground for the part of agent work the Agents dive left off: once
you've hand-written the loop, most real agent engineering is building **on a
harness** — the layer that runs the loop for you and adds subagents, hooks,
permission policies, sandboxed tool execution, headless automation, durable
(checkpointed, resumable) runs, and orchestration (parallel workers, mid-run
steering, and graph control flow). You'll build a small harness from scratch and
watch each of those primitives appear as a thin wrapper around the loop you know. No framework magic — just enough
code to *see* what a harness gives you, and to answer the interview question:
*"you have a working agent loop; when do you throw it away for the SDK, and what
does the SDK actually give you?"*

The twist that makes this repo work: it runs **completely offline on a mock
provider**, with no API key. The harness primitives — hooks, policies, sandboxing,
subagents, event streams — are all provider-neutral, so a deterministic rule-based
"model" is all you need to see every one of them work. Flip one env var and the
same harness drives a real OpenAI or Claude model.

This is a **bonus dive**, and it's the direct sequel to
[Agents](https://github.com/Ailuue/agents-deep-dive) (#6): that dive builds the
loop; this one builds the layer above it. It also connects to
[Prompt Injection](https://github.com/Ailuue/prompt-injection-deep-dive) (hooks
and the sandbox are where guardrails live) and
[Context Engineering](https://github.com/Ailuue/context-engineering-deep-dive)
(subagents give each agent its own window). Its code depends on none of them.

Like its siblings, it's meant to be *walked through*. Each section ends with
something to run, and **every section runs offline and free** on the mock.
[EXERCISES.md](EXERCISES.md) has a predict-then-run prompt for each one.

---

## 0. The one big idea

> **A harness is the agent loop, wrapped — so instead of writing the loop you
> configure it and consume its event stream. That wrapper is where subagents,
> hooks, permission policies, the sandbox, durable checkpoints, and orchestration
> (parallel workers, mid-run steering, graph control flow) live. In 2026, most
> agent work is building on a harness, not hand-rolling the loop.**

That's the whole repo. The Agents dive proved the loop is ~20 lines. But a
*production* loop needs a place to gate a dangerous call, a place to redact a
secret, a boundary on where tools act, a way to delegate, structured output you can
log and test, and a way to survive a crash mid-run. Bolt all of that into a bare
`while` loop and it stops being
readable. A harness lifts each concern out into its own seam. Everything below is
one of those seams — a small addition to the loop, not a new concept. Hold onto
that and none of this feels complicated.

---

## 1. Setup (5 minutes)

```bash
# 1. Create an isolated Python environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install dependencies (the default mock stack needs only python-dotenv + rich)
pip install -r requirements.txt

# 3. Copy the env file — the default runs keyless (no API key needed)
cp .env.example .env
#    (Real provider instead of the mock? Its key goes in your OS keychain,
#     not .env — see ../SECRETS.md — then run scripts as `secrun python ...`.)

# 4. Confirm everything is wired up (makes no API call, costs nothing)
python check_setup.py
```

No key required. The default `PROVIDER=mock` is a deterministic, in-process
tool-calling "model." Pick your stack with `PROVIDER` in `.env`:

| `PROVIDER` | What runs the model | Key needed | Cost |
|------------|---------------------|------------|------|
| `mock` (default) | a deterministic offline planner | **none** | **$0** |
| `openai` | OpenAI `gpt-4o-mini` | `OPENAI_API_KEY` | tiny |
| `claude` | Claude `claude-haiku-4-5` | `ANTHROPIC_API_KEY` | tiny |

The only file that knows which you picked is
[harness/providers.py](harness/providers.py). Everything above it — the harness,
hooks, policy, sandbox, subagents — is provider-neutral.

> 💡 **Why a mock is the right call here.** The subject is the harness, not the
> model. A rule-based planner that reliably asks for the tool each example is about
> lets you watch hooks fire, policies gate, and sandboxes refuse — deterministically,
> offline, for $0. Real models make the same kinds of requests, just less predictably.

---

## 2. The bare loop, and what it's missing

```bash
python examples/01_bare_loop_recap.py        # offline
```

Here's the Agents-dive loop again, in ~15 lines, driving the mock. It works — and
that's the point: it works, but it's naked. There's no structured way to observe
it (just `print`), nowhere to gate a `write_file`, nowhere to block a call or
redact a result, no boundary on where a tool acts, and no way to delegate. The
example runs the loop, then names those five gaps. The rest of the dive fills them.

---

## 3. The harness: the loop, wrapped

```bash
python examples/02_harness_events.py
```

Hand the same task to a `Harness` and stop writing loops. You configure it, then
iterate its **event stream** — one typed event per thing that happens
([harness/events.py](harness/events.py)). The `while` is gone from your code; it's
inside `Harness.run()`. That inversion is the reason a harness is worth adopting:
every event is a seam to observe, react, or record. The next three examples slot
capabilities into those seams without touching the loop.

---

## 4. Hooks — intercept without editing the loop

```bash
python examples/03_hooks.py
```

A hook is a function the harness calls at a fixed point in every tool cycle.
**Pre-tool** runs before a tool (return a substitute result, or raise `HookBlock`
to refuse). **Post-tool** runs after (transform the result before it re-enters the
model's context — the natural home for redaction). The example blocks reads of
credential-looking files with a pre-tool hook and redacts an API key that slips
through a file's contents with a post-tool hook — the model and your logs never see
the raw secret. This is where the [Prompt Injection](https://github.com/Ailuue/prompt-injection-deep-dive)
dive's defenses live in a real system: at the harness seam, not re-implemented in
every tool.

---

## 5. Permission policies — allow / ask / deny

```bash
python examples/04_permissions.py
```

The Agents dive gated dangerous tools with an `approve` callback tangled into the
loop. A harness makes the *policy* a declarative object
([harness/policy.py](harness/policy.py)) you read, diff, version, and swap per
environment. Three verdicts: **allow** (run it), **ask** (pause for a human),
**deny** (never). The example allows the calculator, asks before `write_file`, and
denies `run_command` — and the agent adapts when a call is denied, because a denial
comes back as just another tool result. This is the shape of Claude Agent SDK
permission modes and Managed Agents' per-tool `always_allow` / `always_ask` config.

---

## 6. The sandbox — the boundary tools execute inside

```bash
python examples/05_sandbox.py
```

The model chose the arguments, and it may be acting on attacker-controlled text.
So tool execution needs a boundary the model can't argue past
([harness/sandbox.py](harness/sandbox.py)). Two reject-by-default boundaries: a
**path jail** (every file path is resolved and must stay under the workspace root —
`../../etc/passwd` is refused) and a **command allowlist** (only named executables
run). The example reads a legit file, then watches a directory-traversal escape and
a non-allowlisted command get refused *as tool results*, so the agent adapts. Real
harnesses sandbox far harder — containers, seccomp, egress rules, a provider-hosted
per-session workspace — but it's the same contract: the model proposes, the sandbox
disposes.

---

## 7. Subagents — delegate with an isolated context

```bash
python examples/06_subagents.py
```

The Agents dive showed a subagent as "a tool whose function runs its own loop." A
harness makes it first-class: register a `Subagent` (its own persona and toolset)
and it appears to the model as an ordinary tool. When called, the harness spawns a
**nested harness** — a fresh context window with only that subagent's tools — runs
it, and returns just the final answer. The payoff is **context isolation**: the
orchestrator's window never fills with the subagent's intermediate steps. The
example has an arithmetic-only orchestrator delegate a lookup to a `research`
subagent that owns the knowledge-base tool; the nested run appears indented in the
stream. Scale this up and it's how large agent systems are built.

---

## 8. Headless automation — one-shot, scriptable, structured

```bash
python examples/07_headless.py
python examples/07_headless.py "What is 19 * 21?"
```

The other way to run an agent — the one job descriptions call "agentic automation"
— is **headless**: no human, kicked off by cron or CI, emitting structured output
another program consumes. Because everything is events, you fold a run into a
machine-readable record as it happens. The example runs a task with no interaction
and prints a JSON summary — the shape you'd write to a log, post to a webhook, or
assert on in CI (fail the build if a `blocked` tool shows up).

---

## 9. Computer use & hosted sandboxes

```bash
python examples/08_computer_use.py        # offline simulation of the pattern
```

Computer use is the same loop with a different tool surface: the tools are
`screenshot` / `click` / `type`, and the observation fed back each step is an image
of a screen. Observe → act → observe, exactly as before. The example is a
self-contained *simulation* of that loop (a mock login form, a scripted planner
standing in for a vision model) so you see the shape offline. Two things a harness
adds here: the same permission and hook seams (gate a click on a payment page,
redact a typed password), and a **hosted sandbox** — a provider-run VM or browser,
so the agent drives an isolated machine, never your laptop. Reach for computer use
only when the task lives in a GUI with no API; a real tool/API is cheaper and far
more reliable than driving pixels.

---

## 10. Durable runs — checkpoint, crash, resume

```bash
python examples/09_checkpoint_resume.py        # offline
```

A long-horizon agent runs for minutes or hours; if the process dies mid-run (a
deploy, an OOM kill, a timeout, a reboot), an in-memory loop loses everything and
starts over, re-paying for every step it already finished. A harness **checkpoints**
instead: it persists its state after each step and can **resume** in a fresh process,
redoing nothing. The elegant part — the harness's own **transcript** is the
checkpoint. Because every tool result is fed back into it, persisting the transcript
is all it takes ([harness/checkpoint.py](harness/checkpoint.py)); reload it and keep
looping, and the model, seeing the results already there, moves on. The example runs
a two-step task, lets "process 1" crash after the first tool, and has a brand-new
"process 2" resume — a counter proves each tool runs exactly once across both. Real
systems (LangGraph checkpointers, Temporal-style durable workflows, Managed Agents'
server-side sessions) do the same with a database instead of a JSON file.

---

## 11. Durable task state — a queryable run log

```bash
python examples/10_run_records.py        # offline
```

The same persisted state gives you the other half for free: a **task-state log** you
can query. Each run carries a status through its lifecycle — `queued` → `running` →
`done`, or `failed` (gave up), or stuck in `running` (crashed mid-run). Because every
run is a file on disk, you can list them all: which finished, which are still going,
and which crashed and need resuming — exactly what a job queue, a cron dashboard, or
Managed Agents' deployment-run records give you. The example runs three jobs (one
completes, one is capped so it fails, one crashes), prints the durable log, and
resumes the crashed one straight from it. That status column is the difference
between an agent you *hope* finished and one you can *prove* did.

---

## 12. Parallel subagents — fan out, then join

```bash
python examples/11_parallel_subagents.py        # offline
```

Example 07 delegated to *one* subagent, and they run one at a time. But a lot of
agent work is **independent** — research five topics, review ten files — and running
that serially wastes wall-clock: the batch should cost the *slowest* worker, not the
*sum*. `fan_out` ([harness/orchestrate.py](harness/orchestrate.py)) is the
coordinator's map step: hand it a list of `(subagent, task)` workers and it runs them
concurrently, each in its own harness and context window, returning every result for
you to aggregate (the reduce). The example times the same batch serial vs concurrent
and shows the concurrent run finishing in about one worker's time (~3× here). Keep
parallel workers independent and read-mostly (they share the sandbox); for dependent
steps, delegate serially. This is the from-scratch shape of LangGraph parallel
branches or a Managed Agents multiagent coordinator.

---

## 13. Steering a running agent — inject and interrupt

```bash
python examples/12_steering.py        # offline
```

The permission policy (§5) gates a tool *before* it runs. **Steering** is the other
half of operator control — acting on a run *while it's in flight*. The harness polls
a **controller** ([harness/steer.py](harness/steer.py)) at each step boundary, so you
can **inject** a message that changes the next step ("actually, only Pro") without
restarting, **queue** follow-ups processed in order, and **interrupt** — stop the run
at a safe boundary instead of killing it mid-tool. The example injects a follow-up
that redirects the agent, then interrupts it cleanly; an interrupted run is
checkpointed as `interrupted` (resumable), not lost. A real app drives the live
`QueueController` (`steer()` / `interrupt()` from a UI or chat bridge); this is the
from-scratch shape of Managed Agents' message queue + `user.interrupt`.

---

## 14. Orchestration as a graph — routing, branching, cycles

```bash
python examples/13_orchestration_graph.py        # offline
```

The loop lets the *model* choose the next step; when the path is knowable, you want
*code* to choose it — a **graph** of nodes wired by conditional edges
([harness/graph.py](harness/graph.py)). The example builds a support-ticket workflow:
`classify` routes each ticket to a per-category handler (**branching** — a billing
and a technical ticket visit different nodes), a `review` gate loops back through
`revise` until the draft passes (**a cycle**), then routes to `send`. A node is just
`state -> state`, so it can run plain code *or* a whole Harness — the graph owns the
control flow, not what's inside a node. This is the "workflow vs. agent" call from
the Agents dive made concrete, and the model behind LangGraph: if you can draw the
flowchart, build a graph (cheaper, predictable, testable); reach for the model-driven
loop only when the path genuinely can't be known up front.

---

## The capstone: `agent_harness.py`

Everything assembled into a harness you can drive: a real permission policy
(`write_file` asks, `run_command` is denied), a sandboxed workspace with a command
allowlist, a redaction post-tool hook, a `research` subagent, durable checkpointing,
and a choice of live event trace or headless JSON.

```bash
# One-off task with a live event trace (offline on the mock): the agent delegates
# the lookup to the research subagent, THEN computes with the calculator — a real
# two-step chain, and the final answer reports both.
python hands_on/agent_harness.py "Look up the plans and prices, then compute a year of Pro (30 * 12)."

# Auto-approve the `ask` tools (non-interactive):
python hands_on/agent_harness.py "write file todo.txt containing: ship it" --yes

# Headless: emit a JSON record instead of a trace (for CI / cron):
python hands_on/agent_harness.py "What is (23 * 47) + 100?" --json

# Durable: checkpoint under an id; re-run with the same id to RESUME a crashed run.
python hands_on/agent_harness.py "read the file plan.txt and compute (2 + 2)." --run-id job1
```

Read [hands_on/agent_harness.py](hands_on/agent_harness.py): it's just the library
composed — `build_agent()` wires policy + sandbox + hook + subagent, and the main
loop consumes the event stream. **Suggested exercise:** add a second subagent (say
a `math` specialist), or tighten the policy to `deny` `write_file` outright, and
watch the trace change. Adding a capability is: register it, and the harness routes
to it.

---

## When do you throw away your loop for the SDK?

The honest answer, and the one to give in an interview:

- **Write the loop by hand when** the agent is simple (a few tools, one context),
  you need to understand exactly what happens, or you're learning. The loop is ~20
  lines; a dependency and its concepts cost more than that.
- **Adopt a harness/SDK when** you need any of the seams this dive built —
  gated tools, hooks/guardrails, a real sandbox, subagents, structured headless
  output, durable/resumable runs, or orchestration (parallel workers, mid-run
  steering, graph control flow) — *and especially* when you'd otherwise
  reimplement them badly.
  A harness is a pile of hard, security-sensitive code (sandboxing, permission
  prompts, event plumbing, reconnection, streaming) that someone else has hardened.
- **What the SDK gives you** that this toy doesn't: a real sandbox (containers, not
  a path check), provider-hosted per-session workspaces, robust streaming and
  reconnection, subagent orchestration, permission UIs, and headless run records —
  the productionized version of every seam here.

The two named options in the Claude world: the **Claude Agent SDK** (you host the
compute, the SDK runs the loop and gives you hooks, subagents, permission modes,
sandboxing) and **Managed Agents** (Anthropic hosts the loop *and* a per-session
container where tools execute). OpenAI's Agents SDK is the equivalent on that
stack. All of them are this dive's harness, hardened and hosted.

---

## Where to go next

You've built a harness from scratch. The frontier is more of the same seams, harder:

- **A real sandbox** — swap the path jail for a container or microVM with seccomp,
  read-only mounts, and network egress rules; or use a provider-hosted sandbox.
- **Richer permission policies** — per-argument rules (allow `read_file` anywhere
  but `write_file` only under `/tmp`), rate limits, and budgets per run.
- **Harder durable execution** — §10–11 checkpoint to a JSON file and resume; the
  frontier is a DB-backed durable-workflow engine (idempotent, exactly-once replay
  even across a mid-tool crash), and reconnecting a dropped event stream without
  losing events.
- **Deeper orchestration** — §12–14 fan out to parallel workers, steer a run mid-
  flight, and route with a graph. The frontier: hierarchical multi-level delegation,
  agent-to-agent messaging, backpressure and concurrency limits across many workers,
  and graph engines with persistence and streaming baked in (LangGraph, Managed
  Agents' multiagent coordinator).
- **Provider-hosted tools & agents** — web search, code execution, and computer use
  run by the provider; and fully managed agents where you never run the loop.
- **Evaluating harness behavior** — score trajectories (right tools, right order, no
  denied-then-retried loops) with the
  [Evals dive](https://github.com/Ailuue/evals-deep-dive), not just final answers.

---

## From teaching code to production

The shortcuts that make this repo readable and free are exactly what a real harness
replaces:

| This repo's teaching shortcut | In production |
|-------------------------------|---------------|
| Sandbox is a path check + command allowlist | A **container / microVM** with seccomp, read-only mounts, and egress rules — or a provider-hosted sandbox |
| Hooks are in-process Python functions | A **guardrail pipeline** (input/output classifiers, PII redaction, injection detection) wired at the same seam |
| Permission policy is a dict of verdicts | A **policy engine** with per-argument rules, budgets, rate limits, and an audit log of every decision |
| Subagents share one process; `fan_out` uses a thread pool | **Isolated workers** with their own resource limits, backpressure/concurrency caps, and a coordinator that survives a crash |
| Steering is an in-process controller; the graph is plain Python | A **durable message queue** (steer/interrupt across processes) and a **graph engine** with persistence, streaming, and observability baked in |
| Events are printed | A **structured trace** (a span per step) shipped to observability, plus durable run records |
| Checkpoint is a JSON file per run | A **durable-execution engine** — DB- or workflow-backed state, idempotent exactly-once replay even across a mid-tool crash (Temporal-style), or a provider's server-side sessions |
| The mock (or one model) is hard-wired | A **model router** with fallbacks, retries, and cost/latency budgets per run |
| Headless run is a script | A **queue/worker** with retries, idempotency, and a webhook or eval gate on the result |

These are right for learning and wrong for production. The general ops machinery —
observability, cost, reliability, caching, guardrails, prompt versioning, eval
gates — is built from scratch and wired into one running app in
**[Production](https://github.com/Ailuue/ai-in-production-deep-dive)** (#8), which
also runs offline on a mock provider.

---

## File map

```
check_setup.py              ← run first: verifies Python, packages, provider
README.md                   ← this guide
EXERCISES.md                ← predict-then-run prompts, one per section
harness/                    ← the from-scratch harness library (read it!)
  providers.py              ← the ONLY provider file: mock (default) + openai + claude
  tools.py                  ← what a tool is + a sandboxed toolbox
  sandbox.py                ← the boundary tools run inside (path jail + command allowlist)
  policy.py                 ← declarative allow / ask / deny permission policy
  events.py                 ← the typed event stream the harness emits
  checkpoint.py             ← durable run state: persist the transcript, resume after a crash
  steer.py                  ← steering controllers: inject / queue / interrupt a running run
  orchestrate.py            ← fan out to many subagents concurrently, then join (map-reduce)
  graph.py                  ← orchestration as a graph: nodes, conditional routing, cycles
  core.py                   ← the Harness: loop + hooks + policy + sandbox + subagents + checkpointing + steering
hands_on/
  agent_harness.py          ← capstone: a configured harness CLI (trace / headless JSON / --run-id resume)
examples/
  01_bare_loop_recap.py     ← the bare loop and its five missing pieces (offline)
  02_harness_events.py      ← the same task via the harness's event stream (offline)
  03_hooks.py               ← pre-tool block + post-tool redaction (offline)
  04_permissions.py         ← allow / ask / deny policy (offline)
  05_sandbox.py             ← path jail + command allowlist, escapes refused (offline)
  06_subagents.py           ← delegate to a nested harness with its own context (offline)
  07_headless.py            ← one-shot scriptable run → JSON record (offline)
  08_computer_use.py        ← the loop pointed at a screen; hosted sandboxes (offline sim)
  09_checkpoint_resume.py   ← durable runs: checkpoint, crash, resume without redoing work (offline)
  10_run_records.py         ← durable task state: a queryable queued/running/done/failed log (offline)
  11_parallel_subagents.py  ← fan out to many workers concurrently, then join (offline)
  12_steering.py            ← inject / interrupt a running agent mid-run (offline)
  13_orchestration_graph.py ← routing, branching, and cycles as a graph (offline)
```

(`workspace/` and `runs/` are created by the examples and are git-ignored.)

---

## Troubleshooting

Run `python check_setup.py` first — it catches most problems. Then, by symptom:

| What you see | What it means / the fix |
|--------------|-------------------------|
| `ModuleNotFoundError` (dotenv / rich) | Deps aren't installed or the venv isn't active. `source .venv/bin/activate` then `pip install -r requirements.txt`. |
| `PROVIDER=... needs ... in the environment` | You switched to a real provider without a key. Load it from your keychain with `secrun` (see [SECRETS.md](../SECRETS.md)), or go back to `PROVIDER=mock`. |
| A tool ran that I expected to be blocked | Check the policy verdict *and* your hooks — `deny` blocks outright; `ask` runs if your `approve` callback returns True (the capstone's `--yes` auto-approves `ask`, but never overrides `deny`). |
| "escapes the sandbox" on a path I meant | Working as intended — the jail resolves `..` and symlinks and refuses anything outside the root. Use a relative path inside `workspace/`. |
| The mock takes one step where I expected several | The deterministic planner does one tool per turn for clarity; a real model may chain more. Switch `PROVIDER` to see it. |
| `SyntaxError` / odd type errors on startup | You're likely on Python 3.9 or older; this repo needs 3.10+. `check_setup.py` confirms your version. |

Still stuck? Every file is small and self-contained — open it, read the docstring
at the top, and run it directly. [harness/core.py](harness/core.py) is the whole
story: the loop, wrapped.

---

## The series

This is one of the standalone, hands-on deep dives into building with LLM APIs —
eight core, plus the bonus dives. Each stands on its own — its own setup, examples,
and capstone — and they share one house style: provider-agnostic where it makes
sense, built from scratch (no frameworks), offline-first examples, and a real
capstone. Do them in any order; this sequence builds naturally:

1. [OpenAI API](https://github.com/Ailuue/openai-api-deep-dive) — the API from zero
2. [Claude API](https://github.com/Ailuue/claude-api-deep-dive) — the same ideas, the Anthropic way
3. [Prompt Engineering](https://github.com/Ailuue/prompt-engineering-deep-dive) — shape model behavior with better prompts
4. [RAG](https://github.com/Ailuue/rag-deep-dive) — answer questions over your own documents
5. [Evals](https://github.com/Ailuue/evals-deep-dive) — measure whether a change actually helps
6. [Agents](https://github.com/Ailuue/agents-deep-dive) — give a model tools and a loop so it can act
7. [Prompt Injection & Guardrails](https://github.com/Ailuue/prompt-injection-deep-dive) — attack and defend all of the above
8. [Production](https://github.com/Ailuue/ai-in-production-deep-dive) — operate one app end to end

**Bonus dives** — standalone, slotting in where they're most useful:

- [Agent Harnesses](https://github.com/Ailuue/agent-harness-deep-dive) — build on the loop: hooks, permissions, sandboxing, subagents, headless
- [Context Engineering](https://github.com/Ailuue/context-engineering-deep-dive) — manage what's in the window
- [Multimodal](https://github.com/Ailuue/multimodal-deep-dive) — images & audio, not just text
- [Realtime Voice](https://github.com/Ailuue/realtime-voice-deep-dive) — low-latency speech-to-speech agents
- [Fine-tuning](https://github.com/Ailuue/fine-tuning-deep-dive) — teach a model new behavior by example
- [MCP](https://github.com/Ailuue/mcp-deep-dive) — serve tools, data & prompts over a standard protocol
- [Local Models](https://github.com/Ailuue/local-models-deep-dive) — run open-weight models on your own machine

**Agent Harnesses is a bonus dive.** It slots directly after
[Agents](https://github.com/Ailuue/agents-deep-dive) (#6) — that dive builds the
loop; this one builds the layer you run it on.
