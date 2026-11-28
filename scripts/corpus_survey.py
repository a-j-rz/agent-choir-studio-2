"""Corpus survey: what is in a figure's raw texts. It reports; it never decides. Offline, stdlib only.

    python -m scripts.corpus_survey <figure_id>   # summary; writes corpora/<id>/data/survey.json
    python -m scripts.corpus_survey --selftest    # the answer key: Darwin's and Marcus's strip reports

Every `*.txt` in corpora/<figure_id>/data/raw/ is read in sorted order, decoded as UTF-8 with CRLF
turned into LF. Line numbers are 1-based in that LF text. Detection runs inside the Gutenberg
envelope: the lines strictly between `*** START OF` and `*** END OF`. Each section is a list of
candidates, not a verdict, and the detectors are generic: no figure has a branch, a region or a
threshold here. survey.json quotes source text, so it lives in the gitignored data/ directory.

Known limitation: the table rule (three or more consecutive lines, each with an internal run of 3+
spaces) misses tables whose rows wrap onto unspaced text lines (e.g. Descent table 2).
"""

import argparse
import bisect
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parent.parent
CORPORA = ROOT / "corpora"
PREVIEW = 60
WORD_THRESHOLDS = (250, 340, 380, 500)
HAZARD_ABBREVIATIONS = ("Mr", "Mrs", "Dr", "Prof", "Rev", "St", "Capt", "Hon", "etc", "vol", "p",
                        "pp", "viz", "cf", "i.e", "e.g")  # as in corpora/charles_darwin/chunking.json
APPARATUS = ("[Fig.", "[Illustration", "[Footnote", "[Sidenote", "[Transcriber")
BRACKETS = {"(": ")", "[": "]"}
OPENER = re.compile(r"\((\*?)(\d{1,3})\.\s")  # the whitespace may be a newline
LABEL = re.compile(r"\[(\d{1,3}|[A-Z])\]")
LABEL_BODY = re.compile(r"[ \t]*\[(\d{1,3}|[A-Z])\]")
HEADING_LINE = re.compile(r"(?:CHAPTER|BOOK|PART)\s+(?:[IVXLCDM]+|\d+)\b")
TABLE_GAP = re.compile(r"\S {3,}\S")
INITIALS = re.compile(r"(?<![A-Za-z.])(?:[A-Z]\.)+(?=\s+[A-Z])")
BLANK_LINE = re.compile(r"\n[ \t]*\n")
INSTANCES = 20


class Text:
    """LF text with 1-based line lookup by character offset."""

    def __init__(self, text):
        self.text = text
        self.starts = [0] + [m.end() for m in re.finditer("\n", text)]

    def line(self, offset):
        return bisect.bisect_right(self.starts, offset)

    def item(self, start, end=None):
        """A reported item: its line (or line range) and its first 60 characters."""
        first, last = self.line(start), self.line(end - 1 if end else start)
        where = {"line": first} if first == last else {"lines": [first, last]}
        return {**where, "first_60": self.text[start:start + PREVIEW]}


def envelope(t):
    """(start, end) offsets of the text between the first START line and the next END line."""
    starts = [m for m in re.finditer(r"(?m)^\*\*\* START OF.*$", t.text)]
    ends = [m for m in re.finditer(r"(?m)^\*\*\* END OF.*$", t.text)]
    begin = starts[0].end() + 1 if starts else 0
    after = [m for m in ends if m.start() >= begin]
    finish = after[0].start() if after else len(t.text)
    report = {"start_count": len(starts), "start_lines": [t.line(m.start()) for m in starts],
              "end_count": len(ends), "end_lines": [t.line(m.start()) for m in ends]}
    return begin, finish, report


def paragraphs(t, begin, end):
    """Runs of non-blank lines inside the envelope: (start, end) offsets."""
    found = []
    for m in re.finditer(r"(?:[^\n]*\S[^\n]*(?:\n|$))+", t.text[begin:end]):
        text = m.group().rstrip("\n")
        found.append((begin + m.start(), begin + m.start() + len(text)))
    return found


