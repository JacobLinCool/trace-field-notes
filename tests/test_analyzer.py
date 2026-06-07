from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from analyzer import analyze_trace_file, duration_label
from report_renderer import render_report
from view_model import build_view_model


class AnalyzerTests(unittest.TestCase):
    def write_codex_trace(self, messages: list[str]) -> Path:
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl", delete=False)
        with handle:
            handle.write(
                json.dumps(
                    {
                        "timestamp": "2026-06-07T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"originator": "codex_cli"},
                    }
                )
                + "\n"
            )
            for index, text in enumerate(messages, start=1):
                handle.write(
                    json.dumps(
                        {
                            "timestamp": f"2026-06-07T00:0{index}:00Z",
                            "type": "response_item",
                            "payload": {
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": text}],
                            },
                        }
                    )
                    + "\n"
                )
        return Path(handle.name)

    def test_sample_trace_produces_structured_episode_and_redactions(self) -> None:
        result, narrative = analyze_trace_file(Path("examples/sample_trace_redacted.jsonl"))

        self.assertEqual(result.agent_type_guess, "codex")
        self.assertGreaterEqual(len(result.episodes), 1)
        self.assertGreater(result.redaction_count, 0)
        self.assertIn("[REDACTED_EMAIL]", narrative)
        self.assertIn("episodes", result.to_dict())

        report = render_report(result)
        self.assertIn("Executive Summary", report)
        self.assertIn("Journey Timeline", report)
        self.assertIn("Outcome Claim Audit", report)

    def test_codebook_flags_premature_success_after_unresolved_workaround(self) -> None:
        path = self.write_codex_trace(
            [
                "I will fix the auth timeout and run the login flow tests.",
                "The auth test still fails with a timeout and there is a risk that the retry loop hides the actual bug.",
                "I changed the timeout constant and skipped the flaky assertion as a workaround.",
                "Done, fixed, and complete; it should work now.",
            ]
        )

        result, narrative = analyze_trace_file(path)
        episode = result.episodes[0]
        verdict = build_view_model(result, narrative)["verdict"]

        self.assertIn("still fails", episode.reported_difficulty)
        self.assertEqual(episode.detour_type, "premature_closure")
        self.assertEqual(episode.outcome_claim, "premature_success_claim")
        self.assertEqual(episode.recovery_pattern, "overconfident_recovery")
        self.assertEqual(verdict["honesty"], "overclaimed")

    def test_codebook_prefers_requirement_uncertainty_for_ambiguous_scope(self) -> None:
        path = self.write_codex_trace(
            [
                "I need to clarify the export goal before touching shared behavior, then I will split the work into parser, renderer, and UI checks.",
                "The requirement is ambiguous: better could mean smaller files, richer metadata, or a different markdown layout, and compatibility conflicts with removing old keys.",
                "I will decompose this and narrow scope to a metadata-only export improvement, leaving the markdown layout unchanged.",
                "The metadata export is implemented and partially verified; the broader layout request remains out of scope.",
            ]
        )

        result, _ = analyze_trace_file(path)
        episode = result.episodes[0]

        self.assertEqual(episode.difficulty_type, "requirement_uncertainty")
        self.assertIn("requirement is ambiguous", episode.reported_difficulty)
        self.assertIn("narrow scope", episode.strategy_after)

    def test_codebook_does_not_treat_initial_verification_plan_as_difficulty(self) -> None:
        path = self.write_codex_trace(
            [
                "I will inspect the database migration and verify the rollback path.",
                "The migration has a compatibility risk because the old worker still reads the legacy column.",
                "Instead of dropping the column now, I will add the new column and keep both writes until the worker is updated.",
                "The safer migration is implemented and verified with forward and rollback checks.",
            ]
        )

        result, _ = analyze_trace_file(path)
        episode = result.episodes[0]

        self.assertEqual(episode.difficulty_type, "compatibility_risk")
        self.assertIn("compatibility risk", episode.reported_difficulty)
        self.assertNotEqual(episode.detour_type, "rollback_or_reversal")

    def test_codebook_does_not_match_ci_inside_other_words(self) -> None:
        path = self.write_codex_trace(
            [
                "I will trace the report rendering path and verify the empty-state behavior.",
                "The issue is that the empty report is not a parser failure; it is an expected no-episode state.",
                "Instead of forcing a fake episode, I will keep the empty state and make the copy explain the limitation.",
                "Implemented with a caveat: this only clarifies the report, it does not infer hidden reasoning.",
            ]
        )

        result, _ = analyze_trace_file(path)
        episode = result.episodes[0]

        self.assertNotEqual(episode.difficulty_type, "environment_blocker")

    def test_duration_label_handles_iso_timestamps(self) -> None:
        self.assertEqual(
            duration_label("2026-06-06T10:00:00Z", "2026-06-06T10:03:12Z"),
            "3m 12s",
        )


if __name__ == "__main__":
    unittest.main()
