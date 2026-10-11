"""World engine 22, standdown slice: a demand is not an offer of a stand-down (fine_print.py).

In run 20261011-105713-seed1 the engine read two demands on the Solvaran Union as Karamaniya's own offer of a
stand-down. Month 4, D1 (a protest) demanded "an immediate pull-back to garrison levels" and carried the term "Pull back
massed forces to garrison levels"; Month 5, M1 (a non-aggression proposal) asked the Union to withdraw "troops massed on
our borders". Each was published as an offer of a stand-down of Karamanian patrols, and Army Command resented being
ordered to pull back from its own border. A stand-down counts as Karamaniya's offer only when its words make it ours or
mutual.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import fine_print, foreign, ministries, politics  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

D1_TEXT = ("The Provisional Government formally protests the Solvaran Union's military build-up on Karamaniya's "
           "borders and rejects its claimed right to inspect our shipping as interference in our internal affairs. "
           "We demand an immediate pull-back to garrison levels, a public explanation, and a mutual non-aggression "
           "undertaking. Delivery is tied to the funded 39,000 target: our words carry the force behind them.")
D1_TERMS = ["Pull back massed forces to garrison levels", "A public explanation of the deployment",
            "A mutual non-aggression undertaking", "No Union role in Karamaniya's internal affairs"]
M1_TEXT = ("Answer the Union's invitation with terms, not tribute: the Union renounces any right to inspect "
           "Karamaniya's shipping, withdraws troops massed on our borders, and takes no role in our internal affairs. "
           "In return "
           "Karamaniya keeps its borders calm and joins no alliance against the Union. Rejected terms mean we escalate "
           "readiness.")
M1_TERMS = ["Renounce any right to inspect Karamaniya's shipping", "Withdraw troops massed on Karamaniya's borders",
            "No Union role in Karamaniya's internal affairs", "No alliance against the Union, borders kept calm"]


def world(seed: int = 11):
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.agent_architecture_version = 2
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def offered(text: str, terms=()) -> list:
    """The clauses a diplomacy motion offers the Union, read the way politics.apply_motion reads it."""
    return fine_print.clauses(world(), fine_print.detection_text({"text": text}, {"terms": list(terms)}), "union")


class TheRunTextsOfferNoStandDown(unittest.TestCase):
    """Run 20261011-105713-seed1: the demand in D1 (Month 4) and the request in M1 (Month 5) offer no stand-down."""

    def test_the_month_4_protest_demands_a_pull_back_and_offers_none(self):
        self.assertEqual(offered(D1_TEXT, D1_TERMS), [])

    def test_the_month_5_proposal_asks_the_union_to_withdraw_and_offers_none(self):
        self.assertEqual(offered(M1_TEXT, M1_TERMS), [])

    def test_passed_as_they_were_the_two_motions_publish_no_stand_down_and_cost_the_army_nothing(self):
        w = world()
        w.month = 3
        protest = {"id": "D1", "proposer": "C", "type": "diplomacy", "subject": "diplomatic_protest", "value": "",
                   "text": D1_TEXT, "votes": {mid: "yes" for mid in "ABCDE"}, "passed": True,
                   "action": {"action_type": "diplomatic_protest", "target": "Solvaran Union", "terms": D1_TERMS},
                   "summary": "protest to the Union over the border build-up"}
        politics.apply_motion(w, protest)
        self.assertEqual(fine_print.state(w)["standdowns"], [])
        self.assertEqual(ministries.grievance(w, "army"), 0.0)
        w.month = 4
        proposal = {"id": "M1", "proposer": "A", "type": "diplomacy", "subject": "non_aggression", "value": "",
                    "text": M1_TEXT, "votes": {mid: "yes" for mid in "ABCDE"}, "passed": True,
                    "action": {"action_type": "non_aggression_pact", "target": "Solvaran Union", "terms": M1_TERMS},
                    "summary": "non-aggression terms to the Union"}
        politics.apply_motion(w, proposal)
        self.assertEqual(w.dip.proposals[-1]["clauses"], [])
        self.assertEqual(fine_print.state(w)["standdowns"], [])
        self.assertEqual(ministries.grievance(w, "army"), 0.0)


class ADemandOnTheOtherSideIsNotAnOffer(unittest.TestCase):
    """A demand that the other side pull back, stand down or withdraw is not Karamaniya's offer (engine 22)."""

    def test_a_demand_or_an_other_side_pull_back_is_not_read_as_ours(self):
        for text in ("The Union must withdraw troops from the border.",
                     "We require the Union to withdraw troops from the border.",
                     "We urge the Union to pull back troops from the border.",
                     "We demand that the Union pull back its patrols from the northern border.",
                     "We demand a stand-down of patrols in the north.",
                     "We demand a demilitarized zone along the northern border.",
                     "In return the Union withdraws troops from the border.",
                     "Dorsania must pull back its massed forces from the east border.",
                     "The Union proposes a stand-down of its patrols in the north.",
                     "We demand a public explanation and a stand-down of patrols in the north.",
                     "We ask the Union to pull back its troops from the north.",
                     "The Union's stand-down of patrols in the north would calm the border."):
            with self.subTest(text=text):
                self.assertEqual(fine_print.clauses(world(), text, "union"), [])

    def test_a_bare_imperative_names_no_forces_of_ours(self):
        for text in ("Pull back massed forces to garrison levels.", "Pull back forces to garrison levels.",
                     "Withdraw troops from the incident sector pending findings.", "Pull back troops from the border.",
                     "Pull back its forces from the border.", "We pull back Dorsanian forces from the border.",
                     "We pull back the Union's forces to garrison levels."):
            with self.subTest(text=text):
                self.assertEqual(fine_print.clauses(world(), text, "union"), [])


