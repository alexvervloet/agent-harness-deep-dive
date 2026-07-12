# Chapter 9: The Harness, or What Grows Around a Loop

*This is the textbook chapter for the Agent Harnesses deep dive, a bonus dive that follows [Agents](../agents-deep-dive/TEXTBOOK.md) directly. The [README](README.md) is the lab manual; this is the lecture. It covers why the twenty-line loop you wrote in Chapter 6 is never what production runs, where each layer of the wrapper came from, and how to answer the interview question this whole dive exists for: when do you throw away your loop for the SDK, and what does the SDK actually give you?*

---

## 9.1 A story the web already told

Something happened to web development between roughly 1995 and 2010 that is about to repeat itself, and knowing the first telling helps you recognize the second.

In the beginning, writing a web application meant writing everything: parse the HTTP request off the socket, split the headers, decode the form fields, remember to escape the output. It was educational, briefly, and then it was a liability, because every team was re-implementing the same security-sensitive plumbing, each with their own bugs. Frameworks emerged, and the good ones shared a shape: they ran the request loop for you, and your code plugged into named seams (routes, middleware, before and after filters). The framework called you, not the other way around; old-timers called it the Hollywood principle, don't call us, we'll call you. Within a decade, "I hand-wrote my own HTTP parsing" changed from a credential into a confession.

Agents are partway through the same transition. Chapter 6 had you hand-write the loop, and that was the right way to learn it, exactly as parsing HTTP by hand once was. But the loop that runs unattended in a real product needs a place to gate a dangerous call, a place to redact a secret before it hits the logs, a boundary tools cannot act outside of, a way to delegate, structured output a machine can consume, and the ability to survive a crash halfway through an hour of work. Bolt all of that into a bare `while` loop and it stops being a loop; it becomes an unreadable knot with security code woven through business logic. The alternative has a name:

> **A harness is the agent loop, wrapped: you configure it and consume its event stream instead of writing it. The wrapper is where subagents, hooks, permissions, the sandbox, durable checkpoints, and orchestration live.**

Claude Code, the tool many readers of this series use daily, is exactly this: a harness around the same loop you wrote, hardened. Most professional agent work now happens at this layer, building on a harness rather than hand-rolling, and this dive builds a small one from scratch so the commercial ones read as engineering rather than magic. Like the Production dive, it runs entirely offline on a deterministic mock, because the subject is the machinery, and machinery is best studied on a model that behaves on cue.

## 9.2 The inversion, and why events are the product

The first move is small and changes everything. Instead of writing `while True:` yourself, you hand the task to a `Harness` object and iterate its **event stream**: one typed event for each thing that happens (a model turn started, a tool was requested, a tool returned, the run finished). The loop still exists; it moved inside `Harness.run()`, out of your code.

Why does relocating a while loop matter? Because once the loop is inside a component, every point in its cycle becomes a **seam**: a fixed, named place where outside code can observe or intervene without anyone editing the loop itself. The rest of this chapter is a tour of those seams, and it is worth noticing in advance that not one of them will introduce a new concept. Each is a small addition at a seam, which is the entire trick.

The event stream itself is the first payoff. A bare loop's observability is whatever `print` statements you scattered; an event stream is a structured record produced as a side effect of running at all. Pipe it to a terminal and you have a live trace. Fold it into JSON and you have a machine-readable run record. Feed it to the trajectory evals of Chapter 5 and you have graded behavior. Same events, three consumers, no loop edits.

## 9.3 Hooks: middleware for the tool cycle

A **hook** is a function the harness calls at a fixed point in every tool cycle. A pre-tool hook runs before execution and can substitute a result or refuse the call outright. A post-tool hook runs after and can transform the result before it re-enters the model's context.

If you have written web middleware, or a git pre-commit hook, or a database trigger, you have met this pattern; it is one of software's most durable ideas because it solves a permanent problem, cross-cutting concerns, things that apply to every operation but belong to none of them. The lab's example is the security pair: a pre-tool hook blocks reads of credential-looking files, and a post-tool hook redacts an API key that slips through inside a file's contents, so the raw secret never reaches the model's context or your logs.

