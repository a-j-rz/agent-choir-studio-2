"""Read clean Thoughts, manifest and chunking config; write chunks JSONL and report.

Run from the repository root. No retrieval index is built here.
"""

import hashlib
import json
from pathlib import Path
import re


BASE = Path("corpora/marcus_aurelius")
ROMANS = "I II III IV V VI VII VIII IX X XI XII".split()


def words(text):
    return len(text.split())


def split_section(text, maximum):
    if words(text) <= maximum:
        return [text]
    boundaries = [match.start() for match in re.finditer(r"\n\n", text)]
    if not boundaries:
        # A capital after terminal punctuation is a sentence boundary here.
        boundaries = [match.start() for match in re.finditer(
            r'''(?<=[.!?])\s+(?=["'\[]?[A-Z])''', text)]
    if not boundaries:
        raise ValueError("A sentence exceeds max_words; no permitted split boundary")
    midpoint = words(text) / 2
    cut = min(boundaries, key=lambda pos: (abs(words(text[:pos]) - midpoint), pos))
    return (split_section(text[:cut].strip(), maximum)
            + split_section(text[cut:].strip(), maximum))


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
    payload = "".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks)
    sizes = sorted(chunk["word_count"] for chunk in chunks)
    count = len(sizes)
    median = (sizes[(count - 1) // 2] + sizes[count // 2]) / 2
    report = {"schema_version": 1, "total_chunks": count,
              "section_count": sum(coverage.values()),
              "word_counts": {"min": sizes[0], "median": median,
                              "p90": sizes[(9 * count + 9) // 10 - 1], "max": sizes[-1]},
              "p90_method": "nearest rank", "split_sections": splits,
              "chunks_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
              "clean_sha256": hashlib.sha256(clean.encode("utf-8")).hexdigest(),
              "config_sha256": hashlib.sha256((BASE / "chunking.json").read_bytes()).hexdigest()}
    (BASE / "data/chunks.jsonl").write_text(payload, encoding="utf-8")
    (BASE / "data/chunk_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Chunks: {count}; words min/median/p90/max: "
          f"{sizes[0]}/{median:g}/{report['word_counts']['p90']}/{sizes[-1]}")
    print(f"Split sections: {', '.join(s['section_id'] for s in splits)}")
    print(f"chunks.jsonl SHA-256: {report['chunks_sha256']}")


if __name__ == "__main__":
    main()
