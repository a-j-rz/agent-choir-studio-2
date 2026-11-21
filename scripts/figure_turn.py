"""One live figure turn against Marcus's corpus. Costs a fraction of a cent (≤ 8 model calls).

    python -m scripts.figure_turn "How should a person govern their own mind?"

Runs choir.figure_turn through the shared runner (core/runner.py) and prints each event as it
happens, then the contribution, the citation check and the per-trip costs. Exits non-zero if
the run did not complete.
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

FIGURE = "marcus_aurelius"
TAG = {"both": "B", "lexical_only": "L", "semantic_only": "S"}


def line(event: Event) -> str:
    p = event.payload
    if event.type == "round_trip":
        calls = ", ".join(f"{c['name']}({c['arguments']})" for c in p["tool_calls_requested"])
        detail = (f"trip {p['trip']} · {p['latency_s']}s · in {p['input_tokens']} "
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
    elif event.type in ("contribution", "citation_check", "run_complete"):
        detail = "(below)" if event.type != "run_complete" else json.dumps(p)
    else:
        detail = json.dumps(p, ensure_ascii=False)
    return f"#{event.seq:<3} {event.type:<22} {event.role:<16} {detail}"


async def main(question: str) -> int:
    body = partial(figure_turn, figure_id=FIGURE, question=question)
    events: list[Event] = []
    try:
        async for event in relay(body, f"figure turn: {FIGURE}", render=lambda e: e):
            print(line(event), flush=True)
            events.append(event)
    except Exception as error:  # already in the trace as run_failed; say so and stop
        print(f"RUN FAILED: {error!r}")
    if not events:
        return 1
    print(f"\ntrace: traces/{events[-1].run_id}")
    for event in events:
        if event.type in ("contribution", "citation_check"):
            print(f"\n{event.type}:\n{json.dumps(event.payload, indent=2, ensure_ascii=False)}")
    trips = [e.payload for e in events if e.type == "round_trip"]
    total = sum(t["est_cost_usd"] for t in trips)
    print(f"\n{'trip':<6}{'input':>8}{'cached':>8}{'output':>8}{'reason':>8}{'latency':>9}{'cost $':>12}")
    for t in trips:
        print(f"{t['trip']:<6}{t['input_tokens']:>8}{t['cached_input_tokens']:>8}"
              f"{t['output_tokens']:>8}{t['reasoning_tokens']:>8}{t['latency_s']:>9}"
              f"{t['est_cost_usd']:>12.8f}")
    print(f"model calls: {len(trips)} · estimated cost: ${total:.8f}")
    return 0 if events[-1].type == "run_complete" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.question)))
