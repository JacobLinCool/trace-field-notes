"""Deterministic codebook analysis for coding-agent narrative traces."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from parser import parse_trace
from redaction import redact_text
from schemas import AnalysisResult, DifficultyEpisode, MessageSpan, NarrativeMessage


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
    "rollback",
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


def analyze_trace_file(
    path: str | Path,
    *,
    include_user_context: bool = True,
    redact_secrets: bool = True,
    ignore_tool_calls: bool = True,
    report_style: str = "field_notes",
) -> tuple[AnalysisResult, str]:
    """Parse, optionally redact, and analyze an uploaded trace file."""

    parsed_messages, agent_type = parse_trace(
        path,
        include_user_context=include_user_context,
        ignore_tool_calls=ignore_tool_calls,
    )

    redaction_count = 0
    privacy_notes = [
        "Uploaded traces are processed for this request only; the app exports a redacted narrative text file.",
        "The analysis uses visible messages and does not inspect hidden reasoning.",
    ]
    if ignore_tool_calls:
        privacy_notes.append("Tool-call contents were ignored before analysis.")

    messages = parsed_messages
    if redact_secrets:
        redacted_messages: list[NarrativeMessage] = []
        all_notes: Counter[str] = Counter()
        for message in parsed_messages:
            result = redact_text(message.text)
            redaction_count += result.count
            for note in result.notes:
                label, _, count = note.partition(": ")
                all_notes[label] += int(count or 0)
            redacted_messages.append(
                NarrativeMessage(
                    index=message.index,
                    role=message.role,
                    text=result.text,
                    timestamp=message.timestamp,
                    source=message.source,
                )
            )
        messages = redacted_messages
        if all_notes:
            privacy_notes.append(
                "Redactions applied: "
                + ", ".join(f"{label} ({count})" for label, count in sorted(all_notes.items()))
                + "."
            )
        else:
            privacy_notes.append("No likely secrets matched the built-in redaction patterns.")
    else:
        privacy_notes.append("Secret redaction was disabled by the user.")

    episodes = identify_episodes(messages)
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
    narrative_text = render_redacted_narrative(messages)
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
    difficulty_sentence = first_sentence_with(combined, DIFFICULTY_SIGNALS) or first_sentence(combined)
    intention = first_sentence_with(combined, INTENTION_SIGNALS) or first_sentence(combined)
    shift_sentence = first_sentence_with(combined, SHIFT_SIGNALS)
    outcome_sentence = first_sentence_with(combined, OUTCOME_SIGNALS)

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
    lowered = text.lower()
    return sum(1 for signal in signals if signal in lowered)


def first_sentence(text: str) -> str:
    return split_sentences(text)[0] if split_sentences(text) else ""


def first_sentence_with(text: str, signals: set[str]) -> str:
    for sentence in split_sentences(text):
        if signal_score(sentence, signals):
            return sentence
    return ""


def split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?])\s+|\n+", normalized)
    return [part.strip(" -") for part in parts if part.strip(" -")]


def classify_difficulty(text: str) -> str:
    lowered = text.lower()
    checks = [
        ("environment_blocker", ("dependency", "install", "permission", "auth", "network", "timeout", "sandbox", "environment", "ci", "build fail")),
        ("verification_difficulty", ("verify", "verification", "test", "reproduce", "confirmed", "validate", "cannot run", "not able to run")),
        ("compatibility_risk", ("regression", "break", "compatibility", "existing behavior", "side effect", "risk", "backward")),
        ("requirement_uncertainty", ("requirement", "spec", "unclear", "ambiguous", "user intent", "not specified", "scope unclear")),
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
        ("rollback_or_reversal", ("rollback", "roll back", "revert", "abandon", "undo")),
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
    if any(token in lowered for token in ("not resolved", "still failing", "could not", "unable to")):
        return "not_resolved"
    if any(token in lowered for token in ("need to verify", "needs verification", "not verified", "cannot verify", "can't verify")):
        return "needs_verification"
    if any(token in lowered for token in ("partial", "partially", "some of", "subset")):
        return "partially_resolved"
    if any(token in lowered for token in ("caveat", "assuming", "should", "likely", "not run")) and any(
        token in lowered for token in ("done", "fixed", "implemented", "resolved", "complete")
    ):
        return "resolved_with_caveat"
    if any(token in lowered for token in ("done", "fixed", "implemented", "resolved", "complete", "verified", "passes")):
        if signal_score(text, DIFFICULTY_SIGNALS) >= 3 and "verified" not in lowered and "passes" not in lowered:
            return "premature_success_claim"
        return "resolved_with_confidence"
    if any(token in lowered for token in ("uncertain", "not sure", "proceed")):
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
        if any(needle in lowered_text for needle in needles):
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
