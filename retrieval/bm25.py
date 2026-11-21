"""Hand-written BM25 over one figure's chunks.jsonl (Decisions B1, B5).

One index per figure, built in memory from a path. Every result explains itself: which
query stems were found, how rare each is, and which surface words in a chunk produced it.

    IDF          = ln(1 + (N - n + 0.5) / (n + 0.5))          never negative
    contribution = IDF * tf*(k1+1) / (tf + k1*(1 - b + b*len/avglen))
    score        = sum of contributions over distinct query stems
"""

import json
import math
from pathlib import Path
import re

import snowballstemmer


K1 = 1.2
B = 0.75
STEMMER_NAME = "snowball-english"

_STEMMER = snowballstemmer.stemmer("english")
# A run of Unicode letters, with internal apostrophes allowed: "one's", "o'er", "doesn't".
# Leading/trailing apostrophes can't match, so "'tis" -> "tis" and "gods'" -> "gods".
# Everything else (hyphens included) splits: "self-control" -> "self", "control".
_TOKEN = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*")
_CURLY = str.maketrans({"’": "'", "‘": "'"})


def tokenise(text):
    """Lowercase, normalise curly apostrophes, then take letter runs (see _TOKEN)."""
    return _TOKEN.findall(text.lower().translate(_CURLY))


def analyse(text):
    """[(surface, stem), ...] — the same path for chunks and queries."""
    surfaces = tokenise(text)
    return list(zip(surfaces, _STEMMER.stemWords(surfaces)))


def load_chunks(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Chunks file not found: {path}")
    chunks, seen = [], set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{number}: malformed JSON: {error}") from None
        for field in ("chunk_id", "locator", "text"):
            if not isinstance(chunk.get(field), str) or not chunk[field]:
                raise ValueError(f"{path}:{number}: missing or empty '{field}'")
        if chunk["chunk_id"] in seen:
            raise ValueError(f"{path}:{number}: duplicate chunk_id {chunk['chunk_id']}")
        seen.add(chunk["chunk_id"])
        chunks.append(chunk)
    if not chunks:
        raise ValueError(f"{path}: no chunks")
    return chunks


def build_from_analysed(docs):
    """docs: [{chunk_id, locator, text, tokens: [(surface, stem), ...]}], in file order."""
    if not docs:
        raise ValueError("Cannot build an index over zero documents")
    built, df = [], {}
    for doc in docs:
        tf, surfaces = {}, {}
        for surface, stem in doc["tokens"]:
            tf[stem] = tf.get(stem, 0) + 1
            surfaces.setdefault(stem, set()).add(surface)
        for stem in tf:
            df[stem] = df.get(stem, 0) + 1
        built.append({"chunk_id": doc["chunk_id"], "locator": doc["locator"],
                      "text": doc["text"], "length": len(doc["tokens"]), "tf": tf,
                      "surfaces": {stem: sorted(forms) for stem, forms in surfaces.items()}})
    n = len(built)
    return {"docs": built, "df": df, "N": n,
            "avglen": sum(doc["length"] for doc in built) / n}


def build(path):
    return build_from_analysed([
        {"chunk_id": c["chunk_id"], "locator": c["locator"], "text": c["text"],
         "tokens": analyse(c["text"])}
        for c in load_chunks(path)])


def idf(n_total, n_with):
    return math.log(1 + (n_total - n_with + 0.5) / (n_with + 0.5))


def search_analysed(index, query_tokens, k=8):
    n_total, avglen = index["N"], index["avglen"]
    query, stems = [], []
    for surface, stem in query_tokens:
        n_with = index["df"].get(stem, 0)
        query.append({"token": surface, "stem": stem, "df": n_with,
                      "idf": idf(n_total, n_with), "in_corpus": n_with > 0})
        if n_with and stem not in stems:
            stems.append(stem)

    scored = []
    for order, doc in enumerate(index["docs"]):
        norm = K1 * (1 - B + B * doc["length"] / avglen)
        terms, score = [], 0.0
        for stem in stems:
            tf = doc["tf"].get(stem, 0)
            if not tf:
                continue
            weight = idf(n_total, index["df"][stem])
            contribution = weight * tf * (K1 + 1) / (tf + norm)
            score += contribution
            terms.append({"stem": stem, "surface_forms": doc["surfaces"][stem], "tf": tf,
                          "idf": weight, "contribution": contribution})
        if terms:
            scored.append((-score, order, score, doc, terms))
    scored.sort(key=lambda row: (row[0], row[1]))

    hits = [{"rank": rank, "chunk_id": doc["chunk_id"], "locator": doc["locator"],
             "score": score, "length": doc["length"], "terms": terms}
            for rank, (_, _, score, doc, terms) in enumerate(scored[:k], 1)]
    return {"params": {"k1": K1, "b": B, "N": n_total, "avglen": avglen,
                       "stemmer": STEMMER_NAME},
            "query": query, "hits": hits}


def search(index, query, k=8):
    return search_analysed(index, analyse(query), k)
