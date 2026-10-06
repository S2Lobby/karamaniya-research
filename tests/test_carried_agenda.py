"""A deferred proposal must keep one agenda place when renewed next month."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, deliberation, motion_actions, prompts  # noqa: E402
from karamaniya.politics import apply_motion, validate_motion_detail  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


class CarriedAgendaTests(unittest.TestCase):
    def setUp(self):
        self.w = new_world(17)
        self.w.month = 1
        self.w.agenda["deferred"] = [{"type": "diplomacy", "subject": "non_aggression", "value": "",
                                      "text": "Seek a border agreement", "proposer": "B",
                                      "summary": "non aggression", "deferred_month": 0}]

    def test_renewal_and_cosponsorship_leave_room_for_new_policy(self):
        carried = deliberation.carried_over(self.w)
        carried[0]["id"] = "D1"
        renewed = {"type": "diplomacy", "subject": "non_aggression", "value": "",
                   "text": "Seek a border agreement with a hotline"}
        self.assertEqual(deliberation.coalesce_carried(self.w, renewed, carried, "B")["code"], "RENEWED_CARRIED")
        self.assertEqual(deliberation.coalesce_carried(self.w, renewed, carried, "A")["code"], "COSPONSORED_CARRIED")
        self.assertEqual(len(carried), 1)
        self.assertEqual(carried[0]["cosponsors"], ["A"])
        self.assertIn("hotline", carried[0]["text"])
        new = {"id": "M1", "type": "set_policy", "subject": "tax", "value": "0.24",
               "text": "Raise tax to fund administration", "proposer": "D", "summary": "tax 0.24"}
        scheduled, deferred, _ = deliberation.allocate(self.w, carried + [new], [], set(), carried)
        self.assertEqual({m["id"] for m in scheduled}, {"D1", "M1"})
        self.assertEqual(deferred, [])
        self.assertIn("D1 by B", prompts.opening_instructions_v2(self.w, "A", 3, list("ABCDE"), 4, carried))

    def test_renewal_updates_diplomatic_text_and_executable_target_together(self):
        w = self.w
        w.agenda["deferred"] = [{
            "type": "diplomacy", "subject": "non_aggression", "value": "",
            "text": "Propose a non-aggression pact to Veleria for three years.",
            "action": {"action_type": "non_aggression_pact", "target": "Veleria",
                       "terms": ["three years"]},
            "proposer": "B", "summary": "non-aggression pact", "deferred_month": 0,
        }]
        carried = deliberation.carried_over(w)
        carried[0]["id"] = "D1"
        proposal = actions.normalize_motion_v2(w, {
            "type": "diplomacy", "subject": "non_aggression", "value": "",
            "text": "Propose a non-aggression pact to the Solvaran Union for ten years.",
            "action": {"action_type": "non_aggression_pact", "target": "Solvaran Union",
                       "terms": ["ten years"]},
        })
        proposal["proposer"] = "B"

        renewed = deliberation.coalesce_carried(w, proposal, carried, "B")

        self.assertEqual(renewed, {"code": "RENEWED_CARRIED", "motion": "D1"})
        self.assertIn("Solvaran Union", carried[0]["text"])
        self.assertEqual(motion_actions.structured_action(w, carried[0])["target"], "SOLVARAN_UNION")
        self.assertEqual(carried[0]["action"]["terms"], ["ten years"])
        self.assertEqual(carried[0]["original_action"]["target"], "VELERIA")
        self.assertIsNone(motion_actions.validate_diplomatic_action(w, carried[0]))

    def test_fiscal_distress_adds_one_agenda_slot_but_normal_months_do_not(self):
        self.assertEqual(deliberation.capacity(self.w), 4)
        self.w.econ.paid_share = 0.80
        self.assertEqual(deliberation.capacity(self.w), 5)

    def test_large_arrears_add_a_slot_even_if_current_bills_are_paid(self):
        self.w.econ.gdp_nominal = 500e6
        self.w.econ.arrears = 60e6
        self.assertEqual(deliberation.capacity(self.w), 5)

    def test_cosponsor_can_keep_or_leave_motion_after_originator_withdraws(self):
        carried = deliberation.carried_over(self.w)
        motion = carried[0]
        motion["id"] = "D1"
        motion["cosponsors"] = ["A"]
        replacement = {"id": "M9", "proposer": "C", "type": "set_policy", "subject": "tax",
                       "value": "0.3", "text": "", "summary": "tax"}
        carried.append(replacement)
        schema = actions.revision_schema(self.w, "A", carried)
        self.assertIn("D1", schema["properties"]["withdraw"]["items"]["properties"]["motion_id"]["enum"])
        deliberation.apply_revisions(self.w, "B", {"withdraw": ["D1"]}, carried, carried)
        self.assertEqual(motion["proposer"], "A")
        self.assertFalse(motion.get("withdrawn"))
        # The structured form keeps why the motion went, and what the proposer fell in behind.
        deliberation.apply_revisions(self.w, "A", {"withdraw": [
            {"motion_id": "D1", "reason": "consolidating behind the costed alternative",
             "replaced_by": "M9"}]}, carried, carried)
        self.assertTrue(motion["withdrawn"])
        self.assertEqual(motion["withdrawal_reason"], "consolidating behind the costed alternative")
        self.assertEqual(motion["replaced_by"], "M9")

    def test_withdrawal_cannot_fall_in_behind_a_motion_already_withdrawn(self):
        first = {"id": "D1", "proposer": "B", "type": "set_policy", "subject": "tax",
                 "value": "0.3", "withdrawn": False, "cosponsors": []}
        second = {"id": "D2", "proposer": "E", "type": "set_policy", "subject": "welfare",
                  "value": "0.1", "withdrawn": False, "cosponsors": []}
        motions = [first, second]
        deliberation.apply_revisions(self.w, "B", {"withdraw": [
            {"motion_id": "D1", "reason": "support D2", "replaced_by": "D2"}]}, motions, motions)
        self.assertTrue(first["withdrawn"])
        notes = deliberation.apply_revisions(self.w, "E", {"withdraw": [
            {"motion_id": "D2", "reason": "support D1", "replaced_by": "D1"}]}, motions, motions)
        self.assertFalse(second.get("withdrawn"))
        self.assertEqual(notes["rejected_withdrawals"][0]["code"], "WITHDRAWAL_TARGET_INACTIVE")

    def test_arrears_settlement_is_a_funded_vote_with_real_cost(self):
        w = self.w
        w.econ.arrears = 40e6
        w.econ.gold = 30e6
        cash = {"type": "settle_arrears", "subject": "reserves", "value": "quarter", "text": "Pay clerks"}
        self.assertIsNone(validate_motion_detail(w, cash))
        self.assertEqual(deliberation.topic(cash), "fiscal")
        self.assertIn("quarter", actions.motion_summary(w, cash))
        apply_motion(w, cash)
        self.assertAlmostEqual(w.econ.arrears, 30e6)
        self.assertAlmostEqual(w.econ.gold, 20e6)
        self.assertAlmostEqual(sum(w.econ.arrears_by.values()), w.econ.arrears)
        bonds = {**cash, "subject": "domestic_bonds", "value": "all"}
        before_debt = w.econ.debt_dom
        apply_motion(w, bonds)
        self.assertGreater(w.econ.debt_dom, before_debt)
        self.assertAlmostEqual(before_debt + 30e6 - w.econ.arrears, w.econ.debt_dom)
        self.assertEqual(validate_motion_detail(w, bonds)["reason_code"], "NO_FUNDING_CAPACITY")
        self.assertEqual(validate_motion_detail(w, {**cash, "value": "pay_full_clearance_prioritized"})["reason_code"],
                         "BAD_VALUE")


if __name__ == "__main__":
    unittest.main()
