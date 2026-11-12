# Agent Choir Studio — V1 Lineage

*A faithful, self-contained account of the first experiment: what it was, why it was
built, what it proved, and what carried forward into V2. This is grandfathered history,
not live specification. Nothing here needs re-deriving — it is recorded so V2 can stand
on it without assuming the V1 repository or its documents are reachable. Skip this file
if you already know V1.*

---

## 1. What V1 was

Agent Choir Studio (V1) was a version-controlled **learning instrument** whose purpose
was earned first-hand competence in **multi-agent coordination topologies and their
failure modes**, specifically in the context of **context aggregation** — how a system
assembles a coherent picture of a situation from several narrow contributors before
anything downstream acts on it.

It was not a product, not a demo, not a PowerPoint concept. It was a sandbox built to be
*watched*. The owner was always at the controls; there was no unattended or public use,
which removed any need for robustness, onboarding, rate-limiting or abuse protection.

Its guiding inversion: for most multi-agent demos the synthesised final answer is the
point and the trace is a footnote. V1 flipped that. **The trace was the product.** The
input barely mattered — it was a trigger, not the subject. What mattered was everything
*around* the output: latency, token cost, whether agents genuinely reacted or merely
agreed, how context assembled and degraded across a topology.

Repository: `a-j-rz/agent-choir-studio`.

---

## 2. Why it existed

V1 was explicitly built as grounded preparation for **Project Elbereth** — a strategic
capability venture to make an enterprise's work intent-led, machine-interrogable and
selectively automatable. Elbereth's architecture has a dedicated **Context Aggregation
layer**: a component that assembles colleague identity, role, permissions, policy, system
state and governance constraints into a usable context object before an Orchestrator
routes work. V1 existed to build first-hand intuition about how that layer could behave —
and fail — across different coordination patterns.

The stated bargain: *the code will never be reused; the judgement will be.*

---

## 3. The fixed problem and the cast

V1 held **one problem constant** and varied only the coordination topology, so that any
observed difference was caused by the topology alone. The subject was **context
aggregation**; the held-constant trigger was a representative enterprise request:

> *"A colleague has requested parental leave — assemble the context needed to support this."*

The mental model was **not** "a panel of equals deliberating." It was *a sharp central
aggregator served by a ring of fast, cheap, narrow context scouts*. The cast:

- **Conductor** — interprets the incoming intent, classifies the request, announces the
  plan. No aggregation, no final output.
- **Persona** *(satellite)* — the colleague's identity dimension: who they are, role,
  level, history relevant to the request.
- **Policy** *(satellite)* — the firm's rules, entitlements, constraints applied to the
  request.
- **System State** *(satellite)* — what the relevant systems would report if queried
  (a *simulated* deterministic read, not a real integration).
- **Risk & Gaps** *(satellite)* — what is unverified, assumed, missing, or requires
  confirmation before any action.
- **Aggregator** *(load-bearing)* — reconciles the satellite outputs into a coherent
  context object; names what is trusted, inferred, missing, and what needs human
  confirmation. This was where model capability earned its cost.

The satellites were deliberately narrow — bounded role, fixed prompt, structured output
schema — so small, fast, cheap models suited them. The Aggregator was the load-bearing
seat.

---

## 4. The three topologies

One trigger, one cast, three ways of coordinating — each a different position in the
iron triangle (below) and a different answer to *how should the parts of a context
object be assembled?*

- **Hub-and-spoke** *(orchestrator-worker; fan-out/fan-in)* — the Conductor dispatches
  to four independent satellites in parallel; they never see each other; the Aggregator
  reconciles all four afterward. Fastest (wall-clock ≈ slowest single satellite), but
  every gap or contradiction between satellites is invisible until the Aggregator catches
  it alone.
