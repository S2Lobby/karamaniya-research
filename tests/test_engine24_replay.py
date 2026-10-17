"""Seeded replay (engine 24, brief S8): a run's own recorded answers, fed back through the engine, reproduce it.

The replay backend answers each call with the raw text the run logged for that call. A call is keyed by
(month, phase, member) and then by how many times that key was asked before: a repair is a second call in the
same phase, and a format retry is one call (base.complete keeps one record for it). The order of the lines in
log.jsonl does not matter, because the calls of a phase are logged in the order their threads finish.

The tests check that a scripted run replays identically, that the order of its records does not matter, that a
changed or missing answer is found in the month it belongs to, and that the replay's keys and connector traits
work as documented.
"""
import importlib.util
import json
import os
import random
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya.backends import make_backend  # noqa: E402
from karamaniya.backends.replay import ReplayBackend, ReplayMissing  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")
_spec = importlib.util.spec_from_file_location("replay_run", os.path.join(ROOT, "tools", "replay_run.py"))
replay_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(replay_run)


def read_log(run_dir):
    with open(os.path.join(run_dir, "log.jsonl"), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_log(run_dir, records):
    with open(os.path.join(run_dir, "log.jsonl"), "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def copy_run(src, tmp, name):
    dst = os.path.join(tmp, name)
    shutil.copytree(src, dst)
    return dst


def change_a_statement(records, month):
    """Change one public opening statement made in `month`, the way a different answer would. Statements reach the
    month record, unlike a decision's notes, and a decision has no votes in a month with no motions."""
    for r in records:
        if r.get("type") != "call" or r.get("month") != month or r.get("phase") != "session":
            continue
        data = json.loads(r["raw"])
        if isinstance(data.get("statement"), str) and data["statement"]:
            data["statement"] = data["statement"] + " (a different answer)"
            r["raw"] = json.dumps(data, ensure_ascii=False)
            return r
    raise AssertionError(f"no recorded opening statement in Month {month + 1}")


class _World:
    def __init__(self, month):
        self.month = month


class TheStandInsLogTheirAnswers(unittest.TestCase):
    """The scripted stand-ins write the answer they gave as `raw`, so the log holds what a replay needs."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-replay-")
        cls.original = new_run(CONFIG, runs_dir=cls.tmp, name="orig", months=3, quiet=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_call_logs_the_answer_it_gave(self):
        calls = [r for r in read_log(self.original) if r["type"] in ("call", "foreign_call")]
        self.assertTrue(calls)
        for r in calls:
            self.assertNotEqual(r["raw"], "(scripted)", r.get("phase"))
            self.assertIsInstance(json.loads(r["raw"]), dict, r.get("phase"))


class AScriptedRunReplaysIdentically(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-replay-")
        cls.original = new_run(CONFIG, runs_dir=cls.tmp, name="orig", months=3, quiet=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_replay_reproduces_every_month_and_the_checkpoint(self):
        result = replay_run.replay(self.original)
        self.assertTrue(result["identical"], result["message"])
        self.assertEqual(result["replayed_months"], 3)
        self.assertTrue(result["checkpoint_compared"])

    def test_the_replay_sends_the_runs_own_prompts(self):
        # The same engine and the same answers: every prompt of the run is sent again, byte for byte.
        result = replay_run.replay(self.original)
        self.assertGreater(result["prompts"]["total"], 0)
        self.assertEqual(result["prompts"]["differ"], 0, result["prompts"]["message"])

    def test_the_order_of_the_recorded_lines_does_not_matter(self):
        # Shuffle the call records among the positions they hold, keeping the order of the calls of each
        # (month, phase, member): a repair's first call still comes before its repair. Month and other records
        # keep their places, since the month records are read in file order.
        copy = copy_run(self.original, self.tmp, "shuffled")
        records = read_log(copy)
        positions = [i for i, r in enumerate(records) if r["type"] in ("call", "foreign_call")]
        queues = {}
        for i in positions:
            r = records[i]
            key = (r["month"], r.get("phase") or "foreign", r.get("member") or r.get("actor"))
            queues.setdefault(key, []).append(r)
        rng = random.Random(24)
        order = []
        while queues:
            key = rng.choice(list(queues))
            order.append(queues[key].pop(0))
            if not queues[key]:
                del queues[key]
        for i, r in zip(positions, order):
            records[i] = r
        write_log(copy, records)
        result = replay_run.replay(copy)
        self.assertTrue(result["identical"], result["message"])

    def test_months_limits_the_replay_and_skips_the_checkpoint(self):
        result = replay_run.replay(self.original, months=2)
        self.assertTrue(result["identical"], result["message"])
        self.assertEqual(result["replayed_months"], 2)
        self.assertFalse(result["checkpoint_compared"])


class AChangedAnswerIsFoundInItsMonth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-replay-")
        cls.original = new_run(CONFIG, runs_dir=cls.tmp, name="orig", months=3, quiet=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_different_statement_in_month_two_diverges_in_month_two(self):
        copy = copy_run(self.original, self.tmp, "changed")
        records = read_log(copy)
        change_a_statement(records, month=1)    # the second month, month index 1
        write_log(copy, records)
        result = replay_run.replay(copy)
        self.assertFalse(result["identical"])
        self.assertEqual(result["divergence"]["where"], "month", result["message"])
        self.assertEqual(result["divergence"]["month"], 1, result["message"])
        self.assertIn("Month 2", result["message"])

    def test_a_missing_answer_is_found_in_its_month(self):
        copy = copy_run(self.original, self.tmp, "missing")
        records = read_log(copy)
        # Drop the one decision of a member in the second month: the replay asks for it and finds nothing.
        drop = next(i for i, r in enumerate(records)
                    if r["type"] == "call" and r["month"] == 1 and r["phase"] == "decision")
        records.pop(drop)
        write_log(copy, records)
        result = replay_run.replay(copy)
        self.assertFalse(result["identical"])
        self.assertEqual(result["divergence"]["where"], "replay", result["message"])
        self.assertEqual(result["divergence"]["month"], 1, result["message"])
        self.assertIn("no recorded answer", result["message"])


class ARunWithStandInAnswersIsRefused(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-replay-")
        cls.original = new_run(CONFIG, runs_dir=cls.tmp, name="orig", months=2, quiet=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_answers_logged_as_a_placeholder_cannot_be_replayed(self):
        copy = copy_run(self.original, self.tmp, "placeholder")
        records = read_log(copy)
        for r in records:
            if r["type"] in ("call", "foreign_call"):
                r["raw"] = "(scripted)"          # what the engine logged before this change
        write_log(copy, records)
        result = replay_run.replay(copy)
        self.assertFalse(result["identical"])
        self.assertEqual(result["divergence"]["where"], "recording", result["message"])
        self.assertIn("(scripted)", result["message"])


class TheBackendKeysAnswersByOccurrence(unittest.TestCase):
    """A synthetic log: two answers for one key (a repair), one foreign answer, and a format retry."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-replay-unit-")
        self.log = os.path.join(self.tmp, "log.jsonl")
        records = [
            {"type": "call", "month": 0, "phase": "decision", "member": "A", "raw": '{"n": 1}', "served_model": "m1",
             "cost_usd": 0.5, "attempts": 1, "format_retry": False},
            {"type": "call", "month": 0, "phase": "decision", "member": "A", "raw": '{"n": 2}', "served_model": "m1",
             "repair": "vote_intent", "attempts": 1, "format_retry": False},
            {"type": "call", "month": 0, "phase": "decision", "member": "B", "raw": '{"n": 3}', "served_model": "m1",
             "attempts": 2, "format_retry": True},
            {"type": "foreign_call", "month": 0, "actor": "veleria", "raw": '{"n": 4}', "served_model": "f1"},
        ]
        with open(self.log, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def backend(self, **extra):
        return ReplayBackend({"provider": "replay", "replay_log": self.log, "replay_of": "openrouter", **extra})

    def test_the_second_call_of_a_key_gets_the_second_answer(self):
        b = self.backend()
        ctx = {"world": _World(0), "member": "A", "phase": "decision"}
        first = b.complete("s", "u", {}, dict(ctx))
        second = b.complete("s", "u", {}, dict(ctx))
        self.assertEqual(first.data, {"n": 1})
        self.assertEqual(first.cost_usd, 0.5)
        self.assertEqual(second.data, {"n": 2})

    def test_a_third_call_of_the_key_is_missing_and_says_so(self):
        b = self.backend()
        ctx = {"world": _World(0), "member": "A", "phase": "decision"}
        b.complete("s", "u", {}, dict(ctx))
        b.complete("s", "u", {}, dict(ctx))
        with self.assertRaises(ReplayMissing) as caught:
            b.complete("s", "u", {}, dict(ctx))
        self.assertEqual((caught.exception.month, caught.exception.phase, caught.exception.member),
                         (0, "decision", "A"))
        self.assertEqual(caught.exception.attempt, 3)

    def test_a_format_retry_is_one_answer_with_its_flag(self):
        b = self.backend()
        res = b.complete("s", "u", {}, {"world": _World(0), "member": "B", "phase": "decision"})
        self.assertEqual(res.data, {"n": 3})
        self.assertTrue(res.format_retry)
        self.assertEqual(res.attempts, 2)

    def test_a_foreign_cabinet_is_keyed_by_its_actor(self):
        b = self.backend()
        res = b.complete("s", "u", {}, {"world": _World(0), "actor": "veleria", "phase": "foreign"})
        self.assertEqual(res.data, {"n": 4})
        with self.assertRaises(ReplayMissing):
            b.complete("s", "u", {}, {"world": _World(0), "actor": "dorsania", "phase": "foreign"})

    def test_the_answer_is_read_the_way_its_connector_read_it(self):
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "call", "month": 1, "phase": "decision", "member": "C",
                                "raw": '{"x": "a", "y": null}'}) + "\n")
        schema = {"type": "object", "properties": {"x": {"type": "string"}, "y": {"type": ["string", "null"]}},
                  "required": ["x"]}
        ctx = {"world": _World(1), "member": "C", "phase": "decision"}
        codex = self.backend(replay_of="codex_cli").complete("s", "u", schema, dict(ctx))
        other = self.backend(replay_of="anthropic").complete("s", "u", schema, dict(ctx))
        self.assertEqual(codex.data, {"x": "a"})       # codex drops an optional null (codex_cli.drop_optional_nulls)
        self.assertEqual(other.data, {"x": "a", "y": None})


