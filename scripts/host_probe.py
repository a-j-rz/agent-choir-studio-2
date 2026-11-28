"""Run the Host: call 1 (triage), then calls 2 (scoring) and 3 (cast) on proceed. Or none, offline.

    python -m scripts.host_probe "<question>"                 # one live run (1 or 3 calls)
    python -m scripts.host_probe --triage-only "<question>"   # call 1 alone (1 call)
    python -m scripts.host_probe --offline                    # no live calls: prompt checks + canned runs

Offline: the prompt-load checks on all three prompts (and on temp copies with a forbidden term
inserted); then each canned case as its own traced run, with call_model patched separately in
host.triage, host.score and host.cast. Each patch records how often it was called and emits the
same round_trip event call_model would, with zero tokens and cost, marked offline_canned. Every
run that makes call 3 also has its recorded request inspected: exactly the question, archetypes
and roster, with no score, topology or original wording.
"""

import asyncio
from functools import partial
import json
from pathlib import Path
import sys
import tempfile

import host.cast as host_cast
import host.score as host_score
import host.triage as host_triage
from core.config import role_config
from core.events import Event
from core.llm import LLMResult
from core.runner import relay
from core.trace import TRACES_DIR
from host.records import DIMENSIONS
from host.triage import DIMENSIONS as DIMENSION_NAMES, normalise
from host.run import host_run, host_triage_only


def line(event: Event) -> str:
    p = event.payload
    if event.type == "round_trip":
        d = (f"{p['latency_s']}s · in {p['input_tokens']} / out {p['output_tokens']} "
             f"(reasoning {p['reasoning_tokens']}) · ${p['est_cost_usd']:.6f}"
             + (" · OFFLINE CANNED" if p.get("offline_canned") else ""))
    elif event.type in ("host_bound", "host_score_bound", "host_cast_bound"):
        d = f"{p['prompt_file']} sha256 {p['prompt_sha256'][:12]}… · {p['role_config']}"
    elif event.type == "host_scoring":
        d = f"totals {p['unit_totals']} · governing unit {p['governing_unit']} · {p['rule']} · {p['score_status']}"
    else:
        d = json.dumps(p, ensure_ascii=False)[:200]
    return f"#{event.seq:<3} {event.type:<22} {event.role:<7} {d}"


async def run_one(question: str, body=host_run, quiet=False) -> tuple[list[Event], str | None]:
    """One traced Host run. Returns its events and the error, if the run failed."""
    events, error = [], None
    note = "host run (4c)" if body is host_run else "host triage only (4c)"
    try:
        async for event in relay(partial(body, question=question), note, render=lambda e: e):
            if not quiet:
                print(line(event), flush=True)
            events.append(event)
    except Exception as exc:
        error = repr(exc)
    return events, error


# ---------------------------------------------------------------- offline: canned outputs

def canned(**fields) -> str:
    """One call-1 message item: every field present, unset ones null / []."""
    out = {"outcome": None, "reason": "canned for the offline probe", "direct_answer": None,
           "clarifying_question": None, "explanation": None, "suggested_question": None,
           "canonical_question": None, "answer_criterion": None, "factual_posture": None,
           "factual_gaps": []}
    out.update(fields)
    return json.dumps(out)


def unit(scores, text="canned unit", depends_on=None, empty_rationale=None) -> dict:
    """One scored unit; scores in DIMENSIONS order. empty_rationale names a dimension to blank."""
    return {"text": text, "depends_on": depends_on,
            **{d: {"rationale": "" if d == empty_rationale else f"canned rationale for {d}",
                   "score": s} for d, s in zip(DIMENSIONS, scores, strict=True)}}


def scored(decomposition, units, primary="Moral / Ethical", secondaries=()) -> str:
    """One call-2 message item."""
    return json.dumps({"decomposition": decomposition, "primary_archetype": primary,
                       "secondary_archetypes": list(secondaries), "units": units})


DEFAULT_SCORE = [scored("single", [unit([1, 0, 1, 0, 1])])]  # total 3 → hub_and_spoke

