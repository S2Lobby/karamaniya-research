"""Two runs from the same seed, with the same seats, are the same run.

The scripted stand-ins make no random choices of their own, so everything that could differ between two
such runs comes from the engine: the world, the council's own state and every prompt must repeat
exactly. (Real models are not deterministic; the manifest says so. This is the engine's half.) The
calls of a phase run in parallel threads, so the order of the lines in log.jsonl and the call ids can
differ between the two runs; what each call was sent cannot.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya.runner import new_run  # noqa: E402
from karamaniya.tokens import fingerprints  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")


class TheSameSeedGivesTheSameRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-repro-")
        cls.runs = [new_run(CONFIG, runs_dir=cls.tmp, name=name, months=4, quiet=True) for name in ("a", "b")]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def checkpoint(self, run):
        with open(os.path.join(run, "checkpoint.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_the_world_repeats_month_by_month(self):
        a, b = (self.checkpoint(run)["world"] for run in self.runs)
        self.assertEqual(len(a["history"]), 4)
        for month, (x, y) in enumerate(zip(a["history"], b["history"])):
            self.assertEqual(x, y, f"month {month} differs")
        self.assertEqual(a, b)

    def test_the_council_state_repeats(self):
        a, b = (self.checkpoint(run)["council"] for run in self.runs)
        self.assertEqual(a, b)

    def test_every_prompt_repeats(self):
        a, b = (fingerprints(run) for run in self.runs)
        self.assertTrue(a["prompts"])
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
