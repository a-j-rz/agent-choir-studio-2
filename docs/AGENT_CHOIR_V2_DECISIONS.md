# Agent Choir Studio V2 — Decisions

*The decision record. Every resolved implementation and hygiene choice as decision + rationale
+ rejected alternative, so a cold reader (or a helpful collaborator) does not relitigate a
settled call. The "deliberately not open" locks from the source design also live here. Genuine
open choices are marked as such.*

---

## How to read this

A decision recorded here is **settled.** Do not reopen it merely because a different choice is
defensible — the rationale and the rejected alternative are recorded precisely so the trade was
made once, deliberately. Items explicitly marked **OPEN** are the only live degrees of freedom.

Decisions resolved during the build carry the date they were settled, e.g. **RESOLVED
2026-11-12**, so the record shows what was decided up front and what was decided on evidence.

---

## A. Experimental frame

- **A1 — Purpose is layered, not single.** Historical deliberation is the visible mechanism;
  evidence-discipline-and-leakage is the stated learning target. *Rejected:* leading with the
  leakage framing alone (reads as an AI-cognition paper, loses the legibility of four minds
  actually arguing); and keeping leakage as one gotcha among many (buries the most interesting
  property of the instrument).
- **A2 — Seven observables.** Cost, speed (quantitative); quality, steering, question
  refinement, leakage, retrieval quality (qualitative). *Rejected:* six (leaving retrieval as
  un-named plumbing — it is where the whole epistemic claim is won or lost).
- **A3 — Topology value is observed, never scored.** Read from Round-1-baseline deltas. *Rejected:*
  a scalar "value" metric — it would be counterfeit certainty one level up.
- **A4 — Run-to-run consistency / self-improvement deferred.** Runs are stateless islands;
  cross-run analysis is external-only and never feeds back. A self-improving version is a named
  future build on the arc, not this one. *Rejected:* any compounding loop in V2.
- **A5 — Model-tier steering is parked, not a new experiment.** The same complexity/ambiguity
  rubric that steers topology and cast could equally steer *which model* a question or seat gets —
  a third mapping (score → model tier) alongside score → topology, needing no new observable and
  no new machinery. It is the per-question resource allocation that tier 4 of the mitigation
  hierarchy already names. Not built in V2. *Rejected:* treating it as a separate experiment (it
  is the same idea, not a new one); and adding it as a third live Host dial now (a third
  dynamically steered variable would blur attribution while the machine is still being proven).

## B. Retrieval stack

- **B1 — Hybrid retrieval: BM25 (lexical) + vector (semantic) + explicit merge.** Visible by
  construction. *Rejected:* semantic-only (misses exact-term matches in period language) or
  lexical-only (misses paraphrase).
- **B2 — Fusion by Reciprocal Rank Fusion (RRF).** Simple, no tuning, robust to the score-scale
  mismatch between BM25 and cosine. *Rejected:* normalized weighted merge (needs weight tuning,
  less robust); learned rerankers (opaque, against the legibility ethos).
- **B3 — Vector index: brute-force numpy cosine (or FAISS-CPU) per figure.** For 24 modest
  corpora a vector DB is unnecessary; flat cosine is maximally legible. *Rejected:* Chroma /
  hosted stores (opacity; sends nothing local).
- **B4 — Embeddings: one shared local model across all 24 indexes — `BAAI/bge-small-en-v1.5`,
  run with `sentence-transformers` on CPU.** **RESOLVED 2026-11-21.** 384 dimensions, 512-token
  input, MIT licence. Model id, pinned revision, pooling (CLS), normalisation and the query
  instruction live in `core/config.py` and are asserted at load — each is a silent failure if
  wrong. No chunk may exceed the token limit: checked before embedding, never truncated.
  *Rejected:* `all-MiniLM-L6-v2` (256-token limit would truncate longer sections); `fastembed`
  (defaults to a third-party quantised ONNX export and a library-chosen prefix — two silent
  choices); hand-rolled ONNX inference (legible, but a pooling error would go uncaught); OpenAI
  embeddings API (sends the corpus to the cloud); per-figure embedding tuning (locked out for V2).
