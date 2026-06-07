from __future__ import annotations

import json
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from analyzer import analyze_trace_file
from model_runtime import (
    MODEL_CHOICES,
    MODEL_MAX_NEW_TOKENS,
    PRIMARY_MODEL_ID,
    QUICK_MODEL_ID,
    _chat_template_kwargs,
    _prepare_generation_inputs,
    parse_analysis_json,
    resolve_device,
    run_model_analysis,
)


ANALYSIS_JSON = {
    "verdict": {
        "tone": "partial",
        "headline": "Reroute landed with a caveat.",
        "detail": "The agent caught a wrong assumption about the upload shape and narrowed the fix.",
        "honesty": "candid",
    },
    "overall_patterns": {
        "difficulty_style": "One localization snag.",
        "detour_style": "A productive narrowing.",
        "recovery_style": "Reflective.",
        "risk_or_caveat": "Deployment path left unverified.",
    },
    "episodes": [
        {
            "start_index": 0,
            "end_index": 3,
            "title": "Upload boundary fix",
            "initial_intention": "Inspect the failing upload path.",
            "reported_difficulty": "The Gradio file object can arrive as a temporary path.",
            "difficulty_type": "localization_difficulty",
            "appraisal": "initial_hypothesis_wrong",
            "strategy_before": "Fix the parser.",
            "strategy_after": "Narrow the fix to the upload boundary.",
            "detour_type": "scope_narrowing",
            "resolution_mode": "defensive_handling",
            "recovery_pattern": "reflective_recovery",
            "outcome_claim": "resolved_with_caveat",
            "productive_detour": "yes",
            "evidence_quotes": ["my initial assumption about the upload shape was wrong"],
            "analyst_memo": "The agent names the wrong assumption and picks the smaller change.",
        }
    ],
}


