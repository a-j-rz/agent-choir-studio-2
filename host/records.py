"""The Host's records (System §3; Topology & Steering §1–3, §8).

TriageOutput is call 1's output, validated against TEXT_FORMAT; ClassificationOutput is call 2's,
validated against SCORE_TEXT_FORMAT. Our code adds schema_version (the model is never asked to
echo a constant). Scoring is computed by code from call 2's scores; the model never sees it.
ChoirInput is what crosses to the Choir. HostDecisionRecord is what the Host decided and why, for
the trace and the user only.
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


# ---------------------------------------------------------------- call 2: classification and scoring

# Exactly as written in prompts/host_score.md (Topology & Steering §5).
Archetype = Literal["Moral / Ethical", "Strategic / Competitive", "Political / Institutional",
                    "Economic / Systemic", "Psychological / Interpersonal", "Scientific / Epistemic",
                    "Personal / Existential", "Social / Cultural"]
DIMENSIONS = ["value_conflict", "interpretive_ambiguity", "cross_domain_interaction",
              "challenge_value", "consequence_stakes"]


class DimensionScore(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # rationale first: structured output is generated in field order, so the score follows it
    rationale: str
    score: Literal[0, 1, 2]


class ScoredUnit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    depends_on: int | None  # nested only: index of the unit this one depends on
    value_conflict: DimensionScore
    interpretive_ambiguity: DimensionScore
    cross_domain_interaction: DimensionScore
    challenge_value: DimensionScore
    consequence_stakes: DimensionScore


class ClassificationOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"  # added by our code; the model never writes it
    decomposition: Literal["single", "compound", "nested"]
    primary_archetype: Archetype
    secondary_archetypes: list[Archetype]  # at most 2, distinct, not the primary: checked in code
    units: list[ScoredUnit]


_DIMENSION_SCHEMA = {
    "type": "object",
    "properties": {
        "rationale": {"type": "string"},
        "score": {"type": "integer", "enum": [0, 1, 2]},
    },
    "required": ["rationale", "score"],
    "additionalProperties": False,
}
_ARCHETYPE_SCHEMA = {"type": "string", "enum": list(Archetype.__args__)}

# Hand-written so it can be read. No field for a total or a topology: those are code's.
SCORE_TEXT_FORMAT = {
    "type": "json_schema",
    "name": "host_classification",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "decomposition": {"type": "string", "enum": ["single", "compound", "nested"]},
            "primary_archetype": _ARCHETYPE_SCHEMA,
            "secondary_archetypes": {"type": "array", "items": _ARCHETYPE_SCHEMA},
            "units": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "depends_on": {"type": ["integer", "null"]},
                        **{d: _DIMENSION_SCHEMA for d in DIMENSIONS},
                    },
                    "required": ["text", "depends_on", *DIMENSIONS],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["decomposition", "primary_archetype", "secondary_archetypes", "units"],
        "additionalProperties": False,
    },
}

# The schema and the classes must not drift apart: checked at import.
_score = SCORE_TEXT_FORMAT["schema"]
assert set(_score["properties"]) == set(ClassificationOutput.model_fields) - {"schema_version"}
assert set(_score["required"]) == set(_score["properties"])
_unit = _score["properties"]["units"]["items"]
assert set(_unit["properties"]) == set(_unit["required"]) == set(ScoredUnit.model_fields)
assert set(DIMENSIONS) == set(ScoredUnit.model_fields) - {"text", "depends_on"}
assert list(_DIMENSION_SCHEMA["properties"]) == list(DimensionScore.model_fields) == ["rationale", "score"]
assert _DIMENSION_SCHEMA["properties"]["score"]["enum"] == list(
    DimensionScore.model_fields["score"].annotation.__args__)
assert _score["properties"]["decomposition"]["enum"] == list(
    ClassificationOutput.model_fields["decomposition"].annotation.__args__)


class Scoring(BaseModel):
    """Computed by code from ClassificationOutput (Topology & Steering §4, §6). Never by a model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_totals: list[int]
    governing_unit: int  # index of the highest total; ties go to the lowest index
    governing_total: int
    topology: Literal["hub_and_spoke", "token_ring"]
    rule: str  # e.g. "governing total 6 ≥ 5 → token_ring"
    score_status: Literal["final", "provisional_is_final_research_not_run"]


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

    2: classification and scoring (4b). 4c extends it again and bumps schema_version.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["2"] = "2"
    original_question: str  # verbatim
    prompt_sha256: dict[str, str]  # {"triage": ...}, plus "score" when call 2 ran
    triage: TriageOutput
    research_needed: bool | None  # derived in code on proceed; None otherwise
    researcher_status: Literal["not_built"] | None  # "not_built" when research_needed
    classification: ClassificationOutput | None  # call 2; None unless call 1 returned proceed
    scoring: Scoring | None  # computed from classification; None unless call 1 returned proceed
