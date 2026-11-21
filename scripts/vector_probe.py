"""Probe the local embedding model. Offline after the first download; no model API calls.

    python -m scripts.vector_probe --lengths

Part A of 2d: load report and chunk lengths in the model's own tokens. No embedding yet.
"""

import argparse
from pathlib import Path

from core.config import EMBEDDING
from retrieval.bm25 import load_chunks
from retrieval.vectors import load_model, token_lengths


DEFAULT_CHUNKS = Path("corpora/marcus_aurelius/data/chunks.jsonl")
SAMPLE = "thyself doth hath ruling faculty government"


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

    lengths = token_lengths(model, chunks)
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
            print(f"  [{chunk['chunk_id']}]  words {chunk['word_count']:<4}tokens {n:<4}{flag}")

    pieces = model.tokenizer.tokenize(SAMPLE)
    ids = model.tokenizer(SAMPLE)["input_ids"]
    print(f"\ntokenisation sample: {SAMPLE!r}")
    print(f"  pieces ({len(pieces)}): {pieces}")
    print(f"  with specials ({len(ids)}): "
          f"{model.tokenizer.convert_ids_to_tokens(ids)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lengths", action="store_true", required=True)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    args = parser.parse_args()
    chunks = load_chunks(args.chunks)
    model, report = load_model()
    report_lengths(model, report, chunks)


if __name__ == "__main__":
    main()
