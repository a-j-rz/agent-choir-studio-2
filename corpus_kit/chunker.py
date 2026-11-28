"""Section chunking: the midpoint splitter, the end-of-chunk check, word statistics, serialising."""

import hashlib
import json
import re

INITIALS = re.compile(r'^(?:[A-Z]\.)+$')


def words(text) -> int:
    """Whitespace-delimited tokens, punctuation-only tokens included."""
    return len(text.split())


def split_section(text, maximum, abbreviations=frozenset(), initials=False) -> list:
    """Split `text` into pieces of at most `maximum` words, recursively at the boundary closest
    to half the words: a paragraph break; else a sentence boundary; else just after a semicolon
    followed by whitespace. Raises if no permitted boundary exists. Order and text are kept.

    With the defaults, every sentence boundary is permitted (Marcus's splitter). A sentence
    boundary after a token that ends in a full stop is excluded when the token minus its stop is
    in `abbreviations`, or, with `initials=True`, when the token is uppercase initials such as
    `E.` or `C.S.` (Darwin's splitter).
    """
    if words(text) <= maximum:
        return [text]
    boundaries = [match.start() for match in re.finditer(r"\n\n", text)]
    if not boundaries:
        # A capital after terminal punctuation is a sentence boundary here.
        boundaries = [match.start() for match in re.finditer(
            r'''(?<=[.!?])\s+(?=["'\[]?[A-Z])''', text)
            if not (text[:match.start()].endswith('.') and
                    (text[:match.start()].split()[-1][:-1] in abbreviations or
                     (initials and INITIALS.fullmatch(text[:match.start()].split()[-1]))))]
    if not boundaries:
        # Last resort: just after a semicolon followed by whitespace.
        boundaries = [match.end() for match in re.finditer(r";(?=\s)", text)]
    if not boundaries:
        raise ValueError("A sentence exceeds max_words with no semicolon; "
                         "no permitted split boundary")
    midpoint = words(text) / 2
    cut = min(boundaries, key=lambda pos: (abs(words(text[:pos]) - midpoint), pos))
    return (split_section(text[:cut].strip(), maximum, abbreviations, initials)
            + split_section(text[cut:].strip(), maximum, abbreviations, initials))


def end_check(pieces, end_abbreviations, initials):
    """An independent check on the splitter's output. `pieces` is [(chunk_id, text), ...] for
    one section; every piece but the last must not end on an abbreviation in
    `end_abbreviations` (with or without its stop) or, with `initials`, on uppercase initials.
    Raises naming the chunk id and the token."""
    for chunk_id, piece in pieces[:-1]:
        last = piece.split()[-1]
        if last.removesuffix('.') in end_abbreviations or (initials and INITIALS.fullmatch(last)):
            raise ValueError(f'Abbreviation at chunk end: {chunk_id}: {last}')


def word_stats(chunks) -> dict:
    """{min, median, p90, max} of the chunks' word_count; p90 by nearest rank."""
    sizes = sorted(c['word_count'] for c in chunks)
    n = len(sizes)
    return {'min': sizes[0], 'median': (sizes[(n - 1) // 2] + sizes[n // 2]) / 2,
            'p90': sizes[(9 * n + 9) // 10 - 1], 'max': sizes[-1]}


def serialise(chunks) -> tuple[str, str]:
    """(payload, sha256): one JSON object per line, ensure_ascii off; the SHA-256 of its UTF-8."""
    payload = ''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in chunks)
    return payload, hashlib.sha256(payload.encode('utf-8')).hexdigest()
