# Exercises: make the learning stick

Reading code teaches you less than *predicting* what it will do and then checking.
This file turns each section of the [README](README.md) into a few quick
active-recall prompts.

How to use it: work the section first, then come back. **Commit to an answer
before you run or reveal.** The prediction is where the learning happens. Answers
are hidden behind ▸ toggles.

> **Every example is offline**: the default `PROVIDER=mock` runs the whole repo
> with no key and no cost.

---

## Section 2: The bare loop and its gaps

**Recall.** The loop in `examples/01_bare_loop_recap.py` works. Name the five things
it *can't* do that a harness adds.

<details><summary>▸ Answer</summary>

**Observe** (only `print`, no event stream), **gate** (every tool runs
unconditionally), **intercept** (no place to block a call or redact a result),
**contain** (no boundary on where a tool acts), and **delegate** (one loop, one
context: no subagents). Each is a seam the harness adds around the same loop.
</details>

---

## Section 3: The harness and its event stream

**Predict (`02`).** You hand the same task to a `Harness` and iterate `run()`. Where
did the `while` loop go, and what do you write instead?

<details><summary>▸ Answer</summary>

The loop moved *inside* `Harness.run()`. You don't write a loop at all; you iterate
the **event stream** it yields (RunStarted, ModelTurn, ToolFinished, RunFinished,
...). That inversion is the whole value: every event is a seam to observe, react, or
record.
</details>

---

## Section 4: Hooks

**Predict (`03`).** A pre-tool hook raises `HookBlock` on credential files; a
post-tool hook redacts API keys. For a safe file that happens to contain a key,
which hook fires and what does the model end up seeing?

<details><summary>▸ Answer</summary>

