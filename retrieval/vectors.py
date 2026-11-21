"""Local vector index for one figure (Decisions B3, B4, B5): load, embed, cache, search.

Every model setting comes from core.config.EMBEDDING and is asserted against the loaded
model, because each one fails silently if wrong: the wrong pooling or a missing normalise
step still returns 384 numbers. Vectors are cached beside the figure's chunks.jsonl and
used only if they provably came from the same chunks file and the same model settings.
"""

import hashlib
import json
from pathlib import Path
import time

from huggingface_hub import snapshot_download
import numpy as np
from sentence_transformers import SentenceTransformer
from sentence_transformers.models import Normalize, Pooling

from core.config import EMBEDDING
from retrieval.bm25 import load_chunks


NORM_TOLERANCE = 1e-5
# Everything the vectors depend on. Any mismatch with the current run means rebuild.
CACHE_KEYS = ("chunks_sha256", "model_id", "revision", "pooling", "normalise", "dimensions")


def _check(name, expected, actual):
    if expected != actual:
        raise RuntimeError(f"embedding model {name}: expected {expected!r}, loaded {actual!r}")


def load_model(local_files_only=True):
    """Load the pinned model on CPU; assert every B4 setting; return (model, report).

    Offline by default: the model must already be in the local Hugging Face cache.
    """
    started = time.perf_counter()
    # The Hub resolves the revision and caches the files under snapshots/<commit SHA>.
    # Loading from that folder means the name we check is the commit we actually load.
    folder = Path(snapshot_download(EMBEDDING.model_id, revision=EMBEDDING.revision,
                                    local_files_only=local_files_only))
    model = SentenceTransformer(str(folder), device="cpu")
    load_seconds = time.perf_counter() - started

    modules = [type(module).__name__ for module in model]
    pooling = next((m for m in model if isinstance(m, Pooling)), None)
    if pooling is None:
        raise RuntimeError(f"embedding model has no Pooling module: {modules}")
    normalises = any(isinstance(m, Normalize) for m in model)

    _check("revision", EMBEDDING.revision, folder.name)
    _check("dimensions", EMBEDDING.dimensions, model.get_embedding_dimension())
    _check("max_seq_length", EMBEDDING.max_tokens, model.max_seq_length)
    _check("pooling", EMBEDDING.pooling, pooling.pooling_mode)
    _check("normalise", EMBEDDING.normalise, normalises)
    # Our query instruction must be the only prefix: the model may ship none of its own.
    _check("shipped prompts", {}, {k: v for k, v in model.prompts.items() if v})
    _check("default prompt", None, model.default_prompt_name)

    return model, {
        "model_id": EMBEDDING.model_id, "revision_pinned": EMBEDDING.revision,
        "revision_loaded": folder.name, "dimensions": model.get_embedding_dimension(),
        "max_seq_length": model.max_seq_length, "pooling": pooling.pooling_mode,
        "normalise": normalises, "modules": modules, "load_seconds": load_seconds}


def token_lengths(model, chunks):
    """Each chunk's true length in the model's tokens: specials included, truncation off."""
    encoded = model.tokenizer([c["text"] for c in chunks], add_special_tokens=True,
                              truncation=False, verbose=False)
    return [len(ids) for ids in encoded["input_ids"]]


def check_lengths(model, chunks):
    """Raise, listing every offender, if any chunk would be truncated by the model."""
    over = [(c["chunk_id"], c["locator"], n)
            for c, n in zip(chunks, token_lengths(model, chunks)) if n > EMBEDDING.max_tokens]
    if over:
        listing = "; ".join(f"{cid} ({loc}): {n} tokens" for cid, loc, n in over)
        raise ValueError(f"{len(over)} chunk(s) exceed {EMBEDDING.max_tokens} model tokens "
                         f"and would be truncated: {listing}")


def _norms(vectors):
    return np.linalg.norm(vectors.astype(np.float64), axis=1)


def check_norms(vectors):
    norms = _norms(vectors)
    worst = int(np.argmax(np.abs(norms - 1.0)))
    if abs(norms[worst] - 1.0) > NORM_TOLERANCE:
        raise RuntimeError(f"vector {worst} has norm {norms[worst]!r}; expected 1 ± "
                           f"{NORM_TOLERANCE}")


