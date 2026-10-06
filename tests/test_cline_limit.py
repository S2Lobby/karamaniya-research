"""A used-up ClinePass reported as the answer text pauses the run like any other plan limit."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya.backends import make_backend  # noqa: E402
from karamaniya.backends.base import QuotaError  # noqa: E402
from karamaniya.backends.cli_common import classify  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = os.path.join(HERE, "tests", "fake_cli.py")
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}, "note": {"type": "string"}},
          "required": ["ok", "note"], "additionalProperties": False}
MESSAGE = "You have reached your monthly Clinepass limit. The limit resets in 1h 11m, please try again later."
KEYS = ("FAKE_CLI_LIMIT_AFTER", "FAKE_CLI_COUNTER", "FAKE_CLI_LIMIT_STYLE", "FAKE_CLI_RECORD")


class ClinePassLimit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-cline-limit-")
        self.saved = {k: os.environ.get(k) for k in KEYS}
        os.environ.pop("FAKE_CLI_RECORD", None)
        os.environ["FAKE_CLI_COUNTER"] = os.path.join(self.tmp, "count")

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def backend(self):
        return make_backend({"provider": "cline_cli", "model": "cline-pass/kimi-k3", "cline_provider": "cline-pass",
                             "cli_command": [sys.executable, FAKE, "cline"], "retries": 0, "timeout": 60})

    def test_the_message_reads_as_a_used_up_plan(self):
        self.assertIsInstance(classify(MESSAGE, "Cline CLI"), QuotaError)

    def test_limit_as_answer_text_is_a_quota_pause_not_a_silent_seat(self):
        os.environ["FAKE_CLI_LIMIT_AFTER"] = "0"
        os.environ["FAKE_CLI_LIMIT_STYLE"] = "text"
        res = self.backend().complete("SYSTEM", 'Reply with {"ok": true, "note": "ready"}.', SCHEMA)
        self.assertTrue(res.quota, res.error)
        self.assertIn("monthly Clinepass limit", res.error)

    def test_a_normal_answer_still_passes(self):
        os.environ.pop("FAKE_CLI_LIMIT_AFTER", None)
        res = self.backend().complete("SYSTEM", 'Reply with {"ok": true, "note": "ready"}.', SCHEMA)
        self.assertEqual(res.data, {"ok": True, "note": "ready"}, res.error)
        self.assertFalse(res.quota)


if __name__ == "__main__":
    unittest.main()
