"""Deterministic codebook analysis for coding-agent narrative traces."""

from __future__ import annotations

import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from model_runtime import MODEL_CHOICES, run_model_analysis
from parser import parse_trace
from profiling import Profiler, get_logger
from redaction import redact_text
from schemas import (
    APPRAISALS,
    DETOUR_TYPES,
    DIFFICULTY_TYPES,
    OUTCOME_CLAIMS,
    RECOVERY_PATTERNS,
    RESOLUTION_MODES,
    AnalysisResult,
    DifficultyEpisode,
    MessageSpan,
    NarrativeMessage,
)

logger = get_logger()


ANALYSIS_SCOPE = (
    "assistant narrative messages only, with user prompts included only as optional context; "
    "raw tool-call contents are ignored by default"
)

DIFFICULTY_SIGNALS = {
    "error",
    "failed",
    "failure",
    "fails",
    "problem",
    "issue",
    "bug",
    "blocked",
    "blocker",
    "cannot",
    "can't",
    "could not",
    "unclear",
    "ambiguous",
    "not sure",
    "risk",
    "regression",
    "compatibility",
    "however",
    "but",
    "unfortunately",
    "missing",
    "incomplete",
    "permission",
    "auth",
    "timeout",
    "dependency",
    "conflict",
    "mismatch",
    "unexpected",
    "verify",
    "verification",
    "test failing",
}

INTENTION_SIGNALS = {
    "i will",
    "i'll",
    "i am going to",
    "i'm going to",
    "next",
    "plan",
    "goal",
    "need to",
    "i need",
    "i should",
    "let me",
    "i'm checking",
    "i'm going",
    "i will inspect",
    "i'll inspect",
}

SHIFT_SIGNALS = {
    "instead",
    "alternative",
    "switch",
    "change approach",
    "narrow",
    "smaller",
    "decompose",
    "split",
    "break down",
    "roll back",
    "revert",
    "try another",
    "workaround",
    "safer",
    "different route",
    "verify with",
}

OUTCOME_SIGNALS = {
    "done",
    "fixed",
    "resolved",
    "complete",
    "implemented",
    "verified",
    "passes",
    "works",
    "unable",
    "could not",
    "still failing",
    "needs verification",
    "not verified",
    "caveat",
    "partial",
    "partially",
}

PROBLEM_EVIDENCE_SIGNALS = {
    "failed",
    "failure",
    "fails",
    "still failing",
    "test failing",
    "issue",
    "bug",
    "blocked",
    "blocker",
    "cannot",
    "can't",
    "could not",
    "unclear",
    "ambiguous",
    "not sure",
    "risk",
    "regression",
    "unfortunately",
    "missing",
    "incomplete",
    "permission",
    "dependency",
    "conflict",
    "mismatch",
    "unexpected",
}


ANALYSIS_STEPS = ("extract", "redact", "chart", "classify", "synthesize")


def _accumulate_notes(counter: Counter[str], notes: Iterable[str]) -> None:
    """Fold ``"label: count"`` note strings into a running counter."""

    for note in notes:
        label, _, count = note.partition(": ")
        counter[label] += int(count or 0)


