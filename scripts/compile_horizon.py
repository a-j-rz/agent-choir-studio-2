"""Compile a figure's Epistemic Horizon from horizons/ sources. Offline; no model calls.

    python -m scripts.compile_horizon <figure_id>            # write horizons/compiled/<id>.json
    python -m scripts.compile_horizon <figure_id> --check    # exit 1 if the committed file is stale
    python -m scripts.compile_horizon --selftest             # toy data, built in
    python -m scripts.compile_horizon <figure_id> --window   # the figure's epistemic window

--root DIR points at another horizons directory (default: the repo's horizons/).
"""

import argparse
import json
from pathlib import Path
import shutil
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
            _sense("L1.s3", "A", 300, ["gamma", "sharedtwo"], ["m3"]),
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
EXPECTED_VARIANT_TERMS = ["beta", "delta", "epsilon", "gamma", "sharedtwo", "zeta"]
# Main case + L4 (v1 in B from 900: a tradition the profile lacks, after the horizon).
EXPECTED_L4 = ("L4", (None, [("v1", 1)], [], []))
EXPECTED_L4_TERM = "theta"
# Extended toy (3a-ii A): main toy + "habit" in L1.s1, "habits" and "smart phones" in L1.s4.
EXPECTED_EXT_NOT_BREACH = "habits"        # stems to habit, which s1 makes available
EXPECTED_EXT_BREACH = "smart phones"
EXPECTED_EXT_HITS = [(["smart", "phone"], "smart phone", 3)]   # "I check my smart phone daily"


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


# ---- the window report: the figure's epistemic boundary on one screen -------------------------

def fmt_year(year: int) -> str:
    """BCE years as 'N BCE', CE years as plain numbers (there is no year 0)."""
    return f"{-year} BCE" if year < 0 else str(year)


def years_after(horizon_year: int, year: int) -> int:
    """Years from the horizon to a later year. There is no year 0, so a span that crosses from
    BCE into CE is one shorter than the plain difference."""
    span = year - horizon_year
    if horizon_year < 0 < year:
        span -= 1
    return span


def window_data(root: Path, figure_id: str) -> dict:
    """Per lineage, from the sources: available senses (with the edge), beyond, unreached.
    Availability is horizon.availability, the compiler's own rule. Shows; never judges."""
    _, lineages, profile, _ = horizon.load(root, figure_id)
    mine = {t.tradition for t in profile.traditions}
    exceptions = {e.sense_id: e.include for e in profile.exceptions}
    year = profile.horizon_year
    records = []
    for lineage in sorted(lineages, key=lambda lin: lin.lineage_id):
        available, beyond, unreached = [], [], []
        for sense in lineage.senses:
            ok, via = horizon.availability(sense, mine, year, exceptions)
            if ok and via == "exception":
                available.append({"sense_id": sense.sense_id, "label": sense.label,
                                  "via": "exception", "from": "exception", "also": []})
            elif ok:
                routes = {}  # each of the figure's traditions that qualifies -> its earliest year
                for a in sense.available_in:
                    if a.tradition in mine and a.from_ <= year:
                        routes[a.tradition] = min(a.from_, routes.get(a.tradition, a.from_))
                ordered = sorted(routes.items(), key=lambda kv: (kv[1], kv[0]))
                available.append({"sense_id": sense.sense_id, "label": sense.label,
                                  "via": ordered[0][0], "from": ordered[0][1],
                                  "also": ordered[1:]})
            elif horizon.not_yet_anywhere(sense, year):
                first = min(a.from_ for a in sense.available_in)
                beyond.append({"sense_id": sense.sense_id, "label": sense.label,
                               "bridge_distance": len(beyond) + 1, "from": first,
                               "years_after": years_after(year, first)})
            else:
                where = {}
                for a in sense.available_in:
                    where[a.tradition] = min(a.from_, where.get(a.tradition, a.from_))
                unreached.append({"sense_id": sense.sense_id, "label": sense.label,
                                  "available_in": dict(sorted(where.items()))})
        records.append({"lineage_id": lineage.lineage_id, "label": lineage.label,
                        "available": available,
                        "edge": available[-1]["sense_id"] if available else None,
                        "beyond": beyond, "unreached": unreached})
    return {"figure_id": profile.figure_id, "horizon_year": year,
            "lived": (profile.lived.born, profile.lived.died),
            "traditions": [(t.tradition, t.confidence) for t in profile.traditions],
            "exceptions": [(e.sense_id, e.include, e.confidence) for e in profile.exceptions],
            "lineages": records}


