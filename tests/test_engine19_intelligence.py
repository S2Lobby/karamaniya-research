"""Engine 19: office reports, requests and costings (audit IN1, IN5, IN-M6, IN-L7, IN-M4, IN-L3, IN-M8, IN-L4, FO13).

Each test reproduces one audit proof script (the intelligence auditor's audit/ folder, poc_<n>) at the smallest size that
shows the bug, and checks the fix. The foreign auditor's poc_11 is the FO13 case.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import intelligence, military, tuning  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

OFFICES = {"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"}
MILITARY = {"id": "M3", "type": "set_policy", "subject": "military", "value": "0.08",
            "summary": "raise military spending to 8 percent of output"}
TAX = {"id": "M1", "type": "set_policy", "subject": "tax", "value": "0.25",
       "summary": "raise the tax rate to 25 percent"}


def world(seed=5, month=5):
    w = new_world(seed)
    w.const.offices.update(OFFICES)
    w.month = month
    return w


class CostingAskedLastMonth(unittest.TestCase):
    """IN1: a costing request is answered from the motion it named when it was made. The carry-over call at the start
    of the next month is given an empty motion list, and must not turn a named motion into 'no costable proposal'."""

    def test_a_named_motion_is_costed_at_the_carry_over_call(self):    # PoC 3
        w = world(5, 5)
        req = intelligence.request(w, "A", [{"topic": "costing", "motion_id": "M3"}], "session", [MILITARY])[0]
        self.assertEqual(req["motion"]["lever"], "military")
        self.assertEqual(req["motion"]["value"], "0.08")
        w.month = 6
        delivered = intelligence.answer_requests(w, {"treasury": .6}, [], "carry")
        self.assertEqual(len(delivered), 1)
        self.assertIn("costing of M3", delivered[0]["text"])
        self.assertNotIn("no costable proposal", delivered[0]["text"])

    def test_an_unnamed_costing_is_costed_from_the_proposal_on_the_table(self):    # PoC 4
        w = world(5, 10)
        intelligence.request(w, "C", [{"topic": "costing", "motion_id": ""}], "session", [TAX])
        w.month = 11
        delivered = intelligence.answer_requests(w, {"treasury": .6}, [], "carry")
        self.assertIn("costing of M1", delivered[0]["text"])

    def test_the_answer_costs_the_setting_the_request_was_made_against(self):
        w = world(5, 5)
        w.policy.military = 0.05
        intelligence.request(w, "A", [{"topic": "costing", "motion_id": "M3"}], "session", [MILITARY])
        w.policy.military = 0.08        # the motion is then voted through
        w.month = 6
        delivered = intelligence.answer_requests(w, {"treasury": .6}, [], "carry")
        self.assertIn("costs about", delivered[0]["text"])
        self.assertEqual(intelligence.state(w)["requests"][0]["motion"]["current"], 0.05)


class NamedMotionIsNeverReplaced(unittest.TestCase):
    """IN-M6: a request that names one motion is never answered with another motion's cost, sign flipped. A named motion
    that is not on the agenda is said so. A motion that reaches the agenda after the request is found when the session
    settles the agenda (IN1)."""

    def test_a_motion_not_on_the_table_is_not_replaced_by_another(self):     # PoC 17, the other way round
        w = world(5, 4)
        intelligence.request(w, "A", [{"topic": "costing", "motion_id": "M3"}], "session", [TAX])
        w.month = 5
        delivered = intelligence.answer_requests(w, {"treasury": .6}, [TAX], "session")
        self.assertEqual(len(delivered), 1)
        self.assertIn("not on the agenda", delivered[0]["text"])
        self.assertNotIn("costing of M1", delivered[0]["text"])

    def test_a_named_motion_on_the_table_keeps_its_own_cost_when_answered_later(self):    # PoC 17
        w = world(5, 5)
        intelligence.request(w, "A", [{"topic": "costing", "motion_id": "M3"}], "session", [MILITARY])
        w.month = 6
        delivered = intelligence.answer_requests(w, {"treasury": .6}, [TAX], "carry")
        self.assertIn("costing of M3", delivered[0]["text"])
        self.assertNotIn("M1", delivered[0]["text"])

    def test_a_motion_tabled_after_the_request_is_costed_once_the_agenda_is_known(self):
        w = world(5, 5)
        intelligence.request(w, "A", [{"topic": "costing", "motion_id": "M3"}], "session", [])
        intelligence.answer_requests(w, {"treasury": .3}, [MILITARY], "session")    # the same-month answer is deferred
        w.month = 6
        delivered = intelligence.answer_requests(w, {"treasury": .6}, [], "carry")
        self.assertIn("costing of M3", delivered[0]["text"])

    def test_a_motion_deferred_this_month_is_costed_too(self):
        w = world(5, 5)
        intelligence.request(w, "A", [{"topic": "costing", "motion_id": "M3"}], "session", [])
        w.agenda["deferred"] = [{**MILITARY, "deferred_month": 5}]
        intelligence.answer_requests(w, {"treasury": .3}, [], "session")
        w.month = 6
        delivered = intelligence.answer_requests(w, {"treasury": .6}, [], "carry")
        self.assertIn("costing of M3", delivered[0]["text"])


class RequestCapacity(unittest.TestCase):
    """IN-M4: a ministry answers its documented capacity in a month, however many calls answer in that month."""

    def test_the_carry_over_call_and_the_session_call_share_one_months_capacity(self):    # PoC 7
        w = world(3, 5)
        limit = int(tuning.get(w, "intelligence.request_capacity"))
        for mid in ("A", "B", "C"):
            intelligence.request(w, mid, [{"topic": "reserves"}, {"topic": "forecast"}], "session", [])
        w.month = 6
        carry = intelligence.answer_requests(w, {"treasury": .6}, [], "carry")
        session = intelligence.answer_requests(w, {"treasury": .6}, [], "session")
        self.assertEqual(limit, 3)
        self.assertEqual(len(carry) + len(session), limit)

    def test_a_request_deferred_to_next_month_uses_no_slot(self):    # PoC 8
        w = world(3, 4)
        older = [intelligence.request(w, mid, [{"topic": "reserves"}], "session", [])[0] for mid in ("A", "B", "C")]
        w.month = 5
        today = intelligence.request(w, "D", [{"topic": "forecast"}], "session", [])[0]
        intelligence.state(w)["requests"] = [today] + older      # the request met first is the one deferred
        # cap .3 is below the .55 that lets a same-month request be answered now, so today's request is deferred
        delivered = intelligence.answer_requests(w, {"treasury": .3}, [], "session")
        self.assertEqual(today["status"], "pending")
        self.assertEqual(len(delivered), 3)


class QuietDraws:
    """A draw source for one report: no error is made, and there is no noise. Only the arithmetic after the draws is tested."""

    def random(self):
        return .999

    def gauss(self, mu, sigma):
        return 0.0

    def uniform(self, low, high):
        return low

    def choice(self, seq):
        return seq[0]


class ReportRanges(unittest.TestCase):
    """IN-M8: a centre above the scale is clamped first, so the range is built around the scale, not collapsed to it."""

    def test_an_office_report_above_the_scale_keeps_a_range(self):    # PoC 1
        w = world(5, 3)
        truths = intelligence._truths(w)
        truths["union_intent"] = 125.0
        r = intelligence._report(w, QuietDraws(), "army", "union_intent", truths, dict(truths), {}, 2)
        self.assertEqual(r["confidence"], "low")
        self.assertEqual(r["estimate"], 100.0)
        self.assertEqual((r["low"], r["high"]), (80.0, 100.0))

    def test_a_requested_figure_above_the_scale_keeps_a_range(self):    # PoC 1, the request path
        w = world(5, 3)
        truths = intelligence._truths(w)
        truths["union_intent"] = 125.0
        q = {"id": "Qx", "month": 3, "from": "A", "office": "army", "topic": "threat", "motion_id": ""}
        text = intelligence._answer_text(w, q, truths, False, [], QuietDraws())
        self.assertNotIn("100-100%", text)
        self.assertIn("-100% probability", text)


class LensReportIds(unittest.TestCase):
    """IN-L4: a contested lens report's id does not depend on whether another report of its office was made this month."""

    def test_the_contested_reports_keep_their_ids_with_or_without_the_officers_plot(self):    # PoC 9
        checked = 0
        for seed in range(1, 13):
            for month in range(6):
                ids = {}
                for plotted in (False, True):
                    w = world(seed, month)
                    w.dip.war = False
                    w.dip.union_formed = True
                    with mock.patch("karamaniya.plots.detected", return_value=plotted):
                        reports = intelligence.generate(w)
                    ids[plotted] = {(r["office"], r["subject"]): r["id"] for r in reports if r.get("contested")}
                for key in ids[False].keys() & ids[True].keys():
                    checked += 1
                    self.assertEqual(ids[False][key], ids[True][key], (seed, month, key))
                if (seed, month) == (2, 0):
                    self.assertEqual(ids[True][("interior", "food_outlook")], "R1-INT6")
                    self.assertEqual(ids[False][("interior", "food_outlook")], "R1-INT6")
        self.assertGreater(checked, 0)


