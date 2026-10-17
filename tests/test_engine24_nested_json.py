"""World engine 24: a deeply nested answer is an unreadable answer, not a fatal crash.

Batch rows b1-s1005 (Month 6) and b1-s1007 (Month 11) paused as "fatal: RecursionError: maximum
recursion depth exceeded while decoding a JSON object" when a model's answer nested past the
interpreter's recursion limit: extract_json caught only json.JSONDecodeError. The fix reads such an
answer as unreadable, so it goes to the normal format retry, and puts the same guard on every other
json.loads of model or provider text. The streaming preview callbacks (claude, codex, antigravity)
needed none: cli_common.run already contains a callback's exception.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import versions  # noqa: E402
from karamaniya.backends import cli_common, make_backend  # noqa: E402
from karamaniya.backends.base import extract_json  # noqa: E402
from tests import stub_servers  # noqa: E402

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}, "note": {"type": "string"}},
          "required": ["ok", "note"], "additionalProperties": False}

# The shape of the b1-s1005/b1-s1007 answers: brackets nested far past the interpreter's limit.
NESTED = '{"a": ' + '[' * 100000 + ']' * 100000 + '}'


class Versions(unittest.TestCase):
    def test_the_bump(self):
        self.assertGreaterEqual((versions.WORLD_ENGINE, versions.AGENT_PROMPT, versions.PSYCHOLOGY,
                                 versions.ERROR_TAXONOMY), (24, 20, 8, 5))


class ExtractJson(unittest.TestCase):
    def test_a_deeply_nested_answer_reads_as_unreadable(self):
        self.assertIsNone(extract_json(NESTED))

    def test_the_fence_and_chunk_paths_read_it_the_same(self):
        self.assertIsNone(extract_json("```json\n" + NESTED + "\n```"))
        self.assertIsNone(extract_json("Here is my answer: " + NESTED))

    def test_deep_but_readable_json_still_parses(self):
        import json
        text = '{"a": ' + '[' * 50 + '1' + ']' * 50 + '}'
        self.assertEqual(extract_json(text), json.loads(text))


class JsonLines(unittest.TestCase):
    def test_a_deeply_nested_line_is_skipped_not_fatal(self):
        out = cli_common.json_lines('{"a": 1}\n' + NESTED + '\n{"b": 2}')
        self.assertEqual(out, [{"a": 1}, {"b": 2}])


class WholeStdoutFallbacks(unittest.TestCase):
    """The CLI fallbacks that parse all of stdout at once: claude_cli (an old CLI that ignored
    stream-json) and qoder_cli. The mock stands in for the CLI process."""

    def test_claude_whole_stdout(self):
        with mock.patch.object(cli_common, "run", return_value=(0, NESTED, "")):
            res = make_backend({"provider": "claude_cli", "model": "", "cli_command": ["fake"],
                                "retries": 0, "timeout": 5}).complete("S", "U", SCHEMA)
        self.assertTrue(res.error)
        self.assertNotIn("RecursionError", res.error)
        self.assertIn("unreadable output", res.error)

    def test_qoder_whole_stdout(self):
        with mock.patch.object(cli_common, "run", return_value=(0, NESTED, "")):
            res = make_backend({"provider": "qoder_cli", "model": "q", "cli_command": ["fake"],
                                "retries": 0, "timeout": 5}).complete("S", "U", SCHEMA)
        self.assertTrue(res.error)
        self.assertNotIn("RecursionError", res.error)


class OverHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.state, cls.url = stub_servers.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.state.text_override = None
        self.state.raw_body = None
        self.state.message_extra = {}
        self.state.usage = {}
        self.addCleanup(setattr, self.state, "text_override", None)
        self.addCleanup(setattr, self.state, "raw_body", None)
        os.environ["KARAMANIYA_TEST_KEY"] = "sk-test"

    def compat(self):
        return make_backend({"provider": "deepseek", "model": "x", "base_url": self.url,
                             "api_key_env": "KARAMANIYA_TEST_KEY", "retries": 0})

    def ollama(self):
        return make_backend({"provider": "ollama", "model": "x", "base_url": self.url, "retries": 0})

    def test_a_nested_answer_goes_to_the_format_retry(self):
        for name, backend in (("openai_compat", self.compat()), ("ollama", self.ollama())):
            with self.subTest(backend=name):
                self.state.text_override = NESTED
                res = backend.complete("S", "U", SCHEMA)
                self.assertIsNone(res.data)
                self.assertTrue(res.format_retry)
                self.assertEqual(res.error, "")
                self.assertNotIn("RecursionError", res.error)

    def test_a_nested_reply_body_is_a_transient_error_not_a_crash(self):
        for name, backend in (("openai_compat", self.compat()), ("ollama", self.ollama())):
            with self.subTest(backend=name):
                self.state.raw_body = NESTED
                res = backend.complete("S", "U", SCHEMA)
                self.assertIsNone(res.data)
                self.assertIn("unreadable response", res.error)
                self.assertNotIn("RecursionError", res.error)


if __name__ == "__main__":
    unittest.main()
