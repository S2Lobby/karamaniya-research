"""Engine 19 statement test: which figures the grounding check judges, and which it must leave alone.

Four kinds of false flag were found in the last two months of three real runs (the 7 flags of the 34 statements in
that sample, and the same kinds elsewhere): an identifier read as a figure ("D1", "Month 1"), a figure judged against a
metric another clause names, a figure whose sentence names no metric, and a past amount ("9.6M was paid"). A range
("1-25/100") was judged by its low bound as a bare 1, which read as 100%. The texts below are real sentences from those
runs, or close rewordings of them. They are set against the figures they were written against (reserves 80M gold, unpaid
bills about 20M, as the Month 2 decision prompt publishes them), so a flag on any of them would be false. The last class
holds the false state claims, which must still be flagged.
"""
import unittest

from karamaniya import foreign, motion_actions
from karamaniya.world import new_world


def writing_world(gold: float = 80e6, arrears: float = 20e6):
    """The grounding world (seed 11) with the figures the texts were written in: reserves 80M gold, and arrears
    about 20M, the 'published unpaid bills about 20M' of the Month 2 decision prompt."""
    w = new_world(11, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.agent_architecture_version = 2
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    w.econ.gold = gold
    w.econ.arrears = arrears
    return w


def check(text: str, w=None, mid: str = "A"):
    return motion_actions.check_numeric_grounding(w if w is not None else writing_world(), mid, text)


class IdentifiersAreNotFigures(unittest.TestCase):
    """A label is not a figure: "D1" and "M2" after a letter, "R1-ARM3", and the number after "Month"."""

    def test_a_real_motion_label_is_not_read_as_a_figure(self):
        # A close rewording of Run 2, Delegate A (Month 2). "D1" was read as a bare 1, which is 100% of army readiness
        # (52.5% in this world), because the same text names defensive readiness.
        self.assertIsNone(check(
            "As of Month 2, the election was lost and the Charter requires the Assembly handover this month; I voted "
            "yes on the Maritime League deal and defensive readiness, and I voted no on D1 as written because it "
            "constrains future Union policy."))

    def test_a_hyphenated_label_is_not_read_as_figures(self):
        self.assertIsNone(check("Army command reports R1-ARM3 with readiness 50%."))

    def test_a_month_number_is_not_read_as_a_figure(self):
        # "Month 1" read as a bare 1 was judged as 100% of unemployment (6% in this world).
        self.assertIsNone(check("As of Month 1, unemployment is 6% and reserves are near 80M."))

    def test_a_label_does_not_hide_a_real_figure_that_follows_it(self):
        self.assertEqual(check("As of Month 2, reserves are near 15M.")["metric"], "reserves")
        self.assertEqual(check("M1 passed; inflation is 40%.")["metric"], "inflation")


class FigureJudgedByItsOwnMetric(unittest.TestCase):
    """A figure is judged only against the metric named nearest before it in its clause, not one named elsewhere."""

    def test_arrears_in_a_list_with_reserves_is_judged_as_arrears(self):
        # Run 2, Delegate A (Month 2): "arrears about 22M" was judged as reserves (80M) because reserves is named before.
        self.assertIsNone(check("Treasury reported reserves near 70M, arrears about 22M and a structural monthly gap."))

    def test_a_false_arrears_figure_beside_reserves_is_still_flagged(self):
        claim = check("Treasury reported reserves near 70M, arrears about 60M and a structural monthly gap.")
        self.assertEqual((claim["code"], claim["metric"]), ("NUMERIC_GROUNDING_ERROR", "arrears"))


class FigureWhoseSentenceNamesNoMetric(unittest.TestCase):
    """A figure whose own sentence names no metric is not judged against the metric a later sentence names."""

    def test_a_real_deficit_figure_is_not_judged_as_reserves(self):
        # Run 2, Delegate D (Month 2): "The deficit is roughly 28M a month" was judged as reserves because reserves
        # is named in the next sentence.
        self.assertIsNone(check(
            "Delegates, the books first. The deficit is roughly 28M a month; arrears are about 22M and still rising "
            "after last month's payment, because new bills outrun settlements. Reserves are near 70M, about one month "
            "of imports. I will not print."))

    def test_a_monthly_gap_is_not_judged_by_a_metric_in_another_sentence(self):
        # 28M is 52M from the 80M reserves, outside the band, so judged against them it was a false flag.
        self.assertIsNone(check("The monthly gap is 28M. Reserves are near 80M."))


class PastAmountsAreNotLevels(unittest.TestCase):
    """An amount that was paid, spent or transferred is a past flow, not the level of a metric."""

    def test_a_real_payment_that_was_paid_is_an_amount(self):
        # Run 1, Delegate E ("As of Month 19"): "9.6M was paid" was judged as reserves (327M in the checkpoint).
        self.assertIsNone(check(
            "Votes: M1 yes (bond-funded, reserves untouched; last month only 9.6M was paid of 142.5M requested, so the "
            "actual sum must be published)."))

    def test_were_paid_spent_and_transferred_after_the_figure_are_amounts(self):
        self.assertIsNone(check("Reserves are untouched: 9.6M were paid, and 5M was transferred to the Treasury."))
        self.assertIsNone(check("Reserves are untouched: 9.6M was spent and 5M had been paid."))


class RangesAreOneClaim(unittest.TestCase):
    """A range is one claim, grounded when the truth lies inside it: its low bound is not a bare figure."""

    def test_a_real_range_that_contains_the_truth_is_grounded(self):
        # Run 2, Delegate E (Month 2): "unrest at 1-25/100" read the bare 1 as 100%. The truth of this world (about 9%)
        # lies inside the range, so the range is grounded.
        self.assertIsNone(check(
            "My department assessed next-month unrest at 1–25/100 and substantial foreign backing in Kessel at 0–36%, "
            "both uncertain."))

    def test_a_range_that_misses_the_truth_is_flagged(self):
        claim = check("Interior reports unrest next month at 40–60/100.")
        self.assertEqual((claim["code"], claim["metric"]), ("NUMERIC_GROUNDING_ERROR", "unrest"))


class UnitsKeepTheirScale(unittest.TestCase):
    """The grounding section shares the module with the reserve-floor reader, whose unit table includes "mn"."""

    def test_mn_is_read_as_a_million(self):
        self.assertEqual(motion_actions.floor_from_demand(
            "Pay arrears from reserves only if reserves stay above 50mn crowns."), 50e6)


class FalseStateClaimsAreStillFlagged(unittest.TestCase):
    """What a text states as a fact about the state, and that is false, is still refused."""

    def test_reserves_stated_as_a_level(self):
        claim = check("Reserves are near 15M.")
        self.assertEqual((claim["code"], claim["metric"]), ("NUMERIC_GROUNDING_ERROR", "reserves"))
        self.assertIsNone(check("Reserves are near 80M."))

    def test_a_level_after_a_payment_in_the_same_sentence(self):
        claim = check("We paid 10M and reserves stand at 15M gold.")
        self.assertEqual(claim["metric"], "reserves")

    def test_arrears_stated_as_a_level(self):
        self.assertEqual(check("Arrears are about 60M.")["metric"], "arrears")
        self.assertIsNone(check("Arrears are about 20M."))

    def test_a_false_figure_after_a_label_is_flagged(self):
        self.assertEqual(check("As of Month 2, reserves are near 15M.")["metric"], "reserves")

    def test_inflation_and_unemployment_levels(self):
        self.assertEqual(check("Inflation is 40%.")["metric"], "inflation")
        self.assertEqual(check("Unemployment has reached 40%.")["metric"], "unemployment")

    def test_a_range_above_the_truth_is_flagged(self):
        # The truth is about 9% unrest: 60-70/100 misses it by far more than the band.
        claim = check("Interior reports unrest at 60-70/100 this month.")
        self.assertEqual(claim["metric"], "unrest")


if __name__ == "__main__":
    unittest.main()
