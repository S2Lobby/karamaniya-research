"""The forecast ledger: checkable claims, scored honestly afterwards.

A delegate saying "inflation will be under 15% by winter" has made a claim that can be checked.
These tests pin the scoring arithmetic and, more importantly, the two things that are easy to get
wrong and flattering to get wrong: the Brier scale convention, and the fact that the no-skill
baseline for directional accuracy is not 50%.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import director, engine, forecasts  # noqa: E402
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


class Recording(unittest.TestCase):
    def test_a_well_formed_forecast_is_stored(self):
        w = new_world(1, 12)
        f = forecasts.record(w, "A", "inflation", 6, "below", 0.15, 0.7, "because")
        self.assertIsNotNone(f)
        self.assertEqual(f["metric"], "inflation")
        self.assertEqual(f["due_month"], 6)
        self.assertIsNone(f["resolved_month"])
        self.assertEqual(len(forecasts.ledger(w)), 1)

    def test_vague_or_malformed_forecasts_are_refused_not_stored(self):
        w = new_world(1, 12)
        bad = [("nonsense_metric", 6, "below", 0.1, 0.5),
               ("inflation", 7, "below", 0.1, 0.5),        # horizon not offered
               ("inflation", 6, "sideways", 0.1, 0.5),     # direction must be above/below
               ("inflation", "soon", "below", 0.1, 0.5),
               ("inflation", 6, "below", "a lot", 0.5)]
        for metric, horizon, direction, threshold, conf in bad:
            with self.subTest(metric=metric, horizon=horizon, direction=direction):
                self.assertIsNone(forecasts.record(w, "A", metric, horizon, direction, threshold, conf))
        self.assertEqual(forecasts.ledger(w), [], "a malformed forecast was stored anyway")

    def test_confidence_is_read_as_a_probability(self):
        """A confidence above 1 is a percentage, as a proportion above 1 is in a condition. Engine 5
        clamped it, so "75" was recorded as certainty and later scored as overconfidence. Anything
        still out of range is clamped."""
        w = new_world(1, 12)
        percent = forecasts.record(w, "A", "inflation", 3, "below", 0.1, 75)
        high = forecasts.record(w, "B", "inflation", 3, "below", 0.1, 500.0)
        low = forecasts.record(w, "C", "inflation", 3, "below", 0.1, -3.0)
        self.assertEqual(percent["confidence"], 0.75)
        self.assertEqual(high["confidence"], 1.0)
        self.assertEqual(low["confidence"], 0.0)

    def test_a_threshold_is_read_in_the_units_of_a_condition(self):
        """A forecast is scored against the values conditions use, so its threshold is read the
        way a condition's is: 15 for inflation is 15%, 90 for reserves is 90 million."""
        w = new_world(1, 12)
        self.assertEqual(forecasts.record(w, "A", "inflation", 3, "below", 15, 0.6)["threshold"], 0.15)
        self.assertEqual(forecasts.record(w, "B", "reserves", 3, "above", 90, 0.6)["threshold"], 90_000_000.0)
        self.assertEqual(forecasts.record(w, "C", "approval", 3, "above", 0.4, 0.6)["threshold"], 0.4)

    def test_the_number_of_open_forecasts_is_capped(self):
        w = new_world(1, 12)
        for i in range(forecasts.MAX_OPEN + 3):
            forecasts.record(w, "A", "inflation", 12, "below", 0.1 + i * 0.01, 0.5)
        self.assertEqual(len(forecasts.open_for(w, "A")), forecasts.MAX_OPEN + 3)
        # The cap is applied where the council reads model output, not in the ledger itself.
        self.assertGreater(len(forecasts.open_for(w, "A")), forecasts.MAX_OPEN)


class Resolution(unittest.TestCase):
    def test_a_forecast_is_not_scored_before_its_horizon(self):
        w = new_world(1, 12)
        forecasts.record(w, "A", "food_ratio", 6, "above", 0.5, 0.9)
        run(w, 4, each=steady)
        self.assertEqual(forecasts.score(w, "A")["scored"], 0)
        self.assertEqual(forecasts.open_for(w, "A"), forecasts.ledger(w))

    def test_a_forecast_is_scored_when_its_horizon_arrives(self):
        w = new_world(1, 12)
        f = forecasts.record(w, "A", "food_ratio", 3, "above", 0.5, 0.9)
        run(w, 4, each=steady)
        self.assertIsNotNone(f["resolved_month"])
        self.assertIsNotNone(f["actual"])
        self.assertIsNotNone(f["outcome"])

    def test_a_forecast_is_scored_exactly_once(self):
        w = new_world(1, 12)
        f = forecasts.record(w, "A", "food_ratio", 3, "above", 0.5, 0.9)
        run(w, 6, each=steady)
        first = f["resolved_month"]
        run(w, 4, each=steady)
        self.assertEqual(f["resolved_month"], first)

    def test_the_direction_decides_the_outcome(self):
        w = new_world(1, 12)
        run(w, 3, each=steady)
        actual = w.econ.food_ratio
        below = forecasts.record(w, "A", "food_ratio", 3, "below", actual + 1.0, 0.9)
        above = forecasts.record(w, "B", "food_ratio", 3, "above", actual - 1.0, 0.9)
        run(w, 4, each=steady)
        self.assertEqual(below["outcome"], 1.0)
        self.assertEqual(above["outcome"], 1.0)


