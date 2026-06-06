from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from parser import parse_trace


class ParserTests(unittest.TestCase):
    def write_jsonl(self, records: list[dict]) -> Path:
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl", delete=False)
        with handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        return Path(handle.name)

    def test_parses_codex_response_items_and_ignores_tools(self) -> None:
        path = self.write_jsonl(
            [
                {"type": "session_meta", "payload": {"originator": "codex_cli"}},
                {
                    "timestamp": "2026-06-06T00:00:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "I will inspect the failing path."},
                            {"type": "tool_call", "name": "exec", "arguments": "cat secret.py"},
                        ],
                    },
                },
                {
                    "timestamp": "2026-06-06T00:00:02Z",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Please fix it."}],
                    },
                },
            ]
        )

        messages, agent_type = parse_trace(path)

        self.assertEqual(agent_type, "codex")
        self.assertEqual([message.role for message in messages], ["assistant", "user"])
        self.assertIn("inspect", messages[0].text)
        self.assertNotIn("secret.py", messages[0].text)

    def test_parses_claude_message_shape(self) -> None:
        path = self.write_jsonl(
            [
                {
                    "parentUuid": None,
                    "sessionId": "session",
                    "type": "assistant",
                    "timestamp": "2026-06-06T00:00:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "The test failed, so I will verify another path."}],
                    },
                }
            ]
        )

        messages, agent_type = parse_trace(path)

        self.assertEqual(agent_type, "claude_code")
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].role, "assistant")
        self.assertIn("test failed", messages[0].text)


if __name__ == "__main__":
    unittest.main()
