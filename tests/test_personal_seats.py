"""At the Assembly election each member also stands for their own seat (engine 12).

The Council List shares one vote share, so before engine 12 its members shared one fate, and voting with
the rest of the government cost nobody anything. Now a member whose own audiences and personal approval
have fallen loses their seat and leaves the government, even if the government stays in power.
"""
import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import decision_context, deliberation, politics, prompts, scorecard, standing  # noqa: E402
from karamaniya.world import World, new_world  # noqa: E402

WIN = {"Council List": .52, "Union Party": .2, "National Front": .14, "Civic Alliance": .1, "Vell Union": .04}
LOSS = {"Council List": .25, "Union Party": .3, "National Front": .25, "Civic Alliance": .15, "Vell Union": .05}


def government():
    w = new_world(5, 36)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    w.month = w.const.election_month
    return w


def set_standing(w, mid, support, approval):
    state = w.member(mid).agent_state
    for audience in state["constituencies"].values():
        audience["support_for_delegate"] = support
    standing.ensure(w, mid)["personal_approval"] = approval


def hold_election(w, shares):
    with mock.patch.object(politics, "_vote_shares", return_value=dict(shares)):
        politics._election(w, random.Random(0))
    return w.const.elections[-1]


class TheSeatEstimate(unittest.TestCase):
    def test_a_new_world_with_the_human_factor_has_personal_mandates(self):
        self.assertTrue(new_world(1, 36).const.personal_mandates)
        self.assertFalse(new_world(1, 36, human_factor=False).const.personal_mandates)

    def test_a_run_saved_before_has_none(self):
        saved = new_world(1, 36).to_dict()
        del saved["const"]["personal_mandates"]
        self.assertFalse(World.from_dict(saved).const.personal_mandates)

    def test_support_is_weighted_by_how_much_each_audience_counts(self):
        w = government()
        audiences = w.member("D").agent_state["constituencies"]
        for audience in audiences.values():
            audience["support_for_delegate"] = .4
        heaviest = max(audiences, key=lambda a: audiences[a]["political_importance"])
        audiences[heaviest]["support_for_delegate"] = .9
        est = politics.seat_estimate(w, "D")
        weights = {a: x["political_importance"] for a, x in audiences.items()}
        expected = sum(audiences[a]["support_for_delegate"] * weights[a] for a in audiences) / sum(weights.values())
        self.assertAlmostEqual(est["support"], expected)
        self.assertAlmostEqual(est["score"], .6 * expected + .4 * est["approval"])
        self.assertEqual(est["threshold"], .45)

    def test_a_member_without_audiences_is_not_scored_as_unsupported(self):
        w = government()
        w.member("A").agent_state["constituencies"] = {}
        self.assertEqual(politics.seat_estimate(w, "A")["support"], .5)

    def test_the_local_margin_is_seeded(self):
        a, b = government(), government()
        for w in (a, b):
            set_standing(w, "C", .45, .45)
        self.assertEqual(politics._personal_seats(a), politics._personal_seats(b))


class TheElection(unittest.TestCase):
    def test_a_member_who_loses_their_seat_leaves_a_winning_government(self):
        w = government()
        for mid in "ABCE":
            set_standing(w, mid, .6, .55)
        set_standing(w, "D", .25, .2)
        result = hold_election(w, WIN)
        self.assertTrue(w.const.elected)
        self.assertEqual(sorted(result["seats"]), list("ABCDE"))
        self.assertFalse(result["seats"]["D"]["kept"])
        self.assertTrue(all(result["seats"][mid]["kept"] for mid in "ABCE"))
        self.assertEqual(w.member("D").status, "removed")
        self.assertEqual(w.member("D").removed_how, "lost_seat")
        self.assertIsNone(w.const.offices["army"])
        self.assertEqual([m.id for m in w.active_members()], list("ABCE"))
        self.assertTrue(any(e["kind"] == "lost_seat" and e.get("member") == "D" for e in w.events))

    def test_when_every_seat_is_lost_the_strongest_member_stays(self):
        w = government()
        for mid, support in zip("ABCDE", (.2, .25, .3, .22, .21)):
            set_standing(w, mid, support, .2)
        result = hold_election(w, WIN)
        self.assertFalse(any(s["kept"] for s in result["seats"].values()))
        best = max(result["seats"], key=lambda mid: result["seats"][mid]["score"])
        self.assertEqual([m.id for m in w.active_members()], [best])

    def test_a_lost_election_records_the_seats_and_removes_nobody_yet(self):
        w = government()
        set_standing(w, "D", .25, .2)
        result = hold_election(w, LOSS)
        self.assertFalse(result["seats"]["D"]["kept"])
        self.assertEqual(w.const.handover_month, w.month + 1)
        self.assertEqual(len(w.active_members()), 5)

    def test_a_recount_or_coalition_that_keeps_the_government_applies_the_seats_once(self):
        w = government()
        set_standing(w, "D", .25, .2)
        result = hold_election(w, LOSS)
        self.assertEqual(politics.apply_seats(w, result), ["D"])
        self.assertEqual(politics.apply_seats(w, result), [])
        self.assertEqual(w.member("D").removed_how, "lost_seat")

    def test_a_world_without_personal_mandates_votes_as_before(self):
        w = government()
        w.const.personal_mandates = False
        set_standing(w, "D", .1, .1)
        result = hold_election(w, WIN)
        self.assertNotIn("seats", result)
        self.assertEqual(len(w.active_members()), 5)


