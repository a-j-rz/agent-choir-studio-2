"""One figure turn: the figure searches its own corpus, may ask the Oracle, then returns a cited
contribution.

The turn receives a lane (`trace.for_figure(id)`) and a ChoirInput: the canonical question, and
nothing else from the Host (Decisions J4, K9). Every event it emits carries role "figure" and
the lane's figure id. Whoever starts the turn records run-level facts such as the condition.

The citation check and the Horizon reconciliation after the turn are set arithmetic over what was
recorded — no model judges anything here. `condition` is the 3c prompt experiment: A without, B
with, a block listing what the figure's own world understood where it touches on later things.
"""

import asyncio
from pathlib import Path
import re
import time
from typing import Any, Literal

from choir import oracle
from choir.contribution import TEXT_FORMAT, ContributionInvalid, parse_contribution
from choir.reconcile import reconcile
from core.config import ORACLE, RETRIEVAL
from core.llm import call_model
from core.trace import LaneTrace
from host.records import ChoirInput
from epistemic.horizon import find_breaches
from retrieval import hybrid, vectors
from retrieval.tools import bind_corpus_tools

PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "figure_standin.md"
MAX_ROUND_TRIPS = 10
ROLE = "figure"  # the seat; the lane says which figure
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
        edition=manifest["prompt_edition"],
        reading_rule=f"{manifest['reading_rule']}\n" if manifest["reading_rule"] else "",
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
    """What was cited vs opened vs surfaced. Lists in corpus order; unknown ids last.

    Two flags for the Editor, recorded, never raised (J10, K9): an insufficiency declared with no
    search this turn, and a grounded answer that cites nothing.
    """
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
        "declared_without_search": (contribution.status == "insufficient_corpus_basis"
                                    and not state["searches"]),
        "grounded_without_citations": (contribution.status == "grounded"
                                       and not contribution.citations),
    }


def editor_passages(contribution, figure) -> list[dict[str, Any]]:
    """Each cited passage, in citation order, in full, with one neighbour each side from the same
    book (open_context's rule at window 1), marked by side. For the Editor input only (K10):
    never written to baseline.json, which stays text-free. An unknown id keeps its place, empty."""
    chunks, position = figure["chunks"], figure["position"]
    out = []
    for pid in dict.fromkeys(c.passage_id for c in contribution.citations):
        if pid not in position:
            out.append({"passage_id": pid, "locator": None, "text": None, "neighbours": []})
            continue
        i = position[pid]
        chunk = chunks[i]
        neighbours = [{"passage_id": chunks[j]["chunk_id"], "locator": chunks[j]["locator"],
                       "text": chunks[j]["text"], "side": side}
                      for j, side in ((i - 1, "before"), (i + 1, "after"))
                      if 0 <= j < len(chunks) and chunks[j]["book"] == chunk["book"]]
        out.append({"passage_id": pid, "locator": chunk["locator"], "text": chunk["text"],
                    "neighbours": neighbours})
    return out


class RoundTripCapReached(Exception):
    """The turn hit its round-trip cap before answering. Checked before parsing."""


async def figure_turn(
    lane: LaneTrace,
    choir_input: ChoirInput,
    condition: Condition,
    model,
    max_round_trips: int = MAX_ROUND_TRIPS,
) -> dict[str, Any]:
    figure_id = lane.figure_id
    question = choir_input.canonical_question  # the only thing from the Host that reaches here
    # Loads off the event loop, so four lanes don't stall it (K9).
    started = time.perf_counter()
    # The figure load touches the embedding model (length check, cache read): its one owner.
    figure = await vectors.on_model(hybrid.load_figure, figure_id, model, allow_build=False)
    ctx = await asyncio.to_thread(oracle.load_context, figure_id)  # no model; stemmer per thread
    # Includes queueing for the model owner: it measures the lane's wait, not disk time.
    load_ms = round((time.perf_counter() - started) * 1000, 1)
    instructions = fill_prompt(figure["manifest"], ctx, condition)  # guard runs here
    corpus_schemas, corpus_handlers, turn_state = bind_corpus_tools(figure, model, lane)
    oracle_schema, ask_oracle, oracle_state = oracle.bind_oracle(figure_id, lane, ctx=ctx)
    schemas = [*corpus_schemas, oracle_schema]
    handlers = {**corpus_handlers, "ask_oracle": ask_oracle}  # budgets stay independent
    lane.emit("figure_bound", ROLE, {
        "figure_id": figure_id, "condition": condition, "chunks": len(figure["chunks"]),
        "chunks_sha256": figure["vectors"]["meta"]["chunks_sha256"],
        "vector_cache": figure["cache"]["status"], "load_ms": load_ms,
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
        trace=lane,
        max_round_trips=max_round_trips,
        text_format=TEXT_FORMAT,
    )
    if result.stop_reason == "round_trip_cap_reached":
        raise RoundTripCapReached(f"{figure_id}: no answer within {max_round_trips} round trips")

    try:
        contribution, extra_items = parse_contribution(result.message_texts)
    except ContributionInvalid as error:
        lane.emit("contribution_invalid", ROLE, {
            "reason": error.reason, "stop_reason": result.stop_reason,
            "message_texts": result.message_texts, "errors": error.errors})
        raise

    check = citation_check(contribution, turn_state(), figure, extra_items)
    lane.emit("contribution", ROLE, {
        "contribution": contribution.model_dump(), "stop_reason": result.stop_reason})
    lane.emit("citation_check", ROLE, check)

    state, requests = turn_state(), oracle_state()
    chunks = {c["chunk_id"]: c["text"] for c in figure["chunks"]}
    opened = [(pid, chunks[pid]) for pid in dict.fromkeys(o["passage_id"] for o in state["opens"])]
    reconciliation = reconcile(contribution, question, requests, opened, ctx["compiled"])
    lane.emit("horizon_reconciliation", ROLE, {"condition": condition, **reconciliation})

    oracle_cost = round(sum(r.get("cost_usd", 0.0) for r in requests), 8)
    return {
        "figure_id": figure_id, "canonical_question": question, "condition": condition,
        "status": contribution.status, "stop_reason": result.stop_reason,
        "round_trips": result.round_trips, "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens, "reasoning_tokens": result.reasoning_tokens,
        "searches_used": len(state["searches"]),
        "oracle_requests_used": sum(r["outcome"] != "refused" for r in requests),
        "figure_cost_usd": result.cost_usd, "oracle_cost_usd": oracle_cost,
        "cost_usd": round(result.cost_usd + oracle_cost, 8),
        # For the independent baseline (K9): ids and query strings only, never passage text.
        "contribution": contribution.model_dump(),
        "check_flags": {k: check[k] for k in ("declared_without_search",
                                              "grounded_without_citations")},
        "search_queries": [s["query"] for s in state["searches"]],
        "opened": list(dict.fromkeys(o["passage_id"] for o in state["opens"])),
        "cited": check["cited"],
        "oracle_bridges": [{"number": r["number"], "concept": r["concept"],
                            "returned": r["returned"]} for r in requests],
        # For the Editor input only, never the baseline (K10): cited passages in full.
        "editor_passages": editor_passages(contribution, figure),
    }
