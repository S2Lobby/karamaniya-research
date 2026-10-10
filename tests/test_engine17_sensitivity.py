"""World engine 17: does the engine respond to what a council does? (baseline.py, backends/scripted.py)

Three councils of stand-ins on the same seed, six months each: the council that does nothing (passive), five seats
of the hawk and five seats of the dove. Each council's formation must give it a whole government, and the two
councils of one persona must end differently: the hawk raises the military budget in Month 3 and the dove never
does, and the hawk's budget shows in its approval. Six months keep the test to a few seconds.

The army is the figure the hawk's budget was for, and it does not move in six months: the hawk's army orders call
for recruitment only once a deadline, a formed Union or a war comes, and none of those reaches a stand-in
baseline. So the hawk is held to the army or to its military budget, whichever the engine shows.
"""
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import baseline  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import OFFICES  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")
MONTHS = 6


def run_settings() -> dict:
    """The run settings of council.scripted.toml, as the baselines keep them (test_engine16.scripted_cfg)."""
    cfg = load_config(CONFIG)
    raw = {"run": {**cfg["run"], "survey": False, "baseline": False}, "seat": cfg["seats"]}
    return normalize_config(raw, "test")["run"]


class ScriptedCouncils(unittest.TestCase):
    """The three councils, run once for the whole module."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-sensitivity-")
        cls.worlds, cls.seconds = {}, {}
        settings = run_settings()
        for mode in ("passive", "hawk", "dove"):
            cfg = normalize_config(baseline._config(settings, 5, mode, MONTHS), f"baseline:{mode}")
            started = time.time()
            path = new_run(cfg, runs_dir=cls.tmp, name=mode, quiet=True, check=False)
            cls.seconds[mode] = time.time() - started
            cls.worlds[mode], _, _ = RunStore(path).load_checkpoint()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def figures(self, mode: str) -> dict:
        w = self.worlds[mode]
        last = w.history[-1]
        return {"months": len(w.history), "approval": float(last["approval"]), "army": float(last["army"]),
                "military": float((last.get("policy") or {}).get("military", 0.0))}

    def describe(self, mode: str) -> str:
        f = self.figures(mode)
        return (f"{mode}: approval {f['approval']:.3f}, army {f['army']:,.0f}, "
                f"military budget {f['military']:.3f}")

    def test_each_council_plays_its_six_months_under_a_whole_government(self):
        for mode in ("passive", "hawk", "dove"):
            with self.subTest(mode=mode):
                self.assertEqual(self.figures(mode)["months"], MONTHS, self.describe(mode))
                formed = self.worlds[mode].founding["formation"]["offices"]
                empty = [office for office in OFFICES if not formed.get(office)]
                self.assertEqual(empty, [], f"{mode}: formation left {empty} empty")

    def test_the_hawk_council_out_arms_the_passive_one_in_army_or_in_budget(self):
        hawk, passive = self.figures("hawk"), self.figures("passive")
        self.assertTrue(hawk["army"] >= passive["army"] + 1000 or hawk["military"] > passive["military"],
                        f"the hawk council did not out-arm the passive one: army {hawk['army']:,.0f} against "
                        f"{passive['army']:,.0f} (needs +1,000), military budget {hawk['military']:.3f} against "
                        f"{passive['military']:.3f} (needs higher). {self.describe('hawk')}; {self.describe('passive')}")

    def test_the_dove_and_the_hawk_councils_end_differently(self):
        dove, hawk = self.figures("dove"), self.figures("hawk")
        differs = (abs(dove["approval"] - hawk["approval"]) >= .005
                   or abs(dove["army"] - hawk["army"]) >= 1000
                   or abs(dove["military"] - hawk["military"]) >= .002)
        self.assertTrue(differs,
                        "the dove and hawk councils ended alike: approval differs by "
                        f"{abs(dove['approval'] - hawk['approval']):.3f} (needs .005), army by "
                        f"{abs(dove['army'] - hawk['army']):,.0f} (needs 1,000), military budget by "
                        f"{abs(dove['military'] - hawk['military']):.3f} (needs .002). "
                        f"{self.describe('dove')}; {self.describe('hawk')}")

    def test_the_dove_never_raises_the_military_budget_or_the_army(self):
        w = self.worlds["dove"]
        budgets = {round(float((h.get("policy") or {}).get("military", 0.0)), 4) for h in w.history}
        armies = [float(h["army"]) for h in w.history]
        self.assertEqual(len(budgets), 1, f"the dove council changed the military budget: {sorted(budgets)}")
        self.assertLessEqual(max(armies), armies[0], f"the dove council's army rose: {armies[0]:,.0f} to {max(armies):,.0f}")


if __name__ == "__main__":
    unittest.main()
