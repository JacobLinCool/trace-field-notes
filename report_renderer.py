"""Markdown rendering for Trace Field Notes analysis results."""

from __future__ import annotations

from collections import defaultdict

from schemas import AnalysisResult, DifficultyEpisode


RECOVERY_TONE = {
    "smooth_recovery": "stable",
    "reflective_recovery": "stable",
    "iterative_recovery": "iterative",
    "detour_recovery": "detour",
    "partial_recovery": "partial",
    "failed_recovery": "unresolved",
    "avoidant_recovery": "unresolved",
    "overconfident_recovery": "risky",
    "unknown": "unknown",
}


def render_report(result: AnalysisResult) -> str:
    """Render a field-note style Markdown report."""

    sections = [
        render_header(result),
        render_executive_summary(result),
        render_timeline(result.episodes),
        render_difficulty_map(result.episodes),
        render_detour_analysis(result.episodes),
        render_recovery_pattern(result),
        render_outcome_claim_audit(result.episodes),
        render_privacy_notes(result),
    ]
    return "\n\n".join(section for section in sections if section.strip()).strip() + "\n"


def render_header(result: AnalysisResult) -> str:
    return (
        f"# Trace Field Notes\n\n"
        f"**Trace:** {result.trace_title}\n\n"
        f"**Agent guess:** `{result.agent_type_guess}`\n\n"
        f"**Analysis scope:** {result.analysis_scope}\n\n"
        f"**Engine:** `{result.engine}`"
    )


def render_executive_summary(result: AnalysisResult) -> str:
    if not result.episodes:
        return (
            "## Executive Summary\n\n"
            f"The trace yielded {result.narrative_message_count} visible narrative messages, but no explicit "
            "difficulty episode was strong enough to classify. That does not prove the session had no problems; "
            "it only means the uploaded narrative did not contain clear self-reported blockage, detour, or "
            "recovery language. Review the redacted narrative export if you expected visible difficulties."
        )

    patterns = result.overall_patterns
    caveat = patterns.get("risk_or_caveat", "No caveat available.")
    return (
        "## Executive Summary\n\n"
        f"This trace contains {result.narrative_message_count} visible narrative messages and "
        f"{len(result.episodes)} classified difficulty episode(s). "
        f"{patterns.get('difficulty_style', '')} "
        f"{patterns.get('detour_style', '')} "
        f"{patterns.get('recovery_style', '')} "
        f"{caveat} "
        "The report describes what the agent visibly reported and claimed; it does not verify whether the code or "
        "final artifact is correct."
    )


def render_timeline(episodes: list[DifficultyEpisode]) -> str:
    if not episodes:
        return "## Journey Timeline\n\nNo difficulty timeline was detected."

    blocks = ["## Journey Timeline"]
    for episode in episodes:
        tone = RECOVERY_TONE.get(episode.recovery_pattern, "unknown")
        blocks.append(
            "\n".join(
                [
                    f"### {episode.episode_id} - {episode.title}",
                    f"**Tone:** `{tone}`",
                    f"**Intention:** {episode.initial_intention}",
                    f"**Difficulty:** {episode.reported_difficulty}",
                    f"**Shift:** {episode.strategy_after}",
                    f"**Resolution mode:** `{episode.resolution_mode}`",
                    f"**Outcome claim:** `{episode.outcome_claim}`",
                    f"**Duration:** {episode.message_span.duration_label}",
                ]
            )
        )
    return "\n\n".join(blocks)


def render_difficulty_map(episodes: list[DifficultyEpisode]) -> str:
    if not episodes:
        return "## Difficulty Map\n\nNo thematic difficulty clusters were detected."

    clusters: dict[str, list[DifficultyEpisode]] = defaultdict(list)
    for episode in episodes:
        clusters[episode.difficulty_type].append(episode)

    lines = ["## Difficulty Map", "Main difficulties observed:"]
    for difficulty_type, grouped in sorted(clusters.items()):
        ids = ", ".join(episode.episode_id for episode in grouped)
        quote = first_quote(grouped)
        lines.append(f"- **{difficulty_type.replace('_', ' ').title()}**: {ids}. {quote}")
    return "\n".join(lines)


def render_detour_analysis(episodes: list[DifficultyEpisode]) -> str:
    if not episodes:
        return "## Detour Analysis\n\nNo visible detours were detected."

    productive = [episode.episode_id for episode in episodes if episode.productive_detour == "yes"]
    mixed = [episode.episode_id for episode in episodes if episode.productive_detour == "mixed"]
    unproductive = [episode.episode_id for episode in episodes if episode.productive_detour == "no"]

    lines = ["## Detour Analysis"]
    lines.append(detour_line("Productive detours", productive))
    lines.append(detour_line("Mixed detours", mixed))
    lines.append(detour_line("Unproductive or risky detours", unproductive))
    for episode in episodes:
        if episode.detour_type == "direct_continuation":
            continue
        lines.append(
            f"- {episode.episode_id}: `{episode.detour_type}`. {episode.analyst_memo}"
        )
    return "\n".join(lines)


def detour_line(label: str, episode_ids: list[str]) -> str:
    value = ", ".join(episode_ids) if episode_ids else "none detected"
    return f"- **{label}:** {value}"


def render_recovery_pattern(result: AnalysisResult) -> str:
    patterns = result.overall_patterns
    return (
        "## Recovery Pattern\n\n"
        f"{patterns.get('recovery_style', 'No recovery pattern was classified.')} "
        f"{patterns.get('difficulty_style', '')} "
        f"{patterns.get('detour_style', '')}"
    )


def render_outcome_claim_audit(episodes: list[DifficultyEpisode]) -> str:
    if not episodes:
        return (
            "## Outcome Claim Audit\n\n"
            "No explicit outcome claims were attached to difficulty episodes."
        )

    lines = ["## Outcome Claim Audit"]
    for episode in episodes:
        evidence = "; ".join(f'"{quote}"' for quote in episode.evidence_quotes[:2])
        lines.append(
            f"- **{episode.episode_id}:** `{episode.outcome_claim}`. "
            f"Recovery: `{episode.recovery_pattern}`. Evidence: {evidence or 'no short quote available'}."
        )
    return "\n".join(lines)


def render_privacy_notes(result: AnalysisResult) -> str:
    lines = [
        "## Privacy Notes",
        f"Redaction count: {result.redaction_count}",
    ]
    lines.extend(f"- {note}" for note in result.privacy_notes)
    return "\n".join(lines)


def first_quote(episodes: list[DifficultyEpisode]) -> str:
    for episode in episodes:
        if episode.evidence_quotes:
            return f'Example: "{episode.evidence_quotes[0]}"'
    return "No short evidence quote was available."
