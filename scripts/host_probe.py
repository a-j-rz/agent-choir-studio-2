"""Run Host call 1 (triage and framing). One live call, or none with --offline.

    python -m scripts.host_probe "<question>"   # one traced live run (1 model call)
    python -m scripts.host_probe --offline      # no live calls: prompt tripwire + canned runs

Offline: the prompt-load tripwire on prompts/host_triage.md and on a temp copy with "topology"
inserted; then each canned case as its own traced run, with host.triage.call_model patched to
return canned message items. The patch emits the same round_trip event call_model would, with
zero tokens and cost, marked offline_canned.
"""

import asyncio
from functools import partial
import json
from pathlib import Path
import sys
import tempfile

import host.triage as host_triage
from core.config import role_config
from core.events import Event
from core.llm import LLMResult
from core.runner import relay
from core.trace import TRACES_DIR


def line(event: Event) -> str:
    p = event.payload
    if event.type == "round_trip":
        d = (f"{p['latency_s']}s · in {p['input_tokens']} / out {p['output_tokens']} "
             f"(reasoning {p['reasoning_tokens']}) · ${p['est_cost_usd']:.6f}"
             + (" · OFFLINE CANNED" if p.get("offline_canned") else ""))
    elif event.type == "host_bound":
        d = f"{p['prompt_file']} sha256 {p['prompt_sha256'][:12]}… · {p['role_config']}"
    else:
        d = json.dumps(p, ensure_ascii=False)[:200]
    return f"#{event.seq:<3} {event.type:<22} {event.role:<7} {d}"


async def run_one(question: str, quiet=False) -> tuple[list[Event], str | None]:
    """One traced triage. Returns its events and the error, if the run failed."""
    events, error = [], None
    try:
        async for event in relay(partial(host_triage.triage, question=question),
                                 "host triage (4a)", render=lambda e: e):
            if not quiet:
                print(line(event), flush=True)
            events.append(event)
    except Exception as exc:
        error = repr(exc)
    return events, error


# ---------------------------------------------------------------- offline

def canned(**fields) -> str:
    """One message item: a full triage output, every field present, unset ones null / []."""
    out = {"outcome": None, "reason": "canned for the offline probe", "direct_answer": None,
           "clarifying_question": None, "explanation": None, "suggested_question": None,
           "canonical_question": None, "answer_criterion": None, "factual_posture": None,
           "factual_gaps": []}
    out.update(fields)
    return json.dumps(out)


def fake_call_model(texts: list[str]):
    async def call_model(*, role, instructions, input_items, tools, handlers, trace,
                         max_round_trips=8, text_format=None):
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


PROCEED = dict(outcome="proceed", canonical_question="Should a city ban private cars from its centre?",
               answer_criterion="A direct answer says whether the city should, and why.",
               factual_posture="mixed")
CASES = [
    # (name, question, message items, expected status, host_outcome, extra checks)
    ("answer_directly", "What is 17 times 23?",
     [canned(outcome="answer_directly", direct_answer="391")],
     "complete", "answered_directly", {}),
    ("clarify", "Should I take it?",
     [canned(outcome="clarify", clarifying_question="What is the 'it' you are deciding about?")],
     "complete", "awaiting_clarification", {}),
    ("reframe_or_reject", "Which number will win next week's lottery?",
     [canned(outcome="reframe_or_reject", explanation="No reasoning can ground a lottery draw.",
             suggested_question="Is it rational to buy lottery tickets?")],
     "complete", "reframed", {}),
    ("reframe_or_reject, no suggestion", "Which number will win next week's lottery?",
     [canned(outcome="reframe_or_reject", explanation="No reasoning can ground a lottery draw.")],
     "complete", "rejected", {}),
    ("proceed", "should cities ban cars downtown",
     [canned(**PROCEED, factual_gaps=[{"gap": "Which city", "kind": "user_can_supply"}])],
     "complete", "framed", {"research_needed": False, "researcher_status": None}),
    ("proceed + needs_research", "should cities ban cars downtown",
     [canned(**PROCEED, factual_gaps=[
         {"gap": "Measured traffic deaths after existing bans", "kind": "needs_research"}])],
     "complete", "framed", {"research_needed": True, "researcher_status": "not_built"}),
    ("answer_directly, null direct_answer", "What is 17 times 23?",
     [canned(outcome="answer_directly")],
     "failed", None, {"invalid": "answer_directly: direct_answer must be non-empty"}),
    ("proceed carrying direct_answer", "should cities ban cars downtown",
     [canned(**PROCEED, direct_answer="Yes.")],
     "failed", None, {"invalid": "proceed: direct_answer must be null"}),
    ("two valid message items (H4)", "What is 17 times 23?",
     [canned(outcome="answer_directly", direct_answer="391")] * 2,
     "failed", None, {"invalid": "H4: 2 of 2"}),
    ("token-ring in canonical only", "How should a committee take turns speaking?",
     [canned(**{**PROCEED, "canonical_question":
                "Should a committee speak in a token-ring order?"})],
     "failed", None, {"guard": ["token-ring"]}),
    ("token ring (unhyphenated) in canonical only", "How should a committee take turns speaking?",
     [canned(**{**PROCEED, "canonical_question":
                "Should a committee speak in a token ring order?"})],
     "failed", None, {"guard": ["token-ring"]}),
    ("token-ring in both", "Is a token-ring order fair for a committee?",
     [canned(**{**PROCEED, "canonical_question":
                "Is a token-ring speaking order fair for a committee?"})],
     "complete", "framed", {}),
]


