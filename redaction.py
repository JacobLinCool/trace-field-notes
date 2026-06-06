"""Privacy-preserving redaction helpers for uploaded traces."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass


@dataclass(slots=True)
class RedactionResult:
    text: str
    notes: list[str]
    count: int


_REDACTION_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "authorization bearer token",
        re.compile(r"(?i)\b(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~+/=-]{12,}"),
        r"\1[REDACTED_BEARER_TOKEN]",
    ),
    (
        "GitHub token",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b"),
        "[REDACTED_GITHUB_TOKEN]",
    ),
    (
        "GitHub fine-grained token",
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
        "[REDACTED_GITHUB_TOKEN]",
    ),
    (
        "OpenAI API key",
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
        "[REDACTED_OPENAI_KEY]",
    ),
    (
        "Hugging Face token",
        re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
        "[REDACTED_HF_TOKEN]",
    ),
    (
        "GitLab token",
        re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
        "[REDACTED_GITLAB_TOKEN]",
    ),
    (
        "AWS access key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "[REDACTED_AWS_ACCESS_KEY]",
    ),
    (
        "Slack token",
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
        "[REDACTED_SLACK_TOKEN]",
    ),
    (
        "private key block",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
            re.MULTILINE,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (
        "email address",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED_EMAIL]",
    ),
    (
        "macOS user path",
        re.compile(r"/Users/[^/\s]+/[^\s`'\"<>)]*"),
        "/Users/[REDACTED_USER]/[REDACTED_PATH]",
    ),
    (
        "Linux home path",
        re.compile(r"/home/[^/\s]+/[^\s`'\"<>)]*"),
        "/home/[REDACTED_USER]/[REDACTED_PATH]",
    ),
    (
        "Windows user path",
        re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+\\[^\s`'\"<>)]*"),
        r"C:\\Users\\[REDACTED_USER]\\[REDACTED_PATH]",
    ),
    (
        "URL query string",
        re.compile(r"\b(https?://[^\s`'\"<>?]+)\?[^\s`'\"<>)]*"),
        r"\1?[REDACTED_QUERY]",
    ),
    (
        "long base64-like secret",
        re.compile(r"\b[A-Za-z0-9+/]{48,}={0,2}\b"),
        "[REDACTED_LONG_TOKEN]",
    ),
]


def redact_text(text: str) -> RedactionResult:
    """Redact likely secrets while preserving surrounding prose and layout."""

    counts: Counter[str] = Counter()
    redacted = text
    for label, pattern, replacement in _REDACTION_PATTERNS:
        redacted, substitutions = pattern.subn(replacement, redacted)
        if substitutions:
            counts[label] += substitutions

    notes = [f"{label}: {count}" for label, count in sorted(counts.items())]
    return RedactionResult(text=redacted, notes=notes, count=sum(counts.values()))
