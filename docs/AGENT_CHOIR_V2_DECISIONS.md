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
  per cell; two of condition B's three Oracle requests quoted the block back. Phase 5 runs on
  condition A and on the stand-in prompt (K2); both questions stay OPEN.
  *Refined 2026-11-28 (C1):* coverage-probe questions are generated blind, per figure: one builder
  call naming no figure, year or context, written once and never curated (Marcus's were the Phase 3
  questions in hand). No-imprint rule: nothing in a profile, milieu or lineage may originate from
  example questions or working conversation; every entry traces to a source about the world. A term
  belongs to a sense only if it names that sense's concept as it existed at the sense's date; a
  later product or system gets its own later sense. Self-collision gate: no breach term may match
  the figure's own chunk text by stem sequence; made permanent in T2 (`scripts/horizon_gate.py`,
  K11). Known bias, recorded and not deepened by us: the tree's first 15 lineages were shaped
  by three owner-chosen questions.
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
  question. *Phase 5 design (K1, K7):* the figure-side fields arrive with `Contribution` schema 2;
  the Editor's five classes are its per-figure audit entry.

---

## K. Phase 5 — hub-and-spoke and the Editor

Agreed 2026-11-26 as design, before any Phase 5 code: these record what will be built, not what has
been. Each item is updated with evidence as its slice lands.

- **K1 — Two tracks that meet at the first four-figure run.** **RESOLVED 2026-11-26.** *Content:*
  corpora, Manifests and compiled Horizons, one figure at a time — Darwin, then Plato, then
  Douglass — through Marcus's pipeline (design here; a recipe-only offload; verification; the token
  gate on the owner's machine; profile, lineages, compile and coverage probe). *Machinery:* 5a the
  four-figure substrate (per-figure event labels; figure and embedding loads off the event loop;
  `figure_turn` takes `ChoirInput`; `Contribution` schema 2 with the J10 figure-side fields; four
  turns concurrent and isolated, one logged retry, the degraded / hard-fail rule; the independent
  baseline persisted); 5b the call-1 revision (K6); 5c the Editor (K7); 5d the Editor model test;
  5e the pause (K8). Machinery is tested offline until all four corpora pass the token gate. Two
  consequences of locked rules: a question the Host routes to token-ring stops after the Host with
  `topology_not_built`, never a silent hub-and-spoke (no threshold override, and token-ring is
  Phase 6); and the Editor model test is an offline script over a frozen Editor input, because
  previous-run traces never enter runtime. Darwin first because he adds one new variable (corpus
  shape) to a pipeline proven on one figure. *Rejected:* Plato first (shape and voice at once);
  serial content-then-machinery (the machinery waits on the slowest work for no reason).
- **K2 — Figure prompts in Phase 5.** **RESOLVED 2026-11-26.** All four figures run on the stand-in
  (`prompts/figure_standin.md`); dossiers stay with Phase 9 and their generation prompt stays OPEN
  (E1). No own-era Horizon block in the prompt (the 3c condition A); E1's question stays OPEN, and
  the compiled Horizon still serves the Oracle and reconciliation. The stand-in changes once, as a
  recorded change with a new hash: "in {translator}'s English translation" becomes an edition phrase
  from the Manifest (Darwin and Douglass wrote in English), and it gains one reading-rule slot from
  the Manifest, empty except for Plato (K4). *Rejected:* dossiers first (four content builds on an
  undesigned prompt, adding a per-figure variable); a short handwritten persona per figure (an
  unreviewed dossier by another name); repeating the Horizon A/B inside Phase 5.