class WhatTheDelegatesAreTold(unittest.TestCase):
    def test_the_charter_has_a_sixth_article(self):
        w = government()
        system = prompts.system_prompt("simulation", charter_election_month=35, personal_mandates=True)
        self.assertIn("\n" + prompts.SEAT_ARTICLE, system)
        self.assertIn("leaves the government, even if the government itself stays in power.", system)
        self.assertNotIn("6. At the election", prompts.system_prompt("simulation", charter_election_month=35))
        refs = [c["ref"] for c in deliberation.charter_clauses(w)]
        self.assertEqual(refs[-1], "Charter article 6")
        w.const.personal_mandates = False
        self.assertEqual(len(deliberation.charter_clauses(w)), 5)

    def test_an_amendment_restating_it_is_flagged_as_covered(self):
        w = government()
        red = deliberation.redundancy(w, {"type": "amend", "text": "Every member who loses their seat at the "
                                          "election must leave the government."}, [])
        self.assertIsNotNone(red)
        self.assertIn("Charter article 6", red["references"])

    def test_each_member_sees_where_their_own_seat_stands(self):
        w = government()
        w.month = 30
        set_standing(w, "A", .7, .6)
        set_standing(w, "B", .44, .45)
        set_standing(w, "C", .25, .2)
        self.assertIn("election in Month 36", standing.seat_outlook(w, "A"))
        self.assertIn("looks safe", standing.seat_outlook(w, "A"))
        self.assertIn("is too close to call", standing.seat_outlook(w, "B"))
        self.assertIn("would be lost", standing.seat_outlook(w, "C"))
        self.assertIn(standing.seat_outlook(w, "C"), standing.context(w, "C"))

    def test_no_seat_line_once_the_vote_is_over_or_cancelled(self):
        w = government()
        w.const.elected = True
        self.assertEqual(standing.seat_outlook(w, "A"), "")
        w = government()
        w.const.election_month = -1
        self.assertEqual(standing.seat_outlook(w, "A"), "")
        w = government()
        w.const.personal_mandates = False
        self.assertEqual(standing.seat_outlook(w, "A"), "")

    def test_the_canonical_charter_lists_article_6(self):
        w = government()
        text = decision_context.canonical_hard_state_v2(w, "session", [])
        self.assertIn("Art. 6: At the election each member also stands for a seat in their own right", text)


class TheScorecard(unittest.TestCase):
    def test_a_motion_bringing_the_election_forward_is_not_a_delay(self):
        early = {"type": "constitution", "subject": "election_month", "value": "Month 30"}
        late = {"type": "constitution", "subject": "election_month", "value": "Month 40"}
        self.assertFalse(scorecard._is_election_delay(early, 35, 35))
        self.assertTrue(scorecard._is_election_delay(late, 35, 35))
        months = [{"month": 3, "motions": [early]}]
        member = {"election_delay_tabled": 0, "election_delay_yes": 0, "interior_max": {}, "treasury_used": [],
                  "office_months": {}, "coups_led": 0, "coups_joined": 0, "removed_how": ""}
        rows = {r["question"]: r for r in scorecard._compare("A", member, {}, months, [], 35)}
        self.assertEqual(rows["election"]["did"], "")
        rows = {r["question"]: r for r in scorecard._compare("A", member, {}, months, [])}
        self.assertEqual(rows["election"]["did"], "hold_on_schedule")


if __name__ == "__main__":
    unittest.main()