def stream_deterministic_analysis(
    path: str | Path,
    *,
    include_user_context: bool = True,
    redact_secrets: bool = True,
    ignore_tool_calls: bool = True,
    model_redact=None,
    profiler: Profiler | None = None,
    stream_redact_progress: bool = False,
):
    """Run the deterministic pipeline as a generator.

    Yields ``("progress", info)`` after each real stage completes — ``info`` has
    a ``stage`` name (one of :data:`ANALYSIS_STEPS`) and the running ``messages``
    count — then a final ``("result", (AnalysisResult, str))``. Callers that
    don't care about progress can just drain it for the tuple.

    ``model_redact`` is an optional ``(list[str]) -> list[RedactionResult]``
    callable applied on top of regex redaction; the Server injects a GPU- or
    CPU-bound ``openai/privacy-filter`` pass. It is absent locally and in tests,
    so redaction falls back to regex only. ``profiler`` collects per-stage
    timings; one is created if not supplied.
    """

    prof = profiler or Profiler("deterministic")

    _started = time.perf_counter()
    parsed_messages, agent_type = parse_trace(
        path,
        include_user_context=include_user_context,
        ignore_tool_calls=ignore_tool_calls,
    )
    prof.record("extract", time.perf_counter() - _started)
    message_count = len(parsed_messages)
    prof.mark(messages=message_count, agent=agent_type)
    logger.info("parsed %d narrative messages (agent=%s)", message_count, agent_type)
    yield ("progress", {"stage": "extract", "messages": message_count})

    redaction_count = 0
    privacy_notes = [
        "Uploaded traces are processed for this request only; the app exports a redacted narrative text file.",
        "The analysis uses visible messages and does not inspect hidden reasoning.",
    ]
    if ignore_tool_calls:
        privacy_notes.append("Tool-call contents were ignored before analysis.")

    _redact_started = time.perf_counter()
    messages = parsed_messages
    if redact_secrets:
        all_notes: Counter[str] = Counter()
        redacted_messages: list[NarrativeMessage] = []
        model_used = False
        model_failed = False

        # Process in chunks so slow (CPU) runs can stream per-message progress.
        # Without streaming (ZeroGPU) it is a single chunk = one GPU allocation;
        # with streaming the update count is capped at ~30 regardless of size.
        if stream_redact_progress and message_count:
            chunk = max(1, (message_count + 29) // 30)
        else:
            chunk = message_count or 1

        for start in range(0, message_count, chunk):
            chunk_messages = parsed_messages[start : start + chunk]

            # Pass 1: deterministic regex redaction (always available).
            regex_results = [redact_text(message.text) for message in chunk_messages]
            texts = [red.text for red in regex_results]

            # Pass 2: optional model PII pass on top. The Server injects a GPU- or
            # CPU-bound openai/privacy-filter pass; it is absent locally and in
            # tests, so regex-only redaction is used. Once it is unavailable we
            # stop retrying it for the rest of the trace.
            model_results = None
            if model_redact is not None and not model_failed:
                try:
                    model_results = model_redact(texts)
                    model_used = True
                except Exception as exc:  # noqa: BLE001 - graceful degradation
                    privacy_notes.append(
                        "AI privacy filter was unavailable "
                        f"({type(exc).__name__}); regex redaction was applied."
                    )
                    model_failed = True
                    model_results = None

            for i, message in enumerate(chunk_messages):
                text = texts[i]
                redaction_count += regex_results[i].count
                _accumulate_notes(all_notes, regex_results[i].notes)
                if model_results is not None:
                    text = model_results[i].text
                    redaction_count += model_results[i].count
                    _accumulate_notes(all_notes, model_results[i].notes)
                redacted_messages.append(
                    NarrativeMessage(
                        index=message.index,
                        role=message.role,
                        text=text,
                        timestamp=message.timestamp,
                        source=message.source,
                    )
                )
            yield (
                "progress",
                {
                    "stage": "redact",
                    "processed": min(start + chunk, message_count),
                    "total": message_count,
                },
            )

        messages = redacted_messages

        if model_used:
            privacy_notes.append(
                "AI privacy filter (openai/privacy-filter) screened for names, "
                "contacts, and other personal data."
            )
        if all_notes:
            privacy_notes.append(
                "Redactions applied: "
                + ", ".join(f"{label} ({count})" for label, count in sorted(all_notes.items()))
                + "."
            )
        else:
            privacy_notes.append("No likely secrets matched the redaction patterns.")
    else:
        privacy_notes.append("Secret redaction was disabled by the user.")
    prof.record("redact", time.perf_counter() - _redact_started)
    prof.mark(redactions=redaction_count)
    if not redact_secrets or message_count == 0:
        # No chunk loop ran (redaction disabled or empty trace) — still advance.
        yield ("progress", {"stage": "redact", "processed": message_count, "total": message_count})

    _chart_started = time.perf_counter()
    episodes = identify_episodes(messages)
    prof.record("chart", time.perf_counter() - _chart_started)
    prof.mark(episodes=len(episodes))
    yield ("progress", {"stage": "chart", "messages": message_count})

    _classify_started = time.perf_counter()
    result = AnalysisResult(
        trace_title=derive_trace_title(path, agent_type),
        agent_type_guess=agent_type,
        analysis_scope=ANALYSIS_SCOPE,
        privacy_notes=privacy_notes,
        episodes=episodes,
        overall_patterns=summarize_patterns(episodes, messages),
        narrative_message_count=len(messages),
        redaction_count=redaction_count,
        engine="deterministic-codebook",
    )
    prof.record("classify", time.perf_counter() - _classify_started)
    yield ("progress", {"stage": "classify", "messages": message_count})

    _synth_started = time.perf_counter()
    narrative_text = render_redacted_narrative(messages)
    prof.record("synthesize", time.perf_counter() - _synth_started)
    yield ("progress", {"stage": "synthesize", "messages": message_count})

    yield ("result", (result, narrative_text, messages))


_PRODUCTIVE_VALUES = {"yes", "no", "mixed", "unknown"}
_VALID_TONES = {"stable", "iterative", "detour", "partial", "risk", "unknown"}
_VALID_HONESTY = {"candid", "mixed", "overclaimed"}


def build_numbered_narrative(
    messages: list[NarrativeMessage], *, char_budget: int = 16000, per_message: int = 320
) -> str:
    """Number the (redacted) messages by real index for the model.

    Long traces are sampled evenly across the session (keeping the first and last)
    so the model sees the whole timeline within its context budget; each line keeps
    the message's real index and timestamp so the model can cite spans.
    """

    if not messages:
        return ""
    max_messages = max(1, char_budget // per_message)
    if len(messages) <= max_messages:
        chosen = messages
    else:
        stride = len(messages) / max_messages
        picks = sorted({0, len(messages) - 1, *(int(i * stride) for i in range(max_messages))})
        chosen = [messages[i] for i in picks if 0 <= i < len(messages)]
    lines = []
    for message in chosen:
        snippet = " ".join(message.text.split())[:per_message]
        lines.append(f"[{message.index}] {message.role} {message.timestamp or ''}: {snippet}")
    return "\n".join(lines)


def build_codebook_hint(episodes: list[DifficultyEpisode]) -> str:
    if not episodes:
        return "(none)"
    return "; ".join(
        f"{ep.episode_id} msgs {ep.message_span.start_index}-{ep.message_span.end_index}"
        for ep in episodes[:12]
    )


def _coerce_code(value: object, vocab: dict[str, str]) -> str:
    code = str(value or "").strip()
    return code if code in vocab else "unknown"


# Weak models sometimes echo the schema placeholders verbatim; drop those.
_PLACEHOLDER_RE = re.compile(
    r"^\s*(<.*>|<=.*|\d+(\s*-\s*\d+)?\s+sentences?.*|one key.*|short verbatim.*|up to \d+.*|a message index.*)\s*$",
    re.IGNORECASE,
)


def _clean_text(value: object) -> str:
    text = str(value or "").strip()
    if not text or _PLACEHOLDER_RE.match(text):
        return ""
    return text


def _clean_verdict(verdict: dict) -> dict[str, str]:
    tone = str(verdict.get("tone", "")).strip().lower()
    honesty = str(verdict.get("honesty", "")).strip().lower()
    return {
        "tone": tone if tone in _VALID_TONES else "unknown",
        "headline": _clean_text(verdict.get("headline")) or "Session analyzed by the model.",
        "detail": _clean_text(verdict.get("detail")),
        "honesty": honesty if honesty in _VALID_HONESTY else "mixed",
    }


def _episode_from_model(
    raw: dict, ordinal: int, index_to_timestamp: dict[int, str | None], max_index: int
) -> DifficultyEpisode:
    def clamp(value: object) -> int:
        try:
            return max(0, min(int(value), max_index))
        except (TypeError, ValueError):
            return 0

    start = clamp(raw.get("start_index", 0))
    end = clamp(raw.get("end_index", start))
    if end < start:
        start, end = end, start
    start_time = index_to_timestamp.get(start)
    end_time = index_to_timestamp.get(end)
    span = MessageSpan(
        start_index=start,
        end_index=end,
        start_time=start_time,
        end_time=end_time,
        duration_label=duration_label(start_time, end_time) if start_time and end_time else "unknown",
    )
    productive = str(raw.get("productive_detour", "unknown")).strip().lower()
    quotes = [cleaned for q in (raw.get("evidence_quotes") or []) if (cleaned := _clean_text(q))][:3]
    difficulty = _clean_text(raw.get("reported_difficulty"))
    title = _clean_text(raw.get("title")) or (difficulty[:60] if difficulty else "Difficulty episode")
    return DifficultyEpisode(
        episode_id=f"E{ordinal:02d}",
        title=title,
        message_span=span,
        initial_intention=_clean_text(raw.get("initial_intention")),
        reported_difficulty=difficulty,
        difficulty_type=_coerce_code(raw.get("difficulty_type"), DIFFICULTY_TYPES),
        appraisal=_coerce_code(raw.get("appraisal"), APPRAISALS),
        strategy_before=_clean_text(raw.get("strategy_before")),
        strategy_after=_clean_text(raw.get("strategy_after")),
        detour_type=_coerce_code(raw.get("detour_type"), DETOUR_TYPES),
        resolution_mode=_coerce_code(raw.get("resolution_mode"), RESOLUTION_MODES),
        recovery_pattern=_coerce_code(raw.get("recovery_pattern"), RECOVERY_PATTERNS),
        outcome_claim=_coerce_code(raw.get("outcome_claim"), OUTCOME_CLAIMS),
        productive_detour=productive if productive in _PRODUCTIVE_VALUES else "unknown",
        evidence_quotes=quotes,
        analyst_memo=_clean_text(raw.get("analyst_memo")),
    )


def apply_model_analysis(
    result: AnalysisResult,
    messages: list[NarrativeMessage],
    analysis_engine: str,
    *,
    run=None,
) -> None:
    """Replace the deterministic analysis with a model-produced one (codebook is the fallback).

    ``run`` defaults to :func:`run_model_analysis` (resolved at call time so tests
    can monkeypatch it); the Server passes a GPU- or CPU-bound runner. On success
    the model's episodes, overall patterns, and verdict replace the rule-based
    ones. On any failure the deterministic codebook result is kept and the reason
    recorded in ``model_notes``.
    """

    if analysis_engine == "deterministic":
        return
    if analysis_engine not in MODEL_CHOICES:
        result.model_notes.append(
            f"Unknown analysis engine {analysis_engine!r}; rule-based analysis was returned."
        )
        return

    runner = run or run_model_analysis
    numbered_narrative = build_numbered_narrative(messages)
    codebook_hint = build_codebook_hint(result.episodes)
    try:
        produced = runner(
            engine=analysis_engine,
            numbered_narrative=numbered_narrative,
            agent_type=result.agent_type_guess,
            codebook_hint=codebook_hint,
        )
    except Exception as exc:
        error_message = str(exc).strip().rstrip(".")
        result.model_notes.append(
            "Model analysis was requested but unavailable: "
            f"{type(exc).__name__}: {error_message}. "
            "Rule-based analysis was returned."
        )
        return

    analysis = produced.analysis
    index_to_timestamp = {message.index: message.timestamp for message in messages}
    max_index = (len(messages) - 1) if messages else 0
    episodes = [
        _episode_from_model(raw, ordinal + 1, index_to_timestamp, max_index)
        for ordinal, raw in enumerate(analysis.get("episodes", []))
    ]
    result.episodes = episodes
    patterns = analysis.get("overall_patterns")
    if isinstance(patterns, dict) and patterns:
        result.overall_patterns = {key: str(value) for key, value in patterns.items()}
    else:
        result.overall_patterns = summarize_patterns(episodes, messages)
    verdict = analysis.get("verdict")
    if isinstance(verdict, dict) and verdict:
        result.session_verdict = _clean_verdict(verdict)
    result.engine = produced.model_id
    result.model_notes.append(produced.note)


def analyze_trace_file(
    path: str | Path,
    *,
    include_user_context: bool = True,
    redact_secrets: bool = True,
    ignore_tool_calls: bool = True,
    report_style: str = "field_notes",
    analysis_engine: str = "deterministic",
) -> tuple[AnalysisResult, str]:
    """Parse, optionally redact, and analyze an uploaded trace file."""

    result: AnalysisResult | None = None
    narrative_text = ""
    messages: list[NarrativeMessage] = []
    for kind, payload in stream_deterministic_analysis(
        path,
        include_user_context=include_user_context,
        redact_secrets=redact_secrets,
        ignore_tool_calls=ignore_tool_calls,
    ):
        if kind == "result":
            result, narrative_text, messages = payload
    assert result is not None
    apply_model_analysis(result, messages, analysis_engine)
    return result, narrative_text


def derive_trace_title(path: str | Path, agent_type: str) -> str:
    stem = Path(path).stem if path else "uploaded trace"
    readable_agent = {
        "codex": "Codex",
        "claude_code": "Claude Code",
        "pi": "Pi Agent",
        "unknown": "Agent",
    }.get(agent_type, "Agent")
    return f"{readable_agent} trace: {stem}"


def identify_episodes(messages: list[NarrativeMessage]) -> list[DifficultyEpisode]:
    assistant_indexes = [message.index for message in messages if message.role == "assistant"]
    if not assistant_indexes:
        return []

    candidate_spans: list[tuple[int, int]] = []
    for index, message in enumerate(messages):
        if message.role != "assistant":
            continue
        score = signal_score(message.text, DIFFICULTY_SIGNALS)
        score += 1 if signal_score(message.text, SHIFT_SIGNALS) else 0
        if score < 2:
            continue
        start = previous_assistant_index(messages, index, max_distance=2)
        end = next_episode_end(messages, index, max_distance=3)
        candidate_spans.append((start, end))

    if not candidate_spans:
        return []

    merged_spans = merge_spans(candidate_spans)
    episodes: list[DifficultyEpisode] = []
    for episode_number, (start, end) in enumerate(merged_spans[:12], start=1):
        span_messages = [
            message
            for message in messages
            if start <= message.index <= end and message.role == "assistant"
        ]
        if not span_messages:
            continue
        episodes.append(build_episode(episode_number, start, end, span_messages))
    return episodes


def previous_assistant_index(
    messages: list[NarrativeMessage],
    index: int,
    *,
    max_distance: int,
) -> int:
    start = messages[index].index
    for position in range(index - 1, max(-1, index - max_distance - 1), -1):
        if messages[position].role == "assistant" and signal_score(messages[position].text, INTENTION_SIGNALS):
            start = messages[position].index
            break
    return start


def next_episode_end(
    messages: list[NarrativeMessage],
    index: int,
    *,
    max_distance: int,
) -> int:
    end = messages[index].index
    for position in range(index, min(len(messages), index + max_distance + 1)):
        if messages[position].role != "assistant":
            continue
        end = messages[position].index
        if position > index and signal_score(messages[position].text, OUTCOME_SIGNALS):
            break
    return end


def merge_spans(spans: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    ordered = sorted(spans)
    merged: list[tuple[int, int]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
        else:
            prev_start, prev_end = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end))
    return merged


def build_episode(
    episode_number: int,
    start: int,
    end: int,
    span_messages: list[NarrativeMessage],
) -> DifficultyEpisode:
    combined = "\n\n".join(message.text for message in span_messages)
    difficulty_sentence = first_difficulty_sentence(combined) or first_sentence(combined)
    intention = first_sentence_with(combined, INTENTION_SIGNALS) or first_sentence(combined)
    shift_sentence = first_sentence_after_with(
        combined,
        SHIFT_SIGNALS,
        after_sentence=difficulty_sentence,
    )
    outcome_sentence = last_sentence_with(combined, OUTCOME_SIGNALS)

    difficulty_type = classify_difficulty(difficulty_sentence)
    if difficulty_type == "unknown":
        difficulty_type = classify_difficulty(combined)
    appraisal = classify_appraisal(combined)
    detour_type = classify_detour(combined)
    resolution_mode = classify_resolution(combined)
    outcome_claim = classify_outcome(combined)
    recovery_pattern = classify_recovery(combined, detour_type, outcome_claim)
    productive_detour = classify_productive_detour(detour_type, outcome_claim, recovery_pattern)

    title = make_episode_title(difficulty_type, difficulty_sentence)
    evidence = compact_quotes([difficulty_sentence, shift_sentence, outcome_sentence])

    return DifficultyEpisode(
        episode_id=f"E{episode_number:02d}",
        title=title,
        message_span=MessageSpan(
            start_index=start,
            end_index=end,
            start_time=span_messages[0].timestamp,
            end_time=span_messages[-1].timestamp,
            duration_label=duration_label(span_messages[0].timestamp, span_messages[-1].timestamp),
        ),
        initial_intention=trim_sentence(intention, max_words=36),
        reported_difficulty=trim_sentence(difficulty_sentence, max_words=40),
        difficulty_type=difficulty_type,
        appraisal=appraisal,
        strategy_before=infer_strategy_before(combined),
        strategy_after=trim_sentence(shift_sentence or outcome_sentence or "No explicit strategy shift was visible.", max_words=36),
        detour_type=detour_type,
        resolution_mode=resolution_mode,
        recovery_pattern=recovery_pattern,
        outcome_claim=outcome_claim,
        productive_detour=productive_detour,
        evidence_quotes=evidence,
        analyst_memo=make_analyst_memo(
            difficulty_type,
            appraisal,
            detour_type,
            recovery_pattern,
            outcome_claim,
        ),
    )


def signal_score(text: str, signals: set[str]) -> int:
    return sum(1 for signal in signals if contains_signal(text, signal))


def contains_signal(text: str, signal: str) -> bool:
    """Match a codebook signal as a token or phrase, never as an arbitrary substring."""

    needle = signal.strip().lower()
    if not needle:
        return False
    pattern = re.escape(needle).replace(r"\ ", r"\s+")
    if needle[0].isalnum():
        pattern = rf"(?<![a-z0-9]){pattern}"
    if needle[-1].isalnum():
        pattern = rf"{pattern}(?![a-z0-9])"
    return re.search(pattern, text.lower()) is not None


def contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(contains_signal(text, needle) for needle in needles)


def first_sentence(text: str) -> str:
    return split_sentences(text)[0] if split_sentences(text) else ""


def first_sentence_with(text: str, signals: set[str]) -> str:
    for sentence in split_sentences(text):
        if signal_score(sentence, signals):
            return sentence
    return ""


def last_sentence_with(text: str, signals: set[str]) -> str:
    for sentence in reversed(split_sentences(text)):
        if signal_score(sentence, signals):
            return sentence
    return ""


def first_sentence_after_with(
    text: str,
    signals: set[str],
    *,
    after_sentence: str,
) -> str:
    sentences = split_sentences(text)
    start = 0
    if after_sentence in sentences:
        start = sentences.index(after_sentence) + 1
    for sentence in sentences[start:]:
        if signal_score(sentence, signals):
            return sentence
    return first_sentence_with(text, signals)


def first_difficulty_sentence(text: str) -> str:
    signaled = [
        sentence
        for sentence in split_sentences(text)
        if signal_score(sentence, DIFFICULTY_SIGNALS)
    ]
    if not signaled:
        return ""
    for sentence in signaled:
        if not signal_score(sentence, INTENTION_SIGNALS) or contains_any(
            sentence,
            PROBLEM_EVIDENCE_SIGNALS,
        ):
            return sentence
    return signaled[0]


def split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?])\s+|\n+", normalized)
    return [part.strip(" -") for part in parts if part.strip(" -")]


