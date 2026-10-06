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

    def setUp(self):
        self.state.requests.clear()
        self.state.reject_json_schema = False
        self.state.refuse = False

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

    def test_unreachable_server_gives_up_cleanly(self):
        b = make_backend({"provider": "ollama", "model": "x", "base_url": "http://127.0.0.1:9", "retries": 0,
                          "timeout": 2})
        res = b.complete("S", "U", SCHEMA)
        self.assertIsNone(res.data)
        self.assertIn("cannot reach Ollama", res.error)


if __name__ == "__main__":
    unittest.main()
