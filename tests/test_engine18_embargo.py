"""World engine 18: an embargo's cost follows the embargo's level, not the months a cabinet asked to move it.

The calibration harness (tools/calibrate.py, engine 18) found Dorsania's output falling in a straight line, to 0.892
of its start in 36 months, on every seed and every council. The stand-in Dorsania asked to ease its grain embargo in
every month, the embargo stood at zero and could not ease, and foreign.resolve_union charged the exporter's cost
(EMBARGO_COST times the change asked for) all the same, for good: 12 charges and 4.9% of its output in the first year.
Veleria's coal embargo was charged the same way at its ceiling, and never gave the trade back when eased.
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import calibration, foreign  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def world(seed: int = 5):
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    return w


def union_month(w, coal=0.0, grain=0.0):
    positions = foreign.positions(w)
    positions["veleria"].update(coal_embargo=coal)
    positions["dorsania"].update(grain_embargo=grain, union="support")
    foreign.resolve_union(w, positions, {})


class TheLevelNotTheAsking(unittest.TestCase):
    def test_easing_a_grain_embargo_that_stands_at_zero_costs_nothing(self):
        w = world()
        w.dip.grain_embargo = 0.0
        output = w.rivals["dorsania"].gdp_real
        for _ in range(12):
            union_month(w, grain=-.05)
        self.assertEqual(w.dip.grain_embargo, 0.0)
        self.assertEqual(w.rivals["dorsania"].gdp_real, output)
        self.assertFalse([m for m in w.dip.inbox if "restoring some grain trade" in m["text"]])

    def test_a_coal_embargo_at_its_ceiling_costs_nothing_more(self):
        w = world()
        w.dip.coal_embargo = 1.0
        output = w.rivals["veleria"].gdp_real
        union_month(w, coal=.2)
        self.assertEqual(w.dip.coal_embargo, 1.0)
        self.assertEqual(w.rivals["veleria"].gdp_real, output)

    def test_easing_gives_back_what_tightening_took(self):
        w = world()
        w.dip.grain_embargo = 0.0
        output = w.rivals["dorsania"].gdp_real
        union_month(w, grain=.3)
        tightened = w.dip.grain_embargo
        self.assertGreater(tightened, 0)
        self.assertAlmostEqual(w.rivals["dorsania"].gdp_real / output, 1 - foreign.EMBARGO_COST["dorsania"] * tightened,
                               places=9)
        union_month(w, grain=-1.0)                     # eased all the way back
        self.assertEqual(w.dip.grain_embargo, 0.0)
        self.assertAlmostEqual(w.rivals["dorsania"].gdp_real / output, 1.0, places=9)
        self.assertTrue([m for m in w.dip.inbox if "restoring some grain trade" in m["text"]])

    def test_a_passive_year_no_longer_shrinks_dorsania(self):
        # The harness's finding, on the run it was found in: seed 1, the council that does nothing, twelve months.
        # Engine 17 left Dorsania at 0.964 of its start; its trend alone (director: +0.1% a month) gives about 1.012.
        tmp = tempfile.mkdtemp(prefix="karamaniya-e18-embargo-")
        try:
            settings = calibration.scripted_settings(os.path.join(ROOT, "council.scripted.toml"))
            w, _ = calibration.simulate(settings, 1, "passive", 12, tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        ratio = w.rivals["dorsania"].gdp_real / w.rivals["dorsania"].gdp_real0
        self.assertGreater(ratio, .99, ratio)


if __name__ == "__main__":
    unittest.main()
