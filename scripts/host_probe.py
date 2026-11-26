"""Run the Host: call 1 (triage), then call 2 (scoring) on proceed. Or none, with --offline.

    python -m scripts.host_probe "<question>"                 # one live run (1 or 2 calls)
    python -m scripts.host_probe --triage-only "<question>"   # call 1 alone (1 call)
    python -m scripts.host_probe --offline                    # no live calls: prompt checks + canned runs

Offline: the prompt-load checks on both prompts (and on temp copies with "topology" inserted);
then each canned case as its own traced run, with call_model patched separately in host.triage
and host.score. Each patch records how often it was called and emits the same round_trip event
call_model would, with zero tokens and cost, marked offline_canned.
"""

import asyncio
from functools import partial
import json
from pathlib import Path
import sys
import tempfile

import host.score as host_score
import host.triage as host_triage
from core.config import role_config
from core.events import Event
from core.llm import LLMResult
from core.runner import relay
from core.trace import TRACES_DIR
from host.records import DIMENSIONS
from host.run import host_run, host_triage_only


def line(event: Event) -> str:
    p = event.payload
    if event.type == "round_trip":
        d = (f"{p['latency_s']}s · in {p['input_tokens']} / out {p['output_tokens']} "
             f"(reasoning {p['reasoning_tokens']}) · ${p['est_cost_usd']:.6f}"
             + (" · OFFLINE CANNED" if p.get("offline_canned") else ""))
    elif event.type in ("host_bound", "host_score_bound"):
        d = f"{p['prompt_file']} sha256 {p['prompt_sha256'][:12]}… · {p['role_config']}"
    elif event.type == "host_scoring":
        d = f"totals {p['unit_totals']} · governing unit {p['governing_unit']} · {p['rule']} · {p['score_status']}"
    else:
        d = json.dumps(p, ensure_ascii=False)[:200]
    return f"#{event.seq:<3} {event.type:<22} {event.role:<7} {d}"


async def run_one(question: str, body=host_run, quiet=False) -> tuple[list[Event], str | None]:
    """One traced Host run. Returns its events and the error, if the run failed."""
    events, error = [], None
    note = "host run (4b)" if body is host_run else "host triage only (4b)"
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


def case(name, question, triage_texts, status, outcome, score_texts=DEFAULT_SCORE, **expect):
    """expect: research_needed, researcher_status, invalid, guard (call 1);
    scoring (a subset of Scoring), score_invalid, classification_null (call 2)."""
    return dict(name=name, question=question, triage=triage_texts, score=score_texts,
                status=status, outcome=outcome, expect=expect)


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


