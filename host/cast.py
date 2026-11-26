"""Host call 3: cast assessment and selection (Topology & Steering §7; Choir & Corpus §1–2, §5).

The model sees exactly three things: the canonical question, the archetypes from call 2, and the
roster metadata (with a manifest summary where a corpus is built). Never the scores, the topology,
the original wording or call 1's reasoning. It assesses every candidate before it selects.

    load prompt (forbidden terms) → load roster (built ⇔ manifest) → build input → call
    → parse (H4) → consistency → CastRecord: would_reject, gate_unassessable, gate_not_applied,
    near_miss_note

On the machine-proving four the choice is degenerate (four from four); the assessments are the
information. A would_reject entry is a recorded prediction, tested against retrieval in Phase 5.
"""

from collections import Counter
from pathlib import Path
import hashlib
import json
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, ValidationError

from core.config import role_config
from core.llm import call_model
from core.trace import RunTrace
from host.records import CAST_TEXT_FORMAT, CastOutput, CastRecord
from host.triage import DIMENSIONS, normalise

ROOT = Path(__file__).resolve().parent.parent
PROMPT = ROOT / "prompts" / "host_cast.md"
ROSTER = ROOT / "host" / "roster.json"
CORPORA = ROOT / "corpora"
MAX_ROUND_TRIPS = 1
CAST_SIZE = 4  # locked (Choir & Corpus §1)

# The selector must not see how the question was scored or routed.
FORBIDDEN = ["topology", "token-ring", "hub-and-spoke", "threshold", "score", *DIMENSIONS]

GATE_NOT_APPLIED = "roster exhausted"
NEAR_MISS_NOTE = "roster of four; none to miss"
MANIFEST_FIELDS = ["included_works", "period", "genre", "audience_context"]


class HostCastInvalid(Exception):
    """Call 3's output failed parsing (H4) or the consistency check."""


class RosterEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    figure_id: str
    name: str
    handle: str
    primary_contribution: str
    corpus: Literal["built", "not_built"]


class Cast(NamedTuple):
    record: CastRecord
    prompt_sha256: str


def load_prompt(path: Path = PROMPT) -> tuple[str, str]:
    """The prompt text and its SHA-256. Fails loudly, naming each forbidden term it contains."""
    text = path.read_text(encoding="utf-8")
    hits = [t for t in FORBIDDEN if normalise(t) in normalise(text)]
    if hits:
        raise HostCastInvalid(f"prompt {path.name} contains forbidden term(s): {hits}")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_roster(path: Path = ROSTER, corpora: Path = CORPORA) -> list[RosterEntry]:
    """The roster, in file order. A figure is built if and only if its manifest exists."""
    data = json.loads(path.read_text(encoding="utf-8"))
    roster = [RosterEntry.model_validate(f) for f in data["figures"]]
    ids = [f.figure_id for f in roster]
    if len(set(ids)) != len(ids):
        raise ValueError(f"roster has duplicate figure ids: {ids}")
    for f in roster:
        has_manifest = (corpora / f.figure_id / "manifest.json").exists()
        if has_manifest != (f.corpus == "built"):
            raise ValueError(f"roster says {f.figure_id} corpus is {f.corpus}, but its manifest "
                             f"{'exists' if has_manifest else 'does not exist'}")
    return roster


def roster_input(roster: list[RosterEntry], corpora: Path = CORPORA) -> list[dict]:
    """What the model is told about each figure: roster fields, plus a manifest summary if built."""
    out = []
    for f in roster:
        manifest = None
        if f.corpus == "built":
            m = json.loads((corpora / f.figure_id / "manifest.json").read_text(encoding="utf-8"))
            manifest = {k: m[k] for k in MANIFEST_FIELDS}
            manifest["translation_edition"] = {"translator": m["translation_edition"]["translator"]}
        out.append({**f.model_dump(), "manifest": manifest})
    return out


def build_input(canonical_question: str, primary: str, secondaries: list[str],
                roster: list[dict]) -> list[dict]:
    """Two input items: the question and its archetypes; then the roster as JSON."""
    first = (f"Question: {canonical_question}\n"
             f"Primary archetype: {primary}\n"
             f"Secondary archetypes: {'; '.join(secondaries) if secondaries else 'none'}")
    return [{"role": "user", "content": first},
            {"role": "user", "content": json.dumps(roster, indent=2, ensure_ascii=False)}]


def parse_cast(message_texts: list[str]) -> tuple[CastOutput, int]:
    """H4: exactly one message item must validate. Returns (output, extra message items).

    On failure the exception carries (rule, per-item errors: the error, or None if it validated).
    """
    valid, errors = [], []
    for text in message_texts:
        try:
            valid.append(CastOutput.model_validate_json(text))
            errors.append(None)
        except ValidationError as error:
            errors.append(str(error))
    if len(valid) != 1:
        raise HostCastInvalid(
            f"H4: {len(valid)} of {len(message_texts)} message item(s) validated; exactly 1 "
            "required", errors)
    return valid[0], len(message_texts) - 1