def match_brackets(text, start, end, opener):
    """Stack-match one bracket type over text[start:end]: matched spans with their enclosing
    opener (or None), unmatched openers, unmatched closers."""
    closer, stack, spans, stray = BRACKETS[opener], [], [], []
    for i in range(start, end):
        ch = text[i]
        if ch == opener:
            stack.append(i)
        elif ch == closer:
            if not stack:
                stray.append(i)
                continue
            o = stack.pop()
            parent = stack[-1] if stack else None
            spans.append((o, i + 1, parent))
    return spans, stack, stray


def is_heading_caps(text):
    return any(c.isupper() for c in text) and not any(c.islower() for c in text)


def survey_text(text):
    """Sections 1 (envelope) to 9 for one LF-normalised text."""
    t = Text(text)
    begin, end, env = envelope(t)
    paras = paragraphs(t, begin, end)
    body = text

    # 2. Paragraphs
    words = [len(text[a:b].split()) for a, b in paras]
    para_report = {"count": len(paras),
                   "words_min": min(words) if words else 0,
                   "words_median": statistics.median(words) if words else 0,
                   "words_max": max(words) if words else 0,
                   "over": {str(n): sum(w > n for w in words) for n in WORD_THRESHOLDS}}

    # 3. Heading candidates
    caps_single, caps_multi, italic, numbered = [], [], [], []
    for a, b in paras:
        p = text[a:b]
        if is_heading_caps(p):
            (caps_multi if "\n" in p else caps_single).append(t.item(a, b))
        stripped = p.strip()
        if len(stripped) > 2 and stripped.startswith("_") and stripped.endswith("_"):
            italic.append(t.item(a, b))
    for m in re.finditer(r"(?m)^.*$", text[begin:end]):
        if HEADING_LINE.match(m.group()):
            numbered.append(t.item(begin + m.start()))
    headings = {"all_caps_single_line": caps_single, "all_caps_multi_line": caps_multi,
                "italic": italic, "numbered_lines": numbered}
    heading_lines = sorted({(h.get("line") or h["lines"][0]): h for kind in headings.values()
                            for h in kind}.items())

    # 4. Brackets
    brackets, matched = {}, {}
    for opener in BRACKETS:
        unmatched_open, unmatched_close = [], []
        for a, b in paras:
            _, opens, closes = match_brackets(text, a, b, opener)
            unmatched_open += [t.item(o) for o in opens]
            unmatched_close += [t.item(c) for c in closes]
        spans, opens, closes = match_brackets(text, begin, end, opener)
        matched[opener] = spans
        brackets[opener] = {
            "paragraph_unmatched_openers": unmatched_open,
            "paragraph_unmatched_closers": unmatched_close,
            "envelope_unmatched_openers": len(opens), "envelope_unmatched_closers": len(closes),
            "spans_with_blank_line": [t.item(o, c) for o, c, _ in spans
                                      if BLANK_LINE.search(text, o, c)],
            "nested_spans": [t.item(o, c) for o, c, parent in spans if parent is not None]}

    # 5. Parenthesised numbered notes
    openers = [m for m in OPENER.finditer(text, begin, end)]
    runs, unclosed = [], []
    for k, m in enumerate(openers):
        n, o = int(m.group(2)), m.start()
        limit = openers[k + 1].start() if k + 1 < len(openers) else end
        depth, close = 0, None
        for i in range(o, limit):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    close = i + 1
                    break
        if n == 1 or not runs:
            runs.append({"numbers": [], "note_lines": [], "gaps": [], "duplicates": [],
                         "backwards": [], "start": o, "end": o})
        run = runs[-1]
        item = {"number": n, **t.item(o)}
        if run["numbers"]:
            prev = run["numbers"][-1]
            if n == prev:
                run["duplicates"].append(item)
            elif n > prev + 1:
                run["gaps"] += [{**item, "missing": x} for x in range(prev + 1, n)]
            elif n < prev:
                run["backwards"].append(item)
        run["numbers"].append(n)
        run["note_lines"].append(t.line(o))
        run["end"] = close or limit
        if close is None:
            unclosed.append({"run": len(runs), **item})
    run_report = []
    for index, run in enumerate(runs, 1):
        line = t.line(run["start"])
        before = [h for start, h in heading_lines if start < line]
        run_report.append({"run": index, "lines": [line, t.line(run["end"] - 1)],
                           "numbers": run["numbers"], "note_lines": run["note_lines"],
                           "count": len(run["numbers"]),
                           "gaps": run["gaps"], "duplicates": run["duplicates"],
                           "backwards": run["backwards"],
                           "nearest_heading": before[-1] if before else None})
    notes = {"opener_count": len(openers), "star_form_count": sum(bool(m.group(1)) for m in openers),
             "runs": run_report, "unclosed": unclosed}

    # 6. Bracket-label notes
    bodies, body_starts = {}, set()
    for a, b in paras:
        m = LABEL_BODY.match(text, a, b)
        if m:
            bodies.setdefault(m.group(1), []).append(t.item(a, b))
            body_starts.add(m.start(1) - 1)
    markers = {}
    for m in LABEL.finditer(text, begin, end):
        if m.start() not in body_starts:
            markers.setdefault(m.group(1), []).append(t.item(m.start()))
    labels = sorted(set(bodies) | set(markers), key=lambda x: (not x.isdigit(), x.zfill(3)))
    label_notes = {"marker_count": sum(map(len, markers.values())),
                   "body_count": sum(map(len, bodies.values())),
                   "per_label": {x: {"markers": len(markers.get(x, [])), "bodies": len(bodies.get(x, []))}
                                 for x in labels},
                   "differing_labels": [x for x in labels
                                        if len(markers.get(x, [])) != len(bodies.get(x, []))],
                   "markers": markers, "bodies": bodies}

    # 7. Apparatus markers
    square = {o: (c, parent) for o, c, parent in matched["["]}
    parents = {parent for _, _, parent in matched["["] if parent is not None}
    apparatus = {}
    for marker in APPARATUS:
        spans, unmatched, nested = [], [], []
        for m in re.finditer(re.escape(marker), text[begin:end]):
            o = begin + m.start()
            if o not in square:
                unmatched.append(t.item(o))
                continue
            spans.append(t.item(o, square[o][0]))
            if o in parents:
                nested.append(t.item(o, square[o][0]))
        apparatus[marker] = {"count": len(spans) + len(unmatched), "spans": spans,
                             "unmatched": unmatched, "nested": nested}

    # 8. Table candidates
    tables, run_lines = [], []
    line_iter = [(begin + m.start(), m.group()) for m in re.finditer(r"(?m)^.*$", text[begin:end])]
    for offset, line in line_iter + [(end, "")]:
        if line.strip() and TABLE_GAP.search(line):
            run_lines.append(offset)
            continue
        if len(run_lines) >= 3:
            last = run_lines[-1]
            tables.append({"lines": [t.line(run_lines[0]), t.line(last)],
                           "first_60": text[run_lines[0]:run_lines[0] + PREVIEW]})
        run_lines = []

    # 9. Sentence hazards
    abbreviations = {}
    for abbr in HAZARD_ABBREVIATIONS:
        pattern = re.compile(r"(?<![A-Za-z.])" + re.escape(abbr) + r"\.\s+[A-Z]")
        found = [t.item(m.start()) for m in pattern.finditer(text, begin, end)]
        abbreviations[abbr] = {"count": len(found), "instances": found[:INSTANCES]}
    initials = [(m.start(), m.end()) for m in INITIALS.finditer(text, begin, end)]
    hazards = {"abbreviations": abbreviations,
               "initials": {"count": len(initials),
                            "instances": [t.item(a) for a, _ in initials[:INSTANCES]]}}

    return {"envelope": env, "paragraphs": para_report, "headings": headings,
            "brackets": brackets, "numbered_notes": notes, "label_notes": label_notes,
            "apparatus": apparatus, "tables": tables, "hazards": hazards,
            "_initials_followers": [body[b:b + 40].split()[0] if body[b:b + 40].split() else ""
                                    for _, b in initials]}


