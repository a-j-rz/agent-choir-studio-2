"""Host call 2: classification and scoring (Topology & Steering §4–6).

The model sees the canonical question only: not the original wording, not call 1's reasoning,
not the roster. It decomposes, assigns archetypes, and scores five dimensions per unit, each with
its rationale first. Code does everything that decides anything:

    load prompt (forbidden terms) → call → parse (H4) → consistency → Scoring:
    sum each unit → highest total governs (ties: lowest index) → locked threshold → topology

The model has no field for a total or a topology, and its prompt names neither.
"""

from pathlib import Path
import hashlib
from typing import NamedTuple, get_args

from pydantic import ValidationError

from core.config import role_config
from core.llm import call_model
from core.trace import RunTrace
from host.records import (DIMENSIONS, SCORE_TEXT_FORMAT, Archetype, ClassificationOutput,
                          Scoring)
from host.triage import ARCHETYPES, normalise

ROOT = Path(__file__).resolve().parent.parent
PROMPT = ROOT / "prompts" / "host_score.md"
MAX_ROUND_TRIPS = 1  # no tools: one round trip is the whole call

# The locked threshold (Topology & Steering §6): 0–4 hub_and_spoke, 5–10 token_ring. No override.
TOKEN_RING_FROM = 5

# The routing must stay invisible to the scorer.
FORBIDDEN = ["topology", "token-ring", "hub-and-spoke", "threshold"]

# The archetype type and the call-1 tripwire list name the same eight labels.
assert set(get_args(Archetype)) == set(ARCHETYPES)


class HostScoreInvalid(Exception):
    """Call 2's output failed parsing (H4) or the consistency check."""


class Scored(NamedTuple):
    classification: ClassificationOutput
    scoring: Scoring
    prompt_sha256: str


def load_prompt(path: Path = PROMPT) -> tuple[str, str]:
    """The prompt text and its SHA-256. Fails loudly, naming each forbidden term it contains."""
    text = path.read_text(encoding="utf-8")
    hits = [t for t in FORBIDDEN if normalise(t) in normalise(text)]
    if hits:
        raise HostScoreInvalid(f"prompt {path.name} contains forbidden term(s): {hits}")
    missing = [a for a in get_args(Archetype) if a not in text]
    if missing:
        raise HostScoreInvalid(f"prompt {path.name} does not name archetype(s): {missing}")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_classification(message_texts: list[str]) -> tuple[ClassificationOutput, int]:
    """H4: exactly one message item must validate. Returns (output, extra message items).

    On failure the exception carries (rule, per-item errors: the error, or None if it validated).
    """
    valid, errors = [], []
    for text in message_texts:
        try:
            valid.append(ClassificationOutput.model_validate_json(text))
            errors.append(None)
        except ValidationError as error:
            errors.append(str(error))
    if len(valid) != 1:
        raise HostScoreInvalid(
            f"H4: {len(valid)} of {len(message_texts)} message item(s) validated; exactly 1 "
            "required", errors)
    return valid[0], len(message_texts) - 1


def check_classification(out: ClassificationOutput) -> list[str]:
    """Each rule broken, in words. Empty means consistent."""
    broken, units, n = [], out.units, len(out.units)
    if out.decomposition == "single":
        if n != 1:
            broken.append(f"single: exactly 1 unit required, got {n}")
        broken += [f"single: unit {i} depends_on must be null"
                   for i, u in enumerate(units) if u.depends_on is not None]
    elif out.decomposition == "compound":
        if n < 2:
            broken.append(f"compound: at least 2 units required, got {n}")
        broken += [f"compound: unit {i} depends_on must be null"
                   for i, u in enumerate(units) if u.depends_on is not None]
    else:  # nested
        if n < 2:
            broken.append(f"nested: at least 2 units required, got {n}")
        for i, u in enumerate(units):
            if u.depends_on is None:
                continue
            if u.depends_on == i:
                broken.append(f"nested: unit {i} depends_on itself")
            elif not 0 <= u.depends_on < n:
                broken.append(f"nested: unit {i} depends_on {u.depends_on} is out of range "
                              f"0..{n - 1}")
        if all(u.depends_on is None for u in units):
            broken.append("nested: at least one unit must have a non-null depends_on")
        broken += [f"nested: depends_on cycle through units {' → '.join(map(str, c))}"
                   for c in _cycles(out)]

    secondaries = out.secondary_archetypes
    if out.primary_archetype in secondaries:
        broken.append(f"primary_archetype {out.primary_archetype!r} also in secondary_archetypes")
    if len(set(secondaries)) != len(secondaries):
        broken.append("secondary_archetypes must be distinct")
    if len(secondaries) > 2:
        broken.append(f"at most 2 secondary_archetypes, got {len(secondaries)}")

    for i, u in enumerate(units):
        if not u.text.strip():
            broken.append(f"unit {i}: text must be non-empty")
        broken += [f"unit {i}: {d} rationale must be non-empty"
                   for d in DIMENSIONS if not getattr(u, d).rationale.strip()]
    return broken


