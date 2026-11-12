# Agent Choir Studio V2 — Trace & Instrumentation

*The trace is the product. This document specifies what every run captures, how it is stored,
where each of the seven observables physically lives, and how the live UI separates the causal
chain from the noisy diagnostics. If the code and this document ever disagree once the build
exists, the code wins for behaviour — but this is the intent the trace must serve.*

---

## 1. The principle

For most multi-agent systems the trace is a footnote to the answer. Here it is inverted: **the
trace is the measurement instrument, and the answer is almost a by-product.** Do not hide the ugly
bits — failures, retries, thin retrievals, leakage flags are the curriculum, not blemishes to
smooth over. Everything that follows serves one goal: a completed run should be fully legible,
cold, from its trace alone.

---

## 2. Raw and normalized, always both

Every run persists **both**:

1. **raw model outputs exactly as returned** — the unedited responses and tool payloads;
2. **normalized application objects** — the structured, schema-versioned objects the app reasons
   over.

Every normalized object carries a **`schema_version`.** Raw exists so nothing is lost to
normalization; normalized exists so runs are comparable. The pair is non-negotiable — a
normalized-only trace hides where the model actually said something the app tidied away.

---

## 3. Storage shape — one directory per run

```text
traces/<run_id>/
  events.jsonl     # the live causal event stream, one JSON object per event, append-only
  raw/             # raw model + tool payloads (prompts, responses, tool I/O)
  summary.json     # the normalized run summary (schema_version stamped)
  detective.json   # the standalone leakage verdict (see Leakage & Detective)
```

A per-run **directory**, not V1's single flat `runs.jsonl`, because a V2 run contains far more
sub-events — every corpus search with its candidate lists, every passage open, every Oracle call,
every round and seat rotation. A flat file would drown; the directory keeps raw payloads
separable and lets the leakage report be read and compared in isolation. `detective.json` is a
separate file (not a block in `summary.json`) so a future cross-run utility can diff leakage
reports alone. Adopt SQLite only if cross-run querying later becomes genuinely useful — not
pre-emptively.

`traces/` is gitignored.

---

## 4. The event model

One shared event schema across everything, so the live stream and the trace are the same
substance. Each event minimally carries an event type, the role/actor, a payload (the full
structured output on "spoke"/"produced" events — this doubles as the trace record, not just a UI
string), a round number where relevant, and a timestamp. The frontend animates strictly off
**real** events as they arrive — never simulated timing — and closes its SSE connection explicitly
on completion so a browser auto-reconnect can never silently re-trigger a billed run (a concrete
V1 lesson).

Events should cover at least: run lifecycle; Host interpretation / clarification / triage /
score / cast / topology; Researcher intervention and fact pack; each figure's turn start and
contribution; corpus search and retrieval activity; Oracle requests; round transitions and seat
rotation; direct question/challenge state changes; stop decision; Editor audit and synthesis;
Detective verdict; errors and retries.

---

## 5. Where the seven observables physically live

Each observable must be readable off the trace — this table is the contract between the
measurement frame and the instrumentation.

| Observable | Kind | Where it lives in the trace |
|---|---|---|
| **Cost** | quantitative | token usage → estimated cost, per call / per round / per run, in `summary.json`; raw usage in `raw/`. |
| **Speed** | quantitative | latency per call / per turn / per round / total, in `summary.json`. |
| **Quality of outcome** | qualitative | the Editor synthesis + audit; read by human. Topology-value *deltas* (not a score) derived from the Round-1 baseline. |
| **Steering** | qualitative | Host archetypes, per-dimension complexity score + rationale, chosen topology, cast rationale + near-misses. Topology steering readable from run one; **cast steering only meaningful once the roster forces a choice** (Phase 9 checkpoint). |
| **Question refinement** | qualitative | original / clarified / canonical question kept separate; triage outcome; research-need decision; provisional-vs-final score with reason for change. |
| **Leakage** | qualitative | `detective.json` — hard/soft breaches, Oracle cross-check, self-limitation clause. Also streamed as a live event. |
| **Retrieval quality** | qualitative | per-turn search query, lexical candidates, semantic candidates, merged/ranked results, passages opened vs cited, whether fresh retrieval occurred. |

Topology value is present as **baseline deltas only** — material position changes after Round 1,
refinements, new arguments/evidence, interaction-triggered searches, direct-question/challenge
activity, unresolved disagreements, rounds completed, stop reason, context growth, latency/cost by
round — and is **never** collapsed into a scalar.

---

## 6. The live UI split — causal chain vs expandable diagnostics

The live UI shows the **main causal chain** without drowning the user:

- Host interpretation, triage and clarification;
- Researcher intervention and distilled fact pack;
- archetypes and complexity score;
- cast and rationale;
- selected topology;
- Choir turns as they happen;
- direct questions / challenges;
- Oracle and corpus activity at a useful summary level;
- round transitions and seat rotation;
- stop reason;
- Editor disposition and synthesis;
- Detective verdict.

**Noisy diagnostics are expandable, not front-and-centre:** raw prompts; raw tool payloads; full
retrieval candidate lists; token detail; retries; exact normalized JSON. The full Editor audit
lives in an expandable panel — the main user-facing answer stays clean. The Detective's leakage
report lives in the same instrumentation surface; the user gets the clean synthesis by default and
the contamination verdict one click away.

---

## 7. Minimum per-run capture

At minimum, a run captures:

- run ID; timestamp; schema versions; models per role;
- original / clarified / canonical question; initial user position if captured;
- decomposition; archetypes; provisional and final complexity scores + per-dimension rationale;
- cast + near-misses + cast rationale; selected topology + rationale;
- Researcher queries / results / distilled fact pack; any mid-run factual-substrate change;
- all Oracle requests and responses;
- all corpus search queries with lexical candidates, semantic candidates, merged/ranked
  retrievals; passages opened; passages cited; whether fresh retrieval occurred per turn;
- every historical turn's output and structured state; token-ring seat order per round; direct
  question/challenge state;
- termination reason;
- Editor audit; final synthesis;
- Detective leakage verdict (`detective.json`);
- latency per call/turn/round/total; token usage; estimated cost;
- errors and retries;
- raw prompts and raw model/tool payloads.

---

## 8. What "done" means for instrumentation

The instrument's trace is complete when a cold reader can, from `traces/<run_id>/` alone,
reconstruct: what was asked and how it was framed; whether it was even worth deliberating; who was
selected and why (and who wasn't); which topology and why; what each figure retrieved, cited, and
argued; how the deliberation moved (or didn't) past its Round 1 baseline; why it stopped; what the
Editor concluded and on what evidence; and where — and how confidently — knowledge leaked past the
epistemic bounds. If any of those cannot be read off the trace, the instrumentation is not done,
regardless of whether the code runs.