def manifest_strings(figure_id):
    path = CORPORA / figure_id / "manifest.json"
    if not path.is_file():
        return None
    found = set()

    def walk(value):
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, str):
            found.add(value)
    walk(json.loads(path.read_text(encoding="utf-8")))
    return found


def read_raw(path):
    raw = path.read_bytes()
    crlf, lf = raw.count(b"\r\n"), raw.count(b"\n")
    endings = "LF" if crlf == 0 else "CRLF" if crlf == lf else "mixed"
    return raw, raw.decode("utf-8").replace("\r\n", "\n"), endings


def survey_file(path, manifest):
    raw, text, endings = read_raw(path)
    sha = hashlib.sha256(raw).hexdigest()
    result = survey_text(text)
    result.pop("_initials_followers")
    result["file"] = {"name": path.name, "sha256": sha, "bytes": len(raw), "line_endings": endings,
                      "in_manifest": None if manifest is None else sha in manifest}
    return result


def survey(figure_id):
    raw_dir = CORPORA / figure_id / "data" / "raw"
    if not raw_dir.is_dir():
        raise SystemExit(f"no raw directory: corpora/{figure_id}/data/raw/")
    manifest = manifest_strings(figure_id)
    files = sorted(p for p in raw_dir.iterdir() if p.is_file())
    return {"figure_id": figure_id,
            "files": {p.name: survey_file(p, manifest) for p in files if p.suffix == ".txt"},
            "other_files": [p.name for p in files if p.suffix != ".txt"]}