def embed_passages(model, chunks):
    """(N, dims) float32 unit vectors. Passages get no prompt; the pipeline normalises."""
    check_lengths(model, chunks)
    vectors = model.encode([c["text"] for c in chunks], prompt=None,
                           normalize_embeddings=False, convert_to_numpy=True,
                           show_progress_bar=False).astype(np.float32)
    check_norms(vectors)
    return vectors


def _expected_meta(path):
    return {"chunks_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            "model_id": EMBEDDING.model_id, "revision": EMBEDDING.revision,
            "pooling": EMBEDDING.pooling, "normalise": EMBEDDING.normalise,
            "dimensions": EMBEDDING.dimensions}


def _read_cache(npy, meta_path, expected, chunk_ids):
    """Return (vectors, None) if the cache is valid for this run, else (None, reason)."""
    if not npy.is_file() or not meta_path.is_file():
        return None, "no cache"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for key in CACHE_KEYS:
        if meta.get(key) != expected[key]:
            return None, f"{key} differs: cached {meta.get(key)!r}, current {expected[key]!r}"
    if meta.get("chunk_ids") != chunk_ids:
        return None, "chunk_ids differ"
    raw = npy.read_bytes()
    if hashlib.sha256(raw).hexdigest() != meta.get("vectors_sha256"):
        return None, "vectors_sha256 differs: vectors.npy is not the file vectors.json describes"
    vectors = np.load(npy)
    if vectors.shape != (len(chunk_ids), EMBEDDING.dimensions) or vectors.dtype != np.float32:
        return None, f"shape/dtype differs: cached {vectors.shape} {vectors.dtype}"
    return vectors, None


def build(path, model):
    """The vector index for one figure's chunks file, from cache if provably current."""
    path = Path(path)
    started = time.perf_counter()
    chunks = load_chunks(path)
    check_lengths(model, chunks)  # every build, hit or miss: never assume the gate held
    chunk_ids = [c["chunk_id"] for c in chunks]
    expected = _expected_meta(path)
    npy, meta_path = path.parent / "vectors.npy", path.parent / "vectors.json"

    vectors, reason = _read_cache(npy, meta_path, expected, chunk_ids)
    status = "hit" if vectors is not None else "miss"
    if vectors is None:
        vectors = embed_passages(model, chunks)
        np.save(npy, vectors)
        meta = {**expected, "chunk_ids": chunk_ids,
                "vectors_sha256": hashlib.sha256(npy.read_bytes()).hexdigest()}
        # Written last: vectors.json is the commit marker for vectors.npy.
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    check_norms(vectors)
    norms = _norms(vectors)
    return {
        "chunks": [{"chunk_id": c["chunk_id"], "locator": c["locator"], "text": c["text"]}
                   for c in chunks],
        "vectors": vectors,
        "meta": {**expected, "chunk_ids": chunk_ids},
        "cache": {"status": status, "reason": reason, "seconds": time.perf_counter() - started,
                  "bytes": npy.stat().st_size + meta_path.stat().st_size,
                  "norm_min": float(norms.min()), "norm_max": float(norms.max())}}


def embed_query(model, text, instruction=True):
    prompt = EMBEDDING.query_instruction if instruction else None
    vector = model.encode([text], prompt=prompt, normalize_embeddings=False,
                          convert_to_numpy=True, show_progress_bar=False)[0]
    return vector.astype(np.float32)


def search(index, model, query, k=8, instruction=True):
    """Rank every chunk by cosine to the query; ties by chunk order. JSON-serialisable."""
    query_vector = embed_query(model, query, instruction)
    check_norms(query_vector[None, :])
    cosines = index["vectors"] @ query_vector  # both unit length, so dot product = cosine
    order = sorted(range(len(cosines)), key=lambda i: (-float(cosines[i]), i))
    hits = [{"rank": rank, "chunk_id": index["chunks"][i]["chunk_id"],
             "locator": index["chunks"][i]["locator"], "cosine": float(cosines[i])}
            for rank, i in enumerate(order[:k], 1)]
    return {"params": {"model_id": EMBEDDING.model_id, "revision": EMBEDDING.revision,
                       "pooling": EMBEDDING.pooling, "normalise": EMBEDDING.normalise,
                       "dimensions": EMBEDDING.dimensions, "instruction_applied": instruction},
            "query": {"text": query,
                      "embedded_text": (EMBEDDING.query_instruction if instruction else "")
                      + query},
            "N": len(cosines), "hits": hits}
