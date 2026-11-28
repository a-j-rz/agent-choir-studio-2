"""Horizon coverage: which modern concepts would these questions draw on, and are they mapped?

    python -m scripts.horizon_coverage_probe marcus_aurelius
    python -m scripts.horizon_coverage_probe marcus_aurelius --from-trace traces/<run_id>
    python -m scripts.horizon_coverage_probe --selftest    # offline cases; no calls

Offline build tooling, not a figure run. The questions come from
horizons/probe_questions/<figure_id>.json; the horizon year from the figure's profile. For each
question, twice: a `builder` call answers it as a well-informed person today; a second `builder`
call lists the concepts in that answer that did not exist before the horizon year. Then, with
no model, each listed term is matched against the figure's compiled Horizon by stem sequence
(the BM25 tokeniser and stemmer), and find_breaches runs over each full answer. Changes no
Horizon file. At most 12 live calls. --from-trace re-classifies an earlier run's answers against
the current Horizon: no calls, and nothing is written.

The model only proposes candidates; whether a gap matters is a human call.
"""

import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from functools import partial
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from core.events import Event
from core.llm import call_model
from core.runner import relay
from epistemic import horizon

QUESTIONS_DIR = horizon.HORIZONS_DIR / "probe_questions"
SAMPLES = 2
COST_CAP_USD = 0.02

ANSWER_INSTRUCTIONS = "Answer as a thoughtful, well-informed person today, in about 250 words."
EXTRACT_INSTRUCTIONS = (  # a template: .format(year=<the figure's horizon year>)
    "List every concept or term in the text that did not exist anywhere before {year} CE. "
    'Include concepts that use old words in a new sense (e.g. "circulation" in Harvey\'s '
    "sense of the blood's circuit). Leave out ordinary words, and concepts that already "
    "existed in antiquity. For each: term — exactly as written in the text; concept — a "
    "short name; emerged — approximate year or century; why_post_{year} — one line."
)
FIELDS = ("term", "concept", "emerged")  # then why_post_<year>
_FROZEN = ConfigDict(frozen=True, extra="forbid")


def why_field(year):
    return f"why_post_{year}"


def extract_instructions(year):
    return EXTRACT_INSTRUCTIONS.format(year=year)


def extraction_model(year):
    """The extraction schema for one horizon year: term, concept, emerged, why_post_<year>."""
    item = create_model("Item", __config__=_FROZEN,
                        **{k: (str, ...) for k in (*FIELDS, why_field(year))})
    return create_model("Extraction", __config__=_FROZEN, items=(list[item], ...))


def text_format(year):
    fields = [*FIELDS, why_field(year)]
    return {
        "type": "json_schema", "name": f"post_{year}_concepts", "strict": True,
        "schema": {
            "type": "object",
            "properties": {"items": {"type": "array", "items": {
                "type": "object",
                "properties": {k: {"type": "string"} for k in fields},
                "required": fields,
                "additionalProperties": False}}},
            "required": ["items"],
            "additionalProperties": False,
        },
    }


class QuestionsFile(BaseModel):
    model_config = _FROZEN
    schema_version: Literal["1"]
    source: str = Field(min_length=1)
    questions: list[str] = Field(min_length=1)


class ProbeStopped(Exception):
    pass


def horizon_year(figure_id):
    """The figure's horizon year, from its profile."""
    path = horizon.HORIZONS_DIR / "profiles" / f"{figure_id}.json"
    return horizon.Profile.model_validate_json(path.read_bytes()).horizon_year


def load_questions(figure_id, root=QUESTIONS_DIR):
    """The figure's probe questions; refuses a figure that has no questions file."""
    path = Path(root) / f"{figure_id}.json"
    if not path.is_file():
        raise ProbeStopped(f"no probe questions for {figure_id}: {path.name} does not exist in "
                           f"{Path(root).name}/ (python -m scripts.generate_probe_questions "
                           f"{figure_id} creates it)")
    return QuestionsFile.model_validate_json(path.read_bytes()).questions


