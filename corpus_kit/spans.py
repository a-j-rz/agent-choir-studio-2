"""Locating and recording spans of a source: unique markers, balanced brackets, the ledger."""

import bisect
import re


def nc(text) -> int:
    """The number of non-whitespace characters (spaces, tabs and newlines are not counted)."""
    return sum(not c.isspace() for c in text)


def unique(s, marker, lo=0, hi=None) -> int:
    """The offset of `marker` in s[lo:hi]; raises unless it occurs there exactly once."""
    hi = len(s) if hi is None else hi
    p = s.find(marker, lo, hi)
    if p < 0 or s.find(marker, p + len(marker), hi) >= 0:
        raise ValueError(f'Marker not unique in region: {marker!r}')
    return p


def balanced(s, start, left, right, limit) -> int:
    """The offset just after the `right` that closes the `left` at `start`, counting nesting,
    searching no further than `limit`; raises if it does not close before `limit`."""
    depth = 0
    for i in range(start, limit):
        if s[i] == left:
            depth += 1
        elif s[i] == right:
            depth -= 1
            if depth == 0:
                return i + 1
    raise ValueError(f'Unbalanced {left} at offset {start}')


class Ledger:
    """Every categorised span stripped from one source, with the record the strip report keeps.

    Guarantees: an empty span is rejected; entries iterate as (start, end, record) in insertion
    order until check_overlap() sorts them by start (stable); check_overlap() raises on the
    first overlap. Rendering and heading rules stay in the recipe.
    """

    def __init__(self, s):
        self.s = s
        self._newlines = [-1] + [m.start() for m in re.finditer('\n', s)]
        self.entries = []

    def line(self, p) -> int:
        """The 1-based LF line of offset p."""
        return bisect.bisect_left(self._newlines, p)

    def add(self, a, b, category):
        if a >= b:
            raise ValueError(f'Empty span: {category}')
        t = self.s[a:b]
        self.entries.append((a, b, {'category': category, 'start_marker': t[:60],
                                    'end_marker': t[-60:],
                                    'lf_line_range': [self.line(a), self.line(b - 1)],
                                    'token_count': len(t.split()),
                                    'non_whitespace_chars': nc(t), 'first_60': t[:60]}))

    def __iter__(self):
        return iter(self.entries)

    def check_overlap(self):
        """Sort the entries by start (stable) and raise on the first pair that overlaps."""
        self.entries.sort(key=lambda v: v[0])
        for prev, cur in zip(self.entries, self.entries[1:]):
            if prev[1] > cur[0]:
                raise ValueError(f'Overlapping ledger {prev[2]} / {cur[2]}')


def contamination(text, terms) -> list:
    """The terms that occur in `text`, in the order given."""
    return [x for x in terms if x in text]
