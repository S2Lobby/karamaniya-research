"""A delegate's opening prompt lists its own motions the engine refused to table the month before.

The reason was shown for the rest of the month it happened in and was gone the next: in run
20261008-130316-seed1 Delegates A and C were refused an Interior audit inside its cooldown in Month 5 and
asked for it again in Month 7, and Delegate C moved the same unknown lever month after month.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya.council import _rejected_last_month  # noqa: E402

RECORD = {"rejected_motions": [
    {"member": "C", "motion": {"type": "investigation", "subject": "interior", "value": "open",
                               "text": "Order an independent audit of Interior spending."},
     "status": "rejected", "reason_code": "RECENTLY_AUDITED",
     "explanation": "the interior office was audited in Month 4 and cannot be audited again until Month 10"},
    {"member": "A", "motion": {"type": "investigation", "subject": "interior", "value": "open", "text": "Re-open it."},
     "status": "rejected", "reason_code": "RECENTLY_AUDITED", "explanation": "audited in Month 4"},
]}


class RejectionFeedback(unittest.TestCase):
    def test_a_delegate_sees_its_own_refusals_with_the_reason(self):
        sections = _rejected_last_month(RECORD, "C")
        self.assertEqual([s.key for s in sections], ["rejected_last_month"])
        text = sections[0].text
        self.assertIn("investigation interior open: RECENTLY_AUDITED", text)
        self.assertIn("cannot be audited again until Month 10", text)
        self.assertNotIn("Re-open it", text)  # only its own

    def test_nothing_is_added_without_a_refusal(self):
        self.assertEqual(_rejected_last_month(RECORD, "B"), [])
        self.assertEqual(_rejected_last_month(None, "C"), [])
        self.assertEqual(_rejected_last_month({"motions": []}, "C"), [])   # a checkpoint from before


class LeakRecords(unittest.TestCase):
    def test_a_leak_records_the_chance_it_had_and_its_factors(self):
        from karamaniya import intelligence
        from karamaniya.world import new_world
        w = new_world(3, 12, member_ids=list("ABCDE"))
        w.tuning = {"leaks": {"base": 10.0, "max_per_month": 20}}
        dms = [{"from": "A", "to": "B", "text": f"private note {i}", "kind": "confidential"} for i in range(12)]
        leaks = intelligence.leaks(w, dms, [])
        self.assertTrue(leaks)
        for leak in leaks:
            self.assertEqual(leak["probability"], 0.5)          # capped
            self.assertEqual(set(leak["factors"]), {"base", "press", "admin", "person", "kind"})
            self.assertEqual(leak["factors"]["kind"], 1.3)      # a confidential message


if __name__ == "__main__":
    unittest.main()
