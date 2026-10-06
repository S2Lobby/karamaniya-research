"""What a delegate believes about how the economy works, held apart from what it is.

The distinction is mandatory: the engine's true structural parameters must never be visible to an
agent, and an agent must be able to be wrong in a way the benchmark can measure. These tests pin
both halves — that beliefs move on evidence, and that nothing in the belief path reads the truth.
"""
import inspect
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import causal_beliefs as cb, causality, director, engine, forecasts  # noqa: E402
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


class PriorsAreNotTheTruth(unittest.TestCase):
    def test_a_delegate_is_not_seeded_with_the_true_parameter(self):
        """If priors came from the truth, every delegate would start correct and there would be
        nothing to learn."""
        matched = 0
        for seed in range(1, 25):
            w = new_world(seed, 12)
            w.const.offices["treasury"] = "B"
            believed = cb.estimate(w, "B", "exchange_rate_pass_through")["value"]
            true = causality.param(w, "exchange_rate_pass_through")
            if abs(believed - true) < 0.005:
                matched += 1
        self.assertLess(matched, 3, f"{matched} of 24 seeds were seeded with the truth")

    def test_nothing_in_the_belief_module_reads_the_true_parameters(self):
        """Except in `compare_to_truth`, which is research-only and never shown to an agent."""
        source = inspect.getsource(cb)
        for fn in ("def ensure", "def learn", "def context", "def learn_from_forecast"):
            i = source.find(fn)
            j = source.find("\ndef ", i + 5)
            body = source[i:j if j > 0 else len(source)]
            with self.subTest(function=fn.split()[-1]):
                self.assertNotIn("causality.param", body)
                self.assertNotIn("ensure(w)", body)

    def test_the_research_comparison_is_the_only_place_the_truth_appears(self):
        w = new_world(3, 12)
        w.const.offices["treasury"] = "B"
        comparison = cb.compare_to_truth(w, "B")
        self.assertIn("believed", comparison["exchange_rate_pass_through"])
        self.assertIsNotNone(comparison["exchange_rate_pass_through"]["true"])


class WhichRelationshipsADelegateHolds(unittest.TestCase):
    def test_an_office_shapes_what_a_delegate_models(self):
        w = new_world(1, 12)
        w.const.offices["treasury"] = "B"
        w.const.offices["army"] = "C"
        treasury = set(cb.ensure(w, "B"))
        army = set(cb.ensure(w, "C"))
        self.assertIn("exchange_rate_pass_through", treasury)
        self.assertNotIn("exchange_rate_pass_through", army,
                         "an army commander models the exchange rate")
        self.assertIn("army_institutional_loyalty", army)
        self.assertNotIn("army_institutional_loyalty", treasury)

    def test_a_delegate_with_no_office_still_holds_a_view(self):
        w = new_world(1, 12)
        self.assertTrue(cb.ensure(w, "A"))

    def test_the_strongest_coverage_is_the_head_and_the_treasury(self):
        w = new_world(1, 12)
        w.const.offices["head"] = "A"
        self.assertIn("fiscal_multiplier", cb.ensure(w, "A"))

    def test_estimates_are_seeded_and_stable_within_a_run(self):
        w = new_world(5, 12)
        first = dict(cb.ensure(w, "A"))
        again = {k: dict(v) for k, v in cb.ensure(w, "A").items()}
        self.assertEqual(first, again)

    def test_the_same_seed_gives_the_same_priors(self):
        a = new_world(11, 12)
        b = new_world(11, 12)
        self.assertEqual(cb.ensure(a, "A")["inflation_persistence"]["value"],
                         cb.ensure(b, "A")["inflation_persistence"]["value"])

    def test_different_seeds_give_different_priors(self):
        values = {cb.ensure(new_world(s, 12), "A")["inflation_persistence"]["value"]
                  for s in range(1, 15)}
        self.assertGreater(len(values), 5)

    def test_every_relationship_has_a_midpoint_spread_and_bounds(self):
        for name, spec in cb.RELATIONSHIPS.items():
            with self.subTest(relationship=name):
                self.assertIn("midpoint", spec)
                self.assertIn("spread", spec)
                low, high = spec["bounds"]
                self.assertLess(low, high)

    def test_a_seeded_prior_always_lies_inside_the_bounds(self):
        for seed in range(1, 30):
            w = new_world(seed, 12)
            for name, item in cb.ensure(w, "A").items():
                low, high = cb.RELATIONSHIPS[name]["bounds"]
                with self.subTest(seed=seed, relationship=name):
                    self.assertGreaterEqual(item["value"], low)
                    self.assertLessEqual(item["value"], high)


