"""World engine 17: the General Staff asks for soldiers, and the services resent being ignored (staff.py).

In run 20261010-070501-seed1 the army stayed at 28,000 for nine months with recruitment and mobilization both
"none", while the Union grew from 95,000 to 102,600. Nothing in the world asked for anything, so ignoring the
threat cost nothing until an invasion. These tests pin the request, the office report that carries it to the
Army minister, the grievance that ignoring it builds and an answer eases, and the budget cuts the services
resent. No delegate is told what to decide: the world reacts to what the government does.
"""
import copy
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import agents, engine, foreign, intelligence, military, ministries, staff  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

OLD_ARMY = ("union_strength", "union_intent", "officer_loyalty", "readiness", "net_assessment")


def world(seed: int = 5, version: int | None = None):
    w = new_world(seed, 36, agent_architecture_version=version)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    for m in w.members:                      # the audiences a seat carries once its offices are set (agents.py)
        m.agent_state["constituencies"] = agents.audiences_for(w, m.id)
    return w


def month(w, n=1):
    for _ in range(n):
        engine.begin_month(w)
        engine.step(w)


def army_reports(w):
    return {r["subject"]: r for r in intelligence.generate(w) if r["office"] == "army"}


def senior_officers(w):
    return w.holder("army").agent_state["constituencies"]["senior officers"]


class TheRequest(unittest.TestCase):
    def test_a_gap_of_ten_thousand_is_asked_for_with_partial_recruitment(self):
        w = world()
        req = staff.request(w)
        self.assertEqual(req["extra"], 10_000)                 # 95,000 / 2.5 = 38,000, less our 28,000
        self.assertEqual(req["target"], 38_000)
        self.assertEqual(req["recruitment"], "partial")
        self.assertAlmostEqual(req["monthly_cost"], 10_000 * military.ARMY_COST * w.econ.cpi)
        self.assertAlmostEqual(req["cost_share"], req["monthly_cost"] / w.econ.gdp_nominal, places=4)

    def test_it_names_the_front_the_neighbours_would_reach_first(self):
        w = world()
        req = staff.request(w)
        fronts = military.net_assessment(w)["fronts"]
        soonest = min((f["worst_months"], name) for name, f in fronts.items() if f["worst_months"] is not None)
        self.assertEqual((req["months"], req["front"]), soonest)
        self.assertEqual(req["region"], fronts[req["front"]]["region"])

    def test_a_smaller_gap_asks_for_volunteers_and_a_tiny_one_asks_for_nothing(self):
        w = world()
        w.mil.army.size = 36_000
        req = staff.request(w)
        self.assertEqual((req["extra"], req["recruitment"]), (2_000, "volunteer"))
        w.mil.army.size = 37_000
        self.assertIsNone(staff.request(w))                    # 1,000 is under MIN_REQUEST

    def test_no_request_once_the_army_is_big_enough(self):
        w = world()
        w.mil.army.size = 40_000
        self.assertIsNone(staff.request(w))

    def test_reservists_already_called_up_count_as_ours(self):
        w = world()
        military.mobilization_of(w).called_up = 20_000         # 15% effective before they serve: 3,000
        self.assertEqual(staff.request(w)["extra"], 7_000)


