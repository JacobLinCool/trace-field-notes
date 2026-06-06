"""Shared data structures and codebook constants for Trace Field Notes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


AgentType = Literal["codex", "claude_code", "pi", "unknown"]


DIFFICULTY_TYPES = {
    "requirement_uncertainty": "Requirements, specification, or user intent are unclear.",
    "localization_difficulty": "The relevant module, file, function, or root cause is unclear.",
    "architecture_complexity": "The system structure, dependencies, or shared surfaces are more complex than expected.",
    "implementation_difficulty": "The direction is known, but the implementation is non-trivial.",
    "compatibility_risk": "A change may break existing behavior or nearby surfaces.",
    "verification_difficulty": "It is unclear how to verify that the work is correct.",
    "environment_blocker": "Dependencies, permissions, network, runtime, or local environment block progress.",
    "insufficient_context": "The agent reports that more context is needed.",
    "conflicting_assumptions": "A prior assumption conflicts with new evidence.",
    "unknown": "The evidence is too weak to classify.",
}

APPRAISALS = {
    "local_fix_possible": "The agent frames the issue as locally fixable.",
    "needs_more_context": "The agent says it needs more information.",
    "initial_hypothesis_wrong": "The agent revises an earlier hypothesis.",
    "risk_is_higher_than_expected": "The agent recognizes higher side-effect or regression risk.",
    "scope_too_large": "The agent decides the original scope is too broad.",
    "needs_alternative_path": "The agent seeks a different route.",
    "cannot_reliably_verify": "The agent says verification is not reliable yet.",
    "task_boundary_unclear": "The agent sees the task boundary as unclear.",
    "unknown": "The evidence is too weak to classify.",
}

DETOUR_TYPES = {
    "direct_continuation": "The agent continues the original strategy.",
    "decomposition": "The agent breaks the problem down.",
    "scope_narrowing": "The agent narrows the scope.",
    "alternative_path": "The agent switches route.",
    "workaround": "The agent works around the issue without resolving the root cause.",
    "rollback_or_reversal": "The agent abandons or reverses a prior direction.",
    "hypothesis_switch": "The agent changes its problem hypothesis.",
    "verification_shift": "The agent changes verification strategy.",
    "ask_or_defer": "The agent asks for input or defers judgment.",
    "premature_closure": "The agent closes before the difficulty is resolved.",
    "unknown": "The evidence is too weak to classify.",
}

RESOLUTION_MODES = {
    "information_gathering": "The episode resolves through additional context.",
    "problem_reframing": "The agent reframes the problem.",
    "minimal_patch": "The agent applies a focused patch.",
    "structural_change": "The agent makes or proposes a structural change.",
    "defensive_handling": "The agent adds guards, validation, or explicit handling.",
    "alternative_implementation": "The agent changes implementation approach.",
    "goal_reduction": "The agent lowers the goal or solves a subset.",
    "explicit_limitation": "The agent explicitly states a limitation.",
    "narrative_rationalization": "The agent smooths over unresolved evidence in prose.",
    "unknown": "The evidence is too weak to classify.",
}

RECOVERY_PATTERNS = {
    "smooth_recovery": "The agent quickly understands the issue and moves forward.",
    "iterative_recovery": "The agent recovers through repeated attempts.",
    "detour_recovery": "The agent recovers after a route change.",
    "partial_recovery": "The agent solves part of the issue while preserving caveats.",
    "failed_recovery": "The episode does not recover.",
    "avoidant_recovery": "The agent bypasses the difficulty by doing adjacent work.",
    "overconfident_recovery": "The agent claims success without enough visible support.",
    "reflective_recovery": "The agent identifies a wrong assumption and corrects course.",
    "unknown": "The evidence is too weak to classify.",
}

OUTCOME_CLAIMS = {
    "resolved_with_confidence": "The agent clearly claims completion.",
    "resolved_with_caveat": "The agent claims completion with a caveat.",
    "partially_resolved": "The agent says only part of the work is complete.",
    "not_resolved": "The agent says the issue remains unresolved.",
    "needs_verification": "The agent says more testing or confirmation is needed.",
    "uncertain_but_proceeding": "The agent proceeds despite uncertainty.",
    "premature_success_claim": "The agent claims success with weak visible evidence.",
    "unknown": "The evidence is too weak to classify.",
}


@dataclass(slots=True)
class NarrativeMessage:
    """A visible user or assistant message extracted from an agent trace."""

    index: int
    role: Literal["assistant", "user"]
    text: str
    timestamp: str | None = None
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MessageSpan:
    start_index: int
    end_index: int
    start_time: str | None = None
    end_time: str | None = None
    duration_label: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DifficultyEpisode:
    episode_id: str
    title: str
    message_span: MessageSpan
    initial_intention: str
    reported_difficulty: str
    difficulty_type: str
    appraisal: str
    strategy_before: str
    strategy_after: str
    detour_type: str
    resolution_mode: str
    recovery_pattern: str
    outcome_claim: str
    productive_detour: Literal["yes", "no", "mixed", "unknown"]
    evidence_quotes: list[str] = field(default_factory=list)
    analyst_memo: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["message_span"] = self.message_span.to_dict()
        return data


@dataclass(slots=True)
class AnalysisResult:
    trace_title: str
    agent_type_guess: AgentType
    analysis_scope: str
    privacy_notes: list[str]
    episodes: list[DifficultyEpisode]
    overall_patterns: dict[str, str]
    narrative_message_count: int
    redaction_count: int = 0
    engine: str = "deterministic-codebook"
    model_notes: list[str] = field(default_factory=list)
    model_memo: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_title": self.trace_title,
            "agent_type_guess": self.agent_type_guess,
            "analysis_scope": self.analysis_scope,
            "privacy_notes": self.privacy_notes,
            "episodes": [episode.to_dict() for episode in self.episodes],
            "overall_patterns": self.overall_patterns,
            "narrative_message_count": self.narrative_message_count,
            "redaction_count": self.redaction_count,
            "engine": self.engine,
            "model_notes": self.model_notes,
            "model_memo": self.model_memo,
        }
