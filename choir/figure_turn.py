"""One figure turn: the figure searches its own corpus, may ask the Oracle, then returns a cited
contribution.

A run body (see core.runner): the work only, no lifecycle events. The citation check and the
Horizon reconciliation after the turn are set arithmetic over what was recorded — no model
judges anything here. `condition` is the 3c prompt experiment: A without, B with, a block
listing what the figure's own world understood where it touches on later things.
"""

from pathlib import Path
import re
from typing import Any, Literal

from choir import oracle
from choir.contribution import TEXT_FORMAT, ContributionInvalid, parse_contribution
from choir.reconcile import reconcile
from core.config import ORACLE, RETRIEVAL
from core.llm import call_model
from core.trace import RunTrace
from epistemic.horizon import find_breaches
from retrieval import hybrid, vectors
from retrieval.tools import bind_corpus_tools

PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "figure_standin.md"
MAX_ROUND_TRIPS = 10
Condition = Literal["A", "B"]


def year_label(year: int) -> str:
    return f"{-year} BCE" if year < 0 else f"{year} CE"


def horizon_block(ctx) -> str:
    """Condition B: one line per lineage with an available sense, in lineage-id order."""
    lines = [f"- {r['available_sense']['label']}: "
             f"{ctx['senses'][r['available_sense']['sense_id']].summary}"
             for r in sorted(ctx["compiled"]["lineages"], key=lambda r: r["lineage_id"])
             if r["available_sense"]]
    return "What your own world understood, where it touches on later things:\n" + "\n".join(lines)


def fill_prompt(manifest: dict[str, Any], ctx, condition: Condition) -> str:
    """The stand-in prompt, filled from the Manifest, profile and config. Missing keys raise.

    Guard: the filled prompt must contain no breach term — it never hands the figure modern
    vocabulary. Raises naming the hits.
    """
    if condition not in ("A", "B"):
        raise ValueError(f"condition must be 'A' or 'B', got {condition!r}")
    lived = ctx["profile"].lived
    text = PROMPT.read_text(encoding="utf-8").format(
        author=manifest["author"],
        works=", ".join(manifest["included_works"]),
        translator=manifest["translation_edition"]["translator"],
        searches=RETRIEVAL.searches_per_turn,
        opens=RETRIEVAL.opens_per_turn,
        born=year_label(lived.born),
        died=year_label(lived.died),
        oracle_requests=ORACLE.requests_per_turn,
        horizon_block=horizon_block(ctx) if condition == "B" else "",
    )
    text = re.sub(r"\n{3,}", "\n\n", text)  # condition A: no empty block left behind
    hits = find_breaches(text, ctx["compiled"])
    if hits:
        raise RuntimeError(f"figure prompt carries breach terms: "
                           f"{[h['matched_surface'] for h in hits]}")
    return text


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
    condition: Condition,
    model=None,
    max_round_trips: int = MAX_ROUND_TRIPS,
) -> dict[str, Any]:
    # Synchronous loads (about half a second). Fine for the CLI; the server will want them
    # off the event loop when it runs figures.
    if model is None:
        model, _ = vectors.load_model()  # offline: the pinned model must already be cached
    figure = hybrid.load_figure(figure_id, model)
    ctx = oracle.load_context(figure_id)
    instructions = fill_prompt(figure["manifest"], ctx, condition)  # guard runs here
    corpus_schemas, corpus_handlers, turn_state = bind_corpus_tools(
        figure, model, trace, role=figure_id)
    oracle_schema, ask_oracle, oracle_state = oracle.bind_oracle(figure_id, trace, figure_id)
    schemas = [*corpus_schemas, oracle_schema]
    handlers = {**corpus_handlers, "ask_oracle": ask_oracle}  # budgets stay independent
    trace.annotate("condition", condition)
    trace.emit("figure_bound", figure_id, {
        "figure_id": figure_id, "condition": condition, "chunks": len(figure["chunks"]),
        "chunks_sha256": figure["vectors"]["meta"]["chunks_sha256"],
        "vector_cache": figure["cache"]["status"],
        "horizon_sha256": ctx["compiled"]["sources_sha256"],
        "tools": [s["name"] for s in schemas],
        "budgets": {"searches": RETRIEVAL.searches_per_turn, "opens": RETRIEVAL.opens_per_turn,
                    "oracle_requests": ORACLE.requests_per_turn}})

    result = await call_model(
        role="figure",
        instructions=instructions,
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

    state, requests = turn_state(), oracle_state()
    chunks = {c["chunk_id"]: c["text"] for c in figure["chunks"]}
    opened = [(pid, chunks[pid]) for pid in dict.fromkeys(o["passage_id"] for o in state["opens"])]
    reconciliation = reconcile(contribution, question, requests, opened, ctx["compiled"])
    trace.emit("horizon_reconciliation", figure_id, {"condition": condition, **reconciliation})

    oracle_cost = round(sum(r.get("cost_usd", 0.0) for r in requests), 8)
    return {
        "figure_id": figure_id, "question": question, "condition": condition,
        "status": contribution.status, "stop_reason": result.stop_reason,
        "round_trips": result.round_trips, "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens, "reasoning_tokens": result.reasoning_tokens,
        "searches_used": len(state["searches"]),
        "oracle_requests_used": sum(r["outcome"] != "refused" for r in requests),
        "figure_cost_usd": result.cost_usd, "oracle_cost_usd": oracle_cost,
        "cost_usd": round(result.cost_usd + oracle_cost, 8),
    }
