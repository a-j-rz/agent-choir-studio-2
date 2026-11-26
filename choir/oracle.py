"""The Oracle: a neutral bridge to one modern concept, bound per figure per turn (System §7).

"The Oracle may tell you what the modern world contains. Your corpus determines what you
think about it."

The Oracle is told the asker's epoch, where the concept sits on its lineage relative to the
asker, the concept, and the asker's own words about where they met it — and nothing else: never
the figure's name, corpus, dossier, or the user's question. Its input is composed here, in code.

Per request, in order: budget → Horizon lookup (deterministic) → truncate the asker's words →
identity flag on the figure's own words (concept, where_encountered), whose name tokens are then
replaced with "[name]" in what is sent; the trace keeps the original → identity guarantee on the
whole composed input after redaction (raises if broken) → write the composed input, emit
oracle_request → call → parse (H4).
A technical failure returns an error to the figure and never fails the figure (Topology §14).
The request gets the same one logged retry as every role (core.llm; Decisions K9): the former
"no retry" was in fact two silent SDK retries.
"""

import copy
import json
from pathlib import Path
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from core.config import ORACLE
from core.llm import call_model
from epistemic import horizon
from retrieval.bm25 import analyse

ROOT = Path(__file__).resolve().parent.parent
PROMPT = ROOT / "prompts" / "oracle.md"
MAX_ROUND_TRIPS = 1  # no tools: one call is the whole answer

REDACTION = "[name]"
ASKER_LINE = "What their world already understands about this: {label}: {summary}"
BEYOND_LINES = (
    "What they are asking about is a later idea: {label}: {summary}\n"
    "({distance_phrase})"
)
UNREACHED_LINE = ("What they are asking about existed in their own time, in a world they never "
                  "reached: {label}: {summary}")
UNMAPPED_LINE = ("No counterpart from their world is recorded for this; build from what an "
                 "educated person of their time would know.")
# A candidate word, as BM25's tokeniser finds them (letters, internal apostrophes); each one is
# then stemmed with the same analyse() before deciding whether it is a name.
_WORD = re.compile(r"[^\W\d_]+(?:['\u2019\u2018][^\W\d_]+)*")


class OracleAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"  # added by our code; the model never writes it
    status: Literal["bridged", "cannot_bridge"]
    explanation: str
    anchors: list[str]
    left_out: list[str]


TEXT_FORMAT = {
    "type": "json_schema",
    "name": "oracle_answer",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["bridged", "cannot_bridge"]},
            "explanation": {"type": "string"},
            "anchors": {"type": "array", "items": {"type": "string"}},
            "left_out": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["status", "explanation", "anchors", "left_out"],
        "additionalProperties": False,
    },
}
assert set(TEXT_FORMAT["schema"]["properties"]) == set(OracleAnswer.model_fields) - {"schema_version"}

TOOL_SCHEMA = {
    "type": "function",
    "name": "ask_oracle",
    "description": (
        "Ask for a plain explanation of something from beyond your own time. "
        f"You may ask {ORACLE.requests_per_turn} times this turn."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "concept": {"type": "string", "description": "The thing you want explained"},
            "where_encountered": {
                "type": "string",
                "description": "Where you met it, in your own words",
            },
        },
        "required": ["concept", "where_encountered"],
        "additionalProperties": False,
    },
    "strict": True,
}


def distance_phrase(distance: int) -> str:
    return f"{distance} step{'' if distance == 1 else 's'} beyond what they know"


def _contains(small, big):
    n = len(small)
    return any(big[i:i + n] == small for i in range(len(big) - n + 1))