class LearningFromBeingWrong(unittest.TestCase):
    def _misses(self, direction, threshold, count=6):
        w = new_world(7, 30)
        w.const.offices["treasury"] = "B"
        start = dict(cb.estimate(w, "B", "inflation_persistence"))
        for _ in range(count):
            forecasts.record(w, "B", "inflation", 3, direction, threshold, 0.9, "test")
            run(w, 4, each=steady)
        return start, cb.estimate(w, "B", "inflation_persistence")

    def test_under_predicting_inflation_raises_the_persistence_estimate(self):
        """A delegate that keeps expecting inflation to vanish and is wrong each time should come
        to believe inflation is more persistent, not less."""
        start, end = self._misses("below", 0.0001)
        self.assertGreater(end["value"], start["value"])

    def test_over_predicting_inflation_lowers_it(self):
        start, end = self._misses("above", 0.50)
        self.assertLess(end["value"], start["value"])

    def test_being_wrong_costs_confidence(self):
        start, end = self._misses("below", 0.0001)
        self.assertLess(end["confidence"], start["confidence"])

    def test_being_right_restores_confidence_only_slowly(self):
        w = new_world(7, 30)
        w.const.offices["treasury"] = "B"
        for _ in range(4):
            forecasts.record(w, "B", "inflation", 3, "below", 0.0001, 0.9, "test")
            run(w, 4, each=steady)
        low = cb.estimate(w, "B", "inflation_persistence")["confidence"]
        for _ in range(4):
            forecasts.record(w, "B", "inflation", 3, "above", -1.0, 0.85, "sure to hit")
            run(w, 4, each=steady)
        recovered = cb.estimate(w, "B", "inflation_persistence")["confidence"]
        self.assertGreater(recovered, low)
        self.assertLess(recovered - low, 0.15, "confidence vaulted back on four successes")

    def test_an_estimate_never_leaves_its_plausible_range(self):
        start, end = self._misses("above", 0.50, count=20)
        low, high = cb.RELATIONSHIPS["inflation_persistence"]["bounds"]
        self.assertGreaterEqual(end["value"], low)
        self.assertLessEqual(end["value"], high)

    def test_an_error_is_attributed_to_the_mechanisms_bearing_on_the_subject(self):
        w = new_world(7, 12)
        w.const.offices["treasury"] = "B"
        before = {n: cb.estimate(w, "B", n)["value"] for n in cb.held_by(w, "B")}
        entry = {"actor": "B", "metric": "inflation", "brier": 0.81, "correct": False,
                 "outcome": 0.0, "direction": "below", "actual": 0.05, "threshold": 0.001}
        revised = cb.learn_from_forecast(w, entry)
        names = [r[0] for r in revised]
        self.assertIn("inflation_persistence", names)
        self.assertNotIn("army_institutional_loyalty", names)
        after = {n: cb.estimate(w, "B", n)["value"] for n in cb.held_by(w, "B")}
        # The treasury holds several estimates; only the ones bearing on inflation should move.
        self.assertEqual(before["fiscal_multiplier"], after["fiscal_multiplier"])
        self.assertEqual(before["okun_slope"], after["okun_slope"])

    def test_a_forecast_about_a_metric_the_delegate_cannot_model_teaches_nothing(self):
        w = new_world(7, 12)
        self.assertEqual(cb.learn(w, "A", "no_such_relationship", 0.5), None)

    def test_the_magnitude_comes_from_the_brier_scale_not_the_raw_units(self):
        """A raw miss has whatever units the metric has; the Brier score does not."""
        w = new_world(7, 12)
        w.const.offices["treasury"] = "B"
        big = {"actor": "B", "metric": "inflation", "brier": 0.95, "correct": False,
               "outcome": 0.0, "direction": "above", "actual": 0.1, "threshold": 0.05}
        small = dict(big, brier=0.27)
        cb.ensure(w, "B")
        first = dict(cb.estimate(w, "B", "inflation_persistence"))
        cb.learn_from_forecast(w, big)
        after_big = cb.estimate(w, "B", "inflation_persistence")["value"]
        w2 = new_world(7, 12)
        w2.const.offices["treasury"] = "B"
        cb.ensure(w2, "B")
        cb.learn_from_forecast(w2, small)
        after_small = cb.estimate(w2, "B", "inflation_persistence")["value"]
        self.assertNotAlmostEqual(after_big, after_small, places=4)


