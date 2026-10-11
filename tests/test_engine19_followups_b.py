"""Engine 19 follow-ups (B): the gaps the merged audit fixes left behind.

Each class pins one follow-up to the audit fix it completes: a percent reading stored once at intake (MO11), programme
motions that renormalise once and refuse a value out of range (CO11, MO11), an adopted amendment shown word-limited
(TO2), an unreadable answer counted in the run's errors (CO2), trust kept at full precision (AG1), one reading of a
food threshold (MO9), a false warning filed in its own month (IN-M1), and a resumed world's opposition reading its
first month (PO9).
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import actions, commitments, dilemmas, errors, intelligence, politics, scenarios  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def set_policy(lever, value, text):
    return {"type": "set_policy", "subject": lever, "value": value, "text": text, "proposer": "A"}


class PercentReadingStoredOnceAtIntake(unittest.TestCase):
    """MO11: a share the motion's own text writes with a percent sign is stored as that percent at intake, so every
    reader after intake parses the figure validation and execution read."""

    def setUp(self):
        self.w = new_world(1, 36)

    def test_the_stored_value_is_the_percent_the_text_writes(self):
        mo = actions.normalize_motion_v2(self.w, set_policy("military", "0.8",
                                                            "raise military spending to 0.8% of output"))
        self.assertEqual(mo["value"], "0.8%")

    def test_every_reader_parses_the_stored_value_as_point_zero_zero_eight(self):
        mo = actions.normalize_motion_v2(self.w, set_policy("military", "0.8",
                                                            "raise military spending to 0.8% of output"))
        self.assertEqual(politics.parse_lever("military", mo["value"]), 0.008)

    def test_the_percent_reading_is_what_the_motion_executes(self):
        mo = actions.normalize_motion_v2(self.w, set_policy("military", "0.8",
                                                            "raise military spending to 0.8% of output"))
        self.assertIsNone(politics.validate_motion_detail(self.w, mo))
        politics.apply_motion(self.w, mo)
        self.assertEqual(self.w.policy.military, 0.008)
        self.assertEqual(self.w.const.directives["military"], 0.008)

    def test_without_a_percent_sign_the_value_is_kept_and_validation_refuses_it(self):
        mo = actions.normalize_motion_v2(self.w, set_policy("military", "0.8",
                                                            "raise military spending to 0.8 of output"))
        self.assertEqual(mo["value"], "0.8")
        detail = politics.validate_motion_detail(self.w, mo)
        self.assertEqual(detail["reason_code"], "VALUE_OUT_OF_RANGE")


def programme(measures):
    """A programme motion that passed, carrying its package as the delegate wrote it."""
    return {"type": "program", "subject": "army", "text": "Redeploy the army.", "proposer": "A",
            "action": {"measures": [{"lever": lever, "value": value} for lever, value in measures]}}


def run_programme(measures):
    """The deployment shares after a programme's measures are validated and applied to a fresh world."""
    w = new_world(1, 36)
    mo = programme(measures)
    if politics.validate_motion_detail(w, mo) is None:
        politics.apply_motion(w, mo)
    return w


class ProgrammeSharesNormalisedOnce(unittest.TestCase):
    """CO11: a programme's deployment shares are set first and normalised once, after all of them, as an office's
    orders are, so the order its measures are written in changes nothing."""

    def test_two_orders_of_the_same_measures_give_the_same_shares(self):
        measures = [("deploy_capital", "0.5"), ("deploy_north", "0.3")]
        forward = run_programme(measures).mil.deploy
        backward = run_programme(list(reversed(measures))).mil.deploy
        self.assertEqual(set(forward), set(backward))
        for key in forward:
            with self.subTest(share=key):
                self.assertAlmostEqual(forward[key], backward[key], places=12)

    def test_the_shares_sum_to_one_after_the_programme(self):
        w = run_programme([("deploy_capital", "0.5"), ("deploy_north", "0.3")])
        self.assertAlmostEqual(sum(w.mil.deploy.values()), 1.0, places=12)