- **Blackboard** *(shared external store; linear pipeline)* — satellites coordinate
  through a shared store (SQLite), each reading the accumulating state and appending its
  own fragment before the next runs. Sequential and durable, at the cost of latency
  stacking. Included as a **deliberate anti-pattern** — durable state on the hot path,
  exactly what Elbereth's architecture avoids — so the owner could *feel why* it is an
  anti-pattern, not just read that it is.
- **Token-ring** *(shared transcript; one speaks per turn; everyone reacts)* — satellites
  speak in turn around a shared transcript, each reading everything said so far, for up to
  a capped number of rounds, terminating early on consensus. The only topology with
  genuine cross-examination — and the most exposed to *counterfeit consensus*.

All three were built, committed, and verified live against the real OpenAI API — including
a genuine unstaged satellite failure that proved the non-blocking failure-handling design
held under real conditions.

---

## 5. The iron triangle and the two certainties

The organising frame of the whole instrument:

> **Speed / Cost / Quality-of-reasoning. Pick the corner you are paying for.**

Each topology is a different position inside this triangle; per-role model choice is the
fine-tuning within a position. Architecture is the coarse setting, model choice the fine.

V1 insisted on separating two distinct "certainties":

- **Output quality** — how good the assembly is at the position where assembly matters
  most. This is what the model slider controlled.
- **Epistemic certainty** — how confident one should be that the assembled context is
  actually *correct*. A property of the whole system's reasoning, and a permanent gotcha.

Speed and cost are numbers the trace reads cleanly. **Quality is a human judgement** — the
instrument held everything else still so the model variable was isolated, but the verdict
stayed human. That is the part of the skill that lives in the learner, not the trace.

---

## 6. What V1 proved

The central lesson, and the one that carries hardest into V2:

**Counterfeit certainty.** Multi-agent systems *manufacture* it. An Aggregator receiving
confident, consistent fragments *feels* like it is receiving reliable ground truth. But
consistency measures agreement among agents, not accuracy against reality. The topology
that looks most deliberate (token-ring) is the one most able to produce a confidently
wrong result through sycophancy and anchoring. Self-reported confidence is uncalibrated
and untrustworthy; better proxies are inter-agent tension (did anyone push back?),
whether the gap-finder flagged anything, and consistency across re-runs.

Other things it demonstrated or observed:

- **The iron triangle is real and observable via topology.** Blackboard's latency
  stacking was felt directly (~34s vs ~26s for hub-and-spoke on the same trigger).
  Token-ring's cost compounds per round because each turn re-sends a growing transcript.
- **Aggregation masquerading as synthesis** (hub-and-spoke): the Aggregator can quietly
  concatenate four fragments rather than reconcile them.
- **Framing variance under cold synthesis.** Two hub-and-spoke runs on the same input,
  same model config, back-to-back, diverged on whether the Aggregator *led with a
  conclusion* or *led with a refusal to conclude* — while the underlying caveats were
  near-identical. The one-shot synthesis topology showed *more* framing variance across
  repeats than the transcript-reading topology, the opposite of the naive expectation:
  once a caveat is surfaced in a token-ring transcript it tends to stay surfaced, whereas
  a cold synthesiser reaches for confident or cautious phrasing closer to a coin flip.
- **A failure-masking trap in consensus logic.** By design, a failed satellite counted as
  "nothing more to add" for that round's consensus check — the same non-blocking rule that
  keeps one hung call from stalling the ring. But that means *a genuine four-way agreement
  and a three-way agreement plus one silenced dropout produced an identical consensus
  result.* The trace could not distinguish them. A sharper, mechanistic version of the
  counterfeit-certainty risk: the design choice that prevents the ring stalling can quietly
  manufacture the *appearance* of agreement out of an agent's inability to object.
- **The round cap was mis-calibrated for the lighter model tier.** Cases that "hit the
  round cap" at 3 rounds converged to genuine consensus given a 4th. Round-cap counts were
  partly measuring the cap, not the difficulty of the case.
