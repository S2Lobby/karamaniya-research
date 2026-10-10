"""World engine 17: the fine print of a motion becomes a real offer (fine_print.py).

In run 20261010-070501-seed1, Month 5, the council passed 5-0 a formal protest to the Solvaran Union over a shooting on
the eastern border. Its text also demanded a joint fact-finding investigation with published findings, a mutual
stand-down of patrols near the incident sector and a reaffirmation of the non-aggression pact. The engine executed it
as a plain protest: nobody reacted, and army loyalty kept rising. These tests pin down what the clauses are, what
passing them does to the ministries, the public and the fronts, and what the other side and the country do in answer.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import (agents, director, fine_print, foreign, military, ministries,  # noqa: E402
                        motion_actions, politics, public_mood, standing)
from karamaniya.world import new_world  # noqa: E402

UNION = motion_actions.SOLVARAN_UNION
MONTH5 = ("Issue a formal protest to the Union over the Month 5 shooting on the eastern border that left casualties "
          "on our side. Demand a joint fact-finding investigation with published findings within one month, mutual "
          "stand-down of patrols near the incident sector pending findings, and a reaffirmation of the non-aggression "
          "pact. This is a lawful, measured response; it must not become a pretext for escalation by either side.")
TERMS = ["Joint fact-finding investigation with published findings within one month",
         "Mutual stand-down of patrols near the incident sector pending findings",
         "Reaffirmation of the non-aggression pact"]
MONTH3_AUDIT = ("Independent two-month audit of Army procurement since Month 1, and of earlier contracts linked to the "
                "same suppliers. The council, not Army Command, chooses the auditors")


def world(seed: int = 5):
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    agents.ensure(w)                  # the office audiences (senior officers, sailors ...) follow the offices held
    return w


def protest(text: str = MONTH5, terms=TERMS, target: str = UNION, subject: str = "diplomatic_protest", **extra):
    mo = {"id": "M5", "proposer": "C", "type": "diplomacy", "subject": subject, "value": "", "text": text,
          "action": {"action_type": "diplomatic_protest", "target": target, "terms": list(terms)},
          "votes": {mid: "yes" for mid in "ABCDE"}, "passed": True,
          "summary": "protest to the Union over the border shooting"}
    mo.update(extra)
    return mo


def detection_text() -> str:
    return MONTH5 + ". " + ". ".join(TERMS)


def inquiries(w) -> list:
    return w.institutions.get(fine_print.KEY, {}).get("inquiries", [])


def standdowns(w) -> list:
    return w.institutions.get(fine_print.KEY, {}).get("standdowns", [])


def reactions(w) -> list:
    return [(r["kind"], r["where"], r["value"], r["months_left"], r["reason"]) for r in public_mood.state(w)]


class Detection(unittest.TestCase):
    def test_the_month_5_protest_offers_a_joint_inquiry_and_a_stand_down_to_the_union(self):
        w = world()
        self.assertEqual(fine_print.clauses(w, detection_text(), "union"), ["joint_inquiry", "stand_down"])
        self.assertEqual(fine_print.motion_clauses(w, protest()), ["joint_inquiry", "stand_down"])

    def test_a_text_addressed_to_the_league_offers_nothing(self):
        self.assertEqual(fine_print.clauses(world(), detection_text(), "league"), [])

    def test_a_clause_stated_only_to_rule_it_out_does_not_count(self):
        self.assertEqual(fine_print.clauses(world(), "We reject any joint inquiry and there will be no withdrawal of "
                                                     "our troops.", "union"), [])

    def test_keeping_soldiers_on_their_own_side_of_the_line_is_not_a_stand_down(self):
        self.assertEqual(fine_print.clauses(world(), "keep our soldiers on their own side of the line", "union"), [])

    def test_an_inspection_regime_is_an_offer_of_its_own(self):
        text = "Accept an inspection regime for Union inspectors on Karamanian shipping."
        self.assertEqual(fine_print.clauses(world(), text, "union"), ["foreign_inspection"])

    def test_the_month_3_internal_audit_offers_nothing(self):
        self.assertEqual(fine_print.clauses(world(), MONTH3_AUDIT, "union"), [])

    def test_a_world_from_before_architecture_2_reads_nothing(self):
        w = world()
        w.agent_architecture_version = 1
        self.assertEqual(fine_print.clauses(w, detection_text(), "union"), [])


class PassingTheProtest(unittest.TestCase):
    def passed(self, mo=None, seed: int = 5):
        w = world(seed)
        w.month = 4
        return w, politics.apply_motion(w, mo or protest())

    def test_army_and_interior_grievance_rise_by_the_stated_amounts(self):
        w, _ = self.passed()
        self.assertAlmostEqual(ministries.grievance(w, "army"), .06 + .05)
        self.assertAlmostEqual(ministries.grievance(w, "interior"), .04)

    def test_the_public_reacts_to_the_inquiry_and_the_stand_down(self):
        w, _ = self.passed()
        self.assertIn(("approval", "ident:karamanian", -.004, 3, "fine_print:joint_inquiry"), reactions(w))
        self.assertIn(("approval", "ident:karamanian", -.002, 2, "fine_print:stand_down"), reactions(w))

    def test_propaganda_rises_by_the_inquiry(self):
        w, _ = self.passed()
        self.assertAlmostEqual(w.dip.propaganda, .03)

    def test_the_proposal_keeps_its_clauses_and_the_result_names_them(self):
        w, result = self.passed()
        self.assertEqual(w.dip.proposals[-1]["clauses"], ["joint_inquiry", "stand_down"])
        self.assertTrue(result.endswith("; it also offers a joint inquiry, a stand-down of Karamanian patrols"), result)
        offers = [e for e in w.events if e["kind"] == "fine_print"]
        self.assertEqual(len(offers), 2)
        self.assertTrue(all(e["importance"] == 2 for e in offers))

    def test_a_protest_with_no_such_clauses_changes_none_of_it(self):
        mo = protest("Formal protest to the Solvaran Union over the shooting on the eastern border that left "
                     "casualties on our side.", terms=["Compensation for the families of the dead"])
        w, result = self.passed(mo)
        self.assertEqual(w.dip.proposals[-1]["clauses"], [])
        self.assertNotIn("it also offers", result)
        self.assertEqual((ministries.grievance(w, "army"), ministries.grievance(w, "interior")), (0.0, 0.0))
        self.assertEqual(public_mood.state(w), [])
        self.assertEqual(w.dip.propaganda, 0.0)

    def test_a_protest_to_the_league_is_not_an_offer(self):
        w, result = self.passed(protest(target=motion_actions.MARITIME_LEAGUE))
        self.assertEqual(w.dip.proposals[-1]["clauses"], [])
        self.assertNotIn("it also offers", result)
        self.assertEqual(ministries.grievance(w, "army"), 0.0)

    def test_an_inspection_regime_costs_the_navy_and_the_public_and_is_recorded_as_accepted(self):
        mo = protest("Accept an inspection regime for Union inspectors on Karamanian shipping, under our port "
                     "authority.", terms=[])
        w, result = self.passed(mo)
        self.assertIn("it also offers an inspection regime over Karamanian shipping", result)
        self.assertAlmostEqual(ministries.grievance(w, "navy"), .06)
        self.assertIn(("approval", "ident:karamanian", -.003, 3, "fine_print:foreign_inspection"), reactions(w))
        director._answer_proposals(w)
        self.assertEqual(w.institutions[fine_print.KEY]["inspections"], [{"party": "union", "from": 4}])
        self.assertTrue(any("accepts an inspection regime" in m["text"] for m in w.dip.inbox))


class TheStaffEstimate(unittest.TestCase):
    def test_the_army_holder_is_told_a_yes_will_sour_its_senior_officers(self):
        w = world()
        # The protest itself is read as a firm act (engine 17's audiences); its fine print as two concessions.
        self.assertEqual(standing.motion_tags(w, protest()), ["protest", "foreign_inquiry", "stand_down"])
        ex = standing.vote_exposure(w, "D", protest())
        self.assertLess(ex["yes"]["senior officers"], 0)
        self.assertGreater(ex["no"]["senior officers"], 0)
        self.assertIn("a yes would sour", standing.exposure_text(w, "D", [protest()]))

    def test_every_clause_tag_has_an_audience_table(self):
        for tag in standing.FINE_PRINT_TAGS.values():
            self.assertIn(tag, standing.ACTION_EFFECTS)


class Replies(unittest.TestCase):
    def answered(self, seed: int, weariness: float | None = None, mo=None):
        """The protest passed in Month 5 (index 4) and answered by the council that month."""
        w = world(seed)
        w.month = 4
        if weariness is not None:
            w.dip.union_weariness = weariness
        politics.apply_motion(w, mo or protest())
        director._answer_proposals(w)
        return w

    def test_an_accepted_inquiry_reports_two_months_later_with_its_finding(self):
        # Seed 4: the Union accepts (first draw .05 of .75) and the finding in Month 7 blames Karamanian soldiers (.22).
        w = self.answered(4)
        self.assertEqual(inquiries(w), [{"party": "union", "from": 4, "reports": 6}])
        self.assertTrue(any("accepts a joint inquiry" in m["text"] for m in w.dip.inbox))
        propaganda, army = w.dip.propaganda, ministries.grievance(w, "army")
        w.month = 5
        fine_print.monthly(w)
        self.assertEqual([e for e in w.events if e["kind"] == "inquiry_finding"], [])
        w.month = 6
        fine_print.monthly(w)
        found = [e for e in w.events if e["kind"] == "inquiry_finding"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["finding"], "karamanian")
        self.assertEqual(found[0]["importance"], 2)
        self.assertIn("blamed Karamanian soldiers", found[0]["text"])
        self.assertAlmostEqual(w.dip.propaganda, propaganda + .06)
        self.assertAlmostEqual(ministries.grievance(w, "army"), army + .04)
        self.assertIn(("approval", "ident:karamanian", -.004, 3, "fine_print:inquiry_finding"), reactions(w))
        self.assertEqual(inquiries(w), [])

    def test_an_inquiry_that_blames_the_other_side_rallies_the_country(self):
        # Seed 12: accepted in Month 5, and the finding in Month 7 blames the other side (.99).
        w = self.answered(12)
        self.assertEqual(inquiries(w), [{"party": "union", "from": 4, "reports": 6}])
        propaganda = w.dip.propaganda
        w.month = 6
        fine_print.monthly(w)
        self.assertEqual([e["finding"] for e in w.events if e["kind"] == "inquiry_finding"], ["other"])
        self.assertAlmostEqual(w.dip.rally, .05)
        self.assertAlmostEqual(w.dip.propaganda, max(0.0, propaganda - .05))

    def test_a_dismissed_inquiry_is_not_opened(self):
        # Seed 13: the first draw (.99) is a refusal, so the Union dismisses the call.
        w = self.answered(13)
        self.assertEqual(inquiries(w), [])
        self.assertTrue(any("dismisses the call for a joint inquiry" in m["text"] for m in w.dip.inbox))

    def test_a_stand_down_is_matched_only_by_a_weary_union(self):
        for weariness, matched in ((.6, True), (.2, False)):
            with self.subTest(weariness=weariness):
                w = self.answered(5, weariness)
                self.assertEqual({x["reciprocated"] for x in standdowns(w)}, {matched})
                # Army grievance: .11 from the offer, and .03 more when the other side does not match it.
                self.assertAlmostEqual(ministries.grievance(w, "army"), .11 if matched else .14)

    def test_dorsania_matches_a_stand_down_only_when_it_trusts_karamaniya(self):
        for trust, matched in ((.7, True), (.3, False)):
            with self.subTest(trust=trust):
                w = world(5)
                w.month = 4
                w.foreign["actors"]["dorsania"]["relations"]["karamaniya"]["trust"] = trust
                politics.apply_motion(w, protest(target=motion_actions.DORSANIA))
                director._answer_proposals(w)
                self.assertEqual({x["reciprocated"] for x in standdowns(w)}, {matched})

    def test_the_council_step_reports_an_inquiry_in_the_month_it_is_due(self):
        w = self.answered(4)
        w.month = 6
        director.prepare_external(w)
        self.assertEqual([e["finding"] for e in w.events if e["kind"] == "inquiry_finding"], ["karamanian"])
        self.assertEqual(inquiries(w), [])

    def test_the_council_step_answers_the_print_of_the_proposals_it_holds(self):
        w = world(4)
        w.month = 4
        politics.apply_motion(w, protest())
        self.assertEqual(w.dip.proposals[-1]["clauses"], ["joint_inquiry", "stand_down"])
        director.prepare_external(w)           # the council's monthly step answers the proposals it holds
        self.assertEqual(inquiries(w), [{"party": "union", "from": 4, "reports": 6}])
        self.assertEqual(w.dip.proposals, [])


class Defence(unittest.TestCase):
    def test_a_stood_down_front_is_held_more_thinly_until_the_stand_down_runs_out(self):
        w = world()
        w.month = 4
        before = military._front_defence(w, "east")[3]
        politics.apply_motion(w, protest())
        self.assertEqual(fine_print.defence_factor(w, "east"), .85)
        self.assertEqual(fine_print.defence_factor(w, "north"), 1.0)
        self.assertAlmostEqual(military._front_defence(w, "east")[3], before * .85, places=9)
        w.month = 7                            # the stand-down ran from Month 5 to Month 7
        self.assertEqual(fine_print.defence_factor(w, "east"), 1.0)
        self.assertAlmostEqual(military._front_defence(w, "east")[3], before, places=9)
        fine_print.monthly(w)
        self.assertEqual(standdowns(w), [])

    def test_a_stand_down_the_other_side_matches_does_not_thin_the_front(self):
        w = world()
        w.month = 4
        w.dip.union_weariness = .6
        politics.apply_motion(w, protest())
        director._answer_proposals(w)
        self.assertEqual(fine_print.defence_factor(w, "east"), 1.0)

    def test_a_stand_down_names_its_front_or_takes_the_live_border_incident_or_both(self):
        w = world()
        w.month = 4
        w.dilemmas = {"active": [{"kind": "border_incident", "region": "kessel", "month": 4}]}
        politics.apply_motion(w, protest(text="Mutual stand-down of patrols pending findings, and a reaffirmation of "
                                              "the non-aggression pact.", terms=[]))
        self.assertEqual([x["front"] for x in standdowns(w)], ["north"])
        self.assertEqual([x["until"] for x in standdowns(w)], [6])
        fresh = world()
        fresh.month = 4
        politics.apply_motion(fresh, protest(text="Mutual stand-down of patrols pending findings.", terms=[]))
        self.assertEqual(sorted(x["front"] for x in standdowns(fresh)), ["east", "north"])


class AnAuditThatInvitesInvestigators(unittest.TestCase):
    def test_an_audit_inviting_union_investigators_is_a_joint_inquiry_already_accepted(self):
        w = world()
        w.month = 4
        mo = {"id": "M7", "proposer": "E", "type": "investigation", "subject": "army", "value": "open",
              "text": "Open a joint inquiry with Solvaran Union investigators into the border shooting.",
              "votes": {"A": "yes"}}
        result = politics.apply_motion(w, mo)
        self.assertIn("it also offers a joint inquiry", result)
        self.assertEqual(inquiries(w), [{"party": "union", "from": 4, "reports": 6}])
        self.assertAlmostEqual(ministries.grievance(w, "army"), .06)
        self.assertEqual(standing.motion_tags(w, mo), ["audit_army", "foreign_inquiry"])

    def test_the_month_3_audit_is_only_an_audit(self):
        w = world()
        w.month = 2
        mo = {"id": "M3", "proposer": "E", "type": "investigation", "subject": "army", "value": "open",
              "text": MONTH3_AUDIT, "votes": {"A": "yes"}}
        result = politics.apply_motion(w, mo)
        self.assertNotIn("it also offers", result)
        self.assertEqual(inquiries(w), [])
        self.assertEqual(ministries.grievance(w, "army"), 0.0)
        self.assertEqual(standing.motion_tags(w, mo), ["audit_army"])


class OldWorlds(unittest.TestCase):
    def test_a_world_from_before_architecture_2_is_left_as_it_was(self):
        w = world()
        w.month = 4
        w.agent_architecture_version = 1
        result = politics.apply_motion(w, protest())
        self.assertNotIn("it also offers", result)
        self.assertEqual(w.dip.proposals[-1]["clauses"], [])
        self.assertEqual((ministries.grievance(w, "army"), w.dip.propaganda, public_mood.state(w)), (0.0, 0.0, []))
        self.assertEqual(fine_print.defence_factor(w, "east"), 1.0)
        # A protest is still read as a protest; no clause of its fine print is.
        self.assertEqual(standing.motion_tags(w, protest()), ["protest"])
        fine_print.reply(w, {"clauses": ["joint_inquiry"], "party": "union", "month": 4})
        fine_print.monthly(w)
        self.assertNotIn(fine_print.KEY, w.institutions)


if __name__ == "__main__":
    unittest.main()
