"""Score one canonical question N times with Host call 2, and show where the scores move.

    python -m scripts.score_stability "<canonical question>" --runs 3   # N live calls

Each run is its own traced run calling host.score.score_canonical, with no call 1: the input is
the canonical question exactly as given. Then a table: per unit and dimension, the score in each
run; each run's decomposition, governing total and topology; and, per dimension, whether all runs
agreed.
"""

import argparse
import asyncio
import sys
from functools import partial

from core.runner import relay
from host.records import DIMENSIONS
from host.score import score_canonical


async def body(trace, canonical_question):
    scored = await score_canonical(trace, canonical_question)
    return {"governing_total": scored.scoring.governing_total, "topology": scored.scoring.topology}


async def one_run(question: str) -> dict:
    """One traced run. Returns what the table needs, read back from its events."""
    events, error = [], None
    try:
        async for event in relay(partial(body, canonical_question=question),
                                 "score stability (4b)", render=lambda e: e):
            events.append(event)
    except Exception as exc:
        error = repr(exc)
    by_type = {e.type: e.payload for e in events}
    trips = [e.payload for e in events if e.type == "round_trip"]
    return {"run_id": events[-1].run_id if events else None, "error": error,
            "classification": by_type.get("host_classification", {}).get("classification"),
            "scoring": by_type.get("host_scoring"),
            "cost": sum(t["est_cost_usd"] for t in trips),
            "reasoning": [t["reasoning_tokens"] for t in trips]}


def table(runs: list[dict]) -> str:
    ok = [r for r in runs if r["classification"]]
    n_units = max((len(r["classification"]["units"]) for r in ok), default=0)
    head = f"{'unit':<5} {'dimension':<26}" + "".join(f" {'run' + str(i + 1):<14}" for i in range(len(runs)))
    out = [head, "-" * len(head)]
    for u in range(n_units):
        for d in DIMENSIONS:
            cells = []
            for r in runs:
                units = (r["classification"] or {}).get("units", [])
                cells.append(str(units[u][d]["score"]) if u < len(units) else "-")
            out.append(f"{u:<5} {d:<26}" + "".join(f" {c:<14}" for c in cells))
    out.append("-" * len(head))
    for label, get in (("decomposition", lambda r: r["classification"]["decomposition"]),
                       ("unit totals", lambda r: r["scoring"]["unit_totals"]),
                       ("governing total", lambda r: r["scoring"]["governing_total"]),
                       ("topology", lambda r: r["scoring"]["topology"])):
        out.append(f"{'':<5} {label:<26}" + "".join(
            f" {str(get(r)) if r['classification'] else 'FAILED':<14}" for r in runs))
    out.append("")
    same_shape = len({len(r["classification"]["units"]) for r in ok}) == 1 and len(ok) == len(runs)
    for d in DIMENSIONS:
        if not same_shape:
            out.append(f"{d:<26} n/a (runs differ in units or a run failed)")
            continue
        per_run = [[unit[d]["score"] for unit in r["classification"]["units"]] for r in ok]
        out.append(f"{d:<26} {'all runs agreed' if all(p == per_run[0] for p in per_run) else 'DIFFERED'}")
    return "\n".join(out)


async def main(question: str, n: int) -> int:
    runs = []
    for i in range(n):
        r = await one_run(question)
        runs.append(r)
        print(f"run {i + 1}: traces/{r['run_id']}  reasoning {r['reasoning']}  ${r['cost']:.8f}"
              + (f"  FAILED {r['error']}" if r["error"] else ""), flush=True)
    print()
    print(table(runs))
    print(f"\nlive calls: {sum(len(r['reasoning']) for r in runs)} · estimated cost: "
          f"${sum(r['cost'] for r in runs):.8f}")
    return 0 if all(r["classification"] for r in runs) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--runs", type=int, required=True)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    sys.exit(asyncio.run(main(args.question, args.runs)))
