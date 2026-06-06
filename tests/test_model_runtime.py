from __future__ import annotations

import json
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from analyzer import analyze_trace_file
from model_runtime import MODEL_CHOICES, PRIMARY_MODEL_ID, parse_model_json, run_model_assist


class FakeChatClient:
    def chat_completion(self, *args, **kwargs):
        self.kwargs = kwargs
        content = json.dumps(
            {
                "executive_memo": "The trace shows a visible upload-boundary correction.",
                "detour_memo": "E01 narrows scope instead of changing the parser.",
                "outcome_audit_memo": "The agent keeps a deployment caveat visible.",
                "caveats": ["Model memo is based only on redacted narrative."],
            }
        )
        return types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content=content),
                )
            ]
        )


class ModelRuntimeTests(unittest.TestCase):
    def test_nemotron_label_does_not_call_it_small(self) -> None:
        label = str(MODEL_CHOICES["nemotron"]["label"])

        self.assertIn("NVIDIA Nemotron 3 Nano 30B-A3B", label)
        self.assertNotIn("small", label.lower())

    def test_parse_model_json_validates_required_shape(self) -> None:
        memo = parse_model_json(
            json.dumps(
                {
                    "executive_memo": "summary",
                    "detour_memo": "detour",
                    "outcome_audit_memo": "audit",
                    "caveats": ["one"],
                }
            )
        )

        self.assertEqual(memo["executive_memo"], "summary")
        self.assertEqual(memo["caveats"], ["one"])

    def test_run_model_assist_uses_selected_model(self) -> None:
        result, narrative = analyze_trace_file(Path("examples/sample_trace_redacted.jsonl"))
        client = FakeChatClient()

        assist = run_model_assist(
            engine="nemotron",
            result=result,
            narrative_text=narrative,
            client=client,
        )

        self.assertEqual(assist.model_id, PRIMARY_MODEL_ID)
        self.assertIn("upload-boundary", assist.memo["executive_memo"])
        self.assertEqual(client.kwargs["model"], PRIMARY_MODEL_ID)

    def test_analyzer_records_unknown_engine_note(self) -> None:
        result, _ = analyze_trace_file(
            Path("examples/sample_trace_redacted.jsonl"),
            analysis_engine="missing-engine",
        )

        self.assertTrue(result.model_notes)
        self.assertIn("Unknown analysis engine", result.model_notes[0])

    def test_analyzer_model_error_note_avoids_double_period(self) -> None:
        with patch("analyzer.run_model_assist", side_effect=ValueError("needs login.")):
            result, _ = analyze_trace_file(
                Path("examples/sample_trace_redacted.jsonl"),
                analysis_engine="qwen",
            )

        self.assertTrue(result.model_notes)
        self.assertNotIn("..", result.model_notes[0])
        self.assertIn("ValueError: needs login.", result.model_notes[0])

    def test_analyzer_passes_hf_token_to_model_assist(self) -> None:
        with patch("analyzer.run_model_assist") as run_model_assist:
            run_model_assist.return_value = types.SimpleNamespace(
                model_id=PRIMARY_MODEL_ID,
                memo={
                    "executive_memo": "memo",
                    "detour_memo": "detour",
                    "outcome_audit_memo": "audit",
                    "caveats": [],
                },
                note="ok",
            )
            result, _ = analyze_trace_file(
                Path("examples/sample_trace_redacted.jsonl"),
                analysis_engine="nemotron",
                hf_token="hf_test_token",
            )

        self.assertIn(PRIMARY_MODEL_ID, result.engine)
        self.assertEqual(run_model_assist.call_args.kwargs["token"], "hf_test_token")


if __name__ == "__main__":
    unittest.main()