class TheReport(unittest.TestCase):
    def test_the_army_minister_gets_it_as_the_sixth_army_report(self):
        w = world()
        reports = army_reports(w)
        self.assertEqual(list(reports), ["union_strength", "union_intent", "officer_loyalty", "readiness",
                                         "net_assessment", "staff_request"])
        self.assertEqual(reports["staff_request"]["id"], f"R{w.month + 1}-ARM6")

    def test_the_text_says_what_is_asked_what_it_costs_and_when_the_front_goes(self):
        w = world()
        req = staff.request(w)
        text = army_reports(w)["staff_request"]["text"]
        self.assertTrue(text.startswith(
            f"General Staff request: to keep the {w.names['union']} to 2.5 soldiers for each of ours, the army needs "
            "about 10,000 more: an army target of 38,000 with recruitment at least partial."), text)
        self.assertIn(f"Paying them would cost about {req['monthly_cost'] / 1e6:.1f}M crowns a month", text)
        self.assertIn(f"the {req['region']} to fall in about {req['months']} month"
                      f"{'' if req['months'] == 1 else 's'} to the most the neighbours could send.", text)
        self.assertTrue(text.endswith("Confidence: high."), text)

    def test_it_is_the_staffs_own_position_not_an_estimate_and_draws_no_error(self):
        w = world()
        with mock.patch.object(intelligence, "_error", wraps=intelligence._error) as draw:
            r = army_reports(w)["staff_request"]
        drawn = [c.args[2] for c in draw.call_args_list]
        self.assertIn("union_strength", drawn)                 # the other army reports do draw
        self.assertNotIn("staff_request", drawn)
        self.assertEqual(r["estimate"], 10_000)
        self.assertEqual((r["low"], r["high"], r["truth"]), (r["estimate"], r["estimate"], r["estimate"]))
        self.assertEqual((r["error"], r["accurate"], r["confidence"]), ("none", True, "high"))
        self.assertIsNone(r["proposition"])

    def test_the_minister_holds_it_and_the_rest_of_the_council_does_not(self):
        w = world()
        report = army_reports(w)["staff_request"]
        self.assertIn(report["text"], intelligence.office_context(w, "D"))
        self.assertIn(report["id"], [r["id"] for r in intelligence.reports_for(w, "D")])
        self.assertNotIn(report["text"], intelligence.office_context(w, "A"))

    def test_the_minister_can_share_it_like_any_report(self):
        w = world()
        rid = army_reports(w)["staff_request"]["id"]
        accepted = intelligence.share(w, "D", [{"report_id": rid, "with": "council"}], "session")
        self.assertEqual([x["subject"] for x in accepted], ["staff_request"])
        self.assertIn("staff_request", [x["subject"] for x in intelligence.shared_with(w, "A")])

    def test_an_alarming_request_the_minister_keeps_back_is_withheld(self):
        w = world()
        staff.state(w)["army"]["unanswered"] = staff.ALARM_MONTHS
        intelligence.generate(w)
        flagged = intelligence.flag_withheld(w)
        self.assertIn("staff_request", [x["subject"] for x in flagged])

    def test_it_is_urgent_once_ignored_for_three_months_or_when_a_front_is_about_to_go(self):
        cases = {"fresh": (0, None), "ignored twice": (2, None), "ignored three months": (3, None),
                 "a front about to go": (0, 60_000.0)}
        for name, (unanswered, massed) in cases.items():
            with self.subTest(name):
                w = world()
                staff.state(w)["army"]["unanswered"] = unanswered
                if massed:
                    w.dip.border_forces = {"veleria": {"north": massed, "east": 0.0}}
                report = army_reports(w)["staff_request"]
                self.assertEqual(report["alarming"], name in ("ignored three months", "a front about to go"))

    def test_it_says_how_long_it_has_gone_unanswered_from_the_second_month(self):
        for unanswered in (1, 2):
            with self.subTest(unanswered=unanswered):
                w = world()
                staff.state(w)["army"]["unanswered"] = unanswered
                text = army_reports(w)["staff_request"]["text"]
                self.assertEqual("The staff has made this request for 2 months without an answer." in text,
                                 unanswered == 2)


class ExistingReportsAreUntouched(unittest.TestCase):
    def test_the_five_older_army_reports_are_the_same_with_the_request_subject(self):
        w = world()
        without = copy.deepcopy(w)
        with mock.patch.dict(intelligence.SUBJECTS, {"army": OLD_ARMY}):
            before = {(r["office"], r["subject"]): r for r in intelligence.generate(without)}
        after = {(r["office"], r["subject"]): r for r in intelligence.generate(w)
                 if r["subject"] != "staff_request"}
        self.assertEqual({s for o, s in before if o == "army"}, set(OLD_ARMY))
        self.assertEqual(set(before), set(after))
        for key in before:
            for field in ("id", "estimate", "low", "high", "error", "text"):
                self.assertEqual(after[key][field], before[key][field], (key, field))