def summary(report):
    out = [f"corpus survey: {report['figure_id']}"]
    for name, f in report["files"].items():
        e, p, h, n = f["envelope"], f["paragraphs"], f["headings"], f["numbered_notes"]
        ln, b = f["label_notes"], f["brackets"]
        out += [f"\n{name}  sha256 {f['file']['sha256'][:12]}…  {f['file']['bytes']:,} bytes  "
                f"{f['file']['line_endings']}  in manifest: {f['file']['in_manifest']}",
                f"  1 envelope    START ×{e['start_count']} {e['start_lines']} · "
                f"END ×{e['end_count']} {e['end_lines']}",
                f"  2 paragraphs  {p['count']} · words min/median/max {p['words_min']}/"
                f"{p['words_median']}/{p['words_max']} · over "
                + ", ".join(f">{k}: {v}" for k, v in p["over"].items()),
                f"  3 headings    all-caps {len(h['all_caps_single_line'])} single-line + "
                f"{len(h['all_caps_multi_line'])} multi-line · italic {len(h['italic'])} · "
                f"CHAPTER/BOOK/PART lines {len(h['numbered_lines'])}"]
        for opener in BRACKETS:
            x = b[opener]
            out.append(f"  4 brackets {opener}  per paragraph: unmatched openers "
                       f"{len(x['paragraph_unmatched_openers'])}, closers "
                       f"{len(x['paragraph_unmatched_closers'])} · envelope: spans with a blank "
                       f"line {len(x['spans_with_blank_line'])}, nested {len(x['nested_spans'])}")
        anomalies = sum(len(r["gaps"]) + len(r["duplicates"]) + len(r["backwards"]) for r in n["runs"])
        out += [f"  5 (n. notes   {n['opener_count']} openers in {len(n['runs'])} runs · "
                f"anomalies {anomalies} · unclosed {len(n['unclosed'])} · star form "
                f"{n['star_form_count']}",
                f"  6 [n] notes   markers {ln['marker_count']} · bodies {ln['body_count']} · "
                f"labels {len(ln['per_label'])} · differing {ln['differing_labels'][:12]}",
                "  7 apparatus   " + " · ".join(
                    f"{k} {v['count']} (nested {len(v['nested'])})"
                    for k, v in f["apparatus"].items()),
                f"  8 tables      {len(f['tables'])} candidates",
                f"  9 hazards     abbreviations {sum(v['count'] for v in f['hazards']['abbreviations'].values())}"
                f" · initials {f['hazards']['initials']['count']}"]
    if report["other_files"]:
        out.append(f"\nnot surveyed (not .txt): {', '.join(report['other_files'])}")
    return "\n".join(out)