class UnionRiskReadAgainstTheRule(unittest.TestCase):
    """FO13: army intelligence's estimate of the Union's offensive risk is read against the Union's own war threshold
    (director.war_threshold, with the league alliance, the pact and the ceasefire), not a copy of it without those terms."""

    def test_the_risk_moves_with_the_threshold_the_rule_uses(self):    # foreign PoC 11
        w = world(5, 5)
        w.foreign["union"]["cohesion"] = 0.80
        w.dip.union_formed = True
        w.dip.league_alliance = True
        normal = intelligence.union_offensive_risk(w)
        with mock.patch("karamaniya.director.war_threshold", return_value=1e9):
            unreachable = intelligence.union_offensive_risk(w)
        self.assertLess(unreachable, normal)

    def test_a_world_with_no_foreign_state_still_has_a_risk(self):
        w = world(5, 5)
        w.foreign = {}
        self.assertIsInstance(intelligence.union_offensive_risk(w), float)


class SettingAlreadyInPlace(unittest.TestCase):
    """IN-L7: a switch already in the state it would be set to changes nothing, so it costs nothing. A switch that does
    change the state is costed as it was."""

    def test_a_switch_already_on_costs_nothing(self):    # PoC 23
        w = world(2, 5)
        for lever in ("rationing", "shipbuilding"):
            setattr(w.policy, lever, True)
            self.assertEqual(intelligence.costing(w, {"type": "set_policy", "subject": lever, "value": "true"}), 0.0, lever)

    def test_the_answer_says_a_no_op_costs_nothing(self):
        w = world(2, 5)
        w.policy.rationing = True
        ration = {"id": "M4", "type": "set_policy", "subject": "rationing", "value": "true", "summary": "ration grain"}
        intelligence.request(w, "A", [{"topic": "costing", "motion_id": "M4"}], "session", [ration])
        w.month = 6
        delivered = intelligence.answer_requests(w, {"treasury": .6}, [], "carry")
        self.assertIn("costs nothing", delivered[0]["text"])
        self.assertNotIn("0-0M", delivered[0]["text"])

    def test_an_import_cap_already_in_place_costs_nothing(self):
        w = world(2, 5)
        w.policy.imports = "max"
        self.assertEqual(intelligence.costing(w, {"type": "set_policy", "subject": "imports", "value": "max"}), 0.0)

    def test_a_switch_that_changes_the_state_is_still_costed(self):
        w = world(2, 5)
        gdp = w.econ.gdp_nominal
        w.policy.rationing = False
        self.assertAlmostEqual(intelligence.costing(w, {"type": "set_policy", "subject": "rationing", "value": "true"}), .004 * gdp)
        w.policy.rationing = True
        self.assertAlmostEqual(intelligence.costing(w, {"type": "set_policy", "subject": "rationing", "value": "false"}), -.004 * gdp)
        w.policy.shipbuilding = False
        self.assertAlmostEqual(intelligence.costing(w, {"type": "set_policy", "subject": "shipbuilding", "value": "true"}), .003 * gdp)


