"""World engine 17: four same-seed councils and the report's baseline section (baseline.py, report_template.html).

The rule-following, passive, all-hawk and all-dove councils are all run beside a finished run. The two councils
of one persona give every seat its own office at formation (SAME_PERSONA_OFFICES), so a whole government is
formed in each; the first two councils are unchanged. The report shows all four, and a one-line headline near
the top of the page, built from the same figures.
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import baseline  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.world import OFFICES  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")


def scripted(**run):
    cfg = load_config(CONFIG)
    return normalize_config({"run": {**cfg["run"], "survey": False, "baseline": False, **run},
                             "seat": cfg["seats"]}, "test")


class CouncilsOfOnePersona(unittest.TestCase):
    def test_there_are_four_same_seed_councils(self):
        self.assertEqual(baseline.MODES, ("scripted", "passive", "hawk", "dove"))

    def test_seats_of_one_persona_are_each_given_an_office_and_between_them_every_office(self):
        run = scripted()["run"]
        for mode in ("hawk", "dove"):
            with self.subTest(mode=mode):
                seats = baseline._config(run, 5, mode, 3)["seats"]
                self.assertEqual([s["persona"] for s in seats], [mode] * 5)
                self.assertEqual(sorted(s["formation_office"] for s in seats), sorted(OFFICES))
                normalized = normalize_config(baseline._config(run, 5, mode, 3), f"baseline:{mode}")
                self.assertEqual(sorted(s["formation_office"] for s in normalized["seats"]), sorted(OFFICES))

    def test_the_rule_following_and_passive_councils_are_as_they_were(self):
        run = scripted()["run"]
        mixed = baseline._config(run, 5, "scripted", 3)["seats"]
        self.assertEqual([s["persona"] for s in mixed], ["democrat", "technocrat", "hawk", "loyalist", "opportunist"])
        self.assertTrue(all("formation_office" not in s for s in mixed))
        passive = baseline._config(run, 5, "passive", 3)["seats"]
        self.assertEqual({s["persona"] for s in passive}, {"passive"})
        self.assertTrue(all("formation_office" not in s for s in passive))


class BaselinesBesideAFinishedRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-engine17-baseline-")
        cls.finished = new_run(scripted(baseline=True, months=3), runs_dir=cls.tmp, name="based", months=3,
                               quiet=True, check=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_all_four_councils_are_run_beside_the_finished_run(self):
        data = baseline.read(self.finished)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(set(data["modes"]), set(baseline.MODES))
        for mode in ("hawk", "dove"):
            with self.subTest(mode=mode):
                self.assertEqual(data["modes"][mode]["summary"]["months"], 3)
                self.assertEqual(data["modes"][mode]["personas"], [mode] * 5)
        self.assertEqual(set(baseline.deltas(data)), set(baseline.MODES))

    def test_the_report_names_the_four_councils_and_carries_the_headline(self):
        html = (self.finished / "report.html").read_text(encoding="utf-8")
        self.assertIn('"dove":{"summary":', html)
        self.assertIn('"hawk":{"summary":', html)
        self.assertIn("All-hawk rule council", html)
        self.assertIn("All-dove rule council", html)
        self.assertIn("Against the same seed", html)
        self.assertIn("baseline-headline", html)


if __name__ == "__main__":
    unittest.main()
