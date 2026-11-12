# Agent Choir Studio V2 — Conceptual Glossary

*The project's own vocabulary, for a reader who follows the ideas but wants the terms pinned
down. Pairs with the stack-literacy glossary
([`AGENT_CHOIR_V2_GLOSSARY_NON_TECHNICAL.md`](../AGENT_CHOIR_V2_GLOSSARY_NON_TECHNICAL.md), at the
repo root), which covers the plumbing underneath, with pictures. Definitions here are the project's meaning, not the general one.*

---

## The frame

**Instrumentation over answers.** The governing principle. The polished final answer a run
produces is useful but secondary; the real object of study is the *trace* — how the system framed,
routed, retrieved, deliberated, stopped, and where it leaked. The input is a trigger, not the
subject.

**The paradox.** The central idea of V2: *what makes LLMs powerful reasoning tools is that they
know everything; what makes them flawed components of a near-deterministic system is that they know
everything.* You cannot bound a general model to only-supplied information; you can only engineer
toward it and measure where it fails.

**The seven observables.** What each run makes observable. Two quantitative — **cost** (token
spend) and **speed** (latency). Five qualitative — **quality of outcome** (is the synthesis good),
**steering** (was the topology + cast routing apt), **question refinement** (was it framed/triaged
well), **leakage** (how bounded the figures stayed and how the bound broke), and **retrieval
quality** (did figures find and cite the right passages). Quality lives in human judgement, by
design.

**The iron triangle.** Speed / cost / quality-of-reasoning — pick the corner you are paying for.
Carried from V1. Topology is the coarse setting on the triangle; per-role model choice is the
fine-tuning. In V2, **leak-tolerance** is effectively a fourth dial on the same panel.

**The four-tier mitigation hierarchy.** The ways to bound a general LLM to supplied information,
cheapest and leakiest first: (1) prompt + audit *(what V2 does)*; (2) cross-checking LLMs *(named,
not built)*; (3) purpose-trained SLMs *(structural boundary, but trades away capability; not
attempted)*; (4) resource allocation — because none is perfect, the real act is choosing a point on
accuracy/speed/cost, **per use case and sometimes per question.**

**Deliberation triage.** The Host's decision *not to run* the machine when a question does not
warrant it (`4 × 9 = 36` needs an answer, not a four-figure deliberation). The cheapest,
highest-leverage act in the system — every question correctly deflected saves 100% of its cost and
latency.

**Counterfeit certainty.** Carried from V1: a set of agents agreeing *feels* like reliable ground
truth, but consistency measures agreement among agents, not accuracy against reality. Recurs in V2
one level up — a clean-looking leakage report feels like proof of boundedness and is not. And
*across runs*: two runs agreeing with each other measures stability, not correctness — the Phase 0
spike produced two identical answers that both missed the same evidence.

**Counterfeit completeness.** Retrieval's version of counterfeit certainty: an answer that looks
whole because the evidence it never saw leaves no trace in it. A figure cannot notice a passage its
search failed to surface, so a thin retrieval produces a confident, clean-looking answer. First seen
in the Phase 0 spike; the reason retrieval quality is an observable and both candidate lists are
kept in the trace.

---

## The roles

**Host.** The governed orchestrator. Frames, triages, researches-if-needed, classifies, scores,
selects the four figures and picks the topology. Does **not** answer the substantive question. In
effect, a per-question resource allocator.

**Choir.** The exactly four historical figures selected for a run. They do the substantive
reasoning, each bounded to its own corpus, dossier, horizon and sanctioned modern channels.

**Editor.** Audits the deliberation and writes the final synthesis in one two-phase call, in its
own voice, attributing reasoning to figures without impersonating them. Not a fifth worldview.

**Detective.** The fifth, terminal, read-only role. Reads the frozen trace and hunts for
**leakage** — knowledge a figure used that no sanctioned channel accounts for. Produces a standalone
report. Separated from the Editor because the agent that wrote the answer is the wrong one to
certify it clean.

**Researcher** *(utility)*. Supplies current, decision-relevant facts, claim-by-claim, preserving
disagreement. Not an essayist; never fabricates a missing quantitative premise.

**Oracle** *(utility)*. A neutral modern-concept bridge a figure may request when it hits something
beyond its lifetime. Knows the epoch, not the figure's identity. Tells the figure what the modern
world contains; the figure's corpus determines what it thinks about it.

---

## The historical agents

**Corpus.** A figure's approved body of **primary authored material only** — the sole evidence it
may reason from at runtime.

**Corpus Manifest.** The frozen record of *what evidence exists* for a figure: works, translation,
chronology, provenance, rights, exclusions. If a work is not in the Manifest, the figure may not use
it.

**Persona Dossier.** The frozen, human-reviewed derivation of *how a figure reasons*, structured as
**Logos** (reasoning style), **Ethos** (deliberative temperament) and **Pathos** (rhetorical voice),
plus tensions and provenance. Supplied in full on every runtime call. Priority order: evidence
fidelity → deliberative integrity → temperament → voice.

**Epistemic Horizon.** The frozen record of *what a figure could plausibly know without a modern
bridge* — lifetime/epoch, available concepts, post-lifetime concepts, anachronism hazards. The
figure uses it to know when to call the Oracle.

