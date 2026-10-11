"""World engine 22: the council can talk to Dorsania, and it can answer Dorsania's ultimatum.

Four faults, each read from run 20261011-105713-seed1 (world engine 21) and pinned here before its fix:

1. A protest, a non-aggression offer and the other acts addressed to Dorsania were refused for want of a verdict
   on the grain agreement in force (UNKNOWN_DEAL_INTENT, DEAL_ALREADY_EXISTS). A non-aggression pact could not be
   addressed to Dorsania at all.
2. No act answered an ultimatum. Dorsania's was answered through grain deals, and the replies that named it were
   refused as the wrong act.
3. A grain deal's other terms (troop withdrawals, dropping the ultimatum) were accepted without a word about them.
4. A tax rise tabled as a diplomatic protest passed the check that compares a motion's words with its action.

The texts below are the council's own words from that run. Where a motion was repaired once, the repaired form is
the one that was refused, so the repaired texts and actions are used.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, decision_context, director, foreign, foreign_force, motion_actions, politics  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

# Month 7 (month index 6): the protests to Dorsania. B's was tabled as sent; E's and C's were repaired once.
B_PROTEST_M7 = ("Karamaniya protests the armed attack on its eastern border, rejects Dorsania's blame, and demands a "
                "joint inquiry with neutral officers, an immediate pull-back of massed forces, and the withdrawal of "
                "the Month 9 ultimatum's demand for a foreign role in our internal affairs. Residents' rights are "
                "guaranteed under our own law. Refusal will be met with escalation.")
E_PROTEST_M7 = ("Protest Dorsania's ultimatum and the eastern border shooting. Demand withdrawal of the ultimatum, a "
                "joint inquiry with reciprocal access, immediate reciprocal pullback from the border, and recognition "
                "that citizenship and internal law are Karamaniya's sovereign responsibilities.")
C_PROTEST_M7 = ("Protest to Dorsania over Dorran March shooting: demand joint probe in 14 days, site access, halt "
                "eastern buildup.")
# Month 7 (month index 6): D's answer to the ultimatum, which passed and must keep passing.
D_STATUS_M7 = ("Answer the ultimatum with a counter-proposal: Karamaniya's Charter already guarantees equal rights and "
               "safety to all citizens, Imperial communities included; our status, laws and citizenship authority are "
               "not negotiable. We require withdrawal of the Month 9 ultimatum as a precondition. Talks then cover a "
               "joint inquiry into the border shooting, chaired by Karamaniyan officers with neutral observers, and a "
               "mutual troop pull-back, in exchange for the Union's affirmation of non-interference.")
# Month 8 (month index 7): A's non-aggression offer, as first tabled (its target was Dorsania).
A_NONAGGRESSION_M8 = ("Offer Dorsania a reciprocal non-aggression pact. Karamaniya guarantees equal rights and safety "
                      "for Imperial citizens under its law. Dorsania must recognize Karamaniya's sovereignty and pull "
                      "back its massed forces. Any verification must be by a mutually agreed neutral observer, invited "
                      "under Karamaniya's rules, with no foreign jurisdiction.")
# Month 8 (month index 7): B's tax rise, tabled with the action diplomatic_protest to the Solvaran Union.
B_TAX_M8 = ("Contain borrowing and prices without cutting soldiers' or police pay: raise the tax take to 0.30 of "
            "output, a step toward closing the monthly deficit.")
# Month 4 (month index 3): B's grain proposal to Dorsania, which asked for more than a grain agreement carries.
B_GRAIN_M4 = ("To Dorsania: Karamaniya will guarantee and publish the rights and safety of Imperial citizens under its "
              "own law, with no foreign role in our internal affairs. In return Dorsania withdraws the troops massed on "
              "the east border, drops the Month 9 ultimatum, and extends our grain agreement beyond Month 12 at current "
              "volume.")
B_GRAIN_M4_TERMS = ["Karamaniya guarantees and publishes Imperial citizens' rights under its own law",
                    "No foreign role in Karamaniya's internal affairs",
                    "Dorsania withdraws massed east-border troops and drops the ultimatum",
                    "Dorsania extends the grain agreement beyond Month 12 at current volume"]
# Dorsania's ultimatum, issued in Month 3 (index 2) with its deadline in Month 9 (index 8).
DORSANIA_ULTIMATUM = {"issued": 2, "deadline": 8,
                      "terms": "Guarantee the rights and safety of Imperial citizens in Karamaniya.",
                      "terms_id": "protect_imperial_citizens", "by": "dorsania"}


def world(month: int = 6, grain_until: int | None = 17, ultimatum: dict | None = None, nonaggression: bool = False):
    """A v2 world as the council sees it: the offices of the run, a grain agreement with Dorsania in force to
    `grain_until` (0-based), and the ultimatum, if any, that stands."""
    w = new_world(11, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.agent_architecture_version = 2
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    w.month = month
    if grain_until is not None:
        diplomacy = w.foreign["actors"]["dorsania"].setdefault("diplomacy", {})
        diplomacy.setdefault("commitments", []).append(
            {"type": "grain agreement", "month": 0, "until": grain_until, "partner": "karamaniya",
             "temporary": True, "message": "Inherited transition arrangement through the first harvest."})
    if ultimatum is not None:
        w.dip.ultimatum = dict(ultimatum)
    w.dip.nonaggression = nonaggression
    return w


def motion(text: str, subject: str, action_type: str, target: str, value: str = "", **action) -> dict:
    return {"id": "M1", "proposer": "B", "type": "diplomacy", "subject": subject, "value": value, "text": text,
            "action": {"action_type": action_type, "target": target, **action}}


class Bug1AgreementCheckIsForAgreements(unittest.TestCase):
    """The grain agreement is judged only when a motion makes or changes an agreement."""

    def test_a_protest_to_dorsania_is_not_refused_for_the_grain_agreement_in_force(self):
        for member, text, extra in (("B", B_PROTEST_M7, {}), ("E", E_PROTEST_M7, {}),
                                    ("C", C_PROTEST_M7, {"deal_action": "NEW_DEAL"})):
            with self.subTest(member=member):
                mo = motion(text, "diplomatic_protest", "diplomatic_protest", "DORSANIA", **extra)
                self.assertIsNone(politics.validate_motion_detail(world(), mo))

    def test_a_non_aggression_offer_to_dorsania_is_tabled_while_a_grain_agreement_stands(self):
        mo = actions.normalize_motion_v2(world(month=7), {
            "type": "diplomacy", "subject": "non_aggression", "value": "", "text": A_NONAGGRESSION_M8,
            "action": {"action_type": "non_aggression_pact", "target": "DORSANIA"}})
        self.assertIsNone(politics.validate_motion_detail(world(month=7), mo))

    def test_dorsania_is_a_valid_addressee_of_a_non_aggression_pact_as_veleria_is(self):
        targets = motion_actions.DIPLOMATIC_TARGETS["non_aggression_pact"]
        for actor in (motion_actions.DORSANIA, motion_actions.VELERIA, motion_actions.SOLVARAN_UNION):
            self.assertIn(actor, targets)

    def test_a_non_aggression_offer_to_dorsania_is_answered_by_the_union_and_recorded_as_dorsanias(self):
        w = world(month=7)
        politics.apply_motion(w, motion(A_NONAGGRESSION_M8, "non_aggression", "non_aggression_pact", "DORSANIA"))
        self.assertEqual([p["party"] for p in w.dip.proposals], ["dorsania"])
        director._answer_proposals(w)
        pact = [m for m in w.dip.inbox if m["from"] == w.names["union"]]
        self.assertEqual(len(pact), 1, "the Union answers the pact for its member")
        self.assertIn("non-aggression pact", pact[0]["text"])
        self.assertTrue(w.dip.nonaggression)
        # Dorsania answers the fine print of the offer (a stand-down), not the pact: that is the same for every offer.
        self.assertFalse(any(m["from"] == w.names["dorsania"] and "pact" in m["text"] for m in w.dip.inbox))

    def test_the_veleria_non_aggression_answer_is_the_unions_and_is_unchanged(self):
        w = world(month=7)
        mo = motion("Offer Veleria a reciprocal non-aggression pact.", "non_aggression", "non_aggression_pact", "VELERIA")
        self.assertIsNone(politics.validate_motion_detail(w, mo))
        politics.apply_motion(w, mo)
        director._answer_proposals(w)
        self.assertEqual({m["from"] for m in w.dip.inbox}, {w.names["union"]})

    def test_a_second_grain_agreement_is_still_refused(self):
        mo = motion("Propose a new grain agreement with Dorsania.", "grain_deal", "grain_deal", "DORSANIA",
                    deal_action="NEW_DEAL")
        self.assertEqual(politics.validate_motion_detail(world(), mo)["reason_code"], "DEAL_ALREADY_EXISTS")

    def test_the_month_7_status_talks_answering_the_ultimatum_still_pass(self):
        w = world(ultimatum=DORSANIA_ULTIMATUM)
        mo = motion(D_STATUS_M7, "status_talks", "status_talks", "SOLVARAN_UNION")
        self.assertIsNone(motion_actions.conflict(w, mo))
        self.assertIsNone(politics.validate_motion_detail(w, mo))


class Bug2AnUltimatumHasAnAnswer(unittest.TestCase):
    """ultimatum_reply: answered by the power that issued the ultimatum, read by its cabinet."""

    @staticmethod
    def reply(text: str, target: str = "DORSANIA", **action) -> dict:
        return motion(text, "ultimatum_reply", "ultimatum_reply", target, **action)

    def test_a_reply_needs_an_ultimatum_to_answer(self):
        detail = politics.validate_motion_detail(world(), self.reply("We reject the ultimatum."))
        self.assertEqual(detail["reason_code"], "NO_ULTIMATUM")

    def test_a_reply_goes_to_the_power_that_issued_the_ultimatum_or_to_the_union(self):
        w = world(ultimatum=DORSANIA_ULTIMATUM)
        for target in ("DORSANIA", "SOLVARAN_UNION"):
            with self.subTest(target=target):
                self.assertIsNone(politics.validate_motion_detail(w, self.reply("We reject the ultimatum.", target)))
        detail = politics.validate_motion_detail(w, self.reply("We reject the ultimatum.", "VELERIA"))
        self.assertEqual(detail["reason_code"], "ULTIMATUM_NOT_FROM_TARGET")
        self.assertIn("the ultimatum was issued by Dorsania", detail["explanation"])

    def test_a_veleria_ultimatum_is_answered_by_veleria_or_the_union_only(self):
        ultimatum = {**DORSANIA_ULTIMATUM, "by": "veleria", "terms_id": "status_talks",
                     "terms": "Open negotiations on Karamaniya's status in the Solvaran Union."}
        w = world(ultimatum=ultimatum)
        for target in ("VELERIA", "SOLVARAN_UNION"):
            with self.subTest(target=target):
                self.assertIsNone(politics.validate_motion_detail(w, self.reply("We reject the ultimatum.", target)))
        detail = politics.validate_motion_detail(w, self.reply("We reject the ultimatum.", "DORSANIA"))
        self.assertEqual(detail["reason_code"], "ULTIMATUM_NOT_FROM_TARGET")
        self.assertIn("the ultimatum was issued by Veleria", detail["explanation"])

    def test_the_stance_is_taken_from_the_action_or_read_from_the_text(self):
        cases = (("We reject the ultimatum; the grain agreement stays.", {}, "reject"),
                 ("Karamaniya accepts the demand and guarantees equal rights.", {}, "accept"),
                 ("We will not accept the ultimatum; we offer talks only.", {}, "reject"),
                 ("Karamaniya renews the grain agreement and offers talks.", {}, "counter"),
                 ("We reject the ultimatum.", {"stance": "counter"}, "counter"))
        for text, extra, want in cases:
            with self.subTest(text=text, extra=extra):
                mo = self.reply(text, **extra)
                self.assertEqual(motion_actions.ultimatum_stance(mo), want)

    def test_a_reply_is_recorded_as_a_proposal_with_its_stance_and_result(self):
        w = world(ultimatum=DORSANIA_ULTIMATUM)
        result = politics.apply_motion(w, self.reply("We reject the ultimatum. Equal rights are guaranteed by our law."))
        self.assertEqual(result, "reply delivered to Dorsania: the council rejects the ultimatum")
        proposal = w.dip.proposals[-1]
        self.assertEqual((proposal["kind"], proposal["party"], proposal["stance"]),
                         ("ultimatum_reply", "dorsania", "reject"))

    def test_the_answer_is_kept_on_the_ultimatum_and_shown_to_its_issuer_only(self):
        w = world(ultimatum=DORSANIA_ULTIMATUM)
        text = "We reject the ultimatum. Equal rights are guaranteed by our law."
        politics.apply_motion(w, self.reply(text))
        director._answer_proposals(w)
        self.assertEqual(w.dip.ultimatum["reply"], {"month": 6, "stance": "reject", "text": text})
        self.assertTrue(w.dip.ultimatum, "a reply does not end the ultimatum")
        self.assertEqual(w.dip.inbox, [], "no answer is invented for the issuer")
        events = [e for e in w.events if e["kind"] == "ultimatum_reply"]
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["public"])
        view = foreign_force.ultimatum_compliance(w)
        self.assertEqual(view["karamaniya_reply"], {"stance": "reject", "text": text, "month": "Month 7"})
        self.assertIn("replied in Month 7", foreign_force.ultimatum_text(w))

    def test_earlier_replies_are_kept_and_the_latest_is_the_reply(self):
        w = world(ultimatum=DORSANIA_ULTIMATUM)
        politics.apply_motion(w, self.reply("Karamaniya accepts the demand and will guarantee equal rights."))
        director._answer_proposals(w)
        w.month = 7
        politics.apply_motion(w, self.reply("We reject the ultimatum."))
        director._answer_proposals(w)
        self.assertEqual([r["stance"] for r in w.dip.ultimatum["replies"]], ["accept", "reject"])
        self.assertEqual(w.dip.ultimatum["reply"]["stance"], "reject")

    def test_a_reply_changes_nothing_else_in_the_world(self):
        w = world(ultimatum=DORSANIA_ULTIMATUM)
        before = (w.dip.war, w.dip.blockade, w.dip.grain_embargo, w.dip.nonaggression, w.dip.rally)
        politics.apply_motion(w, self.reply("We reject the ultimatum."))
        director._answer_proposals(w)
        self.assertEqual((w.dip.war, w.dip.blockade, w.dip.grain_embargo, w.dip.nonaggression, w.dip.rally), before)

    def test_a_reply_naming_other_acts_is_not_a_mismatch_when_it_answers_an_ultimatum(self):
        text = ("Karamaniya rejects the ultimatum's demand as interference in its internal affairs. We reaffirm our "
                "non-aggression obligations and invite talks on the border.")
        self.assertIsNone(motion_actions.conflict(world(ultimatum=DORSANIA_ULTIMATUM), self.reply(text)))

    def test_a_reply_that_names_an_act_without_the_ultimatum_is_still_a_mismatch(self):
        clash = motion_actions.conflict(world(ultimatum=DORSANIA_ULTIMATUM),
                                        self.reply("Karamaniya protests the border shooting."))
        self.assertEqual(clash["code"], "MOTION_ACTION_MISMATCH")
        self.assertIn("ACTION_MISMATCH", {r["code"] for r in clash["reasons"]})

    def test_ultimatum_is_not_an_act_in_its_own_right(self):
        self.assertEqual(motion_actions.prose_intent(world(), "We reject the ultimatum.")["actions"], [])

    def test_the_act_is_offered_in_the_action_schema(self):
        from karamaniya import actions as action_schemas
        schema = action_schemas.action_schema(world())
        self.assertIn("ultimatum_reply", schema["properties"]["action_type"]["enum"])

    def test_the_council_is_told_whose_ultimatum_stands(self):
        text = decision_context.canonical_hard_state_v2(world(ultimatum=DORSANIA_ULTIMATUM), "session", [])
        self.assertIn("ultimatum ACTIVE, issued by Dorsania", text)


class Bug3AGrainDealSaysWhichTermsItLeavesOut(unittest.TestCase):
    def test_the_acceptance_names_the_terms_a_grain_agreement_does_not_carry(self):
        w = world(month=3, grain_until=11)
        mo = {"id": "M3", "type": "diplomacy", "subject": "grain_deal", "value": "", "text": B_GRAIN_M4,
              "proposer": "B", "action": {"action_type": "grain_deal", "target": "DORSANIA",
                                          "terms": B_GRAIN_M4_TERMS, "deal_action": "EXTEND_EXISTING_DEAL"}}
        self.assertIsNone(politics.validate_motion_detail(w, mo))
        politics.apply_motion(w, mo)
        director._answer_proposals(w)
        note = [p["text"] for p in w.dip.private_inbox if p.get("channel") == "commercial channel"][-1]
        self.assertIn("accepts a grain purchase arrangement through Month", note)
        self.assertIn("does not take up the other terms", note)
        self.assertIn("In return Dorsania withdraws the troops massed on the east border", note)
        self.assertIn("drops the Month 9 ultimatum", note)
        self.assertIn("a grain agreement carries only the grain trade", note)
        self.assertGreater(w.counters["dorsania_trade_until"], 11.0, "the grain part still took effect")

    def test_a_grain_deal_with_no_other_terms_says_nothing_of_the_kind(self):
        w = world(month=3, grain_until=11)
        text = "Dorsania extends the grain agreement beyond Month 12 at current volume, paid on delivery."
        mo = {"id": "M3", "type": "diplomacy", "subject": "grain_deal", "value": "", "text": text,
              "proposer": "B", "action": {"action_type": "grain_deal", "target": "DORSANIA",
                                          "terms": ["Extend the grain agreement at current volume"],
                                          "deal_action": "EXTEND_EXISTING_DEAL"}}
        politics.apply_motion(w, mo)
        director._answer_proposals(w)
        note = [p["text"] for p in w.dip.private_inbox if p.get("channel") == "commercial channel"][-1]
        self.assertIn("accepts a grain purchase arrangement", note)
        self.assertNotIn("does not take up", note)


class Bug4ADomesticChangeIsNotAProtest(unittest.TestCase):
    def test_a_tax_rise_tabled_as_a_protest_to_the_union_is_a_mismatch(self):
        mo = motion(B_TAX_M8, "diplomatic_protest", "diplomatic_protest", "SOLVARAN_UNION", value="0.30")
        clash = motion_actions.conflict(world(), mo)
        self.assertEqual(clash["code"], "MOTION_ACTION_MISMATCH")
        reason = next(r for r in clash["reasons"] if r["code"] == "DOMESTIC_TEXT_FOREIGN_ACTION")
        self.assertEqual(reason["detail"], "the text describes a domestic measure (tax), but the structured action is "
                                           "a diplomatic protest to the Solvaran Union")
        self.assertEqual(politics.validate_motion_detail(world(), mo)["reason_code"], "MOTION_ACTION_MISMATCH")

    def test_a_domestic_setting_the_text_refuses_to_change_is_not_a_mismatch(self):
        mo = motion("Contain borrowing and prices without cutting soldiers' or police pay.",
                    "diplomatic_protest", "diplomatic_protest", "SOLVARAN_UNION")
        self.assertIsNone(motion_actions.conflict(world(), mo))

    def test_a_protest_that_names_the_union_is_never_read_as_domestic(self):
        mo = motion("Protest to the Solvaran Union: its inspectors cut our trade and raise the tax on our shipping.",
                    "diplomatic_protest", "diplomatic_protest", "SOLVARAN_UNION")
        self.assertIsNone(motion_actions.conflict(world(), mo))

    def test_each_domestic_lever_named_with_a_change_is_caught(self):
        for text, lever in (("Lower the interest rate to 0.05 to ease borrowing.", "rate"),
                            ("Set the army target at 39,000 soldiers.", "army target"),
                            ("Cut welfare to pay the deficit.", "welfare")):
            with self.subTest(text=text):
                clash = motion_actions.conflict(world(), motion(text, "diplomatic_protest", "diplomatic_protest",
                                                                "SOLVARAN_UNION"))
                reason = next(r for r in clash["reasons"] if r["code"] == "DOMESTIC_TEXT_FOREIGN_ACTION")
                self.assertIn(f"({lever})", reason["detail"])


class TheActsAreRegistered(unittest.TestCase):
    def test_the_new_act_has_a_default_receiver_and_all_four_targets(self):
        self.assertEqual(motion_actions.DIPLOMATIC_ACTIONS["ultimatum_reply"], motion_actions.SOLVARAN_UNION)
        self.assertEqual(motion_actions.DIPLOMATIC_TARGETS["ultimatum_reply"], set(motion_actions.ACTORS))
        self.assertEqual(politics.DIPLOMACY["ultimatum_reply"], "union")


if __name__ == "__main__":
    unittest.main()
