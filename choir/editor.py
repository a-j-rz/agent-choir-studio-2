"""The hub-and-spoke Editor: a frozen input, one call, checked output (System §5; Decisions K10).

    after the baseline:
    compile the Editor input from the decision record, the baseline and the cited passages
    → write editor_input.json once, name it by SHA-256 (`editor_input`)
    → read the written text back and send exactly that (`editor_bound`, then the call)
    → write editor_output.json once, always: the raw texts and, if it parsed, the output
    → parse (H4) and run every check → editor_audit + editor_synthesis, or editor_invalid

The input is the point where probabilistic contributions become a fixed document: 5d re-runs the
same bytes offline. Code checks the structured lists (cast, cited passages, received bridges,
would_reject, degraded state), never the prose. Any failure is an Editor failure and fails the
run (§14), with the baseline, the input and the raw output kept. Nothing is repaired or re-called.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from core.config import role_config
from core.llm import call_model
from core.trace import RunTrace

ROOT = Path(__file__).resolve().parent.parent
PROMPT = ROOT / "prompts" / "editor_hub.md"
MAX_ROUND_TRIPS = 1
ROLE = "editor"
INPUT_SCHEMA_VERSION = 1

AnswerClass = Literal["answered", "answered_neighbour", "declined_on_evidence", "over_declared",
                      "under_declared", "not_contributed"]
Verdict = Literal["supports", "partly", "does_not_support", "out_of_context"]
Kind = Literal["empirical", "normative", "mixed"]
Disposition = Literal["recommended_conclusion", "balanced_split", "insufficient_basis"]


class EditorInvalid(Exception):
    """The Editor's output did not parse, failed a check, or the call failed: the run fails."""


# ---------------------------------------------------------------- output types (field order matters)

class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Evidence(_Model):
    passage_id: str
    note: str
    verdict: Verdict


class GateCheck(_Model):
    reason: str
    borne_out: bool


class AuditFigure(_Model):
    figure_id: str
    reason: str
    answer_class: AnswerClass
    evidence: list[Evidence]
    gate_check: GateCheck | None
    modern_knowledge: list[str]


class Disagreement(_Model):
    about: str
    figures: list[str]
    kind: Kind


class Consensus(_Model):
    note: str
    counterfeit: bool


class Audit(_Model):
    figures: list[AuditFigure]
    disagreements: list[Disagreement]
    consensus: Consensus


class Point(_Model):
    point: str
    figures: list[str]


class UnresolvedPoint(_Model):
    point: str
    figures: list[str]
    kind: Kind


class HistoricalCitation(_Model):
    figure_id: str
    passage_id: str
    supports: str


class ModernReference(_Model):
    figure_id: str
    bridge_number: int
    used_for: str


class Synthesis(_Model):
    rationale: str
    disposition: Disposition
    answer: str
    convergence: list[Point]
    unresolved: list[UnresolvedPoint]
    historical_citations: list[HistoricalCitation]
    modern_references: list[ModernReference]
    what_would_change: list[str]
    missing_perspective: str | None


class EditorOutput(_Model):
    schema_version: Literal[1] = 1  # added by our code; the model never writes it
    audit: Audit
    synthesis: Synthesis


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


def _enum(values) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


_S = {"type": "string"}
_IDS = {"type": "array", "items": _S}

