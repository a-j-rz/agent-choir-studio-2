"""Probe the local vector index beside BM25. Offline; no model API calls.

    python -m scripts.vector_probe --download --lengths      # first run only: fetch the model
    python -m scripts.vector_probe --lengths
    python -m scripts.vector_probe --search "governing one's own mind" [--no-instruction]
    python -m scripts.vector_probe --selfcheck

Cache and load reports go to stderr, so --json stdout is byte-identical between runs.
"""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

from core.config import EMBEDDING
from retrieval import bm25, vectors
from retrieval.bm25 import load_chunks


DEFAULT_CHUNKS = Path("corpora/marcus_aurelius/data/chunks.jsonl")
SAMPLE = "thyself doth hath ruling faculty government"
NO_MATCH = ">>> NO BM25 MATCH <<<"


def median(values):
    ordered = sorted(values)
    return (ordered[(len(ordered) - 1) // 2] + ordered[len(ordered) // 2]) / 2


def p90(values):  # nearest rank, as in corpora/marcus_aurelius/chunk.py
    ordered = sorted(values)
    return ordered[(9 * len(ordered) + 9) // 10 - 1]


def report_lengths(model, report, chunks):
    print(f"model      {report['model_id']}")
    print(f"revision   pinned {report['revision_pinned']}")
    print(f"           loaded {report['revision_loaded']}  "
          f"{'MATCH' if report['revision_loaded'] == report['revision_pinned'] else 'MISMATCH'}")
    print(f"pipeline   {' -> '.join(report['modules'])}")
    print(f"dims {report['dimensions']}  max_seq_length {report['max_seq_length']}  "
          f"pooling {report['pooling']}  normalise {report['normalise']}  "
          f"load {report['load_seconds']:.2f} s")

    lengths = vectors.token_lengths(model, chunks)
    rows = [(c, n, n / c["word_count"]) for c, n in zip(chunks, lengths)]
    print(f"\nmodel-token length over {len(chunks)} chunks (specials included, no truncation):")
    print(f"  min {min(lengths)}  median {median(lengths):g}  p90 {p90(lengths)}  "
          f"max {max(lengths)}")
    worst = max(rows, key=lambda row: row[2])
    print(f"tokens per word: median {median([r[2] for r in rows]):.3f}  max {worst[2]:.3f} "
          f"({worst[0]['locator']} [{worst[0]['chunk_id']}], {worst[0]['word_count']} words, "
          f"{worst[1]} tokens)")

    limit = EMBEDDING.max_tokens
    over = [r for r in rows if r[1] > limit]
    print(f"\nchunks over {limit} tokens: {len(over)}")
    for chunk, n, _ in over:
        print(f"  {chunk['locator']:<16}[{chunk['chunk_id']}]  words {chunk['word_count']:<4}"
              f"tokens {n}")
    print("\nBook I, 17 explicitly:")
    for chunk, n, _ in rows:
        if chunk["locator"] == "Book I, 17":
            flag = "OVER" if n > limit else "ok"
            text = " ".join(chunk["text"].split())
            print(f"  [{chunk['chunk_id']}]  words {chunk['word_count']:<4}tokens {n:<4}{flag}")
            print(f"      starts: {text[:60]!r}")
            print(f"      ends:   {text[-60:]!r}")

    pieces = model.tokenizer.tokenize(SAMPLE)
    ids = model.tokenizer(SAMPLE)["input_ids"]
    print(f"\ntokenisation sample: {SAMPLE!r}")
    print(f"  pieces ({len(pieces)}): {pieces}")
    print(f"  with specials ({len(ids)}): "
          f"{model.tokenizer.convert_ids_to_tokens(ids)}")


def report_cache(index):
    c = index["cache"]
    reason = f" ({c['reason']})" if c["reason"] else ""
    print(f"vector cache: {c['status'].upper()}{reason}  {c['seconds']:.2f} s  "
          f"{c['bytes']:,} bytes on disk  N={len(index['chunks'])}  "
          f"norms min {c['norm_min']:.7f} max {c['norm_max']:.7f}", file=sys.stderr)


def compare(index, bm25_index, model, query, k, instruction):
    """Both rankings over all chunks; JSON-serialisable top-k of each plus cross-ranks."""
    n = len(index["chunks"])
    vec_all = vectors.search(index, model, query, k=n, instruction=instruction)
    bm_all = bm25.search(bm25_index, query, k=n)
    vec_rank = {h["chunk_id"]: h["rank"] for h in vec_all["hits"]}
    bm_rank = {h["chunk_id"]: h["rank"] for h in bm_all["hits"]}
    vec_top = {**vec_all, "hits": vec_all["hits"][:k]}
    bm_top = {**bm_all, "hits": bm_all["hits"][:k]}
    return {"vector": vec_top, "bm25": bm_top,
            "bm25_rank_of_vector_hits": {h["chunk_id"]: bm_rank.get(h["chunk_id"])
                                         for h in vec_top["hits"]},
            "vector_rank_of_bm25_hits": {h["chunk_id"]: vec_rank[h["chunk_id"]]
                                         for h in bm_top["hits"]},
            "bm25_matching_chunks": len(bm_all["hits"])}


def render(result, index):
    texts = {c["chunk_id"]: " ".join(c["text"].split()) for c in index["chunks"]}
    vec, bm = result["vector"], result["bm25"]
    snippet = lambda cid: texts[cid][:200] + ("…" if len(texts[cid]) > 200 else "")
    lines = [f"query:    {vec['query']['text']!r}",
             f"embedded: {vec['query']['embedded_text']!r}",
             f"N={vec['N']}  instruction_applied={vec['params']['instruction_applied']}  "
             f"BM25 matching chunks={result['bm25_matching_chunks']}", "",
             f"=== VECTOR top {len(vec['hits'])} (BM25 rank over all matching chunks) ==="]
    for h in vec["hits"]:
        rank = result["bm25_rank_of_vector_hits"][h["chunk_id"]]
        other = NO_MATCH if rank is None else f"bm25 #{rank}"
        lines += [f"#{h['rank']:<2} {h['locator']:<16}[{h['chunk_id']}]  "
                  f"cos {h['cosine']:.4f}   {other}",
                  f"      \"{snippet(h['chunk_id'])}\"", ""]
    lines.append(f"=== BM25 top {len(bm['hits'])} (vector rank of {vec['N']}) ===")
    for h in bm["hits"]:
        terms = ", ".join(f"{t['stem']}←{'/'.join(t['surface_forms'])}" for t in h["terms"])
        lines += [f"#{h['rank']:<2} {h['locator']:<16}[{h['chunk_id']}]  "
                  f"score {h['score']:.4f}   vector #{result['vector_rank_of_bm25_hits'][h['chunk_id']]}"
                  f"   [{terms}]",
                  f"      \"{snippet(h['chunk_id'])}\"", ""]
    return "\n".join(lines)


def selfcheck(model, index):
    chunks = index["chunks"]
    words = [len(c["text"].split()) for c in chunks]  # same rule as chunk.py's word_count
    mid = median(words)
    picks = [chunks[0],
             [c for c in chunks if c["locator"] == "Book I, 17"][-1],
             next(c for c, w in zip(chunks, words) if w >= mid)]
    failures = 0
    print(f"{'chunk':<16}{'words':>6}  {'self rank':>9}  {'cosine':>10}  ok")
    for chunk, w in [(p, len(p["text"].split())) for p in picks]:
        result = vectors.search(index, model, chunk["text"], k=1, instruction=False)
        top = result["hits"][0]
        ok = top["chunk_id"] == chunk["chunk_id"] and top["cosine"] >= 0.999
        failures += not ok
        rank = 1 if top["chunk_id"] == chunk["chunk_id"] else f"not 1 ({top['chunk_id']})"
        print(f"{chunk['chunk_id']:<16}{w:>6}  {rank!s:>9}  {top['cosine']:>10.6f}  "
              f"{'PASS' if ok else 'FAIL'}")

    # embedded_text must be exactly what the model saw: prompt= equals plain concatenation.
    query = "governing one's own mind"
    with_prompt = vectors.embed_query(model, query, instruction=True)
    concatenated = vectors.embed_query(model, EMBEDDING.query_instruction + query,
                                       instruction=False)
    gap = float(np.max(np.abs(with_prompt - concatenated)))
    ok = gap < 1e-6
    failures += not ok
    print(f"prompt= vs concatenated text: max |diff| {gap:.2e}  {'PASS' if ok else 'FAIL'}")
    print("SELFCHECK", "PASSED" if not failures else f"FAILED ({failures})")
    return 0 if not failures else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--lengths", action="store_true")
    mode.add_argument("--search", metavar="QUERY")
    mode.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--no-instruction", action="store_true")
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--download", action="store_true",
                        help="allow fetching the pinned model from the Hub (first run only)")
    args = parser.parse_args()

    model, report = vectors.load_model(local_files_only=not args.download)
    if args.lengths:
        report_lengths(model, report, load_chunks(args.chunks))
        return
    index = vectors.build(args.chunks, model)
    report_cache(index)
    if args.selfcheck:
        sys.exit(selfcheck(model, index))
    result = compare(index, bm25.build(args.chunks), model, args.search, args.k,
                     instruction=not args.no_instruction)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render(result, index))


if __name__ == "__main__":
    main()