The **post-tool** hook fires (the pre-tool block only triggers on credential-looking
*paths*, and this file's path is safe). The tool reads the file, then the post-tool
hook redacts the key from the result, so the model summarizes the file but never
sees the raw secret. Blocking (pre) and transforming (post) are different jobs at
different points in the cycle.
</details>

**Recall.** Why put redaction in a hook instead of inside the `read_file` tool?

<details><summary>▸ Answer</summary>

Because it's a cross-cutting rule, not one tool's job. You want it applied to
*every* tool's output, and you want to add or change it without editing tools. The
harness seam is the one place it lives; this is how real systems ship guardrails
(the Prompt Injection dive's defenses) without every tool re-implementing them.
</details>

---

## Section 5: Permission policies

**Predict (`04`).** The policy is `ask` for `write_file` and `deny` for
`run_command`, and the demo auto-approves. What happens to each of the two tasks?

<details><summary>▸ Answer</summary>

The `write_file` is gated by `ask`, the callback approves, and it runs. The
`run_command` hits `deny` and is refused *before executing*, regardless of
approval; `deny` isn't something a human can wave through. The denial comes back as
a tool result, so the agent sees it and adapts.
</details>

**Recall.** What did lifting the policy out of the loop into its own object buy you?

<details><summary>▸ Answer</summary>

You can read it, unit-test it, diff it in code review, and swap it per environment
(strict in prod, loose in a dev sandbox), all without touching agent code. In the
Agents dive the policy was tangled into an `approve` callback threaded through the
loop; here it's a declarative object, the same shape as Claude Agent SDK permission
modes.
</details>

---

## Section 6: The sandbox

**Predict (`05`).** The agent tries `read ../../../../etc/passwd`. Does a
`startswith(root)` check on the raw path string catch it? What does the sandbox do?

<details><summary>▸ Answer</summary>

A raw-string check can be fooled (the path may not literally start with the root, or
may use symlinks). The sandbox **resolves** the path first (`os.path.realpath`,
collapsing `..` and following symlinks) and checks the *canonical* location against
the root, so the traversal is refused. The refusal comes back as a tool result, not
a crash.
</details>

**Recall.** Why an allowlist for commands instead of a blocklist?

<details><summary>▸ Answer</summary>

A blocklist ("reject `rm`") loses: there are infinite dangerous phrasings and
encodings. An allowlist names the few commands you trust and refuses everything else
by default. Reject-by-default is the only boundary that holds against an adversary
choosing the input.
</details>

---

## Section 7: Subagents

**Predict (`06`).** The orchestrator has only the calculator; the `research`
subagent owns the knowledge-base tool. After delegation, what enters the
orchestrator's context: the subagent's search step, or just its answer?

<details><summary>▸ Answer</summary>

Just the answer. The subagent runs in a **nested harness** with its own context
window; only its final result returns to the orchestrator. That's context
isolation: the orchestrator's window never fills with the subagent's intermediate
tool calls. (They share the sandbox/filesystem, but not the conversation.)
</details>

---

## Section 8: Headless automation

**Recall (`07`).** What makes the harness suitable for a cron job or CI step, with
no human present?

<details><summary>▸ Answer</summary>

`run_to_completion` drives it to a final answer, and because everything is events
you fold the run into a machine-readable record (tools run, anything blocked, the
answer) as it happens. The only thing it emits is structured output another program
consumes: a log line, a webhook payload, or something CI can assert on (e.g. fail
the build if a tool was `blocked`).
</details>

---

## Section 9: Computer use & hosted sandboxes

**Recall (`08`).** How is computer use the *same* loop you already know, and what's
different?

<details><summary>▸ Answer</summary>

Same observe → act → observe loop. What's different is the tool surface: the tools
are `screenshot` / `click` / `type`, and the observation fed back each step is an
image of a screen instead of a text tool result. A harness still adds the same
permission and hook seams, and a **hosted sandbox** (a provider-run VM/browser) so
the agent drives an isolated machine, not your own.
</details>

**Recall.** When should you reach for computer use, and when not?

<details><summary>▸ Answer</summary>

Reach for it only when the task lives in a GUI with **no API** to call. If a real
tool or API exists, use that. Driving pixels is slower, costlier, and far less
reliable than a typed tool call. Computer use is the fallback for the un-automatable,
not the default.
</details>

---

## Section 10: Durable runs (checkpoint & resume)

**Predict (`09`).** A two-step run (read a file, then compute) crashes right after
the first tool finishes. A fresh process resumes it. Does the resumed process re-run
the read? Why or why not?

<details><summary>▸ Answer</summary>

No. The completed read's result was checkpointed into the persisted **transcript**
before the crash. On resume, the harness reloads that transcript and keeps looping 
the model sees the read result already present and moves straight to the calculation.
The example's counter proves each tool ran exactly once across both processes. That's
the whole mechanism: the transcript *is* the checkpoint.
</details>

**Recall.** Why is persisting the transcript enough to make a run resumable, when you
don't separately save "which step I'm on"?

<details><summary>▸ Answer</summary>

Because the loop is deterministic given the transcript: every tool result is already
fed back into it, so "where I am" is implied by "what's in the transcript." Reload it
and the next model turn naturally produces the *next* step. Real durable-execution
engines (LangGraph, Temporal) persist more, but the principle is the same: save the
state the loop reads, and resuming is just continuing.
</details>

---

## Section 11: Durable task state (run records)

**Recall (`10`).** Three runs finish in three states: `done`, `failed`, and stuck in
`running`. What does each mean, and what do you do with the `running` one?

<details><summary>▸ Answer</summary>

`done` = finished with an answer. `failed` = gave up (here, hit the step limit) 
needs a fix or a bigger budget. Stuck in `running` = the process **crashed** mid-run
(the status was never advanced to done). You **resume** it from its checkpoint, which
the example does straight from the run log, knowing nothing but its id.
</details>

**Recall.** The checkpoint file powers two different features. What are they?

<details><summary>▸ Answer</summary>

**Resuming** one run (§10) and **monitoring** all runs (§11): a queryable task-state
log of what finished, what's running, and what crashed. Same persisted state, two
uses. That status column is the difference between an agent you *hope* finished and
one you can *prove* did: the durable task state real agent systems are built on.
</details>

---

## Section 12: Parallel subagents

**Predict (`11`).** Three independent research workers, each taking ~0.4s, run via
`fan_out`. Serially the batch takes ~1.2s. Roughly how long does the concurrent run
take, and why?

<details><summary>▸ Answer</summary>

About **0.4s**: the time of the *slowest* worker, not the sum. The workers are
independent, so there's no reason to wait between them; run them concurrently and the
batch cost is the MAX, not the SUM (~3× here). Each still gets its own harness and
context window (isolation); they only share the sandbox, which is why parallel workers
should be independent and read-mostly.
</details>

---

## Section 13: Steering a running agent

**Predict (`12`).** Mid-run, the operator injects "now compute 30 * 12" and then
interrupts. What does the agent do with the injected message, and does the interrupt
kill it mid-tool?

<details><summary>▸ Answer</summary>

The injected message becomes the newest user turn, so it **steers the next step** 
the agent switches from the lookup to the calculation, no restart. The interrupt does
**not** kill it mid-tool: the harness only checks the controller at a step *boundary*,
so the current step finishes and the run halts cleanly. An interrupted run is
checkpointed as `interrupted` (resumable), not lost.
</details>

**Recall.** How does steering differ from the permission policy (§5)?

<details><summary>▸ Answer</summary>

The permission policy decides whether a tool runs *before* it runs (a synchronous
gate). Steering acts on a run *while it's in flight*: inject a new instruction, queue
follow-ups, or interrupt. Gate = "may this happen?"; steer = "here's a change of
plan / stop."
</details>

---

## Section 14: Orchestration as a graph

**Recall (`13`).** A graph classifies a ticket, routes it to a handler, runs a review
gate, and loops back to revise until it passes. Which two control-flow features does
that use that a straight sequence of steps doesn't?

<details><summary>▸ Answer</summary>

**Branching** (the router sends a billing ticket and a technical ticket to *different*
handler nodes, since the path depends on the state) and a **cycle** (the review gate routes
back through `revise` until the draft passes). Nodes + conditional edges give you both;
a straight pipeline gives you neither.
</details>

**Recall.** When do you build a graph vs. run the agent loop?

<details><summary>▸ Answer</summary>

If you can **draw the flowchart**, build a graph. Code drives the path, which is
cheaper, predictable, and testable. Reach for the model-driven loop only when the path
genuinely **can't be known up front**. Real systems mix them: a graph whose individual
nodes each run a Harness (an agent as one step).
</details>

---

## Capstone: `agent_harness.py`

**Do.** Run `python hands_on/agent_harness.py "write file todo.txt containing: ship
it" --yes`, then run the same task without `--yes`. What changes, and does `--yes`
let the agent run a denied tool?

<details><summary>▸ Answer</summary>

With `--yes` the `ask` verdict on `write_file` is auto-approved; without it you're
prompted. Neither lets a **denied** tool run: `--yes` only auto-answers `ask`, and
`deny` (like `run_command`) is refused regardless. Allow/ask/deny are three distinct
verdicts, and only `ask` is a question.
</details>

**Stretch.** Add a second subagent, or tighten the policy to `deny` `write_file`
outright, and watch the event trace change. When the harness routes to a capability
you added just by registering it, the "configure, don't code the loop" idea has
landed.

---

### Where to take it next

Point the harness at a real model (`PROVIDER=openai` or `claude`, add a key) and
give it a multi-step task. Watch the *same* hooks, policy, and sandbox govern a real
model's tool calls. The machinery didn't change, only who's choosing the tools.
Then open the Claude Agent SDK or Managed Agents docs: everything there will read as
the hardened, hosted version of the seams you just built.
