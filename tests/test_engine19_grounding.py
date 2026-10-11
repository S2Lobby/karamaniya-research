"""Engine 19 numeric grounding and thresholds (audit of engine 18: MO3-MO10, MO22, CO7).

Each class is one audit ID. The proof scripts (PoCs) of the audit reproduce the same cases against
engine 18; these tests keep them fixed.
"""
import unittest
from unittest import mock

from karamaniya import actions, intelligence, motion_actions, token_saving
from karamaniya.military import union_army
from karamaniya.world import new_world


def ratio_world(inflation: float):
    """A world whose annualised inflation is exactly `inflation` (a fraction)."""
    w = new_world(11, 36)
    w.econ.cpi = (1 + inflation) ** (1 / 12)
    return w


class PercentPointThresholds(unittest.TestCase):
    """MO9 + CO7: a threshold written in percentage points means percent for inflation and deficit."""

    def test_inflation_and_deficit_percent_points_are_read_as_percent(self):
        for metric in ("inflation", "deficit"):
            with self.subTest(metric=metric):
                self.assertAlmostEqual(motion_actions.canonical_metric_value(metric, 2), 0.02)
                self.assertAlmostEqual(motion_actions.canonical_metric_value(metric, 6), 0.06)
                self.assertAlmostEqual(motion_actions.canonical_metric_value(metric, 8), 0.08)

    def test_fractions_are_left_alone(self):
        for metric, value in (("inflation", 0.06), ("inflation", 0.3), ("deficit", 0.05), ("approval", 0.4)):
            with self.subTest(metric=metric, value=value):
                self.assertEqual(motion_actions.canonical_metric_value(metric, value), value)

    def test_food_coverage_keeps_its_surplus_reading(self):
        # Food coverage legitimately exceeds 1 (the economy starts at 1.0), so 1.05 is 105%, not 1.05%.
        self.assertEqual(motion_actions.canonical_metric_value("food_ratio", 1.05), 1.05)
        self.assertEqual(motion_actions.canonical_metric_value("food_ratio", 100), 1.0)
        self.assertEqual(motion_actions.canonical_metric_value("food_ratio", 80), 0.8)


class PercentPointConditions(unittest.TestCase):
    """MO9 + CO7: the three places a threshold is read, each with the same units."""

    def motion(self, operator: str, value: float) -> dict:
        return {"type": "set_policy", "subject": "tax", "value": "0.10", "passed": True,
                "text": "Cut the tax share to 10% of output.",
                "conditions": [{"metric": "inflation", "operator": operator, "value": value,
                                "source": "inflation condition"}]}

    def test_a_motion_ceiling_in_percent_points_blocks_execution_at_high_inflation(self):
        gate = motion_actions.validate_execution(ratio_world(0.60), self.motion("<=", 6))
        self.assertIsNotNone(gate)
        self.assertEqual(gate["code"], "EXECUTION_BLOCKED_CONDITION")

    def test_the_same_ceiling_executes_when_inflation_is_low(self):
        self.assertIsNone(motion_actions.validate_execution(ratio_world(0.03), self.motion("<=", 6)))

    def test_a_vote_condition_in_percent_points_is_stored_as_a_fraction(self):
        w = new_world(12, 6, member_ids=list("ABCDE"))
        normalized, problems = actions.normalize_decision_v2(
            w, "A",
            {"votes": {"M1": "conditional"},
             "vote_reasons": {"M1": "Support only while inflation stays at or below 2 percent."},
             "vote_conditions": [{"motion_id": "M1", "kind": "metric", "metric": "inflation",
                                  "operator": "<=", "value": 2, "if_unmet": "no"}]},
            ["M1"], 0)
        self.assertEqual(problems, [])
        self.assertAlmostEqual(normalized["vote_conditions"]["M1"]["value"], 0.02)

    def test_a_quiet_month_wake_in_percent_points_wakes_at_the_stated_level(self):
        plan = token_saving.read_stand_by(
            {"stand_by": {"months": "2", "wake_if": [{"metric": "inflation", "operator": ">=", "value": 8}]}},
            {**token_saving.DEFAULTS, "wakeups": "on_events"})
        self.assertAlmostEqual(plan["wake_if"][0]["value"], 0.08)