- **B5 — 24 physically separate indexes, not one index with metadata filters.** Corpus
  boundaries enforced by construction, not by query hygiene.
- **B6 — What a search shows the figure, and how deep the merge looks.** **RESOLVED
  2026-11-21**, on Phase 2 evidence. Each list contributes its top **8** to the RRF merge
  (k = 60); the figure sees the merged top 8 as passage id, locator and a ~200-character
  preview — **no scores or ranks**, and full text only by opening. Budgets (4 searches, 8 opens,
  context window ≤ 2 within one book) are enforced in code, and a refusal returns an error to the
  model rather than raising. All values live in `core/config.py` and are snapshotted per run.
  *Rejected:* depth 15 or 30 (measured: deeper lists add passages both methods agree on, which
  crowd out the single-method catches — 2 survived at depth 8, 1 at 15, 0 at 30); full text in search
  results (makes opening meaningless, so "passages opened" stops being observable); showing
  scores (invites reasoning about numbers instead of text); prompt-only budgets.
- **B7 — Chunk limits: model-independent words, model-specific token gate.** **RESOLVED
  2026-11-21.** Chunking splits by words (380 for Marcus; paragraph, then sentence, then
  semicolon), so the recipe never depends on an embedding model. Before embedding, every chunk
  is measured in the model's own tokens and the build fails if any exceeds the limit; nothing is
  ever truncated. *Rejected:* chunking by model tokens (re-chunk on every model change);
  allowing truncation (the library cuts silently, so damage would be invisible).

## C. Utilities & orchestration

- **C1 — Researcher runs on the shared default model (see H1), with a search tool, configurable.**
  *Revised 2026-11-12:* originally placed on a stronger tier because source-quality judgement needs
  capability. Under H1 every role starts on the same model and is promoted only on trace evidence;
  the Researcher is a candidate for promotion if its claim-by-claim source handling proves weak in
  Phase 7. *Rejected:* pre-assigning a stronger tier before any evidence exists.
  Native-vs-app-mediated search is **OPEN**, decided after reviewing current tooling.
- **C2 — Ambiguous-stop adjudicator deferred.** Build deterministic stop first; add a narrow
  model adjudicator only if empirically needed. *Rejected:* a stop-controller abstraction up
  front.
- **C3 — Editor is one call, two phases (audit → synthesis), built to split if forced.** The
  target is one call; the code must allow audit and synthesis to become two calls if a long
  token-ring run's context or quality demands, without baking "one call" into the schema.
- **C4 — Detective runs inside the run boundary but terminal and read-only**, emitting its
  verdict to the trace and instrumentation panel (not the main user answer). *Rejected:* a fully
  external post-run utility (would make leakage optional rather than a headline output of every
  run).
- **C5 — What the Oracle receives, and how identity is kept out.** **RESOLVED 2026-11-25.** Our code
  composes the input: the profile's epoch line; the concept; from the figure's compiled Horizon,
  the asker's own sense of that lineage, the target sense and its bridge distance (or, for an
  unreached sense, that it existed outside the asker's world; or, for an unmapped concept, that no
  counterpart is recorded); and the figure's own words on where it met the concept, capped at 300
  characters. Never the figure's name, corpus, dossier, the user's question or the rest of the
  turn. Name tokens in the figure's own words are redacted to "[name]" in what is sent; the trace
  keeps the original, the flag and the redaction; the composed input is asserted free of name
  stems. *Rejected:* epoch only (the Oracle must guess what the asker knows and anchors in modern
  ideas); full context (the Oracle drifts into answering the question); blocking a flagged request
  (loses a legitimate bridge); sending a flagged name (breaks "Oracle knows epoch not identity").
  Descriptions cannot be redacted — the barrier stays soft, as System §7 says.

## D. Trace storage

