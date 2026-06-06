from __future__ import annotations

import unittest
from pathlib import Path

from analyzer import analyze_trace_file, duration_label
from report_renderer import render_report


class AnalyzerTests(unittest.TestCase):
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

    def test_duration_label_handles_iso_timestamps(self) -> None:
        self.assertEqual(
            duration_label("2026-06-06T10:00:00Z", "2026-06-06T10:03:12Z"),
            "3m 12s",
        )


if __name__ == "__main__":
    unittest.main()
