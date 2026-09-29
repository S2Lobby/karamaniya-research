"""The causal core: parameters are seeded and hidden, lags fire once, regimes describe not script."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import causality as cz  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


class StructuralParameters(unittest.TestCase):
    def test_the_same_seed_draws_the_same_parameters(self):
        self.assertEqual(cz.generate(11), cz.generate(11))

    def test_different_seeds_draw_different_parameters(self):
        a, b = cz.generate(1), cz.generate(2)
        self.assertNotEqual(a, b)

    def test_every_parameter_is_inside_its_calibrated_band(self):
        for seed in range(1, 40):
            world = cz.generate(seed)
            for name, (low, high, _unit, _why) in cz.STRUCTURAL_PARAMETERS.items():
                with self.subTest(seed=seed, name=name):
                    self.assertGreaterEqual(world[name], low)
                    self.assertLessEqual(world[name], high)

    def test_parameters_vary_across_worlds_rather_than_being_fixed(self):
        draws = [cz.generate(s)["exchange_rate_pass_through"] for s in range(1, 25)]
        self.assertGreater(len(set(draws)), 5, "pass-through is effectively constant across seeds")

    def test_every_parameter_carries_its_units_and_rationale(self):
        for name, (low, high, unit, why) in cz.STRUCTURAL_PARAMETERS.items():
            with self.subTest(name=name):
                self.assertLess(low, high)
                self.assertTrue(unit.strip())
                self.assertTrue(why.strip(), f"{name} has no recorded rationale")

    def test_parameters_are_stable_on_a_world_and_survive_save_load(self):
        from karamaniya.world import World
        w = new_world(5, 6)
        first = cz.ensure(w)
        self.assertEqual(cz.ensure(w), first, "parameters were regenerated mid-run")
        again = World.from_dict(w.to_dict())
        self.assertEqual(cz.ensure(again), first)


class Lags(unittest.TestCase):
    def test_an_effect_due_now_arrives_now(self):
        w = new_world(1, 6)
        cz.schedule(w, "money", 0, 0.5, source="printing")
        self.assertEqual(len(cz.due(w)), 1)

    def test_a_future_effect_does_not_arrive_early(self):
        w = new_world(1, 6)
        cz.schedule(w, "rate", 3, 0.5)
        self.assertEqual(cz.due(w), [])
        self.assertEqual(len(cz.pending(w)), 1)

    def test_an_effect_fires_exactly_once(self):
        w = new_world(1, 6)
        cz.schedule(w, "fiscal", 1, 0.5)
        w.month = 1
        self.assertEqual(len(cz.due(w)), 1)
        self.assertEqual(cz.due(w), [], "the same effect was delivered twice")
        w.month = 2
        self.assertEqual(cz.due(w), [])

    def test_every_channel_has_a_declared_lag_profile(self):
        for channel in ("rate", "money", "fx", "fiscal", "wage", "supply"):
            with self.subTest(channel=channel):
                profile = cz.CHANNEL_LAGS[channel]
                self.assertEqual(len(profile), 3)
                self.assertEqual(list(profile), sorted(profile), "lag offsets must be ordered")

    def test_the_queue_is_bounded(self):
        w = new_world(1, 6)
        for i in range(cz.MAX_PENDING + 30):
            cz.schedule(w, "fiscal", 1, 0.01, note=str(i))
        self.assertLessEqual(len(cz.pending(w)), cz.MAX_PENDING)

    def test_pending_effects_survive_save_load(self):
        from karamaniya.world import World
        w = new_world(1, 6)
        cz.schedule(w, "fx", 4, 0.2, source="depreciation")
        again = World.from_dict(w.to_dict())
        self.assertEqual(len(cz.pending(again)), 1)
        again.month = 4
        self.assertEqual(len(cz.due(again)), 1)


class Regimes(unittest.TestCase):
    def test_a_calm_world_is_normal(self):
        w = new_world(1, 6)
        self.assertEqual(cz.regime(w), cz.NORMAL)

    def test_a_food_shortfall_is_a_supply_crisis_before_it_is_an_inflation(self):
        w = new_world(1, 6)
        w.econ.food_ratio = 0.6
        w.econ.infl = 0.20          # even with high inflation, supply is named first
        self.assertEqual(cz.regime(w), cz.SUPPLY_CRISIS)

    def test_high_inflation_is_recognised(self):
        w = new_world(1, 6)
        w.econ.infl = 0.06          # about 100% a year
        self.assertEqual(cz.regime(w), cz.HIGH_INFLATION)

    def test_a_recession_is_recognised_from_the_output_gap(self):
        w = new_world(1, 6)
        w.econ.output_gap = -0.08
        self.assertEqual(cz.regime(w), cz.RECESSION)

    def test_a_small_negative_gap_is_a_slowdown_not_a_recession(self):
        w = new_world(1, 6)
        w.econ.output_gap = -0.02
        self.assertEqual(cz.regime(w), cz.SLOWDOWN)

    def test_a_fiscal_crisis_needs_both_low_confidence_and_unpaid_bills(self):
        w = new_world(1, 6)
        w.econ.confidence = 0.2
        w.econ.arrears = 0.0
        self.assertNotEqual(cz.regime(w), cz.FISCAL_CRISIS)
        w.econ.arrears = 0.3 * max(1.0, w.econ.gdp_nominal or 1.0)
        self.assertEqual(cz.regime(w), cz.FISCAL_CRISIS)

    def test_every_regime_label_is_declared(self):
        w = new_world(1, 6)
        self.assertIn(cz.regime(w), cz.REGIMES)


class Expectations(unittest.TestCase):
    def test_expectations_are_anchored_when_credibility_is_high(self):
        w = new_world(1, 6)
        w.econ.printed = 0.0
        w.econ.gold = w.econ.gold0
        anchored = cz.expected_inflation(w)
        self.assertGreater(cz.credit_anchor(w), 0.5)
        self.assertLess(anchored, 0.02)

    def test_adaptive_experience_pulls_expectations_up(self):
        w = new_world(1, 6)
        w.zone_of("karamaniya").infl = 0.05
        high = cz.expected_inflation(w)
        w.zone_of("karamaniya").infl = 0.001
        low = cz.expected_inflation(w)
        self.assertGreater(high, low)

    def test_money_financing_erodes_the_anchor(self):
        w = new_world(1, 6)
        before = cz.credit_anchor(w)
        w.econ.printed = 0.4 * max(1.0, w.econ.spending)
        self.assertLess(cz.credit_anchor(w), before)

    def test_expectations_are_bounded(self):
        w = new_world(1, 6)
        w.zone_of("karamaniya").infl = 5.0
        w.econ.gold = 0.0
        self.assertLessEqual(cz.expected_inflation(w), 1.5)
        self.assertGreaterEqual(cz.expected_inflation(w), -0.02)


class Multiplier(unittest.TestCase):
    def test_the_multiplier_is_larger_in_slack_than_at_capacity(self):
        slack = new_world(1, 6)
        slack.econ.output_gap = -0.08
        hot = new_world(1, 6)
        hot.econ.output_gap = 0.04
        self.assertGreater(cz.fiscal_multiplier(slack), cz.fiscal_multiplier(hot))

    def test_the_multiplier_stays_positive_and_bounded(self):
        for gap in (-0.30, -0.10, 0.0, 0.05, 0.30):
            w = new_world(1, 6)
            w.econ.output_gap = gap
            with self.subTest(gap=gap):
                self.assertGreater(cz.fiscal_multiplier(w), 0.0)
                self.assertLess(cz.fiscal_multiplier(w), 3.0)

    def test_the_multiplier_is_read_from_the_world_not_a_constant(self):
        values = set()
        for seed in range(1, 15):
            w = new_world(seed, 6)
            values.add(cz.fiscal_multiplier(w))
        self.assertGreater(len(values), 4, "the multiplier does not depend on the world")


class Okun(unittest.TestCase):
    def test_a_negative_output_gap_raises_unemployment(self):
        w = new_world(1, 6)
        w.econ.unemployment = 0.06
        worse = cz.okun_step(w, current_gap=-0.05)
        self.assertGreater(worse, 0.06)

    def test_a_positive_output_gap_lowers_unemployment(self):
        w = new_world(1, 6)
        w.econ.unemployment = 0.10
        better = cz.okun_step(w, current_gap=0.04)
        self.assertLess(better, 0.10)

    def test_a_depressed_gap_keeps_unemployment_high_rather_than_drifting_it_down(self):
        """The level anchor: a gap that stays negative must not leave unemployment falling."""
        w = new_world(1, 6)
        w.econ.unemployment = 0.06
        for _ in range(24):
            w.econ.unemployment = cz.okun_step(w, previous_gap=-0.06, current_gap=-0.06)
        self.assertGreater(w.econ.unemployment, 0.08,
                           "a permanently depressed economy drifted to low unemployment")

    def test_at_a_zero_gap_unemployment_settles_at_the_natural_rate(self):
        w = new_world(1, 6)
        w.econ.unemployment = 0.20
        for _ in range(60):
            w.econ.unemployment = cz.okun_step(w, current_gap=0.0)
        self.assertAlmostEqual(w.econ.unemployment, cz.NATURAL_UNEMPLOYMENT, places=2)

    def test_unemployment_is_persistent_rather_than_snapping(self):
        w = new_world(1, 6)
        w.econ.unemployment = 0.20
        after = cz.okun_step(w, current_gap=0.0)
        self.assertGreater(after, 0.17, "unemployment snapped back to natural in one month")

    def test_a_rigid_labour_market_persists_longer_than_a_flexible_one(self):
        rigid, flexible = new_world(1, 6), new_world(2, 6)
        for w in (rigid, flexible):
            w.econ.unemployment = 0.20
        cz.ensure(rigid)["labor_market_flexibility"] = 0.25
        cz.ensure(flexible)["labor_market_flexibility"] = 0.75
        self.assertGreater(cz.okun_step(rigid, current_gap=0.0),
                           cz.okun_step(flexible, current_gap=0.0))

    def test_unemployment_stays_inside_plausible_bounds(self):
        for gap in (-1.0, -0.2, 0.0, 0.2, 1.0):
            w = new_world(1, 6)
            w.econ.unemployment = 0.30
            with self.subTest(gap=gap):
                u = cz.okun_step(w, previous_gap=0.0, current_gap=gap)
                self.assertGreaterEqual(u, 0.005)
                self.assertLessEqual(u, 0.60)


class ExchangeRate(unittest.TestCase):
    def test_depreciation_pressure_has_named_terms(self):
        w = new_world(1, 6)
        pressure = cz.depreciation_pressure(w)
        for term in ("inflation_differential", "fiscal_risk", "reserve_pressure",
                     "political_risk", "expected_money_creation", "interest_rate_support"):
            self.assertIn(term, pressure["terms"])
        self.assertAlmostEqual(pressure["total"], sum(pressure["terms"].values()), places=4)

    def test_running_down_reserves_raises_pressure(self):
        w = new_world(1, 6)
        w.currency_launch = 0
        before = cz.depreciation_pressure(w)["terms"]["reserve_pressure"]
        w.econ.gold = w.econ.gold0 * 0.1
        after = cz.depreciation_pressure(w)["terms"]["reserve_pressure"]
        self.assertGreater(after, before)

    def test_high_interest_rates_support_the_currency(self):
        w = new_world(1, 6)
        w.policy.rate = 0.02
        low = cz.depreciation_pressure(w)["terms"]["interest_rate_support"]
        w.policy.rate = 0.30
        high = cz.depreciation_pressure(w)["terms"]["interest_rate_support"]
        self.assertLess(high, low)

    def test_a_crown_world_does_not_move_its_own_exchange_rate(self):
        w = new_world(1, 6)
        self.assertEqual(w.econ.currency, "crown")
        self.assertEqual(cz.fx_step(w), 0.0)

    def test_a_karam_world_moves_and_stays_bounded(self):
        for seed in range(1, 20):
            w = new_world(seed, 6)
            w.econ.currency = "karam"
            w.econ.fx = 1.0
            change = cz.fx_step(w)
            with self.subTest(seed=seed):
                self.assertGreaterEqual(change, -0.10)
                self.assertLessEqual(change, 0.18)
                self.assertGreater(w.econ.fx, 0.0)

    def test_pass_through_is_higher_when_the_economy_depends_on_imports(self):
        shallow = new_world(1, 6)
        deep = new_world(2, 6)
        cz.ensure(shallow)["import_dependency"] = 0.18
        cz.ensure(deep)["import_dependency"] = 0.34
        self.assertLess(cz.pass_through(shallow), cz.pass_through(deep))

    def test_pass_through_is_suppressed_under_price_controls(self):
        w = new_world(1, 6)
        free = cz.pass_through(w)
        w.policy.price_controls = "all"
        self.assertLess(cz.pass_through(w), free)


class TraceAndCalibration(unittest.TestCase):
    def test_a_trace_records_named_contributors(self):
        w = new_world(1, 6)
        cz.trace(w, "inflation", 0.021, {"expectations": 0.008, "fx_pass_through": 0.006,
                                         "food_shock": 0.005, "demand": 0.004, "credit_tightening": -0.002})
        entry = cz.trace_for(w, "inflation")
        self.assertEqual(entry["total"], 0.021)
        self.assertIn("fx_pass_through", entry["contributions"])

    def test_zero_contributions_are_not_recorded(self):
        w = new_world(1, 6)
        cz.trace(w, "inflation", 0.01, {"demand": 0.01, "nothing": 0.0})
        self.assertNotIn("nothing", cz.trace_for(w, "inflation")["contributions"])

    def test_explain_names_the_largest_contributor_first(self):
        w = new_world(1, 6)
        cz.trace(w, "output", -0.014, {"credit_tightening": -0.005, "import_shortage": -0.006,
                                       "protests": -0.004, "fiscal_support": 0.001})
        text = cz.explain(w, "output")
        self.assertIn("import_shortage", text)
        self.assertLess(text.index("import_shortage"), text.index("fiscal_support"))

    def test_the_trace_is_bounded(self):
        w = new_world(1, 6)
        for i in range(cz.TRACE_CAP + 20):
            cz.trace(w, "inflation", 0.01, {"demand": 0.01})
        self.assertLessEqual(len(w.institutions["causal_trace"]), cz.TRACE_CAP)

    def test_explaining_something_never_traced_says_so_rather_than_inventing_it(self):
        w = new_world(1, 6)
        self.assertIn("no recorded causal trace", cz.explain(w, "something_never_measured"))

    def test_the_calibration_view_shows_the_true_parameters(self):
        w = new_world(1, 6)
        view = cz.calibration_view(w)
        self.assertEqual(view["structural_parameters"], cz.ensure(w))
        self.assertIn(view["regime"], cz.REGIMES)
        self.assertIn("fiscal_multiplier", view)

    def test_the_trace_survives_save_load(self):
        from karamaniya.world import World
        w = new_world(1, 6)
        cz.trace(w, "inflation", 0.02, {"demand": 0.02})
        again = World.from_dict(w.to_dict())
        self.assertIsNotNone(cz.trace_for(again, "inflation"))


class AgentsCannotSeeTheAnswers(unittest.TestCase):
    def test_the_true_parameters_do_not_appear_in_a_delegate_briefing(self):
        from karamaniya import briefing
        w = new_world(3, 6)
        text = briefing.month_briefing(w, "A") if hasattr(briefing, "month_briefing") else ""
        for name in cz.STRUCTURAL_PARAMETERS:
            with self.subTest(name=name):
                self.assertNotIn(name, text)

    def test_the_causal_trace_never_reaches_a_prompt(self):
        from karamaniya import prompts
        w = new_world(3, 6)
        cz.trace(w, "inflation", 0.02, {"demand_pressure": 0.02})
        for attr in dir(prompts):
            if attr.startswith("_"):
                continue
            fn = getattr(prompts, attr)
            if not callable(fn):
                continue
            try:
                out = fn(w)
            except Exception:
                continue
            if isinstance(out, str):
                with self.subTest(fn=attr):
                    self.assertNotIn("demand_pressure", out)


if __name__ == "__main__":
    unittest.main()