class ProgrammeMeasuresInRange(unittest.TestCase):
    """MO11: a programme measure outside its setting's range is refused at validation, naming the measure, as a
    set_policy value is. It used to be clamped to the bound with no word, so an austerity package written as
    'military 0.8' set the budget to 20% and said nothing."""

    def setUp(self):
        self.w = new_world(1, 36)

    def test_a_measure_outside_its_range_is_refused_and_names_the_measure(self):
        mo = programme([("military", "0.8"), ("welfare", "0.03")])
        detail = politics.validate_motion_detail(self.w, mo)
        self.assertEqual(detail["reason_code"], "VALUE_OUT_OF_RANGE")
        self.assertEqual(detail["related_state"]["lever"], "military")
        self.assertIn("military", detail["explanation"])

    def test_a_refused_programme_sets_nothing(self):
        mo = programme([("military", "0.8"), ("welfare", "0.03")])
        self.assertIsNotNone(politics.validate_motion_detail(self.w, mo))
        before = (self.w.policy.military, self.w.policy.welfare, dict(self.w.const.directives))
        politics.apply_motion(self.w, mo)
        self.assertEqual((self.w.policy.military, self.w.policy.welfare, dict(self.w.const.directives)), before)

    def test_a_programme_inside_its_ranges_is_adopted_as_written(self):
        mo = programme([("military", "0.05"), ("welfare", "0.03")])
        self.assertIsNone(politics.validate_motion_detail(self.w, mo))
        politics.apply_motion(self.w, mo)
        self.assertEqual(self.w.policy.military, 0.05)
        self.assertEqual(self.w.policy.welfare, 0.03)


class AdoptedAmendmentShownAsStored(unittest.TestCase):
    """TO2: the event colleagues read shows the stored, word-limited amendment with its [cut] marker. It used to be
    sliced at 120 characters, so a clause was cut mid-word with no marker."""

    def setUp(self):
        self.w = new_world(1, 36)

    def test_the_event_shows_the_stored_text_with_its_cut_marker(self):
        long_text = " ".join(f"clause{i}" for i in range(1, 161))
        mo = actions.normalize_motion_v2(self.w, {"type": "amend", "text": long_text, "proposer": "A"})
        self.assertTrue(mo["text"].endswith(actions.CUT_MARK))
        result = politics.apply_motion(self.w, mo)
        self.assertEqual(result, "amendment adopted: " + mo["text"])
        self.assertTrue(result.endswith("clause120 [cut]"), result[-40:])

    def test_a_short_amendment_is_shown_whole(self):
        mo = actions.normalize_motion_v2(self.w, {"type": "amend", "text": "The election shall be held in Month 36.",
                                                  "proposer": "A"})
        self.assertEqual(politics.apply_motion(self.w, mo), "amendment adopted: The election shall be held in Month 36.")


def broken_normaliser(world, mid, data, dm_quota):
    """A normaliser with an engine bug: it answers an empty reply and raises on any real one."""
    if data is None:
        return actions.normalize_session_v2(world, mid, None, dm_quota)
    raise RuntimeError("boom")


class UnreadableAnswerIsCounted(unittest.TestCase):
    """CO2: an answer that cannot be read is a problem for its delegate, and it is also an entry in the run's error
    ledger, so an engine bug shows in the error counts rather than only in one answer's problem list."""

    def setUp(self):
        self.w = new_world(1, 36)

    def test_the_answer_is_still_read_as_empty_with_its_problem(self):
        out, problems = actions.read_answer(broken_normaliser, self.w, "B", {"statement": "x"}, 3)
        self.assertEqual(problems, ["answer could not be read (RuntimeError: boom)"])
        self.assertEqual(out["statement"], "")

    def test_it_is_recorded_in_the_run_errors_with_the_member_and_the_normaliser(self):
        actions.read_answer(broken_normaliser, self.w, "B", {"statement": "x"}, 3)
        self.assertEqual(errors.summary(self.w)["by_code"], {"ANSWER_UNREADABLE": 1})
        [entry] = errors.since(self.w)
        self.assertEqual(entry["code"], "ANSWER_UNREADABLE")
        self.assertEqual(entry["details"]["member"], "B")
        self.assertEqual(entry["details"]["normaliser"], "broken_normaliser")
        self.assertIn("boom", entry["message"])

    def test_the_code_is_registered_as_an_action_warning(self):
        self.assertTrue(errors.is_registered("ANSWER_UNREADABLE"))
        entry = errors.describe("ANSWER_UNREADABLE")
        self.assertEqual((entry["category"], entry["severity"]), ("action", "warning"))

    def test_a_good_answer_records_nothing(self):
        actions.read_answer(actions.normalize_session_v2, self.w, "B", {"statement": "x"}, 3)
        self.assertEqual(errors.summary(self.w)["total"], 0)


