"""Compile a figure's Epistemic Horizon from horizons/ sources. Offline; no model calls.

    python -m scripts.compile_horizon <figure_id>            # write horizons/compiled/<id>.json
    python -m scripts.compile_horizon <figure_id> --check    # exit 1 if the committed file is stale
    python -m scripts.compile_horizon --selftest             # toy data, built in

--root DIR points at another horizons directory (default: the repo's horizons/).
"""

import argparse
import json
from pathlib import Path
import sys
import tempfile

from epistemic import horizon
from epistemic.horizon import HorizonError


# ---- toy data: traditions A, B; profile in A, horizon 350, exception include t1 ----------

def _sense(sense_id, tradition, year, terms, markers=()):
    return {"sense_id": sense_id, "label": sense_id, "summary": "toy",
            "available_in": [{"tradition": tradition, "from": year, "precision": "exact"}],
            "prerequisites": [], "terms": list(terms), "markers": list(markers),
            "hazards": [], "sources": [{"citation": "toy", "note": "toy"}],
            "confidence": "high"}


def _lineage(lineage_id, senses):
    return {"schema_version": "1", "lineage_id": lineage_id, "label": lineage_id,
            "lcc_class": "B", "wikidata": None, "senses": senses}


def toy_files():
    return {
        "traditions.json": {"schema_version": "1", "traditions": [
            {"tradition_id": "A", "label": "Tradition A"},
            {"tradition_id": "B", "label": "Tradition B"}]},
        "lineages/L1.json": _lineage("L1", [
            _sense("L1.s1", "A", 100, ["alpha", "shared"]),
            _sense("L1.s2", "B", 150, ["beta"]),
            _sense("L1.s3", "A", 300, ["gamma", "shared2"], ["m3"]),
            _sense("L1.s4", "A", 500, ["delta"], ["m4"])]),
        "lineages/L2.json": _lineage("L2", [
            _sense("L2.t1", "B", 50, ["pump"]),
            _sense("L2.t2", "A", 400, ["epsilon"])]),
        "lineages/L3.json": _lineage("L3", [
            _sense("L3.u1", "A", 1000, ["pump", "zeta"], ["mu1"])]),
        "profiles/toy.json": {
            "schema_version": "1", "figure_id": "toy", "lived": {"born": 300, "died": 360},
            "horizon_year": 350, "horizon_year_basis": "toy", "milieu": "toy",
            "traditions": [{"tradition": "A", "basis": "toy", "confidence": "high"}],
            "exceptions": [{"sense_id": "L2.t1", "include": True, "basis": "toy",
                            "confidence": "high"}],
            "oracle_epoch": "A toy epoch."},
    }


def write_tree(root: Path, files: dict):
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# Hand-computed outside the code (see the 3a-i brief). Do not derive from horizon.py.
# lineage: (available sense, beyond [(sense, distance)], unreached, breach_markers)
EXPECTED_MAIN = {
    "L1": ("s3", [("s4", 1)], ["s2"], ["m4"]),
    "L2": ("t1", [("t2", 1)], [], []),
    "L3": (None, [("u1", 1)], [], ["mu1"]),
}
EXPECTED_MAIN_TERMS = ["beta", "delta", "epsilon", "zeta"]
EXPECTED_VARIANT = {
    "L1": ("s1", [("s4", 1)], ["s2", "s3"], ["m3", "m4"]),
    "L2": ("t1", [("t2", 1)], [], []),
    "L3": (None, [("u1", 1)], [], ["mu1"]),
}
EXPECTED_VARIANT_TERMS = ["beta", "delta", "epsilon", "gamma", "shared2", "zeta"]
# Main case + L4 (v1 in B from 900: a tradition the profile lacks, after the horizon).
EXPECTED_L4 = ("L4", (None, [("v1", 1)], [], []))
EXPECTED_L4_TERM = "theta"


def _short(sense_id):
    return sense_id.split(".", 1)[1]


def _actual(compiled):
    out = {}
    for rec in compiled["lineages"]:
        avail = rec["available_sense"]
        out[rec["lineage_id"]] = (
            _short(avail["sense_id"]) if avail else None,
            [(_short(b["sense_id"]), b["bridge_distance"]) for b in rec["beyond"]],
            [_short(u["sense_id"]) for u in rec["unreached"]],
            rec["breach_markers"])
    return out


def _show(value):
    avail, beyond, unreached, markers = value
    b = ", ".join(f"{s}→{d}" for s, d in beyond)
    return f"avail {avail} · beyond [{b}] · unreached [{', '.join(unreached)}] · markers [{', '.join(markers)}]"


def _compare(title, compiled, expected, expected_terms):
    failures = 0
    print(f"\n{title}")
    actual = _actual(compiled)
    for lineage_id, want in expected.items():
        got = actual.get(lineage_id)
        ok = got == want
        failures += not ok
        print(f"  {lineage_id} expected {_show(want)}")
        print(f"     actual   {_show(got) if got else 'missing'}   {'PASS' if ok else 'FAIL'}")
    ok = compiled["breach_terms"] == expected_terms
    failures += not ok
    print(f"  breach_terms expected {expected_terms}")
    print(f"               actual   {compiled['breach_terms']}   {'PASS' if ok else 'FAIL'}")
    return failures


def _rejects(label, files):
    with tempfile.TemporaryDirectory() as tmp:
        write_tree(Path(tmp), files)
        try:
            horizon.build(Path(tmp), "toy")
            print(f"  {label:<34} NOT REJECTED   FAIL")
            return 1
        except HorizonError as error:
            print(f"  {label:<34} PASS  {str(error)[:150]}")
            return 0