ROSTER_IDS = ["marcus_aurelius", "plato", "frederick_douglass", "charles_darwin"]
# J6: a roster-consistent rating is "adequate" where the corpus is built, "unassessable" where not.
ROSTER_CORPUS = {f.figure_id: f.corpus for f in host_cast.load_roster()}


def roster_rating(figure_id):
    return "adequate" if ROSTER_CORPUS.get(figure_id) == "built" else "unassessable"


def assess(figure_id, corpus="unassessable", relevance="adequate", fit="adequate", reason="canned reason"):
    return {"figure_id": figure_id,
            "archetype_relevance": {"reason": reason, "rating": relevance},
            "question_fit": {"reason": reason, "rating": fit},
            "corpus_suitability": {"reason": reason, "rating": corpus}}


def cast_out(assessments=None, selected=ROSTER_IDS, near_misses=(), tension="canned tension") -> str:
    """One call-3 message item. Default: every figure rated from the roster (J6)."""
    if assessments is None:
        assessments = [assess(f, corpus=roster_rating(f)) for f in ROSTER_IDS]
    return json.dumps({"candidate_assessments": assessments, "selected": list(selected),
                       "panel_diversity": "canned diversity", "panel_redundancy": "canned redundancy",
                       "panel_tension": tension, "near_misses": list(near_misses)})


DEFAULT_CAST = [cast_out()]
OTHERS = [assess(f, corpus=roster_rating(f)) for f in ROSTER_IDS[1:]]  # the other three, rated from the roster
MARCUS = assess("marcus_aurelius", corpus="adequate")


def fake_call_model(texts: list[str], calls: list):
    async def call_model(*, role, instructions, input_items, tools, handlers, trace,
                         max_round_trips=8, text_format=None):
        calls.append(text_format["name"])
        cfg = role_config(role)
        request = {"model": cfg.model, "instructions": instructions, "input": list(input_items),
                   "tools": tools, "reasoning": {"effort": cfg.reasoning_effort},
                   "text": {"format": text_format}}
        raw_file = trace.write_raw(f"{role}-rt1", {
            "request": request, "response": {"offline_canned": True, "message_texts": texts}})
        trace.emit("round_trip", role, {
            "trip": 1, "started_at": None, "latency_s": 0.0, "input_tokens": 0,
            "cached_input_tokens": 0, "cache_write_tokens": 0, "output_tokens": 0,
            "reasoning_tokens": 0, "tool_calls_requested": [], "est_cost_usd": 0.0,
            "raw_file": raw_file, "offline_canned": True})
        return LLMResult(text="".join(texts), stop_reason="answered", round_trips=1,
                         input_tokens=0, cached_input_tokens=0, cache_write_tokens=0,
                         output_tokens=0, reasoning_tokens=0, cost_usd=0.0, message_texts=texts)
    return call_model


def case(name, question, triage_texts, status, outcome, score_texts=DEFAULT_SCORE,
         cast_texts=DEFAULT_CAST, **expect):
    """expect: research_needed, researcher_status, invalid, guard (call 1);
    scoring (a subset of Scoring), score_invalid, classification_null (call 2);
    cast (a subset of CastRecord), cast_invalid (call 3)."""
    return dict(name=name, question=question, triage=triage_texts, score=score_texts,
                cast=cast_texts, status=status, outcome=outcome, expect=expect)


PROCEED = dict(outcome="proceed", canonical_question="Should a city ban private cars from its centre?",
               answer_criterion="A direct answer says whether the city should, and why.",
               factual_posture="mixed")
CITY = "should cities ban cars downtown"
P = [canned(**PROCEED)]
RESEARCH_GAP = [{"gap": "Measured traffic deaths after existing bans", "kind": "needs_research"}]
ok_unit = unit([1, 1, 1, 1, 1])

