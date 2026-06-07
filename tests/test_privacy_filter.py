from __future__ import annotations

import unittest
from pathlib import Path

from analyzer import stream_deterministic_analysis
from privacy_filter import PII_TYPES, redact_texts
from redaction import RedactionResult


def fake_detect(texts: list[str]) -> list[list[dict]]:
    """Stand-in detector: flags "Alice Smith" and "555-1234" without torch."""

    results = []
    for text in texts:
        spans = []
        person = text.find("Alice Smith")
        if person != -1:
            spans.append({"start": person, "end": person + len("Alice Smith"), "label": "private_person"})
        phone = text.find("555-1234")
        if phone != -1:
            spans.append({"start": phone, "end": phone + len("555-1234"), "label": "private_phone"})
        results.append(spans)
    return results


def _drain(stream):
    result = None
    for kind, payload in stream:
        if kind == "result":
            result = payload[0]
    assert result is not None
    return result


class PrivacyFilterMaskingTests(unittest.TestCase):
    def test_redact_texts_masks_detected_spans(self) -> None:
        texts = ["Call Alice Smith at 555-1234 tomorrow.", "no pii here"]

        results = redact_texts(texts, detect=fake_detect)

        self.assertIsInstance(results[0], RedactionResult)
        self.assertNotIn("Alice Smith", results[0].text)
        self.assertNotIn("555-1234", results[0].text)
        self.assertIn(PII_TYPES["private_person"][0], results[0].text)
        self.assertIn(PII_TYPES["private_phone"][0], results[0].text)
        self.assertEqual(results[0].count, 2)
        self.assertEqual(results[1].count, 0)
        self.assertEqual(results[1].text, "no pii here")

    def test_notes_are_human_readable(self) -> None:
        results = redact_texts(["Alice Smith"], detect=fake_detect)

        self.assertIn("personal name: 1", results[0].notes)

    def test_malformed_and_overlapping_spans_are_skipped(self) -> None:
        def detect(texts: list[str]) -> list[list[dict]]:
            return [
                [
                    {"start": 0, "end": 999, "label": "secret"},  # out of range
                    {"start": 2, "end": 2, "label": "secret"},  # zero width
                ]
            ]

        results = redact_texts(["abc"], detect=detect)

        self.assertEqual(results[0].text, "abc")
        self.assertEqual(results[0].count, 0)

    def test_unknown_labels_are_ignored(self) -> None:
        def detect(texts: list[str]) -> list[list[dict]]:
            return [[{"start": 0, "end": 3, "label": "not_a_pii_type"}]]

        results = redact_texts(["abc"], detect=detect)

        self.assertEqual(results[0].text, "abc")
        self.assertEqual(results[0].count, 0)

    def test_bioes_fragments_merge_into_one_placeholder(self) -> None:
        # The real model fragments "Alice Smith" into touching same-label spans
        # ("Alice" + " Smith"); they must collapse to a single placeholder.
        def detect(texts: list[str]) -> list[list[dict]]:
            return [
                [
                    {"start": 0, "end": 5, "label": "private_person"},  # Alice
                    {"start": 5, "end": 11, "label": "private_person"},  # " Smith"
                ]
            ]

        results = redact_texts(["Alice Smith calls"], detect=detect)

        self.assertEqual(results[0].text.count("[REDACTED_NAME]"), 1)
        self.assertEqual(results[0].count, 1)
        self.assertEqual(results[0].text, "[REDACTED_NAME] calls")

    def test_same_label_spans_with_one_char_gap_merge(self) -> None:
        def detect(texts: list[str]) -> list[list[dict]]:
            return [
                [
                    {"start": 0, "end": 5, "label": "private_person"},  # Alice
                    {"start": 6, "end": 11, "label": "private_person"},  # Smith (gap = space)
                ]
            ]

        results = redact_texts(["Alice Smith"], detect=detect)

        self.assertEqual(results[0].count, 1)

    def test_different_label_adjacent_spans_stay_separate(self) -> None:
        def detect(texts: list[str]) -> list[list[dict]]:
            return [
                [
                    {"start": 0, "end": 5, "label": "private_person"},
                    {"start": 6, "end": 14, "label": "private_phone"},
                ]
            ]

        results = redact_texts(["Alice 555-1234"], detect=detect)

        self.assertEqual(results[0].count, 2)
        self.assertIn(PII_TYPES["private_person"][0], results[0].text)
        self.assertIn(PII_TYPES["private_phone"][0], results[0].text)


class StreamRedactionIntegrationTests(unittest.TestCase):
    SAMPLE = Path("examples/sample_trace_redacted.jsonl")

    def test_stream_records_ai_privacy_note_when_model_runs(self) -> None:
        def passthrough(texts: list[str]) -> list[RedactionResult]:
            return [RedactionResult(text=text, notes=[], count=0) for text in texts]

        result = _drain(stream_deterministic_analysis(self.SAMPLE, model_redact=passthrough))

        self.assertTrue(any("AI privacy filter (openai/privacy-filter)" in note for note in result.privacy_notes))

    def test_stream_falls_back_gracefully_when_model_unavailable(self) -> None:
        def boom(texts: list[str]) -> list[RedactionResult]:
            raise RuntimeError("no gpu here")

        result = _drain(stream_deterministic_analysis(self.SAMPLE, model_redact=boom))

        self.assertTrue(any("AI privacy filter was unavailable" in note for note in result.privacy_notes))
        # Regex redaction still ran on the sample (it embeds an email + token).
        self.assertGreater(result.redaction_count, 0)

    def test_redact_progress_streams_per_chunk(self) -> None:
        events = [
            payload
            for kind, payload in stream_deterministic_analysis(
                self.SAMPLE, stream_redact_progress=True
            )
            if kind == "progress" and payload.get("stage") == "redact"
        ]

        # 4-message sample -> chunk size 1 -> one redact event per message.
        self.assertGreaterEqual(len(events), 2)
        processed = [event["processed"] for event in events]
        self.assertEqual(processed, sorted(processed))  # monotonically advancing
        self.assertEqual(events[-1]["processed"], events[-1]["total"])  # finishes at total
        self.assertTrue(all(event["total"] == events[0]["total"] for event in events))

    def test_model_redaction_count_adds_to_regex_count(self) -> None:
        def mask_first_word(texts: list[str]) -> list[RedactionResult]:
            out = []
            for text in texts:
                if text:
                    out.append(RedactionResult(text="[REDACTED_NAME]" + text, notes=["personal name: 1"], count=1))
                else:
                    out.append(RedactionResult(text=text, notes=[], count=0))
            return out

        regex_only = _drain(stream_deterministic_analysis(self.SAMPLE))
        combined = _drain(stream_deterministic_analysis(self.SAMPLE, model_redact=mask_first_word))

        self.assertGreater(combined.redaction_count, regex_only.redaction_count)


if __name__ == "__main__":
    unittest.main()