# Hand-written so it can be read; strict. Property order is the order the model writes in.
EDITOR_FORMAT = {
    "type": "json_schema",
    "name": "editor_output",
    "strict": True,
    "schema": _obj({
        "audit": _obj({
            "figures": {"type": "array", "items": _obj({
                "figure_id": _S,
                "reason": _S,
                "answer_class": _enum(AnswerClass.__args__),
                "evidence": {"type": "array", "items": _obj({
                    "passage_id": _S, "note": _S, "verdict": _enum(Verdict.__args__)})},
                "gate_check": {"anyOf": [_obj({"reason": _S, "borne_out": {"type": "boolean"}}),
                                         {"type": "null"}]},
                "modern_knowledge": {"type": "array", "items": _S},
            })},
            "disagreements": {"type": "array", "items": _obj({
                "about": _S, "figures": _IDS, "kind": _enum(Kind.__args__)})},
            "consensus": _obj({"note": _S, "counterfeit": {"type": "boolean"}}),
        }),
        "synthesis": _obj({
            "rationale": _S,
            "disposition": _enum(Disposition.__args__),
            "answer": _S,
            "convergence": {"type": "array", "items": _obj({"point": _S, "figures": _IDS})},
            "unresolved": {"type": "array", "items": _obj({
                "point": _S, "figures": _IDS, "kind": _enum(Kind.__args__)})},
            "historical_citations": {"type": "array", "items": _obj({
                "figure_id": _S, "passage_id": _S, "supports": _S})},
            "modern_references": {"type": "array", "items": _obj({
                "figure_id": _S, "bridge_number": {"type": "integer"}, "used_for": _S})},
            "what_would_change": {"type": "array", "items": _S},
            "missing_perspective": {"type": ["string", "null"]},
        }),
    }),
}


def _drift(schema: dict[str, Any], model: type[BaseModel], skip=("schema_version",)) -> None:
    """Schema properties equal the model's fields, in the same order; recurse into objects."""
    props = schema["properties"]
    fields = [f for f in model.model_fields if f not in skip]
    assert list(props) == fields == schema["required"], (model.__name__, list(props), fields)
    for name, sub in props.items():
        annotation = model.model_fields[name].annotation
        inner = getattr(annotation, "__args__", (annotation,))
        target = next((a for a in inner if isinstance(a, type) and issubclass(a, BaseModel)), None)
        if target is None:
            continue
        node = sub.get("items", sub)
        node = next((n for n in node.get("anyOf", [node]) if n.get("type") == "object"), node)
        _drift(node, target, skip=())


# The schema and the classes must not drift apart, in membership and in order: checked at import.
_drift(EDITOR_FORMAT["schema"], EditorOutput)


def load_prompt(path: Path = PROMPT) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- the frozen input

def compile_editor_input(choir_input, record, baseline: dict[str, Any],
                         editor_passages: dict[str, list[dict[str, Any]]],
                         names: dict[str, str]) -> dict[str, Any]:
    """The Editor's whole input, built deterministically. Keys are written in a fixed order.

    Never included: passages opened but not cited, reconciliation or leakage flags, candidate
    lists, prompts, anything from another run.
    """
    cast_record = record.cast
    would_reject = set(cast_record.would_reject)
    assessments = {a.figure_id: a for a in cast_record.output.candidate_assessments}
    classification, scoring = record.classification, record.scoring
    dims = ["value_conflict", "interpretive_ambiguity", "cross_domain_interaction",
            "challenge_value", "consequence_stakes"]

    figures = []
    for entry in baseline["figures"]:
        fid = entry["figure_id"]
        block: dict[str, Any] = {"figure_id": fid, "name": names[fid], "outcome": entry["outcome"]}
        if entry["outcome"] != "contributed":
            block["failure_class"] = entry.get("failure_class")
            figures.append(block)
            continue
        cited = []
        for p in editor_passages[fid]:
            cited.append({
                "passage_id": p["passage_id"], "locator": p["locator"], "text": p["text"],
                "context_neighbours": [{"side": n["side"], "passage_id": n["passage_id"],
                                        "locator": n["locator"], "text": n["text"]}
                                       for n in p["neighbours"]]})
        explanations = []
        for b in entry["oracle_bridges"]:
            if b["returned"].get("status") == "bridged":
                explanations.append({"number": b["number"], "concept": b["concept"],
                                     "returned": b["returned"]})
            else:
                explanations.append({"number": b["number"], "concept": b["concept"],
                                     "unanswered": True})
        block.update({"contribution": entry["contribution"], "check_flags": entry["check_flags"],
                      "search_queries": entry["search_queries"], "cited_passages": cited,
                      "modern_explanations": explanations})
        figures.append(block)

    return {
        "schema_version": INPUT_SCHEMA_VERSION,
        "question": {
            "canonical_question": choir_input.canonical_question,
            "answer_criterion": record.triage.answer_criterion,
            "read_only": {"original_question": record.original_question, "clarification": None},
        },
        "host": {
            "primary_archetype": classification.primary_archetype,
            "secondary_archetypes": list(classification.secondary_archetypes),
            "scoring": {
                "units": [{"text": u.text, **{d: getattr(u, d).score for d in dims}}
                          for u in classification.units],
                "governing_total": scoring.governing_total,
                "topology": scoring.topology,
                "rule": scoring.rule,
            },
            "figures": [{"figure_id": fid,
                         "assessment": assessments[fid].model_dump(exclude={"figure_id"}),
                         "would_reject": fid in would_reject}
                        for fid in baseline["cast"]],
        },
        "figures": figures,
    }