class BrierArithmetic(unittest.TestCase):
    """The scale convention is the thing most easily got wrong, so it is pinned."""

    def _score(self, confidence, threshold_below):
        w = new_world(1, 12)
        run(w, 2, each=steady)
        actual = w.econ.food_ratio
        threshold = actual + 1.0 if threshold_below else actual - 1.0
        direction = "below" if threshold_below else "above"
        f = forecasts.record(w, "A", "food_ratio", 3, direction, threshold, confidence)
        run(w, 4, each=steady)
        return f

    def test_a_correct_certain_forecast_scores_near_zero(self):
        f = self._score(1.0, True)
        self.assertEqual(f["outcome"], 1.0)
        self.assertAlmostEqual(f["brier"], 0.0, places=6)

    def test_a_wrong_certain_forecast_scores_one(self):
        # Certain the event happens, and it does not.
        w = new_world(1, 12)
        run(w, 2, each=steady)
        actual = w.econ.food_ratio
        f = forecasts.record(w, "A", "food_ratio", 3, "below", actual - 1.0, 1.0)
        run(w, 4, each=steady)
        self.assertEqual(f["outcome"], 0.0)
        self.assertAlmostEqual(f["brier"], 1.0, places=6)

    def test_always_saying_fifty_percent_scores_a_quarter(self):
        """On the binomial 0-1 scale. On the Good Judgment 0-2 scale it would be 0.5."""
        f = self._score(0.5, True)
        self.assertAlmostEqual(f["brier"], 0.25, places=6)

    def test_a_confident_miss_costs_more_than_a_hedged_one(self):
        wrong_confident = self._score(0.05, True)
        self.assertEqual(wrong_confident["outcome"], 1.0)
        self.assertGreater(wrong_confident["brier"], 0.25)

    def test_the_scale_is_stated_on_every_score(self):
        w = new_world(1, 12)
        self.assertIn("0-1", forecasts.score(w, "A")["brier_scale"])
        self.assertIn("0-2", forecasts.score(w, "A")["brier_scale"])


class MurphyDecomposition(unittest.TestCase):
    def test_the_decomposition_adds_up(self):
        w = new_world(1, 12)
        run(w, 2, each=steady)
        for i, conf in enumerate((0.9, 0.6, 0.5, 0.3, 0.8)):
            forecasts.record(w, "A", "food_ratio", 3, "above", -1.0, conf)
        run(w, 5, each=steady)
        s = forecasts.score(w, "A")
        self.assertAlmostEqual(s["decomposition_sums"], s["brier"], places=3)

    def test_reliability_is_low_when_stated_confidence_matches_outcomes(self):
        w = new_world(1, 12)
        run(w, 2, each=steady)
        # Forecasts that are certainly right should be reliable.
        for _ in range(4):
            forecasts.record(w, "A", "food_ratio", 3, "above", -1.0, 1.0)
        run(w, 5, each=steady)
        self.assertLess(forecasts.score(w, "A")["reliability"], 0.01)

    def test_reliability_is_high_when_confidence_is_unjustified(self):
        w = new_world(1, 12)
        run(w, 2, each=steady)
        for _ in range(4):
            forecasts.record(w, "A", "food_ratio", 3, "above", 1e9, 1.0)   # certainly wrong
        run(w, 5, each=steady)
        self.assertGreater(forecasts.score(w, "A")["reliability"], 0.5)


class DirectionalAccuracy(unittest.TestCase):
    def test_the_no_skill_baseline_is_not_fifty_percent(self):
        """The Pesaran-Timmermann point: the baseline is whichever direction was more common."""
        w = new_world(1, 12)
        run(w, 2, each=steady)
        # Every event happens, so always answering "it will happen" is the no-skill rule and it
        # scores 100%.
        for _ in range(4):
            forecasts.record(w, "A", "food_ratio", 3, "above", -1.0, 0.7)
        run(w, 5, each=steady)
        d = forecasts.score(w, "A")["directional"]
        self.assertEqual(d["event_rate"], 1.0)
        self.assertEqual(d["no_skill_baseline"], 1.0)
        self.assertFalse(d["beats_no_skill"],
                         "getting everything right was reported as beating a 100% baseline")

    def test_a_forecaster_who_beats_the_baseline_is_credited(self):
        w = new_world(1, 12)
        run(w, 2, each=steady)
        # Mix of outcomes, all called correctly.
        forecasts.record(w, "A", "food_ratio", 3, "above", -1.0, 0.9)     # will happen
        forecasts.record(w, "A", "food_ratio", 3, "below", -1.0, 0.0)     # will not happen
        forecasts.record(w, "A", "unemployment", 3, "above", -1.0, 0.9)
        forecasts.record(w, "A", "unemployment", 3, "below", -1.0, 0.0)
        run(w, 5, each=steady)
        d = forecasts.score(w, "A")["directional"]
        self.assertEqual(d["hit_rate"], 1.0)
        self.assertLess(d["no_skill_baseline"], 1.0)
        self.assertTrue(d["beats_no_skill"])


