"""One figure turn: the figure searches its own corpus, then returns a cited contribution.

A run body (see core.runner): the work only, no lifecycle events. The citation check after
the turn is set arithmetic over what the tools recorded — no model judges anything here.
"""

from pathlib import Path
from typing import Any

from choir.contribution import TEXT_FORMAT, ContributionInvalid, parse_contribution
from core.config import RETRIEVAL
from core.llm import call_model
from core.trace import RunTrace
from retrieval import hybrid, vectors
from retrieval.tools import bind_corpus_tools

PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "figure_standin.md"
MAX_ROUND_TRIPS = 8


def fill_prompt(manifest: dict[str, Any]) -> str:
    """The stand-in prompt, filled from the Manifest and RETRIEVAL. Missing keys raise."""
    return PROMPT.read_text(encoding="utf-8").format(
        author=manifest["author"],
        works=", ".join(manifest["included_works"]),
        translator=manifest["translation_edition"]["translator"],
        searches=RETRIEVAL.searches_per_turn,
        opens=RETRIEVAL.opens_per_turn,
    )


def citation_check(contribution, state, figure, extra_items: int) -> dict[str, Any]:
    """What was cited vs opened vs surfaced. Lists in corpus order; unknown ids last."""
    position = figure["position"]
    cited = list(dict.fromkeys(c.passage_id for c in contribution.citations))
    opened = list(dict.fromkeys(o["passage_id"] for o in state["opens"]))
    sources = state["surfaced_sources"]

    def ordered(ids):
        ids = set(ids)
        known = sorted((i for i in ids if i in position), key=position.__getitem__)
        return known + [i for i in cited if i in ids and i not in position]

    return {
        "cited": ordered(cited),
        "cited_not_opened": ordered(set(cited) - set(opened)),
        "opened_not_cited": ordered(set(opened) - set(cited)),
        "opened_not_surfaced": ordered(set(opened) - set(sources)),
        "cited_unknown_ids": [i for i in cited if i not in position],
        "cited_sources": {i: sources.get(i, []) for i in ordered(cited)},
        # Only the vector path ever surfaced it this turn: lexical search never did.
        "cited_semantic_only": ordered(i for i in cited if sources.get(i) == ["semantic_only"]),
        "extra_message_items": extra_items,
    }


async def figure_turn(
    trace: RunTrace,
    figure_id: str,
    question: str,
    model=None,
    max_round_trips: int = MAX_ROUND_TRIPS,
) -> dict[str, Any]:
    # Synchronous loads (about half a second). Fine for the CLI; the server will want them
    # off the event loop when it runs figures.
    if model is None:
        model, _ = vectors.load_model()  # offline: the pinned model must already be cached
    figure = hybrid.load_figure(figure_id, model)
    schemas, handlers, turn_state = bind_corpus_tools(figure, model, trace, role=figure_id)
    trace.emit("figure_bound", figure_id, {
        "figure_id": figure_id, "chunks": len(figure["chunks"]),
        "chunks_sha256": figure["vectors"]["meta"]["chunks_sha256"],
        "vector_cache": figure["cache"]["status"],
        "tools": [s["name"] for s in schemas],
        "budgets": {"searches": RETRIEVAL.searches_per_turn, "opens": RETRIEVAL.opens_per_turn}})

    result = await call_model(
        role="figure",
        instructions=fill_prompt(figure["manifest"]),
        input_items=[{"role": "user", "content": question}],
        tools=schemas,
        handlers=handlers,
        trace=trace,
        max_round_trips=max_round_trips,
        text_format=TEXT_FORMAT,
    )

    try:
        contribution, extra_items = parse_contribution(result.message_texts)
    except ContributionInvalid as error:
        trace.emit("contribution_invalid", figure_id, {
            "reason": error.reason, "stop_reason": result.stop_reason,
            "message_texts": result.message_texts, "errors": error.errors})
        raise

    check = citation_check(contribution, turn_state(), figure, extra_items)
    trace.emit("contribution", figure_id, {
        "contribution": contribution.model_dump(), "stop_reason": result.stop_reason})
    trace.emit("citation_check", figure_id, check)
    return {
        "figure_id": figure_id, "question": question, "status": contribution.status,
        "stop_reason": result.stop_reason, "round_trips": result.round_trips,
        "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
        "reasoning_tokens": result.reasoning_tokens, "cost_usd": result.cost_usd,
    }
