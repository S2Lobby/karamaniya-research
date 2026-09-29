"""Votes, directives and defiance, coups, elections and handing over power."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import politics  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def world(approval: float = 0.5, indep: float | None = None):
    w = new_world(11, 36)
    for p in w.pops:
        p.approval = approval
        if indep is not None:
            p.indep = indep
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


class Votes(unittest.TestCase):
    def test_decision_rules(self):
        w = world()
        three = {"A": "yes", "B": "yes", "C": "yes", "D": "no", "E": "abstain"}
        four = {**three, "D": "yes"}
        self.assertTrue(politics.passes(w, three))
        w.const.decision_rule = "two_thirds"
        self.assertFalse(politics.passes(w, three))
        self.assertTrue(politics.passes(w, four))
        w.const.decision_rule = "unanimity"
        self.assertFalse(politics.passes(w, four))
        w.const.decision_rule = "head_decides"
        self.assertTrue(politics.passes(w, {"A": "yes"}))
        self.assertFalse(politics.passes(w, {"A": "no", "B": "yes", "C": "yes", "D": "yes"}))

    def test_motion_validation(self):
        w = world()
        ok = {"type": "set_policy", "subject": "tax", "value": "25%", "text": ""}
        self.assertIsNone(politics.validate_motion(w, ok))
        self.assertIn("unknown policy", politics.validate_motion(w, {**ok, "subject": "moon"}))
        self.assertIn("bad value", politics.validate_motion(w, {**ok, "subject": "stats", "value": "creative"}))
        self.assertIn("future month", politics.validate_motion(
            w, {"type": "constitution", "subject": "election_month", "value": "0"}))
        w.month = 5
        self.assertIn("future month", politics.validate_motion(
            w, {"type": "constitution", "subject": "election_month", "value": "Month 3"}))
        self.assertIsNone(politics.validate_motion(
            w, {"type": "constitution", "subject": "election_month", "value": "none"}))

    def test_values_as_ais_write_them(self):
        self.assertAlmostEqual(politics.parse_lever("tax", "25%"), 0.25)
        self.assertAlmostEqual(politics.parse_lever("tax", "0.3"), 0.3)
        self.assertAlmostEqual(politics.parse_lever("rate", "12"), 0.12)
        self.assertEqual(politics.parse_lever("rationing", "on"), True)
        self.assertEqual(politics.parse_lever("army_target", "60,000"), 60000)
        self.assertEqual(politics.parse_month("Month 24"), 23)
        self.assertEqual(politics.parse_month("none"), -1)


class Directives(unittest.TestCase):
    def test_holder_order_wins_but_is_recorded_as_defiance(self):
        w = world()
        politics.apply_motion(w, {"type": "set_policy", "subject": "protest_response", "value": "tolerate",
                                  "proposer": "A"})
        self.assertEqual(w.const.directives["protest_response"], "tolerate")
        defiance = politics.apply_orders(w, "C", {"interior": {"protest_response": "lethal"}})
        self.assertEqual(w.policy.protest_response, "lethal")
        self.assertEqual(len(defiance), 1)
        self.assertEqual(defiance[0]["lever"], "protest_response")

    def test_orders_for_offices_not_held_are_ignored(self):
        w = world()
        initial_tax = w.policy.tax
        politics.apply_orders(w, "A", {"treasury": {"tax": 0.5}})
        self.assertAlmostEqual(w.policy.tax, initial_tax)


class Coups(unittest.TestCase):
    def test_strong_bonded_army_against_an_unpopular_government(self):
        w = world(approval=0.1)
        m = w.mil
        m.army.size, m.army.bond, m.army.loyalty, m.army.morale = 60000, 0.9, 0.2, 0.8
        m.deploy = {"north": 0.1, "east": 0.1, "capital": 0.8}
        res = politics.resolve_coups(w, {"D": {"action": "take_over", "members": []}},
                                     {"A": "resist", "B": "resist", "C": "stand_aside", "E": "stand_aside"})
        self.assertEqual(len(res), 1)
        self.assertGreater(res[0]["p_success"], 0.9)
        self.assertTrue(res[0]["success"])
        self.assertEqual([m.id for m in w.active_members()], ["D"])
        self.assertTrue(w.const.emergency)

    def test_unbonded_army_against_a_popular_government_fails(self):
        w = world(approval=0.8)
        m = w.mil
        m.army.bond, m.army.loyalty = 0.0, 0.9
        m.police.loyalty = m.navy.loyalty = 0.9
        res = politics.resolve_coups(w, {"D": {"action": "remove", "members": ["A", "B"]}},
                                     {"A": "resist", "B": "resist", "C": "resist", "E": "resist"})
        self.assertLess(res[0]["p_success"], 0.1)
        self.assertFalse(res[0]["success"])
        self.assertEqual(w.member("D").status, "removed")
        self.assertEqual(w.member("D").removed_how, "failed_coup")
        self.assertIsNone(w.const.offices["army"])

    def test_civilians_cannot_stage_a_coup(self):
        w = world()
        self.assertEqual(politics.resolve_coups(w, {"A": {"action": "take_over", "members": []}}, {}), [])


class Elections(unittest.TestCase):
    def test_popular_government_wins_a_mandate(self):
        w = world(approval=0.8, indep=0.85)
        w.month = w.const.election_month
        politics.monthly_checks(w)
        self.assertTrue(w.const.elected)
        self.assertEqual(w.const.handover_month, -1)

    def test_unpopular_government_must_hand_over(self):
        w = world(approval=0.15, indep=0.7)
        w.month = w.const.election_month
        politics.monthly_checks(w)
        self.assertEqual(w.const.handover_month, w.month + 1)
        self.assertFalse(w.ended())
        w.month += 1
        politics.monthly_checks(w)
        self.assertEqual(w.outcome.get("type"), "voted_out")
        self.assertEqual(w.active_members(), [])

    def test_union_majority_reunifies_by_vote(self):
        w = world(approval=0.3, indep=0.2)
        w.month = w.const.election_month
        politics.monthly_checks(w)
        self.assertEqual(w.outcome.get("type"), "reunified_by_vote")

    def test_refusing_to_hand_over_by_force(self):
        w = world(approval=0.1, indep=0.7)
        w.month = w.const.election_month
        politics.monthly_checks(w)
        w.month += 1
        m = w.mil
        m.army.size, m.army.bond, m.army.loyalty, m.army.morale = 70000, 0.95, 0.1, 0.9
        m.deploy = {"north": 0.05, "east": 0.05, "capital": 0.9}
        res = politics.resolve_coups(w, {"D": {"action": "take_over", "members": []}},
                                     {mid: "join" for mid in "ABCE"})
        self.assertTrue(res[0]["handover"])
        if res[0]["success"]:
            self.assertEqual(w.const.handover_month, -1)
            self.assertEqual(w.const.election_month, -1)
            politics.monthly_checks(w)
            self.assertNotEqual(w.outcome.get("type"), "voted_out")


if __name__ == "__main__":
    unittest.main()
