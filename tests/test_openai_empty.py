"""An OpenAI-style seat tells apart an empty reply (the provider failed), a reply cut off by the token
limit (a reasoning model used the budget) and a provider error inside a 200, instead of just 'failed'."""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya.backends import make_backend  # noqa: E402

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}, "note": {"type": "string"}},
          "required": ["ok", "note"], "additionalProperties": False}
GOOD = json.dumps({"ok": True, "note": "ready"})


def completion(content, tokens_out, finish="stop", **extra):
    return 200, {"id": "c", "model": "vendor/model", "provider": "Stealth", **extra,
                 "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish}],
                 "usage": {"prompt_tokens": 900, "completion_tokens": tokens_out}}


class ScriptedServer:
    """Answers the requests it gets, one queued reply each, and keeps the bodies it was sent."""

    def __init__(self, replies):
        self.replies, self.bodies = list(replies), []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                outer.bodies.append(body)
                status, payload = outer.replies.pop(0) if outer.replies else (500, {"error": "script ran out"})
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class EmptyAndCutOffReplies(unittest.TestCase):
    def setUp(self):
        self.servers = []
        patcher = mock.patch("karamaniya.backends.base.time.sleep", lambda s: None)   # no real backoff waits
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        for s in self.servers:
            s.close()

    def seat(self, replies, **extra):
        server = ScriptedServer(replies)
        self.servers.append(server)
        backend = make_backend({"provider": "openai_compat", "model": "vendor/model", "base_url": server.url,
                                "json_mode": "none", "retries": 3, **extra})
        return backend, server

    def test_a_reply_with_no_tokens_is_retried_with_backoff_not_reasked_as_a_format_problem(self):
        # Recorded shape of the failure: a reply in about a second, zero tokens, nothing in it.
        backend, server = self.seat([completion("", 0), completion("", 0), completion(GOOD, 40)])
        res = backend.complete("SYS", "USER", SCHEMA)
        self.assertEqual(res.data, {"ok": True, "note": "ready"}, res.error)
        self.assertFalse(res.format_retry)                      # it never reached the re-ask-the-format step
        self.assertEqual(len(server.bodies), 3)
        self.assertNotIn("previous answer", json.dumps(server.bodies[-1]))

    def test_a_reply_that_stays_empty_fails_with_the_reason_named(self):
        backend, _ = self.seat([completion("", 0) for _ in range(6)], retries=2)
        res = backend.complete("SYS", "USER", SCHEMA)
        self.assertIsNone(res.data)
        self.assertIn("empty completion: 0 tokens", res.error)
        self.assertIn("provider=Stealth", res.error)

    def test_a_reply_cut_off_by_the_token_limit_is_retried_once_with_a_larger_budget(self):
        cut = completion('{"ok": tru', 8000, finish="length")
        backend, server = self.seat([cut, completion(GOOD, 900)], max_tokens=8000)
        res = backend.complete("SYS", "USER", SCHEMA)
        self.assertEqual(res.data, {"ok": True, "note": "ready"}, res.error)
        self.assertEqual([b["max_tokens"] for b in server.bodies], [8000, 16000])
        self.assertEqual(res.attempts, 1)

    def test_all_thinking_and_no_answer_is_the_same_case(self):
        # The recorded failure: 8,000 tokens spent, content empty, finish_reason length.
        backend, server = self.seat([completion("", 8000, finish="length"), completion(GOOD, 700)], max_tokens=8000)
        self.assertEqual(backend.complete("SYS", "USER", SCHEMA).data, {"ok": True, "note": "ready"})
        self.assertEqual(len(server.bodies), 2)

    def test_still_cut_off_at_the_cap_is_a_clear_error_not_a_format_retry(self):
        cut = completion("", 8000, finish="length")
        backend, server = self.seat([cut, cut, cut, cut], max_tokens=8000, max_tokens_cap=16000)
        res = backend.complete("SYS", "USER", SCHEMA)
        self.assertIsNone(res.data)
        self.assertIn("cut off at 16000 tokens", res.error)
        self.assertIn("raise max_tokens", res.error)
        self.assertEqual(len(server.bodies), 2)                 # 8000, then 16000; no more spend after that
        self.assertFalse(res.format_retry)

    def test_a_provider_error_inside_a_200_is_named_and_retried_when_temporary(self):
        busy = (200, {"error": {"message": "Provider returned error", "code": 429}})
        backend, server = self.seat([busy, completion(GOOD, 40)])
        self.assertEqual(backend.complete("SYS", "USER", SCHEMA).data, {"ok": True, "note": "ready"})
        self.assertEqual(len(server.bodies), 2)
        denied = (200, {"error": {"message": "No auth credentials found", "code": 401}})
        backend, server = self.seat([denied, completion(GOOD, 40)])
        res = backend.complete("SYS", "USER", SCHEMA)
        self.assertIsNone(res.data)
        self.assertIn("provider error: No auth credentials found (code 401)", res.error)
        self.assertEqual(len(server.bodies), 1)                  # a permanent error is not retried

    def test_an_ordinary_answer_and_a_refusal_are_unchanged(self):
        backend, server = self.seat([completion(GOOD, 40)])
        res = backend.complete("SYS", "USER", SCHEMA)
        self.assertEqual((res.data, res.output_tokens, res.served_model), ({"ok": True, "note": "ready"}, 40, "vendor/model"))
        refusal = (200, {"model": "m", "choices": [{"message": {"content": None, "refusal": "No."}, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": 5, "completion_tokens": 1}})
        backend, _ = self.seat([refusal])
        self.assertTrue(backend.complete("SYS", "USER", SCHEMA).refusal)

    def test_openrouter_seats_start_with_a_budget_a_reasoning_model_can_use(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-only"}):
            seat = make_backend({"provider": "openrouter", "model": "vendor/model"})
            self.assertEqual((seat.max_tokens, seat.max_tokens_cap), (16000, 32000))
            self.assertEqual(make_backend({"provider": "openrouter", "model": "m", "max_tokens": 4000}).max_tokens, 4000)
        self.assertEqual(make_backend({"provider": "openai", "model": "m", "api_key_env": ""}).max_tokens, 8000)


if __name__ == "__main__":
    unittest.main()


class AProviderThatCannotServeTheSchemaInTheBody(unittest.TestCase):
    """OpenRouter reports an upstream failure inside a 200 reply rather than as a status code. When
    that failure names the response format, the provider cannot serve the schema at all, so the
    ordinary retry would fail identically — the mode has to step down instead.

    Recorded shape, from a real seat: "JSON error injected into SSE stream (code 502)" for a large
    nested schema, while the same seat answered a smaller schema every time."""

    def setUp(self):
        self.servers = []
        patcher = mock.patch("karamaniya.backends.base.time.sleep", lambda s: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        for s in self.servers:
            s.close()

    def seat(self, replies, **extra):
        server = ScriptedServer(replies)
        self.servers.append(server)
        backend = make_backend({"provider": "openai_compat", "model": "vendor/model",
                                "base_url": server.url, "retries": 3,
                                "json_mode": "json_schema", **extra})
        return backend, server

    def test_an_in_body_format_failure_steps_the_mode_down_instead_of_retrying_identically(self):
        backend, server = self.seat([
            (200, {"error": {"code": 502, "message": "JSON error injected into SSE stream"}}),
            completion(GOOD, 40),
        ])
        self.assertEqual(backend.json_mode, "json_schema")
        res = backend.complete("SYS", "USER", SCHEMA)
        self.assertEqual(res.data, {"ok": True, "note": "ready"}, res.error)
        self.assertEqual(backend.json_mode, "json_object",
                         "the mode did not step down, so the retry was identical")
        self.assertEqual(len(server.bodies), 2, "the failed request was not retried")

    def test_the_weaker_mode_still_asks_for_json(self):
        backend, server = self.seat([
            (200, {"error": {"code": 502, "message": "JSON error injected into SSE stream"}}),
            completion(GOOD, 40),
        ])
        backend.complete("SYS", "USER", SCHEMA)
        self.assertIn("json_object", json.dumps(server.bodies[1].get("response_format") or {}))
        self.assertNotIn("json_schema", json.dumps(server.bodies[1].get("response_format") or {}))

    def test_an_in_body_failure_that_is_not_about_the_format_is_still_a_transient_retry(self):
        backend, server = self.seat([
            (200, {"error": {"code": 503, "message": "upstream provider overloaded"}}),
            completion(GOOD, 40),
        ])
        res = backend.complete("SYS", "USER", SCHEMA)
        self.assertEqual(res.data, {"ok": True, "note": "ready"}, res.error)
        self.assertEqual(backend.json_mode, "json_schema",
                         "an unrelated outage weakened the request format for the whole seat")

    def test_a_client_error_in_the_body_is_still_fatal(self):
        backend, server = self.seat([
            (200, {"error": {"code": 404, "message": "no such model"}}),
        ])
        res = backend.complete("SYS", "USER", SCHEMA)
        self.assertIsNone(res.data)
        self.assertIn("404", res.error)