def lookup(concept, compiled, senses):
    """Where the concept sits on the figure's Horizon. Deterministic; no model.

    senses: sense_id -> Sense, from the lineage files (for labels and summaries).
    """
    def sense_view(sense_id):
        return {"sense_id": sense_id, "label": senses[sense_id].label,
                "summary": senses[sense_id].summary} if sense_id else None

    records = {r["lineage_id"]: r for r in compiled["lineages"]}
    hits = horizon.find_breaches(concept, compiled)
    if hits:
        hit = sorted(hits, key=lambda h: (-len(h["stems"]), h["start_token"]))[0]
        candidates = []  # (rank, lineage_id, list position, kind, sense_id, distance)
        for lineage_id in hit["lineages"]:
            rec = records[lineage_id]
            for kind in ("beyond", "unreached"):
                for pos, item in enumerate(rec[kind]):
                    if any(list(horizon.term_stems(t)) == hit["stems"] for t in item["terms"]):
                        distance = item["bridge_distance"] if kind == "beyond" else "unreached"
                        rank = distance if kind == "beyond" else float("inf")
                        candidates.append((rank, lineage_id, pos, kind, item["sense_id"], distance))
        _, lineage_id, _, kind, target, distance = min(candidates)
        asker = records[lineage_id]["available_sense"]
        return {"kind": kind, "lineage_id": lineage_id,
                "asker_sense": sense_view(asker["sense_id"] if asker else None),
                "target_sense": sense_view(target), "bridge_distance": distance, "hits": hits}

    stems = list(horizon.term_stems(concept))
    his = [e for e in compiled["available_stems"] if stems and _contains(e["stems"], stems)]
    if his:
        entry = sorted(his, key=lambda e: (-len(e["stems"]), e["stems"]))[0]
        lineage_id = entry["lineages"][0]
        asker = records[lineage_id]["available_sense"]
        return {"kind": "his", "lineage_id": lineage_id,
                "asker_sense": sense_view(asker["sense_id"] if asker else None),
                "target_sense": None, "bridge_distance": None, "hits": [],
                "his_match": {"stems": entry["stems"], "terms": entry["terms"]}}
    return {"kind": "unmapped", "lineage_id": None, "asker_sense": None, "target_sense": None,
            "bridge_distance": None, "hits": []}


def identity_stems(manifest, figure_id) -> set[str]:
    """Stems of the figure's name: the Manifest author and the parts of figure_id."""
    words = f"{manifest['author']} {figure_id.replace('_', ' ')}"
    return {stem for _, stem in analyse(words)}


def compose(epoch, concept, look, where):
    """The Oracle's whole input: instructions from prompts/oracle.md, and the concept."""
    lines = []
    if look["kind"] in ("beyond", "unreached"):
        target, asker = look["target_sense"], look["asker_sense"]
        if asker:
            lines.append(ASKER_LINE.format(label=asker["label"], summary=asker["summary"]))
        if look["kind"] == "beyond":
            lines.append(BEYOND_LINES.format(
                label=target["label"], summary=target["summary"],
                distance_phrase=distance_phrase(look["bridge_distance"])))
        else:
            lines.append(UNREACHED_LINE.format(label=target["label"], summary=target["summary"]))
    elif look["kind"] == "unmapped":
        lines.append(UNMAPPED_LINE)
    instructions = PROMPT.read_text(encoding="utf-8").format(
        oracle_epoch=epoch, asker_sense_block="\n".join(lines), concept=concept,
        where_encountered=where)
    return {"instructions": instructions, "input": [{"role": "user", "content": concept}]}


def redact(text, name_stems):
    """Replace each word whose stem is a name stem with [name]. Returns (text, changed)."""
    def swap(match):
        stems = {stem for _, stem in analyse(match.group())}
        return REDACTION if stems & name_stems else match.group()
    redacted = _WORD.sub(swap, text)
    return redacted, redacted != text


def load_context(figure_id):
    """Everything an Oracle binding needs for one figure. Refuses a stale compiled Horizon."""
    root = horizon.HORIZONS_DIR
    stale = horizon.check(root, figure_id)
    if stale:
        raise RuntimeError(f"compiled Horizon for {figure_id} is stale: {stale}")
    compiled = json.loads(horizon.compiled_path(root, figure_id).read_text(encoding="utf-8"))
    _, lineages, profile, _ = horizon.load(root, figure_id)
    manifest = json.loads((ROOT / "corpora" / figure_id / "manifest.json").read_text(encoding="utf-8"))
    return {"compiled": compiled, "profile": profile,
            "senses": {s.sense_id: s for lin in lineages for s in lin.senses},
            "name_stems": identity_stems(manifest, figure_id)}


def prepare(concept, where_encountered, ctx):
    """Lookup, truncation, identity flag, redaction, composition and the guarantee. No I/O."""
    look = lookup(concept, ctx["compiled"], ctx["senses"])
    cap = ORACLE.where_encountered_max_chars
    where, truncated = where_encountered[:cap], len(where_encountered) > cap
    names = ctx["name_stems"]
    # The figure's own words: flagged, and name tokens redacted in what is sent.
    flagged = sorted({stem for _, stem in analyse(f"{concept} {where}")} & names)
    sent_concept, concept_changed = redact(concept, names)
    sent_where, where_changed = redact(where, names)
    composed = compose(ctx["profile"].oracle_epoch, sent_concept, look, sent_where)
    # Our guarantee: after redaction, nothing that is sent carries the figure's name.
    sent_stems = {stem for _, stem in analyse(
        composed["instructions"] + " " + " ".join(i["content"] for i in composed["input"]))}
    leaked = sorted(sent_stems & names)
    if leaked:
        raise RuntimeError(f"composed Oracle input carries identity stems {leaked}")
    return {"lookup": look, "where_encountered": where, "truncated": truncated,
            "identity_terms_in_request": flagged, "redacted": concept_changed or where_changed,
            "composed": composed}


