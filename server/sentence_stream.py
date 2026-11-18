"""Split streamed model text into sentences for per-sentence TTS (N3b).

Feed text deltas as they arrive; complete sentences come back as soon as the
model has written the whitespace after their final punctuation. Very short
fragments ("I see.") are held and merged into the next sentence, because each
TTS request has a fixed cost and a tiny clip would leave a gap before the next.
"""

import re
from collections.abc import Iterator

# End punctuation, optional closing quote/bracket, then whitespace.
_BOUNDARY = re.compile(r"[.!?\u2026]+[\"'\u201d\u2019)\]]*\s+")
_ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "st", "vs", "etc", "e.g", "i.e", "approx", "no"}
MIN_SENTENCE_CHARS = 12


def _ends_with_abbreviation(text: str) -> bool:
    words = text.split()
    if not words:
        return False
    last = words[-1].rstrip(".").lower()
    # Single letters cover initials ("J. R. R. Tolkien").
    return last in _ABBREVIATIONS or (len(last) == 1 and last.isalpha())


class SentenceSplitter:
    def __init__(self, min_chars: int = MIN_SENTENCE_CHARS) -> None:
        self._buffer = ""
        self._min_chars = min_chars

    def feed(self, delta: str) -> Iterator[str]:
        """Add a text delta; yield any sentences it completes."""
        self._buffer += delta
        start = 0
        for match in _BOUNDARY.finditer(self._buffer):
            candidate = self._buffer[start : match.end()].strip()
            if len(candidate) < self._min_chars or _ends_with_abbreviation(candidate):
                continue
            yield candidate
            start = match.end()
        self._buffer = self._buffer[start:]

    def flush(self) -> Iterator[str]:
        """Yield whatever is left once the stream has ended."""
        rest = self._buffer.strip()
        self._buffer = ""
        if rest:
            yield rest
