"""Probe the BM25 index: show why each chunk ranked. Offline; no model calls.

    python -m scripts.bm25_probe "governing one's own mind"
    python -m scripts.bm25_probe "ruling faculty" --json
    python -m scripts.bm25_probe --selftest

Build stats go to stderr so --json stdout stays byte-identical between runs.
"""

import argparse
import json
from pathlib import Path
import sys
import time

from retrieval import bm25


DEFAULT_CHUNKS = Path("corpora/marcus_aurelius/data/chunks.jsonl")

# Hand-computed outside the code (see the slice brief). Do not derive from bm25.py.
EXPECTED = [("d1", "mind", "idf", 0.98083), ("d1", "mind", "contribution", 1.34864),
            ("d1", "rule", "idf", 0.47000), ("d1", "rule", "contribution", 0.47000),
            ("d1", None, "score", 1.81864),
            ("d2", "rule", "contribution", 0.54421), ("d2", None, "score", 0.54421)]

# Tokeniser + stemmer cases from the 2c follow-up brief (expected stems given there).
TOKENISER_CASES = [("one's", ["one"]), ("one’s", ["one"]), ("gods'", ["god"]),
                   ("'tis", ["tis"]), ("self-control", ["self", "control"])]


def selftest():
    toy = {"d1": ["mind", "rule", "mind"], "d2": ["rule", "body"],
           "d3": ["body", "soul", "fate", "fate"]}
    index = bm25.build_from_analysed([
        {"chunk_id": cid, "locator": cid, "text": " ".join(words),
         "tokens": [(w, w) for w in words]} for cid, words in toy.items()])
    result = bm25.search_analysed(index, [("mind", "mind"), ("rule", "rule")])
    hits = {hit["chunk_id"]: hit for hit in result["hits"]}

    print(f"N={index['N']} avglen={index['avglen']:g} k1={bm25.K1} b={bm25.B}")
    print(f"{'check':<24}{'expected':>10}{'actual':>10}  ok")
    failures = 0
    for cid, stem, field, expected in EXPECTED:
        hit = hits.get(cid)
        if hit is None:
            actual = None
        elif stem is None:
            actual = hit["score"]
        else:
            term = next((t for t in hit["terms"] if t["stem"] == stem), None)
            actual = term[field] if term else None
        ok = actual is not None and round(actual, 5) == round(expected, 5)
        failures += not ok
        label = f"{cid} {stem or ''} {field}".replace("  ", " ")
        shown = "missing" if actual is None else f"{actual:.5f}"
        print(f"{label:<24}{expected:>10.5f}{shown:>10}  {'PASS' if ok else 'FAIL'}")

    tf_ok = hits.get("d1") and {t["stem"]: t["tf"] for t in hits["d1"]["terms"]} == {
        "mind": 2, "rule": 1}
    absent_ok = "d3" not in hits
    sums_ok = all(abs(sum(t["contribution"] for t in h["terms"]) - h["score"]) < 1e-12
                  for h in result["hits"])
    for label, ok in (("d1 tf mind=2 rule=1", tf_ok), ("d3 not returned", absent_ok),
                      ("contributions sum", sums_ok)):
        failures += not ok
        print(f"{label:<44}  {'PASS' if ok else 'FAIL'}")

    print(f"\n{'tokeniser input':<20}{'expected stems':<20}{'actual stems':<20}ok")
    for text, expected in TOKENISER_CASES:
        actual = [stem for _, stem in bm25.analyse(text)]
        ok = actual == expected
        failures += not ok
        print(f"{text:<20}{', '.join(expected):<20}{', '.join(actual):<20}"
              f"{'PASS' if ok else 'FAIL'}")
    print("SELFTEST", "PASSED" if not failures else f"FAILED ({failures})")
    return 0 if not failures else 1


def render(result, index):
    p = result["params"]
    texts = {doc["chunk_id"]: doc["text"] for doc in index["docs"]}
    lines = [f"BM25 k1={p['k1']} b={p['b']} N={p['N']} avglen={p['avglen']:.3f} "
             f"stemmer={p['stemmer']}", "",
             f"{'token':<16}{'stem':<16}{'df':>5}{'idf':>9}"]
    for q in result["query"]:
        flag = "" if q["in_corpus"] else "   <-- OUT OF CORPUS"
        lines.append(f"{q['token']:<16}{q['stem']:<16}{q['df']:>5}{q['idf']:>9.5f}{flag}")
    lines.append("")
    if not result["hits"]:
        lines.append("(no hits)")
    for hit in result["hits"]:
        lines.append(f"#{hit['rank']}  {hit['locator']}  [{hit['chunk_id']}]  "
                     f"score {hit['score']:.5f}  len {hit['length']}")
        for t in hit["terms"]:
            lines.append(f"      {t['stem']:<12} from {', '.join(t['surface_forms']):<24}"
                         f"tf {t['tf']:<3} idf {t['idf']:.5f}  contrib {t['contribution']:.5f}")
        text = " ".join(texts[hit["chunk_id"]].split())
        lines.append(f"      \"{text[:200]}{'…' if len(text) > 200 else ''}\"")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("query", nargs="?")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    args = parser.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if not args.query:
        parser.error("give a query or --selftest")

    started = time.perf_counter()
    index = bm25.build(args.chunks)
    elapsed = (time.perf_counter() - started) * 1000
    print(f"index: N={index['N']} vocab={len(index['df'])} avglen={index['avglen']:.3f} "
          f"build={elapsed:.1f} ms", file=sys.stderr)

    result = bm25.search(index, args.query, args.k)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render(result, index))


if __name__ == "__main__":
    main()