class SoldiersCostedAsThePayIs(unittest.TestCase):
    """IN5: a soldier costs what military.update pays him: ARMY_COST, the price level, and the officer-pay and the
    training bills. The Treasury's costing used a flat 900 crowns, 3.5 times what the engine pays."""

    def world(self, size=28000):
        w = world(1, 5)
        w.mil.army.size = size
        w.econ.cpi = 1.0
        return w

    def test_a_bigger_army_costs_the_pay_the_engine_charges(self):    # PoC 6
        w = self.world()
        motion = {"type": "set_policy", "subject": "army_target", "value": "50000"}
        extra = 50000 - 28000
        per_soldier = military.ARMY_COST * w.econ.cpi * military.officer_pay(w)["bill"] * military.training_intensity(w)["bill"]
        self.assertAlmostEqual(intelligence.costing(w, motion), extra * per_soldier, delta=1)
        # with the standard pay and training, a soldier costs the General Staff's own figure
        self.assertAlmostEqual(intelligence.costing(w, motion) / extra, military.ARMY_COST, places=6)

    def test_the_officers_pay_and_the_training_scale_each_soldier(self):
        w = self.world()
        w.policy.officer_pay = "premium"
        w.policy.training_intensity = "intense"
        motion = {"type": "set_policy", "subject": "army_target", "value": "50000"}
        expected = 22000 * military.ARMY_COST * 1.28 * 1.10
        self.assertAlmostEqual(intelligence.costing(w, motion), expected, delta=1)

    def test_a_raise_in_officers_pay_is_costed_on_the_training_scale_too(self):
        w = self.world()
        w.policy.training_intensity = "intense"
        bill = w.mil.army.size * military.ARMY_COST * w.econ.cpi * 1.10
        cost = intelligence.costing(w, {"type": "set_policy", "subject": "officer_pay", "value": "raised"})
        self.assertAlmostEqual(cost, .12 * bill, delta=1)


if __name__ == "__main__":
    unittest.main()
