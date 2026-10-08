"""A safeguard the voted text states binds even when the motion's conditions omit it.

Month 3 of run 20261008-130316-seed1: Delegate B tabled a quarter arrears payment from reserves with a
60M floor in its conditions; an amendment rewrote the text to require at least 70M after payment and
left the conditions at 60M. The council passed it 3-2 with reserves at 74M, and the gate refused to run
it at all, though the text's own safeguard was met. Run under its conditions alone it would have run
too early; it now runs under both, and the payment is sized to the stricter floor.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import motion_actions, politics  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

FINAL_TEXT = ("Pay one quarter of inherited unpaid bills from reserves, but only after Treasury certifies in "
              "writing that post-payment reserves will be at least 70M gold and that contracted grain imports "
              "and current army, navy and police payroll are fully funded; otherwise defer the tranche.")
STORED = [{"metric": "reserves_after_payment", "operator": ">=", "value": 60_000_000.0, "source": "Treasury cash desk"}]


class TextSafeguards(unittest.TestCase):
    def setUp(self):
        self.w = new_world(1, 36)
        self.w.econ.arrears = max(self.w.econ.arrears, 20_000_000.0)
        self.motion = {"id": "D1", "type": "settle_arrears", "subject": "reserves", "value": "quarter",
                       "text": FINAL_TEXT, "proposer": "B", "passed": True}

    def test_the_texts_floor_is_bound_with_the_motions_own(self):
        conditions, bound = motion_actions.bind_text_conditions(self.w, self.motion, STORED)
        self.assertEqual([(c["metric"], c["operator"], c["value"]) for c in bound],
                         [("reserves_after_payment", ">=", 70_000_000.0)])
        self.assertEqual(len(conditions), 2)
        self.assertEqual(politics.payment_floor({**self.motion, "conditions": conditions}), 70_000_000.0)

    def test_it_runs_when_both_floors_hold(self):
        self.w.econ.gold = 74_200_000.0
        # Under its own conditions alone the gate still refuses it: they would let it run too early.
        refused = motion_actions.validate_execution(self.w, {**self.motion, "conditions": STORED})
        self.assertEqual(refused["code"], "MOTION_CONDITION_MISMATCH")
        conditions, _ = motion_actions.bind_text_conditions(self.w, self.motion, STORED)
        self.assertIsNone(motion_actions.validate_execution(self.w, {**self.motion, "conditions": conditions}))

    def test_it_is_blocked_when_the_texts_floor_does_not_hold(self):
        self.w.econ.gold = 65_000_000.0
        conditions, _ = motion_actions.bind_text_conditions(self.w, self.motion, STORED)
        gate = motion_actions.validate_execution(self.w, {**self.motion, "conditions": conditions})
        self.assertEqual(gate["code"], "EXECUTION_BLOCKED_CONDITION")

    def test_conditions_that_already_cover_the_text_are_left_alone(self):
        own = [{**STORED[0], "value": 75_000_000.0}]
        conditions, bound = motion_actions.bind_text_conditions(self.w, self.motion, own)
        self.assertEqual((conditions, bound), (own, []))


if __name__ == "__main__":
    unittest.main()