def write(report):
    path = CORPORA / report["figure_id"] / "data" / "survey.json"
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return path, hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- the answer key ---------------------------------------------------------------------------

DESCENT_RUN_COUNTS = [2, 56, 96, 79, 50, 37, 32, 80, 99, 26, 80, 34, 72, 94, 55, 33, 57, 49, 47,
                      76, 28, 2]
DESCENT_ANOMALIES = {(5, "gap", 37), (5, "duplicate", 38), (20, "gap", 48), (20, "duplicate", 49)}
DESCENT_UNCLOSED = {(3, 71), (18, 8), (20, 8), (20, 26), (21, 1)}
# Amendment 1: run 8 (Ch. VII) runs on through Huxley's note on the brain, 70–80; the report's
# 1–69 stops where the recipe stripped that note whole.
RUN_8_KEY = list(range(1, 81))
MARCUS_WINDOW = (2129, 7178)  # Book I to INDEX OF TERMS.; applied in --selftest only


class KeyMissing(Exception):
    pass


def start_line(item):
    return item.get("line") or item["lines"][0]


def item_range(item):
    return (item["line"], item["line"]) if "line" in item else tuple(item["lines"])


def anomalies(notes):
    found = set()
    for r in notes["runs"]:
        found |= {(r["run"], "gap", g["missing"]) for g in r["gaps"]}
        found |= {(r["run"], "duplicate", d["number"]) for d in r["duplicates"]}
        found |= {(r["run"], "backwards", d["number"]) for d in r["backwards"]}
    return found


def load_key():
    raw = {"descent": CORPORA / "charles_darwin/data/raw/pg2300.txt",
           "origin": CORPORA / "charles_darwin/data/raw/pg2009.txt",
           "marcus": CORPORA / "marcus_aurelius/data/raw/pg15877.txt"}
    reports = {"charles_darwin": CORPORA / "charles_darwin/data/clean/strip_report.json",
               "marcus_aurelius": CORPORA / "marcus_aurelius/data/clean/strip_report.json"}
    missing = [p.relative_to(ROOT).as_posix() for p in [*raw.values(), *reports.values()]
               if not p.is_file()]
    if missing:
        raise KeyMissing("missing: " + ", ".join(missing) + " (build the corpora with their "
                         "acquire.py first)")
    texts = {}
    for key, path in raw.items():
        data, text, _ = read_raw(path)
        figure = path.parent.parent.parent.name
        if hashlib.sha256(data).hexdigest() not in manifest_strings(figure):
            raise KeyMissing(f"{path.relative_to(ROOT).as_posix()}: SHA-256 is not in "
                             f"corpora/{figure}/manifest.json")
        texts[key] = text
    return texts, {k: json.loads(p.read_text(encoding="utf-8")) for k, p in reports.items()}


