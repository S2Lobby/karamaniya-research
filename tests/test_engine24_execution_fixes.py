"""Two execution bugs found by the detector audit (docs/DETECTOR_PRECISION.md, D4).

T136: the duplicate-action key ignored a programme's measures, so a second programme passed in the same month was
refused as a duplicate of the first. Run 20261011-211521-seed1, month index 4: programme M3 (deploy north 0.3, east
0.55, capital 0.15) was blocked by programme M4 (tax 0.23, health_edu 0.05, ...). Both had an empty value.

T137: the patronage compliance row was written before the order was applied, so it recorded the value the order
replaced. Run b1-s1005, month index 4: the row said actual True, while the order had set False.
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import motion_actions, politics  # noqa: E402
from karamaniya.council import Council  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

OFFICES = {"head": "A", "treasury": "D", "interior": "E", "army": "B", "navy": "C"}


def world():
    w = new_world(3, 6, member_ids=list("ABCDE"))
    w.const.offices.update(OFFICES)
    return w


def decision(votes, orders):
    return {"votes": votes, "vote_reasons": {}, "vote_conditions": {}, "resign": False, "coup": None,
            "coup_stance": "resist", "orders": orders, "operations": {}, "private_messages": [], "notes": "",
            "belief_updates": [], "decision_factors": []}


def resolve(w, motions, votes, orders=None):
    """One month's resolution, as the council runs it, with every member giving the same vote on every motion."""
    council = Council.__new__(Council)
    council.w, council.pending_dms, council.observer, council._lock, council.spend = w, [], None, threading.Lock(), 0.0
    decisions = {mid: decision({mo["id"]: vote for mo in motions}, (orders or {}).get(mid, {}))
                 for mid, vote in votes.items()}
    return council._resolve_v2(decisions, motions, motions, [], list("ABCDE"), [], {}, {}, [], False)


def programme(motion_id, proposer, measures, value="", text=""):
    return {"id": motion_id, "proposer": proposer, "type": "program", "subject": "", "value": value,
            "text": text or f"Programme {motion_id}.", "summary": f"programme {motion_id}",
            "action": {"measures": [{"lever": lever, "value": amount} for lever, amount in measures]}}


# Run 20261011-211521-seed1, month index 4: the two programmes the duplicate check wrongly joined.
FISCAL = programme("M4", "C", [("tax", "0.23"), ("health_edu", "0.05"), ("welfare", "0.03"),
                              ("military", "0.04"), ("farm_support", "0.03")],
                   text="Fiscal correction to meet League conditions and address the deficit.")
DEPLOY = programme("M3", "D", [("deploy_north", "0.3"), ("deploy_east", "0.55"), ("deploy_capital", "0.15")],
                   text="Rebalance the existing army deployment toward the more exposed eastern front.")

TAX = {"id": "M1", "proposer": "A", "type": "set_policy", "subject": "tax", "value": "0.22", "text": "",
       "summary": "directive tax = 0.22"}

# The keys of the other acts as they stood on main 3bb2ead, at month 4 of a new_world(11). A change to any of
# them is a change to a key this fix must not touch.
SET_TAX = {"id": "M1", "proposer": "E", "type": "set_policy", "subject": "tax", "value": "0.22", "text": "",
           "summary": "directive tax = 0.22"}
PROTEST = {"type": "diplomacy", "subject": "diplomatic_protest", "value": "",
           "text": ("Formal diplomatic protest to the Solvaran Union demanding cessation of unauthorized "
                    "inspections of Karamanian merchant vessels and respect for our sovereign trade rights."),
           "action": {"action_type": "diplomatic_protest", "target": "Solvaran Union",
                      "issue": "unauthorized merchant vessel inspection", "terms": ["cease inspections"]}}
AMEND = {"id": "A1", "proposer": "E", "type": "amend", "subject": "charter", "value": "",
         "text": "The Council shall publish its minutes within seven days."}
RELIEF = {"id": "R1", "type": "disaster_relief", "subject": "lissen", "value": "20", "proposer": "A",
          "text": "Coastal reconstruction on the Lissen Coast.", "summary": "relief"}
APPOINT = {"id": "M9", "proposer": "A", "type": "assign_office", "subject": "treasury", "value": "C",
           "text": "Appoint C to the treasury.", "summary": "appoint"}
GOLDEN_KEYS = [(SET_TAX, "f0d44fbd8300d7cd"), (PROTEST, "c03cdbf8a6248ce9"), (AMEND, "93ceb6a90defb723"),
               (RELIEF, "69edf14dd9e93ddd"), (APPOINT, "c7df2f10040fc7ac")]