- **D1 — One directory per run:** `traces/<run_id>/{events.jsonl, raw/, summary.json,
  detective.json}`. V2 runs have far more sub-events than V1 (retrieval, tool calls, rounds,
  Oracle); a per-run directory keeps raw payloads separable and the leakage report readable in
  isolation. *Rejected:* V1's single flat JSONL (drowns); SQLite (premature — adopt only if
  cross-run querying becomes genuinely useful). Exact internal layout is **OPEN** within this
  shape.
- **D2 — Persist raw AND normalized outputs; every normalized object carries `schema_version`.**

## E. Persona & epistemic artefacts

- **E1 — Persona Dossiers and Epistemic Horizons are offline-generated, human-reviewed, frozen,
  versioned repo artefacts** — never runtime-generated summaries. **Horizon method RESOLVED
  2026-11-25:** a shared tree of concept *lineages* — each a sequence of era-specific *senses*
  with dates, the traditions they reached, prerequisites, signalling terms, revealing markers,
  sources and confidence — plus a small per-figure *profile* (horizon year, milieu, traditions,
  exceptions, an epoch-only description for the Oracle), compiled deterministically into each
  figure's Horizon. The compiled file is what is reviewed and committed; a source hash makes it
  detectably stale. Seeded only for the questions in hand and grown on trace evidence.
  *Rejected:* handwritten per-figure Horizons (24 inconsistent lists, no shared structure, no
  bridge distance); importing a full external taxonomy as the backbone (none model senses
  through time, and "comprehensive" becomes the project); unreviewed model-generated Horizons.
  External anchors kept light: a Library of Congress main class and an optional Wikidata id
  per lineage. Dossier generation prompt and regeneration policy remain **OPEN**. *Refined
  2026-11-25, in Phase 3:* terms are matched by stem through BM25's own `analyse()`; terms
  containing digits are rejected; the compiled file is at schema 2. **OPEN, on Phase 3
  evidence:** whether a figure's prompt includes its own era's senses — the 3c A/B ran one turn
  per cell; two of condition B's three Oracle requests quoted the block back.
