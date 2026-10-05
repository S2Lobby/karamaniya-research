"""The Qoder seat: registered as a login CLI, runs headless with tools off, parses the CLI's JSON
reply, and turns 'not logged in' into a clear instruction. No real CLI or login is touched."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya.backends import CLI_PROVIDERS, PROVIDERS, make_backend  # noqa: E402
from karamaniya.backends import cli_common  # noqa: E402
from karamaniya.backends.base import CallResult, FatalError, QuotaError  # noqa: E402
from karamaniya.backends.qoder_cli import QoderCLIBackend  # noqa: E402
from karamaniya import runner  # noqa: E402

SEAT = {"provider": "qoder_cli", "cli_command": ["qoder"], "model": "qoder-large", "label": "Q"}


class Registration(unittest.TestCase):
    def test_registered_as_a_login_seat(self):
        self.assertIn("qoder_cli", PROVIDERS)
        self.assertIn("qoder_cli", CLI_PROVIDERS)

    def test_make_backend_accepts_the_name_and_aliases(self):
        for provider in ("qoder_cli", "qoder", "qodercli"):
            self.assertIsInstance(make_backend({**SEAT, "provider": provider}), QoderCLIBackend)


class Command(unittest.TestCase):
    def test_headless_tools_off_system_prompt(self):
        cmd = QoderCLIBackend(SEAT)._command("STANDING INSTRUCTIONS")
        self.assertIn("-p", cmd)
        self.assertIn("--no-session-persistence", cmd)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")        # every tool disabled
        self.assertEqual(cmd[cmd.index("--system-prompt") + 1], "STANDING INSTRUCTIONS")
        self.assertEqual(cmd[cmd.index("--model") + 1], "qoder-large")


class Parsing(unittest.TestCase):
    def setUp(self):
        self._run = cli_common.run

    def tearDown(self):
        cli_common.run = self._run

    def test_structured_and_token_accounting(self):
        payload = {"result": "here you go", "structured_output": {"ok": True, "note": "ready"},
                   "usage": {"input_tokens": 100, "cache_read_input_tokens": 50, "output_tokens": 20},
                   "modelUsage": {"qoder-large": {}}, "stop_reason": "end_turn"}
        cli_common.run = lambda *a, **k: (0, json.dumps(payload), "")
        res = QoderCLIBackend(SEAT).call("sys", "user", {}, {})
        self.assertEqual(res.data, {"ok": True, "note": "ready"})
        self.assertEqual((res.input_tokens, res.output_tokens), (150, 20))
        self.assertEqual(res.served_model, "qoder-large")
        self.assertFalse(res.refusal)

    def test_answer_read_from_prose_when_no_structured_field(self):
        payload = {"result": 'the answer is {"stance": "yes"}', "usage": {"output_tokens": 5}}
        cli_common.run = lambda *a, **k: (0, json.dumps(payload), "")
        res = QoderCLIBackend(SEAT).call("sys", "user", {}, {})
        self.assertEqual(res.data, {"stance": "yes"})

    def test_malformed_optional_metadata_does_not_crash_response_parsing(self):
        # Some CLI failure/compatibility responses omit these objects or put diagnostic text in
        # their place. An otherwise valid answer should remain usable, with zero usage metadata.
        payload = {"result": '{"stance": "yes"}', "usage": "not reported",
                   "modelUsage": "not reported", "model": "Qwen3.8-Flash"}
        cli_common.run = lambda *a, **k: (0, json.dumps(payload), "")
        res = QoderCLIBackend(SEAT).call("sys", "user", {}, {})
        self.assertEqual(res.data, {"stance": "yes"})
        self.assertEqual((res.input_tokens, res.output_tokens), (0, 0))
        self.assertEqual(res.served_model, "Qwen3.8-Flash")

    def test_bad_token_counts_are_ignored_without_string_concatenation(self):
        payload = {"result": "{}", "usage": {"input_tokens": "12", "cache_read_input_tokens": 3,
                                               "cache_creation_input_tokens": "bad",
                                               "output_tokens": None},
                   "modelUsage": {"Qwen3.8-Flash": {}}}
        cli_common.run = lambda *a, **k: (0, json.dumps(payload), "")
        res = QoderCLIBackend(SEAT).call("sys", "user", {}, {})
        self.assertEqual((res.input_tokens, res.output_tokens), (15, 0))
        self.assertEqual(res.served_model, "Qwen3.8-Flash")

    def test_not_logged_in_is_a_clear_fatal(self):
        cli_common.run = lambda *a, **k: (1, "", "Not logged in. Run `qodercli login` to authenticate.")
        with self.assertRaises(FatalError) as ctx:
            QoderCLIBackend(SEAT).call("sys", "user", {}, {})
        self.assertIn("qoder login", str(ctx.exception))

    def test_daily_chat_limit_in_errors_array_is_classified_as_quota(self):
        payload = {"type": "result", "subtype": "error_during_execution", "is_error": True,
                   "usage": {"input_tokens": 0, "output_tokens": 0}, "error_code": 110,
                   "errors": ["You've reached your daily usage limit for Chat. Come back tomorrow."]}
        cli_common.run = lambda *a, **k: (0, json.dumps(payload), "")

        with self.assertRaises(QuotaError) as ctx:
            QoderCLIBackend(SEAT).call("sys", "user", {}, {})
        self.assertIn("daily usage limit", str(ctx.exception))

    def test_daily_chat_limit_is_reported_as_a_resumable_quota_result(self):
        payload = {"type": "result", "subtype": "error_during_execution", "is_error": True,
                   "usage": {"input_tokens": 0, "output_tokens": 0}, "error_code": 110,
                   "errors": ["You've reached your daily usage limit for Chat. Come back tomorrow."]}
        cli_common.run = lambda *a, **k: (0, json.dumps(payload), "")

        result = QoderCLIBackend(SEAT).complete("sys", "user", {}, {})
        self.assertTrue(result.quota)
        self.assertIn("daily usage limit", result.error)

    def test_seat_preflight_preserves_quota_classification(self):
        original = runner.make_backend

        class LimitedBackend:
            retries = 4
            timeout = 600

            def complete(self, *args, **kwargs):
                return CallResult(error="usage limit: Qoder CLI: daily usage limit", quota=True)

        runner.make_backend = lambda cfg: LimitedBackend()
        try:
            result, = runner.check_seats({"seats": [SEAT]})
        finally:
            runner.make_backend = original

        self.assertFalse(result["ok"])
        self.assertTrue(result["quota"])
        self.assertIn("daily usage limit", result["error"])

    def test_resume_preflight_explains_quota_and_keeps_checkpoint_retryable(self):
        original = runner.preflight
        runner.preflight = lambda cfg: [{"label": "Qwen-3.8", "provider": "qoder_cli",
                                         "model": "Qwen3.8-Flash", "quota": True,
                                         "error": "usage limit: Qoder CLI: daily usage limit"}]
        try:
            with self.assertRaises(SystemExit) as ctx:
                runner._require_seats({}, None, "resumed")
        finally:
            runner.preflight = original

        self.assertIn("provider usage limit", str(ctx.exception))
        self.assertIn("saved checkpoint is unchanged", str(ctx.exception))
        self.assertIn("after the provider's limit resets", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
