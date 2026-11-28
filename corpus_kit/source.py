"""Pinned sources: load or fetch, verify, normalise; and the Gutenberg envelope."""

import hashlib
from pathlib import Path
import re
from urllib.parse import urlparse
from urllib.request import urlopen

ALLOWED_HOST = "www.gutenberg.org"  # no mirrors: a different source is a new pin, set by hand


def load_pinned(path, url, sha256) -> str:
    """The pinned source as LF text, verified against its SHA-256.

    Guarantees: a URL whose host is not www.gutenberg.org is rejected before anything else, so
    no fetch can reach a mirror. If `path` exists its bytes are used; otherwise `url` is fetched
    and written to `path` only after the bytes verify. Either way the bytes must match `sha256`
    (the error names both hashes). Decoded as UTF-8, CRLF converted to LF.
    """
    host = urlparse(url).hostname
    if host != ALLOWED_HOST:
        raise ValueError(f"Source URL host {host!r} is not {ALLOWED_HOST}: {url}")
    path = Path(path)
    if path.exists():
        payload = path.read_bytes()
    else:
        with urlopen(url, timeout=60) as response:
            payload = response.read()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != sha256:
            raise ValueError(f"Downloaded SHA-256 mismatch for {path.name}: expected {sha256}, "
                             f"got {digest}; raw file was not written")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    if digest != sha256:
        raise ValueError(f"Raw SHA-256 mismatch for {path.name}: expected {sha256}, got {digest}")
    return payload.decode("utf-8").replace("\r\n", "\n")


def envelope(text) -> tuple[int, int]:
    """(start, end): start is the offset just after the text of the single `*** START OF` line
    (its newline is not consumed); end is the offset where the single `*** END OF` line begins.
    Raises unless each line appears exactly once."""
    start_match = list(re.finditer(r"(?m)^\*\*\* START OF .*$", text))
    end_match = list(re.finditer(r"(?m)^\*\*\* END OF .*$", text))
    if len(start_match) != 1 or len(end_match) != 1:
        raise ValueError("Gutenberg envelope")
    return start_match[0].end(), end_match[0].start()
