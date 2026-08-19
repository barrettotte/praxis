"""Shared text normalization for deterministic catalog matching."""

import re

TOKEN_PATTERN = re.compile(r"[^\W_]+(?:[+#.]+)?", flags=re.UNICODE)
STOP_WORDS = frozenset({"a", "an", "and", "for", "in", "of", "on", "the", "to", "with"})


def normalize_text(value: str) -> str:
    """Normalize user and catalog text for case-insensitive comparisons."""
    return " ".join(value.casefold().split())


def tokenize(value: str) -> frozenset[str]:
    """Return distinct meaningful terms from normalized text."""
    return frozenset(
        token
        for token in TOKEN_PATTERN.findall(normalize_text(value))
        if token not in STOP_WORDS and len(token) > 1
    )