- **Round count did not track contentiousness.** The most genuinely contentious case
  converged *faster* than clearer ones — clear-cut factual disagreement resolves quickly,
  while genuine ambiguity keeps generating small legitimate additions that stretch out
  convergence without real disagreement.

---

## 7. The stack V1 established

Locked, and carried forward into V2 largely intact:

```text
Language:     Python 3.12
Backend:      FastAPI
Live updates: Server-Sent Events (SSE), hand-rolled via StreamingResponse
Frontend:     Minimal vanilla HTML + JS (no framework, no build step)
Model API:    OpenAI API (direct, no agent framework)
Concurrency:  asyncio
Schemas:      Pydantic
Trace:        JSONL (local)
Config:       .env / environment variables
SCM:          GitHub from commit one
```

Key rejected alternatives and why: **Streamlit** (reruns the whole script per interaction,
fighting long-running async loops); **agent frameworks / OpenAI Agents SDK** (they abstract
exactly the layer — agent-to-agent interaction, aggregation, orchestration — that had to be
in the owner's hands); **Chainlit** (hides the UI/event layer behind its own abstraction).
The orchestration loop being hand-built was the entire point: raw API + asyncio is a few
dozen extra lines, and those lines *are* the lesson.

Models in play were the GPT-5.6 generation (Sol / Terra / Luna). The **load-bearing
principle** governed model selection: capability should be concentrated where it converts
into output quality (the Aggregator seat) and floored everywhere the role is narrow.
V1 tested this by moving the Aggregator model and reading speed, cost and human-judged
quality off the trace.

Structure:

```text
agent-choir-studio/
  README.md
  PROJECT_CONTEXT.md          # intent, reasoning, full design doc
  GLOSSARY_NON_TECHNICAL.md
  app.py                      # FastAPI app: frontend at / plus three SSE endpoints
  frontend/index.html         # vanilla page consuming the SSE stream
  core/                       # llm.py, schemas.py, events.py, trace.py, config.py, ...
  agents/prompts/             # per-role prompts (+ token_ring variants, reference docs)
  orchestrators/              # hub_and_spoke.py, blackboard.py, token_ring.py
  traces/runs.jsonl           # gitignored
```

---

## 8. What carried forward into V2

V2 is a new experiment, not a continuation of V1's code — there is **no code migration**.
But specific judgement carried across:

- **Instrumentation over answers.** Still the governing principle.
- **Stateless-and-traced discipline.** V1's runs were self-contained; V2 hardens this into
  an absolute run boundary.
- **Per-role model selection / the load-bearing principle.** Concentrate capability where
  it converts to quality; floor it elsewhere. V2 keeps model choice as configuration, never
  architecture.
- **Repo-as-truth.** The git repository is the durable record of behaviour; documents carry
  intent. No duplication between them.
- **Counterfeit certainty as a first-class theme.** V2 inherits it wholesale and extends it:
  the Detective's leakage report carries a mandatory self-limitation clause precisely
  because a clean-looking audit *feels* like proof of boundedness and is not — the same trap,
  one level up.
- **The round-cap lesson, applied.** V2 locks a **four-round** token-ring cap directly on
  V1's finding that three was too tight for the lighter tier.
- **The failure-masking trap, guarded.** V2's stop logic must treat a failed figure as
  *not* a "no material change" vote, so a silenced dropout can never be counted as agreement —
  a direct remedy for the V1 observation.
- **The iron triangle**, extended. V1's Speed / Cost / Quality becomes, in V2, part of a
  wider seven-observable frame (see the Experimental Frame document).

---

## 9. The one-line relationship

> **V1 measured the deliberation. V2 measures the harness around the deliberation.**

V1 held the question fixed and made *topology* the observable variable over the iron
triangle. V2 lets the question be anything and makes observable the intelligent envelope
that decides whether to deliberate at all, how, with whom, and how well the bounding holds
while it does.
