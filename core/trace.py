"""RunTrace owns one run's directory: traces/<run_id>/{events.jsonl, raw/, summary.json}."""

import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, get_args

from core.config import config_snapshot
from core.events import SCHEMA_VERSION, Event, utc_iso

TRACES_DIR = Path(__file__).resolve().parent.parent / "traces"

RunStatus = Literal["complete", "failed", "aborted"]


def new_run_id(now: datetime) -> str:
    """Time-sortable and unique: 20261112T151400Z-a3f9 (UTC second + 4 random hex chars)."""
    return now.strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(2)


class RunTrace:
    def __init__(self, root: Path = TRACES_DIR):
        self.started_at = datetime.now(timezone.utc)
        self._started_clock = time.monotonic()  # for duration: immune to wall-clock jumps
        self.run_id = new_run_id(self.started_at)
        # Taken now, not at finish: the trace records the config this run ran with.
        self._config = config_snapshot()
        self.dir = root / self.run_id
        # exist_ok=False: a run_id collision fails loudly rather than mixing two runs.
        (self.dir / "raw").mkdir(parents=True, exist_ok=False)
        self._events_file = (self.dir / "events.jsonl").open("w", encoding="utf-8")
        self._seq = 0
        self._last_type: str | None = None
        self._finished = False

    def emit(
        self,
        type: str,
        role: str,
        payload: dict[str, Any] | None = None,
        round: int | None = None,
    ) -> Event:
        """Record an event durably, then hand it back for the caller to send.

        Write + flush happen before return, so anything the browser sees is already in the trace.
        """
        if self._finished:
            raise RuntimeError(f"run {self.run_id} is finished; cannot emit {type!r}")
        self._seq += 1
        event = Event(
            run_id=self.run_id,
            seq=self._seq,
            ts=utc_iso(),
            type=type,
            role=role,
            round=round,
            payload=payload or {},
        )
        self._events_file.write(event.model_dump_json() + "\n")
        self._events_file.flush()  # out of Python's buffer, into the OS: survives a process crash
        self._last_type = type
        return event

    def write_raw(self, stem: str, data: Any) -> str:
        """Write a raw payload to raw/<seq>-<stem>.json and return the file name.

        <seq> is the seq the *next* emitted event will get: write the evidence, then emit the
        event that names it. Do not `await` between the two, or another coroutine could take
        that seq first.
        """
        if self._finished:
            raise RuntimeError(f"run {self.run_id} is finished; cannot write raw {stem!r}")
        name = f"{self._seq + 1:04d}-{stem}.json"
        (self.dir / "raw" / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return name

    def finish(self, status: RunStatus) -> None:
        """Close events.jsonl and write summary.json. A second call is a no-op."""
        if self._finished:
            return
        if status not in get_args(RunStatus):
            raise ValueError(f"unknown run status {status!r}")
        self._finished = True
        self._events_file.close()
        ended_at = datetime.now(timezone.utc)
        summary = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "status": status,
            "started_at": utc_iso(self.started_at),
            "ended_at": utc_iso(ended_at),
            "duration_s": round(time.monotonic() - self._started_clock, 3),
            "event_count": self._seq,
            "last_event_type": self._last_type,
            "config": self._config,
        }
        (self.dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
