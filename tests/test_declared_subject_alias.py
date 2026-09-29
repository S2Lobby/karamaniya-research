"""A subject that is the action's own name is not a contradiction of it.

Recorded in a real run: a Treasury-minded Head tabled 'loan_request' as the subject of a loan_request
act to the Maritime League. The engine's own word for that subject is 'loan', so the check declared
"the motion's own subject says loan_request, but its action says loan request", sent it back for
repair, and rejected it when it came back the same, a fortnight of credit talks lost to a false alarm."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, motion_actions, politics  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

LOAN_TEXT = ("Request a loan from the Maritime League on terms that cap the deficit, open ministries to audit "
             "and preserve Karamaniya's policy independence.")
PACT_TEXT = "Propose a mutual non-aggression pact to the Solvaran Union: both sides renounce force."


def world():
    return new_world(11)


def normalized(w, subject, action_type, target, text):
    return actions.normalize_motion_v2(w, {"type": "diplomacy", "subject": subject, "value": "", "text": text,
                                           "action": {"action_type": action_type, "target": target}})


class SubjectNamedLikeTheAction(unittest.TestCase):
    def test_loan_request_as_subject_of_a_loan_request_is_consistent(self):
        w = world()
        mo = normalized(w, "loan_request", "loan_request", "Maritime League", LOAN_TEXT)
        self.assertEqual(mo["subject"], "loan")                       # the engine's name for it
        self.assertNotIn("declared_subject", mo)
        self.assertIsNone(motion_actions.conflict(w, {**mo, "proposer": "C"}))
        self.assertIsNone(politics.validate_motion_detail(w, {**mo, "proposer": "C"}))

    def test_non_aggression_pact_as_subject_of_that_act_is_consistent(self):
        w = world()
        mo = normalized(w, "non_aggression_pact", "non_aggression_pact", "Solvaran Union", PACT_TEXT)
        self.assertEqual(mo["subject"], "non_aggression")
        self.assertNotIn("declared_subject", mo)
        self.assertIsNone(motion_actions.conflict(w, {**mo, "proposer": "C"}))

    def test_the_engines_own_name_and_a_matching_name_still_pass(self):
        w = world()
        for subject in ("loan", "loan_request"):
            mo = normalized(w, subject, "loan_request", "Maritime League", LOAN_TEXT)
            self.assertIsNone(motion_actions.conflict(w, {**mo, "proposer": "C"}), subject)

    def test_a_defensive_record_that_already_carries_the_alias_is_not_a_clash(self):
        w = world()
        mo = normalized(w, "loan", "loan_request", "Maritime League", LOAN_TEXT)
        self.assertIsNone(motion_actions.conflict(w, {**mo, "declared_subject": "loan_request", "proposer": "C"}))


class RealContradictionsStillCaught(unittest.TestCase):
    def test_a_subject_naming_a_different_act_is_still_a_contradiction(self):
        w = world()
        for subject, action_type, target, text in (
                ("trade_deal", "diplomatic_protest", "Solvaran Union",
                 "Protest the Union's boarding of a Karamanian grain ship and demand an end to inspections."),
                ("alliance", "trade_talks", "Solvaran Union", "Open trade talks with the Solvaran Union."),
                ("loan_request", "trade_deal", "Maritime League", "Sign a trade deal with the Maritime League.")):
            mo = normalized(w, subject, action_type, target, text)
            clash = motion_actions.conflict(w, {**mo, "proposer": "C"})
            self.assertIsNotNone(clash, subject)
            self.assertIn("DECLARED_SUBJECT_CONTRADICTS_ACTION", {r["code"] for r in clash["reasons"]}, subject)


class EmergencyMeasureNote(unittest.TestCase):
    def test_the_rejection_names_the_measures_there_are(self):
        w = world()
        note = politics.validate_motion_detail(w, {"type": "emergency_measure", "subject": "navy procurement audit",
                                                    "value": "on", "proposer": "E"})
        self.assertEqual(note["reason_code"], "UNKNOWN_MEASURE")
        for measure in ("curfew", "police_powers", "fiscal_authority"):
            self.assertIn(measure, note["explanation"])


if __name__ == "__main__":
    unittest.main()
