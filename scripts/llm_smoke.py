"""Smoke check: one traced tool loop end to end, against the live API. Costs a fraction of a cent.

    python -m scripts.llm_smoke                      # normal run: ~2 model calls
    python -m scripts.llm_smoke --max-round-trips 1  # cap run: 1 model call

Runs the shared demo (demo/live_demo.py) on the shared runner (core/runner.py), and prints each
event as it happens: the same relay the browser reads, rendered for a terminal. This script holds
no run lifecycle and no corpus of its own. Read events.jsonl, raw/ and summary.json in the trace
directory it prints.
"""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from core.events import Event
from core.runner import relay
from core.trace import TRACES_DIR
from demo.live_demo import MAX_ROUND_TRIPS, editor_demo


def line(event: Event) -> str:
    """One terminal line per event: receive time, then the event's own seq, ts, type and role."""
    p = event.payload
    if event.type == "round_trip":
        detail = (
            f"trip {p['trip']} · {p['latency_s']}s · in {p['input_tokens']} (cached {p['cached_input_tokens']},"
            f" write {p['cache_write_tokens']}) / out {p['output_tokens']} (reasoning {p['reasoning_tokens']})"
            f" · ${p['est_cost_usd']:.8f}"
        )
    elif event.type == "tool_result":
        detail = f"{p['name']} → {json.dumps(p['result'])}"
    else:
        detail = json.dumps(p)
    received = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
    return f"{received}  #{event.seq} {event.ts}  {event.type:<22} {event.role:<7} {detail}"


async def main(max_round_trips: int) -> None:
    body = partial(editor_demo, max_round_trips=max_round_trips)
    last: Event | None = None
    async for event in relay(body, f"llm smoke check (max_round_trips={max_round_trips})", render=lambda e: e):
        print(line(event), flush=True)
        last = event
    if last is not None:
        print(f"trace: {(TRACES_DIR / last.run_id).relative_to(Path.cwd())}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-round-trips", type=int, default=MAX_ROUND_TRIPS)
    args = parser.parse_args()
    asyncio.run(main(args.max_round_trips))
