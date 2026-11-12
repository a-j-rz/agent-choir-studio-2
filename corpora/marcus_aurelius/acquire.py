"""Read/download pinned raw text and manifest; write clean Thoughts and strip report.

Run from the repository root. Only data/ contains source or generated text.
"""

import hashlib
import json
from pathlib import Path
import re
from urllib.request import urlopen


BASE = Path("corpora/marcus_aurelius")
ROMANS = "I II III IV V VI VII VIII IX X XI XII".split()
MARKER = r"\[[A-Z]\]"
NOTE_START = r"^(?:    )?\[([A-Z])\] "
ATTRIBUTION = r"^\s+(?:HESIOD,|_Odyssey_,).*$"


def normalized(text):
    return re.sub(r"\s+", " ", text).strip()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def strip_notes(body):
    kept, notes, markers, attributions, illustrations = [], [], [], [], []
    in_note = False
    for paragraph in re.split(r"\n\s*\n", body.strip("\n")):
        start = re.match(NOTE_START, paragraph)
        if start:
            notes.append({"marker": start[1], "text": normalized(paragraph)})
            in_note = True
        elif in_note and paragraph.startswith("    "):
            notes[-1]["text"] += "\n\n" + normalized(paragraph)
        else:
            in_note = False
            if re.fullmatch(r"\[Illustration: [^\]]+\]", paragraph):
                illustrations.append(paragraph)
                continue
            lines = []
            for line in paragraph.splitlines():
                if re.match(ATTRIBUTION, line):
                    attributions.append(normalized(line))
                else:
                    lines.append(line)
            text = normalized("\n".join(lines))
            markers.extend(re.findall(MARKER, text))
            text = re.sub(MARKER, "", text)
            if text:
                kept.append(text)
    labels = ["[" + note["marker"] + "]" for note in notes]
    if sorted(markers) != sorted(labels):
        raise ValueError(f"Footnote marker/body mismatch: {len(markers)} / {len(notes)}")
    return "\n\n".join(kept), notes, markers, attributions, illustrations


def sections(body):
    matches = list(re.finditer(r"(?m)^(\d+)\. ", body))
    numbers = [int(match[1]) for match in matches]
    if numbers != list(range(2, len(numbers) + 2)):
        raise ValueError(f"Section gap or duplicate: {numbers}")
    starts = [0] + [match.end() for match in matches]
    ends = [match.start() for match in matches] + [len(body)]
    result = [body[start:end].strip() for start, end in zip(starts, ends)]
    if not all(result):
        raise ValueError("Empty section")
    return result


def strip_source(source, manifest):
    start = source.index("\nI.\n") + 1
    end = source.index("\nINDEXES.\n", start)
    body = source[start:end]
    headings = list(re.finditer(r"(?m)^([IVX]+)\.$", body))
    if [match[1] for match in headings] != ROMANS:
        raise ValueError("Expected exactly Books I–XII in order")
    output, coverage, insertions, examples = [], [], [], []
    all_notes, all_markers, all_attributions, all_illustrations = [], [], [], []
    for book, heading in enumerate(headings, 1):
        stop = headings[book].start() if book < 12 else len(body)
        raw_book = body[heading.end():stop]
        cleaned, notes, markers, attributions, illustrations = strip_notes(raw_book)
        all_notes.extend(notes)
        all_markers.extend(markers)
        all_attributions.extend(attributions)
        all_illustrations.extend(illustrations)
        place = next((p["clean"] for p in manifest["chronology"]["place_notes"]
                      if p["book"] == book), None)
        if place:
            if not cleaned.endswith("\n\n" + place):
                raise ValueError(f"Missing place-note in Book {book}")
            cleaned = cleaned[:-(len(place) + 2)]
        entries = sections(cleaned)
        coverage.append({"book": book, "sections": len(entries), "sequence_valid": True})
        output.append(f"Book {ROMANS[book - 1]}")
        for section, text in enumerate(entries, 1):
            locator = f"Book {ROMANS[book - 1]}, {section}"
            output.append(f"{section}. {text}")
            for match in re.finditer(r"\[[^\[\]]*\]|\([^()]*\)", text):
                insertions.append({"locator": locator, "kind": "square" if match[0][0] == "["
                                   else "parenthetical", "text": match[0]})
        if place:
            output.append(place)
        if book == 1:
            for before in re.split(r"(?m)^\d+\. ", raw_book.strip())[:3]:
                examples.append({"before": normalized(before),
                                 "after": re.sub(MARKER, "", normalized(before))})
    clean = "\n\n".join(output) + "\n"
    forbidden = ["Project Gutenberg", "BIOGRAPHICAL SKETCH", "PHILOSOPHY OF",
                 "INDEX OF TERMS", "GENERAL INDEX", "Illustration:"]
    contamination = {term: len(re.findall(re.escape(term), clean, re.I)) for term in forbidden}
    contamination[MARKER] = len(re.findall(MARKER, clean))
    if any(contamination.values()):
        raise ValueError(f"Contamination: {contamination}")
    report = {"schema_version": 1, "coverage": coverage, "contamination": contamination,
              "footnote_marker_regex": MARKER, "markers_removed": len(all_markers),
              "note_bodies_removed": len(all_notes), "footnote_mismatch": False,
              "footnote_examples": examples, "editorial_attributions_removed": all_attributions,
              "body_illustrations_removed": all_illustrations,
              "square_bracket_count": sum(i["kind"] == "square" for i in insertions),
              "parenthetical_count": sum(i["kind"] == "parenthetical" for i in insertions),
              "insertion_candidates": insertions,
              "insertion_count_caveat": "Syntactic candidates, not an authorship classification; parentheses include inline references.",
              "source_sha256": manifest["source_provenance"]["sha256"]}
    return clean, report


def main():
    manifest = json.loads((BASE / "manifest.json").read_text(encoding="utf-8"))
    provenance = manifest["source_provenance"]
    raw = BASE / "data/raw/pg15877.txt"
    raw.parent.mkdir(parents=True, exist_ok=True)
    if not raw.exists():
        with urlopen(provenance["url"], timeout=60) as response:
            payload = response.read()
        if hashlib.sha256(payload).hexdigest() != provenance["sha256"]:
            raise ValueError("Downloaded source SHA-256 mismatch; raw file was not written")
        raw.write_bytes(payload)
    payload = raw.read_bytes()
    if hashlib.sha256(payload).hexdigest() != provenance["sha256"]:
        raise ValueError("Raw source SHA-256 mismatch; clean output was not written")
    clean, report = strip_source(payload.decode("utf-8").replace("\r\n", "\n"), manifest)
    target = BASE / "data/clean"
    target.mkdir(parents=True, exist_ok=True)
    (target / "thoughts.txt").write_text(clean, encoding="utf-8")
    write_json(target / "strip_report.json", report)
    print(f"Source SHA-256 verified: {provenance['sha256']}")
    print(f"Clean: 12 books, {sum(b['sections'] for b in report['coverage'])} sections; "
          f"footnotes {report['markers_removed']} markers / {report['note_bodies_removed']} bodies")


if __name__ == "__main__":
    main()
