"""World engine 18 groundwork: how firm Karamaniya looks to its neighbours (resolve.py).

In run 20261010-070501-seed1 the council met three ultimatums with talks, invited the Union into a joint inquiry,
stood its patrols down, called two referendums and left the army at 28,000 against 100,000, and nothing kept score
of how that looked from Veleria. The figure here does; the cabinets and the Union's rules read it.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import director, foreign, foreign_force, motion_actions, politics, resolve, territory  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

PROTEST = ("Issue a formal protest to the Union over the Month 5 shooting on the eastern border. Demand a joint "
           "fact-finding investigation with published findings within one month and a mutual stand-down of patrols "
           "near the incident sector pending findings.")


def world(seed: int = 5):
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def diplomacy(subject, target, text="Talks.", value=""):
    return {"type": "diplomacy", "subject": subject, "value": value, "text": text, "votes": {m: "yes" for m in "ABCDE"},
            "action": {"action_type": subject, "target": target}}


class TheFigure(unittest.TestCase):
    def test_it_starts_even_and_is_held_within_bounds(self):
        w = world()
        self.assertEqual(resolve.value(w), resolve.BASE)
        for _ in range(10):
            resolve.note(w, "cede_region", "test")
        self.assertEqual(resolve.value(w), resolve.LOW)
        self.assertEqual(resolve.word(w), "yielding")
        self.assertEqual(len(resolve.state(w)["log"]), 10)

    def test_an_unknown_signal_or_an_old_world_changes_nothing(self):
        w = world()
        resolve.note(w, "a parade", "test")
        self.assertEqual(resolve.value(w), resolve.BASE)
        old = world()
        old.agent_architecture_version = 1
        resolve.note(old, "cede_region", "test")
        resolve.monthly(old)
        self.assertNotIn("resolve", old.foreign)

    def test_a_small_army_drifts_it_down_and_a_large_one_up(self):
        weak, strong = world(), world()
        strong.mil.army.size = 60000
        self.assertLess(resolve.baseline(weak), resolve.BASE)
        self.assertGreater(resolve.baseline(strong), resolve.BASE)
        for _ in range(12):
            resolve.monthly(weak)
            resolve.monthly(strong)
        self.assertLess(resolve.value(weak), .48)
        self.assertGreater(resolve.value(strong), .55)

    def test_arming_is_seen_the_month_after(self):
        w = world()
        resolve.monthly(w)                       # the first look records the policy in force
        before = resolve.value(w)
        w.policy.recruitment, w.policy.military = "partial", w.policy.military + .01
        resolve.monthly(w)
        moves = [x["reason"] for x in resolve.recent(w)]
        self.assertTrue(any("recruitment raised to partial" in r for r in moves), moves)
        self.assertTrue(any("military budget raised" in r for r in moves), moves)
        self.assertGreater(resolve.value(w), before + .04)


class WhatTheNeighboursSee(unittest.TestCase):
    def test_a_protest_with_a_joint_inquiry_and_a_stand_down_reads_as_yielding(self):
        w = world()
        w.month = 4
        mo = diplomacy("diplomatic_protest", motion_actions.SOLVARAN_UNION, PROTEST)
        politics.apply_motion(w, mo)
        signals = [x["signal"] for x in resolve.state(w)["log"]]
        self.assertEqual(sorted(signals), ["joint_inquiry", "protest", "stand_down"])
        self.assertAlmostEqual(resolve.value(w), resolve.BASE - .04 - .05 + .01, places=4)

    def test_talks_on_status_under_a_deadline_are_a_concession_and_without_one_are_not(self):
        w = world()
        politics.apply_motion(w, diplomacy("status_talks", motion_actions.SOLVARAN_UNION))
        self.assertEqual(resolve.value(w), resolve.BASE)
        foreign_force.apply(w, "veleria", {"type": "ultimatum", "terms": "status_talks", "deadline_months": 3})
        politics.apply_motion(w, diplomacy("status_talks", motion_actions.SOLVARAN_UNION))
        self.assertAlmostEqual(resolve.value(w), resolve.BASE - .03, places=4)

    def test_a_cession_is_the_largest_concession(self):
        w = world()
        foreign_force.apply(w, "veleria", {"type": "ultimatum", "terms": "cede_region", "region": "kessel",
                                           "deadline_months": 3})
        territory.cede(w, "kessel", "veleria")
        self.assertAlmostEqual(resolve.value(w), resolve.BASE - .15, places=4)
        self.assertIn("Kessel Valley ceded to Veleria", resolve.recent(w)[0]["reason"])

    def test_a_referendum_called_under_a_deadline_costs_twice_what_one_called_in_calm_does(self):
        calm, pressed = world(), world()
        foreign_force.apply(pressed, "veleria", {"type": "ultimatum", "terms": "status_talks", "deadline_months": 3})
        referendum = {"type": "referendum", "subject": "", "value": "", "text": "", "votes": {"A": "yes"}}
        politics.apply_motion(calm, referendum)
        politics.apply_motion(pressed, referendum)
        self.assertAlmostEqual(resolve.BASE - resolve.value(pressed), 2 * (resolve.BASE - resolve.value(calm)), places=4)

    def test_an_alliance_and_a_demand_left_to_lapse_raise_it(self):
        w = world()
        w.dip.league_trust = .9
        director._league_reply(w, "alliance", 0.0)
        self.assertTrue(w.dip.league_alliance)
        self.assertAlmostEqual(resolve.value(w), resolve.BASE + .06, places=4)


if __name__ == "__main__":
    unittest.main()
