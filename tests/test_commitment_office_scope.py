"""Promises about office appointments and policy orders retain their scope."""
import unittest

from karamaniya import commitments
from karamaniya.world import new_world


class CommitmentOfficeScope(unittest.TestCase):
    def test_appointment_promise_only_matches_the_named_office(self):
        w = new_world(43)
        promise = commitments.record(w, "A", "I will appoint you as navy.", "B",
                                     source="dm", kind="promise")

        other_office = commitments.evaluate(w, {"motions": [
            {"type": "assign_office", "subject": "army", "value": "B", "votes": {"A": "yes"}}
        ], "decisions": {}})

        self.assertEqual(promise["normalized"], {
            "type": "support_appointment", "beneficiary": "B", "office": "navy"})
        self.assertEqual(other_office, [])
        self.assertEqual(promise["status"], "active")

        matching_office = commitments.evaluate(w, {"motions": [
            {"type": "assign_office", "subject": "navy", "value": "B", "votes": {"A": "yes"}}
        ], "decisions": {}})
        self.assertEqual(matching_office[0]["verdict"], "kept")

    def test_policy_order_promise_keeps_the_policy_value_from_creation(self):
        w = new_world(44)
        baseline = w.policy.military
        promise = commitments.record(w, "A", "I will increase the military budget.", "public")
        self.assertEqual(promise["baseline_value"], baseline)

        w.month += 1
        result = commitments.evaluate(w, {"motions": [], "decisions": {
            "A": {"orders": {"treasury": {"military": str(baseline + 0.001)}}}
        }})

        self.assertEqual(result[0]["verdict"], "kept")
        self.assertEqual(promise["status"], "fulfilled")


if __name__ == "__main__":
    unittest.main()