CASES_4A = [
    case("answer_directly", "What is 17 times 23?",
         [canned(outcome="answer_directly", direct_answer="391")], "complete", "answered_directly"),
    case("clarify", "Should I take it?",
         [canned(outcome="clarify", clarifying_question="What is the 'it' you are deciding about?")],
         "complete", "awaiting_clarification"),
    case("reframe_or_reject", "Which number will win next week's lottery?",
         [canned(outcome="reframe_or_reject", explanation="No reasoning can ground a lottery draw.",
                 suggested_question="Is it rational to buy lottery tickets?")],
         "complete", "reframed"),
    case("reframe_or_reject, no suggestion", "Which number will win next week's lottery?",
         [canned(outcome="reframe_or_reject", explanation="No reasoning can ground a lottery draw.")],
         "complete", "rejected"),
    case("proceed", CITY,
         [canned(**PROCEED, factual_gaps=[{"gap": "Which city", "kind": "user_can_supply"}])],
         "complete", "framed", research_needed=False, researcher_status=None,
         scoring={"topology": "hub_and_spoke", "score_status": "final"}),
    case("proceed + needs_research", CITY, [canned(**PROCEED, factual_gaps=RESEARCH_GAP)],
         "complete", "framed", research_needed=True, researcher_status="not_built"),
    case("answer_directly, null direct_answer", "What is 17 times 23?",
         [canned(outcome="answer_directly")], "failed", None,
         invalid="answer_directly: direct_answer must be non-empty"),
    case("proceed carrying direct_answer", CITY, [canned(**PROCEED, direct_answer="Yes.")],
         "failed", None, invalid="proceed: direct_answer must be null"),
    case("two valid message items (H4)", "What is 17 times 23?",
         [canned(outcome="answer_directly", direct_answer="391")] * 2, "failed", None,
         invalid="H4: 2 of 2"),
    case("token-ring in canonical only", "How should a committee take turns speaking?",
         [canned(**{**PROCEED, "canonical_question": "Should a committee speak in a token-ring order?"})],
         "failed", None, guard=["token-ring"]),
    case("token ring (unhyphenated) in canonical only", "How should a committee take turns speaking?",
         [canned(**{**PROCEED, "canonical_question": "Should a committee speak in a token ring order?"})],
         "failed", None, guard=["token-ring"]),
    case("token_ring (underscore) in canonical only", "How should a committee take turns speaking?",
         [canned(**{**PROCEED, "canonical_question": "Should a committee speak in a token_ring order?"})],
         "failed", None, guard=["token-ring"]),
    case("token-ring in both", "Is a token-ring order fair for a committee?",
         [canned(**{**PROCEED, "canonical_question": "Is a token-ring speaking order fair for a committee?"})],
         "complete", "framed"),
]

