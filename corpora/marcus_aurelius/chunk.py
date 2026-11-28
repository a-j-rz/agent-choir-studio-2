"""Read clean Thoughts, manifest and chunking config; write chunks JSONL and report.

Run from the repository root. No retrieval index is built here.
"""

import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the repo root, so corpus_kit imports when run as python corpora/<id>/<script>.py
from corpus_kit.chunker import serialise, split_section, word_stats, words  # noqa: E402


BASE = Path("corpora/marcus_aurelius")
ROMANS = "I II III IV V VI VII VIII IX X XI XII".split()


def read_sections(clean, manifest):
    headings = list(re.finditer(r"(?m)^Book ([IVX]+)$", clean))
    if [match[1] for match in headings] != ROMANS:
        raise ValueError("Expected exactly Books I–XII in order")
    for book, heading in enumerate(headings, 1):
        end = headings[book].start() if book < 12 else len(clean)
        body = clean[heading.end():end].strip()
        place = next((p["clean"] for p in manifest["chronology"]["place_notes"]
                      if p["book"] == book), None)
        if place:
            if not body.endswith("\n\n" + place):
                raise ValueError(f"Missing place-note in Book {book}")
            body = body[:-(len(place) + 2)]
        entries = list(re.finditer(r"(?m)^(\d+)\. ", body))
        if [int(m[1]) for m in entries] != list(range(1, len(entries) + 1)):
            raise ValueError(f"Section gap or duplicate in Book {book}")
        if not entries or entries[0].start() != 0:
            raise ValueError(f"Unparsed text in Book {book}")
        for index, entry in enumerate(entries):
            end = entries[index + 1].start() if index + 1 < len(entries) else len(body)
            text = body[entry.end():end].strip()
            if not text:
                raise ValueError(f"Empty section in Book {book}")
            yield book, int(entry[1]), text


def make_chunks(clean, manifest, config):
    if config["unit"] != "section" or config["max_words"] < 1:
        raise ValueError("Expected section units and a positive max_words")
    chunks, splits, coverage = [], [], {}
    for book, section, text in read_sections(clean, manifest):
        # Marcus uses no abbreviation or initials rule (the defaults). Adding one would change
        # his chunks, so it would be a corpus change, not a refactor.
        pieces = split_section(text, config["max_words"])
        if " ".join(text.split()) != " ".join(" ".join(pieces).split()):
            raise ValueError("Split changed section text")
        base_id = f"ma-{book:02d}-{section:03d}"
        if len(pieces) > 1:
            splits.append({"section_id": base_id, "parts": len(pieces)})
        coverage[book] = section
        for part, piece in enumerate(pieces, 1):
            chunk_id = base_id if len(pieces) == 1 else f"{base_id}-p{part}"
            chunks.append({
                "schema_version": 1, "chunk_id": chunk_id,
                "figure_id": manifest["figure_id"], "work": manifest["work"],
                "book": book, "section": section,
                "part": None if len(pieces) == 1 else part, "parts_total": len(pieces),
                "locator": f"Book {ROMANS[book - 1]}, {section}", "text": piece,
                "word_count": words(piece), "period": manifest["period"],
                "genre": "Catalogue of debts" if book == 1 else "Personal philosophical notes",
                "translator": manifest["translation_edition"]["translator"],
                "source": manifest["source_provenance"]["gutenberg_number"],
                "source_sha256": manifest["source_provenance"]["sha256"]})
    return chunks, splits, coverage


def main():
    manifest = json.loads((BASE / "manifest.json").read_text(encoding="utf-8"))
    config = json.loads((BASE / "chunking.json").read_text(encoding="utf-8"))
    clean = (BASE / "data/clean/thoughts.txt").read_text(encoding="utf-8")
    chunks, splits, coverage = make_chunks(clean, manifest, config)
    payload, payload_sha = serialise(chunks)
    stats = word_stats(chunks)
    count = len(chunks)
    report = {"schema_version": 1, "total_chunks": count,
              "section_count": sum(coverage.values()),
              "word_counts": stats,
              "p90_method": "nearest rank", "split_sections": splits,
              "chunks_sha256": payload_sha,
              "clean_sha256": hashlib.sha256(clean.encode("utf-8")).hexdigest(),
              "config_sha256": hashlib.sha256((BASE / "chunking.json").read_bytes()).hexdigest()}
    (BASE / "data/chunks.jsonl").write_text(payload, encoding="utf-8")
    (BASE / "data/chunk_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Chunks: {count}; words min/median/p90/max: "
          f"{stats['min']}/{stats['median']:g}/{stats['p90']}/{stats['max']}")
    print(f"Split sections: {', '.join(s['section_id'] for s in splits)}")
    print(f"chunks.jsonl SHA-256: {report['chunks_sha256']}")


if __name__ == "__main__":
    main()
