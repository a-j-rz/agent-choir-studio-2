"""Probe hybrid retrieval and the bound corpus tools. Offline; no model API calls.

    python -m scripts.retrieval_probe --selftest      # RRF arithmetic, ties, figure-id guards
    python -m scripts.retrieval_probe --depth-table   # merged top 8 at depths 8 / 15 / 30
    python -m scripts.retrieval_probe --trace         # a real run trace, handlers called directly

--trace calls the bound handlers as a model would and, after each, emits the same
`tool_result` event core.llm.call_model emits, so the trace reads like a real turn.
"""

import argparse
import asyncio
import json
import sys
import time

from core.runner import run_work
from core.trace import RunTrace
from retrieval import hybrid, vectors
from retrieval.tools import bind_corpus_tools


FIGURE = "marcus_aurelius"
DEPTHS = (8, 15, 30)
TRACKED = {
    "governing one's own mind": [("IX.15", "ma-09-015"), ("I.1", "ma-01-001")],
    "mastering my thoughts": [("VII.68", "ma-07-068"), ("VI.53", "ma-06-053"),
                              ("IV.3-p2", "ma-04-003-p2"), ("X.38", "ma-10-038")],
}

# Hand-computed outside the code (see the 2e brief). Do not derive from hybrid.py.
RRF_EXPECTED = [("x", 0.032522), ("w", 0.016393), ("y", 0.016129), ("z", 0.015873)]


def selftest():
    failures = 0
    order = {item: i for i, item in enumerate(["w", "x", "y", "z"])}
    merged = hybrid.rrf(["x", "y", "z"], ["w", "x"], 60, order)
    print("RRF  A=[x, y, z]  B=[w, x]  k=60")
    print(f"{'pos':<5}{'expected':<18}{'actual':<18}ok")
    for pos, (want, got) in enumerate(zip(RRF_EXPECTED, merged), 1):
        ok = want[0] == got["id"] and round(got["rrf_score"], 6) == want[1]
        failures += not ok
        print(f"{pos:<5}{want[0]} {want[1]:.6f}{'':<8}{got['id']} {got['rrf_score']:.6f}"
              f"{'':<8}{'PASS' if ok else 'FAIL'}")
    if len(merged) != len(RRF_EXPECTED):
        failures += 1
        print(f"FAIL: {len(merged)} merged items, expected {len(RRF_EXPECTED)}")
    x = merged[0]
    print(f"x keeps both ranks: lexical #{x['lexical_rank']} ({x['lexical_contribution']:.6f})"
          f" + semantic #{x['semantic_rank']} ({x['semantic_contribution']:.6f})")

    # Ties: a/c both rank 1 of one list, b/d both rank 2. Corpus order d, c, b, a decides.
    tie_order = {"d": 0, "c": 1, "b": 2, "a": 3}
    ties = [e["id"] for e in hybrid.rrf(["a", "b"], ["c", "d"], 60, tie_order)]
    ok = ties == ["c", "a", "d", "b"]
    failures += not ok
    print(f"\nTIE  A=[a, b]  B=[c, d]  corpus order d, c, b, a")
    print(f"     expected c, a, d, b   actual {', '.join(ties)}   {'PASS' if ok else 'FAIL'}")

    print("\nFIGURE-ID GUARDS (load_figure must refuse before touching any other directory)")
    for bad in ("../marcus_aurelius", "marcus_aurelius/../x", "seneca", "/tmp"):
        try:
            hybrid.load_figure(bad, model=None)
            ok, outcome = False, "LOADED (bad)"
        except (ValueError, FileNotFoundError) as error:
            ok, outcome = True, f"{type(error).__name__}: {error}"
        failures += not ok
        print(f"     {bad!r:<26}{outcome}   {'PASS' if ok else 'FAIL'}")
    print("SELFTEST", "PASSED" if not failures else f"FAILED ({failures})")
    return 0 if not failures else 1


def depth_table(figure, model):
    lines = []
    for query, tracked in TRACKED.items():
        lines.append(f"=== {query!r} ===")
        for depth in DEPTHS:
            detail = hybrid.search(figure, model, query, depth=depth)
            merged = detail["merged"]
            both = sum(m["source"] == "both" for m in merged)
            lines.append(f"-- depth {depth}: both={both}  lexical_only="
                         f"{sum(m['source'] == 'lexical_only' for m in merged)}  semantic_only="
                         f"{sum(m['source'] == 'semantic_only' for m in merged)}  "
                         f"(BM25 matched {detail['lexical_matched_total']})")
            for m in merged:
                lex = f"#{m['lexical_rank']}" if m["lexical_rank"] else "-"
                sem = f"#{m['semantic_rank']}" if m["semantic_rank"] else "-"
                lines.append(f"   {m['rank']}. {m['locator']:<16}[{m['passage_id']}]  "
                             f"{m['source']:<14}lex {lex:<4}sem {sem:<4}rrf {m['rrf_score']:.6f}")
            ranks = {m["passage_id"]: m["rank"] for m in merged}
            tracked_text = "  ".join(f"{name} {'#' + str(ranks[cid]) if cid in ranks else 'out'}"
                                     for name, cid in tracked)
            lines.append(f"   tracked: {tracked_text}")
        lines.append("")
    return "\n".join(lines)


def make_trace_body(figure, model):
    async def body(trace):
        lane = trace.for_figure(FIGURE)
        _, handlers, _ = bind_corpus_tools(figure, model, lane)
        calls = [
            ("list_my_works", {}),
            ("search_my_corpus", {"query": "governing one's own mind"}),
            ("open_passage", {"passage_id": "ma-09-015"}),
            ("open_context", {"passage_id": "ma-01-001", "window": 1}),
            ("search_my_corpus", {"query": "mastering my thoughts"}),
            ("search_my_corpus", {"query": "death and dissolution"}),
            ("search_my_corpus", {"query": "anger at others"}),
            ("search_my_corpus", {"query": "the fifth search"}),          # must be refused
            ("open_passage", {"passage_id": "ma-99-999"}),                # must be refused
            ("open_context", {"passage_id": "ma-05-016", "window": 3}),   # must be refused
        ]
        for number, (name, args) in enumerate(calls, 1):
            started = time.monotonic()
            result = handlers[name](**args)
            # Same payload shape as core.llm.call_model's tool_result event.
            lane.emit("tool_result", "figure", {
                "name": name, "call_id": f"probe-{number}", "arguments": args,
                "result": result, "duration_s": round(time.monotonic() - started, 3)})
        return {"tool_calls": len(calls), "figure_id": figure["figure_id"]}
    return body


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--selftest", action="store_true")
    mode.add_argument("--depth-table", action="store_true")
    mode.add_argument("--trace", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        sys.exit(selftest())

    model, _ = vectors.load_model()
    figure = hybrid.load_figure(FIGURE, model)
    cache = figure["cache"]
    print(f"figure {figure['figure_id']}: {len(figure['chunks'])} chunks, "
          f"chunk figure_ids {sorted({c['figure_id'] for c in figure['chunks']})}, "
          f"vector cache {cache['status'].upper()}", file=sys.stderr)
    if args.depth_table:
        print(depth_table(figure, model))
        return
    trace = RunTrace()
    asyncio.run(run_work(trace, make_trace_body(figure, model), note="2e retrieval probe"))
    print(f"run directory: traces/{trace.run_id}")


if __name__ == "__main__":
    main()
