# Agent Choir Studio V2 — System

*The architecture in prose: the roles, their contracts, the stateless run boundary and the
technology posture. This is the* what *. The* why *lives in the Experimental Frame; the
orchestration mechanics live in Topology & Steering; the historical-agent detail lives in
Choir & Corpus.*

---

## 1. The visible narrative

The user-facing sequence is deliberately simple:

> **Host → Choir → Editor → Detective**

Behind it sit two bounded utilities the user does not see as "voices":

- **Researcher** — current, decision-relevant facts, when the question needs them.
- **Oracle** — a neutral modern-concept bridge for a historical figure that hits a concept
  beyond its lifetime.

Five structural roles (Host, the four-figure Choir, Editor, Detective) plus two utilities
(Researcher, Oracle). The Detective is a fifth structural role added in V2; it runs last and
read-only, and is specified in full in `AGENT_CHOIR_V2_LEAKAGE_AND_DETECTIVE.md`.

---

## 2. The internal causal sequence

The simple narrative unpacks into this ordered internal flow. Nothing from a previous run
enters it (see §8).

1. original user question, preserved verbatim;
2. sufficiency / admissibility check — including **deliberation triage** (should this even
   be deliberated, or simply answered?);
3. optional single clarification;
4. optional "Before we go on, what do you think?" when the user's own view clarifies intent;
5. current-fact sufficiency check;
6. optional Researcher work;
7. canonical restatement of the question;
8. decomposition (single / compound / nested);
9. archetype assignment;
10. complexity scoring;
11. cast selection (exactly four figures);
12. topology selection (from the locked score threshold);
13. Choir deliberation;
14. Editor audit;
15. Editor synthesis;
16. Detective leakage audit over the frozen trace.

---

## 3. Host

The Host **does not answer the substantive question.** It is a governed, versioned
specification, not a free-form agent that can improvise policy.

Its contract:

- preserve the original question verbatim;
- check sufficiency and admissibility, and **triage** — some questions should be answered
  directly (a maths fact), reframed, or rejected rather than deliberated;
- ask at most one targeted clarification at a time, and only when ambiguity would
  *materially* change interpretation, factual requirements, cast, topology or answerability
  (the clarification threshold is deliberately high);
- optionally ask the user for their own starting view when it materially clarifies intent —
  but this view is **never** passed to the Choir and **never** used to pick a sympathetic or
  adversarial panel;
- determine whether current facts are missing and invoke the Researcher if so;
- transparently restate the canonical question;
- decompose as single / compound / nested;
- assign one primary and up to two secondary archetypes;
- score deliberative complexity;
- select exactly four historical figures from the roster;
- select topology from the locked score threshold;
- expose all of its decisions and rationale to the user and trace;
- **not** send its classification, scoring rationale, cast rationale or near-miss candidates
  to the Choir.

Before the Choir begins, the user may correct the Host's interpretation, factual premises or
omitted context. The user may **not** override the selected cast or topology. A valid
correction causes framing, research decision, scoring, cast and topology to be recomputed,
and the decision delta is logged. (Full mechanics in Topology & Steering.)

---

## 4. Choir

The Choir is the **exactly four historical figures** selected for this run. They do the
substantive reasoning. Each figure is bounded by, and may draw only on:

- its own primary-source corpus (searchable only by that figure);
- its own frozen Persona Dossier;
- its own frozen Epistemic Horizon;
- allowed modern facts from the user and the Researcher;
- Oracle bridges it explicitly requested;
- in token-ring, only what other figures actually said in the current transcript.

A figure may **not** silently rely on modern pretrained knowledge outside those channels —
this is the discipline the Detective later audits. Full corpus, retrieval, dossier and
per-figure rules are in `AGENT_CHOIR_V2_CHOIR_AND_CORPUS.md`.

---

## 5. Editor

The Editor performs **one model call with two explicit phases**: a critical audit, then a
final synthesis. It does not debate and does not become a fifth worldview.

It **may**: inspect the Host's framing and orchestration decisions; inspect the exact
historical passages the Choir cited and their bounded surrounding context; inspect
Researcher supporting extracts; audit evidence fidelity, modern-knowledge leakage, anchoring,
counterfeit consensus and topology value; distinguish ignored from addressed-but-unresolved
challenges; distinguish empirical, normative and mixed disagreement; reject or qualify a
modern factual premise the Researcher evidence does not support; preserve unresolved
disagreement; recommend a conclusion when justified; and state what would change the answer.

It **may not**: independently search any historical corpus; call the Researcher or Oracle;
invent substantive reasoning absent from the deliberation; or infer that a figure changed its
mind unless that figure explicitly declared it.

The final synthesis preserves the figures' **reasoning attribution, not their rhetorical
pastiche** — the Editor writes coherently in its own voice while keeping material lines of
reasoning visibly tied to their figures. It carries a disposition label
(`recommended_conclusion`, `balanced_split`, `insufficient_basis`), a one-sentence rationale,
points of convergence, unresolved disagreement, visually-distinguished modern vs historical
citations, and — mandatory in every run — **"What would change the answer?"** No numerical
confidence score.