def load_compiled(figure_id):
    """The figure's compiled Horizon; refuses a stale one."""
    root = horizon.HORIZONS_DIR
    stale = horizon.check(root, figure_id)
    if stale:
        raise ProbeStopped(f"compiled Horizon for {figure_id} is stale: {stale}")
    return json.loads(horizon.compiled_path(root, figure_id).read_text(encoding="utf-8"))


def _inside(small, big):
    """Contiguous containment of one stem sequence in another, as whole stems."""
    n = len(small)
    return n < len(big) and any(big[i:i + n] == small for i in range(len(big) - n + 1))


def classify(term, compiled):
    """By stem sequence: mapped_beyond | mapped_his | near | unmapped (+ no_stems flag)."""
    stems = horizon.term_stems(term)
    if not stems:
        return {"status": "unmapped", "stems": [], "matched": [], "no_stems": True}
    beyond = {tuple(e["stems"]): e for e in compiled["breach_stems"]}
    his = {tuple(e["stems"]): e for e in compiled["available_stems"]}
    for name, index, status in (("beyond", beyond, "mapped_beyond"), ("his", his, "mapped_his")):
        if stems in index:
            return {"status": status, "stems": list(stems),
                    "matched": [[name, " / ".join(index[stems]["terms"])]]}
    near = sorted([name, " / ".join(entry["terms"])]
                  for name, index in (("beyond", beyond), ("his", his))
                  for key, entry in index.items() if _inside(key, stems) or _inside(stems, key))
    return {"status": "near" if near else "unmapped", "stems": list(stems), "matched": near}


def breach_hits(text, compiled):
    return [{"matched_surface": h["matched_surface"], "stems": h["stems"],
             "lineages": h["lineages"], "start_token": h["start_token"]}
            for h in horizon.find_breaches(text, compiled)]


def parse_extraction(message_texts, extraction):
    valid = []
    for text in message_texts:
        try:
            valid.append(extraction.model_validate_json(text))
        except ValidationError:
            pass
    if len(valid) != 1:
        raise ProbeStopped(f"{len(valid)} of {len(message_texts)} message item(s) validated; "
                           "exactly 1 required")
    return valid[0], len(message_texts) - 1


async def body(trace, figure_id, questions, year):
    compiled = load_compiled(figure_id)
    instructions, fmt, extraction_schema = (extract_instructions(year), text_format(year),
                                            extraction_model(year))
    spent, calls, answers = 0.0, 0, []

    async def call(**kwargs):
        nonlocal spent, calls
        if spent > COST_CAP_USD:
            trace.emit("coverage_stopped", "builder", {"reason": "cost cap", "spent_usd": spent})
            raise ProbeStopped(f"cost ${spent:.6f} passed the ${COST_CAP_USD} cap")
        result = await call_model(role="builder", tools=[], handlers={}, trace=trace,
                                  max_round_trips=1, **kwargs)
        spent += result.cost_usd
        calls += result.round_trips
        return result

    for q_number, question in enumerate(questions, 1):
        for sample in range(1, SAMPLES + 1):
            answer = await call(instructions=ANSWER_INSTRUCTIONS,
                                input_items=[{"role": "user", "content": question}])
            extraction_result = await call(
                instructions=instructions, text_format=fmt,
                input_items=[{"role": "user", "content": answer.text}])
            try:
                extraction, extra = parse_extraction(extraction_result.message_texts,
                                                     extraction_schema)
            except ProbeStopped as error:
                trace.emit("coverage_extraction_invalid", "builder", {
                    "question": question, "sample": sample, "reason": str(error),
                    "message_texts": extraction_result.message_texts})
                raise
            rows = [{**item.model_dump(), **classify(item.term, compiled)}
                    for item in extraction.items]
            record = {"question_number": q_number, "question": question, "sample": sample,
                      "answer": answer.text, "extra_message_items": extra, "items": rows,
                      "breach_hits": breach_hits(answer.text, compiled)}
            raw_file = trace.write_raw(f"coverage-q{q_number}s{sample}", record)
            trace.emit("coverage_answer", "builder", {
                "question_number": q_number, "sample": sample, "raw_file": raw_file,
                "extracted": len(rows), "breach_hits": len(record["breach_hits"]),
                "statuses": {s: sum(r["status"] == s for r in rows) for s in
                             ("mapped_beyond", "mapped_his", "near", "unmapped")}})
            answers.append(record)

    report = build_report(figure_id, answers, calls, spent)
    trace.emit("coverage_report", "builder", report)
    return {"figure_id": figure_id, "calls": calls, "cost_usd": round(spent, 8),
            "counts": report["counts"]}