class RecordingGenerator:
    """Stand-in for the local GPU generator that records its call arguments."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, messages, *, model_id, max_new_tokens) -> str:
        self.calls.append(
            {"messages": messages, "model_id": model_id, "max_new_tokens": max_new_tokens}
        )
        return json.dumps(ANALYSIS_JSON)


class FakeTensor:
    def __init__(self, shape: tuple[int, ...]) -> None:
        self.shape = shape
        self.device = None

    def to(self, device: str) -> "FakeTensor":
        self.device = device
        return self


class ModelRuntimeTests(unittest.TestCase):
    def test_nemotron_label_does_not_call_it_small(self) -> None:
        label = str(MODEL_CHOICES["nemotron"]["label"])

        self.assertIn("NVIDIA Nemotron 3 Nano 30B-A3B", label)
        self.assertNotIn("small", label.lower())

    def test_minicpm_is_the_quick_engine(self) -> None:
        self.assertEqual(MODEL_CHOICES["minicpm"]["model_id"], QUICK_MODEL_ID)
        self.assertIn("MiniCPM5 1B", str(MODEL_CHOICES["minicpm"]["label"]))
        self.assertNotIn("qwen", MODEL_CHOICES)

    def test_minicpm_chat_template_disables_thinking(self) -> None:
        self.assertEqual(_chat_template_kwargs(QUICK_MODEL_ID), {"enable_thinking": False})
        self.assertEqual(_chat_template_kwargs(PRIMARY_MODEL_ID), {})

    def test_resolve_device_honors_explicit_override(self) -> None:
        self.assertEqual(resolve_device("cpu"), "cpu")
        self.assertEqual(resolve_device("cuda"), "cuda")
        self.assertEqual(resolve_device("mps"), "mps")

    def test_parse_analysis_json_validates_shape(self) -> None:
        parsed = parse_analysis_json(json.dumps(ANALYSIS_JSON))

        self.assertEqual(len(parsed["episodes"]), 1)
        self.assertEqual(parsed["verdict"]["tone"], "partial")

    def test_parse_analysis_json_recovers_from_code_fence(self) -> None:
        parsed = parse_analysis_json("```json\n" + json.dumps(ANALYSIS_JSON) + "\n```")

        self.assertEqual(parsed["episodes"][0]["difficulty_type"], "localization_difficulty")

    def test_parse_analysis_json_extracts_object_from_prose(self) -> None:
        raw = "Here is the report:\n" + json.dumps(ANALYSIS_JSON) + "\nDone."
        parsed = parse_analysis_json(raw)

        self.assertEqual(parsed["verdict"]["honesty"], "candid")

    def test_parse_analysis_json_uses_final_object_after_thinking_braces(self) -> None:
        raw = (
            "<think>Draft {not json} and a scratch object "
            '{"draft": "ignore this"} before the final answer.</think>\n'
            + json.dumps(ANALYSIS_JSON)
        )
        parsed = parse_analysis_json(raw)

        self.assertEqual(len(parsed["episodes"]), 1)

    def test_parse_analysis_json_requires_episodes_list(self) -> None:
        with self.assertRaises(ValueError):
            parse_analysis_json(json.dumps({"verdict": {}, "overall_patterns": {}}))

    def test_run_model_analysis_uses_selected_model(self) -> None:
        generate = RecordingGenerator()

        produced = run_model_analysis(
            engine="nemotron",
            numbered_narrative="[0] assistant 10:00: hello",
            generate=generate,
        )

        self.assertEqual(produced.model_id, PRIMARY_MODEL_ID)
        self.assertEqual(len(produced.analysis["episodes"]), 1)
        self.assertEqual(generate.calls[0]["model_id"], PRIMARY_MODEL_ID)
        self.assertEqual(generate.calls[0]["max_new_tokens"], MODEL_MAX_NEW_TOKENS)

    def test_prepare_generation_inputs_accepts_tensor_output(self) -> None:
        tensor = FakeTensor((1, 12))

        generation_inputs, prompt_tokens = _prepare_generation_inputs(tensor, device="cuda")

        self.assertEqual(generation_inputs, {"inputs": tensor})
        self.assertEqual(prompt_tokens, 12)
        self.assertEqual(tensor.device, "cuda")

    def test_prepare_generation_inputs_expands_batch_encoding_output(self) -> None:
        input_ids = FakeTensor((1, 21))
        attention_mask = FakeTensor((1, 21))

        generation_inputs, prompt_tokens = _prepare_generation_inputs(
            {"input_ids": input_ids, "attention_mask": attention_mask},
            device="cuda",
        )

        self.assertEqual(generation_inputs["input_ids"], input_ids)
        self.assertEqual(generation_inputs["attention_mask"], attention_mask)
        self.assertEqual(prompt_tokens, 21)

    def test_analyzer_records_unknown_engine_note(self) -> None:
        result, _ = analyze_trace_file(
            Path("examples/sample_trace_redacted.jsonl"),
            analysis_engine="missing-engine",
        )

        self.assertTrue(result.model_notes)
        self.assertIn("Unknown analysis engine", result.model_notes[0])

    def test_analyzer_model_error_note_avoids_double_period(self) -> None:
        with patch("analyzer.run_model_analysis", side_effect=ValueError("model unavailable.")):
            result, _ = analyze_trace_file(
                Path("examples/sample_trace_redacted.jsonl"),
                analysis_engine="minicpm",
            )

        self.assertTrue(result.model_notes)
        self.assertNotIn("..", result.model_notes[0])
        self.assertIn("ValueError: model unavailable.", result.model_notes[0])

    def test_analyzer_replaces_analysis_on_model_success(self) -> None:
        with patch("analyzer.run_model_analysis") as run:
            run.return_value = types.SimpleNamespace(
                model_id=PRIMARY_MODEL_ID,
                analysis=dict(ANALYSIS_JSON),
                note=f"Analysis produced by {PRIMARY_MODEL_ID}.",
            )
            result, _ = analyze_trace_file(
                Path("examples/sample_trace_redacted.jsonl"),
                analysis_engine="nemotron",
            )

        self.assertEqual(result.engine, PRIMARY_MODEL_ID)
        self.assertEqual(result.session_verdict["tone"], "partial")
        self.assertEqual(result.episodes[0].episode_id, "E01")
        self.assertEqual(result.episodes[0].difficulty_type, "localization_difficulty")

    def test_analyzer_strips_placeholder_echoes(self) -> None:
        bad = {
            "verdict": {"tone": "stable", "headline": "<= 12 words", "detail": "2-4 sentences", "honesty": "candid"},
            "overall_patterns": {},
            "episodes": [
                {
                    "start_index": 0,
                    "end_index": 0,
                    "title": "<= 10 words",
                    "reported_difficulty": "The build failed.",
                    "difficulty_type": "environment_blocker",
                    "analyst_memo": "1-3 sentences",
                    "evidence_quotes": ["short verbatim quote", "the build failed"],
                    "outcome_claim": "not_resolved",
                }
            ],
        }
        with patch("analyzer.run_model_analysis") as run:
            run.return_value = types.SimpleNamespace(model_id=QUICK_MODEL_ID, analysis=bad, note="ok")
            result, _ = analyze_trace_file(
                Path("examples/sample_trace_redacted.jsonl"), analysis_engine="minicpm"
            )

        episode = result.episodes[0]
        self.assertEqual(episode.title, "The build failed.")  # placeholder -> reported_difficulty
        self.assertEqual(episode.analyst_memo, "")  # "1-3 sentences" stripped
        self.assertEqual(episode.evidence_quotes, ["the build failed"])  # placeholder quote dropped
        self.assertNotIn("<", result.session_verdict["headline"])


if __name__ == "__main__":
    unittest.main()
