from __future__ import annotations

import unittest

from redaction import redact_text


class RedactionTests(unittest.TestCase):
    def test_redacts_common_secret_shapes(self) -> None:
        text = (
            "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456\n"
            "email test@example.com\n"
            "token ghp_abcdefghijklmnopqrstuvwxyz123456\n"
            "path /Users/alice/project/private/file.py\n"
            "url https://example.com/callback?code=secret&state=abc"
        )

        result = redact_text(text)

        self.assertNotIn("abcdefghijklmnopqrstuvwxyz123456", result.text)
        self.assertNotIn("test@example.com", result.text)
        self.assertNotIn("/Users/alice/project", result.text)
        self.assertIn("[REDACTED_GITHUB_TOKEN]", result.text)
        self.assertIn("[REDACTED_EMAIL]", result.text)
        self.assertGreaterEqual(result.count, 4)


if __name__ == "__main__":
    unittest.main()
