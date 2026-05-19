# SMS messages are limited to 160 characters per segment (GSM-7).
from functools import lru_cache

MAX_SEGMENT_CHARS = 160


def min_sms_segments(message: str) -> int:
    """Return the minimum number of SMS segments needed to deliver *message*
    without splitting any word across segment boundaries."""
    if not message or not message.strip():
        return 0
    words = tuple(message.split())
    return _min_segments_from(words, 0)


@lru_cache(maxsize=1024)
def _min_segments_from(words: tuple[str, ...], start: int) -> int:
    """DP helper: minimum segments to deliver words[start:]."""
    if start >= len(words):
        return 0

    best: int | None = None
    current_len = 0

    for end in range(start, len(words)):
        word_len = len(words[end])
        add = word_len if current_len == 0 else word_len + 1  # +1 for space
        if current_len + add > MAX_SEGMENT_CHARS:
            if end == start:
                # Single word exceeds limit — forced into its own segment.
                return _min_segments_from(words, start + 1) + 1
            break
        current_len += add
        candidate = _min_segments_from(words, end + 1) + 1
        if best is None or candidate < best:
            best = candidate

    return best if best is not None else 0


def banana_count() -> int:
    return 42
