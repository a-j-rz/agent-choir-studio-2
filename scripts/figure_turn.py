"""One live figure turn against Marcus's corpus, with the Oracle. ≤ 13 model calls.

    python -m scripts.figure_turn "How should a person govern their own mind?" --condition A

Runs choir.figure_turn in Marcus's lane through the shared runner (core/runner.py), with the
question as a ChoirInput, and prints each event as it happens (role and lane), then the
contribution, the citation check, the Horizon reconciliation and the per-trip costs (figure and
Oracle). Exits non-zero if the run did not complete.
"""

import argparse
import asyncio
import json
import sys
from functools import partial

from choir.figure_turn import figure_turn
from core.events import Event
from core.runner import relay
from core.trace import TRACES_DIR
from host.records import ChoirInput
from retrieval import vectors

FIGURE = "marcus_aurelius"
TAG = {"both": "B", "lexical_only": "L", "semantic_only": "S"}


def line(event: Event) -> str:
    p = event.payload
    if event.type == "round_trip":
        calls = ", ".join(f"{c['name']}({c['arguments']})" for c in p["tool_calls_requested"])
        detail = (f"{event.role} trip {p['trip']} · {p['latency_s']}s · in {p['input_tokens']} "
                  f"(cached {p['cached_input_tokens']}) / out {p['output_tokens']} "
                  f"(reasoning {p['reasoning_tokens']}) · ${p['est_cost_usd']:.6f}"
                  + (f" · calls: {calls}" if calls else " · no tool calls"))
    elif event.type == "corpus_search":
        merged = " ".join(f"{m['passage_id']}:{TAG[m['source']]}" for m in p["merged"])
        detail = f"#{p['search_number']} {p['query']!r} → {merged}"
    elif event.type == "passage_opened":
        detail = (f"{p['passage_id']} ({p['locator']}) via {p['via']} · "
                  f"surfaced_by_search={p['surfaced_by_search']} · opens_left {p['opens_left']}")
    elif event.type == "tool_result":
        result = p["result"]
        if isinstance(result, dict) and "error" in result:
            detail = f"{p['name']} → ERROR {result['error']}"
        else:
            detail = f"{p['name']} → {len(json.dumps(result))} chars"
    elif event.type == "oracle_request":
        look = p["lookup"]
        detail = (f"#{p['number']} {p['concept']!r} · {look['kind']} {look['lineage_id'] or ''} "
                  f"d={look['bridge_distance']} · where {p['where_encountered']!r} · identity "
                  f"{p['identity_terms_in_request']} redacted={p['redacted']} · "
                  f"repeat_of {p['repeat_of']}")
    elif event.type == "oracle_bridge":
        a = p["answer"]
        detail = f"#{p['number']} {a['status']} · anchors {a['anchors']}"
    elif event.type == "figure_bound":
        detail = f"condition {p['condition']} · tools {p['tools']} · budgets {p['budgets']}"
    elif event.type in ("contribution", "citation_check", "horizon_reconciliation",
                        "run_complete"):
        detail = "(below)" if event.type != "run_complete" else json.dumps(p)
    else:
        detail = json.dumps(p, ensure_ascii=False)
    lane = f"{event.role}:{event.figure}" if event.figure else event.role
    return f"#{event.seq:<3} {event.type:<22} {lane:<24} {detail}"


async def turn(trace, question: str, condition: str):
    """One turn in Marcus's lane. The condition is a run-level fact, so it is recorded here."""
    trace.annotate("condition", condition)
    model = await asyncio.to_thread(vectors.get_model)
    return await figure_turn(trace.for_figure(FIGURE), ChoirInput(canonical_question=question),
                             condition, model)


async def main(question: str, condition: str) -> int:
    body = partial(turn, question=question, condition=condition)
    events: list[Event] = []
    try:
        async for event in relay(body, f"figure turn: {FIGURE} (condition {condition})",
                                 render=lambda e: e):
            print(line(event), flush=True)
            events.append(event)
    except Exception as error:  # already in the trace as run_failed; say so and stop
        print(f"RUN FAILED: {error!r}")
    if not events:
        return 1
    print(f"\ntrace: traces/{events[-1].run_id}")
    for event in events:
        if event.type in ("contribution", "citation_check", "horizon_reconciliation"):
            print(f"\n{event.type}:\n{json.dumps(event.payload, indent=2, ensure_ascii=False)}")
    trips = [e.payload for e in events if e.type == "round_trip"]
    total = sum(t["est_cost_usd"] for t in trips)
    print(f"\n{'role':<8}{'trip':<6}{'input':>8}{'cached':>8}{'output':>8}{'reason':>8}"
          f"{'latency':>9}{'cost $':>12}")
    roles = [e.role for e in events if e.type == "round_trip"]
    for role, t in zip(roles, trips):
        print(f"{role:<8}{t['trip']:<6}{t['input_tokens']:>8}{t['cached_input_tokens']:>8}"
              f"{t['output_tokens']:>8}{t['reasoning_tokens']:>8}{t['latency_s']:>9}"
              f"{t['est_cost_usd']:>12.8f}")
    done = next((e.payload for e in events if e.type == "run_complete"), {})
    print(f"model calls: {len(trips)} (figure {roles.count('figure')}, oracle "
          f"{roles.count('oracle')}) · searches used {done.get('searches_used')} · Oracle "
          f"requests used {done.get('oracle_requests_used')} · estimated cost: ${total:.8f}")
    return 0 if events[-1].type == "run_complete" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--condition", choices=["A", "B"], required=True)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.question, args.condition)))