def build_report(figure_id, answers, calls, spent):
    unmapped, mapped_his = {}, []
    for index, record in enumerate(answers):
        for row in record["items"]:
            if row["status"] == "unmapped":
                key = horizon.norm_term(row["concept"])
                group = unmapped.setdefault(key, {"concept": row["concept"], "terms": [],
                                                  "answers": set(), "emerged": []})
                if row["term"] not in group["terms"]:
                    group["terms"].append(row["term"])
                if row["emerged"] not in group["emerged"]:
                    group["emerged"].append(row["emerged"])
                group["answers"].add(index)
            elif row["status"] == "mapped_his":
                mapped_his.append({"question_number": record["question_number"],
                                   "sample": record["sample"], **row})
    groups = [{**g, "answers_using": len(g["answers"]), "answers": sorted(g["answers"])}
              for g in unmapped.values()]
    groups.sort(key=lambda g: (-g["answers_using"], horizon.norm_term(g["concept"])))
    rows = [r for record in answers for r in record["items"]]
    counts = {"extracted": len(rows), **{s: sum(r["status"] == s for r in rows) for s in
              ("mapped_beyond", "mapped_his", "near", "unmapped")}}
    hits = [{"question_number": r["question_number"], "sample": r["sample"],
             "hits": r["breach_hits"]} for r in answers]
    return {"figure_id": figure_id, "answers": len(answers), "counts": counts,
            "breach_hits_per_answer": hits,
            "unmapped_by_concept": groups, "mapped_his": mapped_his,
            "calls": calls, "cost_usd": round(spent, 8)}


def line(event: Event) -> str:
    p = event.payload
    if event.type == "round_trip":
        detail = (f"trip {p['trip']} · {p['latency_s']}s · in {p['input_tokens']} / out "
                  f"{p['output_tokens']} (reasoning {p['reasoning_tokens']}) · "
                  f"${p['est_cost_usd']:.6f}")
    elif event.type == "coverage_answer":
        detail = (f"q{p['question_number']} s{p['sample']} · {p['extracted']} items · "
                  f"{p['statuses']} · {p['breach_hits']} breach hits")
    elif event.type == "coverage_report":
        detail = "(below)"
    else:
        detail = json.dumps(p, ensure_ascii=False)[:300]
    return f"#{event.seq:<3} {event.type:<28} {event.role:<8} {detail}"


def render(answers, report, show_answers=True):
    out = []
    for record in answers:
        out += [f"\n=== Q{record['question_number']} sample {record['sample']}: "
                f"{record['question']}", ""]
        if show_answers:
            out += [record["answer"], ""]
        out += [f"{'term':<32}{'concept':<32}{'emerged':<18}status"]
        for r in record["items"]:
            match = f"  ({'; '.join(f'{n}:{t}' for n, t in r['matched'])})" if r["status"] == "near" else ""
            out.append(f"{r['term'][:31]:<32}{r['concept'][:31]:<32}{r['emerged'][:17]:<18}"
                       f"{r['status']}{match}")
        hits = "; ".join(f"{h['matched_surface']} [{'+'.join(h['stems'])}] @{h['start_token']}"
                         for h in record["breach_hits"]) or "none"
        out.append(f"find_breaches over the answer: {hits}")
    out += ["", "=== UNMAPPED, combined across all answers (by concept; answers using it)"]
    for g in report["unmapped_by_concept"]:
        out.append(f"  {g['answers_using']}/{report['answers']}  {g['concept']}  "
                   f"— terms: {', '.join(g['terms'])} — emerged: {', '.join(g['emerged'])}")
    out += ["", "=== MAPPED_HIS (matched a term of one of his available senses)"]
    out += [f"  Q{m['question_number']}s{m['sample']}  {m['term']}  ({m['concept']})"
            for m in report["mapped_his"]] or ["  none"]
    c = report["counts"]
    out += ["", f"counts: extracted {c['extracted']} · mapped_beyond {c['mapped_beyond']} · "
            f"mapped_his {c['mapped_his']} · near {c['near']} · unmapped {c['unmapped']}",
            f"calls: {report['calls']} · estimated cost: ${report['cost_usd']:.8f}"]
    return "\n".join(out)


