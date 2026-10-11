"""World engine 19, slice A: does a motion do what its text says?

Each class pins one audit finding of engine 18 (docs/AUDIT_ENGINE18.md) and its proof script.
"""
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import actions, errors, fine_print, foreign, motion_actions, politics  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def world(seed: int = 11):
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.agent_architecture_version = 2
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def protest_motion(text: str) -> dict:
    return {"type": "diplomacy", "subject": "diplomatic_protest", "value": "", "text": text, "proposer": "A",
            "action": {"action_type": "diplomatic_protest", "target": "Solvaran Union", "issue": "border shooting",
                       "terms": []}}


class MO1RejectionIsNotAnOffer(unittest.TestCase):
    """A motion that rejects a joint inquiry or a stand-down does not offer it (poc_1)."""

    def test_a_rejection_more_than_four_words_before_the_act_rules_it_out(self):
        for text in ("We reject the Union's call for a joint inquiry into the shooting.",
                     "The council rejects the Union's demand for a joint inquiry into the border shooting.",
                     "Karamaniya will not accept the Union's proposal for a joint investigation of the incident."):
            with self.subTest(text=text):
                self.assertEqual(fine_print.clauses(world(), text, "union"), [])

    def test_a_rejected_stand_down_is_not_offered(self):
        self.assertEqual(fine_print.clauses(
            world(), "We reject the Union's demand for a stand-down of Karamanian patrols in the north.", "union"), [])

    def test_a_rejection_in_the_same_sentence_as_the_offer_rules_out_only_what_it_governs(self):
        self.assertEqual(fine_print.clauses(
            world(), "We offer a joint inquiry and will not accept a stand-down.", "union"), ["joint_inquiry"])

    def test_a_rejection_joined_by_but_does_not_rule_out_the_offer_after_it(self):
        self.assertEqual(fine_print.clauses(
            world(), "We reject the joint inquiry, but we propose a stand-down of our patrols.", "union"),
            ["stand_down"])

    def test_true_offers_still_read_as_offers(self):
        self.assertEqual(fine_print.clauses(world(), "We propose a joint inquiry into the shooting.", "union"),
                         ["joint_inquiry"])

    def test_a_passed_rejection_offers_nothing_and_raises_no_propaganda(self):
        w = world()
        before = w.dip.propaganda
        politics.apply_motion(w, protest_motion(
            "Formal protest to the Solvaran Union over the border shooting. The council rejects the Union's demand "
            "for a joint inquiry."))
        self.assertEqual(fine_print.state(w)["inquiries"], [])
        self.assertEqual(w.dip.propaganda, before)


TALKS = "Ask the Solvaran Union for talks on our future. "


def talks_motion(text: str) -> dict:
    return {"id": "M2", "type": "diplomacy", "subject": "status_talks", "value": "", "text": text,
            "action": {"action_type": "status_talks", "target": "Solvaran Union"}}


class MO15OneNegation(unittest.TestCase):
    """The prose check and the fine print read one negation vocabulary (poc_15)."""

    def test_talks_that_refuse_or_decline_an_act_are_tabled(self):
        for text in ("We refuse any federation.", "We decline any federation.",
                     "Karamaniya will give up nothing in Kessel Valley.",
                     "We will not seek military aid.", "We will not accept a grain deal.",
                     "Without a tariff on our exports, we will hold firm.",
                     "We will not accept any trade deal.", "We won't accept any federation.",
                     "We cannot accept a federation."):
            with self.subTest(text=text):
                self.assertIsNone(motion_actions.conflict(world(), talks_motion(TALKS + text)))

    def test_a_refused_act_is_not_named_in_the_prose(self):
        w = world()
        self.assertEqual(motion_actions.prose_intent(w, TALKS + "We refuse any federation.")["actions"], [])
        self.assertEqual(motion_actions.prose_intent(
            w, TALKS + "Karamaniya will give up nothing in Kessel Valley.")["actions"], [])

    def test_a_cession_that_names_its_land_is_still_read(self):
        self.assertEqual(motion_actions.prose_intent(world(), "We give up Kessel Valley to the Union.")["actions"],
                         ["cede_region"])

    def test_the_fine_print_reads_the_same_refusals(self):
        w = world()
        for text in ("We decline a joint inquiry into the shooting.",
                     "We will concede nothing on a stand-down of our patrols.",
                     "We oppose a joint inquiry into the shooting."):
            with self.subTest(text=text):
                self.assertEqual(fine_print.clauses(w, text, "union"), [])

    def test_affirming_idioms_are_not_refusals(self):
        w = world()
        self.assertEqual(fine_print.clauses(
            w, "We will accept nothing short of a joint inquiry into the shooting.", "union"), ["joint_inquiry"])
        self.assertEqual(fine_print.clauses(
            w, "We offer no less than a joint inquiry into the shooting.", "union"), ["joint_inquiry"])
        self.assertEqual(fine_print.clauses(
            w, "We propose not only a joint inquiry into the shooting, but a stand-down of our patrols.", "union"),
            ["joint_inquiry", "stand_down"])
        self.assertEqual(motion_actions.prose_intent(
            w, "Karamaniya accepts nothing short of a federation.")["actions"], ["federation"])