- **K3 — Darwin's corpus.** **RESOLVED 2026-11-26.** *The Origin of Species*, 6th edition (1872;
  Gutenberg #2009), and *The Descent of Man*, 2nd edition (1874; Gutenberg #2300). Horizon year
  1882, knowledge at death, as for Marcus. The 6th edition is his final text, answers later critics,
  and is the first to use "evolution"; *Descent* gives him the moral sense, without which normative
  questions would leave him nearly always declining. Editorial apparatus not by Darwin is stripped.
  *Descent*'s Victorian views on race are primary and stay. *Rejected:* the 1859 1st edition (not
  his final view; inconsistent with a horizon at death); *Origin* alone; *Beagle*, *Expression* and
  the letters (Phase 9, on trace evidence).
  *Built 2026-11-27 (the corpus recipe; slice C1):* sources *Origin* 6th edition (#2009,
  `2b13c852…`) and *Descent* 2nd edition (#2300, `2911dfcc…`), CRLF bytes pinned; fetched 2026-11-27 by rsync from gutenberg.pglaf.org (owner-supplied) while www.gutenberg.org returned 503 —
  **provisional** until a re-fetch from gutenberg.org matches the SHA. *Rule:* keep only prose
  Darwin wrote as argument. Stripped: the Gutenberg wrapper, title and edition matter, *Origin*'s
  three epigraphs, contents lists, part titles, chapter synopses (15 + 21), Dallas's glossary,
  indexes, Huxley's note on the brain, 57 figure captions, two tables, the *Nature* reprint line,
  and *Descent*'s preface sign-off and edition line. Kept: the Historical Sketch, Introductions,
  Preface, all chapters with their Summary sections, the 1876 Supplemental Note. *Footnotes:* all
  stripped (*Origin* 3; *Descent* 1,173, numbered per chapter) by a balanced-parenthesis scanner
  with a strict 1…n sequence per unit; seven source defects handled as exact-marker exceptions
  (five notes missing a closing parenthesis, two duplicate numbers). *Conservation:* non-whitespace
  characters per book, difference 0 for both. *Headings:* *Origin*: 75 italic section headings; *Descent*: 105 all-uppercase section headings (92 and 129
  heading spans including unit titles), except the five ch. XVI "CLASS II–VI" rules, kept as
  body text to match the run-in CLASS I. *Chunking:* a chunk never crosses a heading; Marcus's
  midpoint splitter, unchanged, plus two exclusions — no sentence boundary after a listed
  abbreviation or after initials — guarded by an independent end-of-chunk check. *Ceiling:* at 380
  words five chunks measured 521–530 tokens (dense Latin nomenclature), so `max_words` is 340 for
  Darwin only (Marcus stays 380). *Result:* 1,874 chunks; words min/median/p90/max 27/223/312/340;
  258 sentence-level splits; tokens 36/277.5/387/493, none over 512. `chunks.jsonl` `d4122ff0…`,
  identical on two machines at 340 (three agreed at 380) and rebuilt byte-identically again in the commit pass.
  `book` is the chapter-level unit (`origin-04`, `descent-supplement`…); locators read
  `Origin (1872), Ch. IV — <section>` and `Descent (1874), Pt II, Ch. VIII`, the supplement 1876;
  `translator: null` — Darwin is not a translation, and `list_my_works()` returns it as `None`
  (offline case). The preface sign-off strip is guarded too: removing its marker fails the build
  on "BECKENHAM". *Lessons:* a guard never seen firing is untested — emptying the abbreviation list
  left the 380-word build unchanged while the real failure (initials) sat next to it; all seven source defects surfaced through the strict sequence and balance checks; none was
  silently absorbed. Stale "only Marcus is built" assumptions were
  found in probe fixtures and one expectation; fixtures now derive from the roster, and
  expectations stay explicit literals, updated deliberately when a figure is built. *Rejected:*
  footnotes kept as separate note chunks (little value, more leakage surface); `book` as the whole
  work (context windows would cross chapter breaks); a token-aware splitter (couples the recipe to
  the embedding model); a ceiling of 350 or 360 (too little headroom).
  *Horizon built 2026-11-28 (slice C1):* profile `horizons/profiles/charles_darwin.json`; traditions
  european-modern, european-early-modern and greco-roman (all high) and latin-medieval (medium);
  Oracle epoch "An educated person in Britain in the later nineteenth century.", which deliberately
  omits "naturalist" (C5: epoch, not identity). *No-imprint rule:* nothing in a profile, milieu or
  lineage may originate from example questions or working conversation; every entry traces to a
  source about the world. The latin-medieval basis was first drafted from the very lineage it fixed
  (usury); the owner caught it, and it was rewritten from Darwin's education. *Fixes exposed by a
  second figure:* tea gained a european-early-modern entry (1658); "energy drink" moved from
  caffeine (1819) to a new `energy_drink` sense (1962); "power grid" moved from utility (1882) to a
  new `grid` sense (1926), adding "national grid". Principle: a term belongs to a sense only if it
  names that sense's concept as it existed at the sense's date. *Blind probe:* three questions from
  `scripts/generate_probe_questions.py` (`c6924820…`, 2026-11-27); the coverage probe, live (12
  calls, $0.0068), extracted 45 terms: mapped_beyond 3, near 3, unmapped 39. *Lineage growth:* new
  `climate` (regional, about −400; greenhouse_physics, 1824, available to Darwin; anthropogenic,
  1906; policy, 1992) and `productivity` (labour, 1776; measured, 1911; personal, 1967, medium);
  `messages_at_distance` gains video_call (1964) and internet (1969), and email's prerequisite
  becomes internet; `attention` gains multitasking (1966, medium). Personal boundaries is recorded
  as a gap, not seeded. *Kept out as terms:* bare "adaptation" (Darwin's own word), "climate
  change", "emissions", "productivity" (stems to `product`: 150 hits in Darwin's chunk text),
  "efficiency", "platform", "digital", "optimise". *Self-collision gate:* every breach term, stemmed
  by `retrieval.bm25.analyse`, may have zero stem-sequence matches in the figure's own chunk text.
  Its first run found 5 terms already committed: "tranquilizer"/"tranquilliser" (Marcus's own
  "tranquillity", 18 hits), "inflation" (Darwin 12, Marcus 1), "elasticity" (Darwin 6),
  "reinforcement" (Darwin 1); each was replaced by phrases or removed. Now 0 for both figures (148
  and 102 breach sequences), and shown able to fail (bare "productivity": 150). It was a
  brief-time check, made permanent in T2 (K11). *Re-probe (no calls):* Darwin's unmapped 39 → 16
  (mapped_beyond 13, near 16); what remains is one-offs, boundaries, "optimized", "screen", "tabs".
  The Marcus probe trace's classifications are unchanged by the removals: none of those words occurs
  in it. Compiled files: Marcus `57717ab0…`, Darwin `e33171c4…`, both `--check` current.
  **Closed 2026-11-28:** Darwin's Horizon is compiled, so the gap that barred casting him is closed.
  The candidate code guard stays parked, for C2 and C3: refuse to cast a built figure with no
  compiled Horizon.
- **K4 — Plato's corpus.** **RESOLVED 2026-11-26.** Jowett's translation, 3rd edition; the
  *Republic* from Gutenberg #55201 (Stephanus numbering throughout). Eight dialogues: *Republic*,
  *Apology*, *Crito*, *Phaedo*, *Gorgias*, *Meno*, *Symposium*, *Phaedrus*. Jowett's introductions,
  analyses and notes are stripped. Locators are Stephanus numbers where the source prints them and a
  plain sequence where it does not — never inferred by alignment. Every word Plato wrote is corpus,
  every speaker included; chunks are consecutive paragraphs within the word limit, cut at Stephanus
  sections where they exist, never mid-speech where avoidable, each recording the speakers labelled
  in it. Half the set is narrated rather than scripted (*Republic*, *Phaedo*, *Symposium*), so
  speaker-turn chunking cannot apply throughout. A reading rule (Choir & Corpus §8) reaches the
  figure through the stand-in's slot. *Rejected:* complete works (the *Laws* without Socrates;
  dialogues of doubtful authorship); the *Republic* alone; Socrates' lines only (loses the
  dialectic; presumes Socrates is Plato); a later translation (UK rights).
  *Built 2026-11-28 (the corpus recipe; slice C2):* sources #55201, the *Republic* (Jowett 3rd ed.,
  Clarendon Press 1888; `8a30ff0c…`); #76464, *Dialogues* Vol. II (Jowett 3rd ed., OUP 1892;
  released on Gutenberg 8 July 2025, per Project Gutenberg's record for eBook #76464; `504709b2…`),
  for *Meno*, *Apology*, *Crito*, *Phaedo* and *Gorgias*; #1600 and #1636 (edition not stated by
  Gutenberg; `8b5c599e…`, `ce41cbe9…`), for the *Symposium* and *Phaedrus*. These two are probably
  third-edition text with American spelling: two sibling etexts (*Meno* #1643, *Crito* #1657)
  compared against #76464 showed the same wording apart from speaker labels, inlined notes and
  American spelling (similarity 0.957 and 0.980, nearly all the differences speaker labels; from a
  read-only comparison run in this build session on 2026-11-28, not committed). The five duplicate
  1999 etexts were dropped. Fetched 2026-11-27 by rsync from gutenberg.pglaf.org (owner-supplied);
  **provisional** until a re-fetch from www.gutenberg.org matches the pinned bytes. *Correction:*
  #76464 was in the fetch script; K4 had not named it. *Speaker labels:* normalised to `NAME:` from
  each dialogue's persons list, 1,779 replacements in #76464; an unmapped label fails the build, and
  the guard was shown firing (removing one map entry failed the build); conservation accounts for
  the generated label characters exactly: 14,277 non-whitespace characters, computed label by label.
  *Strip rule:* the corpus is each dialogue's text; everything the edition added is stripped:
  Jowett's introductions, analyses and essays; all sidenotes (746 in the *Republic*, 658 in #76464),
  which are Jowett's interpretation and, as section titles, would put his reading inside Plato's
  corpus; footnotes, page markers, persons lists and scene lines; and Euthyphro and the appendices.
  *Units and locators:* *Republic* Books I–X, and each other dialogue as one unit, chunked by the
  kit's `split_section` over the whole unit. Speech integrity over Stephanus alignment, refining
  "cut at Stephanus sections" above: the Stephanus numbers fall mid-sentence (inline in #55201) or
  against a printed line (the margin of #76464), so they go into the locator as a range: the
  *Republic* by section (`Republic I, 327B–328A`), #76464 by page (`Meno 81–82`), the *Symposium*
  and *Phaedrus* by paragraph sequence (`Symposium ¶14–17`). No number is ever inferred (the *Meno*
  opens "beginning" before its first printed 71); the strip report locates 1,566 Stephanus tokens at
  their source positions (1,355 in #55201, 211 in #76464). *Voice:* `prompt_edition` "in Benjamin
  Jowett's English translation"; the reading rule, verbatim from the Manifest: "Your writings are
  dialogues, and every speaker in them is part of your argument: the positions you refute belong to
  it too. A character's line is not automatically your view, and Socrates does not simply speak for
  you, least of all in the Apology. Reason from where a dialogue's argument comes to rest, and say
  when a reading is interpretive." *The owner's rationale* (owner judgement, in substance): the
  demarcation is drawn where provenance changes; the translator's notes come out; inside the
  dialogues, taking a pen to what Plato said against what Socrates said would go off the objective
  and create complexity creep. *Translator commentary inside the dialogue:* P04, inline
  parentheticals: 34 stripped (*Symposium* 22, *Phaedrus* 12), which in the 1999 etexts are the
  third edition's footnotes, inlined; a Greek word in parentheses is kept only where the English
  does not already carry the wordplay it marks; three readers (ChatGPT, Claude sealed, the owner
  blind), and the owner's reading of *imeros* adopted: Jowett's English "emotion" already carries
  the pun (owner-supplied). P13, square brackets: 13 stripped, 5 kept, by the criterion the owner's
  blind reading refined: supplied words that render what the Greek implies are translation; Plato's
  own Greek words a pun turns on are kept; identifications, alternative renderings, "i. e." glosses
  and explanations of a pun are commentary. *Lesson:* Claude's test, "does the sentence stand
  without it?", sorted these wrongly three times. *Source defects,* each an exact-marker exception,
  never corrected: P01, the *Meno* has no page-70 marker; P02, the *Meno*'s paired notes 7, 8 and 9;
  P03, #76464's notes run 1–78 across the whole file, checked as one bijection; P05, `*Ed. Steph.
  327*`; P06, a footnote missing its closing bracket; P07, a duplicate note 38; P08, `[Footnote:
  11:`; P09, an unnumbered note; P10, `(308}`; P12, `[Sidenote;`; 561E→561A, kept as printed. P11:
  the *Republic*'s introduction apparatus is unvalidated by design, because it is stripped whole.
  *Ceiling:* at 380 words one chunk failed the token gate (*Phaedo* 58–59, 372 words, 552 tokens).
  The cause is the normalised speaker labels: each is one word but several model tokens, so the
  densest chunks (up to 1.48 tokens per word) are labelled exchanges. Lowered to 320, for about 7%
  headroom at that density; Marcus stays 380 and Darwin 340. *Result:* 1,248 chunks; words
  min/median/p90/max 3/200/281/320; 154 sentence-level splits, 0 semicolon-level; tokens
  9/249/353/447, none over 512; conservation difference 0 in all 17 units; byte-identical on two
  machines (`chunks.jsonl` `dbdd6b75…`). The shortest chunk is three words: "Yes, said Glaucon."
  (*Republic* III, 417B). *A metric flaw, recorded:* the recipe's "mid-speech start" counts any
  chunk whose first paragraph lacks a label in a labelled dialogue; in the narrated *Phaedo* and
  *Symposium* that fires on nearly every chunk (329 in all). The real speech breaks are the 154
  sentence-level splits. *Rejected:* the 1999 etexts for all eight; keeping the sidenotes as section
  titles; one chunk per Stephanus page; greedy packing; a token-aware splitter; shorter labels to
  fix the gate.
- **K5 — Douglass's corpus.** **RESOLVED 2026-11-26.** *My Bondage and My Freedom* (1855;
  Gutenberg #202), with its appendix of speech extracts he chose; *Three Addresses on the Relations
  Subsisting Between the White and Colored People of the United States* (Gutenberg #67919);
  *Collected Articles* (Gutenberg #99). Prefaces and introductions by others are stripped. Horizon
  year 1895, knowledge at death. Chunks are consecutive paragraphs within a chapter or speech, each
  recording work, title, and date and occasion. One telling of his life, so near-duplicate passages
  don't crowd RRF's merged slots. *Rejected:* all three autobiographies (three tellings; the pre-
  and post-1851 Douglass mixed); the *Narrative* instead of *Bondage* (the earlier view, no
  speeches); *Life and Times* (a third telling, and Gutenberg's text is the 1881 edition, not the
  1892 revision; the first Phase 9 addition if traces show postwar gaps); third-party anthologies.
- **K6 — The canonical question and clarify.** **RESOLVED 2026-11-26.** One call-1 prompt change,
  one new hash. First-person questions are restated in the third person with the material facts of
  the situation as facts ("Should a person who …"), since a figure may read "I" as itself and never
  sees the clarification exchange. No sub-questions, causes or scope the asker did not raise.
  Clarify asks for one fact only the asker can supply, never what they want, value, feel or think.
  Code checks that `canonical_question` and `clarifying_question` each contain exactly one question
  mark. Proven by the 4a regression questions (seen, so regression only) and a fresh question chosen
  after the prompt is frozen. *Rejected:* first person kept as written; "Should you …" (addresses
  the figure); a model-declared list of changes (a naming rule); a second model checking the
  restatement (cross-checking, out of scope); banned-phrase lists for clarify. *Refined
  2026-11-26, drafting the prompt:* what the asker says matters to them is a fact of the
  situation and is carried; any view they give on what the answer should be is left out (K8 keeps
  the asker's leaning from every seat). *Rejected:* dropping all stated preferences (a personal
  question collapses into a generic one); carrying leanings (the asker's conclusion would reach
  four figures inside the question). No example questions in the prompt (J9). *Landed in 5b:*
  `host_triage.md` `d0195313…` (was `5db7f527…`); the single-`?` checks in code. *5b evidence*
  (21 live calls, read blind by owner and Claude): no clarify asked for values (Phase 4: twice);
  first-person questions restated in the third person with the leaning dropped in all four
  samples; but "one thing only" was met by form and not substance — one `?`, two asks joined by
  "and" (1 of 3 on the offer question, 3 of 3 on blackjack; both readers agree). Blackjack needs
  both facts, and K8 allows one clarify per run, so the rule as written can leave a question
  unanswerable. **OPEN, for 5e:** clarify becomes one question asking only for facts — all the
  facts the answer needs, never values — tested with the answer loop. Readers split on the
  entropy question, now answered directly 3 of 3 (owner: should proceed; Claude: settled physics;
  possibly an effect of "no causes the asker did not raise"), and on whether one of four job
  restatements dropped the stated need to progress. Recorded, not tuned.
- **K7 — The Editor's input and output.** **RESOLVED 2026-11-26.** *In:* the decision record
  (answer criterion, `would_reject`, cast assessments); the original wording and any clarification
  record, read-only; the four contributions; each cited passage in full with one neighbour each
  side; each figure's search query strings; each figure's Oracle bridges, labelled modern. *Out:*
  passages opened but not cited; code's reconciliation and leakage flags (the Detective's, C4);
  candidate lists, figure prompts, anything from another run. *Output:* one schema, `audit` before
  `synthesis`, splittable (C3). The audit carries per figure the J10 class against the answer
  criterion, a check of any `would_reject` prediction against retrieval, evidence-fidelity notes,
  the kind of disagreement, and counterfeit consensus. The synthesis carries the disposition and
  its one-sentence rationale, the attributed answer, convergence, unresolved disagreements naming
  figures, historical citations (figure and passage) apart from modern references (bridges), "What
  would change the answer?", and the missing perspective on a degraded run. *Code checks:* one audit
  entry per figure; attributed figures in the cast; each historical citation a passage that figure
  cited; each modern reference a bridge in the run; the disposition in the locked enum; "what would
  change" non-empty; missing perspective present exactly when degraded. Failures are recorded, never
  repaired (H4). Until the Researcher exists (Phase 7) the only modern material is Oracle bridges,
  so the modern / historical split is built in Phase 5 but properly exercised in Phase 7.
  *Rejected:* the whole trace (audits what it should never weigh); contributions without passages
  (no citation could be checked).
- **K8 — The in-run pause.** **RESOLVED 2026-11-26.** The run task emits `awaiting_user` and waits
  in memory under its run id; `POST /run/{id}/respond` resumes it, with the stream held open. A tab
  closed while paused aborts the run, as now; a configurable timeout (15 minutes by default) aborts
  it with the reason recorded. The slot is removed at finish: state within one run, never across
  runs. *Flow:* call 1 may clarify once; after the answer it runs again, and a second clarify ends
  the run `clarification_unresolved`. After calls 2–3 the correction boundary always pauses, and
  also serves as the confirmation of the canonical interpretation (Topology & Steering §1). One
  correction is accepted; calls 1–3 re-run and code records the decision delta (canonical question,
  scores, topology, cast); no second boundary. CLI and probes pass an explicit flag recorded as
  `correction: auto_accepted`. *"Before we go on, what do you think?"* is asked in the same pause
  when call 1's factual posture is `normative` or `mixed` (a code rule), may be skipped, is asked
  after framing is fixed, and is read by no seat in Phase 5 — recorded in the trace only, for later
  analysis of whether a synthesis drifts toward the asker. *Rejected:* persisting a paused run across
  restarts (production hardening); unlimited corrections (cast override by attrition); passing the
  user's view to call 1 (the Phase 4 leak path) or to the Editor (invites pandering).
- **K9 — The four-figure substrate (slice 5a).** **RESOLVED 2026-11-26**, as design before code.
  *Lanes:* every event carries `role`, the seat that acted (`host`, `figure`, `oracle`, `editor`,
  `system`), and `figure`, whose lane it belongs to (none for Host and Editor); event schema 2. A
  lane view of the trace (`trace.for_figure(id)`) stamps `figure` on every event and raw file name
  (`<seq>-<figure>-<role>-…`) and is the only trace a figure turn receives; one `seq`, one
  `events.jsonl`. *Retry:* the SDK's own retries are off (`max_retries=0`, explicit timeout from
  config); `call_model` retries one failed request once, logged as `round_trip_retry`, on
  connection errors, timeouts, rate-limit 429s and 5xx — never on 400/401/403, a 429
  `insufficient_quota` (the spend cap), an invalid contribution or the round-trip cap. This applies
  to every role; the Oracle's former "no retry" was two silent SDK retries. *Lanes run* as tasks
  awaited as they finish: one failure degrades the run (status `complete`, `degraded` recorded);
  a second cancels the rest (`cancelled_by_hard_fail`) and fails the run; an abort cancels all of
  them. Failure classes: `transient_exhausted`, `contribution_invalid`, `round_trip_cap`,
  `cannot_access_corpus`, `other`. *`Contribution` schema 2:* an `insufficiency` object
  (`looked_for`, `not_found`) present exactly when the status is `insufficient_corpus_basis`,
  enforced as a parse failure; `declared_without_search` and `grounded_without_citations` are
  recorded as check flags, not failures, for the Editor (J10, K7). No partial status yet. *Baseline:*
  `baseline.json`, written once after every lane settles and before any Editor event, on every
  outcome, then named with its SHA-256 by an `independent_baseline` event. *Loads:* the embedding
  model once at server start; each figure's index per run in a worker thread, with `load_ms`
  recorded; a missing or stale vector cache is `cannot_access_corpus` (rebuilding is offline);
  query embedding stays on the loop, timed, until a trace says otherwise. *Routing:* a `token_ring`
  topology ends the run `complete` with outcome `topology_not_built`. *Rejected:* compound role
  labels; `contextvars`; a trace per figure; the SDK's retries; retrying a whole turn;
  `TaskGroup` (cancels siblings on one failure); failing a figure for declaring without a search;
  caching indexes across runs; status `failed` for an unbuilt topology.
  *Amended 2026-11-26, on 5a evidence:* threaded loads shared two process-wide tools across
  threads. The one Snowball stemmer crashed or returned wrong stems under concurrent use (the
  offline probe's clean case failed on a second machine when a lane's Horizon check got corrupted
  stems; a BM25 index built under the same race would have no check), and the embedding model's
  tokenizer is shared the same way. Fix, as design: the stemmer becomes one instance per thread;
  the embedding model gets one owner, a single-worker executor through which everything that
  touches it runs — model load, figure loads, query embedding — awaited by lanes so the loop never
  blocks. This supersedes "query embedding stays on the loop". *Rejected:* a lock (taken on the
  loop thread it freezes the loop, and every caller must remember it); loading all figures before
  the lanes (doesn't cover two runs at once on the server); undoing the threaded loads.
- **K10 — The hub-and-spoke Editor (slice 5c).** **RESOLVED 2026-11-26**, as design before code.
  *Frozen input:* after the baseline, code compiles `editor_input.json` deterministically from the
  decision record, the baseline and the cited passages (each with one same-book neighbour per side,
  marked context), writes it once, names it by SHA-256 in an `editor_input` event, and sends
  exactly that text — the point where probabilistic contributions become a fixed document, so the
  Editor model test (5d) re-runs the same bytes offline. One JSON document after a stable prompt;
  figures in cast order (a fixed order, a possible bias, recorded). *Output:* `audit` before
  `synthesis`, reason before verdict within each judgement; a sixth audit class, `not_contributed`,
  so a failed figure still gets its one entry; code checks the structured lists (cast, cited
  passages, received bridges, `would_reject`, degraded state), never the prose. *Prompt:*
  `prompts/editor_hub.md` (`7713a4be…`), hub-and-spoke only — token-ring gets its own in Phase 6,
  sharing the schema core; each disposition defined, the synthesis told to weigh contributions by
  the audit; no examples (J9); effort `high`. *Failure:* a transient error after its retry, an
  unparseable output, or any failed check is an Editor failure and fails the run (§14), with every
  check reported and the baseline, the input and the raw output kept. *Testing:* offline in full;
  then two live calls on a synthetic deliberation as a mechanics check only — schema acceptance,
  output length, cost, reasoning tokens — with quality judged on the first real four-figure runs.
  *Rejected:* building the input inside the call (5d would rebuild it from the trace); prose
  input (paraphrased ids); one prompt for both topologies, or a templated one (J9); delivering a
  synthesis that failed a check, with flags (a fabricated attribution presented as the answer);
  repairing or re-calling (H4, §14); a staged "real" deliberation from one corpus under four names.
  *Landed in 5c (`947c286`):* offline 37/37 on two machines, every check and the
  send-the-written-bytes rule each shown able to fail. *Mechanics check* (2 live Editor calls on a
  synthetic deliberation, $0.0033): the strict schema was accepted; both outputs parsed and passed
  all ten checks; reasoning tokens (1,271 and 1,530) are priced inside output tokens, confirmed by
  hand — the Phase 1 open item, closed. On filler content the Editor marked every citation
  unsupported, flagged counterfeit consensus and returned `insufficient_basis`; synthetic, so
  observed behaviour, not quality evidence. Identical passages were judged `does_not_support` in
  one run and `partly` in the other: the middle of the verdict scale is soft (recorded). Two fields
  were used outside their meaning — `unresolved` listed all four figures where none disagreed, and
  `historical_citations` listed passages just judged not to support anything — both gaps in the
  prompt's wording against System §5. *Revised before any real run:* `editor_hub.md` v2
  (`e75fdf7d…`, was `7713a4be…`) defines `unresolved` as a disagreement between figures that the
  deliberation leaves open, at least two figures, and `historical_citations` as passages relied on
  as support, with an unsupporting passage left to the audit. *Rejected:* waiting for real runs
  (the gap is known; the first expensive runs would only rediscover it); a code check on what the
  fields mean (a form check is what was just met without its substance).
- **K11 — The toolkit slice (T1–T3).** **RESOLVED 2026-11-28.** Three tools for building a figure,
  committed in `30e009c`, `3a17071` and `193b894`; the procedure they serve is New Figure. *The
  survey reports and never decides:* `scripts/corpus_survey.py` lists candidates per section and
  writes no recipe configuration. *Rejected:* letting it write recipe configuration. *Answer keys
  are region-scoped on the key side; the survey stays region-free:* the selftest windows Marcus's
  key to his books (lines 2129–7178) and reads run 8 as 1–80 through Huxley's note, while the
  survey scans each whole text. *Rejected:* teaching the survey regions or authorship. *Descent's
  table 2 is recorded as a known miss:* the table rule misses rows that wrap onto unspaced text
  lines, and the selftest reports it without failing. *Rejected:* a fitted rule change. *The gate
  is a separate script from compile:* `scripts/horizon_gate.py` reads a figure's chunks.
  *Rejected:* folding it into compile, which would make compile depend on gitignored local data.
  *The window reads the sources and shares the compiler's availability logic*
  (`horizon.availability`). *Rejected:* a view of the compiled file, which holds no dates. *The
  kit moves code; it does not redesign it:* each kit function behaves as the recipe code it
  replaced, and all nine outputs stayed byte-identical; Darwin's note walker stays in his recipe.
  *Rejected:* extracting a walker with one user. *Marcus is not retrofitted to the ledger:* he
  uses the kit for source and chunker only. *Rejected:* retrofitting, which would be a corpus
  change. *Recipes import the kit through one `sys.path` line,* so the documented commands
  (`python corpora/<figure_id>/acquire.py`) are unchanged. *Rejected:* `python -m`.
- **K12 — The Horizon pre-flight guard.** **RESOLVED 2026-11-28.** `horizon_preflight()` in
  `choir/deliberation.py` runs first in `deliberation_run`, before `host_decide` and before any
  model call: for every figure the roster marks `built`, `horizon.check` must find a current
  compiled Horizon; otherwise it raises `RuntimeError` naming each failing figure and the problem.
  It makes no model call and writes nothing. Host-only runs (`host_run`, `POST /run/host`) make no
  figure turns and are not guarded. Without it a missing Horizon surfaces as a lane failure after
  the Host's paid calls, and the run is recorded as degraded (K9), so a configuration error looks
  like a figure failure. Offline, `choir_probe` binds the guard to a no-op for its existing cases;
  its case 18 runs the real guard against the real roster and horizons, raises naming Plato, and
  records zero model calls, and a guard that returns without checking fails it. Closes the parked
  item "refuse to cast a built figure with no compiled Horizon". Plato's Horizon is not built yet,
  so every deliberation run is refused until it is; that is intended. *Rejected:* a corpus/Horizon
  split in the roster's `built` status; guarding at cast time (after the Host's calls).

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
