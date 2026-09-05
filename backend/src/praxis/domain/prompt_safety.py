"""Detect recognizable pasted credentials without recording matched content."""

import re
from collections.abc import Mapping
from typing import cast

# This is accidental-disclosure screening, not a general secret or PII detector.
# Assignment rules also reject examples: users can describe authentication without values.
_SECRET_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})\b",
        r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,255}\b",
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----",
        r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",
        r"(?i)\bauthorization\s*[:=]\s*[\"']?(?:bearer|basic)\s+\S+",
        r"(?i)\b(?:password|passwd|api[_ -]?key|client[_ -]?secret|"
        r"aws_secret_access_key|aws_session_token|access[_ -]?token|refresh[_ -]?token)"
        r"\b[\"']?\s*[:=]\s*[\"']?[^\s\"',;}]+",
    )
)


def contains_likely_secret(text: str) -> bool:
    """Return only a detection flag; never return the credential or its location."""
    return any(pattern.search(text) is not None for pattern in _SECRET_PATTERNS)


class SensitiveInputError(ValueError):
    """Recognizable credentials were found in content intended for a model."""


def require_safe_content(value: object) -> None:
    """Screen JSON-like input before validation can include it in diagnostics."""
    if isinstance(value, str):
        if contains_likely_secret(value):
            raise SensitiveInputError(
                "Content appears to contain credentials; remove them and retry."
            )
    elif isinstance(value, Mapping):
        for key, item in cast("Mapping[object, object]", value).items():
            require_safe_content(key)
            if isinstance(key, str) and isinstance(item, str):
                require_safe_content(f"{key}={item}")
            require_safe_content(item)
    elif isinstance(value, (list, tuple)):
        for item in cast("list[object] | tuple[object, ...]", value):
            require_safe_content(item)