def selftest():
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_tree(root, toy_files())
        main = json.loads(horizon.build(root, "toy"))
        failures += _compare("MAIN (profile A, horizon 350, include t1)", main,
                             EXPECTED_MAIN, EXPECTED_MAIN_TERMS)
        via = {r["lineage_id"]: (r["available_sense"] or {}).get("via") for r in main["lineages"]}
        ok = via == {"L1": "tradition", "L2": "exception", "L3": None}
        failures += not ok
        print(f"  via: {via}   {'PASS' if ok else 'FAIL'}")

    variant = toy_files()
    variant["profiles/toy.json"]["exceptions"].append(
        {"sense_id": "L1.s3", "include": False, "basis": "toy", "confidence": "high"})
    with tempfile.TemporaryDirectory() as tmp:
        write_tree(Path(tmp), variant)
        failures += _compare("VARIANT (+ exception include: false on s3)",
                             json.loads(horizon.build(Path(tmp), "toy")),
                             EXPECTED_VARIANT, EXPECTED_VARIANT_TERMS)

    with_l4 = toy_files()
    with_l4["lineages/L4.json"] = _lineage("L4", [_sense("L4.v1", "B", 900, ["theta"])])
    with tempfile.TemporaryDirectory() as tmp:
        write_tree(Path(tmp), with_l4)
        compiled = json.loads(horizon.build(Path(tmp), "toy"))
        lineage_id, want = EXPECTED_L4
        got = _actual(compiled).get(lineage_id)
        print("\nOTHER TRADITION, AFTER THE HORIZON (main case + L4: v1 in B from 900)")
        ok = got == want
        failures += not ok
        print(f"  L4 expected {_show(want)}")
        print(f"     actual   {_show(got) if got else 'missing'}   {'PASS' if ok else 'FAIL'}")
        ok = EXPECTED_L4_TERM in compiled["breach_terms"]
        failures += not ok
        print(f"  {EXPECTED_L4_TERM!r} in breach_terms {compiled['breach_terms']}   "
              f"{'PASS' if ok else 'FAIL'}")

    print("\nREJECTIONS")
    cases = []
    f = toy_files(); f["lineages/L1.json"]["lcc_class"] = "I"
    cases.append(("lcc_class 'I'", f))
    f = toy_files(); f["lineages/L1.json"]["senses"][0]["sense_id"] = "s1"
    cases.append(("sense_id without lineage prefix", f))
    f = toy_files(); f["lineages/L1.json"]["senses"][2]["prerequisites"] = ["L1.nope"]
    cases.append(("dangling prerequisite", f))
    f = toy_files(); f["lineages/L2.json"]["senses"][1]["available_in"][0]["tradition"] = "C"
    cases.append(("unknown tradition", f))
    f = toy_files(); f["profiles/toy.json"]["exceptions"][0]["sense_id"] = "L9.x"
    cases.append(("exception naming unknown sense", f))
    f = toy_files(); f["lineages/L1.json"]["senses"][0]["available_in"][0]["from"] = 0
    cases.append(("year 0", f))
    for label, files in cases:
        failures += _rejects(label, files)

    print("\nDETERMINISM AND STALENESS")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_tree(root, toy_files())
        first, second = horizon.build(root, "toy"), horizon.build(root, "toy")
        ok = first == second
        failures += not ok
        print(f"  compile twice: identical bytes {ok}   {'PASS' if ok else 'FAIL'}")
        horizon.compiled_path(root, "toy").parent.mkdir(parents=True, exist_ok=True)
        horizon.compiled_path(root, "toy").write_text(first, encoding="utf-8")
        ok = horizon.check(root, "toy") == []
        failures += not ok
        print(f"  check right after compile: current   {'PASS' if ok else 'FAIL'}")
        edited = toy_files()["lineages/L3.json"]
        edited["senses"][0]["terms"] = ["pump", "eta"]
        write_tree(root, {"lineages/L3.json": edited})
        diff = horizon.check(root, "toy")
        ok = bool(diff) and diff[0] == "sources_sha256"
        failures += not ok
        print(f"  after editing one term (zeta→eta): stale, differs in {diff}   "
              f"{'PASS' if ok else 'FAIL'}")

    print("\nSELFTEST", "PASSED" if not failures else f"FAILED ({failures})")
    return 0 if not failures else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("figure_id", nargs="?")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--root", type=Path, default=horizon.HORIZONS_DIR)
    args = parser.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if not args.figure_id:
        parser.error("give a figure_id or --selftest")
    try:
        if args.check:
            diff = horizon.check(args.root, args.figure_id)
            if diff:
                print(f"STALE: {args.figure_id} compiled Horizon differs in: {', '.join(diff)}")
                sys.exit(1)
            print(f"current: {args.figure_id}")
            return
        text = horizon.build(args.root, args.figure_id)
    except HorizonError as error:
        print(f"INVALID: {error}")
        sys.exit(1)
    path = horizon.compiled_path(args.root, args.figure_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    compiled = json.loads(text)
    print(f"wrote compiled/{args.figure_id}.json · {len(compiled['lineages'])} lineages · "
          f"{len(compiled['breach_terms'])} breach terms · sources_sha256 "
          f"{compiled['sources_sha256'][:12]}…")


if __name__ == "__main__":
    main()
