"""The one event shape: a line in events.jsonl and a message on the SSE stream are the same object."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1"


def utc_iso(dt: datetime | None = None) -> str:
    """ISO-8601 UTC with millisecond precision and a 'Z' suffix, e.g. 2026-11-12T15:14:00.123Z."""
    dt = dt or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Event(BaseModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    seq: int  # 1, 2, 3 ... per run, no gaps
    ts: str  # utc_iso()
    type: str  # also the SSE event name
    role: str  # who acted: "system", "host", a figure, ...
    round: int | None = None  # token-ring round; None elsewhere
    payload: dict[str, Any] = Field(default_factory=dict)  # full content, not a UI summary

    def to_sse(self) -> str:
        # model_dump_json() emits a single line (newlines inside strings are escaped as \n),
        # which matters: in SSE a raw newline would end the `data:` field early.
        return f"event: {self.type}\ndata: {self.model_dump_json()}\n\n"
