# Brief: Phase 4c, Host cast selection

Read first: `docs/AGENT_CHOIR_V2_TOPOLOGY_AND_STEERING.md` §7, `docs/AGENT_CHOIR_V2_CHOIR_AND_CORPUS.md`
§1–2 and §5, then `host/run.py`, `host/score.py` and `host/records.py` (4a/4b). This slice follows their
patterns exactly.

## What this slice is

**Call 3 of the Host.** It runs only after call 2, so only on `proceed`. It sees exactly three things: the
canonical question, the archetypes from call 2 (primary and secondary), and the roster metadata. **It
does not see** the scores, the topology, the original wording or call 1's reasoning.

On the machine-proving four, selection is degenerate: it chooses four from four. So the call is built to
**assess each candidate before selecting**, so that the assessment still carries information when nobody
can be rejected.

Code records where the corpus-suitability gate *would* have rejected a figure, and that the gate could
not act because the roster is exhausted. Code also adds the near-miss note. The cast is always exactly
four (locked); a `would_reject` entry is a recorded prediction, tested against retrieval in Phase 5.

Out of scope: a larger roster (Phase 9); any "no viable panel" stop (parked for Phase 9); dossiers.

## Build

Show me each file's shape before writing it.

### 1. `host/roster.json`: the machine-proving four

One entry per figure, in this order: `marcus_aurelius`, `plato`, `frederick_douglass`, `charles_darwin`.
Fields: `figure_id`, `name`, `handle`, `primary_contribution`, all taken verbatim from Choir & Corpus §1's
table, and `corpus: "built" | "not_built"`. Only `marcus_aurelius` is `built` (the code checks that
`corpora/<id>/manifest.json` exists exactly for the built ones). No corpus text.

### 2. Roster input, built by code

For each figure: the roster fields, plus, **only where built**, a `manifest` block taken from its
manifest: `included_works`, `period`, `genre`, `audience_context`, and `translation_edition.translator`.
Where the corpus isn't built, `manifest` is `null`. Send the whole list as JSON in the second input item,
after the canonical question and archetypes in the first. Record the exact input in the trace.

### 3. `prompts/host_cast.md`: exactly the text at the end of this brief

Stable `instructions`. Assert at load that it contains none of: `topology`, `token-ring`,
`hub-and-spoke`, `threshold`, `score`, and the five dimension names (`value conflict`,
`interpretive ambiguity`, `cross-domain interaction`, `challenge value`, `consequence / stakes`). Use
`normalise()`, and fail loudly naming any hit.

### 4. `host/records.py`: types, record version bump

- `Rating = Literal["strong", "adequate", "weak"]`.
  `CorpusRating = Literal["strong", "adequate", "weak", "unassessable"]`.
- `Judged`: `reason: str`, then `rating: Rating`. `CorpusJudged`: `reason: str`, then
  `rating: CorpusRating`. The reason comes first in the class and the schema, as in 4b.
- `CandidateAssessment`: `figure_id`, `archetype_relevance: Judged`, `question_fit: Judged`,
  `corpus_suitability: CorpusJudged`.