def render_window(data: dict) -> str:
    born, died = data["lived"]
    out = [f"Epistemic window: {data['figure_id']}",
           f"horizon year {fmt_year(data['horizon_year'])} · lived {fmt_year(born)}–{fmt_year(died)}",
           "traditions: " + ", ".join(f"{t} ({c})" for t, c in data["traditions"]),
           "exceptions: " + (", ".join(f"{s} ({'include' if inc else 'exclude'}, {c})"
                                       for s, inc, c in data["exceptions"]) or "none")]
    for rec in data["lineages"]:
        out += ["", f"{rec['lineage_id']} — {rec['label']}"]
        for a in rec["available"]:
            when = a["from"] if a["from"] == "exception" else f"from {fmt_year(a['from'])}"
            also = ("; also " + ", ".join(f"{t} from {fmt_year(y)}" for t, y in a["also"])
                    if a["also"] else "")
            edge = "  ← edge" if a["sense_id"] == rec["edge"] else ""
            out.append(f"  available  {a['sense_id']} — {a['label']} · via {a['via']}, {when}"
                       f"{also}{edge}")
        for b in rec["beyond"]:
            out.append(f"  beyond     {b['sense_id']} — {b['label']} · distance "
                       f"{b['bridge_distance']}, from {fmt_year(b['from'])}, "
                       f"{b['years_after']} years after the horizon")
        for u in rec["unreached"]:
            where = ", ".join(f"{t} from {fmt_year(y)}" for t, y in u["available_in"].items())
            out.append(f"  unreached  {u['sense_id']} — {u['label']} · {where}")
    return "\n".join(out) + "\n"


def _find(rec, kind, sense_id):
    return next((x for x in rec[kind] if x["sense_id"] == sense_id), None)


