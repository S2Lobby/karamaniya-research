"""The GitHub Copilot CLI seat against a stand-in program: what it sends and what it reads back."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya.backends import CLI_PROVIDERS, PROVIDERS, make_backend  # noqa: E402
from karamaniya.backends.base import FatalError  # noqa: E402,F401

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = os.path.join(HERE, "tests", "fake_cli.py")
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}, "note": {"type": "string"}},
          "required": ["ok", "note"], "additionalProperties": False}
SYSTEM = "STANDING INSTRUCTIONS FOR THE TEST"
USER = 'Reply with {"ok": true, "note": "ready"}.'
KEYS = ("FAKE_CLI_RECORD", "FAKE_CLI_LIMIT_AFTER", "FAKE_CLI_COUNTER", "FAKE_CLI_NO_LOGIN")


class CopilotSeat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-copilot-test-")
        self.saved = {k: os.environ.get(k) for k in KEYS}
        for k in KEYS:
            os.environ.pop(k, None)
        os.environ["FAKE_CLI_RECORD"] = os.path.join(self.tmp, "record.json")
        os.environ["FAKE_CLI_COUNTER"] = os.path.join(self.tmp, "count")

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def backend(self, **extra):
        return make_backend({"provider": "copilot_cli", "model": extra.pop("model", "auto"),
                             "cli_command": [sys.executable, FAKE, "copilot"], "retries": 0, "timeout": 60, **extra})

    def sent(self):
        with open(os.environ["FAKE_CLI_RECORD"], encoding="utf-8") as f:
            return json.load(f)

    def test_registered_as_a_login_seat(self):
        self.assertIn("copilot_cli", PROVIDERS)
        self.assertIn("copilot_cli", CLI_PROVIDERS)

    def test_headless_answer_with_every_tool_off(self):
        res = self.backend(effort="low").complete(SYSTEM, USER, SCHEMA)
        self.assertEqual(res.data, {"ok": True, "note": "ready"}, res.error)
        # "auto" is recorded as the model Copilot actually chose, with the usage file's token counts.
        self.assertEqual((res.input_tokens, res.output_tokens, res.served_model), (10202, 139, "mai-code-1.1-flash"))
        sent = self.sent()
        argv, prompt = sent["argv"], sent["stdin"]
        self.assertNotIn("-p", argv)                              # the prompt goes in on stdin
        self.assertTrue(prompt.startswith("# Standing instructions"))
        self.assertIn(SYSTEM, prompt)
        self.assertIn(USER, prompt)
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        for flag in ("--no-auto-update", "--no-custom-instructions", "--disable-builtin-mcps"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[-1], "--available-tools")          # given no tools at all
        self.assertNotIn("--allow-all-tools", argv)
        self.assertNotIn("--yolo", argv)
        self.assertEqual(argv[argv.index("--reasoning-effort") + 1], "low")
        workdir = argv[argv.index("-C") + 1]
        self.assertEqual(os.listdir(workdir), [])                 # an empty scratch folder

    def test_non_ascii_and_long_prompts_arrive_intact(self):
        user = "Grain — the delegates’ “duty”, Привет. " + "pad " * 9000 + USER
        res = self.backend().complete(SYSTEM, user, SCHEMA)
        self.assertEqual(res.data, {"ok": True, "note": "ready"}, res.error)
        self.assertGreater(len(user), 32767)                       # longer than any Windows command line
        self.assertIn(user, self.sent()["stdin"])

    def test_a_named_model_is_passed_through(self):
        res = self.backend(model="gpt-5.5").complete(SYSTEM, USER, SCHEMA)
        self.assertEqual(res.served_model, "gpt-5.5")
        argv = self.sent()["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "gpt-5.5")

    def test_not_logged_in_is_a_clear_fatal_error(self):
        os.environ["FAKE_CLI_NO_LOGIN"] = "1"
        res = self.backend().complete(SYSTEM, USER, SCHEMA)
        self.assertIsNone(res.data)
        self.assertIn("copilot login", res.error)
        self.assertFalse(res.quota)

    def test_used_up_premium_requests_pause_the_run(self):
        os.environ["FAKE_CLI_LIMIT_AFTER"] = "0"
        res = self.backend().complete(SYSTEM, USER, SCHEMA)
        self.assertTrue(res.quota, res.error)

    def test_wrapped_plain_text_is_not_the_reply_source(self):
        # The plain-text mode hard-wraps long lines inside JSON strings; only the event stream is read.
        from karamaniya.backends.copilot_cli import read_events
        stream = "\n".join(json.dumps(e) for e in (
            {"type": "assistant.message", "data": {"model": "m", "content": '{"note": "' + "word " * 60 + '"}'}},
            {"type": "result", "exitCode": 0}))
        events = read_events("some banner text\n" + stream)
        self.assertEqual(events["model"], "m")
        self.assertEqual(json.loads(events["text"])["note"], "word " * 60)

    def test_budget_is_no_longer_capped_by_the_command_line(self):
        self.assertEqual(self.backend().prompt_budget(8500), 60000)


if __name__ == "__main__":
    unittest.main()
