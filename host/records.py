"""The Host's records (System §3; Topology & Steering §1–3, §8).

TriageOutput is call 1's output, validated against TEXT_FORMAT; ClassificationOutput is call 2's,
validated against SCORE_TEXT_FORMAT; CastOutput is call 3's, validated against CAST_TEXT_FORMAT.
Our code adds schema_version (the model is never asked to echo a constant). Scoring and CastRecord
are computed by code; the model never sees them.
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


# ---------------------------------------------------------------- call 3: cast assessment and selection

Rating = Literal["strong", "adequate", "weak"]
CorpusRating = Literal["strong", "adequate", "weak", "unassessable"]


class Judged(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str  # first: the rating follows its reason
    rating: Rating


class CorpusJudged(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str
    rating: CorpusRating  # unassessable if and only if the corpus is not built: checked in code


class CandidateAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    figure_id: str
    archetype_relevance: Judged
    question_fit: Judged
    corpus_suitability: CorpusJudged


class NearMiss(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    figure_id: str
    reason: str


class CastOutput(BaseModel):
    """Field order is generation order: every candidate is assessed before any is selected."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"  # added by our code; the model never writes it
    candidate_assessments: list[CandidateAssessment]
    selected: list[str]
    panel_diversity: str
    panel_redundancy: str
    panel_tension: str
    near_misses: list[NearMiss]


def _judged_schema(ratings: list[str]) -> dict:
    return {"type": "object",
            "properties": {"reason": {"type": "string"},
                           "rating": {"type": "string", "enum": ratings}},
            "required": ["reason", "rating"], "additionalProperties": False}


# Hand-written so it can be read. figure_id is a plain string, not an enum of the roster: which
# ids are allowed is checked in code, so the schema does not change when the roster does.
CAST_TEXT_FORMAT = {
    "type": "json_schema",
    "name": "host_cast",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "candidate_assessments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "figure_id": {"type": "string"},
                        "archetype_relevance": _judged_schema(list(Rating.__args__)),
                        "question_fit": _judged_schema(list(Rating.__args__)),
                        "corpus_suitability": _judged_schema(list(CorpusRating.__args__)),
                    },
                    "required": ["figure_id", "archetype_relevance", "question_fit",
                                 "corpus_suitability"],
                    "additionalProperties": False,
                },
            },
            "selected": {"type": "array", "items": {"type": "string"}},
            "panel_diversity": {"type": "string"},
            "panel_redundancy": {"type": "string"},
            "panel_tension": {"type": "string"},
            "near_misses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"figure_id": {"type": "string"}, "reason": {"type": "string"}},
                    "required": ["figure_id", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["candidate_assessments", "selected", "panel_diversity", "panel_redundancy",
                     "panel_tension", "near_misses"],
        "additionalProperties": False,
    },
}

# The schema and the classes must not drift apart, in membership and in order: checked at import.
_cast = CAST_TEXT_FORMAT["schema"]
assert list(_cast["properties"]) == [f for f in CastOutput.model_fields if f != "schema_version"]
assert _cast["required"] == list(_cast["properties"])
_cand = _cast["properties"]["candidate_assessments"]["items"]
assert list(_cand["properties"]) == _cand["required"] == list(CandidateAssessment.model_fields)
for _name, _cls in (("archetype_relevance", Judged), ("question_fit", Judged),
                    ("corpus_suitability", CorpusJudged)):
    _j = _cand["properties"][_name]
    assert list(_j["properties"]) == _j["required"] == list(_cls.model_fields) == ["reason", "rating"]
    assert _j["properties"]["rating"]["enum"] == list(_cls.model_fields["rating"].annotation.__args__)
_near = _cast["properties"]["near_misses"]["items"]
assert list(_near["properties"]) == _near["required"] == list(NearMiss.model_fields)


class CastRecord(BaseModel):
    """Call 3's output plus what code derives from it. Trace and user only; never the Choir."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    output: CastOutput
    would_reject: list[str]  # selected figures whose corpus suitability is weak
    gate_unassessable: list[str]  # selected figures whose corpus suitability is unassessable
    gate_not_applied: str | None  # "roster exhausted" if either list is non-empty
    near_miss_note: str | None  # set when the roster minus the cast is empty


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

    2: classification and scoring (4b). 3: cast (4c).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["3"] = "3"
    original_question: str  # verbatim
    prompt_sha256: dict[str, str]  # {"triage": ...}, plus "score" and "cast" when they ran
    triage: TriageOutput
    research_needed: bool | None  # derived in code on proceed; None otherwise
    researcher_status: Literal["not_built"] | None  # "not_built" when research_needed
    classification: ClassificationOutput | None  # call 2; None unless call 1 returned proceed
    scoring: Scoring | None  # computed from classification; None unless call 1 returned proceed
    cast: CastRecord | None  # call 3; None unless scored
