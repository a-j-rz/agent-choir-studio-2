# Agent Choir Studio V2

A local, disposable learning instrument for **multi-agent orchestration, evidence-bounded
historical agents, topology effects and epistemic leakage.**

Ask it almost anything. A Host decides whether the question deserves deliberation at all, picks
four historical figures from a roster of twenty-four, and routes them through one of two
coordination topologies. Each figure may reason only from its own primary sources. An Editor
synthesises the result, and a Detective then audits the whole run for knowledge that leaked in
from where it shouldn't have.

**Not a product.** The trace is the point; the final answer is a by-product.

> **Status:** Phase 4 complete — the Host. It triages each question, scores it on five dimensions
> and picks the cast, writing down why at every step; code, not the model, applies the threshold.
> **Next: Phase 5, hub-and-spoke and the Editor.** See [Build status](#build-status).

---

## The one idea

> **What makes LLMs powerful reasoning tools is that they know everything.
> What makes them flawed components of a system attempting near-deterministic outcomes
> is that they know everything.**

Every figure here is told: *reason only from your own retrieved primary sources, not from what
you already know about this person.* But the model underneath structurally **cannot un-know**
Marcus Aurelius or Darwin. The boundary is enforced by instruction and audit, never by
construction, so it leaks.

V2 exists to make that leak **observable**, because it is the exact constraint any real
bounded-reasoning or context-aggregation system inherits the moment it is built on a general
model. You can't prevent it. You can only decide how much to spend narrowing it, and measure
where it breaks.

> **V1 measured the deliberation. V2 measures the harness around the deliberation.**

[V1](docs/AGENT_CHOIR_LINEAGE_V1.md) held one question fixed and varied the topology. V2 lets the
question be anything, and makes the *envelope* observable: whether to deliberate, how, with whom,
and how well the reasoning stayed bounded while it did.

---

## How a run works

The visible narrative is four beats: **Host → Choir → Editor → Detective.** Two utilities sit
behind it, and the user never sees them as voices.

```mermaid
flowchart LR
    Q(["Question"]) --> H["Host<br/>frames · triages · scores<br/>picks cast + topology"]
    H -->|"not worth deliberating"| D(["Direct answer<br/>(cheapest outcome)"])
    H --> C["Choir<br/>exactly 4 historical figures"]
    C --> E["Editor<br/>audit + synthesis"]
    E --> A(["Answer"])
    E --> DT["Detective<br/>leakage audit<br/>read-only, runs last"]
    DT --> L[("detective.json")]

    R["Researcher<br/>current facts"] -.->|"frozen fact pack"| C
    H -.->|"invokes if facts missing"| R
    O["Oracle<br/>modern-concept bridge"] -.->|"on a figure's request"| C
```

| Role | Does | Never does |
|---|---|---|
| **Host** | Frames the question, decides whether to deliberate, scores complexity, picks four figures and a topology | Answers the substantive question; tells the Choir why they were picked |
| **Choir** | Four figures reasoning from their own corpora, dossiers and epistemic horizons | Uses knowledge no sanctioned channel supplied |
| **Editor** | Audits the deliberation, then synthesises, attributing reasoning to figures | Becomes a fifth worldview; searches corpora; infers a figure changed its mind |
| **Detective** | Hunts for knowledge a figure used that no logged channel accounts for | Touches the answer, or anything else in the run |
| *Researcher* | Supplies current, decision-relevant facts, claim by claim | Writes essays; fabricates a missing number |
| *Oracle* | Explains a post-lifetime concept neutrally to a figure that asks | Tells the figure what to think about it |

Every run is a **closed, stateless island**. Nothing from one run enters the next.

---

## The Host: deciding how much machine a question deserves

The Host is, in effect, a **per-question resource allocator**. Its cheapest and most valuable act
is deciding *not* to run: `4 × 9` gets an answer, not a four-figure deliberation.

```mermaid
flowchart TD
    Q(["Original question<br/>kept verbatim"]) --> T{"Triage"}
    T -->|"answer_directly"| X(["Answer and stop"])
    T -->|"reframe_or_reject"| Y(["Explain and stop"])
    T -->|"clarify"| CL["One targeted follow-up"] --> T
    T -->|"proceed"| F{"Facts missing?"}
    F -->|"yes"| R["Researcher<br/>≤ 3 gap-tied queries"] --> CQ
    F -->|"no"| CQ["Canonical question"]
    CQ --> AR["Archetypes<br/>1 primary + ≤ 2 secondary"]
    AR --> S["Complexity score<br/>5 dimensions × 0–2"]
    S --> TP{"Score"}
    TP -->|"0–4"| HS["Hub-and-spoke"]
    TP -->|"5–10"| TR["Token-ring"]
    HS --> CAST["Cast: exactly 4 figures<br/>+ near-miss rationale"]
    TR --> CAST
```

The five scored dimensions are value conflict, interpretive ambiguity, cross-domain interaction,
challenge value and consequence. The threshold is **locked**: no runtime override. If the rubric
routes badly, that's evidence for a future governed change, not a licence to improvise.

The Choir receives **only** the canonical question and the frozen fact pack — never the user's
wording, their own view, or the Host's reasoning about the cast.

*As built:* three model calls, each seeing only what it needs. The model judges (outcomes,
restatements, scores with reasons, assessments of each figure); code enforces (totals, the
threshold, the topology, every validity check). The scoring call never learns that its scores are
added up, or what they decide.

---

## Two topologies

### Hub-and-spoke — independent, once each

```mermaid
flowchart LR
    CQ["Canonical question<br/>+ fact pack"] --> F1["Figure A"]
    CQ --> F2["Figure B"]
    CQ --> F3["Figure C"]
    CQ --> F4["Figure D"]
    F1 --> E["Editor"]
    F2 --> E
    F3 --> E
    F4 --> E
```

No figure knows who else was selected or sees any other output. Fast, but every contradiction
between figures surfaces only when the Editor meets it alone.

### Token-ring — deliberation around a shared transcript

```mermaid
flowchart LR
    R1["Round 1<br/>blind baseline<br/>no one sees anyone"] --> R2["Round 2<br/>full transcript visible"]
    R2 --> R3["Round 3"]
    R3 --> R4["Round 4<br/>(a cap, not a target)"]
    R2 -.->|"reasoned early stop"| ST(["Stop + explicit reason"])
    R3 -.-> ST
    R4 --> ST
```

Seats rotate each round so no figure always speaks first or last:

| Round | Seat 1 | Seat 2 | Seat 3 | Seat 4 |
|---|---|---|---|---|
| R1 | A | B | C | D |
| R2 | B | C | D | A |
| R3 | C | D | A | B |
| R4 | D | A | B | C |

From Round 2, every turn must declare its movement — `changed_position`, `refined_position`,
`new_argument`, `new_evidence`, `direct_challenge_remains`, `no_material_change` or
`insufficient_corpus_basis` — and only a figure may declare its *own* change of mind.

> **The V1 trap, guarded.** In V1, a failed agent counted as "nothing more to add", so a
> three-way agreement plus one silenced dropout looked identical to consensus. Here, a failed
> figure is never a `no_material_change` vote. **Consensus is not truth**, and silence is not
> consensus.

---

## Inside one figure's turn

This is the keystone of the build: a cloud model that can only *ask*, and local code that
decides what it gets.

```mermaid
sequenceDiagram
    autonumber
    participant M as Model (the figure)
    participant P as Local Python
    participant I as This figure's index
    participant O as Oracle

    P->>M: canonical question + fact pack + dossier + horizon + tools
    M->>P: call search_my_corpus("justice")
    P->>I: lexical + semantic search, merged
    I-->>P: ranked passages with ids
    P-->>M: tool output (same call_id)
    M->>P: call oracle("parliamentary democracy")
    P->>O: concept + this figure's epoch (not identity)
    O-->>P: neutral explanation
    P-->>M: tool output
    M-->>P: contribution, citing passage ids
```

Per turn: up to **4** corpus searches, **8** candidates each, and **3** Oracle calls. Each figure
has its **own physically separate index**, so cross-figure retrieval is impossible by
construction, not by query hygiene.

Retrieval is **hybrid and visible**, because a figure reasoning beautifully over the wrong
passages is a failure worth seeing:

```mermaid
flowchart LR
    Q["Figure's query"] --> BM["Lexical (BM25)<br/>matches the words"]
    Q --> SEM["Semantic (local embeddings)<br/>matches the meaning"]
    BM --> RRF{"Reciprocal Rank Fusion"}
    SEM --> RRF
    RRF --> OUT["One ranked list<br/>both inputs kept in the trace"]
```

---

## Leakage and the Detective

The boundary isn't "no outside knowledge" — a figure needs general language just to read its
own corpus. It is **no *illegitimate* knowledge**: modern facts nobody supplied, the figure's
own later biography, post-lifetime concepts the Oracle never bridged, or knowledge of who else
is on the panel.

Every sanctioned channel is logged, so the Detective can ask a question the trace can actually
answer:

```mermaid
flowchart LR
    subgraph Sanctioned["Sanctioned channels — all logged"]
        CP["Corpus passages cited"]
        FP["Supplied facts"]
        OB["Oracle bridges"]
        TX["Transcript lines"]
    end
    U["Something a figure used"] --> CHK{"Does any logged<br/>channel account for it?"}
    Sanctioned --> CHK
    CHK -->|"yes"| OK(["Legitimate"])
    CHK -->|"no, and provably so"| HB(["Hard breach"])
    CHK -->|"smells post-epoch,<br/>can't be pinned"| SB(["Soft breach — low confidence"])
```

The cleanest signal is deterministic: **an out-of-horizon concept with no matching Oracle call**
is a near-certain hard breach, found by reconciling two logged lists rather than by judgement.

Every report carries a mandatory clause, because the Detective is the same kind of model as
the figures it audits:

> *Soft-breach detection is performed by a model carrying the same contamination it hunts.
> Absence of flagged soft breaches is **not** evidence of clean reasoning.*

---

## What gets measured

Seven observables per run. Two the trace reads cleanly; five need judgement, which is where the
skill lives.

| | Observable | Question it answers |
|---|---|---|
| Quantitative | **Cost** | Tokens per call, round and run |
| | **Speed** | Latency per call, round and run |
| Qualitative | **Quality** | Is the synthesis actually good? |
| | **Steering** | Were the topology and cast apt? |
| | **Question refinement** | Should we have deliberated at all, and was it framed well? |
| | **Leakage** | How bounded did figures stay, and how did the bound break? |
| | **Retrieval quality** | Did figures find and cite the *right* passages? |

Deliberately **not** scored: topology value. It's read from deltas against the Round 1 baseline.
A single "value" number would be counterfeit certainty one level up.

---

## The roster

Twenty-four figures, locked. The build is proving the machine on **four** of them, chosen for
how differently their texts are shaped, not for fame.

| Figure | Handle | | Figure | Handle |
|---|---|---|---|---|
| **Plato** ★ | Ideals | | Mary Wollstonecraft | Inclusion |
| Aristotle | Judgement | | John Stuart Mill | Liberty |
| Confucius | Harmony | | Karl Marx | Structure |
| **Marcus Aurelius** ★ | Agency | | **Charles Darwin** ★ | Adaptation |
| Sun Tzu | Position | | **Frederick Douglass** ★ | Consequences |
| Niccolò Machiavelli | Power | | William James | Mind |
| René Descartes | Doubt | | Benjamin Franklin | Experiment |
| Thomas Hobbes | Order | | Saint Paul | Transformation |
| John Locke | Rights | | Jane Austen | Character |
| David Hume | Evidence | | Friedrich Nietzsche | Genealogy |
| Adam Smith | Incentives | | Carl Jung | Depth |
| Immanuel Kant | Duty | | William Shakespeare | Human Nature |

★ **Machine-proving four:** aphorism (Marcus), dialogue (Plato), oration and testimony
(Douglass), scientific prose (Darwin) — four genuinely different chunking problems. If the
pipeline handles these, it handles most of the rest.

Each figure carries three frozen, human-reviewed artefacts: a **Corpus Manifest** (what evidence
exists), a **Persona Dossier** (how it reasons — logos, ethos, pathos) and an **Epistemic
Horizon** (what it could know without a bridge).

---

## Build status

Built in thin vertical slices. "Done" means the trace shows it, not that the code runs.

| Phase | Slice | Status |
|---|---|---|
| 0 | Bootstrap + live API spike | ✅ Done |
| 1 | Substrate: event model, trace directory, per-role config, model-call wrapper, live relay | ✅ Done |
| 2 | **Keystone:** one figure, one real corpus, hybrid index, grounded turn | ✅ Done |
| 3 | Oracle loop, on a shared tree of concept lineages | ✅ Done |
| 4 | Host flow: triage, scoring, topology, cast | ✅ Done |
| 5 | Hub-and-spoke + Editor | ⏭ Next |
| 6 | Token-ring | |
| 7 | Researcher + frozen fact pack | |
| 8 | Failure and degraded-run hardening | |
| 9 | Scale toward 24 (cast steering finally gets real choices) | |
| 10 | Regression set + external trace comparison | |

### What Phase 0 already showed

The spike ([`spikes/tool_loop.py`](spikes/tool_loop.py), log in
[`spikes/spike_log.txt`](spikes/spike_log.txt)) ran one figure-shaped tool loop against a
three-passage fake corpus. Small run, real lessons:

- **The model writes its own queries** — and better ones than we would. The figure chooses what
  to search; local code only executes. *Librarian, not editor.*
- **Lexical-only retrieval failed quietly on run one.** A relevant passage shared no words with
  the query, so it never surfaced — and the answer looked complete anyway. The case for hybrid
  retrieval, in miniature.
- **Consistency ≠ correctness.** Two runs wrote different queries, retrieved the same passage,
  and gave identical answers — both missing the same evidence. Stable retrieval, not good
  retrieval.
- **Context grows inside a single turn**, and each round trip costs roughly 3–5 seconds even at
  low effort. Four searches per figure, four figures, four rounds: that number compounds.

### What Phase 1 showed

- **Effort is a ceiling, not a floor.** The Editor ran at `high` on an easy task and reasoned for
  zero tokens. Effort *permits* deliberation; it doesn't buy it.
- **The blocking trap appears in miniature.** Creating the API client did ~270 ms of synchronous
  setup *inside* the first run, stalling everything behind it. Moved to server start; the first
  event's lag fell from 381 ms to 10 ms.
- **Closing the tab must stop the spending.** A cancelled stream doesn't cancel the work behind
  it, which would keep making paid calls for a reader who'd gone. The relay now cancels the work
  explicitly — and a cancelled call may still be billed, so an aborted run's recorded cost is a
  lower bound.
- **Cooperative concurrency is a guarantee, not a style.** Code between two `await`s can't be
  interrupted, which is what keeps every raw file and the event that names it on the same
  sequence number when four figures write at once.

### What Phase 2 showed

Marcus Aurelius, in George Long's English translation: 504 chunks, keyword and meaning search
merged, three live turns for about $0.0015 in all.

- **Each search method catches what the other misses — in both directions.** Meaning search
  found IX.15 for "governing one's own mind" with no shared words. Keyword search found I.1
  ("the government of my temper"), which meaning search ranked 319th, possibly because a
  14-word passage makes a weak point in meaning-space (one data point so far).
- **A catch can be lost at every stage.** Retrieved, then merged, then shown as a preview, then
  opened, then cited. IX.15 was surfaced twice and never opened. At 186 characters its preview
  was the whole passage, and the figure recorded no reasoning, so the trace shows *where* it
  dropped out, not *why*.
- **The merge favours agreement.** With 8 slots and little overlap, each method gets about 4.
  Looking deeper into each list before merging made things worse: catches found by only one
  method fell from 2 to 0. So each list contributes its own top 8.
- **The figure searches with knowledge it shouldn't use.** Marcus's queries were full of Stoic
  vocabulary and even book numbers: memory steering retrieval before any claim is made.
- **Rarity weighting only suppresses junk that is common.** The `s` left over from "one's"
  appeared in 61 passages, rare enough to carry real weight. Found by the trace; fixed.
- **Stable is not correct, again.** Two runs of the same question shared 7 of 8 results and
  3 of 4 citations.

### What Phase 3 showed

Marcus's Epistemic Horizon is compiled from a shared tree of concept lineages, each concept's
meaning tracked through the eras: 15 lineages, 58 senses. The Oracle explains modern things from
what his world already had. 65 live calls in all, about $0.018.

- **The hard leaks are old words in new senses.** "Anxiety" (Cicero's *anxietas*), "therapy",
  "energy" (Aristotle's *energeia*), "dependence": in the breach terms, the coverage probe and the
  Oracle lookup, the difficult cases were ancient words carrying modern meanings.
- **A seed written from imagination missed most of what real answers use.** Grounding it in a
  cheap probe of real answers took the unmapped share of fresh answers from about 70% to 25%.
- **The Oracle builds from his world.** A smartphone, from couriers and fire signals; inflation,
  from debased coinage; a blockchain, from account books and seals. It never refused: its
  honesty lives in what it says it left out.
- **The instruments leak too.** The Horizon's own description would have put "investors" into
  Marcus's prompt; a guard, specified before the first run, caught it.
- **A clean result is only as good as what the check can see.** Asked about anxiety as a medical
  illness, the lookup took "anxiety" for Marcus's own word, and his answer scored zero unbridged
  terms. Whether it carried modern ideas in plain words, term matching cannot tell.

### What Phase 4 showed

The Host is three calls with code between them: triage, scoring, cast. 53 live calls in all, about
$0.024.

- **Stable is not correct, a third time.** The first scoring prompt gave identical scores run after
  run, and consistently higher ones than the owner's blind scores. One question the owner sent to
  hub-and-spoke scored 7 out of 10, every time.
- **Calibration needs independent readers.** The owner and Claude scored blind, Claude's scores
  sealed first. Their first disagreements were about meaning, not numbers ("domain" as topic or as
  field). The fixes went into the wording; the target is convergence, not one reader's numbers.
- **Authors can't see their own ambiguity.** "Natural law" meant physics to the person who wrote it;
  the Host asked whether it meant moral law.
- **A model can satisfy a naming rule without meeting it.** Asked to name the interaction that would
  reverse an answer, it sometimes named a hypothetical.
- **The cast gate became a prediction.** With four figures and four seats, the gate can't reject,
  so it records whom it would have rejected: Marcus, on a question about aesthetic form. Phase 5
  checks that against what his corpus actually yields.

---

## Models

Model choice is configuration, never architecture.

- **Every role runs on `gpt-6-luna`** for now, with `reasoning.effort` set per role as the dial.
  A seat is promoted to a stronger model only when its trace shows it struggling — the Editor is
  the likeliest first candidate, to be tested by re-running a frozen deliberation through both.
- **Responses API only.** It's the one shape that supports tool calling across the current
  generation.
- Project-scoped key with a hard spend cap; requests fail rather than overspend.

---

## Stack

```text
Language:     Python 3.12
Backend:      FastAPI
Live updates: Server-Sent Events, read with fetch() — which never auto-reconnects, so a dropped
              stream can't silently start a second billed run
Frontend:     Vanilla HTML + JS, no framework, no build step
Model API:    OpenAI Responses API, direct
Concurrency:  asyncio
Schemas:      Pydantic
Retrieval:    hand-written BM25 (Snowball stemming) + local embeddings (bge-small-en-v1.5
              via sentence-transformers, on CPU, cached) + RRF; one index per figure
Trace:        one directory per run: events, raw payloads, summary, leakage report
```

**Deliberately absent:** agent frameworks, MCP for corpus retrieval, hosted vector stores,
black-box RAG. The orchestration and retrieval loops *are* the lesson; a framework would hide
exactly the part being learned.

---

## Running it

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then add your own API key
uvicorn app:app --reload      # http://127.0.0.1:8000
```

The page has two buttons: a **free test run** (no model calls) and a **live run** — one real
traced model call as the Editor, costing around $0.0001. Every run writes its trace to
`traces/<run_id>/`. The same live run from the command line, printing events as they happen:

```bash
python -m scripts.llm_smoke
```

**Marcus's corpus** is rebuilt locally from its recipe, then his first turn can run:

```bash
python corpora/marcus_aurelius/acquire.py      # download the pinned text, strip Long's apparatus
python corpora/marcus_aurelius/chunk.py        # one chunk per section → data/chunks.jsonl
python -m scripts.vector_probe --download --lengths   # first time only: fetch the embedding model
python -m scripts.figure_turn "How should a person govern their own mind?" --condition A   # live, ~$0.001
```

**The Host** runs from the page (type a question, one button, three live calls) or the command line:

```bash
python -m scripts.host_probe "Is beauty subjective or objective?"   # live, ~$0.0015
python -m scripts.host_probe --offline                                # 43 canned cases, no calls
```

The probes run offline and cost nothing: `bm25_probe`, `vector_probe` and `retrieval_probe`
show each retrieval stage on its own. `bm25_probe` and `retrieval_probe` each have a `--selftest`
with hand-computed answers; `vector_probe --selfcheck` checks that every chunk retrieves itself.
`compile_horizon --selftest` proves the Epistemic Horizon compiler.

Corpus texts, built indexes, run traces and `.env` are gitignored by design. The repo carries
the *recipe* for a corpus, never the texts.

---

## Repo map

```text
agent-choir-studio-2/
  README.md
  AGENT_CHOIR_V2_GLOSSARY_NON_TECHNICAL.md   # the plumbing, in plain words, with pictures
  CLAUDE.md              # standing rules for Claude Code
  app.py                 # FastAPI: /, /health, /stream (free test run), /stream/live, POST /run/host
  core/
    events.py            # the Event: trace record and SSE message in one object
    trace.py             # RunTrace: traces/<run_id>/, write-first, live queue, summary
    config.py            # the one place for each role's model, effort and prices
    llm.py               # call_model(): async, traced tool-call loop on the Responses API
    runner.py            # run lifecycle as a task; relay to browser or terminal
  retrieval/
    bm25.py              # keyword search, every score broken down by term
    vectors.py           # local embeddings: pinned model, length gate, cache, search
    hybrid.py            # load one figure's index; RRF merge of the two lists
    tools.py             # a figure's corpus tools, bound per turn, budgets enforced in code
  choir/
    contribution.py      # the structured, cited answer a figure returns
    figure_turn.py       # one figure turn: corpus tools + Oracle, citation checks, reconciliation
    oracle.py            # the Oracle: Horizon lookup, composed input, redaction, budget
    reconcile.py         # deterministic leakage reconciliation after every turn
  host/
    records.py           # the Host's typed outputs; ChoirInput, the only thing a figure receives
    triage.py            # call 1: triage and framing; the canonical-question tripwire
    score.py             # call 2: decomposition, archetypes, scores; threshold applied in code
    cast.py              # call 3: assess every figure, then select; the gate as a prediction
    run.py               # the Host run: call 1, then calls 2 and 3 on proceed
    roster.json          # the machine-proving four
  prompts/
    figure_standin.md    # stand-in figure prompt, until Persona Dossiers exist
    oracle.md            # the Oracle's instructions
    host_triage.md       # the Host's three prompts, frozen and hashed
    host_score.md
    host_cast.md
  corpora/
    marcus_aurelius/     # the recipe only: acquire, chunk, Manifest, chunking config
  epistemic/horizon.py   # Epistemic Horizon: lineages + profile → compiled Horizon
  horizons/              # shared concept lineages, figure profiles, compiled Horizons
  demo/live_demo.py      # labelled fake corpus for the live demo run
  scripts/               # llm_smoke, figure_turn, retrieval probes, compile_horizon,
                         # horizon_coverage_probe, oracle_probe, host_probe, score_stability
  frontend/index.html    # vanilla page: renders any event type, live
  spikes/                # Phase 0 evidence, frozen
    tool_loop.py         # Phase 0 spike: model → tool → model round trip
    spike_log.txt        # its captured output
  docs/                  # the design pack: intent, reasoning, decisions
  requirements.txt
  .env.example
```

## Where to read next

| If you want… | Read |
|---|---|
| The map and reading order | [`INDEX`](docs/AGENT_CHOIR_V2_INDEX.md) |
| *Why* this exists | [`EXPERIMENTAL_FRAME`](docs/AGENT_CHOIR_V2_EXPERIMENTAL_FRAME.md) |
| The roles and their contracts | [`SYSTEM`](docs/AGENT_CHOIR_V2_SYSTEM.md) |
| The figures, corpora and retrieval | [`CHOIR_AND_CORPUS`](docs/AGENT_CHOIR_V2_CHOIR_AND_CORPUS.md) |
| Routing and the topologies | [`TOPOLOGY_AND_STEERING`](docs/AGENT_CHOIR_V2_TOPOLOGY_AND_STEERING.md) |
| The interesting idea | [`LEAKAGE_AND_DETECTIVE`](docs/AGENT_CHOIR_V2_LEAKAGE_AND_DETECTIVE.md) |
| What's settled and what isn't | [`DECISIONS`](docs/AGENT_CHOIR_V2_DECISIONS.md) |
| The plan and what's out of scope | [`BUILD_PLAN`](docs/AGENT_CHOIR_V2_BUILD_PLAN.md) |
| What every run records | [`TRACE_AND_INSTRUMENTATION`](docs/AGENT_CHOIR_V2_TRACE_AND_INSTRUMENTATION.md) |
| The plumbing, in plain words | [`GLOSSARY_NON_TECHNICAL`](AGENT_CHOIR_V2_GLOSSARY_NON_TECHNICAL.md) |

> The code is disposable. The judgement is the asset.