def classify_difficulty(text: str) -> str:
    lowered = text.lower()
    checks = [
        ("verification_difficulty", ("verify", "verification", "test", "reproduce", "confirmed", "validate", "cannot run", "not able to run")),
        ("requirement_uncertainty", ("requirement", "spec", "unclear", "ambiguous", "user intent", "not specified", "scope unclear")),
        ("environment_blocker", ("dependency", "install", "permission", "auth", "network", "timeout", "sandbox", "environment", "ci", "build fail")),
        ("compatibility_risk", ("regression", "break", "compatibility", "existing behavior", "side effect", "risk", "backward")),
        ("localization_difficulty", ("where", "locate", "which file", "module", "root cause", "grep", "search", "trace through")),
        ("architecture_complexity", ("architecture", "dependency", "shared", "coupling", "system structure", "cross-module", "data flow")),
        ("implementation_difficulty", ("implement", "tricky", "complex", "not sure how", "hard to", "edge case")),
        ("insufficient_context", ("more context", "missing context", "need context", "cannot inspect", "not enough information")),
        ("conflicting_assumptions", ("assumption", "expected", "actually", "mismatch", "conflict", "turns out")),
    ]
    return first_matching_code(lowered, checks)


def classify_appraisal(text: str) -> str:
    lowered = text.lower()
    checks = [
        ("cannot_reliably_verify", ("cannot verify", "can't verify", "not verified", "need to verify", "cannot run", "unable to run")),
        ("needs_more_context", ("need more context", "need to inspect", "need more information", "missing context")),
        ("initial_hypothesis_wrong", ("hypothesis", "assumption", "i thought", "turns out", "actually")),
        ("risk_is_higher_than_expected", ("risk", "regression", "side effect", "break existing", "higher than expected")),
        ("scope_too_large", ("too large", "scope", "narrow", "smaller", "limit this")),
        ("needs_alternative_path", ("alternative", "instead", "different approach", "try another", "workaround")),
        ("task_boundary_unclear", ("boundary", "unclear", "ambiguous", "not specified")),
        ("local_fix_possible", ("local", "small patch", "focused", "straightforward", "fix")),
    ]
    return first_matching_code(lowered, checks)


