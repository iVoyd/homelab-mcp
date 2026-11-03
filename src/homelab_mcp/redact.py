"""Strip secrets from tool output before it reaches the model."""

from __future__ import annotations

import re
from typing import Any

# Order matters: specific token formats first, generic key=value last.
BUILTIN_PATTERNS: list[tuple[str, str]] = [
    (r"sk-ant-[A-Za-z0-9_\-]{10,}", "[REDACTED:anthropic_key]"),
    (r"\bsk-[A-Za-z0-9_\-]{20,}", "[REDACTED:api_key]"),
    (r"\bgh[pousr]_[A-Za-z0-9]{20,}", "[REDACTED:github_token]"),
    (r"\bgithub_pat_[A-Za-z0-9_]{20,}", "[REDACTED:github_token]"),
    (r"\bAKIA[0-9A-Z]{16}\b", "[REDACTED:aws_key]"),
    (r"\bxox[abprs]-[A-Za-z0-9\-]{10,}", "[REDACTED:slack_token]"),
    (r"\beyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]*", "[REDACTED:jwt]"),
    (r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/\-]{8,}=*", r"\1 [REDACTED]"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
     "[REDACTED:private_key]"),
    (r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", "[REDACTED:email]"),
    # KEY=value / "key": "value" style assignments for secret-looking names.
    (
        r"(?i)\b(?![0-9])([A-Za-z0-9_]*(?:api[_-]?key|token|secret|passw(?:or)?d|credential)s?)"
        r"(\"?\s*[:=]\s*\"?)(?!\[REDACTED)([^\s\"',;]+)",
        r"\1\2[REDACTED]",
    ),
]


class Redactor:
    def __init__(self, extra_patterns: list[str] | None = None):
        self.rules = [(re.compile(p), r) for p, r in BUILTIN_PATTERNS]
        for pattern in extra_patterns or []:
            self.rules.append((re.compile(pattern), "[REDACTED]"))

    def text(self, value: str) -> str:
        for regex, replacement in self.rules:
            value = regex.sub(replacement, value)
        return value

    def any(self, value: Any) -> Any:
        """Redact every string inside nested dicts/lists/tuples."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {k: self.any(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.any(v) for v in value]
        return value