That placement deserves a pause, because it answers a question the guardrails dive (Chapter 7) leaves open: where do the defenses actually live in a real system? The answer is here, at the harness seam. Not re-implemented inside every tool (you will forget one), not woven into the loop (unmaintainable), but registered once, at the point every tool call must pass through. A seam that everything crosses is the only place a guarantee can be universal.

## 9.4 Policy and sandbox: two different kinds of "no"

The next two seams both say no to tools, and the difference between them is the most important distinction in the chapter.

A **permission policy** is judgment, declared. Chapter 6 gated dangerous tools with an approval callback tangled into the loop; the harness lifts the policy out into a declarative object mapping each tool to a verdict: **allow** (run freely), **ask** (pause for a human), **deny** (never). Because it is data rather than code, you can read it, diff it, version it, audit it, and swap it per environment: permissive in development, strict in production, paranoid for the internet-facing deployment. This is recognizably the shape of the permission modes in the commercial SDKs, and the shape matters more than the syntax. A security reviewer can read a policy object in thirty seconds; nobody can review an approval callback scattered through a loop.

A **sandbox** is a boundary, enforced. Here is why the policy is not enough: the policy trusts the tool name, but the model chooses the *arguments*, and the model may be acting on attacker-controlled text (Chapter 7's indirect injection, now with hands). `read_file` is a harmless tool right up until the argument is `../../../etc/passwd`. So tool execution happens inside a reject-by-default boundary the model cannot argue past: a path jail that resolves every path (including `..` and symlinks) and refuses anything outside the workspace root, and a command allowlist that runs only named executables. The lab's slogan compresses it: the model proposes, the sandbox disposes.

The distinction to carry away: the policy encodes what you *intend* to permit; the sandbox limits what can *physically happen* when intent is subverted. Defense in depth means never confusing the two, and the sixty-year lineage behind the second one (chroot jails, virtual machines, containers, browser sandboxes) exists precisely because intent gets subverted. Real harnesses push this boundary much harder than a path check, into containers, microVMs, and network egress rules, up to provider-hosted per-session workspaces where the agent's whole world is a disposable machine. Same contract, thicker walls.

## 9.5 Subagents and headless runs: the shape scales down and sideways

Two seams from Chapter 6 return with the harness making them first-class.

**Subagents** were introduced as a pun (a tool whose implementation runs its own loop); the harness makes the pun infrastructure. Register a subagent with its own persona and toolset and it appears to the model as an ordinary tool; when called, the harness spawns a nested harness with a fresh context window, runs it, and returns only the final answer. The parent's window never fills with the child's intermediate work, which is **context isolation**, and it is the architectural answer to a problem Chapter 10 examines at length: the context window is the scarcest resource an agent has. There is a security bonus too, easy to miss: a subagent's toolset is a capability boundary. The research subagent holds the search tool; the orchestrator holds the calculator; neither can do the other's job even if convinced to try.

**Headless** operation is the other posture of agent work, the one job listings call agentic automation: no human present, kicked off by cron or CI, emitting structured output another program consumes. Because everything is already events, this costs nothing new: fold the stream into a JSON record, and a CI job can assert on it (fail the build if any tool call was blocked, flag the run if it exceeded its step budget). An agent whose runs are records rather than vibes is an agent you can put in a pipeline.

**Computer use** rounds out the tour as a perspective shift rather than a new mechanism: point the same loop at a screen, where the tools are screenshot, click, and type, and the observation fed back each turn is an image. The harness seams apply unchanged, and matter more (gate the click on the payment page; redact the typed password), and the sandbox question sharpens into "whose machine is it driving?", which is why the hosted, disposable VM is the standard answer. The engineering advice attached is unglamorous and correct: driving pixels is the expensive, brittle last resort for software that offers no API; when there is an API, use it.

## 9.6 Durability: the transcript was the checkpoint all along

Now the seam this dive saves for its best reveal. A long-horizon agent runs for minutes or hours, and processes die: deploys, out-of-memory kills, timeouts, reboots. An in-memory loop loses everything and starts over, re-paying for every step already finished, which at agent prices is real money and real time.

The fix sounds heavy (durable, resumable execution, the stuff of workflow engines) and turns out to be almost free, because of a fact you have known since Chapter 1: the loop's entire state *is the transcript*. Every tool result is appended to the conversation; the model re-reads the whole thing each turn anyway. So persist the transcript after each step, and resuming is just reloading it in a fresh process and continuing the loop; the model, seeing the completed steps already in its context, moves on to what is left. The lab proves it with a counter: process one crashes after step one, process two resumes, and every tool ran exactly once across both lives.

Readers with distributed-systems background will recognize event sourcing, the pattern where the log of what happened is the state rather than a description of it, and the recognition is exact: production versions of this idea (LangGraph checkpointers, Temporal-style durable workflows, server-side sessions) are the same move with a database instead of a JSON file and idempotency guarantees hardened for the crash-mid-tool case.

Durability's second dividend comes free: if every run persists its state, you have a queryable **run log**, each run carrying a status through its lifecycle (queued, running, done, failed, or stuck in running, which is how a crash reads). That status column is the difference between an agent you hope finished and one you can prove did, and it is what any job queue or cron dashboard has always offered; agents simply join the club of things operations can see.

## 9.7 Orchestration: many workers, live steering, and the graph

The last three seams turn one agent into a system.

**Fan-out** is map-reduce for subagents: hand the coordinator a list of independent workers (research five topics, review ten files) and run them concurrently, each in its own harness and window, so the batch costs the slowest worker rather than the sum. The judgment attached is the same one parallel computing always charges: keep parallel workers independent and read-mostly, because they share the sandbox, and delegate serially when steps depend on each other.

**Steering** is operator control over a run in flight, the complement to the policy's before-the-fact gating. The harness polls a controller at each step boundary, so you can inject a correction ("actually, only the Pro plan") that changes the next step without restarting, queue follow-ups, or interrupt cleanly, with the interrupted run checkpointed as resumable rather than lost. Anyone who has watched an agent set off in the wrong direction and had no lever but kill-and-restart knows exactly which pain this seam removes.

**Graphs** close the dive by making Chapter 6's workflow-versus-agent decision concrete. When the path through a task is knowable, code should choose the next step, not the model: nodes wired by conditional edges, branching (a billing ticket and a technical ticket visit different handlers), and cycles (a review gate loops a draft back through revision until it passes). A node is just a function from state to state, so it can contain plain code or an entire harness; the graph owns control flow, not what happens inside a node. This is the mental model behind LangGraph and its relatives, and the decision rule stands as before: if you can draw the flowchart, build the graph, and spend the model-driven loop only where the path genuinely cannot be known.

## 9.8 The interview question, answered

The dive frames itself around a question worth being able to answer fluently, so here is the answer in prose.

Write the loop by hand when the agent is simple, when you need to understand exactly what happens, or when you are learning; twenty lines is cheaper than a dependency and its concepts. Adopt a harness when you need any of the seams this chapter toured (gated tools, hooks, a real sandbox, subagents, structured headless output, durable runs, orchestration), and especially when the alternative is re-implementing them yourself, because a harness is a pile of hard, security-sensitive code that someone else has already hardened, and hand-rolled sandboxing is where the web's "I parse HTTP myself" era went to produce incidents. What the commercial SDKs add over this dive's toy is exactly the hardening: containers instead of path checks, hosted per-session workspaces, robust streaming and reconnection, permission UIs, and run records with an operations team behind them.

And the deeper thing the question probes: whether you know what is inside the box you are choosing. Having built each seam once, at teaching scale, you do. When a harness's permission prompt fires, you know which seam that is; when a run resumes after a deploy, you know the transcript was the checkpoint; when a subagent's work does not pollute the parent's context, you know why that was the design. The frameworks stopped being magic one chapter ago. Now the products have too.

---

*Lab manual: [README.md](README.md) · Exercises: [EXERCISES.md](EXERCISES.md) · Builds on: [Agents](../agents-deep-dive/TEXTBOOK.md) · Related: [Context Engineering](../context-engineering-deep-dive/TEXTBOOK.md)*