def classify_detour(text: str) -> str:
    lowered = text.lower()
    checks = [
        ("premature_closure", ("done", "complete", "fixed", "should work")),
        ("rollback_or_reversal", ("roll back", "rollback the", "revert", "abandon", "undo")),
        ("verification_shift", ("verify with", "instead test", "different verification", "check by", "validate by")),
        ("hypothesis_switch", ("new hypothesis", "different hypothesis", "assumption was", "turns out")),
        ("workaround", ("workaround", "bypass", "skip the issue", "without fixing", "temporary fix")),
        ("scope_narrowing", ("narrow", "smaller", "limit", "focus only", "minimal")),
        ("decomposition", ("decompose", "break down", "split", "step by step")),
        ("alternative_path", ("alternative", "instead", "switch", "try another", "different approach")),
    ]
    code = first_matching_code(lowered, checks)
    if code == "premature_closure" and signal_score(text, DIFFICULTY_SIGNALS) >= 2:
        return "premature_closure"
    if code == "premature_closure":
        return "direct_continuation"
    return code if code != "unknown" else "direct_continuation"


def classify_resolution(text: str) -> str:
    lowered = text.lower()
    checks = [
        ("explicit_limitation", ("could not", "unable", "limitation", "caveat", "not verified")),
        ("goal_reduction", ("partial", "partially", "narrow", "smaller scope", "only")),
        ("structural_change", ("refactor", "architecture", "new module", "extract", "centralize", "schema")),
        ("defensive_handling", ("guard", "validate", "fallback", "error handling", "defensive", "sanitize")),
        ("alternative_implementation", ("alternative implementation", "different implementation", "switch to", "instead")),
        ("problem_reframing", ("reframe", "actually", "not a", "instead of treating")),
        ("information_gathering", ("inspect", "search", "read", "looked at", "context")),
        ("minimal_patch", ("small patch", "focused change", "minimal", "fix")),
    ]
    return first_matching_code(lowered, checks)