*Design note:* "one call, two phases" is the target. For a long token-ring run the Editor's
input (full transcript + all cited passages + bounded context + Researcher extracts + Oracle
bridges + Host rationale) is large; the Editor should be built so audit and synthesis *can*
split into two calls if context or quality demands, without that assumption being baked into
the schema.

Note the deliberate separation of concerns: the Editor audits leakage *incidentally* as one
of its categories, but the **Detective** owns leakage as a dedicated, adversarial, terminal
audit — because the agent that produced the synthesis is the wrong agent to certify it clean.

---

## 6. Researcher (utility)

Supplies **current, decision-relevant facts** needed to frame the question responsibly. It is
not an essay writer and makes no policy conclusions. It works claim-by-claim, preserves
credible disagreement between sources rather than flattening it, and **never fabricates a
missing quantitative premise.** The Host controls when it runs. Only *distilled facts and
uncertainty* reach the Choir; full research material stays trace-visible. Full steering,
budget and source-hierarchy rules are in Topology & Steering.

---

## 7. Oracle (utility)

A neutral contemporary concept bridge, triggered only by an explicit historical-agent
request. Its governing rule:

> **The Oracle may tell you what the modern world contains. Your corpus determines what you
> think about it.**

The Oracle knows the asker's **epoch / Epistemic Horizon**, not the figure's identity,
dossier, worldview or corpus. It explains an unfamiliar modern concept minimally and
neutrally; it does not argue, advise, interpret the corpus, or suggest what the figure should
conclude. It may legitimately return that a concept *cannot be faithfully bridged* into the
supplied horizon — a valid outcome. Full budget and per-turn rules are in Choir & Corpus.

*Honest caveat:* "knows the epoch, not the identity" is a soft barrier. An epistemic horizon
specific enough to be useful is often nearly identifying. This is acceptable because the
Oracle's job (neutral concept explanation) is low-sensitivity to that leakage — but the
separation should not be oversold as a real information barrier.

---

## 8. Stateless run boundary

Each run is a **closed, stateless execution.** No previous run, trace, critique, retrieval
path, cast, topology, score, historical answer, Editor synthesis or Detective verdict feeds
into a later run. This applies to every runtime role — Host, Researcher, Choir, Oracle,
Editor, Detective.

> **Run = isolated execution. Trace = record of that execution. Experiment = external
> comparison across completed traces.**

Completed traces may be analysed externally, after the fact, observationally — and that
analysis never alters subsequent runs. This is a **hard property**, not a limitation V2
apologises for: statelessness at runtime is exactly what makes cross-run analysis
trustworthy. A self-improving outer loop that lets post-run analysis propose governed,
versioned, human-approved changes is named as a **future** possibility only; V2 does not
self-modify.

---

## 9. Technology posture

The deliberately simple stack, carried from V1:

```text
Language:     Python 3.12
Backend:      FastAPI
Live updates: Server-Sent Events (SSE)
Frontend:     Minimal vanilla HTML + JS (no framework, no build step)
Model API:    OpenAI API (direct)
Concurrency:  asyncio
Schemas:      Pydantic
Trace:        local structured artefacts (see Trace & Instrumentation)
Config:       .env / environment variables
SCM:          GitHub from commit one
```

Hard "do nots", each protecting the thing being learned:

- **No agent framework** (LangChain, OpenAI Agents SDK, CrewAI, …). The orchestration loop
  *is* the lesson; a framework abstracts exactly what must stay in the owner's hands.
- **No MCP for corpus retrieval.** Corpus access is local function/custom tools mediated by
  the FastAPI process, so retrieval mechanics stay visible.
- **No hosted vector stores** by default. Corpus and indexes stay local and inspectable.

**Per-role model disposition** (configuration, never architecture — keep it in one config
location, and *verify current model names, pricing and API/tool support against official
documentation before relying on them; names drift*):

| Role | Disposition | Currently intended |
|---|---|---|
| Host | Capable orchestration model | GPT-5.6 Terra class |
| Historical figures | Fast/cheap capable model | GPT-5.6 Luna class |
| Oracle | Same narrow class as figures | GPT-5.6 Luna class |
| Editor | Strongest reasoning model | GPT-5.6 Sol class |
| Detective | Strong reasoning model (adversarial audit) | Editor-class; verify/tune |
| Researcher | Capable + search-capable | Choose deliberately after reviewing current tool/search support |

The **load-bearing principle** (from V1) governs the pattern: concentrate model capability
where it converts into quality (Editor, Detective, Host), floor it where the role is narrow
(figures, Oracle). Model choice is the fine-tuning within a topology's position on the iron
triangle; topology is the coarse setting.
