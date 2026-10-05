import unittest

from karamaniya import actions, deliberation, politics
from karamaniya.world import new_world


class ProgramAmendments(unittest.TestCase):
    def setUp(self):
        self.w = new_world(1, member_ids=list("ABCDE"))
        self.w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})

    def motion(self):
        motion = actions.normalize_motion_v2(self.w, {
            "type": "program", "subject": "stabilization", "value": "package",
            "text": "Negotiate protests, support farms, and fund Kessel.",
            "action": {"measures": [
                {"lever": "protest_response", "value": "negotiate"},
                {"lever": "farm_support", "value": "0.025"},
                {"lever": "regional_fund", "value": "kessel"}]} })
        motion.update({"id": "M4", "proposer": "A", "summary": "stabilization package"})
        self.assertIsNone(politics.validate_motion_detail(self.w, motion))
        return motion

    def test_revision_replaces_the_complete_package_before_vote_and_execution(self):
        motion = self.motion()
        notes = deliberation.apply_revisions(self.w, "A", {"amend": [{
            "motion_id": "M4", "value": "package", "text": "Support farms at 2.5%.",
            "measures": [{"lever": "farm_support", "value": "0.025"}]}]}, [motion], [motion])
        self.assertEqual(notes["amended"], ["M4"])
        self.assertEqual(motion["measures"], [("farm_support", .025)])
        self.assertIsNone(politics.validate_motion_detail(self.w, motion))
        politics.apply_motion(self.w, motion)
        self.assertEqual(self.w.policy.farm_support, .025)
        self.assertEqual(self.w.policy.protest_response, "tolerate")
        self.assertEqual(self.w.policy.regional_fund, "none")

    def test_incomplete_program_revision_is_rejected_and_original_package_remains(self):
        motion = self.motion()
        notes = deliberation.apply_revisions(self.w, "A", {"amend": [{
            "motion_id": "M4", "value": "package", "text": "Support farms at 2.5%."}]}, [motion], [motion])
        self.assertEqual(notes["rejected"][0]["code"], "PROGRAM_AMENDMENT_MISSING_MEASURES")
        self.assertEqual(motion["measures"], [("protest_response", "negotiate"),
                                              ("farm_support", .025), ("regional_fund", "kessel")])

    def test_measures_only_revision_replaces_the_executable_package(self):
        motion = self.motion()
        replacement = [{"lever": "farm_support", "value": "0.025"}]
        notes = deliberation.apply_revisions(self.w, "A", {"amend": [{
            "motion_id": "M4", "value": "package", "text": motion["text"],
            "measures": replacement}]}, [motion], [motion])

        self.assertEqual(notes["amended"], ["M4"])
        self.assertEqual(motion["measures"], [("farm_support", .025)])
        self.assertEqual(motion["action"]["measures"], replacement)
        self.assertEqual(motion["revisions"][0]["action"]["measures"], [
            {"lever": "protest_response", "value": "negotiate"},
            {"lever": "farm_support", "value": "0.025"},
            {"lever": "regional_fund", "value": "kessel"}])
        politics.apply_motion(self.w, motion)
        self.assertEqual(self.w.policy.protest_response, "tolerate")
        self.assertEqual(self.w.policy.farm_support, .025)
        self.assertEqual(self.w.policy.regional_fund, "none")

    def test_program_proposals_with_distinct_measures_do_not_collapse(self):
        existing = self.motion()
        existing.update({"id": "M1", "proposer": "A"})
        different = actions.normalize_motion_v2(self.w, {
            "type": "program", "subject": "stabilization", "value": "package",
            "text": existing["text"],
            "action": {"measures": [{"lever": "farm_support", "value": "0.03"}]}})

        rejection, warning = deliberation.check(self.w, different, [existing], "B")

        self.assertIsNone(rejection)
        self.assertIsNone(warning)

    def test_carried_program_with_distinct_measures_is_not_renewed(self):
        carried = self.motion()
        carried.update({"id": "D1", "proposer": "A", "deferred_month": 0})
        different = actions.normalize_motion_v2(self.w, {
            "type": "program", "subject": "stabilization", "value": "package",
            "text": carried["text"],
            "action": {"measures": [{"lever": "farm_support", "value": "0.03"}]}})

        result = deliberation.coalesce_carried(self.w, different, [carried], "A")

        self.assertIsNone(result)
        self.assertEqual(carried["action"]["measures"], [
            {"lever": "protest_response", "value": "negotiate"},
            {"lever": "farm_support", "value": "0.025"},
            {"lever": "regional_fund", "value": "kessel"}])


if __name__ == "__main__":
    unittest.main()