def classify_outcome(text: str) -> str:
    lowered = text.lower()
    success_claim = contains_any(
        lowered,
        ("done", "fixed", "implemented", "resolved", "complete", "verified", "passes"),
    )
    unresolved_evidence = contains_any(
        lowered,
        (
            "still failing",
            "still fails",
            "skipped",
            "skip the issue",
            "workaround",
            "without fixing",
            "should work",
        ),
    )
    if success_claim and unresolved_evidence:
        return "premature_success_claim"
    if contains_any(lowered, ("not resolved", "still failing", "could not", "unable to")):
        return "not_resolved"
    if contains_any(lowered, ("need to verify", "needs verification", "not verified", "cannot verify", "can't verify")):
        return "needs_verification"
    if contains_any(lowered, ("partial", "partially", "some of", "subset")):
        return "partially_resolved"
    if contains_any(lowered, ("caveat", "assuming", "should", "likely", "not run")) and contains_any(
        lowered,
        ("done", "fixed", "implemented", "resolved", "complete"),
    ):
        return "resolved_with_caveat"
    if success_claim:
        if signal_score(text, DIFFICULTY_SIGNALS) >= 3 and "verified" not in lowered and "passes" not in lowered:
            return "premature_success_claim"
        return "resolved_with_confidence"
    if contains_any(lowered, ("uncertain", "not sure", "proceed")):
        return "uncertain_but_proceeding"
    return "unknown"


