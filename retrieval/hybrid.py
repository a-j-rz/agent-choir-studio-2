"""Hybrid retrieval for one figure: BM25 + vector, merged by Reciprocal Rank Fusion (B1, B2, B5).

RRF ignores the two searches' scores (BM25 and cosine are on unrelated scales) and uses only
ranks: each list adds 1/(k + rank) to an item, and the sums are ranked. An item both searches
found almost always beats one only a single search found.

A loaded figure holds exactly one corpus directory. There is no global index to filter.
"""

import json
from pathlib import Path
import re

from core.config import RETRIEVAL
from retrieval import bm25, vectors
from retrieval.bm25 import load_chunks


CORPORA_DIR = Path(__file__).resolve().parent.parent / "corpora"
_FIGURE_ID = re.compile(r"^[a-z][a-z_]*$")  # no "..", no "/": one directory, by construction


def load_figure(figure_id, model):
    """One figure's chunks, manifest, BM25 index and vector index. Nothing else."""
    if not isinstance(figure_id, str) or not _FIGURE_ID.match(figure_id):
        raise ValueError(f"invalid figure_id {figure_id!r}")
    root = CORPORA_DIR / figure_id
    manifest_path, chunks_path = root / "manifest.json", root / "data" / "chunks.jsonl"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"no manifest for figure {figure_id!r}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("figure_id") != figure_id:
        raise ValueError(f"manifest figure_id {manifest.get('figure_id')!r} != {figure_id!r}")

    chunks = load_chunks(chunks_path)
    strays = [c["chunk_id"] for c in chunks if c.get("figure_id") != figure_id]
    if strays:
        raise ValueError(f"{len(strays)} chunk(s) not from {figure_id!r}: {strays[:5]}")
    lexical = bm25.build(chunks_path)
    semantic = vectors.build(chunks_path, model)
    ids = [c["chunk_id"] for c in chunks]
    if [d["chunk_id"] for d in lexical["docs"]] != ids:
        raise ValueError("BM25 index chunk order differs from chunks.jsonl")
    if [c["chunk_id"] for c in semantic["chunks"]] != ids:
        raise ValueError("vector index chunk order differs from chunks.jsonl")

    return {"figure_id": figure_id, "manifest": manifest, "chunks": chunks,
            "position": {cid: i for i, cid in enumerate(ids)},
            "bm25": lexical, "vectors": semantic, "cache": semantic["cache"]}


def rrf(lexical_ids, semantic_ids, k, order):
    """Merge two ranked id lists. Pure. Ties broken by `order` (id -> corpus position)."""
    merged = {}
    for field, ids in (("lexical", lexical_ids), ("semantic", semantic_ids)):
        for rank, item in enumerate(ids, 1):
            entry = merged.setdefault(item, {
                "id": item, "rrf_score": 0.0,
                "lexical_rank": None, "semantic_rank": None,
                "lexical_contribution": None, "semantic_contribution": None})
            contribution = 1 / (k + rank)
            entry[f"{field}_rank"] = rank
            entry[f"{field}_contribution"] = contribution
    for entry in merged.values():
        # Summed in a fixed order (lexical, then semantic) so the float is reproducible.
        entry["rrf_score"] = ((entry["lexical_contribution"] or 0.0)
                              + (entry["semantic_contribution"] or 0.0))
    return sorted(merged.values(), key=lambda e: (-e["rrf_score"], order[e["id"]]))


def _source(entry):
    if entry["lexical_rank"] and entry["semantic_rank"]:
        return "both"
    return "lexical_only" if entry["lexical_rank"] else "semantic_only"


def search(figure, model, query, depth=None):
    """BM25 and vector top-`depth`, RRF-merged, cut to results_per_search. Full detail."""
    depth = RETRIEVAL.candidate_depth if depth is None else depth
    everything = bm25.search(figure["bm25"], query, k=len(figure["chunks"]))
    lexical = {**everything, "hits": everything["hits"][:depth]}
    semantic = vectors.search(figure["vectors"], model, query, k=depth, instruction=True)

    fused = rrf([h["chunk_id"] for h in lexical["hits"]],
                [h["chunk_id"] for h in semantic["hits"]],
                RETRIEVAL.rrf_k, figure["position"])[:RETRIEVAL.results_per_search]
    locators = {c["chunk_id"]: c["locator"] for c in figure["chunks"]}
    merged = [{"rank": rank, "passage_id": e["id"], "locator": locators[e["id"]],
               "source": _source(e), "rrf_score": e["rrf_score"],
               "lexical_rank": e["lexical_rank"], "semantic_rank": e["semantic_rank"],
               "lexical_contribution": e["lexical_contribution"],
               "semantic_contribution": e["semantic_contribution"]}
              for rank, e in enumerate(fused, 1)]
    return {"params": {"figure_id": figure["figure_id"], "rrf_k": RETRIEVAL.rrf_k,
                       "depth": depth, "results_per_search": RETRIEVAL.results_per_search},
            "query": {"text": query, "embedded_text": semantic["query"]["embedded_text"]},
            "lexical_matched_total": len(everything["hits"]),
            "lexical": lexical, "semantic": semantic, "merged": merged}
