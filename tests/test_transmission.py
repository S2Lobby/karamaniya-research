"""Monetary and price transmission: rate -> credit -> demand, and money/fx -> prices.

The point of these channels is that they take time. A rate rise that withdraws credit in the same
month it is announced is not a transmission channel, it is a slider. Each test here pins the lag or
the direction, not a coefficient.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import causality as cz, director, economy, engine  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def run(w, months, each=None):
    original = director.act
    director.act = lambda world, *_a, **_k: setattr(world.dip, "inbox", [])
    try:
        for _ in range(months):
            if w.ended():
                break
            engine.begin_month(w)
            if each:
                each(w)
            engine.step(w)
    finally:
        director.act = original
    return w


def steady(w):
    w.const.elected = True
    w.const.election_month = 99


class CreditLagsTheRate(unittest.TestCase):
    def _hike(self, seed=5, rate=0.25, months=14, start=2, depth=None):
        w = new_world(seed, 30)
        if depth is not None:
            cz.ensure(w)["financial_depth"] = depth

        def each(x):
            steady(x)
            if x.month >= start:
                x.policy.rate = rate
        return run(w, months, each=each)

    def test_credit_does_not_reach_its_new_target_in_one_month(self):
        """The target moves at once; the quantity of credit covers less than half the distance."""
        w = new_world(5, 30)
        cz.ensure(w)["financial_depth"] = 0.6
        before = w.econ.credit_conditions
        w.policy.rate = 0.30
        economy.produce(w)
        self.assertLess(w.econ.credit_target, before, "the target did not move at all")
        covered = (before - w.econ.credit_conditions) / (before - w.econ.credit_target)
        self.assertLess(covered, 0.5,
                        f"credit covered {covered:.0%} of the distance in one month")

    def test_credit_converges_toward_its_target_over_several_months(self):
        w = self._hike()
        self.assertLess(w.econ.credit_conditions, 0.99)
        # Converged close to the target: no overshoot and no long-run gap.
        self.assertAlmostEqual(w.econ.credit_conditions, w.econ.credit_target, delta=0.01)

    def test_credit_trends_down_while_the_rate_is_held_high(self):
        """Not strictly monotone, and it should not be: the target itself drifts as expected
        inflation moves, so credit can tick up a little. What must hold is the trend."""
        w = new_world(5, 30)
        seen = []

        def each(x):
            steady(x)
            if x.month >= 2:
                x.policy.rate = 0.25
            seen.append(x.econ.credit_conditions)
        run(w, 14, each=each)
        tail = seen[4:]
        self.assertLess(tail[-1], tail[0], "credit did not fall while the rate was held high")
        for a, b in zip(tail, tail[1:]):
            with self.subTest(a=a, b=b):
                self.assertLess(b, a + 0.01, "credit rebounded sharply under a held-high rate")

    def test_credit_never_exceeds_its_ceiling(self):
        """Regression: scaling the credit LEVEL by financial depth let utilisation exceed the
        ceiling the rest of the model assumes, and a drought produced a POSITIVE output gap."""
        for depth in (0.25, 0.45, 0.70):
            for seed in (1, 5, 9):
                w = new_world(seed, 12)
                cz.ensure(w)["financial_depth"] = depth
                with self.subTest(depth=depth, seed=seed):
                    produced = economy.produce(w)
                    self.assertLessEqual(w.econ.credit_conditions, 1.0)
                    self.assertGreater(produced["gdp_real"], 0)

    def test_a_drought_still_opens_a_negative_gap_under_every_depth(self):
        for depth in (0.25, 0.45, 0.70):
            w = new_world(1, 12)
            cz.ensure(w)["financial_depth"] = depth
            w.econ.weather = 0.7
            economy.produce(w)
            with self.subTest(depth=depth):
                self.assertLess(w.econ.output_gap, -0.01,
                                "a drought did not open a negative gap")

    def test_a_deeper_financial_system_transmits_the_rate_more_strongly(self):
        shallow = new_world(5, 12)
        deep = new_world(5, 12)
        cz.ensure(shallow)["financial_depth"] = 0.25
        cz.ensure(deep)["financial_depth"] = 0.70
        # A deeper system transmits the same rate more strongly, so credit falls further.
        self.assertLess(cz.rate_target(deep, 0.20), cz.rate_target(shallow, 0.20))

    def test_a_low_rate_does_not_tighten_credit(self):
        w = new_world(5, 12)
        self.assertEqual(cz.rate_target(w, 0.0), 1.0)
        self.assertEqual(cz.rate_target(w, 0.03), 1.0)


class DemandPressureIsPersistent(unittest.TestCase):
    def test_pressure_builds_up_rather_than_appearing_at_once(self):
        w = new_world(6, 12)
        first = cz.demand_step(w, -0.08)
        self.assertGreater(first, -0.08, "pressure jumped straight to the gap")
        for _ in range(20):
            last = cz.demand_step(w, -0.08)
        self.assertLess(last, -0.06, "pressure never converged on a sustained gap")

    def test_pressure_decays_when_the_gap_closes(self):
        w = new_world(6, 12)
        for _ in range(20):
            cz.demand_step(w, -0.08)
        deep = w.econ.demand_pressure
        for _ in range(20):
            cz.demand_step(w, 0.0)
        self.assertGreater(w.econ.demand_pressure, deep)
        self.assertAlmostEqual(w.econ.demand_pressure, 0.0, places=3)

    def test_a_one_month_blip_barely_moves_pressure(self):
        w = new_world(6, 12)
        one_off = cz.demand_step(w, -0.10)
        self.assertGreater(one_off, -0.05, "a single bad month moved pressure most of the way")

    def test_pressure_is_bounded(self):
        w = new_world(6, 12)
        for _ in range(50):
            cz.demand_step(w, -5.0)
        self.assertGreaterEqual(w.econ.demand_pressure, -0.25)
        for _ in range(50):
            cz.demand_step(w, 5.0)
        self.assertLessEqual(w.econ.demand_pressure, 0.25)


class MoneyPressure(unittest.TestCase):
    def test_money_growth_beyond_output_is_excess(self):
        w = new_world(7, 12)
        w.econ.expected_infl = 0.003
        pressure = cz.money_step(w, money_growth=0.05, output_growth=0.002)
        self.assertGreater(pressure, 0.0)

    def test_money_growth_matched_by_output_is_not_excess(self):
        w = new_world(7, 12)
        w.econ.expected_infl = 0.0
        pressure = cz.money_step(w, money_growth=0.002, output_growth=0.002)
        self.assertAlmostEqual(pressure, 0.0, places=6)

    def test_money_growth_matched_by_inflation_is_accommodating_not_excess(self):
        """Printing that merely keeps pace with expected inflation is not inflationary.

        This is what stops the model degenerating into naive quantity theory: in a world used to
        20pc inflation, 20pc money growth is standing still.
        """
        w = new_world(7, 12)
        w.econ.expected_infl = 0.20
        # Accommodating means matching expected inflation AND real output growth.
        pressure = cz.money_step(w, money_growth=0.20 + 0.002, output_growth=0.002)
        self.assertAlmostEqual(pressure, 0.0, places=6)

    def test_money_growth_beyond_expected_inflation_is_excess(self):
        w = new_world(7, 12)
        w.econ.expected_infl = 0.20
        pressure = cz.money_step(w, money_growth=0.35, output_growth=0.002)
        self.assertGreater(pressure, 0.0)

    def test_a_high_inflation_economy_absorbs_more_money_growth_without_new_pressure(self):
        """The same money growth is less of a shock where inflation is already expected.

        The Cagan effect -- that people hold less cash when inflation is high -- is deliberately
        NOT modelled here; it lives in the money-market velocity term. Including it twice would
        double-count the same behaviour.
        """
        low = new_world(7, 12)
        low.econ.expected_infl = 0.0
        high = new_world(7, 12)
        high.econ.expected_infl = 0.30
        self.assertLess(cz.money_step(high, 0.03, 0.002),
                        cz.money_step(low, 0.03, 0.002))

    def test_pressure_is_bounded(self):
        w = new_world(7, 12)
        for _ in range(60):
            cz.money_step(w, 5.0, 0.0)
        self.assertLessEqual(w.econ.money_pressure, 0.30)
        for _ in range(60):
            cz.money_step(w, -5.0, 0.0)
        self.assertGreaterEqual(w.econ.money_pressure, -0.15)


class ImportPrices(unittest.TestCase):
    def test_depreciation_raises_import_prices(self):
        """`e.fx` is CROWNS PER KARAM, so a fall is a depreciation. Getting this backwards makes
        a currency collapse cheapen imports and turn deflationary."""
        w = new_world(8, 12)
        w.econ.fx_prev = 1.0
        w.econ.fx = 1.0
        self.assertAlmostEqual(cz.import_price_step(w), 0.0, places=6)
        w.econ.fx = 0.8                       # the karam buys fewer crowns: a depreciation
        self.assertGreater(cz.import_price_step(w), 0.0)

    def test_appreciation_lowers_import_prices(self):
        w = new_world(8, 12)
        w.econ.fx_prev = 0.8
        w.econ.fx = 1.0                       # the karam buys more crowns: an appreciation
        self.assertLess(cz.import_price_step(w), 0.0)

    def test_world_prices_move_import_costs_even_without_a_currency_move(self):
        w = new_world(8, 12)
        w.econ.fx_prev = w.econ.fx = 1.0
        w.econ.world_price_infl = 0.04
        self.assertGreater(cz.import_price_step(w), 0.0)

    def test_import_price_inflation_is_bounded(self):
        w = new_world(8, 12)
        w.econ.fx_prev = 50.0                 # a catastrophic collapse
        w.econ.fx = 0.05
        self.assertLessEqual(cz.import_price_step(w), 0.40)
        w.econ.fx_prev = 0.05                 # and the reverse
        w.econ.fx = 50.0
        self.assertGreaterEqual(cz.import_price_step(w), -0.25)

    def test_a_currency_collapse_is_inflationary_not_deflationary(self):
        """The finding that prompted this: a 69pc karam depreciation was producing NEGATIVE
        import-price inflation, so a currency crisis was deflationary."""
        w = new_world(8, 12)
        w.econ.currency = "karam"
        w.econ.fx_prev = 1.0
        w.econ.fx = 0.31                      # the karam lost about 69pc of its crown value
        self.assertGreater(cz.depreciation(w), 0.5)
        self.assertGreater(cz.import_price_step(w), 0.0)


class TheChainReachesPrices(unittest.TestCase):
    def test_persistent_demand_pressure_reaches_the_inflation_trace(self):
        w = new_world(9, 12)
        for _ in range(20):
            cz.demand_step(w, -0.08)
        run(w, 2, each=steady)
        entries = [e for e in w.institutions.get("causal_trace", []) if e["variable"] == "inflation"]
        self.assertTrue(entries)
        self.assertIn("demand_pressure", entries[-1]["contributions"])

    def test_money_and_import_channels_reach_the_trace(self):
        w = new_world(10, 12)
        w.econ.currency = "karam"
        w.econ.fx_prev = 1.25
        w.econ.fx = 1.0                      # a depreciation, so import costs are non-zero
        w.econ.world_price_infl = 0.03
        w.econ.money_pressure = 0.02
        run(w, 2, each=steady)
        entry = cz.trace_for(w, "inflation")
        for channel in ("money_pressure", "import_cost", "exchange_rate_passthrough"):
            with self.subTest(channel=channel):
                self.assertIn(channel, entry["contributions"])

    def test_printing_eventually_raises_prices_through_the_pressure_channel(self):
        printer = run(new_world(11, 30), 24,
                      each=lambda x: (steady(x), setattr(x.policy, "printing", 0.05)))
        baseline = run(new_world(11, 30), 24, each=steady)
        self.assertGreater(printer.econ.cpi, baseline.econ.cpi * 1.05)

    def test_the_pressures_are_small_relative_to_the_money_channel(self):
        """They are an additional pull, not a second full Phillips curve."""
        w = new_world(12, 12)
        w.econ.demand_pressure = 0.25
        w.econ.money_pressure = 0.30
        pressures = cz.price_pressures(w)
        self.assertLess(abs(pressures["demand_pressure"]), 0.05)
        self.assertLess(abs(pressures["money_pressure"]), 0.05)


class BaselineStaysSane(unittest.TestCase):
    def test_a_calm_world_does_not_drift_into_deflation(self):
        for seed in range(1, 7):
            w = run(new_world(seed, 30), 24, each=steady)
            recent = [h["infl_yoy"] for h in w.history[12:]]
            with self.subTest(seed=seed):
                self.assertGreater(min(recent), -0.05, f"deflation: {min(recent)}")
                self.assertLess(max(recent), 0.25, f"runaway inflation: {max(recent)}")

    def test_credit_is_unchanged_when_rates_are_below_neutral(self):
        w = run(new_world(2, 18), 12, each=steady)
        self.assertAlmostEqual(w.econ.credit_conditions, 1.0, places=3)

    def test_the_transmission_stocks_survive_save_and_load(self):
        from karamaniya.world import World
        w = run(new_world(3, 18), 8, each=steady)
        again = World.from_dict(w.to_dict())
        for field in ("credit_conditions", "demand_pressure", "money_pressure",
                      "import_price_infl", "output_growth"):
            with self.subTest(field=field):
                self.assertAlmostEqual(getattr(again.econ, field), getattr(w.econ, field), places=9)


if __name__ == "__main__":
    unittest.main()
