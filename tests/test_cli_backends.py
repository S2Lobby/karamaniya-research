"""The command-line seats against stand-in programs: what they send, what they read back, and
how a used-up plan pauses the run and replays the unfinished month on resume."""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya.backends import make_backend  # noqa: E402
from karamaniya.backends.base import QuotaError  # noqa: E402
from karamaniya.backends.cli_common import classify  # noqa: E402
from karamaniya.actions import public_statement_preview  # noqa: E402
from karamaniya.config import load_config  # noqa: E402
from karamaniya.runner import new_run, resume_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = os.path.join(HERE, "tests", "fake_cli.py")
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}, "note": {"type": "string"}},
          "required": ["ok", "note"], "additionalProperties": False}
SYSTEM = "STANDING INSTRUCTIONS FOR THE TEST"
USER = 'Reply with {"ok": true, "note": "ready"}.'


def seat(kind, provider, **extra):
    return {"provider": provider, "model": extra.pop("model", "test-model"), "cli_command": [sys.executable, FAKE, kind],
            "retries": 0, "timeout": 60, **extra}


class CliSeats(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-cli-test-")
        self.record = os.path.join(self.tmp, "record.json")
        self.saved = {k: os.environ.get(k) for k in ("FAKE_CLI_RECORD", "FAKE_CLI_LIMIT_AFTER", "FAKE_CLI_COUNTER", "FAKE_CLI_STREAM",
                                                     "FAKE_CLI_USAGE", "FAKE_CLI_ANSWER", "FAKE_CLI_DETOURS",
                                                     "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "KARAMANIYA_DS_TEST")}
        os.environ["FAKE_CLI_RECORD"] = self.record
        os.environ.pop("FAKE_CLI_LIMIT_AFTER", None)
        os.environ["FAKE_CLI_COUNTER"] = os.path.join(self.tmp, "count")

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sent(self):
        with open(self.record, encoding="utf-8") as f:
            return json.load(f)

    def test_codex(self):
        res = make_backend(seat("codex", "codex_cli", effort="low")).complete(SYSTEM, USER, SCHEMA)
        self.assertEqual(res.data, {"ok": True, "note": "ready"}, res.error)
        self.assertEqual((res.input_tokens, res.output_tokens), (6717, 19))
        s = self.sent()
        argv = s["argv"]
        self.assertEqual(argv[0], "exec")
        for flag in ("--ephemeral", "--ignore-user-config", "--skip-git-repo-check", "--json"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        disabled = [argv[i + 1] for i, a in enumerate(argv) if a == "--disable"]
        self.assertIn("shell_tool", disabled)
        self.assertIn("unified_exec", disabled)
        self.assertIn("developer_instructions=" + json.dumps(SYSTEM), argv)
        self.assertEqual(s["stdin"], USER)  # the prompt goes through stdin, not the command line
        self.assertEqual(os.listdir(argv[argv.index("-C") + 1]), [])  # an empty scratch folder

    def test_cline(self):
        res = make_backend(seat("cline", "cline_cli", model="cline-pass/kimi-k3", cline_provider="cline-pass")).complete(SYSTEM, USER, SCHEMA)
        self.assertEqual(res.data, {"ok": True, "note": "ready"}, res.error)
        argv = self.sent()["argv"]
        self.assertEqual(argv[argv.index("--auto-approve") + 1], "false")
        self.assertEqual(argv[argv.index("-s") + 1], SYSTEM)
        self.assertEqual(argv[argv.index("-P") + 1], "cline-pass")
        self.assertEqual(argv[-1], USER)

    def test_antigravity(self):
        res = make_backend(seat("agy", "antigravity_cli", model="gemini-3.1-pro-high")).complete(SYSTEM, USER, SCHEMA)
        self.assertEqual(res.data, {"ok": True, "note": "ready"}, res.error)
        self.assertEqual(res.served_model, "gemini-3.1-pro-high")
        s = self.sent()
        self.assertEqual(s["argv"][s["argv"].index("--mode") + 1], "plan")
        self.assertIn("--sandbox", s["argv"])
        msg = json.loads(s["stdin"].splitlines()[0])
        self.assertEqual(msg["event"], "user")
        text = msg["message"]["content"][0]["text"]
        self.assertIn(SYSTEM, text)
        self.assertIn(USER, text)

    def test_antigravity_sends_enums_gemini_accepts_and_maps_the_answer_back(self):
        # Gemini rejected "" (an office left empty) and the forecast horizons 3, 6, 12 with
        # INVALID_ARGUMENT, so a Gemini seat could neither form a government nor decide.
        schema = {"type": "object", "additionalProperties": False, "required": ["slate", "horizon", "pick"],
                  "properties": {"slate": {"type": "object", "additionalProperties": False, "required": ["head"],
                                           "properties": {"head": {"type": "string", "enum": ["A", "B", ""]}}},
                                 "horizon": {"type": "integer", "enum": [3, 6, 12]},
                                 "pick": {"type": "string", "enum": ["A", "none"]}}}
        os.environ["FAKE_CLI_ANSWER"] = json.dumps({"slate": {"head": "none"}, "horizon": "6", "pick": "none"})
        res = make_backend(seat("agy", "antigravity_cli")).complete(SYSTEM, USER, schema)
        self.assertEqual(res.data, {"slate": {"head": ""}, "horizon": 6, "pick": "none"}, res.error)
        sent = json.loads(self.sent()["schema"])["properties"]
        self.assertEqual(sent["slate"]["properties"]["head"]["enum"], ["A", "B", "none"])
        self.assertEqual(sent["horizon"], {"type": "string", "enum": ["3", "6", "12"]})
        self.assertEqual(sent["pick"], schema["properties"]["pick"])

    def test_antigravity_answer_lost_to_a_denied_tool_call_is_asked_again(self):
        os.environ["FAKE_CLI_DETOURS"] = "1"
        with mock.patch("karamaniya.backends.base.time.sleep"):
            res = make_backend({**seat("agy", "antigravity_cli"), "retries": 2}).complete(SYSTEM, USER, SCHEMA)
        self.assertEqual(res.data, {"ok": True, "note": "ready"}, res.error)
        self.assertEqual(res.attempts, 2)
        self.assertFalse(res.format_retry)  # the same prompt again, not the "could not be read" note

    def test_claude_on_its_own_and_carrying_deepseek(self):
        os.environ["ANTHROPIC_BASE_URL"] = "https://other-provider.invalid/anthropic"
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "other-provider-token"
        res = make_backend(seat("claude", "claude_cli", model="claude-opus-5-5")).complete(SYSTEM, USER, SCHEMA)
        self.assertEqual(res.data, {"ok": True, "note": "ready"}, res.error)
        self.assertEqual(res.served_model, "claude-opus-5-5")
        env = self.sent()["env"]
        self.assertIsNone(env["ANTHROPIC_BASE_URL"])     # a shell pointed at another provider is not inherited
        self.assertIsNone(env["ANTHROPIC_AUTH_TOKEN"])
        os.environ["KARAMANIYA_DS_TEST"] = "ds-test-key"
        res = make_backend(seat("claude", "claude_cli", model="deepseek-flash", base_url="https://api.deepseek.com/anthropic",
                                api_key_env="KARAMANIYA_DS_TEST")).complete(SYSTEM, USER, SCHEMA)
        self.assertEqual(res.data, {"ok": True, "note": "ready"}, res.error)
        env = self.sent()["env"]
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://api.deepseek.com/anthropic")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "ds-test-key")
        self.assertEqual(env["ANTHROPIC_MODEL"], "deepseek-flash")
        self.assertEqual(env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "deepseek-flash")
        del os.environ["KARAMANIYA_DS_TEST"]
        with self.assertRaises(ValueError):
            make_backend(seat("claude", "claude_cli", base_url="https://api.deepseek.com/anthropic", api_key_env="KARAMANIYA_DS_TEST"))

    def test_cache_and_reasoning_counts_are_read_back(self):
        os.environ["FAKE_CLI_USAGE"] = json.dumps({"cache_read_input_tokens": 9000, "cache_creation_input_tokens": 400})
        res = make_backend(seat("claude", "claude_cli")).complete(SYSTEM, USER, SCHEMA)
        self.assertEqual((res.input_tokens, res.cache_read_tokens, res.cache_write_tokens), (9520, 9000, 400))
        # As codex-rs reports them: the cached and cache-written input are part of input_tokens, the
        # reasoning is part of output_tokens.
        os.environ["FAKE_CLI_USAGE"] = json.dumps({"cached_input_tokens": 6000, "cache_write_input_tokens": 500,
                                                   "output_tokens": 83, "reasoning_output_tokens": 64})
        res = make_backend(seat("codex", "codex_cli", price_in=1.0, price_out=10.0, price_cache_read=0.1,
                                price_cache_write=1.25)).complete(SYSTEM, USER, SCHEMA)
        self.assertEqual((res.input_tokens, res.cache_read_tokens, res.cache_write_tokens), (6717, 6000, 500))
        self.assertEqual((res.output_tokens, res.reasoning_tokens), (83, 64))     # not 83 + 64
        self.assertAlmostEqual(res.cost_usd, (217 * 1.0 + 6000 * 0.1 + 500 * 1.25 + 83 * 10.0) / 1e6)

    def test_effort_by_phase_reaches_the_command_line(self):
        table = {"decision": "high", "session": "low"}
        for kind, provider, flag in (("claude", "claude_cli", "--effort"), ("cline", "cline_cli", "--thinking")):
            b = make_backend(seat(kind, provider, effort="medium", effort_by_phase=table))
            for phase, expected in (("decision", "high"), ("session", "low"), ("survey", "medium")):
                res = b.complete(SYSTEM, USER, SCHEMA, {"phase": phase})
                self.assertEqual(res.data, {"ok": True, "note": "ready"}, res.error)
                argv = self.sent()["argv"]
                self.assertEqual(argv[argv.index(flag) + 1], expected, f"{provider}, {phase}")
        b = make_backend(seat("codex", "codex_cli", effort="medium", effort_by_phase=table))
        b.complete(SYSTEM, USER, SCHEMA, {"phase": "decision"})
        self.assertIn("model_reasoning_effort=" + json.dumps("high"), self.sent()["argv"])

    def test_usage_limits_are_recognised(self):
        os.environ["FAKE_CLI_LIMIT_AFTER"] = "0"
        for kind, provider in (("codex", "codex_cli"), ("cline", "cline_cli"), ("agy", "antigravity_cli"), ("claude", "claude_cli")):
            res = make_backend(seat(kind, provider)).complete(SYSTEM, USER, SCHEMA)
            self.assertTrue(res.quota, f"{provider}: {res.error}")
            self.assertFalse(res.format_retry, provider)
            self.assertIn("usage limit", res.error.lower(), provider)

    def test_claude_session_limit_pauses_instead_of_abstaining(self):
        message = "429: You've hit your session limit · resets 12:50am (Asia/Tashkent)"
        self.assertIsInstance(classify(message, "Claude CLI"), QuotaError)

    def test_short_cli_wait_is_transient_not_a_subscription_pause(self):
        from karamaniya.backends.base import TransientError
        self.assertIsInstance(classify("Try again in 5s; rate limit reached", "Cline CLI"), TransientError)

    def test_claude_speech_draft_arrives_before_call_finishes(self):
        os.environ["FAKE_CLI_STREAM"] = "1"
        spoken = threading.Event()
        drafts = []
        result = {}
        schema = {"type": "object", "properties": {"statement": {"type": "string"}},
                  "required": ["statement"], "additionalProperties": False}
        def progress(raw):
            drafts.append(public_statement_preview(raw))
            spoken.set()
        def call():
            result["answer"] = make_backend(seat("claude", "claude_cli")).complete(
                SYSTEM, USER, schema, {"on_progress": progress})
        worker = threading.Thread(target=call)
        worker.start()
        try:
            self.assertTrue(spoken.wait(5), "no draft appeared while the CLI was running")
            self.assertTrue(worker.is_alive(), "the draft only appeared after the final answer")
        finally:
            worker.join(10)
        self.assertEqual(result["answer"].data["statement"], "We should protect open elections.")
        self.assertIn("We should protect open elections.", drafts)
        self.assertIn("--include-partial-messages", self.sent()["argv"])

    def test_public_preview_never_includes_private_messages(self):
        raw = '{"statement":"A vote for\\npeace", "private_messages":[{"to":"B","text":"secret"}]}'
        self.assertEqual(public_statement_preview(raw), "A vote for\npeace")
        self.assertEqual(public_statement_preview('{"statement":"A vote for'), "A vote for")


class PauseAndReplay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-pause-test-")
        self.saved = {k: os.environ.get(k) for k in ("FAKE_CLI_RECORD", "FAKE_CLI_LIMIT_AFTER", "FAKE_CLI_COUNTER")}
        os.environ.pop("FAKE_CLI_RECORD", None)
        os.environ["FAKE_CLI_COUNTER"] = os.path.join(self.tmp, "count")

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_used_up_plan_pauses_and_the_month_is_replayed(self):
        cfg = load_config(os.path.join(HERE, "council.scripted.toml"))
        cfg["seats"][4] = {"label": "fake-codex", **seat("codex", "codex_cli")}
        cfg["run"].update(months=3, survey=False, shuffle_seats=False)
        # The incomplete diagnosis reply is repaired, then this seat participates through Month 1.
        # Its ninth call lands in Month 2, where the limit must roll back only that month.
        os.environ["FAKE_CLI_LIMIT_AFTER"] = "8"
        path = new_run(cfg, runs_dir=self.tmp, name="p", quiet=True, check=False)
        store = RunStore(path)
        ck = store.read_json("checkpoint.json")
        self.assertEqual(len(ck["world"]["history"]), 1)             # only Month 1 is kept
        self.assertTrue(ck["world"]["founding"]["formation"])
        self.assertTrue(ck["meta"]["stopped"].startswith("paused in Month 2"), ck["meta"]["stopped"])
        self.assertIn("fake-codex", ck["meta"]["stopped"])
        months = [r.get("month") for r in store.read_log() if r.get("type") in ("call", "month", "dm")]
        self.assertTrue(months and max(months) == 0, "records of the abandoned month were left in the log")
        # The limit resets; the run resumes and replays Month 2 from the start.
        os.environ["FAKE_CLI_LIMIT_AFTER"] = "1000"
        resume_run(path, quiet=True, check=False)
        ck = store.read_json("checkpoint.json")
        self.assertEqual(len(ck["world"]["history"]), 3)
        self.assertEqual(ck["meta"]["stopped"], "")
        month_records = [r["month"] for r in store.read_log("month")]
        self.assertEqual(month_records, [0, 1, 2])                    # each month exactly once


if __name__ == "__main__":
    unittest.main()
