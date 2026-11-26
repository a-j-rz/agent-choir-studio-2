"""A figure's structured contribution (CHOIR_AND_CORPUS §7; Decisions D2).

The model writes JSON against TEXT_FORMAT; we validate it into Contribution, which adds
schema_version itself (the model is never asked to echo a constant). Parsing never repairs
and never guesses: exactly one message item must validate, or the turn fails.

Schema 2 (Decisions J10, K9): `insufficiency` says what was looked for and not found. It is
present exactly when the status is insufficient_corpus_basis; a contradiction fails parsing.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    passage_id: str
    supports: str  # what this passage supports in the contribution


class Insufficiency(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    looked_for: str  # what the figure searched its writings for
    not_found: str  # what it did not find

    @field_validator("looked_for", "not_found")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value


class Contribution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[2] = 2
    status: Literal["grounded", "insufficient_corpus_basis"]
    position: str
    reasoning: str
    citations: list[Citation]
    extrapolation: list[str]  # reasoning beyond what the opened passages say; may be empty
    insufficiency: Insufficiency | None  # present exactly when status is insufficient_corpus_basis

    @model_validator(mode="after")
    def _insufficiency_iff_insufficient(self):
        insufficient = self.status == "insufficient_corpus_basis"
        if insufficient and self.insufficiency is None:
            raise ValueError("insufficient_corpus_basis requires insufficiency")
        if not insufficient and self.insufficiency is not None:
            raise ValueError(f"insufficiency must be null when status is {self.status}")
        return self


# Hand-written so it can be read. Strict mode: every field required, no extra properties.
TEXT_FORMAT = {
    "type": "json_schema",
    "name": "contribution",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["grounded", "insufficient_corpus_basis"]},
            "position": {"type": "string"},
            "reasoning": {"type": "string"},
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "passage_id": {"type": "string"},
                        "supports": {"type": "string"},
                    },
                    "required": ["passage_id", "supports"],
                    "additionalProperties": False,
                },
            },
            "extrapolation": {"type": "array", "items": {"type": "string"}},
            "insufficiency": {
                "anyOf": [
                    {
                        "type": "object",
                        "properties": {
                            "looked_for": {"type": "string"},
                            "not_found": {"type": "string"},
                        },
                        "required": ["looked_for", "not_found"],
                        "additionalProperties": False,
                    },
                    {"type": "null"},
                ],
            },
        },
        "required": ["status", "position", "reasoning", "citations", "extrapolation",
                     "insufficiency"],
        "additionalProperties": False,
    },
}

# The schema and the classes must not drift apart: checked at import.
_schema = TEXT_FORMAT["schema"]
assert set(_schema["properties"]) == set(Contribution.model_fields) - {"schema_version"}
assert set(_schema["required"]) == set(_schema["properties"])
_citation = _schema["properties"]["citations"]["items"]
assert set(_citation["properties"]) == set(_citation["required"]) == set(Citation.model_fields)
_insufficiency = _schema["properties"]["insufficiency"]["anyOf"][0]
assert set(_insufficiency["properties"]) == set(_insufficiency["required"]) == set(
    Insufficiency.model_fields)


class ContributionInvalid(Exception):
    def __init__(self, reason: str, errors: list[str | None]):
        super().__init__(reason)
        self.reason = reason
        self.errors = errors  # per message item: the validation error, or None if it validated


def parse_contribution(message_texts: list[str]) -> tuple[Contribution, int]:
    """Exactly one item must validate. Returns (contribution, extra message items)."""
    valid, errors = [], []
    for text in message_texts:
        try:
            valid.append(Contribution.model_validate_json(text))
            errors.append(None)
        except ValidationError as error:
            errors.append(str(error))
    if len(valid) != 1:
        raise ContributionInvalid(
            f"{len(valid)} of {len(message_texts)} message item(s) validated; exactly 1 required",
            errors)
    return valid[0], len(message_texts) - 1