async def main(figure_id):
    try:
        questions = load_questions(figure_id)
    except ProbeStopped as error:
        print(f"REFUSED: {error}")
        return 1
    events = []
    try:
        async for event in relay(partial(body, figure_id=figure_id, questions=questions,
                                         year=horizon_year(figure_id)),
                                 f"horizon coverage probe: {figure_id}", render=lambda e: e):
            print(line(event), flush=True)
            events.append(event)
    except Exception as error:
        print(f"RUN FAILED: {error!r}")
    if not events:
        return 1
    trace_dir = horizon.HORIZONS_DIR.parent / "traces" / events[-1].run_id
    print(f"\ntrace: traces/{events[-1].run_id}")
    report = next((e.payload for e in events if e.type == "coverage_report"), None)
    if report:
        print(render(read_answers(trace_dir), report))
    return 0 if events[-1].type == "run_complete" else 1


def read_answers(trace_dir):
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(Path(trace_dir).glob("raw/*-coverage-q*.json"))]


def from_trace(figure_id, trace_dir):
    """Re-classify an earlier run's extractions and answers. No calls; writes nothing."""
    compiled = load_compiled(figure_id)
    keys = (*FIELDS, why_field(horizon_year(figure_id)))
    answers = []
    for record in read_answers(trace_dir):
        rows = [{**{k: r[k] for k in keys},
                 **classify(r["term"], compiled)} for r in record["items"]]
        answers.append({**record, "items": rows,
                        "breach_hits": breach_hits(record["answer"], compiled)})
    if not answers:
        print(f"no coverage answers under {trace_dir}/raw")
        return 1
    report = build_report(figure_id, answers, calls=0, spent=0.0)
    print(f"re-classified {len(answers)} answers from {trace_dir} against compiled Horizon "
          f"{compiled['sources_sha256'][:12]}… (schema {compiled['schema_version']}); 0 calls")
    print(render(answers, report, show_answers=False))
    return 0


def _case(label, ok, detail=""):
    print(f"  {label:<62} {'PASS' if ok else 'FAIL'}{'  ' + detail if detail else ''}")
    return not ok


def selftest():
    """Offline cases: the filled extraction prompt per figure, and refusal without questions."""
    failures = 0
    darwin = extract_instructions(horizon_year("charles_darwin"))
    failures += _case("(a) Darwin's extraction prompt has 1882, not 180",
                      "1882" in darwin and "180" not in darwin)
    marcus = extract_instructions(horizon_year("marcus_aurelius"))
    failures += _case("(b) Marcus's extraction prompt has 180", "180" in marcus)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            load_questions("charles_darwin", root=tmp)
            failures += _case("(e) refuses a figure with no questions file", False, "NOT REFUSED")
        except ProbeStopped as error:
            failures += _case("(e) refuses a figure with no questions file", True, str(error))
    print("\nSELFTEST", "PASSED" if not failures else f"FAILED ({failures})")
    return 0 if not failures else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("figure_id", nargs="?")
    parser.add_argument("--from-trace", type=Path, metavar="RUN_DIR")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if not args.figure_id:
        parser.error("give a figure_id or --selftest")
    if args.from_trace:
        sys.exit(from_trace(args.figure_id, args.from_trace))
    sys.exit(asyncio.run(main(args.figure_id)))