def check_cast(out: CastOutput, roster: list[RosterEntry]) -> list[str]:
    """Each rule broken, in words. Empty means consistent."""
    broken, corpus = [], {f.figure_id: f.corpus for f in roster}

    counts = Counter(a.figure_id for a in out.candidate_assessments)
    for fid, n in counts.items():
        if fid not in corpus:
            broken.append(f"unknown figure {fid} assessed")
        elif n > 1:
            broken.append(f"{fid} assessed {n} times; exactly once required")
    broken += [f"roster figure {fid} not assessed" for fid in corpus if fid not in counts]

    for a in out.candidate_assessments:
        if a.figure_id not in corpus:
            continue
        rating = a.corpus_suitability.rating
        if corpus[a.figure_id] == "not_built" and rating != "unassessable":
            broken.append(f"{a.figure_id}: corpus_suitability is {rating}, but its corpus is "
                          "not_built: must be unassessable")
        if corpus[a.figure_id] == "built" and rating == "unassessable":
            broken.append(f"{a.figure_id}: corpus_suitability is unassessable, but its corpus is "
                          "built")

    if len(out.selected) != CAST_SIZE:
        broken.append(f"exactly {CAST_SIZE} selected required, got {len(out.selected)}")
    broken += [f"selected must be distinct: {fid} repeated"
               for fid, n in Counter(out.selected).items() if n > 1]
    broken += [f"unknown figure {fid} selected" for fid in dict.fromkeys(out.selected)
               if fid not in corpus]

    near = [m.figure_id for m in out.near_misses]
    broken += [f"near_misses must be distinct: {fid} repeated" for fid, n in Counter(near).items()
               if n > 1]
    for fid in dict.fromkeys(near):
        if fid not in corpus:
            broken.append(f"unknown near miss {fid}")
        elif fid in out.selected:
            broken.append(f"near miss {fid} is in selected")

    for a in out.candidate_assessments:
        for criterion in ("archetype_relevance", "question_fit", "corpus_suitability"):
            if not getattr(a, criterion).reason.strip():
                broken.append(f"{a.figure_id}: {criterion} reason must be non-empty")
    broken += [f"near miss {m.figure_id}: reason must be non-empty"
               for m in out.near_misses if not m.reason.strip()]
    for field in ("panel_diversity", "panel_redundancy", "panel_tension"):
        if not getattr(out, field).strip():
            broken.append(f"{field} must be non-empty")
    return broken


def cast_record(out: CastOutput, roster: list[RosterEntry]) -> CastRecord:
    """What the gate would have done, and why it could not. Plain code."""
    corpus = {a.figure_id: a.corpus_suitability.rating for a in out.candidate_assessments}
    would_reject = [fid for fid in out.selected if corpus[fid] == "weak"]
    unassessable = [fid for fid in out.selected if corpus[fid] == "unassessable"]
    unselected = [f.figure_id for f in roster if f.figure_id not in out.selected]
    return CastRecord(
        output=out, would_reject=would_reject, gate_unassessable=unassessable,
        gate_not_applied=GATE_NOT_APPLIED if (would_reject or unassessable) else None,
        near_miss_note=NEAR_MISS_NOTE if not unselected else None)


async def select_cast(trace: RunTrace, canonical_question: str, primary_archetype: str,
                      secondary_archetypes: list[str]) -> Cast:
    """Call 3. Raises (run failed) on invalid output."""
    prompt, sha = load_prompt()
    roster = load_roster()
    input_items = build_input(canonical_question, primary_archetype, secondary_archetypes,
                              roster_input(roster))
    trace.annotate("host_cast_prompt_sha256", sha)
    trace.emit("host_cast_bound", "host", {
        "prompt_file": str(PROMPT.relative_to(ROOT)), "prompt_sha256": sha,
        "role_config": role_config("host").model_dump(), "max_round_trips": MAX_ROUND_TRIPS,
        "input_items": input_items})

    result = await call_model(
        role="host",
        instructions=prompt,
        input_items=input_items,
        tools=[],
        handlers={},
        trace=trace,
        max_round_trips=MAX_ROUND_TRIPS,
        text_format=CAST_TEXT_FORMAT,
    )

    try:
        out, extra_items = parse_cast(result.message_texts)
    except HostCastInvalid as error:
        trace.emit("host_cast_invalid", "host", {
            "rule": error.args[0], "errors": error.args[1],
            "message_texts": result.message_texts, "stop_reason": result.stop_reason})
        raise

    broken = check_cast(out, roster)
    if broken:
        trace.emit("host_cast_invalid", "host", {
            "rule": "consistency", "broken": broken, "output": out.model_dump()})
        raise HostCastInvalid(f"inconsistent cast output: {broken}")

    record = cast_record(out, roster)
    trace.emit("host_cast", "host", {
        "cast": record.model_dump(), "consistency": {"consistent": True, "broken": []},
        "extra_message_items": extra_items, "stop_reason": result.stop_reason})
    return Cast(record, sha)