CASES_4B = [
    case("single, total 4 (boundary)", CITY, P, "complete", "framed",
         [scored("single", [unit([1, 1, 1, 1, 0])])],
         scoring={"unit_totals": [4], "governing_total": 4, "topology": "hub_and_spoke",
                  "rule": "governing total 4 ≤ 4 → hub_and_spoke"}),
    case("single, total 5 (boundary)", CITY, P, "complete", "framed",
         [scored("single", [unit([1, 1, 1, 1, 1])])],
         scoring={"unit_totals": [5], "governing_total": 5, "topology": "token_ring",
                  "rule": "governing total 5 ≥ 5 → token_ring"}),
    case("compound, totals 3 and 6", CITY, P, "complete", "framed",
         [scored("compound", [unit([1, 1, 1, 0, 0], "first"), unit([2, 1, 1, 1, 1], "second")],
                 secondaries=["Political / Institutional"])],
         scoring={"unit_totals": [3, 6], "governing_unit": 1, "governing_total": 6,
                  "topology": "token_ring"}),
    case("nested, valid depends_on", CITY, P, "complete", "framed",
         [scored("nested", [unit([1, 1, 0, 0, 1], "prior"),
                            unit([1, 0, 1, 1, 1], "dependent", depends_on=0)])],
         scoring={"unit_totals": [3, 4], "governing_unit": 1, "topology": "hub_and_spoke"}),
    case("proceed + needs_research → provisional", CITY,
         [canned(**PROCEED, factual_gaps=RESEARCH_GAP)], "complete", "framed",
         research_needed=True, scoring={"score_status": "provisional_is_final_research_not_run"}),
    case("single with 2 units", CITY, P, "failed", None,
         [scored("single", [ok_unit, ok_unit])], score_invalid="single: exactly 1 unit required, got 2"),
    case("compound with 1 unit", CITY, P, "failed", None,
         [scored("compound", [ok_unit])], score_invalid="compound: at least 2 units required, got 1"),
    case("compound with non-null depends_on", CITY, P, "failed", None,
         [scored("compound", [ok_unit, unit([1] * 5, depends_on=0)])],
         score_invalid="compound: unit 1 depends_on must be null"),
    case("nested depends_on out of range", CITY, P, "failed", None,
         [scored("nested", [ok_unit, unit([1] * 5, depends_on=2)])],
         score_invalid="nested: unit 1 depends_on 2 is out of range 0..1"),
    case("nested self-reference", CITY, P, "failed", None,
         [scored("nested", [ok_unit, unit([1] * 5, depends_on=1)])],
         score_invalid="nested: unit 1 depends_on itself"),
    case("nested 2-unit cycle", CITY, P, "failed", None,
         [scored("nested", [unit([1] * 5, depends_on=1), unit([1] * 5, depends_on=0)])],
         score_invalid="nested: depends_on cycle through units 0 → 1 → 0"),
    case("primary also in secondaries", CITY, P, "failed", None,
         [scored("single", [ok_unit], secondaries=["Moral / Ethical"])],
         score_invalid="primary_archetype 'Moral / Ethical' also in secondary_archetypes"),
    case("three secondaries", CITY, P, "failed", None,
         [scored("single", [ok_unit], secondaries=["Political / Institutional",
                                                    "Economic / Systemic", "Social / Cultural"])],
         score_invalid="at most 2 secondary_archetypes, got 3"),
    case("empty rationale", CITY, P, "failed", None,
         [scored("single", [unit([1] * 5, empty_rationale="challenge_value")])],
         score_invalid="unit 0: challenge_value rationale must be non-empty"),
    case("two valid score items (H4)", CITY, P, "failed", None,
         DEFAULT_SCORE * 2, score_invalid="H4: 2 of 2"),
    case("clarify → no call 2", "Should I take it?",
         [canned(outcome="clarify", clarifying_question="What is the 'it' you are deciding about?")],
         "complete", "awaiting_clarification", classification_null=True),
]

C = DEFAULT_SCORE  # call 2 output for the call-3 cases
CASES_5B = [
    case("canonical with two '?'", CITY,
         [canned(**{**PROCEED, "canonical_question":
                    "Should a city ban private cars from its centre? And if so, when?"})],
         "failed", None, invalid="proceed: canonical_question must contain exactly one '?', found 2"),
    case("canonical with no '?'", CITY,
         [canned(**{**PROCEED, "canonical_question":
                    "Whether a city should ban private cars from its centre."})],
         "failed", None, invalid="proceed: canonical_question must contain exactly one '?', found 0"),
    case("clarifying question with two '?'", "Should I take it?",
         [canned(outcome="clarify",
                 clarifying_question="What is the 'it'? And when must you decide?")],
         "failed", None, invalid="clarify: clarifying_question must contain exactly one '?', found 2"),
]

