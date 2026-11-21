"""Local embedding model (Decisions B4): load it pinned and checked, and measure token lengths.

Part A of 2d: no embedding, no cache, no search yet. Every setting comes from
core.config.EMBEDDING and is asserted against the loaded model, because each one fails
silently if wrong: the wrong pooling or a missing normalise step still returns 384 numbers.
"""

from pathlib import Path
import time

from huggingface_hub import snapshot_download
from sentence_transformers import SentenceTransformer
from sentence_transformers.models import Normalize, Pooling

from core.config import EMBEDDING


def _check(name, expected, actual):
    if expected != actual:
        raise RuntimeError(f"embedding model {name}: expected {expected!r}, loaded {actual!r}")


def load_model():
    """Load the pinned model on CPU; assert every B4 setting; return (model, report)."""
    started = time.perf_counter()
    # The Hub resolves the revision and caches the files under snapshots/<commit SHA>.
    # Loading from that folder means the name we check is the commit we actually load.
    folder = Path(snapshot_download(EMBEDDING.model_id, revision=EMBEDDING.revision))
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