def check_case(events, summary, status, outcome, extra) -> list[str]:
    """What did not match. Empty means the case passed."""
    by_type = {}
    for e in events:
        by_type.setdefault(e.type, []).append(e.payload)
    misses = []
    trips = by_type.get("round_trip", [])
    if len(trips) != 1 or not trips[0].get("offline_canned"):
        misses.append(f"expected exactly one canned round_trip, got {trips}")
    if summary["status"] != status:
        misses.append(f"status {summary['status']} != {status}")
    if summary["annotations"].get("host_outcome") != outcome:
        misses.append(f"host_outcome {summary['annotations'].get('host_outcome')} != {outcome}")
    if "host_prompt_sha256" not in summary["annotations"]:
        misses.append("host_prompt_sha256 not annotated")
    want_choir = status == "complete" and outcome == "framed"
    if ("choir_input" in by_type) != want_choir:
        misses.append(f"choir_input emitted: {'choir_input' in by_type}, expected {want_choir}")
    record = (by_type.get("host_decision_record") or [None])[0]
    if status == "complete" and record is None:
        misses.append("no host_decision_record")
    for key in ("research_needed", "researcher_status"):
        if key in extra and (record or {}).get(key) != extra[key]:
            misses.append(f"record {key} {(record or {}).get(key)!r} != {extra[key]!r}")
    if "invalid" in extra:
        texts = [json.dumps(p) for p in by_type.get("host_triage_invalid", [])]
        if not any(extra["invalid"] in t for t in texts):
            misses.append(f"no host_triage_invalid naming {extra['invalid']!r}")
    if "guard" in extra:
        tripped = by_type.get("host_guard_tripped", [])
        if not tripped or tripped[0]["phrases"] != extra["guard"]:
            misses.append(f"host_guard_tripped phrases {tripped} != {extra['guard']}")
    return misses


def check_prompt_tripwire() -> bool:
    print("######## PROMPT-LOAD TRIPWIRE")
    _, sha = host_triage.load_prompt()
    print(f"prompts/host_triage.md: passes · sha256 {sha}")
    text = host_triage.PROMPT.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "host_triage.md"
        copy.write_text(text.replace("instrument.", "instrument. It has a topology.", 1),
                        encoding="utf-8")
        try:
            host_triage.load_prompt(copy)
        except host_triage.HostGuardTripped as error:
            print(f"temp copy with 'topology' inserted: fails · {error}")
            return "'topology'" in str(error)
    print("temp copy with 'topology' inserted: PASSED — the tripwire did not fire")
    return False


async def offline() -> int:
    ok = check_prompt_tripwire()
    rows = []
    for name, question, texts, status, outcome, extra in CASES:
        print(f"\n######## {name}  question={question!r}")
        real = host_triage.call_model
        host_triage.call_model = fake_call_model(texts)
        try:
            events, error = await run_one(question)
        finally:
            host_triage.call_model = real
        run_id = events[-1].run_id
        summary = json.loads((TRACES_DIR / run_id / "summary.json").read_text())
        misses = check_case(events, summary, status, outcome, extra)
        if error:
            print(f"run failed: {error}")
        rows.append((name, run_id, summary["status"],
                     summary["annotations"].get("host_outcome"), misses))
        ok = ok and not misses
    print("\n######## OFFLINE RUNS (0 live calls)")
    for name, run_id, status, outcome, misses in rows:
        print(f"{'PASS' if not misses else 'FAIL'}  {name:<38} traces/{run_id}  {status:<8} "
              f"{outcome or '-'}" + (f"  {misses}" if misses else ""))
    print(f"\nall checks {'passed' if ok else 'FAILED'}")
    return 0 if ok else 1


# ---------------------------------------------------------------- live

async def live(question: str) -> int:
    events, error = await run_one(question)
    if error:
        print(f"RUN FAILED: {error}")
    if not events:
        return 1
    record = [e.payload for e in events if e.type == "host_decision_record"]
    if record:
        print("\n--- decision record ---")
        print(json.dumps(record[0], indent=2, ensure_ascii=False))
    cost = sum(e.payload["est_cost_usd"] for e in events if e.type == "round_trip")
    calls = sum(e.type == "round_trip" for e in events)
    print(f"\nlive calls: {calls} · estimated cost: ${cost:.8f}")
    print(f"trace: traces/{events[-1].run_id}")
    return 0 if events[-1].type == "run_complete" else 1


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question", nargs="?")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if args.offline == bool(args.question):
        parser.error("give a question, or --offline (not both)")
    sys.exit(asyncio.run(offline() if args.offline else live(args.question)))