CASES_4C = [
    case("valid cast: Marcus, Darwin and Plato adequate, one unassessable", CITY, P, "complete", "framed", C,
         cast={"would_reject": [], "gate_unassessable": ["frederick_douglass"],
               "gate_not_applied": "roster exhausted",
               "near_miss_note": "roster of four; none to miss"}),
    case("valid cast: Marcus corpus weak", CITY, P, "complete", "framed", C,
         [cast_out([assess("marcus_aurelius", corpus="weak")] + OTHERS)],
         cast={"would_reject": ["marcus_aurelius"], "gate_not_applied": "roster exhausted"}),
    case("figure assessed twice", CITY, P, "failed", None, C,
         [cast_out([MARCUS, MARCUS] + OTHERS)],
         cast_invalid="marcus_aurelius assessed 2 times; exactly once required"),
    case("figure missing", CITY, P, "failed", None, C,
         [cast_out([MARCUS] + OTHERS[:2])], cast_invalid="roster figure charles_darwin not assessed"),
    case("unknown figure assessed", CITY, P, "failed", None, C,
         [cast_out([MARCUS] + OTHERS + [assess("socrates")])],
         cast_invalid="unknown figure socrates assessed"),
    case("not-built figure rated strong", CITY, P, "failed", None, C,
         [cast_out([MARCUS, OTHERS[0], assess("frederick_douglass", corpus="strong"), OTHERS[2]])],
         cast_invalid="frederick_douglass: corpus_suitability is strong, but its corpus is not_built"),
    case("built figure rated unassessable", CITY, P, "failed", None, C,
         [cast_out([assess("marcus_aurelius")] + OTHERS)],
         cast_invalid="marcus_aurelius: corpus_suitability is unassessable, but its corpus is built"),
    case("3 selected", CITY, P, "failed", None, C,
         [cast_out(selected=ROSTER_IDS[:3])], cast_invalid="exactly 4 selected required, got 3"),
    case("duplicate in selected", CITY, P, "failed", None, C,
         [cast_out(selected=["marcus_aurelius", "marcus_aurelius", "plato", "charles_darwin"])],
         cast_invalid="selected must be distinct: marcus_aurelius repeated"),
    case("unknown id selected", CITY, P, "failed", None, C,
         [cast_out(selected=ROSTER_IDS[:3] + ["socrates"])],
         cast_invalid="unknown figure socrates selected"),
    case("near miss in the cast", CITY, P, "failed", None, C,
         [cast_out(near_misses=[{"figure_id": "plato", "reason": "canned"}])],
         cast_invalid="near miss plato is in selected"),
    case("empty panel field", CITY, P, "failed", None, C,
         [cast_out(tension="")], cast_invalid="panel_tension must be non-empty"),
    case("two valid cast items (H4)", CITY, P, "failed", None, C,
         DEFAULT_CAST * 2, cast_invalid="H4: 2 of 2"),
    case("clarify → no call 2 or 3", "Should I take it?",
         [canned(outcome="clarify", clarifying_question="What is the 'it' you are deciding about?")],
         "complete", "awaiting_clarification", classification_null=True),
]

# Words that would show call 3 saw scoring or routing. Snake and spaced forms of the dimensions.
CAST_INPUT_FORBIDDEN = ["score", "topology", "token ring", "hub and spoke", "token_ring",
                        "hub_and_spoke", "threshold",
                        "governing", "rationale", *DIMENSION_NAMES, *DIMENSIONS]


def check_cast_request(c, events, run_dir) -> list[str]:
    """Inspect call 3's recorded request: the input is exactly what code built from the canonical
    question, call 2's archetypes and the roster, and carries no score, topology or original."""
    types = [e.type for e in events]
    bound = events[types.index("host_cast_bound")]
    trip = events[types.index("host_cast_bound") + 1]
    if trip.type != "round_trip":
        return ["no round_trip after host_cast_bound"]
    request = json.loads((run_dir / "raw" / trip.payload["raw_file"]).read_text())["request"]
    misses = []
    if request["input"] != bound.payload["input_items"]:
        misses.append("recorded request input differs from host_cast_bound input_items")
    triage = next(e.payload["triage"] for e in events if e.type == "host_triage")
    classification = next(e.payload["classification"] for e in events
                          if e.type == "host_classification")
    expected = host_cast.build_input(
        triage["canonical_question"], classification["primary_archetype"],
        classification["secondary_archetypes"], host_cast.roster_input(host_cast.load_roster()))
    if request["input"] != expected:
        misses.append("call 3 input is not exactly question + archetypes + roster")
    text = normalise(json.dumps(request["input"], ensure_ascii=False))
    canonical = normalise(triage["canonical_question"])  # its own words are allowed through
    hits = [w for w in CAST_INPUT_FORBIDDEN if normalise(w) in text and normalise(w) not in canonical]
    if hits:
        misses.append(f"call 3 input contains {hits}")
    if normalise(c["question"]) in text:
        misses.append("call 3 input contains the original wording")
    if request["instructions"] != host_cast.PROMPT.read_text(encoding="utf-8"):
        misses.append("call 3 instructions are not prompts/host_cast.md")
    return misses