def classify_recovery(text: str, detour_type: str, outcome_claim: str) -> str:
    lowered = text.lower()
    if outcome_claim in {"not_resolved", "needs_verification"}:
        return "failed_recovery" if outcome_claim == "not_resolved" else "partial_recovery"
    if outcome_claim == "premature_success_claim":
        return "overconfident_recovery"
    if any(token in lowered for token in ("assumption", "turns out", "actually", "hypothesis")):
        return "reflective_recovery"
    if detour_type in {"alternative_path", "workaround", "scope_narrowing", "verification_shift"}:
        return "detour_recovery"
    if any(token in lowered for token in ("retry", "again", "iterate", "second", "another attempt")):
        return "iterative_recovery"
    if outcome_claim in {"resolved_with_confidence", "resolved_with_caveat"}:
        return "smooth_recovery"
    return "unknown"


def classify_productive_detour(detour_type: str, outcome_claim: str, recovery_pattern: str) -> str:
    if detour_type in {"direct_continuation", "unknown"}:
        return "unknown"
    if recovery_pattern in {"overconfident_recovery", "failed_recovery", "avoidant_recovery"}:
        return "no"
    if outcome_claim in {"partially_resolved", "needs_verification", "resolved_with_caveat"}:
        return "mixed"
    return "yes"