def _cycles(out: ClassificationOutput) -> list[list[int]]:
    """Each distinct depends_on cycle, as a path that returns to its start, e.g. [0, 1, 0].

    Follows each unit's chain; a revisit is a cycle. Self-references and out-of-range links
    have their own rules, so a chain stops at them. A cycle is reported once, from its lowest unit.
    """
    n, found = len(out.units), []
    for start in range(n):
        path, cur = [start], start
        while True:
            nxt = out.units[cur].depends_on
            if nxt is None or nxt == cur or not 0 <= nxt < n:
                break
            if nxt in path:
                loop = path[path.index(nxt):]
                first = loop.index(min(loop))
                cycle = loop[first:] + loop[:first]
                if cycle + [cycle[0]] not in found:
                    found.append(cycle + [cycle[0]])
                break
            path.append(nxt)
            cur = nxt
    return found


def compute_scoring(out: ClassificationOutput, research_needed: bool) -> Scoring:
    """Plain arithmetic and the locked threshold. Nothing here is a judgement."""
    totals = [sum(getattr(u, d).score for d in DIMENSIONS) for u in out.units]
    governing_total = max(totals)
    governing_unit = totals.index(governing_total)  # first occurrence: ties go to the lowest index
    if governing_total >= TOKEN_RING_FROM:
        topology, rule = "token_ring", f"governing total {governing_total} ≥ {TOKEN_RING_FROM} → token_ring"
    else:
        topology = "hub_and_spoke"
        rule = f"governing total {governing_total} ≤ {TOKEN_RING_FROM - 1} → hub_and_spoke"
    return Scoring(
        unit_totals=totals, governing_unit=governing_unit, governing_total=governing_total,
        topology=topology, rule=rule,
        score_status="provisional_is_final_research_not_run" if research_needed else "final")


async def score_canonical(trace: RunTrace, canonical_question: str,
                          research_needed: bool = False) -> Scored:
    """Call 2 on a canonical question alone. Raises (run failed) on invalid output."""
    prompt, sha = load_prompt()
    trace.annotate("host_score_prompt_sha256", sha)
    trace.emit("host_score_bound", "host", {
        "prompt_file": str(PROMPT.relative_to(ROOT)), "prompt_sha256": sha,
        "role_config": role_config("host").model_dump(), "max_round_trips": MAX_ROUND_TRIPS})

    result = await call_model(
        role="host",
        instructions=prompt,
        input_items=[{"role": "user", "content": canonical_question}],
        tools=[],
        handlers={},
        trace=trace,
        max_round_trips=MAX_ROUND_TRIPS,
        text_format=SCORE_TEXT_FORMAT,
    )

    try:
        out, extra_items = parse_classification(result.message_texts)
    except HostScoreInvalid as error:
        trace.emit("host_score_invalid", "host", {
            "rule": error.args[0], "errors": error.args[1],
            "message_texts": result.message_texts, "stop_reason": result.stop_reason})
        raise

    broken = check_classification(out)
    if broken:
        trace.emit("host_score_invalid", "host", {
            "rule": "consistency", "broken": broken, "classification": out.model_dump()})
        raise HostScoreInvalid(f"inconsistent classification output: {broken}")
    trace.emit("host_classification", "host", {
        "classification": out.model_dump(), "consistency": {"consistent": True, "broken": []},
        "extra_message_items": extra_items, "stop_reason": result.stop_reason})

    scoring = compute_scoring(out, research_needed)
    trace.emit("host_scoring", "host", scoring.model_dump())
    trace.annotate("topology", scoring.topology)
    return Scored(out, scoring, sha)