def check_case(c, events, summary, calls, run_dir) -> list[str]:
    """What did not match. Empty means the case passed."""
    status, outcome, expect = c["status"], c["outcome"], c["expect"]
    by_type = {}
    for e in events:
        by_type.setdefault(e.type, []).append(e.payload)
    misses = []

    # Call 2 runs if and only if call 1 proceeded cleanly; call 3 if and only if call 2 did too.
    want_cast_calls = 1 if (outcome == "framed" or "cast_invalid" in expect) else 0
    want_score_calls = 1 if (want_cast_calls or "score_invalid" in expect) else 0
    if calls["triage"] != ["host_triage"]:
        misses.append(f"call 1 patch called {calls['triage']}")
    if len(calls["score"]) != want_score_calls:
        misses.append(f"call 2 patch called {len(calls['score'])} times, expected {want_score_calls}")
    if len(calls["cast"]) != want_cast_calls:
        misses.append(f"call 3 patch called {len(calls['cast'])} times, expected {want_cast_calls}")
    want_trips = 1 + want_score_calls + want_cast_calls
    trips = by_type.get("round_trip", [])
    if len(trips) != want_trips or not all(t.get("offline_canned") for t in trips):
        misses.append(f"expected {want_trips} canned round_trips, got {len(trips)}")
    if want_cast_calls:
        misses += check_cast_request(c, events, run_dir)

    if summary["status"] != status:
        misses.append(f"status {summary['status']} != {status}")
    ann = summary["annotations"]
    if ann.get("host_outcome") != outcome:
        misses.append(f"host_outcome {ann.get('host_outcome')} != {outcome}")
    if "host_prompt_sha256" not in ann:
        misses.append("host_prompt_sha256 not annotated")
    want_choir = status == "complete" and outcome == "framed"
    if ("choir_input" in by_type) != want_choir:
        misses.append(f"choir_input emitted: {'choir_input' in by_type}, expected {want_choir}")

    records = by_type.get("host_decision_record", [])
    if len(records) != (1 if status == "complete" else 0):
        misses.append(f"{len(records)} host_decision_record events")
    record = records[0] if records else {}
    if record and record["schema_version"] != "3":
        misses.append(f"record schema_version {record['schema_version']}")
    for key in ("research_needed", "researcher_status"):
        if key in expect and record.get(key) != expect[key]:
            misses.append(f"record {key} {record.get(key)!r} != {expect[key]!r}")
    if record:
        scored_run = outcome == "framed"
        if any((record[k] is not None) != scored_run for k in ("classification", "scoring", "cast")):
            misses.append("record classification/scoring/cast presence wrong for the outcome")
        if scored_run:
            if record["cast"] != by_type.get("host_cast", [{}])[0].get("cast"):
                misses.append("host_cast event differs from the record's cast")
            if set(record["prompt_sha256"]) != {"triage", "score", "cast"}:
                misses.append(f"record prompt_sha256 keys {sorted(record['prompt_sha256'])}")
            if ann.get("topology") != record["scoring"]["topology"]:
                misses.append(f"topology annotation {ann.get('topology')!r}")
            if by_type.get("host_scoring", [None])[0] != record["scoring"]:
                misses.append("host_scoring event differs from the record's scoring")
    if expect.get("classification_null") and record and any(
            record[k] is not None for k in ("classification", "scoring", "cast")):
        misses.append("classification/scoring/cast not null")
    for key, want in expect.get("cast", {}).items():
        got = (record.get("cast") or {}).get(key)
        if got != want:
            misses.append(f"cast {key} {got!r} != {want!r}")
    for key, want in expect.get("scoring", {}).items():
        got = (record.get("scoring") or {}).get(key)
        if got != want:
            misses.append(f"scoring {key} {got!r} != {want!r}")

    for event_type, key in (("host_triage_invalid", "invalid"), ("host_score_invalid", "score_invalid"),
                            ("host_cast_invalid", "cast_invalid")):
        if key in expect:
            texts = [json.dumps(p, ensure_ascii=False) for p in by_type.get(event_type, [])]
            if not any(expect[key] in t for t in texts):
                misses.append(f"no {event_type} naming {expect[key]!r}")
    if "guard" in expect:
        tripped = by_type.get("host_guard_tripped", [])
        if not tripped or tripped[0]["phrases"] != expect["guard"]:
            misses.append(f"host_guard_tripped phrases {tripped} != {expect['guard']}")
    return misses