class SafeguardAmountsInMotionText(unittest.TestCase):
    """MO10: the reserve floor in a motion's text is read whole, decimals and comma groups included."""

    SENTENCES = (
        ("Pay arrears from reserves only if reserves stay above 1.5bn crowns.", 1.5e9),
        ("Pay arrears from reserves only if reserves stay above 79.5M crowns.", 79.5e6),
        ("Pay arrears from reserves only if reserves stay above 12,500,000 crowns.", 12_500_000.0),
        ("Reserves must remain at least 88,000,000 crowns after the payment.", 88e6),
    )

    def floor_in_text(self, text: str):
        gating = [c["value"] for c in motion_actions.parse_conditions(text)
                  if c["metric"] == "reserves_after_payment"]
        return gating[0] if gating else None

    def test_the_motion_text_reads_the_whole_amount(self):
        for text, want in self.SENTENCES:
            with self.subTest(text=text):
                self.assertEqual(self.floor_in_text(text), want)

    def test_the_motion_text_agrees_with_the_response_reader(self):
        for text, _want in self.SENTENCES:
            with self.subTest(text=text):
                self.assertEqual(self.floor_in_text(text), motion_actions.floor_from_demand(text))

    def test_the_executable_gate_uses_the_same_floor(self):
        text = "Pay arrears from reserves only if reserves stay above 1.5bn crowns."
        conditions = motion_actions.motion_conditions({"type": "settle_arrears", "subject": "reserves", "text": text})
        self.assertEqual([(c["metric"], c["operator"], c["value"]) for c in conditions],
                         [("reserves_after_payment", ">=", 1.5e9)])


