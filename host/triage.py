"""Host call 1: triage and framing, as a run body (System §3; Topology & Steering §1, §3, §8).

The model sees the original question, verbatim, and nothing else. It judges; code enforces:

    load prompt (tripwire on the prompt itself) → call → parse (H4: exactly one item validates)
    → consistency (exactly the fields for the outcome) → on proceed, tripwire on the canonical
    question → derive research_needed → ChoirInput (proceed only) → HostDecisionRecord

Every outcome completes the run; a deflection is not a failure. Malformed or inconsistent
output, or a tripped guard, emits an event naming the rule and fails the run. Never repaired.
"""

from pathlib import Path
import hashlib
import re
from typing import Any

from pydantic import ValidationError

from core.config import role_config
from core.llm import call_model
from core.trace import RunTrace
from host.records import TEXT_FORMAT, ChoirInput, HostDecisionRecord, TriageOutput

ROOT = Path(__file__).resolve().parent.parent
PROMPT = ROOT / "prompts" / "host_triage.md"
MAX_ROUND_TRIPS = 1  # no tools: one round trip is the whole call, so cost is bounded

# Host vocabulary that must not leak into the canonical question (or the prompt). Phrases only:
# single words such as "economic" are deliberately absent.
ARCHETYPES = ["Moral / Ethical", "Strategic / Competitive", "Political / Institutional",
              "Economic / Systemic", "Psychological / Interpersonal", "Scientific / Epistemic",
              "Personal / Existential", "Social / Cultural"]
DIMENSIONS = ["value conflict", "interpretive ambiguity", "cross-domain interaction",
              "challenge value", "consequence / stakes"]
HOST_TERMS = ["archetype", "topology", "token-ring", "hub-and-spoke", "complexity score"]
TRIPWIRE_PHRASES = ARCHETYPES + DIMENSIONS + HOST_TERMS

# Fields that belong to each outcome. All others must be null (and gaps empty, posture null).
PAYLOAD_FIELDS = ["direct_answer", "clarifying_question", "explanation", "suggested_question",
                  "canonical_question", "answer_criterion"]
REQUIRED = {
    "answer_directly": ["direct_answer"],
    "clarify": ["clarifying_question"],
    "reframe_or_reject": ["explanation"],
    "proceed": ["canonical_question", "answer_criterion"],
}
OPTIONAL = {"reframe_or_reject": ["suggested_question"]}


class HostTriageInvalid(Exception):
    """Call 1's output failed parsing (H4) or the consistency check."""


class HostGuardTripped(Exception):
    """A tripwire phrase appeared in text where it must not."""


def normalise(text: str) -> str:
    """Lower case, whitespace collapsed, spaces around '/' removed, a hyphen read as a space.

    So "Moral / Ethical" == "moral/ethical", and "token-ring" == "token - ring" == "token ring".
    """
    text = re.sub(r"\s+", " ", text.lower())
    text = re.sub(r" ?/ ?", "/", text)
    return re.sub(r" ?- ?", " ", text)


def tripwire_hits(text: str, original: str = "") -> list[str]:
    """Phrases in `text` that are not in `original`. Plain substring match after normalise()."""
    text, original = normalise(text), normalise(original)
    return [p for p in TRIPWIRE_PHRASES if normalise(p) in text and normalise(p) not in original]


def load_prompt(path: Path = PROMPT) -> tuple[str, str]:
    """The prompt text and its SHA-256. Fails loudly, naming each tripwire phrase it contains."""
    text = path.read_text(encoding="utf-8")
    hits = tripwire_hits(text)
    if hits:
        raise HostGuardTripped(f"prompt {path.name} contains tripwire phrase(s): {hits}")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_triage(message_texts: list[str]) -> tuple[TriageOutput, int]:
    """H4: exactly one message item must validate. Returns (output, extra message items).

    On failure the exception carries (rule, per-item errors: the error, or None if it validated).
    """
    valid, errors = [], []
    for text in message_texts:
        try:
            valid.append(TriageOutput.model_validate_json(text))
            errors.append(None)
        except ValidationError as error:
            errors.append(str(error))
    if len(valid) != 1:
        raise HostTriageInvalid(
            f"H4: {len(valid)} of {len(message_texts)} message item(s) validated; exactly 1 "
            "required", errors)
    return valid[0], len(message_texts) - 1