def parse_answer(message_texts):
    valid = []
    for text in message_texts:
        try:
            valid.append(OracleAnswer.model_validate_json(text))
        except ValidationError:
            pass
    if len(valid) != 1:
        raise ValueError(f"{len(valid)} of {len(message_texts)} message item(s) validated; "
                         "exactly 1 required")
    return valid[0], len(message_texts) - 1


ROLE = "oracle"  # the seat; the lane says which figure asked (Decisions K9)


def bind_oracle(figure_id, lane, ctx=None):
    """(tool_schema, async handler, state) for one figure's turn, recorded in its lane.

    Budget lives here only. ctx: an already-loaded load_context(figure_id) (a run loads it in a
    worker thread); loaded here when not given. Each request record keeps `returned`, exactly
    what the figure received.
    """
    if ctx is None:
        ctx = load_context(figure_id)
    requests = []

    async def ask_oracle(concept, where_encountered):
        number = len(requests) + 1
        used = sum(r["outcome"] != "refused" for r in requests)
        limit = ORACLE.requests_per_turn
        if used >= limit:
            reason = f"oracle budget exhausted ({used}/{limit})"
            lane.emit("oracle_request_refused", ROLE, {
                "number": number, "concept": concept, "reason": reason, "requests_used": used})
            returned = {"error": reason}
            requests.append({"number": number, "concept": concept, "outcome": "refused",
                             "reason": reason, "returned": returned})
            return returned

        prep = prepare(concept, where_encountered, ctx)
        composed, look = prep["composed"], prep["lookup"]
        stems = list(horizon.term_stems(concept))
        repeat_of = next((r["number"] for r in requests if r["outcome"] != "refused"
                          and r["stems"] == stems), None)

        record = {"number": number, "concept": concept, "stems": stems, "lookup": look,
                  "where_encountered": prep["where_encountered"], "truncated": prep["truncated"],
                  "identity_terms_in_request": prep["identity_terms_in_request"],
                  "redacted": prep["redacted"], "repeat_of": repeat_of}
        # Evidence first, then the event that names it. No `await` between these two.
        input_file = lane.write_raw(f"{ROLE}-request{number}-input", composed)
        lane.emit("oracle_request", ROLE, {
            **{k: record[k] for k in ("number", "concept", "where_encountered", "truncated",
                                      "lookup", "identity_terms_in_request", "redacted",
                                      "repeat_of")},
            "identity_guarantee_held": True, "requests_used": used + 1, "input_file": input_file})
        record["input_file"] = input_file

        result = None
        try:
            result = await call_model(role="oracle", instructions=composed["instructions"],
                                      input_items=composed["input"], tools=[], handlers={},
                                      trace=lane, max_round_trips=MAX_ROUND_TRIPS,
                                      text_format=TEXT_FORMAT)
            answer, extra = parse_answer(result.message_texts)
        except Exception as error:  # the figure continues; it must record the unresolved concept
            lane.emit("oracle_failed", ROLE, {
                "number": number, "concept": concept, "error": repr(error),
                "message_texts": result.message_texts if result else None})
            returned = {"error": "the Oracle is unavailable"}
            requests.append({**record, "outcome": "failed", "error": repr(error),
                             "returned": returned})
            return returned

        lane.emit("oracle_bridge", ROLE, {
            "number": number, "answer": answer.model_dump(), "extra_message_items": extra,
            "cost_usd": result.cost_usd})
        returned = {"status": answer.status, "explanation": answer.explanation,
                    "anchors": list(answer.anchors), "left_out": list(answer.left_out),
                    "requests_left": limit - (used + 1)}
        requests.append({**record, "outcome": answer.status, "answer": answer.model_dump(),
                         "cost_usd": result.cost_usd, "returned": returned})
        return returned

    def state():
        return copy.deepcopy(requests)

    return TOOL_SCHEMA, ask_oracle, state