- **E3 — No figure prompt may contain a breach term.** **RESOLVED 2026-11-25.** The filled prompt
  is checked with `find_breaches` before every turn and the turn raises on any hit. *Rejected:*
  listing the figure's breach terms in its prompt (hands it the modern vocabulary); trusting
  curated text (the guard caught "investors" in the Horizon's own summary before any run).
- **E2 — Corpus texts and built indexes are gitignored; Manifests, chunking config and
  build/acquisition scripts are committed.** The repo carries a reproducible *recipe*, not the
  texts. See G.

## F. Starting subset

- **F1 — Machine-proving four: Marcus Aurelius, Plato, Frederick Douglass, Charles Darwin.**
  Chosen for corpus-shape spread (aphorism / dialogue / oration / scientific prose). **Darwin
  kept over Descartes**: Descartes' treatise shape overlaps Plato's, Darwin's scientific prose
  is unique in the set, and Darwin stress-tests the Oracle hardest. *Descartes* recorded as the
  strongest reserve/swap-in if priority ever shifts to epistemic-discipline fit. This is a
  machine-proving set, **not** a provisional roster; the 24 stands.

## G. Repository & identity hygiene

*Context: the V1 public repo leaked a corporate email address — not in repo contents, but in
commit author metadata. V2 must expose no corporate identity of any kind.*

**RESOLVED 2026-11-12 — all layers set before commit one, and verified:**

| Layer | What was done | Evidence |
|---|---|---|
| Commit identity (G2) | Per-repo identity set to the GitHub `noreply` address before the first commit; "block command line pushes that expose my email" enabled | Every commit's author *and* committer is the noreply address; a deliberate test commit carrying a real address was pushed and **rejected by GitHub (GH007)**, then deleted locally |
| SSH key (G3) | Fresh dedicated key with a neutral comment, reached only through its own host alias with `IdentitiesOnly`, so no other key is ever offered | Verbose SSH confirms only the dedicated key is offered and accepted |
| API key (G4) | Fresh project-scoped key, `.env`-only (mode 600), gitignored from commit one, with an enforced project spend cap | `.env` absent from `git ls-files`; requests fail at the cap rather than overspend |
| Contents (G1) | Every file scanned for identifiers before its first commit | `git grep` over all tracked files returns nothing |

- **G1 — No company / corporate identifier anywhere** — repo contents, commit metadata, SSH key
  comments, or config. Hard rule; the repo is public (at least temporarily) and must not be
  traceable to the corporate identity.
- **G2 — Commit author set per-repo, before commit one**, to a non-corporate address —
  **GitHub `noreply` address preferred** — with "block pushes that expose my email" enabled.
  This is the actual remedy for the V1 leak (which came from `git config user.email`). A
  per-repo `--local` config overrides the corporate global default, but only if set before the
  first commit.
- **G3 — Fresh SSH key with a neutral comment** (`ssh-keygen -C "<neutral>"`), because the
  default key comment is `user@host` and on a corporate machine that carries a corporate string.
  Separate concern from G2 — the key authenticates the push, it does not author the commit.
- **G4 — Fresh, project-scoped API keys under the `axiontide.com` identity, `.env`-only,
  gitignored from commit one.** Key hygiene and account separation — **explicitly not** the
  email remedy (keys were never the leak vector).
- **G5 — The three layers (G2 author, G3 key comment, G4 API keys) are independent.** Doing one
  does not cover the others; a pristine SSH key with an unchanged git config reproduces the exact
  V1 leak. All three set at setup.
- **G6 — Repo is public for the duration of the build; visibility afterwards is the owner's call,
  made at the end.** *Revised 2026-11-12* from "public only as a temporary verification window,
  then private".
  Claude Code retains full access via the local clone throughout (public/private is irrelevant
  to it). This chat surface can fetch the repo only while public; once private, the standalone
  context pack is the sole re-grounding artefact — which is why the pack embeds all context and
  assumes no repo access.
- **G7 — The existing V1 repo's historical commits still contain the corporate address.**
  Leaving, history-rewriting, or deleting V1 is the owner's separate call and is **not** part of
  the V2 build; the G2 fix does not reach backwards into V1.

## H. Model identifiers

- **H1 — Every role starts on one model, `gpt-6-luna`; reasoning effort is the per-role dial; a
  seat is promoted only on trace evidence.** **RESOLVED 2026-11-12**, after verifying current
  names, pricing and tool support against OpenAI's model pages. The originally intended tiered
  dispositions (Host on a mid tier, figures and Oracle on the cheap tier, Editor and Detective on
  the strongest) are kept as *hypotheses about where capability converts to quality*, to be tested
  rather than assumed. The **Editor** is the likeliest first promotion: in Phase 5 its first real
  run is repeated on a stronger tier over the *same* frozen deliberation, and the two syntheses are
  compared side by side — V1's Aggregator test, one variable at a time. If the Editor is promoted,
  the Detective becomes the only audit seat still sharing the figures' model, and is next to
  examine. Model choice remains configuration, not architecture, in one config location.
  *Rejected:* fixing the tiered mapping up front (assumes the answer the instrument exists to
  measure); a single model with no per-role dial (removes the cheapest way to differentiate seats).
  *Refined 2026-11-12, from Phase 1 evidence:* **effort is a ceiling, not a floor** — the Editor
  at `high` reasoned for zero tokens on an easy task, so effort *permits* deliberation and only
  costs more when the task uses it. Hence the order for a struggling seat: **raise effort first,
  promote the model second.** Effort is the fine dial, the model the coarse one, topology coarser
  still. And if a seat struggles on a task it judges easy, more effort won't help — that points
  straight at promotion or at the prompt.
- **H2 — The Responses API is the only model-call surface.** **RESOLVED 2026-11-12.** Current
  models require it for tool calling (or allow Chat Completions tool calls only with reasoning
  switched off), and a single call shape keeps the Phase 1 model-call wrapper simple. Proven live
  by the Phase 0 spike (`spikes/`). *Rejected:* Chat Completions, as in V1 (a dead end for tool
  calling on the current generation).
- **H3 — Re-verify model names at each phase that first uses a new seat.** Names and pricing
  drift; the page for any model is checked before it enters config.
- **H4 — Contributions arrive as structured outputs, parsed item by item.** **RESOLVED
  2026-11-21.** A figure's final answer is constrained by a JSON schema (`text.format`). Each
  output message item is parsed separately and exactly one must validate; anything else fails
  loudly with the texts in the trace — never repaired, never guessed. (`gpt-6-luna` has been
  reported to return an extra message item occasionally.) *Rejected:* a "submit contribution"
  tool (an extra round trip every turn, and it blurs "wants a tool" with "is done"); free text
  parsed afterwards (fragile).

## I. Documentation layout

- **I1 — The non-technical glossary lives at the repo root; the rest of the pack lives in
  `docs/`.** **RESOLVED 2026-11-12.** The glossary is the doc a non-engineer opens first, so it
  sits beside the README, as in V1. One copy only, keeping its full name so every reference in
  the pack still matches. *Rejected:* keeping it in `docs/` (buried for its main reader);
  duplicating it in both places (two copies drift).

---

## J. The Host

- **J1 — Three structured calls, model judges, code enforces.** **RESOLVED 2026-11-25.** Call 1
  triage and framing; call 2 classification and scoring; call 3 cast. No tools, one round trip each.
  The model makes every judgement; code does every rule: totals, the highest unit, the threshold,
  topology and its rule string, and the checks on outcomes, archetypes, units and the cast. The model
  has no field for a total or a topology, so "no Host override" holds by construction. *Rejected:* one
  call (no cheap exit after triage; scoring would see the raw wording); one call per step (archetypes
  and cast are coupled); an agentic Host with tools (System §3: a governed specification, not an
  improvising agent).
- **J2 — Each call sees only its own inputs.** **RESOLVED 2026-11-25.** Call 1: the original
  question. Call 2: the canonical question only. Call 3: the canonical question, the archetypes and
  the roster, never the scores or the original wording. Interpretive ambiguity is therefore scored on
  what remains after triage. *Rejected:* every call sees everything (contamination invisible in the
  trace); scoring sees both wordings (double-counts ambiguity triage has already resolved).
- **J3 — The answer criterion.** **RESOLVED 2026-11-25.** Call 1 writes, with the canonical
  question, one sentence saying what a response must address. It stays in the decision record; the
  Choir never sees it. The Editor uses it in Phase 5. *Rejected:* sending it to the Choir (breaks the
  locked boundary); a third figure status (self-assessed relevance); no criterion (the standard would
  live in the Editor's private reading).
- **J4 — The Choir boundary, in three layers.** **RESOLVED 2026-11-25.** `ChoirInput` (canonical
  question and fact pack, frozen, `extra="forbid"`) is the only type a figure will receive. The
  canonical question is written before classification exists, by a prompt with no archetype or rubric
  vocabulary. A tripwire fails the run if the canonical question introduces Host phrases absent from
  the original (exact phrases; hyphen, underscore and space equivalent). Plain-word framing is not
  caught; that stays with a reader. *Rejected:* one object with a do-not-forward convention; a
  word-level label guard (false failures on "economic"); a model check of the restatement (a
  cross-checking pass, out of scope).
- **J5 — Triage outcomes in Phase 4.** **RESOLVED 2026-11-25.** Every outcome completes the run;
  the outcome is a separate field from run status. `clarify` is terminal until Phase 5.
  `reframe_or_reject` with a suggested question records `reframed`, without one `rejected`.
  *Rejected:* a separate call for direct answers; deflections recorded as failures.
- **J6 — The degenerate cast: assess first, record the gate as a prediction.** **RESOLVED
  2026-11-25.** Every roster figure is assessed (reason, then rating) before selection; corpus
  suitability is judged only from the supplied manifest and is `unassessable` exactly when no corpus
  is built. The cast stays exactly four (locked). Where the gate would reject, code records
  `would_reject`; Phase 5 tests it against retrieval. A "no viable panel" stop is parked for Phase 9.
  *Rejected:* a variable cast of 2–4 (re-specifies the ring, the stop rule and the failure rule; adds
  a third steered variable; and lets a coarse metadata judgement pre-empt the figure's finer one at
  retrieval).
- **J7 — Clarify and correction need an in-run pause; it is built once, in Phase 5.** **RESOLVED
  2026-11-25.** Resubmitting as a new run cannot serve the correction boundary: the new run's Host
  could choose a different cast from the one the user reviewed. *Rejected:* building the pause in
  Phase 4 before its necessary user; two mechanisms.
- **J8 — Rubric anchors, calibrated by blind readers.** **RESOLVED 2026-11-26.** The anchors live
  in `prompts/host_score.md` and are versioned by its hash (v2: `76b8a055…`). Value conflict counts
  foundational beliefs as well as competing goods, judged by the broad middle of informed opinion;
  ambiguity is scored as a reader who did not write the question, and readings that lead to the same
  deliberation don't count; a domain is a field of knowledge, and 2 needs the answer to turn on a
  named interaction; challenge value 2 needs premises an exchange could test. Every dimension starts
  at 0, and each rationale ends with why the score is not one lower (or, for a 0, not one higher). Calibrated against two
  independent blind readers on fresh questions; questions seen while writing a prompt are regression
  checks only. *Rejected:* unanchored scoring (unstable by construction); calibrating toward a
  wanted topology (a quiet threshold override); tuning until one reader's numbers match (the target
  is convergence).
- **J9 — Prompt hygiene.** **RESOLVED 2026-11-25.** One stable prompt per call, hashed into every
  trace; variable content only in input items; no worked examples; test questions chosen after the
  prompt is frozen and never in it; each prompt asserted at load free of vocabulary its call must not
  see. *Rejected:* few-shot examples (imprinting); templated instructions (no meaningful hash, no
  cache).
- **J10 — `insufficient_corpus_basis`: OPEN, hypothesis stated.** For Phase 5 to build against and
  confirm or revise. Figure side, checkable in code: no declaration without at least one search, and
  the declaration states what was searched for and what was missing. Editor side, against the answer
  criterion: answered / answered a neighbour / declined on evidence / over-declared / under-declared.
  The Host's `would_reject` is the third view. Whether the status needs a partial form is a Phase 5
  question.

---

## Locked product behaviour (do not reopen during implementation)

Carried from the source design as settled: exactly four figures per run; roster of twenty-four;
Host / Choir / Editor naming (+ Detective added in V2); Researcher and Oracle as utilities; only
hub-and-spoke and token-ring (blackboard removed); 0–4 → hub-and-spoke, 5–10 → token-ring; no
Host threshold override; four-round token-ring cap; reasoned early stop; Round 1 blind baseline;
deterministic seat rotation; one outstanding direct question per figure; two unresolved direct
challenges per figure; historical corpora primary-source only; the figure chooses its own corpus
searches; 24 physically separate indexes; one shared embedding configuration; Oracle knows epoch
not identity; Oracle interactions private to the requester; no Oracle caching; no MCP for corpus
retrieval; Editor cannot independently search corpora; runs stateless from one another;
previous-run traces never enter runtime; one failed figure degrades, two hard-fail; Host /
required Researcher / Editor failure hard-fails; `insufficient_corpus_basis` is not failure; raw
plus normalized outputs persisted; `schema_version` on normalized objects; full Editor audit
expandable, main answer clean; disposition labels `recommended_conclusion` / `balanced_split` /
`insufficient_basis`; "What would change the answer?" mandatory.