def motion(kind: str, subject: str, value: str, text: str) -> dict:
    return {"id": "M4", "type": kind, "subject": subject, "value": value, "text": text, "proposer": "A"}


class MO19TheTextNamesTheAct(unittest.TestCase):
    """Appointments, expulsions, referendums and emergencies are checked against their text (poc_19)."""

    def codes(self, mo: dict) -> list:
        clash = motion_actions.conflict(world(), mo)
        return [] if clash is None else [reason["code"] for reason in clash["reasons"]]

    def test_an_appointment_names_the_member_the_text_names(self):
        self.assertEqual(self.codes(motion("assign_office", "navy", "B",
                                           "Appoint member C as commander of the navy.")), ["APPOINTEE_MISMATCH"])

    def test_an_appointment_names_the_office_the_text_names(self):
        self.assertEqual(self.codes(motion("assign_office", "navy", "B",
                                           "Appoint member B as commander of the army.")), ["OFFICE_MISMATCH"])

    def test_an_expulsion_expels_the_member_the_text_names(self):
        self.assertEqual(self.codes(motion("expel", "B", "", "Expel member C from the government.")),
                         ["EXPULSION_MISMATCH"])

    def test_a_referendum_on_another_question_than_independence_is_a_conflict(self):
        self.assertEqual(self.codes(motion("referendum", "", "",
                                           "Hold a referendum on a federation with the Solvaran Union.")),
                         ["REFERENDUM_QUESTION_MISMATCH"])

    def test_a_referendum_question_ends_at_a_comma_so_a_later_clause_is_not_read_as_a_question(self):
        self.assertEqual(self.codes(motion("referendum", "", "",
                                           "Hold a referendum on independence, and keep the federation talks closed.")),
                         [])

    def test_lifting_the_emergency_switched_on_or_imposing_it_switched_off_is_a_conflict(self):
        self.assertEqual(self.codes(motion("constitution", "emergency", "on",
                                           "Lift the state of emergency and return to ordinary government.")),
                         ["EMERGENCY_MISMATCH"])
        self.assertEqual(self.codes(motion("constitution", "emergency", "off",
                                           "Impose a state of emergency in the north.")), ["EMERGENCY_MISMATCH"])
        self.assertEqual(self.codes(motion("emergency_measure", "curfew", "on", "Lift the night curfew.")),
                         ["EMERGENCY_MISMATCH"])

    def test_a_motion_whose_text_matches_its_fields_is_not_flagged(self):
        for mo in (motion("assign_office", "navy", "B", "Appoint member B as commander of the navy."),
                   motion("expel", "B", "", "Expel member B from the government."),
                   motion("referendum", "", "", "Hold a referendum on independence."),
                   motion("referendum", "", "", "Hold a referendum on whether to remain independent."),
                   motion("constitution", "emergency", "off", "Lift the state of emergency."),
                   motion("constitution", "emergency", "on", "Declare a state of emergency in the north."),
                   motion("emergency_measure", "curfew", "on", "Impose a night curfew in affected regions."),
                   motion("emergency_measure", "curfew", "off", "Lift the night curfew."),
                   motion("constitution", "emergency", "on", "Keep the state of emergency and lift the curfew.")):
            with self.subTest(text=mo["text"]):
                self.assertEqual(self.codes(mo), [])

    def test_the_repair_says_what_the_text_and_the_motion_disagree_on(self):
        w = world()
        clash = motion_actions.conflict(w, motion("assign_office", "navy", "B",
                                                  "Appoint member C as commander of the navy."))
        self.assertIn("the text appoints member C, but the motion appoints B", motion_actions.repair_request(w, clash))


def rate_motion(text: str, value: str = "0.11") -> dict:
    return {"id": "M5", "type": "set_policy", "subject": "rate", "value": value, "text": text, "proposer": "A"}


