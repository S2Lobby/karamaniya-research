import unittest

from karamaniya import actions, deliberation
from karamaniya.council import Council
from karamaniya.world import new_world


class RepairedMotionCosponsor(unittest.TestCase):
    def test_repaired_duplicate_is_added_as_cosponsor_not_as_a_second_motion(self):
        world = new_world(13, member_ids=list("ABCDE"))
        raw = {"type": "program", "subject": "stabilization", "value": "package",
               "text": "Support farms at 2.5%."}
        missing_action = actions.normalize_motion_v2(world, raw)
        rejection, warning = deliberation.check(world, missing_action, [], "B")
        self.assertEqual(rejection["reason_code"], "NO_STRUCTURED_ACTION")
        self.assertIsNone(warning)

        existing = actions.normalize_motion_v2(world, {
            **raw, "action": {"measures": [{"lever": "farm_support", "value": "0.025"}]}})
        existing.update({"id": "M1", "proposer": "A", "summary": "farm support"})
        repaired = actions.normalize_motion_v2(world, {
            **raw, "action": {"measures": [{"lever": "farm_support", "value": "0.025"}]}})
        retry_rejection, retry_warning = deliberation.check(world, repaired, [existing], "B")
        self.assertIsNone(retry_rejection)
        self.assertEqual(retry_warning["code"], "COSPONSOR")

        tabled = [existing]
        forced = set()
        Council._record_tabled_motion(world, repaired, "B", tabled, forced,
                                      retry_warning, repaired_format=True)

        self.assertEqual(len(tabled), 1)
        self.assertEqual(tabled[0]["id"], "M1")
        self.assertEqual(tabled[0]["cosponsors"], ["B"])
        self.assertFalse(forced)


if __name__ == "__main__":
    unittest.main()
