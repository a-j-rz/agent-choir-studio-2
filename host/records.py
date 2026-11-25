"""The Host's records (System §3; Topology & Steering §1–3, §8).

TriageOutput is call 1's output, validated against TEXT_FORMAT; our code adds schema_version
(the model is never asked to echo a constant). ChoirInput is what crosses to the Choir.
HostDecisionRecord is what the Host decided and why, for the trace and the user only.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

Outcome = Literal["answer_directly", "clarify", "reframe_or_reject", "proceed"]


class FactualGap(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gap: str
    kind: Literal["user_can_supply", "needs_research", "unknowable"]


class TriageOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"  # added by our code; the model never writes it
    outcome: Outcome
    reason: str
    direct_answer: str | None  # answer_directly
    clarifying_question: str | None  # clarify
    explanation: str | None  # reframe_or_reject
    suggested_question: str | None  # reframe_or_reject, optional
    canonical_question: str | None  # proceed
    answer_criterion: str | None  # proceed
    factual_posture: Literal["normative", "quantitative", "mixed"] | None  # proceed
    factual_gaps: list[FactualGap]  # proceed; may be empty


_NULLABLE = {"type": ["string", "null"]}

# Hand-written so it can be read. Strict mode: every field required (nullable where it does not
# belong to the outcome), no extra properties. Which fields are filled is checked in code.
TEXT_FORMAT = {
    "type": "json_schema",
    "name": "host_triage",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "outcome": {"type": "string",
                        "enum": ["answer_directly", "clarify", "reframe_or_reject", "proceed"]},
            "reason": {"type": "string"},
            "direct_answer": _NULLABLE,
            "clarifying_question": _NULLABLE,
            "explanation": _NULLABLE,
            "suggested_question": _NULLABLE,
            "canonical_question": _NULLABLE,
            "answer_criterion": _NULLABLE,
            "factual_posture": {"type": ["string", "null"],
                                "enum": ["normative", "quantitative", "mixed", None]},
            "factual_gaps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "gap": {"type": "string"},
                        "kind": {"type": "string",
                                 "enum": ["user_can_supply", "needs_research", "unknowable"]},
                    },
                    "required": ["gap", "kind"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["outcome", "reason", "direct_answer", "clarifying_question", "explanation",
                     "suggested_question", "canonical_question", "answer_criterion",
                     "factual_posture", "factual_gaps"],
        "additionalProperties": False,
    },
}

# The schema and the classes must not drift apart: checked at import.
_schema = TEXT_FORMAT["schema"]
assert set(_schema["properties"]) == set(TriageOutput.model_fields) - {"schema_version"}
assert set(_schema["required"]) == set(_schema["properties"])
_gap = _schema["properties"]["factual_gaps"]["items"]
assert set(_gap["properties"]) == set(_gap["required"]) == set(FactualGap.model_fields)
assert _schema["properties"]["outcome"]["enum"] == list(Outcome.__args__)
assert _gap["properties"]["kind"]["enum"] == list(FactualGap.model_fields["kind"].annotation.__args__)


class ChoirInput(BaseModel):
    """Everything a figure is given about the question. The only type Phase 5 hands a figure.

    It carries the canonical question and, from Phase 7, the frozen fact pack — nothing else.
    It must never carry (Topology & Steering §3): the original wording, the clarification
    exchange, the user's own view, archetype labels, complexity scores or rationale, cast
    rationale, or near-miss candidates. Those stay in HostDecisionRecord and the trace.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    canonical_question: str
    fact_pack: None = None  # stays None until the Researcher exists (Phase 7)


class HostDecisionRecord(BaseModel):
    """What the Host decided and on what input. Trace and user only; never reaches the Choir.

    4b and 4c extend it and bump schema_version.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    original_question: str  # verbatim
    prompt_sha256: dict[str, str]  # {"triage": ...}
    triage: TriageOutput
    research_needed: bool | None  # derived in code on proceed; None otherwise
    researcher_status: Literal["not_built"] | None  # "not_built" when research_needed
