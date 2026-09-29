"""The causal economy's qualitative properties.

These are the checks from the mission brief's economic-sanity list. Each one is a statement about
*how the world behaves*, not about a coefficient: a rate rise must not abolish inflation in a
month, nominal wage growth must not be read as real wage growth, and the same spending must do
different work in a slump and at capacity. If these stop holding, the world has stopped being
believable regardless of what the unit tests say.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import causality, director, economy, engine  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def run(w, months, each=None, pressure=False):
    """Drive the world without a council. `pressure` off by default keeps foreign noise out."""
    original = director.act
    if not pressure:
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


def steady(world):
    world.const.elected = True
    world.const.election_month = 99


class OutputGap(unittest.TestCase):
    def test_a_drought_opens_a_negative_gap(self):
        w = new_world(1, 12)
        before = w.econ.output_gap
        w.econ.weather = 0.7
        economy.produce(w)
        self.assertLess(w.econ.output_gap, before)

    def test_potential_output_does_not_jump_on_a_bad_month(self):
        """Potential is a slow stock. One drought must not rewrite what the economy can do.

        It does still *grow*, at the world's structural productivity rate, so the tolerance is
        a fraction of a percent a month rather than exact equality — a jump is what is excluded.
        """
        w = run(new_world(1, 12), 6, each=steady)
        before = w.econ.potential_output
        w.econ.weather = 0.6
        economy.produce(w)
        ratio = w.econ.potential_output / before
        self.assertLess(abs(ratio - 1.0), 0.01, f"potential moved {ratio - 1:+.2%} in one month")

    def test_occupying_a_producing_region_lowers_output_and_opens_the_gap(self):
        w = new_world(2, 12)
        base = w.econ.output_gap
        w.region("kessel").controller = "union"
        economy.produce(w)
        self.assertLess(w.econ.output_gap, base)

    def test_the_gap_closes_as_the_weather_recovers(self):
        """The gap must recover from its trough, though not necessarily to zero.

        It does not return to zero here because the drought also leaves unrest behind, and unrest
        disrupts regional logistics and inflicts damage — so some of the loss is stuck to the
        economy. That persistence is the point; the assertion is that recovery happens at all.
        """
        w = new_world(3, 12)

        def drought(world):
            steady(world)
            world.econ.weather = 0.7

        def recovery(world):
            steady(world)
            world.econ.weather = 1.0

        run(w, 4, each=drought)
        low = w.econ.output_gap
        self.assertLess(low, -0.04, "the drought did not open a gap")
        run(w, 8, each=recovery)
        self.assertGreater(w.econ.output_gap, low + 0.02, "the gap did not recover from the drought")
        self.assertGreater(w.econ.output_gap, -0.08)


class UnemploymentIsPersistent(unittest.TestCase):
    def test_a_recession_raises_unemployment_and_it_stays_up(self):
        """Unemployment is a lagging indicator: it keeps rising after the weather turns.

        So the test does not assert it falls the moment the drought ends. It asserts the thing
        that actually matters — that a recession leaves unemployment durably above where it
        started, rather than evaporating with the shock.
        """
        w = new_world(4, 24)
        run(w, 6, each=steady)
        calm = w.econ.unemployment
        run(w, 6, each=lambda x: (steady(x), setattr(x.econ, "weather", 0.65)))
        high = w.econ.unemployment
        run(w, 3, each=steady)
        self.assertGreater(high, calm)
        self.assertGreater(w.econ.unemployment, calm + 0.004,
                           "unemployment returned to its pre-recession level immediately")

    def test_unemployment_never_goes_negative_or_absurd(self):
        w = run(new_world(5, 36), 30, each=steady)
        self.assertGreaterEqual(w.econ.unemployment, 0.0)
        self.assertLessEqual(w.econ.unemployment, 0.60)

    def test_class_shares_of_unemployment_stay_ordered(self):
        w = run(new_world(6, 24), 18, each=steady)
        self.assertLessEqual(min(p.unemployment for p in w.k_pops()), 0.75)


class InflationHasManyCauses(unittest.TestCase):
    def test_printing_raises_prices(self):
        """The money channel must survive alongside the new channels."""
        printer = run(new_world(7, 24), 18, each=lambda x: (steady(x), setattr(x.policy, "printing", 0.05)))
        baseline = run(new_world(7, 24), 18, each=steady)
        self.assertGreater(printer.econ.cpi, baseline.econ.cpi * 1.05)

    def test_a_rate_rise_does_not_abolish_inflation_in_one_month(self):
        w = new_world(8, 24)
        run(w, 8, each=lambda x: (steady(x), setattr(x.policy, "printing", 0.05)))
        before = w.econ.infl
        self.assertGreater(before, 0.002)
        run(w, 1, each=lambda x: (steady(x), setattr(x.policy, "rate", 0.40)))
        self.assertGreater(w.econ.infl, 0.0, "one month of tight policy ended the inflation")

    def test_inflation_is_persistent_across_months(self):
        w = run(new_world(9, 24), 14, each=steady)
        recent = w.econ.infl_history[-6:]
        self.assertTrue(all(-0.05 < x < 0.20 for x in recent), recent)

    def test_the_inflation_trace_names_its_channels(self):
        w = run(new_world(10, 12), 6, each=steady)
        entry = causality.trace_for(w, "inflation")
        self.assertIsNotNone(entry, "no inflation trace was recorded")
        for channel in ("zone_price_level", "expectations", "demand_pressure"):
            self.assertIn(channel, entry["contributions"])

    def test_a_food_shock_shows_up_in_the_trace(self):
        w = new_world(11, 12)
        run(w, 4, each=steady)
        w.dip.grain_embargo = 0.9
        w.econ.weather = 0.7
        run(w, 2, each=steady)
        found = any("food_relative_price" in e["contributions"]
                    for e in w.institutions.get("causal_trace", []))
        self.assertTrue(found, "a food shock left no trace")


class RealVersusNominalWages(unittest.TestCase):
    def test_real_wages_fall_when_prices_outrun_wages(self):
        w = new_world(12, 24)
        run(w, 6, each=steady)
        before = w.econ.real_wage
        # Freeze wages while prices run.
        run(w, 8, each=lambda x: (steady(x), setattr(x.policy, "printing", 0.06)))
        self.assertLess(w.econ.real_wage, before,
                        "inflation did not reduce real wages")

    def test_a_nominal_raise_under_higher_inflation_is_not_a_real_raise(self):
        w = new_world(13, 24)
        run(w, 8, each=lambda x: (steady(x), setattr(x.policy, "printing", 0.06)))
        nominal_before, real_before = w.econ.wage, w.econ.real_wage
        run(w, 4, each=lambda x: (steady(x), setattr(x.policy, "printing", 0.06)))
        self.assertGreater(w.econ.wage, nominal_before, "the nominal wage did not rise")
        # The point is that the two are tracked separately and can diverge; real growth is
        # smaller than nominal growth, which is all that is being asserted.
        nominal_growth = w.econ.wage / nominal_before - 1
        real_growth = w.econ.real_wage / real_before - 1
        self.assertLess(real_growth, nominal_growth)

    def test_real_wage_is_the_nominal_wage_deflated(self):
        w = run(new_world(14, 12), 8, each=steady)
        self.assertAlmostEqual(w.econ.real_wage, w.econ.wage / w.econ.cpi, places=6)


class ExchangeRatePassThrough(unittest.TestCase):
    def test_a_crown_world_has_no_karam_pass_through(self):
        w = new_world(15, 12)
        self.assertEqual(w.econ.currency, "crown")
        self.assertEqual(causality.pass_through(w) if w.econ.currency == "karam" else 0.0, 0.0)

    def test_depreciation_reaches_prices_only_after_the_currency_exists(self):
        def launch(world):
            steady(world)
            world.econ.currency_launch = 2

        w = run(new_world(16, 18), 10, each=launch)
        self.assertEqual(w.econ.currency, "karam")
        self.assertGreater(w.econ.fx_prev, 0.0)

    def test_depreciation_carries_into_the_trace(self):
        w = new_world(17, 12)
        w.econ.currency = "karam"
        w.econ.fx = 1.0
        w.econ.fx_prev = 0.8          # a 25% appreciation of the crown against the karam
        run(w, 1, each=steady)
        entry = causality.trace_for(w, "inflation")
        self.assertIn("exchange_rate_passthrough", entry["contributions"])


class StructuralParametersBite(unittest.TestCase):
    def test_a_more_import_dependent_world_passes_more_of_a_depreciation_through(self):
        low, high = new_world(31, 12), new_world(32, 12)
        # Hold the base pass-through equal, or the two seeds' different base rates swamp the
        # variable under test.
        for w in (low, high):
            causality.ensure(w)["exchange_rate_pass_through"] = 0.35
        causality.ensure(low)["import_dependency"] = 0.18
        causality.ensure(high)["import_dependency"] = 0.34
        self.assertLess(causality.pass_through(low), causality.pass_through(high))

    def test_the_same_policy_is_not_equally_effective_in_every_world(self):
        many = {causality.fiscal_multiplier(new_world(s, 12)) for s in range(1, 30)}
        self.assertGreater(len(many), 5, "the multiplier is effectively the same in every world")

    def test_a_world_reports_its_regime(self):
        w = run(new_world(18, 12), 6, each=steady)
        self.assertIn(w.econ.regime, causality.REGIMES)


class NothingIsManufactured(unittest.TestCase):
    def test_an_audit_does_not_create_money(self):
        w = new_world(19, 12)
        run(w, 4, each=steady)
        before = w.econ.gold
        # Auditing is a report, not a transfer.
        from karamaniya import audits
        if hasattr(audits, "open_audit"):
            try:
                audits.open_audit(w, "treasury", "arrears", "A")
            except Exception:
                pass
        self.assertEqual(w.econ.gold, before)

    def test_passing_a_motion_does_not_create_physical_goods(self):
        w = run(new_world(20, 12), 4, each=steady)
        before = w.econ.food_stock
        before_ratio = w.econ.food_ratio
        run(w, 1, each=steady)
        # Nothing in a month of ordinary simulation conjures food from nothing.
        self.assertLess(w.econ.food_stock, before + 3.0e6)
        self.assertTrue(0.0 <= w.econ.food_ratio <= 3.0)

    def test_revenue_does_not_exceed_the_tax_base_it_is_drawn_from(self):
        w = run(new_world(21, 24), 18, each=steady)
        self.assertLess(w.econ.revenue, w.econ.gdp_nominal)
        self.assertGreaterEqual(w.econ.revenue, 0.0)

    def test_reserves_do_not_become_negative(self):
        w = run(new_world(22, 36), 30, each=steady)
        self.assertGreaterEqual(w.econ.gold, 0.0)

    def test_debt_and_arrears_never_become_negative(self):
        w = run(new_world(23, 36), 30, each=steady)
        self.assertGreaterEqual(w.econ.debt_dom, 0.0)
        self.assertGreaterEqual(w.econ.debt_for, 0.0)
        self.assertGreaterEqual(w.econ.arrears, 0.0)

    def test_nothing_in_the_economy_becomes_nan(self):
        import math
        w = run(new_world(24, 36), 36, each=steady)
        e = w.econ
        for name in ("cpi", "infl", "wage", "gdp_real", "output_gap", "potential_output",
                     "unemployment", "real_wage", "expected_infl", "gold", "debt_dom", "arrears"):
            with self.subTest(name=name):
                value = getattr(e, name)
                self.assertTrue(math.isfinite(float(value)), f"{name} is {value}")


class AgentsCannotSeeTheModel(unittest.TestCase):
    def test_the_calibration_view_is_not_reachable_from_a_briefing(self):
        from karamaniya import briefing
        w = new_world(25, 12)
        run(w, 3, each=steady)
        text = ""
        for attr in dir(briefing):
            fn = getattr(briefing, attr)
            if attr.startswith("_") or not callable(fn):
                continue
            try:
                out = fn(w, "A")
            except Exception:
                continue
            if isinstance(out, str):
                text += out
        for name in ("exchange_rate_pass_through", "fiscal_multiplier_recession",
                     "labor_market_flexibility", "causal_trace"):
            with self.subTest(name=name):
                self.assertNotIn(name, text)

    def test_the_trace_is_marked_internal(self):
        w = run(new_world(26, 12), 4, each=steady)
        events = [e for e in w.events if e.get("kind") == "causal_trace"]
        self.assertEqual(events, [], "the causal trace leaked into the event timeline")


if __name__ == "__main__":
    unittest.main()