class IgnoredThenAnswered(unittest.TestCase):
    def test_the_grievance_starts_in_the_second_unanswered_month(self):
        w = world()
        month(w)
        self.assertEqual(staff.unanswered(w), 1)
        self.assertEqual(ministries.grievance(w, "army"), 0.0)
        month(w)
        self.assertEqual(staff.unanswered(w), 2)
        self.assertAlmostEqual(ministries.grievance(w, "army"), staff.GRIEVANCE, places=6)     # not yet decayed
        self.assertEqual(ministries.state(w)["army"]["log"][-1]["reason"],
                         "the government leaving the General Staff's request for 10,000 more soldiers unanswered")

    def test_each_unanswered_month_from_the_second_costs_the_senior_officers_support(self):
        w = world()
        senior_officers(w)["support_for_delegate"] = .5
        staff.monthly(w)
        self.assertEqual(senior_officers(w)["support_for_delegate"], .5)
        staff.monthly(w)
        self.assertAlmostEqual(senior_officers(w)["support_for_delegate"], .49, places=6)
        staff.monthly(w)
        self.assertAlmostEqual(senior_officers(w)["support_for_delegate"], .48, places=6)
        senior_officers(w)["support_for_delegate"] = .005
        staff.monthly(w)
        self.assertEqual(senior_officers(w)["support_for_delegate"], 0.0)

    def test_an_army_target_that_covers_the_gap_answers_it_and_soothes_the_grievance(self):
        w = world()
        month(w, 2)
        self.assertGreater(ministries.grievance(w, "army"), 0.0)
        w.policy.army_target = float(staff.request(w)["target"])
        w.policy.recruitment = "partial"
        month(w)
        self.assertEqual(staff.unanswered(w), 0)
        self.assertEqual(ministries.grievance(w, "army"), 0.0)

    def test_calling_up_reservists_answers_it_too(self):
        w = world()
        month(w, 2)
        w.policy.mobilization = "partial"
        month(w)
        self.assertEqual(staff.unanswered(w), 0)
        self.assertEqual(ministries.grievance(w, "army"), 0.0)

    def test_a_target_that_does_not_cover_the_gap_is_no_answer(self):
        w = world()
        month(w, 2)
        w.policy.army_target = 30_000.0        # covers 2,000 of the 10,000 gap
        w.policy.recruitment = "partial"
        month(w)
        self.assertEqual(staff.unanswered(w), 3)


class BudgetCuts(unittest.TestCase):
    def test_a_cut_to_the_military_budget_aggrieves_the_army(self):
        w = world()
        w.mil.army.size = 40_000               # no request, so only the cut can move the grievance
        staff.monthly(w)                       # the first month only notes the budget
        self.assertEqual(ministries.grievance(w, "army"), 0.0)
        w.policy.military -= .005
        staff.monthly(w)
        self.assertAlmostEqual(ministries.grievance(w, "army"), staff.CUT_GRIEVANCE, places=6)
        self.assertEqual(ministries.state(w)["army"]["log"][-1]["reason"], "a cut to the military budget")

    def test_a_cut_to_the_police_budget_aggrieves_the_interior_ministry(self):
        w = world()
        w.mil.army.size = 40_000
        staff.monthly(w)
        w.policy.police -= .005
        staff.monthly(w)
        self.assertAlmostEqual(ministries.grievance(w, "interior"), staff.CUT_GRIEVANCE, places=6)
        self.assertEqual(ministries.grievance(w, "army"), 0.0)

    def test_a_rise_or_a_small_trim_does_nothing(self):
        w = world()
        w.mil.army.size = 40_000
        staff.monthly(w)
        w.policy.military -= .001              # under the .002 that counts as a cut
        staff.monthly(w)
        w.policy.military += .01               # a rise
        staff.monthly(w)
        self.assertEqual(ministries.grievance(w, "army"), 0.0)
        self.assertEqual(ministries.grievance(w, "interior"), 0.0)


class VersionOneWorlds(unittest.TestCase):
    def test_nothing_is_asked_or_recorded_in_a_version_one_world(self):
        w = world(version=1)
        self.assertIsNone(staff.request(w))
        self.assertNotIn("staff_request", army_reports(w))
        w.policy.military -= .01
        staff.monthly(w)
        month(w, 2)
        self.assertNotIn("staff", w.institutions)
        self.assertEqual(ministries.grievance(w, "army"), 0.0)


if __name__ == "__main__":
    unittest.main()