class TrustKeepsItsPrecision(unittest.TestCase):
    """AG1: a relationship's trust keeps full precision. The exposure of a steered office's contracts takes six points
    off the trust of each colleague, and that change used to be rounded to a tenth, which the AG1 fix removed everywhere
    else."""

    def test_exposure_takes_six_points_off_trust_without_rounding(self):
        from karamaniya import self_dealing
        w = new_world(1, 36)
        members = w.active_members()
        mid = members[0].id
        colleague = members[1]
        colleague.agent_state = colleague.agent_state or {"seeded": True}
        colleague.relationships[mid] = {"trust": 50.04}
        self_dealing.state(w)[mid] = {"months": 3, "crowns": 1e6, "first_month": 0, "offices": ["treasury"]}
        self_dealing._expose(w, mid, "treasury", "press")
        self.assertAlmostEqual(colleague.relationships[mid]["trust"], 44.04, places=9)

    def test_a_small_trust_value_is_not_rounded_to_a_tenth(self):
        from karamaniya import self_dealing
        w = new_world(1, 36)
        members = w.active_members()
        mid = members[0].id
        colleague = members[1]
        colleague.agent_state = colleague.agent_state or {"seeded": True}
        colleague.relationships[mid] = {"trust": 6.123}
        self_dealing.state(w)[mid] = {"months": 3, "crowns": 1e6, "first_month": 0, "offices": ["treasury"]}
        self_dealing._expose(w, mid, "treasury", "press")
        self.assertAlmostEqual(colleague.relationships[mid]["trust"], 0.123, places=9)


class OneReadingOfAThreshold(unittest.TestCase):
    """MO9: a promise's condition reads a figure with no unit as motion_actions.canonical_metric_value reads it, so
    food coverage above 1 is a ratio (1.05 is 105%) and only 10 or more is a percent. A percent sign is still /100, and
    the money thresholds read as they always did."""

    def read(self, text):
        return commitments.parse_condition(text)

    def test_food_coverage_above_one_point_oh_five_is_a_ratio(self):
        self.assertEqual(self.read("keep food coverage above 1.05"),
                         {"metric": "food_ratio", "operator": ">=", "value": 1.05})

    def test_food_coverage_above_95_is_ninety_five_per_cent(self):
        self.assertEqual(self.read("keep food coverage above 95"),
                         {"metric": "food_ratio", "operator": ">=", "value": 0.95})

    def test_food_coverage_with_a_percent_sign_is_divided_by_a_hundred(self):
        self.assertEqual(self.read("keep food coverage above 105%"),
                         {"metric": "food_ratio", "operator": ">=", "value": 1.05})

    def test_a_month_count_after_a_percent_metric_reads_as_it_did(self):
        """A figure followed by 'months' carries no scale, so it reads as a figure with no unit, as it always has."""
        self.assertEqual(self.read("approval above 40 months")["value"], 0.4)
        self.assertEqual(self.read("inflation at most 6 months")["value"], 0.06)
        self.assertEqual(self.read("keep food coverage above 1.05 months")["value"], 1.05)

    def test_inflation_at_most_6_is_six_per_cent(self):
        self.assertEqual(self.read("inflation at most 6"), {"metric": "inflation", "operator": "<=", "value": 0.06})

    def test_approval_above_40_is_forty_per_cent(self):
        self.assertEqual(self.read("approval above 40"), {"metric": "approval", "operator": ">=", "value": 0.4})

    def test_money_thresholds_read_as_they_did(self):
        self.assertEqual(self.read("keep reserves above 90")["value"], 90_000_000.0)
        self.assertEqual(self.read("keep reserves above 50 million")["value"], 50_000_000.0)
        self.assertEqual(self.read("arrears at most 5m")["value"], 5_000_000.0)
        self.assertEqual(self.read("army arrears remain zero"), {"metric": "army_arrears", "operator": "<=", "value": 0.0})


