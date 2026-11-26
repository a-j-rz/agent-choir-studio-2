"""One figure's corpus tools, bound fresh per turn (CHOIR_AND_CORPUS §6; Decisions B5).

`bind_corpus_tools` closes over one loaded figure and one set of budget counters. The model
sees passage ids and text, never a path or a figure id, so it has no route to another corpus.

Handlers are synchronous on purpose: with no `await` inside, nothing can run between a
`write_raw` and the `emit` that names its file, so the two keep the same seq.

Refusals (over budget, unknown id, bad window) never raise: the model gets a plain
{"error": ...} and the trace gets a loud *_refused event. Code errors still raise.
"""

import copy

from core.config import RETRIEVAL
from retrieval import hybrid


TOOL_SCHEMAS = [
    {
        "type": "function",
        "name": "search_my_corpus",
        "description": (
            "Search your own writings. Returns up to "
            f"{RETRIEVAL.results_per_search} passages with ids, locators and a short preview. "
            f"You have {RETRIEVAL.searches_per_turn} searches this turn."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "What to look for"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "open_passage",
        "description": (
            "Read one passage in full, by the passage_id a search returned. "
            f"You may open {RETRIEVAL.opens_per_turn} passages this turn."
        ),
        "parameters": {
            "type": "object",
            "properties": {"passage_id": {"type": "string", "description": "A passage_id"}},
            "required": ["passage_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "open_context",
        "description": (
            "Read a passage with its neighbours from the same book, in order. Each passage "
            "returned counts as one open."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "passage_id": {"type": "string", "description": "A passage_id"},
                "window": {
                    "type": "integer",
                    "description": (f"Neighbours each side, 0 to {RETRIEVAL.context_window_max}"),
                },
            },
            "required": ["passage_id", "window"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "list_my_works",
        "description": "List the works in your corpus, with translator and period.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


ROLE = "figure"  # the seat; which figure is the lane's to say (Decisions K9)


def bind_corpus_tools(figure, model, lane):
    """(tool_schemas, handlers, turn_state) for one figure's turn, recorded in its lane.

    Budgets live only in this binding. turn_state() returns a copy of what this turn did,
    for the citation check: changing the copy changes nothing here.
    """
    chunks = figure["chunks"]
    by_id = {c["chunk_id"]: c for c in chunks}
    # surfaced: passage_id -> the sources ("both", "lexical_only", "semantic_only") under
    # which it appeared in any merged list this turn.
    state = {"searches_used": 0, "opens_used": 0, "surfaced": {}, "searches": [], "opens": []}

    def refuse_open(via, reason, **detail):
        lane.emit("passage_open_refused", ROLE, {
            "via": via, **detail, "reason": reason,
            "opens_used": state["opens_used"], "opens_max": RETRIEVAL.opens_per_turn})
        return {"error": reason}

    def record_open(chunk, via):
        state["opens_used"] += 1
        surfaced = chunk["chunk_id"] in state["surfaced"]
        state["opens"].append({"passage_id": chunk["chunk_id"], "via": via,
                               "surfaced_by_search": surfaced})
        lane.emit("passage_opened", ROLE, {
            "passage_id": chunk["chunk_id"], "locator": chunk["locator"], "via": via,
            "surfaced_by_search": surfaced,
            "opens_used": state["opens_used"],
            "opens_left": RETRIEVAL.opens_per_turn - state["opens_used"]})
        return {"passage_id": chunk["chunk_id"], "locator": chunk["locator"],
                "text": chunk["text"]}

    def search_my_corpus(query):
        used, limit = state["searches_used"], RETRIEVAL.searches_per_turn
        reason = None
        if used >= limit:
            reason = f"search budget exhausted ({used}/{limit})"
        elif not query.strip():
            reason = "empty query"
        if reason:
            lane.emit("corpus_search_refused", ROLE, {
                "query": query, "reason": reason, "searches_used": used,
                "searches_max": limit})
            return {"error": reason}

        detail = hybrid.search(figure, model, query)
        state["searches_used"] += 1
        number = state["searches_used"]
        for m in detail["merged"]:
            state["surfaced"].setdefault(m["passage_id"], set()).add(m["source"])
        state["searches"].append({"search_number": number, "query": query, "merged": [
            {"passage_id": m["passage_id"], "source": m["source"]} for m in detail["merged"]]})
        # Evidence first, then the event that names it. No `await` between these two.
        raw_file = lane.write_raw(f"{ROLE}-search{number}", detail)
        lane.emit("corpus_search", ROLE, {
            "search_number": number, "query": query,
            "embedded_text": detail["query"]["embedded_text"],
            "depth": detail["params"]["depth"],
            "lexical_matched_total": detail["lexical_matched_total"],
            "query_embed_ms": detail["query_embed_ms"],
            "merged": [{k: m[k] for k in ("passage_id", "locator", "lexical_rank",
                                          "semantic_rank", "source", "rrf_score")}
                       for m in detail["merged"]],
            "searches_left": limit - number, "raw_file": raw_file})
        return {"searches_used": number, "searches_left": limit - number,
                "results": [{"passage_id": m["passage_id"], "locator": m["locator"],
                             "preview": by_id[m["passage_id"]]["text"][:RETRIEVAL.preview_chars]}
                            for m in detail["merged"]]}

    def open_passage(passage_id):
        chunk = by_id.get(passage_id)
        if chunk is None:
            return refuse_open("open_passage", f"unknown passage_id {passage_id!r}",
                               passage_id=passage_id)
        if state["opens_used"] >= RETRIEVAL.opens_per_turn:
            return refuse_open("open_passage", "open budget exhausted "
                               f"({state['opens_used']}/{RETRIEVAL.opens_per_turn})",
                               passage_id=passage_id)
        return {**record_open(chunk, "open_passage"),
                "opens_left": RETRIEVAL.opens_per_turn - state["opens_used"]}

    def open_context(passage_id, window):
        detail = {"passage_id": passage_id, "window": window}
        chunk = by_id.get(passage_id)
        if chunk is None:
            return refuse_open("open_context", f"unknown passage_id {passage_id!r}", **detail)
        if not isinstance(window, int) or isinstance(window, bool) or not (
                0 <= window <= RETRIEVAL.context_window_max):
            return refuse_open("open_context", f"window must be an integer from 0 to "
                               f"{RETRIEVAL.context_window_max}; got {window!r}", **detail)
        centre = figure["position"][passage_id]
        span = [c for c in chunks[max(0, centre - window):centre + window + 1]
                if c["book"] == chunk["book"]]
        left = RETRIEVAL.opens_per_turn - state["opens_used"]
        if len(span) > left:
            return refuse_open("open_context", f"open budget too small: {len(span)} "
                               f"passages requested, {left} left", **detail)
        passages = [record_open(c, "open_context") for c in span]
        return {"passage_id": passage_id, "window": window, "passages": passages,
                "opens_left": RETRIEVAL.opens_per_turn - state["opens_used"]}

    def list_my_works():
        manifest = figure["manifest"]
        return {"author": manifest["author"], "included_works": manifest["included_works"],
                "translator": manifest["translation_edition"]["translator"],
                "period": manifest["period"]}

    def turn_state():
        return {"searches": copy.deepcopy(state["searches"]),
                "opens": copy.deepcopy(state["opens"]),
                "surfaced_sources": {pid: sorted(sources)
                                     for pid, sources in state["surfaced"].items()}}

    handlers = {"search_my_corpus": search_my_corpus, "open_passage": open_passage,
                "open_context": open_context, "list_my_works": list_my_works}
    return TOOL_SCHEMAS, handlers, turn_state
