"""The latitude arm: a run in which the delegates are told outright that tone and radicalism are not policed.

It is a separate experimental arm (run setting `latitude = "permitted"`). The default arm is not touched:
a config that does not name it normalizes as before and its prompts carry no such paragraph.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import prompts  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")
SEATS = [{"provider": "scripted", "label": "a"}]


class TheSetting(unittest.TestCase):
    def test_a_config_that_does_not_name_it_normalizes_as_before(self):
        self.assertNotIn("latitude", normalize_config({"seat": SEATS})["run"])
        self.assertNotIn("latitude", normalize_config({"run": {"latitude": "default"}, "seat": SEATS})["run"])

    def test_permitted_is_kept_and_anything_else_refused(self):
        run = normalize_config({"run": {"latitude": "permitted"}, "seat": SEATS})["run"]
        self.assertEqual(run["latitude"], "permitted")
        with self.assertRaises(ValueError):
            normalize_config({"run": {"latitude": "unhinged"}, "seat": SEATS})

    def test_the_paragraph_closes_the_permitted_system_prompt_only(self):
        default = prompts.system_prompt("simulation", charter_election_month=35, personal_mandates=True)
        permitted = prompts.system_prompt("simulation", charter_election_month=35, personal_mandates=True,
                                          latitude="permitted")
        self.assertNotIn("LATITUDE", default)
        self.assertEqual(permitted, default + "\n\n" + prompts.LATITUDE_TEXT)
        self.assertIn("This is permission, not a request", permitted)
        # It never says "simulation", so it fits the immersive and unobserved framings too.
        self.assertNotIn("simulat", prompts.LATITUDE_TEXT.lower())


class ARunInThePermittedArm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-latitude-")
        cfg = load_config(CONFIG)
        permitted = {**cfg, "run": {**cfg["run"], "latitude": "permitted", "survey": False}}
        default = {**cfg, "run": {**cfg["run"], "survey": False}}
        cls.permitted = new_run(permitted, runs_dir=cls.tmp, name="permitted", months=1, quiet=True)
        cls.default = new_run(default, runs_dir=cls.tmp, name="default", months=1, quiet=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def read(self, run, name):
        with open(os.path.join(run, name), encoding="utf-8") as f:
            return f.read()

    def test_the_delegates_are_told_and_the_run_records_it(self):
        self.assertTrue(self.read(self.permitted, "system_prompt.txt").endswith(prompts.LATITUDE_TEXT))
        self.assertNotIn("LATITUDE", self.read(self.default, "system_prompt.txt"))
        manifest = json.loads(self.read(self.permitted, "manifest.json"))
        self.assertIn('"latitude": "permitted"', json.dumps(manifest))
        self.assertNotIn('"latitude"', self.read(self.default, "manifest.json"))
        self.assertEqual(json.loads(self.read(self.permitted, "config.json"))["run"]["latitude"], "permitted")

    def test_the_two_arms_differ_only_by_the_paragraph(self):
        self.assertEqual(self.read(self.permitted, "system_prompt.txt"),
                         self.read(self.default, "system_prompt.txt") + "\n\n" + prompts.LATITUDE_TEXT)


if __name__ == "__main__":
    unittest.main()
