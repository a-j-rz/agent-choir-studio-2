"""Smoke check: one traced tool loop end to end, against the live API. Costs a fraction of a cent.

    python -m scripts.llm_smoke                      # normal run: ~2 model calls
    python -m scripts.llm_smoke --max-round-trips 1  # cap run: 1 model call

Prints the trace directory. Read events.jsonl, raw/ and summary.json there.
"""

import argparse
import asyncio
from pathlib import Path

from core.llm import call_model
from core.trace import RunStatus, RunTrace

# Invented placeholder passages, clearly fake. Not real texts; real corpora arrive in Phase 2.
FAKE_CORPUS = {
    "fake-1": "FAKE PASSAGE: The mind is the one territory a person fully governs.",
    "fake-2": "FAKE PASSAGE: Outside events arrive unbidden; judgement about them is ours.",
    "fake-3": "FAKE PASSAGE: The harbour was quiet and the ships were late.",
}

TOOLS = [
    {
        "type": "function",
        "name": "search_my_corpus",
        "description": "Search your own corpus. Returns matching passages with ids.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Words to search for"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "strict": True,
    }
]


def search_my_corpus(query: str) -> list[dict]:
    words = {w.strip(".,;:").lower() for w in query.split()}
    return [
        {"passage_id": pid, "text": text}
        for pid, text in FAKE_CORPUS.items()
        if words & {w.strip(".,;:").lower() for w in text.split()}
    ]


async def main(max_round_trips: int) -> None:
    trace = RunTrace()
    status: RunStatus = "aborted"  # guilty until proven, as in app.py
    try:
        trace.emit("run_started", "system", {"note": "llm smoke check", "max_round_trips": max_round_trips})
        result = await call_model(
            role="figure",
            instructions="Answer only from passages returned by search_my_corpus. Cite passage ids.",
            input_items=[
                {
                    "role": "user",
                    "content": "What does your corpus say about governing one's own mind? Cite passage ids.",
                }
            ],
            tools=TOOLS,
            handlers={"search_my_corpus": search_my_corpus},
            trace=trace,
            max_round_trips=max_round_trips,
        )
        trace.emit("run_complete", "system", result.model_dump())
        status = "complete"
    except Exception as exc:
        status = "failed"
        trace.emit("run_failed", "system", {"error": repr(exc)})
        raise
    finally:
        # Synchronous only. Ctrl-C (KeyboardInterrupt) is not an Exception, so it lands here as aborted.
        if status == "aborted":
            trace.emit("run_aborted", "system", {"reason": "interrupted"})
        trace.finish(status)
        print(f"trace ({status}): {trace.dir.relative_to(Path.cwd())}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-round-trips", type=int, default=8)
    args = parser.parse_args()
    asyncio.run(main(args.max_round_trips))
