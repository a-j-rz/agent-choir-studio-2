"""Generate a figure's horizon-probe questions blind: one `builder` call, written once.

    python -m scripts.generate_probe_questions <figure_id>   # exactly 1 live call
    python -m scripts.generate_probe_questions --selftest    # offline cases; no calls

The prompt names no figure, no year and no project, and gives no example questions, so nothing
from this project can imprint on the questions. The answer is strict structured output: exactly
three strings. They are written verbatim to horizons/probe_questions/<figure_id>.json — no
curation — with the call's provenance as the file's source. The raw request and response are
in the run's trace. Refuses to run if the file already exists: question files are write-once.
"""

import argparse
import asyncio
from functools import partial
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

from core.events import utc_iso
from core.llm import call_model
from core.runner import relay
from host.cast import load_roster
from scripts.horizon_coverage_probe import QUESTIONS_DIR, QuestionsFile

PROMPT = ("List three questions an adult today might bring to a panel of thoughtful people, "
          "about their own life or about the world. Each is one sentence ending in a question "
          "mark. Vary the subjects.")
ORDER = ("first", "second", "third")  # no digits anywhere in the request
PROMPT_SHA256 = hashlib.sha256(PROMPT.encode("utf-8")).hexdigest()
TEXT_FORMAT = {
    "type": "json_schema", "name": "three_questions", "strict": True,
    "schema": {
        "type": "object",
        "properties": {k: {"type": "string"} for k in ORDER},
        "required": list(ORDER),
        "additionalProperties": False,
    },
}


class GeneratorRefused(Exception):
    pass


def request():
    """Everything the call sends besides model and effort: the prompt, nothing else."""
    return {"instructions": "", "input_items": [{"role": "user", "content": PROMPT}],
            "text_format": TEXT_FORMAT}


def refuse_existing(path: Path):
    if path.exists():
        raise GeneratorRefused(f"{path.name} already exists; probe question files are write-once")


async def body(trace, figure_id, root):
    path = Path(root) / f"{figure_id}.json"
    refuse_existing(path)
    result = await call_model(role="builder", tools=[], handlers={}, trace=trace,
                              max_round_trips=1, **request())
    if len(result.message_texts) != 1:
        raise GeneratorRefused(f"{len(result.message_texts)} message items; exactly 1 required")
    answer = json.loads(result.message_texts[0])
    questions = [answer[k] for k in ORDER]
    data = QuestionsFile(schema_version="1", questions=questions, source=(
        f"generate_probe_questions.py, one blind builder call, {utc_iso()}, "
        f"prompt sha256 {PROMPT_SHA256}")).model_dump()
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    refuse_existing(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    file_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    trace.emit("probe_questions_written", "builder", {
        "file": f"horizons/probe_questions/{path.name}", "sha256": file_sha,
        "questions": questions, "calls": result.round_trips, "cost_usd": result.cost_usd})
    return {"questions": questions, "sha256": file_sha, "cost_usd": result.cost_usd}


async def main(figure_id, root=QUESTIONS_DIR):
    try:
        refuse_existing(Path(root) / f"{figure_id}.json")
    except GeneratorRefused as error:
        print(f"REFUSED: {error}")
        return 1
    last = None
    try:
        async for event in relay(partial(body, figure_id=figure_id, root=root),
                                 f"generate probe questions: {figure_id}", render=lambda e: e):
            last = event
            if event.type == "probe_questions_written":
                p = event.payload
                print("\n".join(p["questions"]))
                print(f"wrote {p['file']} · sha256 {p['sha256']} · calls {p['calls']} · "
                      f"estimated cost ${p['cost_usd']:.8f}")
    except Exception as error:
        print(f"RUN FAILED: {error!r}")
    if last is not None:
        print(f"trace: traces/{last.run_id}")
    return 0 if last is not None and last.type == "run_complete" else 1


def _case(label, ok, detail=""):
    print(f"  {label:<62} {'PASS' if ok else 'FAIL'}{'  ' + detail if detail else ''}")
    return not ok


def selftest():
    """Offline cases: the request carries no imprint; an existing file is refused."""
    failures = 0
    sent = json.dumps(request(), ensure_ascii=False).lower()
    words = set(re.findall(r"[a-z]+", sent))
    names = sorted({w for f in load_roster() for w in re.findall(r"[a-z]+", f.name.lower())}
                   | {f.figure_id for f in load_roster()})
    marcus = QuestionsFile.model_validate_json(
        (QUESTIONS_DIR / "marcus_aurelius.json").read_bytes()).questions
    found = ([n for n in names if n in words or n in sent.replace(" ", "_")]
             + re.findall(r"\d", sent) + [q for q in marcus if q.lower() in sent])
    failures += _case("(c) request has no roster name, no year, no Marcus question",
                      not found, f"found {found}" if found else "")
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "toy.json").write_text("{}", encoding="utf-8")
        try:
            refuse_existing(Path(tmp) / "toy.json")
            failures += _case("(d) refuses an existing file", False, "NOT REFUSED")
        except GeneratorRefused as error:
            failures += _case("(d) refuses an existing file", True, str(error))
    print("\nSELFTEST", "PASSED" if not failures else f"FAILED ({failures})")
    return 0 if not failures else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("figure_id", nargs="?")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if not args.figure_id:
        parser.error("give a figure_id or --selftest")
    sys.exit(asyncio.run(main(args.figure_id)))
