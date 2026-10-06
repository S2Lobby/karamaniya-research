"""Configuration checks that keep invalid provider token budgets from reaching a call."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya.config import normalize_config  # noqa: E402


class TokenBudgetValidation(unittest.TestCase):
    def _normalize(self, max_tokens):
        return normalize_config({"seat": [{"provider": "openai_compat", "label": "local",
                                            "max_tokens": max_tokens}]})

    def test_max_tokens_must_be_positive_and_whole(self):
        for value in (0, -1, True, 1.5, "not-a-number"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "max_tokens must be a positive integer"):
                self._normalize(value)

    def test_positive_integer_string_is_normalized(self):
        cfg = self._normalize("8000")
        self.assertEqual(cfg["seats"][0]["max_tokens"], 8000)


if __name__ == "__main__":
    unittest.main()