class TwoProgrammesInOneMonth(unittest.TestCase):
    def test_two_different_programmes_both_take_effect(self):
        w = world()
        record = resolve(w, [FISCAL, DEPLOY], dict.fromkeys("ABCDE", "yes"))
        status = {row["id"]: row["execution_status"] for row in record["motions"]}
        self.assertEqual(status, {"M4": "EXECUTED", "M3": "EXECUTED"})
        self.assertEqual(w.const.directives["tax"], 0.23)
        self.assertEqual(w.const.directives["deploy_north"], 0.3)

    def test_the_same_measures_worded_differently_take_effect_once(self):
        w = world()
        first = programme("M1", "A", [("tax", "0.25")], value="", text="Raise tax to a quarter.")
        second = programme("M2", "B", [("tax", "0.25")], value="Tax to 0.25, as the League asked.",
                           text="Lift tax to 25 percent.")
        record = resolve(w, [first, second], dict.fromkeys("ABCDE", "yes"))
        rows = {row["id"]: row for row in record["motions"]}
        self.assertEqual(rows["M1"]["execution_status"], "EXECUTED")
        self.assertEqual(rows["M2"]["execution_status"], "EXECUTION_BLOCKED")
        self.assertEqual(rows["M2"]["duplicate_of"], "M1")
        self.assertEqual(w.const.directives["tax"], 0.25)

    def test_identical_programmes_take_effect_once(self):
        w = world()
        first = programme("M1", "A", [("tax", "0.25")], text="Raise tax to a quarter.")
        second = programme("M2", "B", [("tax", "0.25")], text="Raise tax to a quarter.")
        record = resolve(w, [first, second], dict.fromkeys("ABCDE", "yes"))
        rows = {row["id"]: row for row in record["motions"]}
        self.assertEqual([rows["M1"]["execution_status"], rows["M2"]["execution_status"]],
                         ["EXECUTED", "EXECUTION_BLOCKED"])
        self.assertEqual(rows["M2"]["duplicate_of"], "M1")

    def test_the_other_acts_keep_the_execution_key_they_had(self):
        w = new_world(11)
        w.month = 4
        for motion, digest in GOLDEN_KEYS:
            self.assertEqual(motion_actions.execution_key(w, motion), digest, motion["type"])


class PatronageRowIsTheAppliedOrder(unittest.TestCase):
    def test_a_row_against_a_directive_records_the_value_the_order_left(self):
        w = world()
        w.policy.patronage["army"] = True
        w.const.directives["patronage_army"] = True
        compliance = []
        defiance = politics.apply_orders(w, "B", {"army": {"patronage": False}}, compliance=compliance)
        self.assertIs(w.policy.patronage["army"], False)              # the order was applied
        self.assertEqual([d["lever"] for d in defiance], ["patronage_army"])
        self.assertEqual(len(compliance), 1)
        row = compliance[0]
        self.assertIs(row["actual_executed_value"], False)
        self.assertIs(row["office_order_value"], False)
        self.assertIs(row["directive_value"], True)
        self.assertEqual(row["compliance_status"], politics.EXPLICIT_VIOLATION)

    def test_the_recorded_row_and_the_office_order_agree_in_a_full_month(self):
        w = world()
        w.policy.patronage["army"] = True
        w.const.directives["patronage_army"] = True
        record = resolve(w, [TAX], dict.fromkeys("ABCDE", "yes"), {"B": {"army": {"patronage": False}}})
        row = next(r for r in record["compliance"] if r["lever"] == "patronage_army")
        order = next(r for r in record["office_orders"] if r["lever"] == "patronage_army")
        self.assertEqual(order["actual_value"], False)
        self.assertEqual(row["actual_executed_value"], order["actual_value"])
        self.assertEqual(row["office_order_value"], order["order"])

    def test_an_order_in_line_with_its_directive_is_recorded_as_applied(self):
        w = world()
        w.policy.patronage["army"] = True
        w.const.directives["patronage_army"] = True
        compliance = []
        politics.apply_orders(w, "B", {"army": {"patronage": True}}, compliance=compliance)
        self.assertEqual(len(compliance), 1)
        self.assertIs(compliance[0]["actual_executed_value"], True)
        self.assertEqual(compliance[0]["compliance_status"], politics.COMPLIANT)


if __name__ == "__main__":
    unittest.main()