**Machine-proving four.** Marcus Aurelius, Plato, Frederick Douglass, Charles Darwin — the subset
the whole machine is proved on before the roster is scaled toward twenty-four. Chosen for
corpus-shape spread, not fame. **Not** a provisional roster; the twenty-four stands.

---

## Leakage

**Leakage (contextual / epistemic).** A figure using *illegitimate* knowledge — modern facts not
supplied, its own biography from pretraining, post-lifetime concepts the Oracle didn't bridge, or
knowledge of the panel beyond the transcript. The boundary is *selective* (no illegitimate
knowledge), not absolute (a figure needs general competence to read its corpus).

**Hard breach.** Trace-verifiable, high-confidence leakage: a concept/fact used that no sanctioned
channel accounts for.

**Soft breach.** Flagged, low-confidence leakage: reasoning that *smells* post-epoch but can't be
pinned to an unsanctioned channel.

**Oracle cross-check.** The Detective's deterministic core: for every out-of-horizon concept a
figure used, was there a *logged Oracle bridge*? A modern concept with no matching Oracle call is a
near-certain hard breach — detectable from records, not judgement.

**Self-limitation clause.** The mandatory line in every Detective report: soft-breach detection is
done by a model carrying the same contamination it hunts, so *absence of flagged breaches is not
evidence of clean reasoning.* Without it, the report manufactures counterfeit certainty.

---

## Orchestration terms

**Archetype.** One of eight question types (Moral/Ethical, Strategic/Competitive,
Political/Institutional, Economic/Systemic, Psychological/Interpersonal, Scientific/Epistemic,
Personal/Existential, Social/Cultural). The Host assigns one primary + up to two secondary; they
influence cast selection but don't reserve seats.

**Complexity rubric.** Five dimensions (value conflict, interpretive ambiguity, cross-domain
interaction, challenge value, consequence/stakes), each scored 0–2, max 10.

**Topology threshold.** The locked routing rule: **0–4 → hub-and-spoke, 5–10 → token-ring.** No
qualitative override.

**Hub-and-spoke.** Topology where the four figures reason independently, once each, in parallel;
the Editor reconciles afterward. Fast; contradictions between figures surface only at the Editor.

**Token-ring.** Topology where figures deliberate in turn around a shared transcript for up to four
rounds, reacting to each other. Round 1 is blind. The only topology with genuine cross-examination;
the most exposed to counterfeit certainty.

**Blackboard.** A third topology from V1 (shared external store; a deliberate anti-pattern),
**removed in V2.**

**Round 1 baseline.** The figures' independent first-round positions, persisted so any value added
by interaction is legible as a *delta* from it. Topology value is observed from these deltas,
**never scored.**

**Seat rotation.** In token-ring, the deterministic per-round reassignment of figures to speaking
positions (R1 ABCD → R2 BCDA → …), to distribute first/last-speaker bias.

**Direct question** vs **direct challenge.** Two structured token-ring objects. A *question* is a
procedural obligation (max one outstanding per figure; must be answered first; blocks early
termination). A *challenge* is visible contention (max two unresolved per figure; no hard response
obligation; doesn't block termination).

**`insufficient_corpus_basis`** vs **`cannot_access_corpus`.** The first is a *valid epistemic
outcome* — retrieval worked but the corpus gives no defensible basis; the figure stays in the panel.
The second is a *figure failure* — retrieval broke technically; no pretrained fallback allowed.

**Disposition label.** The Editor's verdict shape, exactly one of `recommended_conclusion`,
`balanced_split`, `insufficient_basis`. No numerical confidence score.

**"What would change the answer?"** A mandatory element of every synthesis — what new evidence or
argument would move the conclusion.

**Model-tier steering** *(parked)*. Using the same complexity rubric that picks topology and cast to
also pick *which model* a question or seat gets — a third mapping from one score, needing no new
machinery. Named in Decisions A5; not built in V2.

---

## Discipline

**Stateless run boundary.** Each run is a closed island; nothing from a prior run enters a later
one. *Run = isolated execution; Trace = record of it; Experiment = external comparison across
completed traces.* A hard property, not a limitation.

**The load-bearing principle.** Concentrate model capability where it converts into quality (Editor,
Detective, Host), floor it where the role is narrow (figures, Oracle). Carried from V1 — and in V2
treated as a hypothesis to test seat by seat, not an assignment (see *promotion on evidence*).

**Effort is a ceiling, not a floor.** Reasoning effort sets how much a model *may* deliberate, not
how much it *will*. Found in Phase 1: the Editor at `high` reasoned for zero tokens on an easy
task. So raising effort is cheap — it costs only when used — but it can't force depth on a task
the model judges easy.

**Promotion on evidence.** Every role starts on one cheap model, with reasoning effort as the
per-role dial; a seat moves to a stronger model only when its own trace shows the cheap one costing
quality, proven by re-running the same frozen input on both and comparing side by side
(Decisions H1). The Editor is the likeliest first. Tier 4 of the mitigation hierarchy, applied to the
instrument itself.

**Repo-as-truth.** The git repository is the durable record of *behaviour*; the documents carry
*intent and reasoning*. No duplication between them.
