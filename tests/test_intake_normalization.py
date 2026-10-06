"""Delegates name offices, foreign acts and funding sources in prose; the harness must resolve the
words they used to the engine's own id -- and must NOT guess when a phrase is genuinely ambiguous."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, politics  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


class Office(unittest.TestCase):
    def test_display_names_resolve(self):
        for raw, want in [("Head of Government", "head"), ("Treasury", "treasury"),
                          ("Army Command", "army"), ("Interior and Police", "interior"),
                          ("Navy Command", "navy"), ("Naval Command", "navy"), ("head", "head")]:
            self.assertEqual(politics.canonical_office(raw), want, raw)

    def test_ambiguous_or_foreign_is_left_for_rejection(self):
        # Names several offices, or names a member/lever, not one office: do not guess.
        for raw in ("head_treasury_interior_army_navy", "Delegate A", "tax"):
            self.assertNotIn(politics.canonical_office(raw), politics.OFFICES, raw)


class Diplomacy(unittest.TestCase):
    def test_prose_wrapped_act_resolves(self):
        for raw, want in [("trade_talks with Dorsania", "trade_talks"),
                          ("non_aggression_pact", "non_aggression"),
                          ("Grain Deal with Dorsania (Imports)", "grain_deal"),
                          ("Union alliance", "alliance"), ("loan", "loan"),
                          ('"trade_deal"', "trade_deal")]:
            self.assertEqual(politics.canonical_diplomacy_subject(raw), want, raw)

    def test_two_acts_in_one_phrase_is_left_as_written(self):
        self.assertEqual(politics.canonical_diplomacy_subject("trade_talks; non_aggression_pact"),
                         "trade_talks; non_aggression_pact")


class Funding(unittest.TestCase):
    def test_synonyms_resolve(self):
        for raw, want in [("Reserves", "reserves"), ("reserves,", "reserves"),
                          ("gold", "reserves"), ("domestic_bonds", "domestic_bonds"), ("bonds", "domestic_bonds")]:
            self.assertEqual(politics.canonical_funding(raw), want, raw)

    def test_choosing_between_two_sources_is_left_for_the_council(self):
        self.assertEqual(politics.canonical_funding("reserves or domestic_bonds"), "reserves or domestic_bonds")


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.w = new_world(4, 12)

    def test_non_object_motion_candidate_is_safe_at_parser_boundary(self):
        normalized = actions.normalize_motion_v2(self.w, "not a motion object")
        self.assertEqual(normalized["type"], "")
        self.assertEqual(normalized["action"], {})
        self.assertEqual(normalized["text"], "")

    def test_assign_office_display_name_validates_and_canonicalizes(self):
        mo = actions.normalize_motion_v2(self.w, {"type": "assign_office", "subject": "Head of Government",
                                                  "value": "A", "text": "appoint"})
        self.assertEqual(mo["subject"], "head")
        self.assertIsNone(politics.validate_motion_detail(self.w, {**mo, "passed": False}))

    def test_diplomacy_prose_subject_routes_to_the_engine_act(self):
        mo = actions.normalize_motion_v2(self.w, {"type": "diplomacy", "subject": "trade_talks with Dorsania",
                                                  "value": "", "text": "open talks"})
        self.assertEqual(mo["subject"], "trade_talks")

    def test_ambiguous_funding_still_rejected(self):
        verdict = politics.validate_motion_detail(self.w, {"type": "settle_arrears",
                                                           "subject": "reserves or domestic_bonds",
                                                           "value": "all", "text": "pay everything"})
        self.assertEqual(verdict["reason_code"], "UNKNOWN_FUNDING")

    def test_office_qualified_policy_names_resolve_and_can_be_enacted(self):
        for subject, value, lever in (("interior:protest_response", "negotiate", "protest_response"),
                                      ("interior:surveillance", "low", "surveillance"),
                                      ("interior.arrests", "targeted", "arrests"),
                                      ("interior/arrests", "targeted", "arrests"),
                                      ("army/recruitment", "partial", "recruitment")):
            with self.subTest(subject=subject):
                mo = actions.normalize_motion_v2(self.w, {"type": "set_policy", "subject": subject,
                                                          "value": value, "text": "respond to current pressure"})
                self.assertEqual(mo["subject"], lever)
                self.assertIsNone(politics.validate_motion_detail(self.w, {**mo, "passed": True}))

    def test_office_qualified_unknown_or_wrong_office_is_not_guessed(self):
        self.assertEqual(politics.canonical_lever("army:protest_response"), "army:protest_response")
        self.assertEqual(politics.canonical_lever("interior:warp_drive"), "interior:warp_drive")


class Program(unittest.TestCase):
    def setUp(self):
        self.w = new_world(4, 12)

    def test_package_sets_several_levers_at_once(self):
        mo = actions.normalize_motion_v2(self.w, {
            "type": "program", "subject": "austerity", "value": "", "text": "fiscal consolidation",
            "action": {"measures": [{"lever": "tax", "value": "0.30"}, {"lever": "welfare", "value": "0.03"}]}})
        self.assertIsNone(politics.validate_motion_detail(self.w, {**mo, "passed": True}))
        politics.apply_motion(self.w, mo)
        self.assertAlmostEqual(self.w.policy.tax, 0.30)
        self.assertAlmostEqual(self.w.policy.welfare, 0.03)

    def test_package_accepts_office_qualified_measure_names(self):
        mo = actions.normalize_motion_v2(self.w, {
            "type": "program", "subject": "security response", "value": "", "text": "a response package",
            "action": {"measures": [{"lever": "interior:protest_response", "value": "negotiate"},
                                     {"lever": "army/recruitment", "value": "partial"}]}})
        self.assertIsNone(politics.validate_motion_detail(self.w, {**mo, "passed": True}))
        politics.apply_motion(self.w, mo)
        self.assertEqual(self.w.policy.protest_response, "negotiate")
        self.assertEqual(self.w.policy.recruitment, "partial")

    def test_one_bad_lever_blocks_the_whole_package(self):
        mo = {"type": "program", "subject": "", "value": "", "text": "",
              "action": {"measures": [{"lever": "tax", "value": "0.30"},
                                      {"lever": "communist_seizure", "value": "1"}]}}
        before = self.w.policy.tax
        verdict = politics.validate_motion_detail(self.w, {**mo, "passed": True})
        self.assertEqual(verdict["reason_code"], "UNKNOWN_LEVER")
        politics.apply_motion(self.w, mo)          # never validated -> applies nothing
        self.assertEqual(self.w.policy.tax, before)

    def test_blank_text_cannot_enter_the_monthly_agenda(self):
        from karamaniya import deliberation
        verdict, _ = deliberation.check(self.w, {"type": "program", "subject": "austerity", "value": "",
                                                  "text": "", "action": {"measures": [{"lever": "tax", "value": "0.3"}]}},
                                         [], "A")
        self.assertEqual(verdict["reason_code"], "EMPTY_MOTION_TEXT")


if __name__ == "__main__":
    unittest.main()