def grounding_world():
    """The audit's world (seed 11): reserves 80,000,000 gold, 28,000 soldiers, inflation 0."""
    from karamaniya import foreign
    w = new_world(11, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.agent_architecture_version = 2
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


class CommaGroupedFigures(unittest.TestCase):
    """MO3: "20,000,000" is one figure, judged the same as "20 million" or "20000000"."""

    def test_a_comma_grouped_figure_is_read_as_one_value(self):
        self.assertEqual([n["value"] for n in motion_actions._numbers_in("Our reserves are 20,000,000 gold")],
                         [2e7])
        self.assertEqual([n["value"] for n in motion_actions._numbers_in("We have 50,000 soldiers")], [50000.0])

    def test_a_false_comma_figure_is_refused_as_the_plain_form_is(self):
        w = grounding_world()
        for text in ("Our reserves are 20 million gold, far too low to pay the arrears.",
                     "Our reserves are 20000000 gold, far too low to pay the arrears.",
                     "Our reserves are 20,000,000 gold, far too low to pay the arrears."):
            with self.subTest(text=text):
                claim = motion_actions.check_numeric_grounding(w, "A", text)
                self.assertIsNotNone(claim)
                self.assertEqual(claim["code"], "NUMERIC_GROUNDING_ERROR")

    def test_a_false_comma_troop_count_is_refused(self):
        w = grounding_world()
        self.assertIsNotNone(motion_actions.check_numeric_grounding(
            w, "A", "We have 50,000 soldiers under arms and can hold the border."))
        self.assertIsNone(motion_actions.check_numeric_grounding(
            w, "A", "We have 28,000 soldiers under arms and can hold the border."))


class UnionTroopsAreJudgedByTheUnion(unittest.TestCase):
    """MO4: a troop figure is checked against the force it is about, not against our own army."""

    def check(self, w, text):
        return motion_actions.check_numeric_grounding(w, "D", text)

    def test_a_true_union_figure_is_grounded_by_the_union_figure(self):
        w = grounding_world()
        truth = union_army(w)
        self.assertEqual(truth, 95000)
        self.assertIsNone(self.check(w, f"Army intelligence puts the Solvaran Union at {truth} troops in the field."))
        self.assertIsNone(self.check(w, f"Army intelligence puts the Solvaran Union at {truth:,} troops in the field."))
        self.assertIsNone(self.check(w, f"The Solvaran Union has {truth:,} soldiers under arms."))

    def test_a_false_union_figure_is_refused_even_when_it_is_close_to_our_army(self):
        # 30,000 is 2,000 from our 28,000, so judged against our army it passed; the Union has 95,000.
        claim = self.check(grounding_world(), "The Solvaran Union has 30,000 soldiers under arms.")
        self.assertIsNotNone(claim)
        self.assertEqual(claim["metric"], "union_forces")

    def test_the_union_figure_is_accepted_inside_the_range_the_reports_gave(self):
        w = grounding_world()
        report = ("PRIVATE OFFICE INFORMATION\n- [R1-ARM] Army intelligence estimates Solvaran Union field strength "
                  "at 78,147-107,917 troops. Confidence: medium.")
        with mock.patch("karamaniya.military.union_army", return_value=30000), \
                mock.patch.object(intelligence, "office_context", lambda *a, **k: report):
            # Far from the truth (30,000) but inside the reported range: grounded by the holder's report.
            self.assertIsNone(self.check(w, "Army intelligence puts the Solvaran Union at 100,000 troops."))
            # Outside the reported range and far from the truth: refused.
            self.assertIsNotNone(self.check(w, "Army intelligence puts the Solvaran Union at 60,000 troops."))

    def test_veleria_dorsania_and_the_enemy_are_the_union_for_this_purpose(self):
        w = grounding_world()
        truth = union_army(w)
        for subject in ("Veleria", "Dorsania", "The enemy"):
            with self.subTest(subject=subject):
                # Plain digits: a comma figure is checked in the same way, but these must fail on the old parser.
                self.assertIsNone(self.check(w, f"{subject} has {truth} soldiers under arms."))

    def test_a_mixed_sentence_judges_each_figure_by_its_own_side(self):
        w = grounding_world()
        truth = union_army(w)
        self.assertIsNone(self.check(w, f"We have 28000 soldiers against the Solvaran Union's {truth} troops."))

    def test_money_beside_union_troops_is_not_a_troop_figure(self):
        w = grounding_world()
        truth = union_army(w)
        self.assertIsNone(self.check(
            w, f"The Solvaran Union has {truth} troops and holds 2000000 gold in its treasury."))


class OpinionWordsDoNotSwitchTheCheckOff(unittest.TestCase):
    """MO5: an opinion word beside a stated figure does not make the figure unchecked."""

    def test_a_false_figure_beside_an_opinion_word_is_refused(self):
        w = grounding_world()           # inflation 0%
        for text in ("Inflation of 9% is alarming.", "Inflation is alarming at 9%."):
            with self.subTest(text=text):
                claim = motion_actions.check_numeric_grounding(w, "A", text)
                self.assertIsNotNone(claim)
                self.assertEqual(claim["code"], "NUMERIC_GROUNDING_ERROR")

    def test_a_true_figure_beside_an_opinion_word_is_accepted(self):
        self.assertIsNone(motion_actions.check_numeric_grounding(grounding_world(), "A",
                                                                 "Inflation of 0% is alarming."))

    def test_an_opinion_with_no_figure_is_not_checked(self):
        self.assertIsNone(motion_actions.check_numeric_grounding(grounding_world(), "A",
                                                                 "Inflation is alarming."))


class PerHundredScale(unittest.TestCase):
    """MO6: a figure on the 0-100 scale, written x/100, is x percent and is checked like one."""

    def test_x_over_100_is_read_as_x_percent(self):
        for text in ("Unrest is 90/100 and rising.", "Unrest is 90 / 100 and rising."):
            with self.subTest(text=text):
                numbers = motion_actions._numbers_in(text)
                self.assertEqual([(n["value"], n["unit"]) for n in numbers], [(0.9, "%")])

    def test_a_false_per_hundred_figure_is_refused_as_the_percent_is(self):
        w = grounding_world()           # unrest about 9%
        claim = motion_actions.check_numeric_grounding(w, "A", "Unrest is 90/100 and rising.")
        self.assertIsNotNone(claim)
        self.assertEqual((claim["code"], claim["metric"]), ("NUMERIC_GROUNDING_ERROR", "unrest"))

    def test_a_true_per_hundred_figure_is_accepted(self):
        self.assertIsNone(motion_actions.check_numeric_grounding(grounding_world(), "A",
                                                                 "Unrest is 9/100 and falling."))


class SourceFiguresSupportTheirOwnMetric(unittest.TestCase):
    """MO7: a source figure supports a claim only when it appears in a sentence about the claimed metric."""

    def check(self, source: str, claim: str):
        w = grounding_world()           # inflation 0%
        with mock.patch.object(intelligence, "office_context", lambda *a, **k: source):
            return motion_actions.check_numeric_grounding(w, "A", claim)

    def test_a_food_figure_does_not_support_a_claim_about_inflation(self):
        claim = self.check("Grain board forecast: food supply next month expected to cover 40% of needs.",
                           "Inflation is 40%.")
        self.assertIsNotNone(claim)
        self.assertEqual(claim["metric"], "inflation")

    def test_an_inflation_figure_supports_the_same_claim(self):
        self.assertIsNone(self.check("Treasury forecast: inflation over the next six months expected at 40%.",
                                     "Inflation is 40%."))


class BareFiguresBesideARatioWord(unittest.TestCase):
    """MO8: a bare figure beside a ratio metric's word is percentage points; counts and changes are not."""

    def test_a_bare_figure_beside_a_ratio_word_is_checked_as_a_percent(self):
        w = grounding_world()           # approval about 48%
        for text in ("Approval is 95.", "Approval has reached 95 and is still climbing."):
            with self.subTest(text=text):
                claim = motion_actions.check_numeric_grounding(w, "A", text)
                self.assertIsNotNone(claim)
                self.assertEqual((claim["code"], claim["metric"]), ("NUMERIC_GROUNDING_ERROR", "approval"))

    def test_a_true_bare_figure_is_accepted(self):
        self.assertIsNone(motion_actions.check_numeric_grounding(grounding_world(), "A", "Approval is 48."))

    def test_counts_changes_and_identifiers_are_not_percentages(self):
        w = grounding_world()
        for text in ("Approval rose by 5 points this quarter.",
                     "A poll of 12 respondents backed the plan.",
                     "Inflation in Month 12 will stay low.",
                     "Unemployment in 3 provinces is high."):
            with self.subTest(text=text):
                self.assertIsNone(motion_actions.check_numeric_grounding(w, "A", text))

    def test_a_bare_figure_that_belongs_to_another_metric_is_not_read_as_its_percent(self):
        # 40 is approval's, and 40% is a true approval figure; read as unrest's it would be refused.
        self.assertIsNone(motion_actions.check_numeric_grounding(grounding_world(), "A",
                                                                 "Unrest and approval are 40."))


class GroundingKeywordGaps(unittest.TestCase):
    """MO22: a precise claim is checked whatever words name its metric, not only the listed ones."""

    def test_a_price_rise_is_checked_however_it_is_worded(self):
        w = grounding_world()           # inflation 0%
        for text in ("Inflation climbed 9% this year.",
                     "Consumer prices climbed 9% this year.",
                     "Prices are up 9% on last year.",
                     "Our cost of living rose 9% this year."):
            with self.subTest(text=text):
                claim = motion_actions.check_numeric_grounding(w, "A", text)
                self.assertIsNotNone(claim)
                self.assertEqual(claim["metric"], "inflation")

    def test_the_other_metrics_are_checked_under_their_new_words(self):
        w = grounding_world()
        cases = (("unemployment", "Joblessness is {p}%."),
                 ("approval", "Public support is {p}%."),
                 ("unrest", "Public anger is {p}%."),
                 ("hunger", "Malnutrition affects {p}% of the population."),
                 ("army_readiness", "Combat effectiveness is {p}%."))
        for key, template in cases:
            truth = motion_actions._grounding_truth(w, key)
            far = truth + 0.5 if truth + 0.5 <= 1 else truth - 0.5
            with self.subTest(metric=key):
                claim = motion_actions.check_numeric_grounding(w, "A", template.format(p=round(far * 100)))
                self.assertIsNotNone(claim)
                self.assertEqual(claim["metric"], key)

    def test_a_true_figure_under_a_new_word_is_accepted(self):
        w = grounding_world()
        approval = motion_actions._grounding_truth(w, "approval")
        self.assertIsNone(motion_actions.check_numeric_grounding(
            w, "A", f"Public support is {round(approval * 100)}%."))


PROTEST = ("Issue a formal protest to the Union over the Month 5 shooting on the eastern border. Demand a joint "
           "fact-finding investigation with published findings within one month and a mutual stand-down of patrols "
           "near the incident sector pending findings.")


def protested_world():
    """The council's protest to the Union in Month 5, passed: the cable of engine 18 is then written for the head."""
    from karamaniya import foreign, politics
    w = new_world(5, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    w.month = 4
    politics.apply_motion(w, {"type": "diplomacy", "subject": "diplomatic_protest", "value": "", "text": PROTEST,
                              "votes": {m: "yes" for m in "ABCDE"},
                              "action": {"action_type": "diplomatic_protest",
                                         "target": motion_actions.SOLVARAN_UNION}})
    return w


class EngineEighteenReportsCitedTruthfully(unittest.TestCase):
    """The engine-18 report subjects print lo-hi/100 or lo-hi%. Quoted as the report prints them, and with the report
    among the delegate's sources, they must be grounded."""

    def quoted(self, w, mid: str, claim: str, report: str):
        source = f"PRIVATE OFFICE INFORMATION\n- {report}"
        with mock.patch.object(intelligence, "office_context", lambda *a, **k: source):
            return motion_actions.check_numeric_grounding(w, mid, claim)

    def test_the_foreign_reading_cable_quoted_whole_is_grounded(self):
        from karamaniya import intelligence as intel
        w = protested_world()
        cable = next(r for r in intel.generate(w) if r["office"] == "head" and r["subject"] == "foreign_reading")
        self.assertIsNone(self.quoted(w, "A", cable["text"], cable["text"]))

    def test_the_foreign_reading_range_in_the_delegates_words_is_grounded(self):
        from karamaniya import intelligence as intel, resolve
        w = protested_world()
        cable = next(r for r in intel.generate(w) if r["office"] == "head" and r["subject"] == "foreign_reading")
        word = next(label for floor, label in resolve.WORDS if cable["estimate"] / 100 >= floor)
        claim = f"Veleria reads us as {word} ({cable['low']:.0f}-{cable['high']:.0f}/100)."
        self.assertIsNone(self.quoted(w, "B", claim, cable["text"]))

    def test_the_incident_attribution_report_quoted_is_grounded(self):
        w = grounding_world()
        for step in (0, 1):
            with self.subTest(forensic_step=step):
                text = intelligence.render(w, {"subject": "incident_attribution", "low": 40.0, "high": 60.0,
                                               "estimate": 50.0, "confidence": "low", "forensic_step": step})
                self.assertIsNone(self.quoted(w, "D", text, text))
                self.assertIsNone(self.quoted(w, "D", "The evidence puts the chance that Union soldiers fired "
                                                       "at 40-60%.", text))

    def test_the_officers_plot_report_quoted_is_grounded(self):
        w = grounding_world()
        text = intelligence.render(w, {"subject": "officers_plot", "low": 40.0, "high": 60.0, "estimate": 50.0,
                                       "confidence": "low"})
        self.assertIsNone(self.quoted(w, "C", text, text))
        self.assertIsNone(self.quoted(w, "C", "The plot is assessed at 40-60/100 of what it would need to act.", text))


if __name__ == "__main__":
    unittest.main()