def first_matching_code(lowered_text: str, checks: list[tuple[str, tuple[str, ...]]]) -> str:
    for code, needles in checks:
        if contains_any(lowered_text, needles):
            return code
    return "unknown"


def infer_strategy_before(text: str) -> str:
    sentence = first_sentence_with(text, INTENTION_SIGNALS)
    if sentence:
        return trim_sentence(sentence, max_words=36)
    return "The agent appears to continue from the prior task context."


def make_episode_title(difficulty_type: str, sentence: str) -> str:
    label = difficulty_type.replace("_", " ").title()
    topic = trim_sentence(sentence, max_words=8)
    return f"{label}: {topic}" if topic else label


def compact_quotes(sentences: list[str | None]) -> list[str]:
    quotes: list[str] = []
    seen: set[str] = set()
    for sentence in sentences:
        if not sentence:
            continue
        quote = trim_sentence(sentence, max_words=30)
        if quote and quote not in seen:
            quotes.append(quote)
            seen.add(quote)
    return quotes[:3]


def trim_sentence(text: str, *, max_words: int) -> str:
    words = re.sub(r"\s+", " ", text or "").strip().split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(",.;:") + "..."


def make_analyst_memo(
    difficulty_type: str,
    appraisal: str,
    detour_type: str,
    recovery_pattern: str,
    outcome_claim: str,
) -> str:
    return (
        f"The visible narrative frames this as {difficulty_type.replace('_', ' ')}; "
        f"the appraisal is {appraisal.replace('_', ' ')}, with {detour_type.replace('_', ' ')} "
        f"and {recovery_pattern.replace('_', ' ')}. The outcome claim reads as "
        f"{outcome_claim.replace('_', ' ')}."
    )


