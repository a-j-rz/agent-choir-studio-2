"""DEMO FIXTURE for GET /stream/live — not part of the runtime core.

One real `call_model()` run as the `editor` role against a three-passage FAKE corpus, so the live
view can be watched end to end. scripts/llm_smoke.py runs it too: this is the only fake corpus.
The passages are invented placeholders, not real texts; real corpora arrive in Phase 2. Costs a
fraction of a cent (~2 model calls).
"""

from typing import Any

from core.llm import call_model
from core.trace import RunTrace

FAKE_CORPUS = {
    "fake-1": "FAKE PASSAGE: The mind is the one territory a person fully governs.",
    "fake-2": "FAKE PASSAGE: Outside events arrive unbidden; judgement about them is ours.",
    "fake-3": "FAKE PASSAGE: The harbour was quiet and the ships were late.",
}

TOOLS = [
    {
        "type": "function",
        "name": "search_demo_corpus",
        "description": "Search a tiny fake demo corpus. Returns matching passages with ids.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Words to search for"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "strict": True,
    }
]

# Bounds the demo's spend: one search trip, one answer trip, one spare.
MAX_ROUND_TRIPS = 3


def search_demo_corpus(query: str) -> list[dict]:
    words = {w.strip(".,;:").lower() for w in query.split()}
    return [
        {"passage_id": pid, "text": text}
        for pid, text in FAKE_CORPUS.items()
        if words & {w.strip(".,;:").lower() for w in text.split()}
    ]


async def editor_demo(trace: RunTrace, max_round_trips: int = MAX_ROUND_TRIPS) -> dict[str, Any]:
    """A run body (see core.runner): the work only, no lifecycle events."""
    result = await call_model(
        role="editor",
        instructions=(
            "Answer only from passages returned by search_demo_corpus. Search once, then answer "
            "in one sentence. Cite passage ids."
        ),
        input_items=[{"role": "user", "content": "What does the corpus say about governing one's own mind?"}],
        tools=TOOLS,
        handlers={"search_demo_corpus": search_demo_corpus},
        trace=trace,
        max_round_trips=max_round_trips,
    )
    return result.model_dump()
