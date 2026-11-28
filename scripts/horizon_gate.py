"""Self-collision gate: no breach term may match a figure's own corpus text. Offline; no model calls.

    python -m scripts.horizon_gate <figure_id>   # gate one figure
    python -m scripts.horizon_gate --all         # every figure host/roster.json marks corpus "built"
    python -m scripts.horizon_gate --selftest    # live state, injected collisions, a missing file

Lineages are shared, so a term added for one figure can collide with another figure's own words.
For each chunk in corpora/<figure_id>/data/chunks.jsonl, epistemic.horizon.find_breaches runs
against the committed compiled Horizon — the same matcher figure turns use, not a second one. The
compiled file must be current (horizon.check) first: a gate on a stale compile proves nothing. A
missing compiled file or chunks file fails, so a skipped gate never looks like a pass. Exit 1 on
any hit or failure.
"""

import argparse
import copy
import json
from pathlib import Path
import sys

from epistemic import horizon
from host.cast import load_roster

ROOT = horizon.HORIZONS_DIR.parent


class GateError(Exception):
    pass


def chunks_path(figure_id) -> Path:
    return ROOT / "corpora" / figure_id / "data" / "chunks.jsonl"


def load_compiled(figure_id) -> dict:
    path = horizon.compiled_path(horizon.HORIZONS_DIR, figure_id)
    if not path.is_file():
        raise GateError(f"no compiled Horizon at horizons/compiled/{figure_id}.json")
    stale = horizon.check(horizon.HORIZONS_DIR, figure_id)
    if stale:
        raise GateError(f"compiled Horizon is stale (differs in {', '.join(stale)}); recompile first")
    return json.loads(path.read_text(encoding="utf-8"))


def load_chunks(path: Path) -> list[dict]:
    if not path.is_file():
        raise GateError(f"no chunks file at {path.name} for this figure; build the corpus first")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def find_hits(chunks, compiled) -> list[dict]:
    """Every breach found in every chunk, sorted by chunk_id then position."""
    terms = {tuple(e["stems"]): e["terms"] for e in compiled["breach_stems"]}
    hits = []
    for chunk in chunks:
        for hit in horizon.find_breaches(chunk["text"], compiled):
            hits.append({"chunk_id": chunk["chunk_id"], "start_token": hit["start_token"],
                         "terms": terms[tuple(hit["stems"])], "stems": hit["stems"],
                         "lineages": hit["lineages"], "matched_surface": hit["matched_surface"]})
    return sorted(hits, key=lambda h: (h["chunk_id"], h["start_token"]))


def gate(figure_id, compiled=None, path=None) -> dict:
    """One figure's result. compiled and path override the committed files (selftest only)."""
    compiled = load_compiled(figure_id) if compiled is None else compiled
    chunks = load_chunks(chunks_path(figure_id) if path is None else path)
    return {"figure_id": figure_id, "chunks": len(chunks),
            "breach_sequences": len(compiled["breach_stems"]),
            "hits": find_hits(chunks, compiled)}


def run(figure_ids, paths=None) -> int:
    """Gate each figure in sorted order and print the result; 1 if any figure failed or hit."""
    failed = False
    for figure_id in sorted(figure_ids):
        try:
            result = gate(figure_id, path=(paths or {}).get(figure_id))
        except GateError as error:
            print(f"{figure_id}: FAILED — {error}")
            failed = True
            continue
        print(f"{figure_id}: {result['chunks']} chunks, {result['breach_sequences']} breach stem "
              f"sequences, {len(result['hits'])} hits")
        for h in result["hits"]:
            print(f"  {h['chunk_id']}  {h['matched_surface']!r}  stems {'+'.join(h['stems'])}  "
                  f"terms {h['terms']}  lineages {h['lineages']}")
        failed = failed or bool(result["hits"])
    return 1 if failed else 0


def built_figures() -> list[str]:
    return [f.figure_id for f in load_roster() if f.corpus == "built"]


def selftest() -> int:
    failures = []

    def check(label, ok, detail=""):
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))
        if not ok:
            failures.append(label)

    print("\n1 · live state")
    for figure_id in ("charles_darwin", "marcus_aurelius"):
        result = gate(figure_id)
        check(f"{figure_id}: 0 hits", result["hits"] == [],
              f"{result['chunks']} chunks, {result['breach_sequences']} breach sequences, "
              f"{len(result['hits'])} hits")
    darwin_chunks = gate("charles_darwin")["chunks"]
    check("charles_darwin: 1,874 chunks", darwin_chunks == 1874, f"{darwin_chunks}")
    report = json.loads((ROOT / "corpora/marcus_aurelius/data/chunk_report.json")
                        .read_text(encoding="utf-8"))
    marcus_chunks = gate("marcus_aurelius")["chunks"]
    if marcus_chunks != report["total_chunks"]:
        print(f"STOP: marcus_aurelius has {marcus_chunks} chunks; his chunk report says "
              f"{report['total_chunks']}")
        return 1
    check("marcus_aurelius: chunk count equals his chunk report", True,
          f"{marcus_chunks} = {report['total_chunks']}")

    print("\n2 · Darwin's historical collision: bare 'productivity'")
    stems = horizon.term_stems("productivity")
    if stems != ("product",):
        print(f"STOP: term_stems('productivity') is {stems}, not ('product',)")
        return 1
    check("term_stems('productivity') is ('product',)", True)
    darwin = load_compiled("charles_darwin")
    injected = copy.deepcopy(darwin)
    injected["breach_stems"].append({"stems": ["product"], "terms": ["productivity"],
                                     "lineages": ["test"]})
    hits = gate("charles_darwin", compiled=injected)["hits"]
    if len(hits) != 150:
        print(f"STOP: the gate found {len(hits)} hits, not 150. First 10:")
        for h in hits[:10]:
            print(f"      {h['chunk_id']}  {h['matched_surface']!r}")
        return 1
    surfaces = {}
    for h in hits:
        surfaces[h["matched_surface"].lower()] = surfaces.get(h["matched_surface"].lower(), 0) + 1
    check("150 hits", True, f"surfaces {dict(sorted(surfaces.items()))}")

    print("\n3 · a term that does not collide: 'smartphone'")
    injected = copy.deepcopy(darwin)
    injected["breach_stems"].append({"stems": list(horizon.term_stems("smartphone")),
                                     "terms": ["smartphone"], "lineages": ["test"]})
    hits = gate("charles_darwin", compiled=injected)["hits"]
    check("0 hits for Darwin", hits == [], f"{len(hits)} hits")

    print("\n4 · a missing chunks file")
    missing = ROOT / "corpora" / "charles_darwin" / "data" / "no_such_chunks.jsonl"
    code = run(["charles_darwin"], paths={"charles_darwin": missing})
    check("the gate fails with exit 1, not a pass", code == 1, f"exit {code}")

    print("\nSELFTEST", "PASSED" if not failures else f"FAILED ({len(failures)})")
    return 0 if not failures else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("figure_id", nargs="?")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if args.all:
        sys.exit(run(built_figures()))
    if not args.figure_id:
        parser.error("give a figure_id, --all or --selftest")
    sys.exit(run([args.figure_id]))


if __name__ == "__main__":
    main()