class MO12PolicyFigures(unittest.TestCase):
    """A text that moves a setting from one figure to another must agree with the value it sets (poc_12)."""

    MOVES = ("Raise the rate from 6% to 7%.", "Raise the rate from 6 percent to 7 percent.",
             "Raise the rate from 6 to 7%.", "Raise the rate from 0.06 to 0.07.",
             "Raise the rate from 6% up to 7%.", "Raise the rate 6% -> 7%.")

    def test_every_phrasing_of_a_move_to_seven_percent_conflicts_with_a_value_of_eleven(self):
        for text in self.MOVES:
            with self.subTest(text=text):
                clash = motion_actions.conflict(world(), rate_motion(text))
                self.assertIsNotNone(clash)
                self.assertEqual(clash["reasons"][0]["code"], "POLICY_FIGURES_MISMATCH")

    def test_the_same_moves_agree_with_a_value_of_seven_percent(self):
        for text in self.MOVES:
            with self.subTest(text=text):
                self.assertIsNone(motion_actions.conflict(world(), rate_motion(text, "0.07")))

    def test_the_conflict_quotes_the_move_it_read(self):
        clash = motion_actions.conflict(world(), rate_motion("Raise the rate from 6 percent to 7 percent."))
        self.assertIn("the text moves rate 6 percent to 7 percent, but the motion sets rate to 0.11",
                      clash["reasons"][0]["detail"])

    def test_figures_that_are_not_shares_are_not_read_as_one(self):
        self.assertIsNone(motion_actions.conflict(world(), rate_motion("Review the rate from 6 to 7 months.")))


def protest_intake(w, text: str, issue=None) -> dict:
    action = {"action_type": "diplomatic_protest", "target": "Solvaran Union"}
    if issue:
        action["issue"] = issue
    raw = {"type": "diplomacy", "subject": "diplomatic_protest", "value": "", "text": text, "action": action}
    return {**actions.normalize_motion_v2(w, raw), "proposer": "A", "passed": True}


class MO21DuplicateProtests(unittest.TestCase):
    """Two different protests to one power in one month are two acts when neither names an issue (poc_21)."""

    FIRST = "Formal protest to the Solvaran Union over unauthorised inspections of our merchant ships."
    SECOND = "Formal protest to the Solvaran Union over the shooting on the eastern border."

    def test_two_protests_about_different_things_are_two_acts(self):
        w = world()
        first, second = protest_intake(w, self.FIRST), protest_intake(w, self.SECOND)
        executed = {}
        self.assertIsNone(motion_actions.validate_execution(w, dict(first), executed))
        executed[motion_actions.execution_key(w, first)] = "M1"
        self.assertIsNone(motion_actions.validate_execution(w, dict(second), executed))
        self.assertNotEqual(motion_actions.execution_key(w, first), motion_actions.execution_key(w, second))

    def test_the_same_protest_twice_in_a_month_is_still_one_act(self):
        w = world()
        first, again = protest_intake(w, self.FIRST), protest_intake(w, self.FIRST)
        executed = {motion_actions.execution_key(w, first): "M1"}
        self.assertEqual(motion_actions.validate_execution(w, dict(again), executed)["code"], "DUPLICATE_ACTION")

    def test_protests_that_name_different_issues_stay_apart(self):
        w = world()
        first = protest_intake(w, self.FIRST, issue="merchant inspections")
        second = protest_intake(w, self.SECOND, issue="border shooting")
        self.assertNotEqual(motion_actions.execution_key(w, first), motion_actions.execution_key(w, second))


class MO24StandDownInOtherWords(unittest.TestCase):
    """A stand-down written in other words is an offer of a stand-down (poc_24)."""

    def test_the_other_wordings_are_offers(self):
        for text in ("Halt our patrols in the incident sector until the findings are published.",
                     "Suspend patrols in the incident sector pending findings.",
                     "Pull our patrols back from the incident sector pending findings.",
                     "Pull all our forces well back from the eastern front pending findings.",
                     "Stand our forces down on the eastern front until the findings are published."):
            with self.subTest(text=text):
                self.assertEqual(fine_print.clauses(world(), text, "union"), ["stand_down"])

    def test_the_wordings_already_read_still_are(self):
        for text in ("A mutual stand-down of patrols in the incident sector pending findings.",
                     "Withdraw our troops from the incident sector pending findings."):
            with self.subTest(text=text):
                self.assertEqual(fine_print.clauses(world(), text, "union"), ["stand_down"])

    def test_a_refused_paraphrase_is_not_an_offer(self):
        for text in ("We will not halt our patrols in the incident sector.",
                     "We refuse to pull our patrols back from the incident sector."):
            with self.subTest(text=text):
                self.assertEqual(fine_print.clauses(world(), text, "union"), [])

    def test_pulling_back_from_talks_names_no_forces(self):
        self.assertEqual(fine_print.clauses(world(), "We pull back from the talks on the border.", "union"), [])