def summarize_patterns(
    episodes: list[DifficultyEpisode],
    messages: list[NarrativeMessage],
) -> dict[str, str]:
    if not episodes:
        return {
            "difficulty_style": "No explicit difficulty episode was detected in the visible assistant narrative.",
            "detour_style": "No strategy shift or detour was visible enough to classify.",
            "recovery_style": "No recovery pattern can be inferred from the available narrative.",
            "risk_or_caveat": "The analyzer only inspects visible narrative messages, so absence of evidence is not proof that the session was difficulty-free.",
        }

    difficulty_counts = Counter(episode.difficulty_type for episode in episodes)
    detour_counts = Counter(episode.detour_type for episode in episodes)
    recovery_counts = Counter(episode.recovery_pattern for episode in episodes)
    outcome_counts = Counter(episode.outcome_claim for episode in episodes)

    primary_difficulty = readable_count_summary(difficulty_counts)
    primary_detour = readable_count_summary(detour_counts)
    primary_recovery = readable_count_summary(recovery_counts)
    risky = [
        episode.episode_id
        for episode in episodes
        if episode.outcome_claim in {"needs_verification", "premature_success_claim", "not_resolved"}
    ]
    caveat = (
        f"Watch {', '.join(risky)}: these episodes end with unresolved, unverifiable, or overconfident claims."
        if risky
        else f"Outcome claims lean toward {readable_count_summary(outcome_counts)}."
    )
    return {
        "difficulty_style": f"Main difficulty pattern: {primary_difficulty}.",
        "detour_style": f"Main detour pattern: {primary_detour}.",
        "recovery_style": f"Main recovery pattern: {primary_recovery}.",
        "risk_or_caveat": caveat,
    }


def readable_count_summary(counter: Counter[str]) -> str:
    if not counter:
        return "unknown"
    return ", ".join(f"{code.replace('_', ' ')} ({count})" for code, count in counter.most_common(3))


def duration_label(start_time: str | None, end_time: str | None) -> str:
    if not start_time or not end_time:
        return "unknown"
    start = parse_timestamp(start_time)
    end = parse_timestamp(end_time)
    if not start or not end or end < start:
        return "unknown"
    seconds = int((end - start).total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def parse_timestamp(value: str) -> datetime | None:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def render_redacted_narrative(messages: list[NarrativeMessage]) -> str:
    blocks: list[str] = []
    for message in messages:
        timestamp = f" [{message.timestamp}]" if message.timestamp else ""
        blocks.append(f"## {message.index:04d} {message.role}{timestamp}\n\n{message.text}")
    return "\n\n".join(blocks).strip() + "\n"
