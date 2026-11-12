# Agent Choir Studio V2 — Decisions

*The decision record. Every resolved implementation and hygiene choice as decision + rationale
+ rejected alternative, so a cold reader (or a helpful collaborator) does not relitigate a
settled call. The "deliberately not open" locks from the source design also live here. Genuine
open choices are marked as such.*

---

## How to read this

A decision recorded here is **settled.** Do not reopen it merely because a different choice is
defensible — the rationale and the rejected alternative are recorded precisely so the trade was
made once, deliberately. Items explicitly marked **OPEN** or **DEFERRED TO SETUP** are the only
live degrees of freedom.

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
- **B4 — Embeddings: one shared local model across all 24 indexes** (e.g. `bge-small-en` or
  `all-MiniLM-L6-v2` — confirm at build). CPU-friendly, reproducible, local. *Rejected:* OpenAI
  embeddings API (sends corpus to cloud, defeats "local and visible"); per-figure embedding
  tuning (locked out for V2). The exact model is **OPEN** within these criteria.
- **B5 — 24 physically separate indexes, not one index with metadata filters.** Corpus
  boundaries enforced by construction, not by query hygiene.

## C. Utilities & orchestration

- **C1 — Researcher on the Host tier (Terra class) with a search tool, configurable.**
  Source-quality judgement needs capability. *Rejected:* a cheap model (degrades the claim-by-claim
  source hierarchy). Native-vs-app-mediated search is **OPEN**, decided after reviewing current
  tooling.
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
  versioned repo artefacts** — never runtime-generated summaries. Generation prompt, provenance
  format, review checklist and regeneration policy are **OPEN** workflow details.
- **E2 — Corpus corpus texts and built indexes are gitignored; Manifests, chunking config and
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
commit author metadata. V2 must expose no corporate identity of any kind. These are resolved in
principle; the mechanics are **DEFERRED TO SETUP**.*

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
- **G6 — Repo is public only as a temporary verification window during build, then private.**
  Claude Code retains full access via the local clone throughout (public/private is irrelevant
  to it). This chat surface can fetch the repo only while public; once private, the standalone
  context pack is the sole re-grounding artefact — which is why the pack embeds all context and
  assumes no repo access.
- **G7 — The existing V1 repo's historical commits still contain the corporate address.**
  Leaving, history-rewriting, or deleting V1 is the owner's separate call and is **not** part of
  the V2 build; the G2 fix does not reach backwards into V1.

## H. Model identifiers

- **H1 — Verify current model names, pricing, API surface and tool/search support against
  official documentation at build time.** Names drift; the currently-intended dispositions
  (Host/Terra, figures & Oracle/Luna, Editor/Sol, Detective/Editor-class, Researcher/configurable)
  are configuration, not architecture, and live in one config location. **OPEN** until verified.

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
