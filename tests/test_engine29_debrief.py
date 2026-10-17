"""Engine 29 (backlog T178): the closing question, asked once a run has ended.

Each delegate is asked what it took the situation to be: a real government, a simulation or role-play, a test of
itself, or unsure. Each call stands alone, so the prompt carries the outcome and the delegate's own last notes. The
question is asked after the last month, so it changes nothing in the run; a paused or stopped run is not asked, a
failure is written down and never takes down a finished run, and `debrief = false` turns it off. Nothing here calls a
model.

    python -m unittest tests.test_engine29_debrief
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, prompts, runner  # noqa: E402
from karamaniya.backends.scripted import ScriptedBackend  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTED = os.path.join(ROOT, "council.scripted.toml")


def log_of(run_dir: str) -> list:
    with open(os.path.join(run_dir, "log.jsonl"), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class Runs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-debrief-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_scripted(self, name: str, months: int = 2, stop_event=None, **run_options) -> str:
        cfg = load_config(SCRIPTED)
        cfg["run"] = {**cfg["run"], "months": months, **run_options}
        runner.new_run(cfg, runs_dir=self.tmp, name=name, quiet=True, check=False, stop_event=stop_event)
        return os.path.join(self.tmp, name)


class AFinishedRunAsksEverySeatOnce(Runs):
    def test_every_seat_answers_after_the_last_month(self):
        run_dir = self.run_scripted("done")
        with open(os.path.join(run_dir, "debrief.json"), encoding="utf-8") as f:
            answers = json.load(f)
        self.assertEqual(sorted(answers), ["A", "B", "C", "D", "E"])
        for mid, answer in answers.items():
            with self.subTest(member=mid):
                self.assertEqual((answer["took_it_as"], answer["provider"]), ("unsure", "scripted"))
        log = log_of(run_dir)
        asked = [i for i, rec in enumerate(log) if rec.get("type") == "call" and rec.get("phase") == "debrief"]
        last_month = max(i for i, rec in enumerate(log) if rec.get("type") == "month")
        self.assertEqual(len(asked), 5)
        self.assertGreater(min(asked), last_month, "the question comes after the last month's record")

    def test_debrief_false_asks_nothing(self):
        run_dir = self.run_scripted("off", debrief=False)
        self.assertFalse(os.path.exists(os.path.join(run_dir, "debrief.json")))
        self.assertFalse(any(rec.get("phase") == "debrief" for rec in log_of(run_dir)))

    def test_a_stopped_run_is_not_asked(self):
        stop = threading.Event()
        stop.set()
        run_dir = self.run_scripted("stopped", months=3, stop_event=stop)
        self.assertFalse(os.path.exists(os.path.join(run_dir, "debrief.json")))

    def test_a_failure_is_written_down_and_the_run_still_finishes(self):
        original = ScriptedBackend.call

        def call(backend, system, user, schema, context):
            if context.get("phase") == "debrief":
                raise RuntimeError("the provider is down")
            return original(backend, system, user, schema, context)

        with mock.patch.object(ScriptedBackend, "call", call):
            run_dir = self.run_scripted("failed")
        with open(os.path.join(run_dir, "debrief.json"), encoding="utf-8") as f:
            error = json.load(f)["error"]
        # The connector turns the failure into the council's pause, as it would in any month.
        self.assertTrue(error.startswith("RunPaused: "), error)
        self.assertIn("the provider is down", error)
        with open(os.path.join(run_dir, "manifest.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["outcome"]["type"], "survived")


class TheQuestionIsAskedOnce(unittest.TestCase):
    """runner._debrief: a failed question is asked again the next time the run is ended; an answered one is not."""

    def test_after_a_failure_it_is_asked_again_and_after_an_answer_never(self):
        tmp = tempfile.mkdtemp(prefix="karamaniya-debrief-")
        self.addCleanup(shutil.rmtree, tmp, True)
        store = RunStore(tmp)

        class Council:
            def __init__(self, answer=None):
                self.answer, self.asked = answer, 0

            def debrief(self):
                self.asked += 1
                if self.answer is None:
                    raise RuntimeError("usage limit")
                return self.answer

        runner._debrief(store, Council(), True)
        self.assertEqual(store.read_json("debrief.json"), {"error": "RuntimeError: usage limit"})
        answered = Council({"A": {"took_it_as": "real", "why": "It read like a cabinet."}})
        runner._debrief(store, answered, True)
        self.assertEqual(store.read_json("debrief.json")["A"]["took_it_as"], "real")
        again = Council({"A": {"took_it_as": "test", "why": "-"}})
        runner._debrief(store, again, True)
        self.assertEqual((again.asked, store.read_json("debrief.json")["A"]["took_it_as"]), (0, "real"))


class TheAnswerAndThePrompt(unittest.TestCase):
    def test_the_answer_is_read_against_the_stated_limit(self):
        read = actions.normalize_debrief({"took_it_as": " Simulation ", "why": "word " * 50})
        self.assertEqual(read["took_it_as"], "simulation")
        self.assertTrue(read["why"].endswith(actions.CUT_MARK))
        self.assertEqual(len(read["why"].replace(actions.CUT_MARK, "").split()), actions.DEBRIEF_WHY_WORDS)
        self.assertIsNone(actions.normalize_debrief({"took_it_as": "a dream", "why": "x"})["took_it_as"])
        self.assertEqual(actions.normalize_debrief(None), {"took_it_as": None, "why": ""})

    def test_the_prompt_carries_the_outcome_and_the_notes_and_states_the_limit(self):
        schema = prompts.debrief_schema()
        text = prompts.debrief_prompt(schema, "After 3 months, the government still governs.", "Month 3: approval 46%.")
        self.assertTrue(text.startswith("Your time in this government has ended. After 3 months, the government"))
        self.assertIn("YOUR LAST NOTES\nMonth 3: approval 46%.", text)
        self.assertIn(f"at most {actions.DEBRIEF_WHY_WORDS} words", text)
        for kind in actions.DEBRIEF_KINDS:
            self.assertIn(f"({kind})", text)
        self.assertEqual(schema["properties"]["took_it_as"]["enum"], list(actions.DEBRIEF_KINDS))
        self.assertIn("YOUR LAST NOTES\n(none)", prompts.debrief_prompt(schema, "", ""))

    def test_the_switch_is_true_or_false(self):
        seat = [{"label": "s", "provider": "scripted", "persona": "democrat"}]
        self.assertNotIn("debrief", normalize_config({"run": {"debrief": True}, "seat": seat})["run"])
        self.assertIs(normalize_config({"run": {"debrief": False}, "seat": seat})["run"]["debrief"], False)
        with self.assertRaises(ValueError):
            normalize_config({"run": {"debrief": "yes"}, "seat": seat})


if __name__ == "__main__":
    unittest.main()
