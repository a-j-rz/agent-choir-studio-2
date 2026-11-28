"""Unit tests for the recipe kit, on synthetic strings only: no raw files, no network.

    python -m corpus_kit.selftest

Each check's work runs inside check(): an exception raised there is reported as a FAIL line with
its text, and the remaining checks still run.
"""

import hashlib
from pathlib import Path
import sys
import tempfile

from corpus_kit import chunker, source, spans

failures = []


def check(label, body):
    """Run body() -> ok or (ok, detail); any exception it raises is a FAIL with its text."""
    try:
        result = body()
        ok, detail = result if isinstance(result, tuple) else (result, "")
    except Exception as error:  # noqa: BLE001 — a crash in a check is that check's failure
        ok, detail = False, f"raised {type(error).__name__}: {error}"
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def raises(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError as error:
        return str(error)
    return None


def test_spans():
    print("\nspans")
    s = "xAyA"
    check("unique: found once", lambda: spans.unique("abc", "b") == 1)
    check("unique: absent raises", lambda: raises(spans.unique, "abc", "z") is not None)
    check("unique: found twice raises", lambda: raises(spans.unique, s, "A") is not None)
    check("unique: respects lo and hi",
          lambda: spans.unique(s, "A", 2) == 3 and spans.unique(s, "A", 0, 2) == 1)
    check("balanced: a nested span closes at the right offset",
          lambda: spans.balanced("(a(b)c)d", 0, "(", ")", 8) == 7)
    check("balanced: an unclosed span raises",
          lambda: raises(spans.balanced, "(a(b)c", 0, "(", ")", 6) is not None)
    check("balanced: limit is honoured",
          lambda: raises(spans.balanced, "(ab)", 0, "(", ")", 3) is not None)
    check("Ledger: rejects an empty span",
          lambda: raises(spans.Ledger("abcdef").add, 2, 2, "x") is not None)

    def overlapping():
        ledger = spans.Ledger("abcdef")
        ledger.add(0, 3, "a")
        ledger.add(2, 5, "b")
        return raises(ledger.check_overlap) is not None
    check("Ledger: rejects overlapping spans", overlapping)
    check("nc: ignores spaces, tabs and newlines", lambda: spans.nc("a b\tc\nd \n") == 4)


def test_source():
    print("\nsource")
    text = "head\n*** START OF X ***\nbody\n*** END OF X ***\ntail"
    check("envelope: found once",
          lambda: source.envelope(text) == (text.index(" ***\n") + 4, text.index("*** END")))
    check("envelope: missing raises", lambda: raises(source.envelope, "no envelope") is not None)
    check("envelope: duplicated raises",
          lambda: raises(source.envelope, text + "\n*** START OF Y ***\n") is not None)

    url = "https://www.gutenberg.org/cache/epub/1/pg1.txt"
    payload = b"line one\r\nline two\r\n"
    good = hashlib.sha256(payload).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pg1.txt"
        path.write_bytes(payload)
        check("load_pinned: a matching local file loads, CRLF converted",
              lambda: source.load_pinned(path, url, good) == "line one\nline two\n")

        def mismatch():
            error = raises(source.load_pinned, path, url, "0" * 64)
            return error is not None and good in error and "0" * 64 in error, f"{error}"
        check("load_pinned: a mismatched hash raises, naming both", mismatch)

        def host_rejected():
            calls = []
            real = source.urlopen
            source.urlopen = lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(
                AssertionError("network reached"))
            try:
                missing = Path(tmp) / "absent.txt"
                error = raises(source.load_pinned, missing, "https://mirror.example.org/pg1.txt",
                               good)
            finally:
                source.urlopen = real
            return error is not None and calls == [] and not missing.exists(), f"{error}"
        check("load_pinned: a non-gutenberg.org URL is rejected before any network call",
              host_rejected)


def test_chunker():
    print("\nchunker")
    split = chunker.split_section
    check("under maximum: returned unchanged",
          lambda: split("one two three", 5) == ["one two three"])
    text = "One two. Three four.\n\nFive six seven eight."
    check("a paragraph boundary is preferred",
          lambda: (split(text, 5) == ["One two. Three four.", "Five six seven eight."],
                   f"{split(text, 5)}"))
    check("sentence fallback", lambda: split("One two three. Four five six.", 4)
          == ["One two three.", "Four five six."])
    check("semicolon fallback", lambda: split("one two three; four five six", 4)
          == ["one two three;", "four five six"])
    check("no boundary raises", lambda: raises(split, "one two three four five", 2) is not None)
    filler = " ".join(f"a{i}" for i in range(1, 10))
    tail = " ".join(f"b{i}" for i in range(1, 9)) + " b9. C1."
    mr = f"{filler} Mr. Brown {tail}"  # 21 words; the boundary after "Mr." is nearest midpoint
    check("defaults: a cut is allowed after 'Mr.'",
          lambda: (split(mr, 20)[0].endswith("Mr."), f"{split(mr, 20)}"))
    check("abbreviations={'Mr'}: no cut lands after 'Mr.'",
          lambda: (not any(p.endswith("Mr.") for p in split(mr, 20, abbreviations={"Mr"})[:-1]),
                   f"{split(mr, 20, abbreviations={'Mr'})}"))
    initial = f"{filler} E. Brown {tail}"
    check("defaults: a cut is allowed after 'E.'",
          lambda: (split(initial, 20)[0].endswith("E."), f"{split(initial, 20)}"))
    check("initials=True: no cut lands after 'E.'",
          lambda: (not any(p.endswith("E.") for p in split(initial, 20, initials=True)[:-1]),
                   f"{split(initial, 20, initials=True)}"))
    check("end_check: raises naming the chunk id",
          lambda: "c-p1" in (raises(chunker.end_check, [("c-p1", "ends Mr."), ("c-p2", "x")],
                                    frozenset({"Mr"}), True) or ""))

    def stats():
        got = chunker.word_stats([{"word_count": n} for n in (5, 1, 3, 2, 4, 10, 7, 6, 9, 8)])
        return got == {"min": 1, "median": 5.5, "p90": 9, "max": 10}, f"{got}"
    check("word_stats: 1..10 gives min 1, median 5.5, p90 9, max 10", stats)

    def serialised():
        payload, sha = chunker.serialise([{"a": "é"}])
        return (payload == '{"a": "é"}\n'
                and sha == hashlib.sha256(payload.encode("utf-8")).hexdigest())
    check("serialise: one JSON line, non-ASCII kept, SHA-256 of its UTF-8", serialised)


def main():
    test_spans()
    test_source()
    test_chunker()
    print("\nSELFTEST", "PASSED" if not failures else f"FAILED ({len(failures)})")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