def selftest():
    try:
        texts, key = load_key()
    except KeyMissing as error:
        print(f"SELFTEST CANNOT RUN: {error}")
        return 1
    darwin, marcus_key = key["charles_darwin"], key["marcus_aurelius"]
    failures = []

    def check(label, ok, detail=""):
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))
        if not ok:
            failures.append(label)

    def extras(label, items):
        print(f"  extras beyond the join, {label}: {len(items)}")
        for item in items[:10]:
            where = item.get("line") or item.get("lines")
            print(f"      {where}  {item['first_60']!r}")

    def spans(book, category):
        return [s for s in darwin[book]["stripped_spans"] if s["category"] == category]

    # ---- Descent
    print("\nDescent (pg2300.txt)")
    d = survey_text(texts["descent"])
    env = d["envelope"]
    check("envelope: START and END once each", env["start_count"] == 1 and env["end_count"] == 1,
          f"START {env['start_lines']}, END {env['end_lines']}")
    header = spans("descent", "gutenberg_header")[0]["lf_line_range"][1]
    footer = spans("descent", "gutenberg_footer")[0]["lf_line_range"][0]
    check("line convention: report header ends on START, footer starts on END",
          env["start_lines"] == [header] and env["end_lines"] == [footer])
    key_runs = [v["numbers"] for v in darwin["descent"]["footnotes"].values() if v["numbers"]]
    if key_runs[7] != list(range(1, 70)):
        print(f"STOP: the report's run 8 is not 1–69 as Amendment 1 says: {key_runs[7][-3:]}")
        return 1
    key_runs[7] = RUN_8_KEY
    if [len(r) for r in key_runs] != DESCENT_RUN_COUNTS:
        print(f"STOP: corrected report run counts {[len(r) for r in key_runs]} differ from the "
              f"brief's literals {DESCENT_RUN_COUNTS}")
        return 1
    runs = [r["numbers"] for r in d["numbered_notes"]["runs"]]
    check("note runs equal the corrected key (22 runs, 1,184 notes; run 8 is 1–80)",
          runs == key_runs, f"survey {len(runs)} runs, counts {[len(r) for r in runs]}")
    huxley = spans("descent", "huxley_note")[0]["lf_line_range"]
    run8 = d["numbered_notes"]["runs"][7]
    tail = [(n, ln) for n, ln in zip(run8["numbers"], run8["note_lines"]) if n >= 70]
    check(f"run 8 notes 70–80 each start inside the huxley_note span {huxley}",
          [n for n, _ in tail] == list(range(70, 81))
          and all(huxley[0] <= ln <= huxley[1] for _, ln in tail),
          f"lines {[ln for _, ln in tail]}")
    check("anomalies: duplicate + gap in runs 5 and 20 only",
          anomalies(d["numbered_notes"]) == DESCENT_ANOMALIES,
          f"found {sorted(anomalies(d['numbered_notes']))}")
    unclosed = {(u["run"], u["number"]) for u in d["numbered_notes"]["unclosed"]}
    check("unclosed notes: exactly the five", unclosed == DESCENT_UNCLOSED,
          f"found {sorted(unclosed)}")
    check("star form: 1", d["numbered_notes"]["star_form_count"] == 1,
          f"found {d['numbered_notes']['star_form_count']}")
    fig = d["apparatus"]["[Fig."]
    check("[Fig. captions: 57, 2 with a nested [", fig["count"] == 57 and len(fig["nested"]) == 2,
          f"found {fig['count']}, nested {len(fig['nested'])}")
    fig_lines = {start_line(s) for s in fig["spans"]}
    key_figs = {s["lf_line_range"][0] for s in spans("descent", "figure_caption")}
    check("every figure_caption span starts on a survey [Fig. line", key_figs <= fig_lines,
          f"missing {sorted(key_figs - fig_lines)[:10]}")
    extras("[Fig. spans not in the key", [s for s in fig["spans"] if start_line(s) not in key_figs])
    key_tables = [tuple(s["lf_line_range"]) for s in spans("descent", "table")]
    cands = [item_range(c) for c in d["tables"]]
    overlap = lambda a, b: a[0] <= b[1] and b[0] <= a[1]
    table1 = [c for c in cands if overlap(key_tables[0], c)]
    check(f"table 1 {key_tables[0]}: exactly one candidate, 8223–8226", table1 == [(8223, 8226)],
          f"found {table1}")
    table2 = [c for c in cands if overlap(key_tables[1], c)]
    print(f"  known miss (reported, not failed): table 2 {key_tables[1]} — candidates {table2}; "
          "the rule misses rows that wrap onto unspaced text lines")
    extras("table candidates overlapping no key table",
           [c for c in d["tables"] if not any(overlap(item_range(c), k) for k in key_tables)])
    caps = d["headings"]["all_caps_single_line"] + d["headings"]["all_caps_multi_line"]
    pool = caps + d["headings"]["italic"] + d["headings"]["numbered_lines"]
    pool_lines = {start_line(c) for c in pool}
    key_heads = {s["lf_line_range"][0] for s in spans("descent", "heading")}
    check(f"every heading span ({len(key_heads)}) starts on a heading candidate (3a, 3b or 3c)",
          key_heads <= pool_lines, f"missing {sorted(key_heads - pool_lines)[:10]}")
    extras("heading candidates (3a, 3b, 3c) on lines not in the key",
           sorted({start_line(c): c for c in pool if start_line(c) not in key_heads}.values(),
                  key=start_line))
    classes = [n for n in ("II", "III", "IV", "V", "VI")
               if any(c["first_60"].startswith(f"CLASS {n}. —") for c in caps)]
    check("CLASS II–VI paragraphs are among the all-caps candidates", len(classes) == 5,
          f"found {classes}")
    check("an initials hazard is followed by 'Ray'",
          any(f.startswith("Ray") for f in d["_initials_followers"]))

    # ---- Origin
    print("\nOrigin (pg2009.txt)")
    o = survey_text(texts["origin"])
    env = o["envelope"]
    check("envelope: START and END once each", env["start_count"] == 1 and env["end_count"] == 1,
          f"START {env['start_lines']}, END {env['end_lines']}")
    per = o["label_notes"]["per_label"]
    check("[n] notes: labels 1, 2, 3, each one marker and one body",
          per == {x: {"markers": 1, "bodies": 1} for x in ("1", "2", "3")}, f"found {per}")
    marker_lines = {start_line(m) for ms in o["label_notes"]["markers"].values() for m in ms}
    body_lines = {start_line(b) for bs in o["label_notes"]["bodies"].values() for b in bs}
    key_markers = {s["lf_line_range"][0] for s in spans("origin", "footnote_marker")}
    key_bodies = {s["lf_line_range"][0] for s in spans("origin", "footnote")}
    check("footnote_marker spans start on survey marker lines", key_markers <= marker_lines,
          f"key {sorted(key_markers)}, survey {sorted(marker_lines)}")
    check("footnote spans start on survey body lines", key_bodies <= body_lines,
          f"key {sorted(key_bodies)}, survey {sorted(body_lines)}")
    italic = o["headings"]["italic"]
    caps = o["headings"]["all_caps_single_line"] + o["headings"]["all_caps_multi_line"]
    pool = italic + caps + o["headings"]["numbered_lines"]
    cand_lines = {start_line(c) for c in pool}
    key_heads = {s["lf_line_range"][0] for s in spans("origin", "heading")}
    check(f"every heading span ({len(key_heads)}) starts on a heading candidate (3a, 3b or 3c)",
          key_heads <= cand_lines, f"missing {sorted(key_heads - cand_lines)[:10]}")
    italic_hit = sum(start_line(c) in key_heads for c in italic)
    check("at least 75 italic candidates are matched by heading spans", italic_hit >= 75,
          f"matched {italic_hit} of {len(italic)}")
    extras("heading candidates (3a, 3b, 3c) on lines not in the key",
           sorted({start_line(c): c for c in pool if start_line(c) not in key_heads}.values(),
                  key=start_line))

    # ---- Marcus
    print("\nMarcus (pg15877.txt)")
    m = survey_text(texts["marcus"])
    ln = m["label_notes"]
    lo, hi = MARCUS_WINDOW

    def split(groups):
        inside, outside = {}, {}
        for label, items in groups.items():
            for item in items:
                (inside if lo <= start_line(item) <= hi else outside).setdefault(label, []).append(item)
        return inside, outside
    bodies_in, bodies_out = split(ln["bodies"])
    markers_in, markers_out = split(ln["markers"])
    count = lambda g: sum(map(len, g.values()))
    differ = lambda b, mk: sorted(x for x in set(b) | set(mk)
                                  if len(b.get(x, [])) != len(mk.get(x, [])))
    four = [count(bodies_in), count(markers_in), marcus_key["markers_removed"],
            marcus_key["note_bodies_removed"]]
    if len(set(four[2:])) != 1 or four[2] != 127:
        print(f"STOP: Marcus's strip_report numbers {four[2:]} are not both 127")
        return 1
    check(f"inside lines {lo}–{hi}: 127 bodies and 127 markers, equal to the strip report",
          four == [127] * 4, f"bodies {four[0]}, markers {four[1]}, report {four[2]} / {four[3]}")
    check(f"inside lines {lo}–{hi}: no label has differing marker and body counts",
          differ(bodies_in, markers_in) == [], f"differing {differ(bodies_in, markers_in)}")
    print(f"  outside the window (reported, not failed): {count(bodies_out)} bodies, "
          f"{count(markers_out)} markers, labels with differing counts "
          f"{differ(bodies_out, markers_out)}")
    extras("bodies outside the window", sorted((b for bs in bodies_out.values() for b in bs),
                                               key=start_line))
    extras("markers outside the window", sorted((x for xs in markers_out.values() for x in xs),
                                                key=start_line))

    # ---- Data mutations, in memory
    print("\nData mutations (in memory)")
    foot = spans("descent", "footnote")
    lines = texts["descent"].split("\n")
    starts = [0]
    for line in lines[:-1]:
        starts.append(starts[-1] + len(line) + 1)

    run2_1 = foot[DESCENT_RUN_COUNTS[0]]
    last_line = run2_1["lf_line_range"][1]
    cut = starts[last_line - 1] + lines[last_line - 1].rindex(")")
    mutated = texts["descent"][:cut] + texts["descent"][cut + 1:]
    got = {(u["run"], u["number"]) for u in survey_text(mutated)["numbered_notes"]["unclosed"]}
    check("1 · closing ) of run 2 #1 removed: 6 unclosed, the new one run 2 #1",
          run2_1["first_60"].startswith("(1.") and got == DESCENT_UNCLOSED | {(2, 1)},
          f"found {sorted(got)}")

    run4_10 = foot[sum(DESCENT_RUN_COUNTS[:3]) + 9]
    first = run4_10["lf_line_range"][0]
    at = starts[first - 1] + lines[first - 1].index("(10.")
    mutated = texts["descent"][:at] + "(10:" + texts["descent"][at + 4:]
    found = anomalies(survey_text(mutated)["numbered_notes"])
    check("2 · opener of run 4 #10 broken to (10: — a gap at 10 in run 4",
          run4_10["first_60"].startswith("(10.") and (4, "gap", 10) in found,
          f"new anomalies {sorted(found - DESCENT_ANOMALIES)}")

    body = re.search(r"\n\n((?: {4})?\[([A-Z])\] [^\n]*(?:\n[^\n]+)*)", texts["marcus"])
    label = body.group(2)
    mutated = texts["marcus"][:body.start(1)] + texts["marcus"][body.end(1) + 2:]
    differing = survey_text(mutated)["label_notes"]["differing_labels"]
    check(f"3 · one Marcus note body ([{label}]) deleted: a mismatch for [{label}]",
          label in differing, f"differing {differing}")

    print("\nSELFTEST", "PASSED" if not failures else f"FAILED ({len(failures)})")
    return 0 if not failures else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("figure_id", nargs="?")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if not args.figure_id:
        parser.error("give a figure_id or --selftest")
    report = survey(args.figure_id)
    print(summary(report))
    path, sha = write(report)
    print(f"\nwrote {path.relative_to(ROOT).as_posix()} · sha256 {sha}")


if __name__ == "__main__":
    main()