- `NearMiss`: `figure_id`, `reason`.
- `CastOutput` (the model's output, in this field order): `candidate_assessments:
  list[CandidateAssessment]`, `selected: list[str]`, `panel_diversity: str`, `panel_redundancy: str`,
  `panel_tension: str`, `near_misses: list[NearMiss]`. Strict hand-written `CAST_TEXT_FORMAT`, with the
  same drift asserts as before.
- `CastRecord` (code): `output: CastOutput`, `would_reject: list[str]` (selected figures whose corpus
  suitability is `weak`), `gate_unassessable: list[str]` (selected figures rated `unassessable`),
  `gate_not_applied: str | None` (`"roster exhausted"` if either list is non-empty, else null),
  `near_miss_note: str | None` (`"roster of four; none to miss"` when the roster minus the cast is
  empty).
- `HostDecisionRecord` → `schema_version "3"`. Add `cast: CastRecord | None`, null unless scored.
  `prompt_sha256` gains `"cast"`.

### 5. `host/cast.py`: call 3

1. Load the prompt (with the load assert) and compute its SHA-256; load the roster; build the input.
2. `call_model(role="host", instructions=prompt, input_items=[...], tools=[], handlers={},
   text_format=CAST_TEXT_FORMAT, max_round_trips=1)`.
3. Parse with exactly-one-validates (H4).
4. **Consistency check** in code. Each rule broken, in words; on any violation emit `host_cast_invalid`,
   then raise:
   - every roster figure is assessed **exactly once**, and nothing else is assessed;
   - `corpus_suitability` is `unassessable` **if and only if** that figure's corpus is `not_built`;
   - `selected` is exactly 4 distinct roster ids;
   - every `near_misses` id is in the roster and not in `selected`; ids are distinct;
   - every reason and every panel field is non-empty.
5. Compute the `CastRecord` fields in code.
6. Events: `host_cast_bound` (prompt, SHA-256, and the exact roster input), the `round_trip`,
   `host_cast` (the validated output plus the consistency verdict and the `CastRecord`).

### 6. Run body

`host_run`: call 1, then call 2 and call 3 on `proceed`. Call 3 receives
`canonical_question`, `primary_archetype` and `secondary_archetypes`, and nothing else. The record
carries `cast`. `--triage-only` is unchanged. The `choir_input` event and its rule are unchanged: the
cast never enters `ChoirInput`.

### 7. UI

The record block gains a **Cast** section: one row per figure showing its three ratings with their
reasons; the selected four; the three panel fields; and, where present, `would_reject`,
`gate_unassessable`, `gate_not_applied` and `near_miss_note`. Use `textContent` only.

## Acceptance, stage 1: offline (no live calls)

1. Prompt-load assert: it passes on `host_cast.md`, and fails, naming the term, on a temp copy with
   `score` inserted.
2. All 28 earlier cases still pass. The canned `proceed` runs now also run a canned call 3.
3. New canned cases, each a traced run:
   - valid cast, with Marcus `adequate` and the other three `unassessable` → `complete`;
     `gate_unassessable` lists those three; `gate_not_applied: "roster exhausted"`;
     `near_miss_note` set.
   - valid cast with Marcus's corpus suitability `weak` → `would_reject: ["marcus_aurelius"]`.
   - each a `failed` run with `host_cast_invalid` naming the rule: a figure assessed twice; a figure
     missing; an unknown figure assessed; a not-built figure rated `strong`; a built figure rated
     `unassessable`; 3 selected; a duplicate in `selected`; an unknown id selected; a near-miss that is
     in the cast; an empty panel field; two valid items (H4).
   - `clarify` → neither call 2 nor call 3 is called.
   - the recorded call 3 input contains no score, no topology and no original wording: assert it by
     inspecting the request.
4. `git grep` for identifying strings. Never read `.env`.

**Stop.** Show me: the prompt and its SHA-256, the roster file, the offline table, and one full offline
`proceed` trace.

## Acceptance, stage 2: live (exactly 6 calls, only after I say go)

Two full `host_probe` runs (3 calls each) on the questions I give you then. No re-runs; report anything
unexpected. For each, report the full cast record, with every rating and reason, and the tokens and cost.

## Drift report

End with: what you did that wasn't in this brief; what in the brief you didn't do; then
`git status --short` and `git diff --stat`. Never commit.

---

## `prompts/host_cast.md`: exact text

```markdown
# Host: cast assessment and selection

You choose the panel of historical figures who will deliberate a question. You are given the
question, the archetypes it was classified under, and the roster: each figure's handle, primary
contribution and corpus status, with a summary of the corpus where one has been built. You do not
answer the question.

## 1. Assess every candidate, before choosing

For every figure on the roster, give a reason and then a rating on three criteria:

- `archetype_relevance`: how well the figure's characteristic concerns match the archetypes given.
- `question_fit`: how directly the figure's thought bears on this specific question, not on the
  topic in general.
- `corpus_suitability`: whether the figure's own writings, as summarised, are likely to contain
  material that bears on the question. Judge it only from the corpus summary supplied, never from
  what you know of the figure. Where no corpus has been built, rate it `unassessable`.

Ratings: `strong`, `adequate`, `weak`. Use `weak` wherever it is deserved. These assessments
matter even when the choice is easy.

## 2. Select exactly four

Corpus suitability is a gate: a figure with weak corpus fit should not be chosen because it would
make the debate interesting. Relevance outranks engineered disagreement: do not manufacture tension
at the cost of relevance. Two figures with overlapping concerns may both be chosen if their
reasoning rests on different foundations.

If the roster holds only four figures, all four are selected. Assess them honestly all the same.

## 3. Describe the panel you selected

- `panel_diversity`: how the four differ in their foundations and methods.
- `panel_redundancy`: where they overlap, and whether that overlap is useful.
- `panel_tension`: where they are likely to disagree productively. If the panel is largely aligned,
  say so and say whether that is acceptable for this question.

## 4. Near misses

Name one or two figures you did not select who came closest, each with the reason. If every figure
on the roster was selected, leave this empty.

## Every field is present

Write every field the format requires.
```