class MO23TheActorNamedFirst(unittest.TestCase):
    """A target that names two actors is the one it names first (poc_23)."""

    CASES = (("Veleria (a Union member)", motion_actions.VELERIA),
             ("Veleria, a member of the Union", motion_actions.VELERIA),
             ("the Maritime League (the Union's partner)", motion_actions.MARITIME_LEAGUE),
             ("the Union, on behalf of Veleria", motion_actions.SOLVARAN_UNION),
             ("Veleria", motion_actions.VELERIA), ("the Veleria government", motion_actions.VELERIA),
             ("Solvaran Union", motion_actions.SOLVARAN_UNION), ("the Maritime League", motion_actions.MARITIME_LEAGUE))

    def test_the_earliest_actor_named_is_the_target(self):
        w = world()
        for raw, want in self.CASES:
            with self.subTest(raw=raw):
                self.assertEqual(motion_actions._canonical_actor(w, raw), want)

    def test_the_live_intake_keeps_the_actor_the_delegate_named_first(self):
        w = world()
        mo = actions.normalize_motion_v2(w, {
            "type": "diplomacy", "subject": "non_aggression", "value": "",
            "text": "Propose a non-aggression pact on the border.",
            "action": {"action_type": "non_aggression_pact", "target": "Veleria (a Union member)"}})
        self.assertEqual(motion_actions.structured_action(w, mo)["target"], motion_actions.VELERIA)


class MO20JointCommission(unittest.TestCase):
    """A joint commission is an inquiry only when its sentence says what it is into (poc_20)."""

    def test_a_standing_joint_commission_on_trade_is_not_an_inquiry(self):
        self.assertEqual(fine_print.clauses(
            world(), "A joint commission on grain trade will be reconvened next month.", "dorsania"), [])
        self.assertEqual(fine_print.clauses(
            world(), "Reconvene the joint commission on tariffs with the Solvaran Union.", "union"), [])

    def test_a_joint_commission_into_the_incident_is_an_inquiry_in_either_order(self):
        self.assertEqual(fine_print.clauses(
            world(), "We propose a joint commission into the border shooting, with published findings.", "union"),
            ["joint_inquiry"])
        self.assertEqual(fine_print.clauses(
            world(), "The shooting calls for a joint commission of the two armies.", "union"), ["joint_inquiry"])

    def test_a_rejected_joint_commission_into_the_incident_is_not_offered(self):
        self.assertEqual(fine_print.clauses(
            world(), "We reject the joint commission into the border shooting.", "union"), [])
        self.assertEqual(fine_print.clauses(
            world(), "The shooting prompted us to reject a joint commission.", "union"), [])


class MO18EveryRefusalIsRegistered(unittest.TestCase):
    """A refusal code the engine raises is in the error taxonomy, so it is never recorded as unregistered (poc_18)."""

    def test_a_loan_without_an_amount_is_recorded_under_its_own_code(self):
        w = world()
        problem = politics.validate_motion_detail(w, {
            "type": "diplomacy", "subject": "loan", "value": "", "proposer": "A",
            "text": "Ask the Maritime League for a loan to cover the deficit.",
            "action": {"action_type": "loan_request", "target": "Maritime League"}})
        self.assertEqual(problem["reason_code"], "BAD_LOAN_AMOUNT")
        entry = errors.record(w, problem["reason_code"], problem["explanation"], member="A")
        self.assertEqual(entry["code"], "BAD_LOAN_AMOUNT")
        self.assertEqual(errors.summary(w)["unregistered"], 0)

    def test_every_code_the_engine_raises_a_refusal_or_a_record_with_is_registered(self):
        codes = set()
        for path in (Path(ROOT) / "karamaniya").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            codes.update(re.findall(r'_reject\(\s*"([A-Z_]+)"', source))
            codes.update(re.findall(r'\brecord\(\s*[\w.]+,\s*"([A-Z_]+)"', source))
        self.assertIn("BAD_LOAN_AMOUNT", codes)
        self.assertEqual(sorted(code for code in codes if not errors.is_registered(code)), [])


if __name__ == "__main__":
    unittest.main()