class TheDelegateSeesItsOwnViewAsABelief(unittest.TestCase):
    def test_the_context_is_phrased_as_an_estimate_not_a_fact(self):
        w = new_world(1, 12)
        text = cb.context(w, "A")
        self.assertIn("YOUR OWN READING", text)
        self.assertIn("may be wrong", text)

    def test_the_context_gives_a_range_and_a_confidence_word(self):
        w = new_world(1, 12)
        text = cb.context(w, "A")
        self.assertIn("between", text)
        self.assertTrue(any(word in text for word in ("sure", "unsure", "guessing")))

    def test_a_delegate_who_models_nothing_gets_no_context(self):
        """Every delegate holds something by default, so this is exercised by removing the view."""
        w = new_world(1, 12)
        original = cb.held_by
        cb.held_by = lambda world, mid: ()
        try:
            w.institutions["causal_beliefs"] = {"A": {}}
            self.assertEqual(cb.context(w, "A"), "")
        finally:
            cb.held_by = original

    def test_a_reported_range_stays_inside_what_the_parameter_can_be(self):
        """A delegate cannot be unsure about values the parameter cannot take."""
        for seed in range(1, 12):
            w = new_world(seed, 12)
            for name, item in cb.ensure(w, "A").items():
                low, high = cb.band(item, name)
                bound_low, bound_high = cb.RELATIONSHIPS[name]["bounds"]
                with self.subTest(seed=seed, relationship=name):
                    self.assertGreaterEqual(low, bound_low)
                    self.assertLessEqual(high, bound_high)

    def test_the_reading_reaches_the_decision_prompt(self):
        from karamaniya import decision_context
        w = new_world(1, 12)
        text, _ = decision_context.build(w, "A", "decision", public_brief="", budget=30000)
        self.assertIn("YOUR OWN READING", text)

    def test_another_delegates_estimates_do_not_leak_into_a_prompt(self):
        from karamaniya import decision_context
        w = new_world(1, 12)
        w.const.offices["treasury"] = "B"
        cb.ensure(w, "B")
        text, _ = decision_context.build(w, "A", "decision", public_brief="", budget=30000)
        self.assertNotIn("exchange rate pass-through", text,
                         "B's private reading of the exchange rate reached A")


class DeterminismAndStorage(unittest.TestCase):
    def test_learning_is_deterministic(self):
        def once():
            w = new_world(5, 18)
            w.const.offices["treasury"] = "B"
            for _ in range(4):
                forecasts.record(w, "B", "inflation", 3, "below", 0.0001, 0.9, "test")
                run(w, 4, each=steady)
            return cb.estimate(w, "B", "inflation_persistence")["value"]
        self.assertEqual(once(), once())

    def test_beliefs_survive_save_and_load(self):
        from karamaniya.world import World
        w = new_world(7, 24)
        w.const.offices["treasury"] = "B"
        for _ in range(3):
            forecasts.record(w, "B", "inflation", 3, "below", 0.0001, 0.9, "test")
            run(w, 4, each=steady)
        before = dict(cb.estimate(w, "B", "inflation_persistence"))
        again = cb.estimate(World.from_dict(w.to_dict()), "B", "inflation_persistence")
        self.assertEqual(before["value"], again["value"])
        self.assertEqual(before["confidence"], again["confidence"])

    def test_a_pre_belief_checkpoint_still_seeds(self):
        from karamaniya.world import World
        w = new_world(7, 12)
        data = w.to_dict()
        data["institutions"].pop("causal_beliefs", None)
        old = World.from_dict(data)
        self.assertTrue(cb.ensure(old, "A"))


if __name__ == "__main__":
    unittest.main()