class CalibrationCurve(unittest.TestCase):
    def test_the_curve_reports_stated_against_observed(self):
        w = new_world(1, 12)
        run(w, 2, each=steady)
        for _ in range(3):
            forecasts.record(w, "A", "food_ratio", 3, "above", -1.0, 0.9)
        run(w, 5, each=steady)
        curve = forecasts.score(w, "A")["calibration_curve"]
        self.assertTrue(curve)
        bucket = curve[0]
        self.assertIn("stated", bucket)
        self.assertIn("observed", bucket)
        self.assertIn("n", bucket)

    def test_an_empty_ledger_produces_no_curve_and_no_error(self):
        w = new_world(1, 12)
        s = forecasts.score(w, "A")
        self.assertEqual(s["scored"], 0)
        self.assertEqual(s["calibration_curve"], [])


class PrivacY(unittest.TestCase):
    def test_a_delegate_sees_its_own_record_and_not_anothers(self):
        from karamaniya import decision_context
        w = new_world(1, 24)
        for _ in range(5):
            forecasts.record(w, "A", "food_ratio", 3, "above", -1.0, 0.95)
        run(w, 5, each=steady)
        text_a, _ = decision_context.build(w, "A", "decision", public_brief="", budget=30000)
        text_b, _ = decision_context.build(w, "B", "decision", public_brief="", budget=30000)
        self.assertIn("YOUR FORECAST RECORD", text_a)
        self.assertNotIn("YOUR FORECAST RECORD", text_b,
                         "one delegate's calibration leaked into another's prompt")

    def test_an_unscored_delegate_gets_no_record_line(self):
        w = new_world(1, 12)
        self.assertEqual(forecasts.context_for(w, "A"), "")

    def test_the_ledger_is_private_to_the_engine_not_the_prompt(self):
        from karamaniya import prompts
        w = new_world(1, 12)
        forecasts.record(w, "A", "inflation", 6, "below", 0.2, 0.8, "secret reasoning")
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
                    self.assertNotIn("secret reasoning", out)


class DeterminismAndStorage(unittest.TestCase):
    def test_scoring_is_deterministic(self):
        def once():
            w = new_world(5, 18)
            run(w, 2, each=steady)
            for conf in (0.8, 0.4, 0.9):
                forecasts.record(w, "A", "food_ratio", 3, "above", -1.0, conf)
            run(w, 5, each=steady)
            return forecasts.score(w, "A")["brier"]
        self.assertEqual(once(), once())

    def test_the_ledger_survives_save_and_load(self):
        from karamaniya.world import World
        w = new_world(1, 12)
        forecasts.record(w, "A", "food_ratio", 3, "above", 0.5, 0.8)
        run(w, 5, each=steady)
        again = World.from_dict(w.to_dict())
        self.assertEqual(len(forecasts.ledger(again)), 1)
        self.assertEqual(forecasts.ledger(again)[0]["brier"], forecasts.ledger(w)[0]["brier"])

    def test_a_pre_ledger_checkpoint_still_scores(self):
        from karamaniya.world import World
        w = new_world(1, 12)
        data = w.to_dict()
        data["institutions"].pop("forecasts", None)
        old = World.from_dict(data)
        self.assertEqual(forecasts.ledger(old), [])
        self.assertEqual(forecasts.score(old, "A")["scored"], 0)


class InARun(unittest.TestCase):
    def test_a_scripted_run_can_carry_forecasts_through_to_a_score(self):
        """End to end: recorded at decision time, resolved months later, scored."""
        from karamaniya.council import Council
        from karamaniya.runner import _seats
        from karamaniya.storage import RunStore
        from karamaniya.config import load_config
        import tempfile, shutil
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg = load_config(os.path.join(root, "council.scripted.toml"))
        mapping = {letter: seat["label"] for letter, seat in zip("ABCDE", cfg["seats"])}
        cfg = {**cfg, "mapping": mapping}
        tmp = tempfile.mkdtemp(prefix="karamaniya-fc-")
        try:
            w = new_world(cfg["run"]["seed"], 12, member_ids=list(mapping))
            council = Council(w, _seats(cfg, mapping), cfg["run"], RunStore(os.path.join(tmp, "r")))
            store = RunStore(os.path.join(tmp, "r"))
            store.save_config(cfg)
            store._write_json("survey.json", council.survey())
            council.diagnose_founding()
            council.form_government()
            for _ in range(5):
                council.run_month()
            # Give a seat a checkable claim and run it out.
            forecasts.record(w, "A", "food_ratio", 3, "above", -1.0, 0.9)
            for _ in range(4):
                council.run_month()
            self.assertGreaterEqual(forecasts.score(w, "A")["scored"], 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