def check_case(c, events, summary, calls) -> list[str]:
    """What did not match. Empty means the case passed."""
    status, outcome, expect = c["status"], c["outcome"], c["expect"]
    by_type = {}
    for e in events:
        by_type.setdefault(e.type, []).append(e.payload)
    misses = []

    # Call 2 runs if and only if call 1 proceeded cleanly.
    want_score_calls = 1 if (outcome == "framed" or "score_invalid" in expect) else 0
    if calls["triage"] != ["host_triage"]:
        misses.append(f"call 1 patch called {calls['triage']}")
    if len(calls["score"]) != want_score_calls:
        misses.append(f"call 2 patch called {len(calls['score'])} times, expected {want_score_calls}")
    trips = by_type.get("round_trip", [])
    if len(trips) != 1 + want_score_calls or not all(t.get("offline_canned") for t in trips):
        misses.append(f"expected {1 + want_score_calls} canned round_trips, got {len(trips)}")

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
    if record and record["schema_version"] != "2":
        misses.append(f"record schema_version {record['schema_version']}")
    for key in ("research_needed", "researcher_status"):
        if key in expect and record.get(key) != expect[key]:
            misses.append(f"record {key} {record.get(key)!r} != {expect[key]!r}")
    if record:
        scored_run = outcome == "framed"
        if (record["classification"] is not None) != scored_run or (
                record["scoring"] is not None) != scored_run:
            misses.append("record classification/scoring presence wrong for the outcome")
        if scored_run:
            if set(record["prompt_sha256"]) != {"triage", "score"}:
                misses.append(f"record prompt_sha256 keys {sorted(record['prompt_sha256'])}")
            if ann.get("topology") != record["scoring"]["topology"]:
                misses.append(f"topology annotation {ann.get('topology')!r}")
            if by_type.get("host_scoring", [None])[0] != record["scoring"]:
                misses.append("host_scoring event differs from the record's scoring")
    if expect.get("classification_null") and record and (
            record["classification"] is not None or record["scoring"] is not None):
        misses.append("classification/scoring not null")
    for key, want in expect.get("scoring", {}).items():
        got = (record.get("scoring") or {}).get(key)
        if got != want:
            misses.append(f"scoring {key} {got!r} != {want!r}")

    for event_type, key in (("host_triage_invalid", "invalid"), ("host_score_invalid", "score_invalid")):
        if key in expect:
            texts = [json.dumps(p, ensure_ascii=False) for p in by_type.get(event_type, [])]
            if not any(expect[key] in t for t in texts):
                misses.append(f"no {event_type} naming {expect[key]!r}")
    if "guard" in expect:
        tripped = by_type.get("host_guard_tripped", [])
        if not tripped or tripped[0]["phrases"] != expect["guard"]:
            misses.append(f"host_guard_tripped phrases {tripped} != {expect['guard']}")
    return misses


def check_prompt(module, label, error_type) -> bool:
    _, sha = module.load_prompt()
    print(f"{module.PROMPT.relative_to(module.ROOT)}: passes · sha256 {sha}")
    text = module.PROMPT.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / module.PROMPT.name
        first_line_end = text.index("\n")
        copy.write_text(text[:first_line_end] + "\nIt has a topology." + text[first_line_end:],
                        encoding="utf-8")
        try:
            module.load_prompt(copy)
        except error_type as error:
            print(f"  temp copy with 'topology' inserted: fails · {error}")
            return "'topology'" in str(error)
    print(f"  temp copy with 'topology' inserted: PASSED — the {label} check did not fire")
    return False


async def offline() -> int:
    print("######## PROMPT-LOAD CHECKS")
    ok = check_prompt(host_triage, "tripwire", host_triage.HostGuardTripped)
    ok = check_prompt(host_score, "forbidden-term", host_score.HostScoreInvalid) and ok
    rows = []
    for group, cases in (("4a", CASES_4A), ("4b", CASES_4B)):
        for c in cases:
            print(f"\n######## [{group}] {c['name']}  question={c['question']!r}")
            calls = {"triage": [], "score": []}
            real = host_triage.call_model, host_score.call_model
            host_triage.call_model = fake_call_model(c["triage"], calls["triage"])
            host_score.call_model = fake_call_model(c["score"], calls["score"])
            try:
                events, error = await run_one(c["question"])
            finally:
                host_triage.call_model, host_score.call_model = real
            run_id = events[-1].run_id
            summary = json.loads((TRACES_DIR / run_id / "summary.json").read_text())
            misses = check_case(c, events, summary, calls)
            if error:
                print(f"run failed: {error}")
            ann = summary["annotations"]
            rows.append((group, c["name"], run_id, summary["status"], ann.get("host_outcome"),
                         ann.get("topology"), len(calls["score"]), misses))
            ok = ok and not misses
    print("\n######## OFFLINE RUNS (0 live calls)")
    for group, name, run_id, status, outcome, topology, n2, misses in rows:
        print(f"{'PASS' if not misses else 'FAIL'}  {group}  {name:<44} traces/{run_id}  "
              f"{status:<8} {outcome or '-':<22} {topology or '-':<13} call2×{n2}"
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
