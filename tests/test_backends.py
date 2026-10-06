"""Connectors against fake local servers: request shape, parsing, refusals, downgrades."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya.backends import make_backend  # noqa: E402
from karamaniya.backends.base import extract_json  # noqa: E402
from tests import stub_servers  # noqa: E402

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}, "note": {"type": "string"}},
          "required": ["ok", "note"], "additionalProperties": False}


class ExtractJson(unittest.TestCase):
    def test_plain_fenced_and_trailing_comma(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})
        self.assertEqual(extract_json('Sure!\n```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(extract_json('Answer: {"a": [1, 2,],}'), {"a": [1, 2]})
        self.assertIsNone(extract_json("no json here"))
        self.assertIsNone(extract_json("[1, 2]"))


class Backends(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.state, cls.url = stub_servers.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.state.requests.clear()
        self.state.reject_json_schema = False
        self.state.refuse = False
        self.state.usage = {}

    def test_anthropic_sdk_request_shape(self):
        try:
            import anthropic  # noqa: F401
        except ImportError:
            self.skipTest("anthropic SDK not installed (pip install -r requirements.txt)")
        os.environ["KARAMANIYA_TEST_KEY"] = "test-key"
        b = make_backend({"provider": "anthropic", "model": "claude-opus-5-5", "base_url": self.url,
                          "api_key_env": "KARAMANIYA_TEST_KEY", "effort": "medium",
                          "price_in": 4.0, "price_out": 20.0, "retries": 0})
        res = b.complete("SYSTEM TEXT", "USER TEXT", SCHEMA)
        self.assertEqual(res.data, {"ok": True, "note": "ready"})
        self.assertEqual(res.served_model, "claude-opus-5-5")
        self.assertAlmostEqual(res.cost_usd, 1200 / 1e6 * 4 + 80 / 1e6 * 20)
        path, headers, body = self.state.requests[-1]
        self.assertTrue(path.endswith("/v1/messages"))
        self.assertEqual(body["model"], "claude-opus-5-5")
        self.assertEqual(body["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(body["output_config"]["format"]["schema"], SCHEMA)
        self.assertEqual(body["output_config"]["effort"], "medium")
        self.assertEqual(body["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("fallbacks", body)
        self.assertNotIn("thinking", body)

    def test_anthropic_ignores_another_providers_environment(self):
        try:
            import anthropic  # noqa: F401
        except ImportError:
            self.skipTest("anthropic SDK not installed")
        saved = {k: os.environ.get(k) for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "KARAMANIYA_TEST_KEY")}
        try:
            # A Claude Code setup pointed at another provider must not reroute the Claude seat.
            os.environ["ANTHROPIC_BASE_URL"] = "https://other-provider.invalid/anthropic"
            os.environ["ANTHROPIC_AUTH_TOKEN"] = "other-provider-token"
            os.environ["KARAMANIYA_TEST_KEY"] = "test-key"
            b = make_backend({"provider": "anthropic", "model": "claude-opus-5-5",
                              "api_key_env": "KARAMANIYA_TEST_KEY"})
            self.assertEqual(str(b.client.base_url).rstrip("/"), "https://api.anthropic.com")
            self.assertEqual(b.client.auth_headers, {"X-Api-Key": "test-key"})
            del os.environ["KARAMANIYA_TEST_KEY"]
            with self.assertRaisesRegex(ValueError, "KARAMANIYA_TEST_KEY is not set"):
                make_backend({"provider": "anthropic", "model": "claude-opus-5-5",
                              "api_key_env": "KARAMANIYA_TEST_KEY"})
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_anthropic_refusal_is_recorded_not_retried(self):
        try:
            import anthropic  # noqa: F401
        except ImportError:
            self.skipTest("anthropic SDK not installed")
        os.environ["KARAMANIYA_TEST_KEY"] = "test-key"
        self.state.refuse = True
        b = make_backend({"provider": "anthropic", "model": "claude-opus-5-5", "base_url": self.url,
                          "api_key_env": "KARAMANIYA_TEST_KEY", "retries": 0})
        res = b.complete("S", "U", SCHEMA)
        self.assertTrue(res.refusal)
        self.assertIsNone(res.data)
        self.assertEqual(len(self.state.requests), 1)

    def test_anthropic_fallbacks_opt_in(self):
        try:
            import anthropic  # noqa: F401
        except ImportError:
            self.skipTest("anthropic SDK not installed")
        os.environ["KARAMANIYA_TEST_KEY"] = "test-key"
        b = make_backend({"provider": "anthropic", "model": "claude-opus-5", "base_url": self.url,
                          "api_key_env": "KARAMANIYA_TEST_KEY", "fallbacks": True, "retries": 0})
        b.complete("S", "U", SCHEMA)
        path, headers, body = self.state.requests[-1]
        self.assertEqual(body.get("fallbacks"), "default")
        self.assertIn("server-side-fallback-2026-07-01", headers.get("anthropic-beta", ""))

    def test_openai_compat_schema_then_downgrade(self):
        os.environ["KARAMANIYA_TEST_KEY"] = "sk-test"
        b = make_backend({"provider": "openai", "model": "gpt-test", "base_url": self.url + "/v1",
                          "api_key_env": "KARAMANIYA_TEST_KEY", "retries": 0})
        res = b.complete("S", "U", SCHEMA)
        self.assertEqual(res.data, {"ok": True, "note": "ready"})
        self.assertEqual(res.served_model, "gpt-test-2026")
        path, headers, body = self.state.requests[-1]
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        self.assertIn("max_completion_tokens", body)
        self.assertEqual(headers.get("Authorization"), "Bearer sk-test")
        self.state.reject_json_schema = True
        res = b.complete("S", "U", SCHEMA)
        self.assertEqual(res.data, {"ok": True, "note": "ready"})
        self.assertEqual(self.state.requests[-1][2]["response_format"]["type"], "json_object")

    def test_anthropic_cache_counts_are_recorded_and_priced_only_when_asked(self):
        try:
            import anthropic  # noqa: F401
        except ImportError:
            self.skipTest("anthropic SDK not installed")
        os.environ["KARAMANIYA_TEST_KEY"] = "test-key"
        self.state.usage = {"cache_read_input_tokens": 9000, "cache_creation_input_tokens": 1000}
        seat = {"provider": "anthropic", "model": "claude-opus-5-5", "base_url": self.url,
                "api_key_env": "KARAMANIYA_TEST_KEY", "price_in": 4.0, "price_out": 20.0, "retries": 0}
        res = make_backend(seat).complete("S", "U", SCHEMA)
        self.assertEqual((res.input_tokens, res.cache_read_tokens, res.cache_write_tokens), (11200, 9000, 1000))
        self.assertAlmostEqual(res.cost_usd, (11200 * 4 + 80 * 20) / 1e6)      # every input token at price_in
        res = make_backend({**seat, "price_cache_read": 0.4, "price_cache_write": 5.0}).complete("S", "U", SCHEMA)
        self.assertAlmostEqual(res.cost_usd, (1200 * 4 + 9000 * 0.4 + 1000 * 5 + 80 * 20) / 1e6)

    def test_anthropic_breakpoints_and_effort_by_phase_reach_the_request(self):
        try:
            import anthropic  # noqa: F401
        except ImportError:
            self.skipTest("anthropic SDK not installed")
        os.environ["KARAMANIYA_TEST_KEY"] = "test-key"
        b = make_backend({"provider": "anthropic", "model": "claude-opus-5-5", "base_url": self.url,
                          "api_key_env": "KARAMANIYA_TEST_KEY", "effort": "medium", "retries": 0,
                          "effort_by_phase": {"decision": "high"}})
        user = "SHARED PART|STANDING PART|THE PHASE"
        b.complete("S", user, SCHEMA, {"phase": "decision", "prompt_meta": {"cache_points": [12, 26]}})
        body = self.state.requests[-1][2]
        self.assertEqual(body["output_config"]["effort"], "high")
        blocks = body["messages"][0]["content"]
        self.assertEqual("".join(block["text"] for block in blocks), user)
        self.assertEqual([("cache_control" in block) for block in blocks], [True, True, False])
        b.complete("S", user, SCHEMA, {"phase": "session"})
        body = self.state.requests[-1][2]
        self.assertEqual(body["output_config"]["effort"], "medium")
        self.assertEqual(body["messages"][0]["content"], user)          # no cache points: one string, as before

    def test_openai_compat_cached_and_reasoning_tokens(self):
        os.environ["KARAMANIYA_TEST_KEY"] = "sk-test"
        b = make_backend({"provider": "openai", "model": "gpt-test", "base_url": self.url + "/v1",
                          "api_key_env": "KARAMANIYA_TEST_KEY", "retries": 0})
        self.state.usage = {"prompt_tokens_details": {"cached_tokens": 600},
                            "completion_tokens_details": {"reasoning_tokens": 40}}
        res = b.complete("S", "U", SCHEMA)
        self.assertEqual((res.input_tokens, res.cache_read_tokens, res.output_tokens, res.reasoning_tokens),
                         (900, 600, 60, 40))
        self.state.usage = {"prompt_cache_hit_tokens": 700, "prompt_cache_miss_tokens": 200}   # DeepSeek's names
        self.assertEqual(b.complete("S", "U", SCHEMA).cache_read_tokens, 700)
        self.state.usage = {}
        res = b.complete("S", "U", SCHEMA)
        self.assertEqual((res.cache_read_tokens, res.reasoning_tokens), (0, 0))

    def test_openai_compat_refusal(self):
        os.environ["KARAMANIYA_TEST_KEY"] = "sk-test"
        self.state.refuse = True
        b = make_backend({"provider": "deepseek", "model": "deepseek-test", "base_url": self.url,
                          "api_key_env": "KARAMANIYA_TEST_KEY", "retries": 0})
        res = b.complete("S", "U", SCHEMA)
        self.assertTrue(res.refusal)
        self.assertEqual(self.state.requests[-1][2]["response_format"]["type"], "json_object")

    def test_missing_key_is_a_clear_error(self):
        os.environ.pop("KARAMANIYA_MISSING_KEY", None)
        with self.assertRaises(ValueError):
            make_backend({"provider": "openai", "model": "x", "api_key_env": "KARAMANIYA_MISSING_KEY"})

    def test_ollama_native(self):
        b = make_backend({"provider": "ollama", "model": "qwen-test", "base_url": self.url, "retries": 0})
        res = b.complete("S", "U", SCHEMA)
        self.assertEqual(res.data, {"ok": True, "note": "ready"})
        body = self.state.requests[-1][2]
        self.assertEqual(body["format"], SCHEMA)
        self.assertFalse(body["stream"])
        self.assertIn("num_ctx", body["options"])

    def test_ollama_thinks_by_phase(self):
        b = make_backend({"provider": "ollama", "model": "qwen-test", "base_url": self.url, "retries": 0,
                          "effort_by_phase": {"decision": "high", "session": "off"}})
        b.complete("S", "U", SCHEMA, {"phase": "decision"})
        self.assertIs(self.state.requests[-1][2]["think"], True)
        b.complete("S", "U", SCHEMA, {"phase": "session"})
        self.assertIs(self.state.requests[-1][2]["think"], False)
        b.complete("S", "U", SCHEMA, {"phase": "survey"})
        self.assertNotIn("think", self.state.requests[-1][2])      # not in the table: the model's default

    def test_unreachable_server_gives_up_cleanly(self):
        b = make_backend({"provider": "ollama", "model": "x", "base_url": "http://127.0.0.1:9", "retries": 0,
                          "timeout": 2})
        res = b.complete("S", "U", SCHEMA)
        self.assertIsNone(res.data)
        self.assertIn("cannot reach Ollama", res.error)


if __name__ == "__main__":
    unittest.main()