class TheOffersOfOursStillCount(unittest.TestCase):
    """A stand-down that is ours or mutual is still Karamaniya's offer, in every wording the engine reads."""

    def test_mutual_and_our_pull_backs_are_still_offers(self):
        for text in ("We offer a mutual pull-back of forces from the border",
                     "Karamaniya will pull our patrols back ten kilometres",
                     "We propose a stand-down of our patrols in the north",
                     "a reciprocal pullback from the border",
                     "We propose an immediate pull-back of our patrols from the border.",
                     "We propose a pullback of our forces from the border.",
                     "Withdraw Karamaniya's troops from the border.",
                     "We will withdraw the army's troops from the border.",
                     "We demand a mutual stand-down of patrols in the north."):
            with self.subTest(text=text):
                self.assertEqual(fine_print.clauses(world(), text, "union"), ["stand_down"])


class TheMixedTextFindsOnlyTheOffer(unittest.TestCase):
    """A text with a demand on the other side and an offer of ours finds the offer, and not the demand."""

    def test_a_demand_and_an_offer_in_one_text_offer_the_stand_down_only_once(self):
        for text in ("The Union must withdraw troops from the border; we propose a stand-down of our patrols in the "
                     "north.",
                     "We propose a stand-down of our patrols in the north; the Union must withdraw troops from the "
                     "border.",
                     "We demand that the Union withdraw troops from the border, and we propose a stand-down of our "
                     "patrols in the north.",
                     "The Union must withdraw troops from the border, but we propose a stand-down of our patrols in "
                     "the north.",
                     "We demand that the Union pull back its patrols and propose a stand-down of our patrols in the "
                     "north.",
                     "We ask for talks and propose a stand-down of our patrols in the north."):
            with self.subTest(text=text):
                self.assertEqual(fine_print.clauses(world(), text, "union"), ["stand_down"])


class TheNoSideStandDownsKeepTheirReading(unittest.TestCase):
    """Patterns that name no side (audit MO24, engine 22) read as offers as they did."""

    def test_a_zone_or_a_disengagement_with_no_side_is_still_a_stand_down(self):
        for text in ("A buffer zone along the northern border.",
                     "A demilitarized zone along the eastern border.",
                     "Disengagement of the two armies along the eastern border.",
                     "A stand-down of patrols in the north pending findings."):
            with self.subTest(text=text):
                self.assertEqual(fine_print.clauses(world(), text, "union"), ["stand_down"])


if __name__ == "__main__":
    unittest.main()
