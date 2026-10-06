"""Run statistics count actual votes, not proposals that never reached the floor."""
import unittest
import tempfile

from karamaniya.analytics import run_metrics
from karamaniya.scorecard import compute
from karamaniya.storage import RunStore
from karamaniya.world import new_world


class CouncilMetrics(unittest.TestCase):
    def test_deferred_and_withdrawn_motions_do_not_dilute_unanimity(self):
        base = {"type": "set_policy", "subject": "tax", "proposer": "A"}
        months = [{"motions": [
            {**base, "id": "M1", "votes": dict.fromkeys("ABCDE", "yes"), "passed": True},
            {**base, "id": "M2", "votes": {}, "withdrawn": True},
            {**base, "id": "M3", "votes": {}, "deferred": True},
        ]}]
        council = run_metrics(new_world(1).to_dict(), months)["council"]
        self.assertEqual(council["substantive"], 1)
        self.assertEqual(council["substantive_tabled"], 3)
        self.assertEqual(council["unanimous_rate"], 1.0)
        self.assertEqual(council["failed_rate"], 0.0)
        self.assertAlmostEqual(council["withdrawal_rate"], 1 / 3, places=3)

    def test_scorecard_report_denominator_excludes_unvoted_motions(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunStore(directory)
            store.save_config({"mapping": {letter: letter for letter in "ABCDE"}, "run": {}})
            store.save_checkpoint(new_world(1), {}, {})
            store.log({"type": "month", "month": 0, "motions": [
                {"id": "M1", "type": "set_policy", "subject": "tax", "value": "0.2",
                 "proposer": "A", "votes": dict.fromkeys("ABCDE", "yes"), "passed": True},
                {"id": "M2", "type": "set_policy", "subject": "tax", "value": "0.3",
                 "proposer": "B", "votes": {}, "passed": False, "withdrawn": True},
            ]})
            division = compute(store)["country"]["vote_division"]
            self.assertEqual(division["substantive"], 1)
            self.assertEqual(division["substantive_tabled"], 2)
            self.assertEqual(division["substantive_unanimous"], 1)
            self.assertEqual(division["substantive_failed"], 0)


if __name__ == "__main__":
    unittest.main()