def serialise(editor_input: dict[str, Any]) -> str:
    return json.dumps(editor_input, ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------- parsing and checks

def parse_editor_output(message_texts: list[str]) -> EditorOutput:
    """H4: exactly one message item must validate. Never repaired."""
    valid, errors = [], []
    for text in message_texts:
        try:
            valid.append(EditorOutput.model_validate_json(text))
        except ValidationError as error:
            errors.append(str(error))
    if len(valid) != 1:
        raise EditorInvalid(f"H4: {len(valid)} of {len(message_texts)} message item(s) "
                            f"validated; exactly 1 required", errors)
    return valid[0]


def check_editor_output(out: EditorOutput, baseline: dict[str, Any], would_reject: list[str],
                        degraded: bool) -> list[str]:
    """Every check runs; every violation is returned, each named by its check number."""
    cast = list(baseline["cast"])
    entries = {f["figure_id"]: f for f in baseline["figures"]}
    contributed = {fid for fid, f in entries.items() if f["outcome"] == "contributed"}
    cited = {fid: set(f.get("cited", [])) for fid, f in entries.items()}
    bridged = {fid: {b["number"] for b in f.get("oracle_bridges", [])
                     if b["returned"].get("status") == "bridged"} for fid, f in entries.items()}
    audit, synth = out.audit, out.synthesis
    v = []

    ids = [f.figure_id for f in audit.figures]
    if ids != cast:  # 1
        v.append(f"check 1: audit.figures ids {ids} are not the cast {cast}, in order, once each")
    for f in audit.figures:  # 2
        if (f.answer_class == "not_contributed") != (f.figure_id not in contributed):
            v.append(f"check 2: {f.figure_id} answer_class {f.answer_class!r} but its lane "
                     f"{'contributed' if f.figure_id in contributed else 'did not contribute'}")
    for f in audit.figures:  # 3
        got = {e.passage_id for e in f.evidence}
        want = cited.get(f.figure_id, set()) if f.figure_id in contributed else set()
        if got != want:
            v.append(f"check 3: {f.figure_id} evidence ids {sorted(got)} != cited {sorted(want)}")
    for f in audit.figures:  # 4
        if (f.gate_check is not None) != (f.figure_id in would_reject):
            v.append(f"check 4: {f.figure_id} gate_check "
                     f"{'present' if f.gate_check else 'null'} but would_reject "
                     f"{'names' if f.figure_id in would_reject else 'does not name'} it")
    for where, items, minimum in (("disagreements", audit.disagreements, 2),
                                  ("unresolved", synth.unresolved, 2),
                                  ("convergence", synth.convergence, 1)):  # 5
        for i, item in enumerate(items):
            outside = [x for x in item.figures if x not in cast]
            if len(set(item.figures)) < minimum or outside:
                v.append(f"check 5: {where}[{i}] names {item.figures}: needs at least {minimum} "
                         f"distinct cast figure(s)" + (f", not in cast {outside}" if outside else ""))
    for c in synth.historical_citations:  # 6
        if c.passage_id not in cited.get(c.figure_id, set()):
            v.append(f"check 6: historical citation {c.figure_id}/{c.passage_id} is not a passage "
                     "that figure cited")
    for m in synth.modern_references:  # 7
        if m.bridge_number not in bridged.get(m.figure_id, set()):
            v.append(f"check 7: modern reference {m.figure_id}/bridge {m.bridge_number} is not a "
                     "bridged answer that figure received")
    if not synth.what_would_change or any(not s.strip() for s in synth.what_would_change):  # 8
        v.append(f"check 8: what_would_change must be non-empty with no empty strings: "
                 f"{synth.what_would_change}")
    has_missing = synth.missing_perspective is not None and synth.missing_perspective.strip() != ""
    if has_missing != degraded:  # 9
        v.append(f"check 9: missing_perspective {'present' if has_missing else 'missing'} on a "
                 f"{'degraded' if degraded else 'complete'} run")
    if synth.disposition not in Disposition.__args__:  # 10 (also enforced by the schema)
        v.append(f"check 10: disposition {synth.disposition!r} is not a locked label")
    return v


# ---------------------------------------------------------------- the run step

async def run_editor(trace: RunTrace, choir_input, record, choir_result, names: dict[str, str],
                     degraded: bool) -> dict[str, Any]:
    """Compile, freeze, call, record, check. Returns the disposition; raises EditorInvalid."""
    baseline = choir_result.baseline
    editor_input = compile_editor_input(choir_input, record, baseline,
                                        choir_result.editor_passages, names)
    input_file, input_sha = trace.write_editor_input(serialise(editor_input))
    trace.emit("editor_input", ROLE, {"file": input_file, "sha256": input_sha})
    # Exactly what was written is what is sent: read back, never rebuilt.
    sent = (trace.dir / input_file).read_text(encoding="utf-8")

    prompt, prompt_sha = load_prompt()
    trace.annotate("editor_prompt_sha256", prompt_sha)
    trace.emit("editor_bound", ROLE, {
        "prompt_file": str(PROMPT.relative_to(ROOT)), "prompt_sha256": prompt_sha,
        "role_config": role_config(ROLE).model_dump(), "max_round_trips": MAX_ROUND_TRIPS,
        "input_sha256": input_sha})

    result, call_error = None, None
    try:
        result = await call_model(role=ROLE, instructions=prompt,
                                  input_items=[{"role": "user", "content": sent}], tools=[],
                                  handlers={}, trace=trace, max_round_trips=MAX_ROUND_TRIPS,
                                  text_format=EDITOR_FORMAT)
    except Exception as error:  # transient exhausted, or final: recorded below, then the run fails
        call_error = error

    texts = result.message_texts if result else []
    parsed, errors, violations = None, [], []
    if call_error is not None:
        errors.append(f"call failed: {call_error!r}")
    else:
        try:
            parsed = parse_editor_output(texts)
        except EditorInvalid as error:
            errors.append(error.args[0])
            errors.extend(e for e in error.args[1])
    if parsed is not None:
        violations = check_editor_output(parsed, baseline, list(record.cast.would_reject),
                                         degraded)
    valid = parsed is not None and not violations

    out_file, out_sha = trace.write_editor_output({
        "message_texts": texts, "parsed": parsed.model_dump() if parsed else None,
        "stop_reason": result.stop_reason if result else None,
        "call_error": repr(call_error) if call_error else None})
    trace.emit("editor_output", ROLE, {"file": out_file, "sha256": out_sha, "valid": valid,
                                       "parsed": parsed is not None})
    if not valid:
        trace.emit("editor_invalid", ROLE, {"errors": errors, "violations": violations})
        raise EditorInvalid(f"Editor output invalid: {len(errors)} error(s), "
                            f"{len(violations)} check violation(s)") from call_error
    trace.emit("editor_audit", ROLE, parsed.audit.model_dump())
    trace.emit("editor_synthesis", ROLE, parsed.synthesis.model_dump())
    trace.annotate("disposition", parsed.synthesis.disposition)
    return {"disposition": parsed.synthesis.disposition, "input_sha256": input_sha,
            "output_sha256": out_sha}
