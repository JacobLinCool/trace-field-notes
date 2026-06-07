"""Adapt an :class:`AnalysisResult` into the JSON shape the React frontend expects.

The designer's prototype renders from a richer object than the analyzer produces:
it also wants a top-level ``verdict`` (a whole-session read), a ``captured``
window, and a ``duration_total``. Those are synthesized here from the
deterministic episodes (and the model memo, when present) so the frontend stays
a pure view layer.
"""

from __future__ import annotations

import json
from typing import Any

from analyzer import duration_label, parse_timestamp
from report_renderer import render_report
from schemas import AnalysisResult


# recovery_pattern -> tone bucket (mirrors the frontend's TONE_OF in data.js)
TONE_OF = {
    "smooth_recovery": "stable",
    "reflective_recovery": "stable",
    "iterative_recovery": "iterative",
    "detour_recovery": "detour",
    "partial_recovery": "partial",
    "failed_recovery": "risk",
    "avoidant_recovery": "risk",
    "overconfident_recovery": "risk",
    "unknown": "unknown",
}

_SEVERITY = {"risk": 5, "partial": 4, "iterative": 3, "detour": 2, "stable": 1, "unknown": 0}

_CANDID_CLAIMS = {
    "resolved_with_caveat",
    "not_resolved",
    "needs_verification",
    "partially_resolved",
    "uncertain_but_proceeding",
}

_HEADLINE_BY_TONE = {
    "stable": "A clean run with an honest close-out.",
    "detour": "Left the planned path and found a better line.",
    "iterative": "Closed in on it through repeated attempts.",
    "partial": "Part of the way there, with caveats left standing.",
    "risk": "Hit hazard terrain and didn't clearly recover.",
    "unknown": "A short session with little difficulty signal.",
}


def build_view_model(
    result: AnalysisResult,
    narrative_text: str,
    *,
    include_exports: bool = True,
) -> dict[str, Any]:
    """Return the frontend-ready dict for one analysis."""

    base = result.to_dict()
    raw_episodes = base["episodes"]
    episodes = [_clean_episode(ep) for ep in raw_episodes]

    view: dict[str, Any] = {
        "trace_title": base["trace_title"],
        "agent_type_guess": base["agent_type_guess"],
        "analysis_scope": base["analysis_scope"],
        "engine": base["engine"],
        "captured": _captured(raw_episodes),
        "narrative_message_count": base["narrative_message_count"],
        "redaction_count": base["redaction_count"],
        "duration_total": _duration_total(raw_episodes),
        "verdict": base.get("session_verdict") or _verdict(episodes, base["overall_patterns"], result.model_memo),
        "overall_patterns": base["overall_patterns"],
        "privacy_notes": list(base["privacy_notes"]) + list(base.get("model_notes") or []),
        "episodes": episodes,
    }
    if result.model_memo:
        view["model_memo"] = result.model_memo
    if include_exports:
        view["exports"] = {
            "narrative_md": narrative_text,
            "report_md": render_report(result),
            "episodes_json": json.dumps(base, indent=2, ensure_ascii=False) + "\n",
        }
    return view


def _clean_episode(ep: dict[str, Any]) -> dict[str, Any]:
    ep = dict(ep)
    span = dict(ep.get("message_span") or {})
    span["start_time"] = _fmt_clock(span.get("start_time"))
    span["end_time"] = _fmt_clock(span.get("end_time"))
    span["duration_label"] = span.get("duration_label") or "unknown"
    ep["message_span"] = span
    ep["evidence_quotes"] = list(ep.get("evidence_quotes") or [])
    return ep


def _fmt_clock(value: str | None) -> str:
    """A bare ``HH:MM:SS`` clock for in-report episode times (date lives in `captured`)."""

    parsed = parse_timestamp(value) if value else None
    if parsed is None:
        return value or ""
    return parsed.strftime("%H:%M:%S")


def _session_tone(episodes: list[dict[str, Any]]) -> str:
    tones = [TONE_OF.get(ep["recovery_pattern"], "unknown") for ep in episodes]
    if not tones:
        return "unknown"
    return max(tones, key=lambda t: _SEVERITY[t])


def _honesty(episodes: list[dict[str, Any]]) -> str:
    claims = [ep["outcome_claim"] for ep in episodes]
    if any(c == "premature_success_claim" for c in claims):
        return "overclaimed"
    if any(c in _CANDID_CLAIMS for c in claims):
        return "candid"
    return "mixed"


def _verdict(
    episodes: list[dict[str, Any]],
    patterns: dict[str, str],
    model_memo: dict[str, Any] | None,
) -> dict[str, str]:
    n = len(episodes)
    if not n:
        return {
            "tone": "unknown",
            "headline": "No explicit difficulty episode surfaced.",
            "detail": "The visible narrative did not carry clear blockage, detour, or recovery language.",
            "honesty": "mixed",
        }
    tone = _session_tone(episodes)
    honesty = _honesty(episodes)
    headline = (
        "Real progress, but the final claim outruns the evidence."
        if honesty == "overclaimed"
        else _HEADLINE_BY_TONE.get(tone, "A session across mixed terrain.")
    )
    memo_detail = (model_memo or {}).get("executive_memo") if model_memo else None
    if memo_detail:
        detail = str(memo_detail)
    else:
        plural = "s" if n != 1 else ""
        parts = [f"{n} difficulty episode{plural}."]
        if patterns.get("recovery_style"):
            parts.append(patterns["recovery_style"])
        if patterns.get("risk_or_caveat"):
            parts.append(patterns["risk_or_caveat"])
        detail = " ".join(parts)
    return {"tone": tone, "headline": headline, "detail": detail, "honesty": honesty}


def _captured(episodes: list[dict[str, Any]]) -> str:
    """A readable capture window from the first/last episode timestamps."""

    if not episodes:
        return "—"
    start = parse_timestamp(episodes[0]["message_span"].get("start_time") or "")
    end = parse_timestamp(episodes[-1]["message_span"].get("end_time") or "")
    if start and end:
        if start.date() == end.date():
            return f"{start:%Y-%m-%d} · {start:%H:%M}–{end:%H:%M} UTC"
        return f"{start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} UTC"
    if start:
        return f"{start:%Y-%m-%d} · {start:%H:%M} UTC"
    raw = episodes[0]["message_span"].get("start_time")
    return raw or "—"


def _duration_total(episodes: list[dict[str, Any]]) -> str:
    if not episodes:
        return "—"
    start = episodes[0]["message_span"].get("start_time")
    end = episodes[-1]["message_span"].get("end_time")
    if start and end:
        label = duration_label(start, end)
        if label != "unknown":
            return label
    # fall back to summing per-episode labels is lossy; show the span count instead
    return episodes[-1]["message_span"].get("duration_label") or "—"