def _filled(value: str | None) -> bool:
    return value is not None and value.strip() != ""


def check_consistency(out: TriageOutput) -> list[str]:
    """Each rule broken, in words. Empty means consistent."""
    broken = []
    if not _filled(out.reason):
        broken.append("reason must be non-empty")
    required, optional = REQUIRED[out.outcome], OPTIONAL.get(out.outcome, [])
    for field in PAYLOAD_FIELDS:
        value = getattr(out, field)
        if field in required and not _filled(value):
            broken.append(f"{out.outcome}: {field} must be non-empty")
        elif field in optional and value is not None and not _filled(value):
            broken.append(f"{out.outcome}: {field} must be null or non-empty")
        elif field not in required + optional and value is not None:
            broken.append(f"{out.outcome}: {field} must be null")
    if out.outcome == "proceed":
        if out.factual_posture is None:
            broken.append("proceed: factual_posture must be non-null")
    else:
        if out.factual_posture is not None:
            broken.append(f"{out.outcome}: factual_posture must be null")
        if out.factual_gaps:
            broken.append(f"{out.outcome}: factual_gaps must be empty")
    return broken


def host_outcome(out: TriageOutput) -> str:
    if out.outcome == "reframe_or_reject":
        return "reframed" if out.suggested_question is not None else "rejected"
    return {"answer_directly": "answered_directly", "clarify": "awaiting_clarification",
            "proceed": "framed"}[out.outcome]


async def triage(trace: RunTrace, question: str) -> dict[str, Any]:
    """The run body for call 1. Returns the outcome and, for answer_directly, the answer."""
    prompt, sha = load_prompt()
    trace.annotate("host_prompt_sha256", {"triage": sha})
    trace.emit("host_bound", "host", {
        "prompt_file": str(PROMPT.relative_to(ROOT)), "prompt_sha256": sha,
        "role_config": role_config("host").model_dump(), "max_round_trips": MAX_ROUND_TRIPS})

    result = await call_model(
        role="host",
        instructions=prompt,
        input_items=[{"role": "user", "content": question}],
        tools=[],
        handlers={},
        trace=trace,
        max_round_trips=MAX_ROUND_TRIPS,
        text_format=TEXT_FORMAT,
    )

    try:
        out, extra_items = parse_triage(result.message_texts)
    except HostTriageInvalid as error:
        trace.emit("host_triage_invalid", "host", {
            "rule": error.args[0], "errors": error.args[1],
            "message_texts": result.message_texts, "stop_reason": result.stop_reason})
        raise

    broken = check_consistency(out)
    if broken:
        trace.emit("host_triage_invalid", "host", {
            "rule": "consistency", "broken": broken, "triage": out.model_dump()})
        raise HostTriageInvalid(f"inconsistent triage output: {broken}")
    trace.emit("host_triage", "host", {
        "triage": out.model_dump(), "consistency": {"consistent": True, "broken": []},
        "extra_message_items": extra_items, "stop_reason": result.stop_reason})

    choir_input = None
    if out.outcome == "proceed":
        hits = tripwire_hits(out.canonical_question, original=question)
        if hits:
            trace.emit("host_guard_tripped", "host", {
                "guard": "canonical_question", "phrases": hits,
                "canonical_question": out.canonical_question})
            raise HostGuardTripped(f"canonical question introduces Host vocabulary: {hits}")
        choir_input = ChoirInput(canonical_question=out.canonical_question)

    research_needed = (any(g.kind == "needs_research" for g in out.factual_gaps)
                       if out.outcome == "proceed" else None)
    record = HostDecisionRecord(
        original_question=question, prompt_sha256={"triage": sha}, triage=out,
        research_needed=research_needed,
        researcher_status="not_built" if research_needed else None)

    if choir_input is not None:
        trace.emit("choir_input", "host", choir_input.model_dump())
    trace.emit("host_decision_record", "host", record.model_dump())

    outcome = host_outcome(out)
    trace.annotate("host_outcome", outcome)
    returned = {"host_outcome": outcome}
    if out.outcome == "answer_directly":
        returned["answer"] = out.direct_answer
    return returned
