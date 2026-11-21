"""A figure's structured contribution (CHOIR_AND_CORPUS §7; Decisions D2).

The model writes JSON against TEXT_FORMAT; we validate it into Contribution, which adds
schema_version itself (the model is never asked to echo a constant). Parsing never repairs
and never guesses: exactly one message item must validate, or the turn fails.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    passage_id: str
    supports: str  # what this passage supports in the contribution


class Contribution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    status: Literal["grounded", "insufficient_corpus_basis"]
    position: str
    reasoning: str
    citations: list[Citation]
    extrapolation: list[str]  # reasoning beyond what the opened passages say; may be empty


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
        },
        "required": ["status", "position", "reasoning", "citations", "extrapolation"],
        "additionalProperties": False,
    },
}

# The schema and the classes must not drift apart: checked at import.
_schema = TEXT_FORMAT["schema"]
assert set(_schema["properties"]) == set(Contribution.model_fields) - {"schema_version"}
assert set(_schema["required"]) == set(_schema["properties"])
_citation = _schema["properties"]["citations"]["items"]
assert set(_citation["properties"]) == set(_citation["required"]) == set(Citation.model_fields)


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
