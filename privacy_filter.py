"""Optional model-based PII redaction using ``openai/privacy-filter``.

The deterministic pipeline always runs regex redaction (:mod:`redaction`). On the
Hugging Face Space GPU this module adds a second pass: a token-classification
model (``openai/privacy-filter``) flags personal or sensitive spans that regex
patterns miss — names, phone numbers, postal addresses, and the like — and masks
them with typed placeholders.

Heavy imports (``torch``/``transformers``) load lazily so the deterministic
analyzer, the test suite, and local development keep working without GPU
dependencies. If the model cannot be loaded, the caller falls back to regex-only
redaction and records the reason in the privacy notes.
"""

from __future__ import annotations

import functools
import time
from collections import Counter
from typing import Any, Callable

from model_runtime import resolve_device
from profiling import get_logger
from redaction import RedactionResult

logger = get_logger()


PRIVACY_MODEL_ID = "openai/privacy-filter"

# Only mask spans the model is reasonably confident about.
PRIVACY_MIN_SCORE = 0.5

# Model entity group -> (placeholder written into the text, human label for notes).
PII_TYPES: dict[str, tuple[str, str]] = {
    "private_person": ("[REDACTED_NAME]", "personal name"),
    "private_email": ("[REDACTED_EMAIL]", "email address"),
    "private_phone": ("[REDACTED_PHONE]", "phone number"),
    "private_address": ("[REDACTED_ADDRESS]", "postal address"),
    "private_url": ("[REDACTED_URL]", "personal URL"),
    "private_date": ("[REDACTED_DATE]", "personal date"),
    "account_number": ("[REDACTED_ACCOUNT]", "account number"),
    "secret": ("[REDACTED_SECRET]", "secret"),
}

# (texts) -> per-text list of {"start", "end", "label"} spans.
DetectFn = Callable[[list[str]], list[list[dict[str, Any]]]]

_PIPELINE_CACHE: dict[str, Any] = {}


def redact_texts(
    texts: list[str],
    *,
    detect: DetectFn | None = None,
    device: str | None = None,
) -> list[RedactionResult]:
    """Detect and mask PII in each text, returning one result per input.

    ``detect`` defaults to :func:`_local_detect` (the lazy model); tests inject a
    stand-in so the masking logic runs without ``torch``. ``device`` forces the
    compute device for the default detector (``cuda`` / ``mps`` / ``cpu``).
    """

    detector = detect or functools.partial(_local_detect, device=device)
    spans_per_text = detector(texts)
    return [_apply_spans(text, spans) for text, spans in zip(texts, spans_per_text)]


def _merge_spans(text: str, spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop malformed spans and merge same-label runs into clean, disjoint spans.

    ``openai/privacy-filter`` uses BIOES tags, which the pipeline's IOB-oriented
    "simple" aggregation can split into adjacent fragments of one entity (and a
    leading separator can leave a one-character gap). Merging same-label spans
    that overlap or sit within one character keeps each entity to a single
    placeholder; a remaining different-label overlap is clipped to stay disjoint.
    """

    valid = [
        span
        for span in spans
        if span.get("label") in PII_TYPES
        and 0 <= int(span["start"]) < int(span["end"]) <= len(text)
    ]
    valid.sort(key=lambda span: (int(span["start"]), int(span["end"])))

    merged: list[dict[str, Any]] = []
    for span in valid:
        start, end, label = int(span["start"]), int(span["end"]), span["label"]
        if merged:
            prev = merged[-1]
            if label == prev["label"] and start <= prev["end"] + 1:
                prev["end"] = max(prev["end"], end)
                continue
            if start < prev["end"]:  # different-label overlap: keep them disjoint
                start = prev["end"]
                if start >= end:
                    continue
        merged.append({"start": start, "end": end, "label": label})
    return merged


def _apply_spans(text: str, spans: list[dict[str, Any]]) -> RedactionResult:
    """Replace detected spans with typed placeholders, right-to-left."""

    counts: Counter[str] = Counter()
    redacted = text
    for span in sorted(_merge_spans(text, spans), key=lambda span: span["start"], reverse=True):
        placeholder, label = PII_TYPES[span["label"]]
        redacted = redacted[: span["start"]] + placeholder + redacted[span["end"] :]
        counts[label] += 1

    notes = [f"{label}: {count}" for label, count in sorted(counts.items())]
    return RedactionResult(text=redacted, notes=notes, count=sum(counts.values()))


def _local_detect(texts: list[str], device: str | None = None) -> list[list[dict[str, Any]]]:
    """Run ``openai/privacy-filter`` and return confident PII spans per text.

    Imported lazily: ``transformers``/``torch`` only need to exist where the
    model actually runs, never for the deterministic path, tests, or light local
    development.
    """

    pipe = _load_pipeline(device=device)
    started = time.perf_counter()
    results: list[list[dict[str, Any]]] = []
    for text in texts:
        if not text.strip():
            results.append([])
            continue
        entities = pipe(text)
        spans = [
            {
                "start": int(entity["start"]),
                "end": int(entity["end"]),
                "label": entity["entity_group"],
            }
            for entity in entities
            if entity.get("entity_group") in PII_TYPES
            and entity.get("start") is not None
            and entity.get("end") is not None
            and float(entity.get("score", 1.0)) >= PRIVACY_MIN_SCORE
        ]
        results.append(spans)
    detected = sum(len(spans) for spans in results)
    logger.debug(
        "privacy-filter scanned %d messages, %d raw spans in %.2fs",
        len(texts),
        detected,
        time.perf_counter() - started,
    )
    return results


def _load_pipeline(device: str | None = None) -> Any:
    """Lazily build and cache the token-classification pipeline per device."""

    resolved = resolve_device(device)
    cached = _PIPELINE_CACHE.get(resolved)
    if cached is not None:
        return cached

    from transformers import pipeline

    # transformers pipeline device: 0 for cuda, "mps"/"cpu" otherwise.
    pipe_device = 0 if resolved == "cuda" else resolved
    started = time.perf_counter()
    pipe = pipeline(
        "token-classification",
        model=PRIVACY_MODEL_ID,
        aggregation_strategy="simple",
        device=pipe_device,
    )
    logger.info(
        "loaded %s on %s in %.1fs", PRIVACY_MODEL_ID, resolved, time.perf_counter() - started
    )
    _PIPELINE_CACHE[resolved] = pipe
    return pipe
