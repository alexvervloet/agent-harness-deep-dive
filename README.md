# Agent Harnesses: A Guided Deep Dive

A hands-on playground for the part of agent work the Agents dive left off. Once you have
hand-written the loop, most real agent engineering happens on a harness, the layer that
runs the loop for you and adds subagents, hooks, permission policies, sandboxed tool
execution, headless automation, durable checkpointed and resumable runs, and orchestration
through parallel workers, mid-run steering, and graph control flow. You'll build a small
harness from scratch and watch each of those pieces appear as a thin wrapper around the
loop you already know. No framework magic, just enough code to see what a harness gives
you, and to answer the interview question: "you have a working agent loop, so when do you
throw it away for the SDK, and what does the SDK actually give you?"

Here is what makes this repo work. It runs completely offline on a mock provider, with no
API key. Hooks, policies, sandboxing, subagents, and event streams are all
provider-neutral, so a deterministic rule-based "model" is all you need to see every one of
them work. Flip one env var and the same harness drives a real OpenAI or Claude model.

This is a bonus dive and the direct sequel to
[Agents](https://github.com/alexvervloet/agents-deep-dive), #6. That dive builds the loop.
This one builds the layer above it. It also connects to
[Prompt Injection](https://github.com/alexvervloet/prompt-injection-deep-dive), since hooks
and the sandbox are where guardrails live, and to
[Context Engineering](https://github.com/alexvervloet/context-engineering-deep-dive), since
subagents give each agent its own window. Its code depends on none of them.

Like its siblings, walk through it. Each section ends with something to run, and every
section runs offline and free on the mock. [EXERCISES.md](EXERCISES.md) has a
predict-then-run prompt for each one.

---

## 0. The one big idea

> **A harness is the agent loop, wrapped, so instead of writing the loop you configure it
> and consume its event stream. That wrapper is where subagents, hooks, permission
> policies, the sandbox, durable checkpoints, and orchestration live. In 2026, most agent
> work happens on a harness rather than in a hand-rolled loop.**

That is the whole repo. The Agents dive proved the loop is about 20 lines. But a production
loop needs a place to gate a dangerous call, a place to redact a secret, a boundary on
where tools act, a way to delegate, structured output you can log and test, and a way to
survive a crash mid-run. Bolt all of that into a bare `while` loop and it stops being
readable. A harness lifts each concern out into its own join. Everything below is one of
those joins, a small addition to the loop rather than a new concept. Hold onto that and
none of this feels complicated.

---

## 1. Setup (5 minutes)

```bash
# 1. Create an isolated Python environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install dependencies (the default mock stack needs only python-dotenv + rich)
pip install -r requirements.txt

# 3. Copy the env file: the default runs keyless (no API key needed)
cp .env.example .env
#    (Real provider instead of the mock? Its key goes in your OS keychain,
#     not .env: see ../docs/SECRETS.md, then run scripts as `secrun python ...`.)

# 4. Confirm everything is wired up (makes no API call, costs nothing)
python check_setup.py
```

No key required. The default `PROVIDER=mock` is a deterministic in-process tool-calling
"model". Pick your stack with `PROVIDER` in `.env`.

| `PROVIDER` | What runs the model | Key needed | Cost |
|------------|---------------------|------------|------|
| `mock` (default) | a deterministic offline planner | **none** | **$0** |
| `openai` | OpenAI `gpt-5.4-nano` | `OPENAI_API_KEY` | tiny |
| `claude` | Claude `claude-haiku-4-5` | `ANTHROPIC_API_KEY` | tiny |

The only file that knows which one you picked is
[harness/providers.py](harness/providers.py). Everything above it, meaning the harness,
hooks, policy, sandbox, and subagents, is provider-neutral.

> **Why a mock is the right call here.** The subject is the harness rather than the model.
> A rule-based planner that reliably asks for the tool each example is about lets you watch
> hooks fire, policies gate, and sandboxes refuse, deterministically, offline, for $0. Real
> models make the same kinds of requests, just less predictably.

---

## 2. The bare loop, and what it's missing

```bash
python examples/01_bare_loop_recap.py        # offline
```

Here is the Agents-dive loop again, in about 15 lines, driving the mock. It works, and
that's the point. It works and it is naked. There is no structured way to observe it beyond
`print`, nowhere to gate a `write_file`, nowhere to block a call or redact a result, no
boundary on where a tool acts, and no way to delegate. The example runs the loop, then
names those five gaps. The rest of the dive fills them.

---

## 3. The harness, which is the loop wrapped

```bash
python examples/02_harness_events.py
```

Hand the same task to a `Harness` and stop writing loops. You configure it, then iterate
its event stream, one typed event per thing that happens
([harness/events.py](harness/events.py)). The `while` is gone from your code and lives
inside `Harness.run()`. That inversion is the reason a harness is worth adopting. Every
event is a place to observe, react, or record. The next three examples slot capabilities
into those places without touching the loop.

---

## 4. Hooks, intercepting without editing the loop

```bash
python examples/03_hooks.py
```

A hook is a function the harness calls at a fixed point in every tool cycle. Pre-tool runs
before a tool, and can return a substitute result or raise `HookBlock` to refuse. Post-tool
runs after, and transforms the result before it re-enters the model's context, which makes
it the natural home for redaction. The example blocks reads of credential-looking files
with a pre-tool hook and redacts an API key that slips through a file's contents with a
post-tool hook, so neither the model nor your logs ever see the raw secret. This is where
the [Prompt Injection](https://github.com/alexvervloet/prompt-injection-deep-dive) dive's
defenses live in a real system: at the harness boundary, rather than re-implemented in
every tool.

---

## 5. Permission policies: allow, ask, deny

```bash
python examples/04_permissions.py
```

The Agents dive gated dangerous tools with an `approve` callback tangled into the loop. A
harness makes the policy a declarative object, [harness/policy.py](harness/policy.py), that
you read, diff, version, and swap per environment. Three verdicts: allow runs it, ask
pauses for a human, deny never runs. The example allows the calculator, asks before
`write_file`, and denies `run_command`, and the agent adapts when a call is denied, because
a denial comes back as another tool result. This is the shape of Claude Agent SDK
permission modes and Managed Agents' per-tool `always_allow` and `always_ask` config.

---

## 6. The sandbox, the boundary tools execute inside

```bash
python examples/05_sandbox.py
```

The model chose the arguments, and it may be acting on attacker-controlled text. So tool
execution needs a boundary the model cannot argue past,
[harness/sandbox.py](harness/sandbox.py). Two reject-by-default boundaries. A path jail
resolves every file path and requires it to stay under the workspace root, so
`../../etc/passwd` is refused. A command allowlist runs only named executables. The example
reads a legitimate file, then watches a directory-traversal escape and a non-allowlisted
command get refused as tool results, so the agent adapts. Real harnesses sandbox far harder
with containers, seccomp, egress rules, and a provider-hosted per-session workspace, and it
is the same contract. The model proposes, the sandbox disposes.

---

## 7. Subagents, delegating with an isolated context

```bash
python examples/06_subagents.py
```

The Agents dive showed a subagent as a tool whose function runs its own loop. A harness
makes it first-class. Register a `Subagent` with its own persona and toolset and it appears
to the model as an ordinary tool. When called, the harness spawns a nested harness, a fresh
context window holding only that subagent's tools, runs it, and returns the final answer.
What you get is context isolation. The orchestrator's window never fills with the
subagent's intermediate steps. The example has an arithmetic-only orchestrator delegate a
lookup to a `research` subagent that owns the knowledge-base tool, and the nested run
appears indented in the stream. Scale this up and it is how large agent systems get
built.

---

## 8. Headless automation, one-shot and scriptable and structured

```bash
python examples/07_headless.py
python examples/07_headless.py "What is 19 * 21?"
```

The other way to run an agent, the one job descriptions call agentic automation, is
headless. No human, kicked off by cron or CI, emitting structured output another program
consumes. Because everything is events, you fold a run into a machine-readable record as it
happens. The example runs a task with no interaction and prints a JSON summary, the shape
you would write to a log, post to a webhook, or assert on in CI, failing the build if a
`blocked` tool shows up.

---

## 9. Computer use and hosted sandboxes

```bash
python examples/08_computer_use.py        # offline simulation of the pattern
```

Computer use is the same loop with a different set of tools. The tools are `screenshot`,
`click`, and `type`, and the observation fed back each step is an image of a screen.
Observe, act, observe, exactly as before. The example is a self-contained simulation of
that loop, with a mock login form and a scripted planner standing in for a vision model, so
you see the shape offline. A harness adds two things here. The same permission and hook
points, so you can gate a click on a payment page or redact a typed password. And a hosted
sandbox, a provider-run VM or browser, so the agent drives an isolated machine rather than
your laptop. Reach for computer use only when the task lives in a GUI with no API. A real
tool or API is cheaper and far more reliable than driving pixels.

---

## 10. Durable runs: checkpoint, crash, resume

```bash
python examples/09_checkpoint_resume.py        # offline
```

A long-horizon agent runs for minutes or hours. If the process dies mid-run, through a
deploy, an OOM kill, a timeout, or a reboot, an in-memory loop loses everything and starts
over, re-paying for every step it already finished. A harness checkpoints instead. It
persists its state after each step and can resume in a fresh process, redoing nothing. The
elegant part is that the harness's own transcript is the checkpoint. Because every tool
result gets fed back into it, persisting the transcript is all it takes, as
[harness/checkpoint.py](harness/checkpoint.py) shows. Reload it, keep looping, and the
model, seeing the results already there, moves on. The example runs a two-step task, lets
"process 1" crash after the first tool, and has a brand-new "process 2" resume, with a
counter proving each tool runs exactly once across both. Real systems do the same with a
database instead of a JSON file: LangGraph checkpointers, Temporal-style durable workflows,
Managed Agents' server-side sessions.

---

## 11. Durable task state, a queryable run log

```bash
python examples/10_run_records.py        # offline
```

The same persisted state gives you the other half for free, a task-state log you can query.
Each run carries a status through its lifecycle: `queued`, then `running`, then `done`. Or
`failed`, meaning it gave up. Or stuck in `running`, meaning it crashed mid-run. Because
every run is a file on disk, you can list them all and see which finished, which are still
going, and which crashed and need resuming. That is exactly what a job queue, a cron
dashboard, or Managed Agents' deployment-run records give you. The example runs three jobs,
one that completes, one capped so it fails, and one that crashes, prints the durable log,
and resumes the crashed one straight from it. That status column is the difference between
an agent you hope finished and one you can prove did.

---

## 12. Parallel subagents, fanning out and joining

```bash
python examples/11_parallel_subagents.py        # offline
```

Example 07 delegated to one subagent, and they run one at a time. But a lot of agent work
is independent, like researching five topics or reviewing ten files, and running that
serially wastes wall-clock. The batch should cost the slowest worker rather than the sum.
`fan_out` in [harness/orchestrate.py](harness/orchestrate.py) is the coordinator's map
step. Hand it a list of `(subagent, task)` workers and it runs them concurrently, each in
its own harness and context window, returning every result for you to aggregate, which is
the reduce. The example times the same batch serially and concurrently and shows the
concurrent run finishing in about one worker's time, roughly 3× here. Keep parallel workers
independent and read-mostly, since they share the sandbox. For dependent steps, delegate
serially. This is the from-scratch shape of LangGraph parallel branches or a Managed Agents
multiagent coordinator.

---

## 13. Steering a running agent, injecting and interrupting

```bash
python examples/12_steering.py        # offline
```

The permission policy in §5 gates a tool before it runs. Steering is the other half of
operator control, acting on a run while it is in flight. The harness polls a controller,
[harness/steer.py](harness/steer.py), at each step boundary, so you can inject a message
that changes the next step ("actually, only Pro") without restarting, queue follow-ups
processed in order, and interrupt, stopping the run at a safe boundary instead of killing
it mid-tool. The example injects a follow-up that redirects the agent, then interrupts it
cleanly. An interrupted run gets checkpointed as `interrupted`, which is resumable rather
than lost. A real app drives the live `QueueController`, calling `steer()` and `interrupt()`
from a UI or chat bridge. This is the from-scratch shape of Managed Agents' message queue
plus `user.interrupt`.

---

## 14. Orchestration as a graph, with routing, branching, and cycles

```bash
python examples/13_orchestration_graph.py        # offline
```

The loop lets the model choose the next step. When the path is knowable you want code to
choose it, which means a graph of nodes wired by conditional edges,
[harness/graph.py](harness/graph.py). The example builds a support-ticket workflow.
`classify` routes each ticket to a per-category handler, which is branching, since a
billing ticket and a technical ticket visit different nodes. A `review` gate loops back
through `revise` until the draft passes, which is a cycle. Then it routes to `send`. A node
is `state -> state`, so it can run plain code or a whole Harness. The graph owns the control
flow, not what is inside a node. This is the workflow-against-agent call from the Agents
dive made concrete, and it is the model behind LangGraph. If you can draw the flowchart,
build a graph, because it is cheaper, predictable, and testable. Reach for the model-driven
loop only when the path genuinely cannot be known up front.

---

## 15. Managed Agents, when you own none of it

```bash
python examples/14_managed_agents.py               # explain only, free
secrun python examples/14_managed_agents.py --real # provisions, then cleans up
```

Sections 3 through 14 built a harness. Managed Agents is Anthropic running that whole
layer. You do not write the loop, host the container, or persist the run. It is the far end
of the axis this dive walks.

```
your own loop  ->  your own harness  ->  a harness you host  ->  hosted entirely
     (§2)              (§3-14)           (Claude Agent SDK)     (Managed Agents)
```

Almost nothing in it is a new idea. It is this dive's problem list with someone else's
answers plugged in.

| This dive | Managed Agents |
|-----------|----------------|
| your event stream (§3) | `sessions.events.stream()` |
| permission policies (§5) | `always_allow` / `always_ask` per tool |
| the sandbox (§6) | the session's container, Anthropic-run |
| subagents (§7) | a `multiagent` roster on the agent |
| checkpoint/resume (§10) | the session, durable by construction |
| run records (§11) | deployment runs |
| steering (§13) | `user.message` / `user.interrupt` events |

One structural rule is worth memorizing. An Agent is a persisted, versioned config holding
the model, system prompt, and tools. A Session is one run of it. Those fields live on the
agent, never on the session. Creating an agent per run is the classic mistake. It orphans
objects, pays creation latency every time, and discards the versioning that is the whole
reason agents are separate objects. Create once, store the id, reuse. That is the hosted
version of not re-instantiating your harness inside the request handler.

What you give up is real. You cannot reach into the loop the way §4's hooks let you, tools
run in a container you do not own, and it is one vendor. Good trade when the alternative is
maintaining §3 through §14 yourself. Bad trade when that layer is where your value lives,
which is precisely the judgement this dive exists to give you.

---

## 16. Agent Skills, instructions that load on demand

```bash
python examples/15_skills.py               # explain + list skills, free
secrun python examples/15_skills.py --real # actually builds a spreadsheet
```

A capable agent needs more instructions than fit comfortably in one system prompt, and
stuffing them all in makes every request slower, dearer, and, as the
[Context Engineering dive](https://github.com/alexvervloet/context-engineering-deep-dive)
shows, measurably worse. A skill is the answer on the instruction side. A folder with a
`SKILL.md`, whose one-line description sits in context always while the body gets read only
when the task calls for it.

| Mechanism | What stays in context |
|-----------|-----------------------|
| system prompt | all of it, every request, forever |
| **skill** | one line; the rest loads on demand |
| subagent (§7) | nothing; it gets its own window |

Three things have to travel together or the request fails: the two betas
(`code-execution-2025-08-25`, `skills-2025-10-02`), a `container` naming the skills, and
the `code_execution` tool, because skills execute in the container. Anthropic ships `xlsx`,
`pptx`, `docx`, and `pdf`, and you can register your own.

This sits in a harness dive rather than an API one because a skill is configuration your
harness owns, exactly like §5's permission policy or §4's set of tools. Which skills to
attach, and whether the model may reach for one unprompted, are your decisions. And since a
skill can carry scripts, and those scripts run, a skill you did not write deserves the same
suspicion as a tool you did not write.

---

## The capstone: `agent_harness.py`

Everything assembled into a harness you can drive. A real permission policy where
`write_file` asks and `run_command` is denied, a sandboxed workspace with a command
allowlist, a redaction post-tool hook, a `research` subagent, durable checkpointing, and a
choice of live event trace or headless JSON.

```bash
# One-off task with a live event trace (offline on the mock): the agent delegates
# the lookup to the research subagent, THEN computes with the calculator: a real
# two-step chain, and the final answer reports both.
python hands_on/agent_harness.py "Look up the plans and prices, then compute a year of Pro (30 * 12)."

# Auto-approve the `ask` tools (non-interactive):
python hands_on/agent_harness.py "write file todo.txt containing: ship it" --yes

# Headless: emit a JSON record instead of a trace (for CI / cron):
python hands_on/agent_harness.py "What is (23 * 47) + 100?" --json

# Durable: checkpoint under an id; re-run with the same id to RESUME a crashed run.
python hands_on/agent_harness.py "read the file plan.txt and compute (2 + 2)." --run-id job1
```

Read [hands_on/agent_harness.py](hands_on/agent_harness.py). It's the library composed.
`build_agent()` wires policy, sandbox, hook, and subagent together, and the main loop
consumes the event stream. **Suggested exercise:** add a second subagent, say a `math`
specialist, or tighten the policy to deny `write_file` outright, and watch the trace
change. Adding a capability is one step: register it, and the harness routes to it.

---

## When do you throw away your loop for the SDK?

Here is the honest answer, and the one to give in an interview.

- **Write the loop by hand when** the agent is simple, with a few tools and one context, or
  you need to understand exactly what happens, or you're learning. The loop is about 20
  lines, and a dependency plus its concepts cost more than that.
- **Adopt a harness or SDK when** you need any of the pieces this dive built: gated tools,
  hooks and guardrails, a real sandbox, subagents, structured headless output, durable
  resumable runs, or orchestration through parallel workers, mid-run steering, and graph
  control flow. Especially when you would otherwise reimplement them badly. A harness is a
  pile of hard, security-sensitive code, covering sandboxing, permission prompts, event
  plumbing, reconnection, and streaming, that someone else has already hardened.
- **What the SDK gives you** that this toy doesn't: a real sandbox with containers rather
  than a path check, provider-hosted per-session workspaces, streaming and reconnection that
  hold up, subagent orchestration, permission UIs, and headless run records. The
  productionized version of every piece here.

Two named options exist in the Claude world. The Claude Agent SDK, where you host the
compute and the SDK runs the loop and gives you hooks, subagents, permission modes, and
sandboxing. And Managed Agents, where Anthropic hosts the loop and a per-session container
where tools execute. OpenAI's Agents SDK is the equivalent on that stack. All of them are
this dive's harness, hardened and hosted.

---

## Where to go next

You've built a harness from scratch. What comes next is the same pieces, harder.

- **A real sandbox.** Swap the path jail for a container or microVM with seccomp,
  read-only mounts, and network egress rules, or use a provider-hosted sandbox.
- **Richer permission policies.** Per-argument rules (allow `read_file` anywhere
  but `write_file` only under `/tmp`), rate limits, and budgets per run.
- **Harder durable execution.** §10 and §11 checkpoint to a JSON file and resume. Next
  comes a DB-backed durable-workflow engine with idempotent, exactly-once replay even
  across a mid-tool crash, plus reconnecting a dropped event stream without losing
  events.
- **Deeper orchestration.** §12 through §14 fan out to parallel workers, steer a run
  mid-flight, and route with a graph. Next comes hierarchical multi-level delegation,
  agent-to-agent messaging, backpressure and concurrency limits across many workers, and
  graph engines with persistence and streaming built in, such as LangGraph and Managed
  Agents' multiagent coordinator.
- **Provider-hosted tools and agents.** Web search, code execution, and computer use
  run by the provider; and fully managed agents where you never run the loop.
- **Evaluating harness behavior.** Score trajectories (right tools, right order, no
  denied-then-retried loops) with the
  [Evals dive](https://github.com/alexvervloet/evals-deep-dive), not just final answers.

---

## From teaching code to production

The shortcuts that make this repo readable and free are exactly what a real harness
replaces:

| This repo's teaching shortcut | In production |
|-------------------------------|---------------|
| Sandbox is a path check + command allowlist | A **container / microVM** with seccomp, read-only mounts, and egress rules, or a provider-hosted sandbox |
| Hooks are in-process Python functions | A **guardrail pipeline** (input/output classifiers, PII redaction, injection detection) wired at the same seam |
| Permission policy is a dict of verdicts | A **policy engine** with per-argument rules, budgets, rate limits, and an audit log of every decision |
| Subagents share one process; `fan_out` uses a thread pool | **Isolated workers** with their own resource limits, backpressure/concurrency caps, and a coordinator that survives a crash |
| Steering is an in-process controller; the graph is plain Python | A **durable message queue** (steer/interrupt across processes) and a **graph engine** with persistence, streaming, and observability baked in |
| Events are printed | A **structured trace** (a span per step) shipped to observability, plus durable run records |
| Checkpoint is a JSON file per run | A **durable-execution engine**: DB- or workflow-backed state, idempotent exactly-once replay even across a mid-tool crash (Temporal-style), or a provider's server-side sessions |
| The mock (or one model) is hard-wired | A **model router** with fallbacks, retries, and cost/latency budgets per run |
| Headless run is a script | A **queue/worker** with retries, idempotency, and a webhook or eval gate on the result |

These are right for learning and wrong for production. The general ops machinery 
observability, cost, reliability, caching, guardrails, prompt versioning, eval
gates) is built from scratch and wired into one running app in
**[Production](https://github.com/alexvervloet/ai-in-production-deep-dive)** (#8), which
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
  14_managed_agents.py     ← the hosted end of the axis: Anthropic runs the harness
  15_skills.py             ← progressive-disclosure instructions (SKILL.md)
```

(`workspace/` and `runs/` are created by the examples and are git-ignored.)

---

## Troubleshooting

Run `python check_setup.py` first; it catches most problems. Then, by symptom:

| What you see | What it means / the fix |
|--------------|-------------------------|
| `ModuleNotFoundError` (dotenv / rich) | Deps aren't installed or the venv isn't active. `source .venv/bin/activate` then `pip install -r requirements.txt`. |
| `PROVIDER=... needs ... in the environment` | You switched to a real provider without a key. Load it from your keychain with `secrun` (see [SECRETS.md](../docs/SECRETS.md)), or go back to `PROVIDER=mock`. |
| A tool ran that I expected to be blocked | Check the policy verdict *and* your hooks. `deny` blocks outright; `ask` runs if your `approve` callback returns True (the capstone's `--yes` auto-approves `ask`, but never overrides `deny`). |
| "escapes the sandbox" on a path I meant | Working as intended: the jail resolves `..` and symlinks and refuses anything outside the root. Use a relative path inside `workspace/`. |
| The mock takes one step where I expected several | The deterministic planner does one tool per turn for clarity; a real model may chain more. Switch `PROVIDER` to see it. |
| `SyntaxError` / odd type errors on startup | You're likely on Python 3.9 or older; this repo needs 3.10+. `check_setup.py` confirms your version. |

Still stuck? Every file is small and self-contained. Open it, read the docstring
at the top, and run it directly. [harness/core.py](harness/core.py) is the whole
story: the loop, wrapped.

---

## The series

This is one of the standalone, hands-on deep dives into building with LLM APIs 
eight core, plus the bonus dives. Each stands on its own, with its own setup, examples,
and capstone, and they share one house style: provider-agnostic where it makes
sense, built from scratch (no frameworks), offline-first examples, and a real
capstone. Do them in any order; this sequence builds naturally:

1. [OpenAI API](https://github.com/alexvervloet/openai-api-deep-dive): the API from zero
2. [Claude API](https://github.com/alexvervloet/claude-api-deep-dive): the same ideas, the Anthropic way
3. [Prompt Engineering](https://github.com/alexvervloet/prompt-engineering-deep-dive): shape model behavior with better prompts
4. [RAG](https://github.com/alexvervloet/rag-deep-dive): answer questions over your own documents
5. [Evals](https://github.com/alexvervloet/evals-deep-dive): measure whether a change actually helps
6. [Agents](https://github.com/alexvervloet/agents-deep-dive): give a model tools and a loop so it can act
7. [Prompt Injection & Guardrails](https://github.com/alexvervloet/prompt-injection-deep-dive): attack and defend all of the above
8. [Production](https://github.com/alexvervloet/ai-in-production-deep-dive): operate one app end to end

**Bonus dives**, standalone and slotting in where they're most useful:

- [Agent Harnesses](https://github.com/alexvervloet/agent-harness-deep-dive): build on the loop, adding hooks, permissions, sandboxing, subagents, and headless runs
- [Context Engineering](https://github.com/alexvervloet/context-engineering-deep-dive): manage what's in the window
- [AI Data Engineering](https://github.com/alexvervloet/ai-data-engineering-deep-dive): the corpus behind the index, with versions, lineage, ACLs, and deletes
- [Multimodal](https://github.com/alexvervloet/multimodal-deep-dive): images and audio as well as text
- [Realtime Voice](https://github.com/alexvervloet/realtime-voice-deep-dive): low-latency speech-to-speech agents
- [Fine-tuning](https://github.com/alexvervloet/fine-tuning-deep-dive): teach a model new behavior by example
- [MCP](https://github.com/alexvervloet/mcp-deep-dive): serve tools, data, and prompts over a standard protocol
- [Local Models](https://github.com/alexvervloet/local-models-deep-dive): run open-weight models on your own machine
- [Observability](https://github.com/alexvervloet/observability-deep-dive): watch a running app over time, covering drift, quality, alerting, and the feedback loop
- [Architecture](https://github.com/alexvervloet/architecture-deep-dive): the seams between the components, each decision measured rather than asserted
- [GenAI Security](https://github.com/alexvervloet/genai-security-deep-dive): treat the model as an untrusted principal, and put identity, supply chain, isolation, budgets, and release gates around it
- [Inference Platform Engineering](https://github.com/alexvervloet/inference-platform-deep-dive): turn finite GPU memory and a request queue into latency, throughput, and a fleet size you can defend
- [Testing & Delivery](https://github.com/alexvervloet/testing-and-delivery-deep-dive): decide whether a build is fit to promote, using evidence, gates, staged rollout, and rollback
- [Professional Tools](https://github.com/alexvervloet/professional-tools-deep-dive): rebuild each hand-written piece with the tool professionals reach for, and measure both

And the whole series lands in one codebase in the
[capstone](https://github.com/alexvervloet/deep-dive-capstone): a codebase Q&A tool
built step by step, one tag per dive.

**Agent Harnesses is a bonus dive.** It slots directly after
[Agents](https://github.com/alexvervloet/agents-deep-dive) (#6), since that dive builds the
loop; this one builds the layer you run it on.