class TheReplayTraitsMatchTheConnectors(unittest.TestCase):
    """The prompts depend on these traits, so the replay must report the connector's own values."""

    def test_schema_and_temperature_traits_match_the_real_classes(self):
        from karamaniya.backends.anthropic_api import AnthropicBackend
        from karamaniya.backends.claude_cli import ClaudeCLIBackend
        from karamaniya.backends.codex_cli import CodexCLIBackend
        from karamaniya.backends.ollama import OllamaBackend
        from karamaniya.backends.openai_compat import OpenAICompatBackend
        # Class attributes of the connectors.
        for provider, cls in [("anthropic", AnthropicBackend), ("claude_cli", ClaudeCLIBackend),
                              ("codex_cli", CodexCLIBackend), ("ollama", OllamaBackend)]:
            replay = ReplayBackend({"provider": "replay", "replay_log": "unused.jsonl", "replay_of": provider})
            self.assertEqual(replay.enforces_schema, cls.enforces_schema, provider)
            self.assertEqual(replay.supports_temperature, cls.supports_temperature, provider)
        # The OpenAI-compatible family: enforces_schema is a property of the seat's json_mode, so compare
        # with a connector built without a key (api_key_env = "" needs no environment variable).
        for provider, extra in [("openrouter", {}), ("openai", {}), ("deepseek", {}), ("lmstudio", {}),
                                ("llamacpp", {}), ("openai_compat", {}), ("openrouter", {"json_mode": "json_object"})]:
            seat = {"provider": provider, "model": "m", "api_key_env": "", "base_url": "http://127.0.0.1:9", **extra}
            real = OpenAICompatBackend(seat)
            replay = ReplayBackend({"provider": "replay", "replay_log": "unused.jsonl", "replay_of": provider,
                                    **extra})
            self.assertEqual(replay.enforces_schema, real.enforces_schema, (provider, extra))
            self.assertEqual(replay.supports_temperature, real.supports_temperature, provider)

    def test_the_ollama_prompt_budget_is_the_connectors(self):
        from karamaniya.backends.ollama import OllamaBackend
        cfg = {"model": "qwen", "num_ctx": 8192}
        for extra in ({}, {"max_prompt_chars": 5000}):
            real = OllamaBackend({**cfg, **extra})
            replay = ReplayBackend({"provider": "replay", "replay_log": "unused.jsonl", "replay_of": "ollama",
                                    **cfg, **extra})
            self.assertEqual(replay.prompt_budget(1234), real.prompt_budget(1234))

    def test_make_backend_builds_a_replay(self):
        backend = make_backend({"provider": "replay", "replay_log": "unused.jsonl", "replay_of": "scripted"})
        self.assertIsInstance(backend, ReplayBackend)


if __name__ == "__main__":
    unittest.main()
