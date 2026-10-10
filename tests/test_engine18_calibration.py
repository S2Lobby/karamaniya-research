"""World engine 18: are the world's dynamics in plausible ranges? (calibration.py, tools/calibrate.py)

The engine watch flags a broken month inside one run, but a bias every run shares only shows across runs: every
seed's inflation creeping up, or the neighbours' output shrinking with no war. This file holds the CI-sized grid
(two seeds, twelve months, the passive and the scripted council: every check inside its range in every run), and each
check on a synthetic history, a passing and a failing case each. The engine-15 fall is reproduced on a real world: a
neighbour's output 4% lower each month for nine months fails rival_output_drift, and the same fall in a run with a war
does not, because a war moves a neighbour's output for reasons the ranges do not describe.

If the grid fails a check, do not widen the range to make it pass. That is a finding to investigate first
(docs/CALIBRATION.md).
"""
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import calibration  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

COUNCIL = os.path.join(ROOT, "council.scripted.toml")
SEEDS = (1, 2)
MODES = ("passive", "scripted")
MONTHS = 12
CHECKS = calibration.CHECKS


class TheCiGrid(unittest.TestCase):
    """Two seeds and two councils, twelve months each, played once for the whole class."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-calibration-")
        settings = calibration.scripted_settings(COUNCIL)
        cls.results = {}
        for seed in SEEDS:
            for mode in MODES:
                world, _ = calibration.simulate(settings, seed, mode, MONTHS, cls.tmp)
                cls.results[(seed, mode)] = calibration.evaluate(world)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_check_is_inside_its_range_in_every_run(self):
        for (seed, mode), results in self.results.items():
            self.assertEqual(set(results), set(CHECKS))
            for name, result in results.items():
                if not result["applies"]:
                    continue
                with self.subTest(seed=seed, mode=mode, check=name):
                    self.assertTrue(result["ok"], f"{name} is {result['value']!r}, outside "
                                                  f"[{result['low']}, {result['high']}]")

    def test_every_check_applies_to_at_least_one_run(self):
        for name in CHECKS:
            with self.subTest(check=name):
                applied = [key for key, results in self.results.items() if results[name]["applies"]]
                self.assertTrue(applied, f"{name} applied to no run, so the grid cannot judge it")

    def test_the_emigration_bound_is_pro_rata_to_the_run_length(self):
        low, high = CHECKS["emigration_share"].bounds(12)
        self.assertIsNone(low)
        self.assertAlmostEqual(high, .05)
        self.assertAlmostEqual(CHECKS["emigration_share"].bounds(36)[1], .15)


def row(month: int = 0, **values) -> dict:
    """One month of history with every field the checks read, at plausible values; keyword arguments override them."""
    base = {"month": month, "infl_yoy": .05, "zone_price": 1.0, "war": False, "currency": "crown",
            "policy": {"printing": 0.0},
            "nations": {"karamaniya": {}, "veleria": {"monthly_printing": 0.0}, "dorsania": {"monthly_printing": 0.0}},
            "unemployment": .08, "approval": .40, "gdp_idx": .95, "food_ratio": 1.0,
            "population_all": 4.7e6, "counters": {"emigrated": 0.0}, "army": 28000.0}
    base.update(values)
    return base


def months_of(n: int, **values) -> list:
    return [row(month=m, **values) for m in range(n)]


def world_stub(war: bool = False, rivals: dict | None = None):
    """Only what the checks read of a world: whether there was a war, and the neighbours."""
    return SimpleNamespace(dip=SimpleNamespace(war=war), rivals=rivals or {})


def result(name: str, rows: list, world=None) -> dict:
    return CHECKS[name].run(rows, world if world is not None else world_stub())


class TheChecksOnSyntheticHistories(unittest.TestCase):
    def test_inflation_mean_passes_at_eight_percent_and_fails_at_fifty_five_or_minus_five(self):
        self.assertTrue(result("inflation_mean", months_of(12, infl_yoy=.08))["ok"])
        self.assertFalse(result("inflation_mean", months_of(12, infl_yoy=.55))["ok"])
        self.assertFalse(result("inflation_mean", months_of(12, infl_yoy=-.05))["ok"])

    def test_inflation_monthly_peak_fails_an_eight_percent_jump_in_a_month_with_no_war_or_printing(self):
        rows = months_of(4)
        rows[2]["zone_price"] = 1.08
        r = result("inflation_monthly_peak", rows)
        self.assertTrue(r["applies"])
        self.assertAlmostEqual(r["value"], .08, places=9)
        self.assertFalse(r["ok"])

    def test_inflation_monthly_peak_passes_a_small_rise_and_leaves_out_war_and_printing_months(self):
        small = months_of(4)
        small[2]["zone_price"] = 1.02
        self.assertTrue(result("inflation_monthly_peak", small)["ok"])
        at_war = months_of(4)
        at_war[2].update(zone_price=1.08, war=True)
        self.assertTrue(result("inflation_monthly_peak", at_war)["ok"])
        karamaniya_printed = months_of(4)
        karamaniya_printed[2].update(zone_price=1.08, policy={"printing": 0.02})
        self.assertTrue(result("inflation_monthly_peak", karamaniya_printed)["ok"])
        neighbour_printed = months_of(4)
        neighbour_printed[2].update(zone_price=1.08)
        neighbour_printed[2]["nations"]["veleria"]["monthly_printing"] = 0.01
        self.assertTrue(result("inflation_monthly_peak", neighbour_printed)["ok"])

    def test_a_neighbours_printing_does_not_excuse_a_rise_once_karamaniya_has_its_own_currency(self):
        rows = months_of(4)
        rows[2].update(zone_price=1.08, currency="karam")
        rows[2]["nations"]["veleria"]["monthly_printing"] = 0.01
        self.assertFalse(result("inflation_monthly_peak", rows)["ok"])

    def test_unemployment_mean_passes_at_eight_percent_and_fails_at_thirty_five_or_one(self):
        self.assertTrue(result("unemployment_mean", months_of(12, unemployment=.08))["ok"])
        self.assertFalse(result("unemployment_mean", months_of(12, unemployment=.35))["ok"])
        self.assertFalse(result("unemployment_mean", months_of(12, unemployment=.01))["ok"])

    def test_approval_final_passes_at_forty_percent_and_fails_at_nine_or_ninety(self):
        self.assertTrue(result("approval_final", months_of(12, approval=.40))["ok"])
        self.assertFalse(result("approval_final", months_of(12, approval=.90))["ok"])
        self.assertFalse(result("approval_final", months_of(12, approval=.05))["ok"])

    def test_output_final_passes_at_ninety_percent_and_fails_at_forty_or_one_and_six_tenths(self):
        self.assertTrue(result("output_final", months_of(12, gdp_idx=.90))["ok"])
        self.assertFalse(result("output_final", months_of(12, gdp_idx=.40))["ok"])
        self.assertFalse(result("output_final", months_of(12, gdp_idx=1.6))["ok"])

    def test_food_ratio_mean_passes_at_full_supply_and_fails_below_seventy_percent(self):
        self.assertTrue(result("food_ratio_mean", months_of(12, food_ratio=1.0))["ok"])
        self.assertFalse(result("food_ratio_mean", months_of(12, food_ratio=.69))["ok"])

    def test_emigration_share_is_judged_against_fifteen_percent_over_thirty_six_months(self):
        rows = months_of(36)
        rows[-1]["counters"]["emigrated"] = 3e5             # 6.4% of 4.7 million
        self.assertTrue(result("emigration_share", rows)["ok"])
        rows[-1]["counters"]["emigrated"] = 8e5             # 17%
        self.assertFalse(result("emigration_share", rows)["ok"])

    def test_emigration_share_scales_its_bound_for_a_shorter_run(self):
        rows = months_of(12)
        rows[-1]["counters"]["emigrated"] = 1.2e5           # 2.6%: inside the 5% bound for twelve months
        self.assertTrue(result("emigration_share", rows)["ok"])
        rows[-1]["counters"]["emigrated"] = 3e5             # 6.4%: outside it, though inside 15%
        self.assertFalse(result("emigration_share", rows)["ok"])

    def test_army_size_bounds_fail_at_any_month_outside_five_thousand_to_two_hundred_thousand(self):
        self.assertTrue(result("army_size_bounds", months_of(12, army=28000.0))["ok"])
        rows = months_of(12, army=28000.0)
        rows[5]["army"] = 4000.0
        r = result("army_size_bounds", rows)
        self.assertFalse(r["ok"])
        self.assertEqual(r["value"], 4000.0)                # the month that breaks the bound is the figure
        self.assertFalse(result("army_size_bounds", months_of(12, army=250000.0))["ok"])


class TheEngine15Fall(unittest.TestCase):
    """The bug the calibration is for, on a real world: the neighbours' output fell 30% in nine months with no war."""

    def test_a_four_percent_monthly_fall_for_nine_months_fails_rival_output_drift(self):
        world = new_world(1, 36)
        veleria = world.rivals["veleria"]
        rows = []
        for month in range(9):
            veleria.gdp_real *= .96
            rows.append(row(month=month))
        r = CHECKS["rival_output_drift"].run(rows, world)
        self.assertTrue(r["applies"])
        self.assertAlmostEqual(r["value"], .96 ** 9, places=9)
        self.assertFalse(r["ok"], f"a {r['value']:.3f} neighbour passed a {r['low']} to {r['high']} range")

    def test_the_same_fall_in_a_run_with_a_war_is_not_judged(self):
        world = new_world(1, 36)
        world.dip.war = True
        world.rivals["veleria"].gdp_real *= .96 ** 9
        self.assertFalse(CHECKS["rival_output_drift"].run(months_of(9), world)["applies"])

    def test_a_slower_fall_inside_the_range_passes(self):
        world = new_world(1, 36)
        world.rivals["veleria"].gdp_real *= .995 ** 9        # about 4.4% over nine months
        r = CHECKS["rival_output_drift"].run(months_of(9), world)
        self.assertTrue(r["applies"])
        self.assertTrue(r["ok"])

    def test_a_war_in_any_month_counts_as_a_war_for_the_whole_run(self):
        world = new_world(1, 36)
        world.rivals["veleria"].gdp_real *= .96 ** 9
        rows = months_of(9)
        rows[3]["war"] = True
        self.assertFalse(CHECKS["rival_output_drift"].run(rows, world)["applies"])


class TheWholeWorldAndItsInputs(unittest.TestCase):
    def test_a_world_with_no_months_cannot_be_checked(self):
        with self.assertRaises(ValueError):
            calibration.evaluate(SimpleNamespace(history=[], dip=SimpleNamespace(war=False), rivals={}))

    def test_an_unknown_council_mode_is_refused_before_anything_runs(self):
        with self.assertRaises(ValueError):
            calibration.simulate(calibration.scripted_settings(COUNCIL), 1, "madeup", 1, tempfile.gettempdir())


if __name__ == "__main__":
    unittest.main()
