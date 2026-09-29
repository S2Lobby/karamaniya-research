"""A directive that passes this month cannot be defied by an order written before its vote was counted.

Recorded in a real run: the Treasury holder voted yes on farm_support 0.03, repeated the current
0.02 in his orders as the instructions ask, and was recorded as defying the council. Twice more the
same happened after a no vote, and a colleague moved to dismiss him for it."""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import politics  # noqa: E402
from karamaniya.council import Council  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

OFFICES = {"head": "A", "treasury": "D", "interior": "E", "army": "B", "navy": "C"}


def world():
    w = new_world(3, 6, member_ids=list("ABCDE"))
    w.const.offices.update(OFFICES)
    return w


class OrdersAgainstFreshDirectives(unittest.TestCase):
    def test_an_order_for_a_setting_directed_this_month_is_set_aside_not_defiance(self):
        w = world()
        politics.apply_motion(w, {"type": "set_policy", "subject": "police", "value": "0.025", "proposer": "E"})
        superseded = []
        defiance = politics.apply_orders(w, "D", {"treasury": {"police": 0.02, "tax": 0.21}}, {"police"}, superseded)
        self.assertEqual(defiance, [])
        self.assertAlmostEqual(w.policy.police, 0.025)              # the directive stands
        self.assertAlmostEqual(w.policy.tax, 0.21)                   # the rest of the order is applied
        self.assertEqual([(s["lever"], s["order"], s["directive"]) for s in superseded], [("police", 0.02, 0.025)])

    def test_an_order_that_matches_the_new_directive_leaves_no_trace(self):
        w = world()
        politics.apply_motion(w, {"type": "set_policy", "subject": "police", "value": "0.025", "proposer": "E"})
        superseded = []
        self.assertEqual(politics.apply_orders(w, "D", {"treasury": {"police": 0.025}}, {"police"}, superseded), [])
        self.assertEqual(superseded, [])

    def test_a_directive_already_in_force_is_still_defied_knowingly(self):
        w = world()
        politics.apply_motion(w, {"type": "set_policy", "subject": "police", "value": "0.025", "proposer": "E"})
        defiance = politics.apply_orders(w, "D", {"treasury": {"police": 0.02}}, set(), [])   # a month later
        self.assertEqual([(d["lever"], d["directive"], d["value"]) for d in defiance], [("police", 0.025, 0.02)])
        self.assertAlmostEqual(w.policy.police, 0.02)                # the holder's order still wins, as before

    def test_calling_it_the_old_way_is_unchanged(self):
        w = world()
        politics.apply_motion(w, {"type": "set_policy", "subject": "protest_response", "value": "tolerate", "proposer": "A"})
        self.assertEqual(len(politics.apply_orders(w, "E", {"interior": {"protest_response": "lethal"}})), 1)


class UnknownLeverNote(unittest.TestCase):
    def test_patronage_names_and_typos_get_a_suggestion(self):
        w = world()
        note = lambda subject: politics.validate_motion_detail(
            w, {"type": "set_policy", "subject": subject, "value": "off", "proposer": "E"})["explanation"]
        self.assertIn("patronage_army", note("army patronage"))            # the council can direct it, under its own name
        self.assertIn("use patronage_army, patronage_navy or patronage_interior", note("patronage"))
        self.assertIn("did you mean recruitment", note("army_recruitment_focus"))
        self.assertIn("settings the council can direct: ", note("zzzzqq"))
        self.assertEqual(politics.validate_motion_detail(
            w, {"type": "set_policy", "subject": "zzzzqq", "value": "1", "proposer": "E"})["reason_code"], "UNKNOWN_LEVER")


def decision(votes, orders):
    return {"votes": votes, "vote_reasons": {}, "vote_conditions": {}, "resign": False, "coup": None,
            "coup_stance": "resist", "orders": orders, "operations": {}, "private_messages": [], "notes": "",
            "belief_updates": [], "decision_factors": []}


def resolve(w, motion, votes, orders):
    """One month's resolution with the votes and orders given, as the council runs it."""
    council = Council.__new__(Council)
    council.w, council.pending_dms, council.observer, council._lock, council.spend = w, [], None, threading.Lock(), 0.0
    decisions = {mid: decision({motion["id"]: vote}, orders.get(mid, {})) for mid, vote in votes.items()}
    return council._resolve_v2(decisions, [motion], [motion], [], list("ABCDE"), [], {}, {}, [], False)


class TheRecordedCase(unittest.TestCase):
    def motion(self, subject, value):
        return {"id": "M1", "proposer": "E", "type": subject and "set_policy", "subject": subject, "value": value,
                "text": "", "summary": f"directive {subject} = {value}"}

    def test_voting_yes_and_repeating_the_old_value_is_not_defiance(self):           # Month 2, farm_support
        w = world()
        record = resolve(w, self.motion("farm_support", "0.03"), dict.fromkeys("ABCDE", "yes"),
                         {"D": {"treasury": {"farm_support": 0.02}}})
        self.assertEqual(record["defiance"], [])
        self.assertAlmostEqual(w.policy.farm_support, 0.03)
        self.assertEqual(w.const.directives["farm_support"], 0.03)
        self.assertEqual([(s["member"], s["lever"], s["order"], s["directive"]) for s in record["superseded_orders"]],
                         [("D", "farm_support", 0.02, 0.03)])

    def test_voting_no_and_writing_your_own_preference_is_not_defiance_either(self):  # Month 3, police
        w = world()
        record = resolve(w, self.motion("police", "0.025"), {"A": "yes", "B": "yes", "C": "yes", "D": "no", "E": "yes"},
                         {"D": {"treasury": {"police": 0.015}}})
        self.assertEqual(record["defiance"], [])
        self.assertAlmostEqual(w.policy.police, 0.025)
        self.assertFalse(any(e["kind"] == "defiance" for e in w.events))

    def test_the_month_after_it_is_real_defiance_and_is_recorded(self):
        w = world()
        resolve(w, self.motion("police", "0.025"), {"A": "yes", "B": "yes", "C": "yes", "D": "no", "E": "yes"}, {})
        w.month += 1
        motion = {**self.motion("tax", "0.22"), "id": "M1"}
        record = resolve(w, motion, dict.fromkeys("ABCDE", "yes"), {"D": {"treasury": {"police": 0.015}}})
        self.assertEqual([(d["member"], d["lever"], d["directive"], d["value"]) for d in record["defiance"]],
                         [("D", "police", 0.025, 0.015)])
        self.assertAlmostEqual(w.policy.police, 0.015)

    def test_a_motion_that_failed_leaves_the_order_alone(self):
        w = world()
        before = w.policy.police
        record = resolve(w, self.motion("police", "0.025"), {"A": "no", "B": "no", "C": "no", "D": "yes", "E": "yes"},
                         {"D": {"treasury": {"police": 0.03}}})
        self.assertEqual(record["defiance"], [])
        self.assertEqual(record["superseded_orders"], [])
        self.assertAlmostEqual(w.policy.police, 0.03)                 # no directive, so the holder's order applies
        self.assertNotEqual(w.policy.police, before)


if __name__ == "__main__":
    unittest.main()