def window_selftest():
    failures = 0

    def check(label, ok, detail=""):
        nonlocal failures
        failures += not ok
        print(f"  {label}{'  — ' + detail if detail else ''}   {'PASS' if ok else 'FAIL'}")

    print("\nWINDOW: BCE years")
    got = [fmt_year(y) for y in (-347, -1, 1)]
    check("fmt_year(-347, -1, 1) → 347 BCE, 1 BCE, 1", got == ["347 BCE", "1 BCE", "1"], f"{got}")
    print("\nWINDOW: years after the horizon (no year 0)")
    for horizon_year, year, want in ((-347, 64, 410), (-347, -300, 47), (1882, 1926, 44)):
        got = years_after(horizon_year, year)
        check(f"horizon {horizon_year}, from {year} → {want}", got == want, f"{got}")

    print("\nWINDOW: toy (exception include on L2.t1)")
    with tempfile.TemporaryDirectory() as tmp:
        write_tree(Path(tmp), toy_files())
        l2 = next(r for r in window_data(Path(tmp), "toy")["lineages"] if r["lineage_id"] == "L2")
        t1 = _find(l2, "available", "L2.t1")
        check("L2.t1 is available via exception",
              t1 is not None and t1["via"] == "exception" and t1["from"] == "exception",
              f"{t1}")

    print("\nWINDOW: toy variant, a sense in two of the profile's traditions (B 100, A 200)")
    files = toy_files()
    files["profiles/toy.json"]["traditions"].append(
        {"tradition": "B", "basis": "toy", "confidence": "high"})
    two = _sense("L5.w1", "B", 100, ["omega"])
    two["available_in"].append({"tradition": "A", "from": 200, "precision": "exact"})
    files["lineages/L5.json"] = _lineage("L5", [two])
    with tempfile.TemporaryDirectory() as tmp:
        write_tree(Path(tmp), files)
        text = render_window(window_data(Path(tmp), "toy"))
    line = next((ln for ln in text.splitlines() if "L5.w1" in ln), "")
    check("L5.w1: route B from 100, then '; also A from 200'",
          "via B, from 100; also A from 200" in line, f"{line.strip()!r}")

    real = horizon.HORIZONS_DIR
    print("\nWINDOW: charles_darwin (C1's verified facts)")
    darwin = {r["lineage_id"]: r for r in window_data(real, "charles_darwin")["lineages"]}
    drinks, energy = darwin["stimulant_drinks"], darwin["energy"]
    check("stimulant_drinks.tea is available",
          _find(drinks, "available", "stimulant_drinks.tea") is not None)
    first = drinks["beyond"][0] if drinks["beyond"] else {}
    check("stimulant drinks: edge caffeine; first beyond energy_drink, 1962, 80 years after",
          drinks["edge"] == "stimulant_drinks.caffeine"
          and first.get("sense_id") == "stimulant_drinks.energy_drink"
          and first.get("from") == 1962 and first.get("years_after") == 80,
          f"edge {drinks['edge']}, first beyond {first}")
    first = energy["beyond"][0] if energy["beyond"] else {}
    check("energy: edge utility; first beyond grid, 1926, 44 years after",
          energy["edge"] == "energy.utility" and first.get("sense_id") == "energy.grid"
          and first.get("from") == 1926 and first.get("years_after") == 44,
          f"edge {energy['edge']}, first beyond {first}")
    both = [("interest_on_loans", "interest_on_loans.prohibition"),
            ("price_and_value", "price_and_value.just_price")]
    routes = {sid: (_find(darwin[lin], "available", sid) or {}).get("via") for lin, sid in both}
    check("prohibition and just_price are available via latin-medieval",
          routes == {sid: "latin-medieval" for _, sid in both}, f"{routes}")

    print("\nWINDOW: marcus_aurelius")
    drinks = next(r for r in window_data(real, "marcus_aurelius")["lineages"]
                  if r["lineage_id"] == "stimulant_drinks")
    tea = _find(drinks, "unreached", "stimulant_drinks.tea")
    check("stimulant_drinks.tea is unreached, with the traditions that have it",
          tea is not None and bool(tea["available_in"]), f"{tea}")

    print("\nWINDOW: temporary tree, latin-medieval dropped from Darwin's profile")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "horizons"
        shutil.copytree(real, copy)
        path = copy / "profiles" / "charles_darwin.json"
        profile = json.loads(path.read_text(encoding="utf-8"))
        profile["traditions"] = [t for t in profile["traditions"]
                                 if t["tradition"] != "latin-medieval"]
        path.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        moved = {r["lineage_id"]: r for r in window_data(copy, "charles_darwin")["lineages"]}
        check("prohibition and just_price move to unreached",
              all(_find(moved[lin], "unreached", sid) is not None for lin, sid in both))
    stale = {f: horizon.check(real, f) for f in ("charles_darwin", "marcus_aurelius")}
    check("the real tree's compiled files are still current", stale == {
        "charles_darwin": [], "marcus_aurelius": []}, f"{stale}")
    return failures


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

    extended = toy_files()
    l1 = extended["lineages/L1.json"]["senses"]
    l1[0]["terms"].append("habit")
    l1[3]["terms"] += ["habits", "smart phones"]
    with tempfile.TemporaryDirectory() as tmp:
        write_tree(Path(tmp), extended)
        compiled = json.loads(horizon.build(Path(tmp), "toy"))
        print("\nEXTENDED TOY (stems): + habit in s1; + habits, smart phones in s4")
        ok = EXPECTED_EXT_NOT_BREACH not in compiled["breach_terms"]
        failures += not ok
        print(f"  {EXPECTED_EXT_NOT_BREACH!r} not a breach term   {'PASS' if ok else 'FAIL'}")
        ok = EXPECTED_EXT_BREACH in compiled["breach_terms"]
        failures += not ok
        print(f"  {EXPECTED_EXT_BREACH!r} is a breach term   {'PASS' if ok else 'FAIL'}")
        print(f"  breach_terms {compiled['breach_terms']}")
        hits = horizon.find_breaches("I check my smart phone daily", compiled)
        got = [(h["stems"], h["matched_surface"], h["start_token"]) for h in hits]
        ok = got == EXPECTED_EXT_HITS
        failures += not ok
        print(f"  find_breaches('I check my smart phone daily')")
        print(f"     expected {EXPECTED_EXT_HITS}")
        print(f"     actual   {got}   {'PASS' if ok else 'FAIL'}")

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
    f = toy_files(); f["lineages/L1.json"]["senses"][0]["terms"].append("—")
    cases.append(("term with no stems ('—')", f))
    f = toy_files(); f["lineages/L1.json"]["senses"][0]["terms"].append("DSM-5")
    cases.append(("term with a digit ('DSM-5')", f))
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

    failures += window_selftest()

    print("\nSELFTEST", "PASSED" if not failures else f"FAILED ({failures})")
    return 0 if not failures else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("figure_id", nargs="?")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--window", action="store_true")
    parser.add_argument("--root", type=Path, default=horizon.HORIZONS_DIR)
    args = parser.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if not args.figure_id:
        parser.error("give a figure_id or --selftest")
    try:
        if args.window:
            print(render_window(window_data(args.root, args.figure_id)), end="")
            return
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
