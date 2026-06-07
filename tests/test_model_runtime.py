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
    parse_model_json,
    run_model_assist,
)


MEMO_JSON = {
    "executive_memo": "The trace shows a visible upload-boundary correction.",
    "detour_memo": "E01 narrows scope instead of changing the parser.",
    "outcome_audit_memo": "The agent keeps a deployment caveat visible.",
    "caveats": ["Model memo is based only on redacted narrative."],
}


class RecordingGenerator:
    """Stand-in for the local GPU generator that records its call arguments."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, messages, *, model_id, max_new_tokens) -> str:
        self.calls.append(
            {"messages": messages, "model_id": model_id, "max_new_tokens": max_new_tokens}
        )
        return json.dumps(MEMO_JSON)


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

    def test_parse_model_json_validates_required_shape(self) -> None:
        memo = parse_model_json(json.dumps(MEMO_JSON))

        self.assertEqual(memo["executive_memo"], MEMO_JSON["executive_memo"])
        self.assertEqual(memo["caveats"], MEMO_JSON["caveats"])

    def test_parse_model_json_recovers_from_code_fence(self) -> None:
        memo = parse_model_json("```json\n" + json.dumps(MEMO_JSON) + "\n```")

        self.assertEqual(memo["detour_memo"], MEMO_JSON["detour_memo"])

    def test_parse_model_json_extracts_object_from_prose(self) -> None:
        raw = "Here is the analysis:\n" + json.dumps(MEMO_JSON) + "\nHope this helps."
        memo = parse_model_json(raw)

        self.assertEqual(memo["outcome_audit_memo"], MEMO_JSON["outcome_audit_memo"])

    def test_run_model_assist_uses_selected_model(self) -> None:
        result, narrative = analyze_trace_file(Path("examples/sample_trace_redacted.jsonl"))
        generate = RecordingGenerator()

        assist = run_model_assist(
            engine="nemotron",
            result=result,
            narrative_text=narrative,
            generate=generate,
        )

        self.assertEqual(assist.model_id, PRIMARY_MODEL_ID)
        self.assertIn("upload-boundary", assist.memo["executive_memo"])
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
        self.assertEqual(input_ids.device, "cuda")
        self.assertEqual(attention_mask.device, "cuda")

    def test_qwen_chat_template_enables_thinking(self) -> None:
        self.assertEqual(_chat_template_kwargs(QUICK_MODEL_ID), {"enable_thinking": True})
        self.assertEqual(_chat_template_kwargs(PRIMARY_MODEL_ID), {})

    def test_analyzer_records_unknown_engine_note(self) -> None:
        result, _ = analyze_trace_file(
            Path("examples/sample_trace_redacted.jsonl"),
            analysis_engine="missing-engine",
        )

        self.assertTrue(result.model_notes)
        self.assertIn("Unknown analysis engine", result.model_notes[0])

    def test_analyzer_model_error_note_avoids_double_period(self) -> None:
        with patch("analyzer.run_model_assist", side_effect=ValueError("model unavailable.")):
            result, _ = analyze_trace_file(
                Path("examples/sample_trace_redacted.jsonl"),
                analysis_engine="qwen",
            )

        self.assertTrue(result.model_notes)
        self.assertNotIn("..", result.model_notes[0])
        self.assertIn("ValueError: model unavailable.", result.model_notes[0])

    def test_analyzer_records_model_engine_on_success(self) -> None:
        with patch("analyzer.run_model_assist") as run_model_assist:
            run_model_assist.return_value = types.SimpleNamespace(
                model_id=PRIMARY_MODEL_ID,
                memo=dict(MEMO_JSON),
                note="ok",
            )
            result, _ = analyze_trace_file(
                Path("examples/sample_trace_redacted.jsonl"),
                analysis_engine="nemotron",
            )

        self.assertIn(PRIMARY_MODEL_ID, result.engine)
        self.assertNotIn("token", run_model_assist.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