def urgent_reports(w):
    return [r for r in intelligence.state(w)["reports"] if "URGENT" in r.get("text", "")]


class FalseWarningFiledInItsMonth(unittest.TestCase):
    """IN-M1: scenario C forces its false warning into the active issues, so its urgent office reports used to be
    filed at the issue's first effect, after that month's session. They are filed when the scenario sets the issue,
    as dilemmas.generate files them, and the month's ordinary reports are still made."""

    def setUp(self):
        self.w = new_world(1, 36)
        self.w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})

    def test_the_urgent_reports_are_filed_for_the_issues_month_when_the_scenario_sets_it(self):
        scenarios.apply(self.w, "C")
        reports = urgent_reports(self.w)
        self.assertEqual(sorted((r["office"], r["month"]) for r in reports), [("army", 0), ("head", 0)])

    def test_the_issue_is_marked_filed_so_its_first_effect_does_not_file_them_again(self):
        scenarios.apply(self.w, "C")
        [issue] = [i for i in dilemmas.state(self.w)["active"] if i["kind"] == "false_warning"]
        self.assertTrue(issue.get("filed"))
        dilemmas.apply_ongoing(self.w)
        self.assertEqual(len(urgent_reports(self.w)), 2)

    def test_the_month_still_makes_its_other_reports(self):
        scenarios.apply(self.w, "C")
        new = intelligence.generate(self.w)
        self.assertTrue(new, "generate made no reports for the month")
        self.assertFalse([r for r in new if "URGENT" in r.get("text", "")])
        self.assertEqual(len(urgent_reports(self.w)), 2)


def resumed_world(previous_military=0.03, now_military=0.09, row_month=None):
    """A world resumed at Month 10 from before engine 18: it has no opposition record, and its history holds the row
    the month before was written with (engine.snapshot), with the military share as it stood then."""
    from karamaniya import engine
    w = new_world(1, 36)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    if row_month is not None:
        w.month = row_month
        w.policy.military = previous_military
        engine.snapshot(w)
    w.institutions.pop("opposition", None)
    w.month = 9
    w.policy.military = now_military
    return w


def opposition_acts(w) -> list:
    from karamaniya import opposition
    opposition.monthly(w)
    return [x["act"] for x in opposition.state(w)["said"]]


class ResumedWorldOpposition(unittest.TestCase):
    """PO9: a world resumed from before engine 18 has no record of the settings it last saw. Its first month is read
    against the history row the month before wrote, so an army build-up made in that month is reported. With no such row
    there is no earlier setting to read, and nothing is reported (the BeforeTheFeature test in engine 18 pins that)."""

    def test_a_resumed_world_reports_the_army_build_up_of_its_first_month(self):
        from karamaniya import opposition
        w = resumed_world(row_month=8)
        self.assertEqual(len(w.history), 1)
        self.assertIn("arming", opposition_acts(w))
        union = [x["text"] for x in opposition.state(w)["said"] if x["party"] == "Union Party"]
        self.assertEqual(union, ["The Union Party says the government's army build-up in Month 10 is a provocation "
                                 "that brings war closer."])

    def test_a_resumed_world_with_no_history_row_reports_nothing(self):
        w = resumed_world(row_month=None)
        self.assertEqual(w.history, [])
        self.assertEqual(opposition_acts(w), [])

    def test_a_row_that_is_not_the_previous_months_is_not_read(self):
        w = resumed_world(row_month=3)
        self.assertNotIn("arming", opposition_acts(w))

    def test_a_ban_in_force_before_the_resume_is_not_this_months_act(self):
        """The history row does not record the parties setting, so it is read as it stands: a ban the world already had
        is not reported as this month's act."""
        w = resumed_world(row_month=8)
        w.const.parties = "ban_opposition"
        self.assertNotIn("ban", opposition_acts(w))


if __name__ == "__main__":
    unittest.main()