def check_prompt(module, label, error_type, term="topology") -> bool:
    _, sha = module.load_prompt()
    print(f"{module.PROMPT.relative_to(module.ROOT)}: passes · sha256 {sha}")
    text = module.PROMPT.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / module.PROMPT.name
        first_line_end = text.index("\n")
        copy.write_text(text[:first_line_end] + f"\nIt has a {term}." + text[first_line_end:],
                        encoding="utf-8")
        try:
            module.load_prompt(copy)
        except error_type as error:
            print(f"  temp copy with '{term}' inserted: fails · {error}")
            return f"'{term}'" in str(error)
    print(f"  temp copy with '{term}' inserted: PASSED — the {label} check did not fire")
    return False


async def offline() -> int:
    print("######## PROMPT-LOAD CHECKS")
    ok = check_prompt(host_triage, "tripwire", host_triage.HostGuardTripped)
    ok = check_prompt(host_score, "forbidden-term", host_score.HostScoreInvalid) and ok
    ok = check_prompt(host_cast, "forbidden-term", host_cast.HostCastInvalid, term="score") and ok
    rows = []
    for group, cases in (("4a", CASES_4A), ("4b", CASES_4B), ("4c", CASES_4C), ("5b", CASES_5B)):
        for c in cases:
            print(f"\n######## [{group}] {c['name']}  question={c['question']!r}")
            calls = {"triage": [], "score": [], "cast": []}
            real = host_triage.call_model, host_score.call_model, host_cast.call_model
            host_triage.call_model = fake_call_model(c["triage"], calls["triage"])
            host_score.call_model = fake_call_model(c["score"], calls["score"])
            host_cast.call_model = fake_call_model(c["cast"], calls["cast"])
            try:
                events, error = await run_one(c["question"])
            finally:
                host_triage.call_model, host_score.call_model, host_cast.call_model = real
            run_id = events[-1].run_id
            summary = json.loads((TRACES_DIR / run_id / "summary.json").read_text())
            misses = check_case(c, events, summary, calls, TRACES_DIR / run_id)
            if error:
                print(f"run failed: {error}")
            ann = summary["annotations"]
            rows.append((group, c["name"], run_id, summary["status"], ann.get("host_outcome"),
                         ann.get("topology"), len(calls["score"]), len(calls["cast"]), misses))
            ok = ok and not misses
    print("\n######## OFFLINE RUNS (0 live calls)")
    for group, name, run_id, status, outcome, topology, n2, n3, misses in rows:
        print(f"{'PASS' if not misses else 'FAIL'}  {group}  {name:<48} traces/{run_id}  "
              f"{status:<8} {outcome or '-':<22} {topology or '-':<13} call2×{n2} call3×{n3}"
              + (f"  {misses}" if misses else ""))
    print(f"\n{len(rows)} runs · all checks {'passed' if ok else 'FAILED'}")
    return 0 if ok else 1


# ---------------------------------------------------------------- live

async def live(question: str, triage_only: bool) -> int:
    events, error = await run_one(question, host_triage_only if triage_only else host_run)
    if error:
        print(f"RUN FAILED: {error}")
    if not events:
        return 1
    record = [e.payload for e in events if e.type == "host_decision_record"]
    if record:
        print("\n--- decision record ---")
        print(json.dumps(record[0], indent=2, ensure_ascii=False))
    trips = [e.payload for e in events if e.type == "round_trip"]
    print(f"\nlive calls: {len(trips)} · estimated cost: "
          f"${sum(t['est_cost_usd'] for t in trips):.8f}")
    print(f"trace: traces/{events[-1].run_id}")
    return 0 if events[-1].type == "run_complete" else 1


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question", nargs="?")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--triage-only", action="store_true")
    args = parser.parse_args()
    if args.offline == bool(args.question):
        parser.error("give a question, or --offline (not both)")
    if args.offline and args.triage_only:
        parser.error("--triage-only is for live runs")
    sys.exit(asyncio.run(offline() if args.offline else live(args.question, args.triage_only)))
