"""World engine 17: the public's reactions and the ministries' grievances, the two mechanisms the engine-17
features build on (public_mood.py, ministries.py).

In run 20261010-070501-seed1 the council invited the Union into a joint inquiry over a shooting on its own
border and twice asked the country whether it wanted to stay independent, and nothing reacted: no public, no
officer corps. These are the places a reaction lives.
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import engine, foreign, ministries, public_mood, staff  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def world(seed: int = 5):
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def month(w, n=1):
    for _ in range(n):
        engine.begin_month(w)
        engine.step(w)


def approval(w, ident):
    pops = [p for p in w.k_pops() if p.ident == ident]
    return sum(p.approval * p.size for p in pops) / sum(p.size for p in pops)


class PublicReactions(unittest.TestCase):
    def test_a_reaction_aimed_at_one_identity_moves_that_identity_only(self):
        base, hit = world(), world()
        public_mood.react(hit, "approval", "ident:karamanian", -.02, 3, "test")
        month(base)
        month(hit)
        self.assertLess(approval(hit, "karamanian"), approval(base, "karamanian") - .005)
        self.assertAlmostEqual(approval(hit, "imperial"), approval(base, "imperial"), places=4)

    def test_a_reaction_lasts_its_months_decays_and_is_gone(self):
        w = world()
        public_mood.react(w, "indep", "*", .01, 2, "test", decay=.5)
        seen = []
        public_mood.effects(w, lambda kind, where, value: seen.append((kind, where, value)))
        public_mood.effects(w, lambda kind, where, value: seen.append((kind, where, value)))
        public_mood.effects(w, lambda kind, where, value: seen.append((kind, where, value)))
        self.assertEqual(seen, [("indep", "*", .01), ("indep", "*", .005)])
        self.assertEqual(public_mood.state(w), [])

    def test_nonsense_is_refused_and_a_reaction_is_capped(self):
        w = world()
        self.assertIsNone(public_mood.react(w, "joy", "*", .01, 2, "x"))
        self.assertIsNone(public_mood.react(w, "approval", "ident:martian", .01, 2, "x"))
        self.assertIsNone(public_mood.react(w, "approval", "atlantis", .01, 2, "x"))
        self.assertIsNone(public_mood.react(w, "approval", "*", .01, 0, "x"))
        self.assertEqual(public_mood.react(w, "approval", "kessel", -.5, 1, "x")["value"], -public_mood.LIMIT)

    def test_nothing_changes_while_nothing_reacts(self):
        a, b = world(), world()
        public_mood.state(b)                     # an empty list must change nothing
        month(a, 2)
        month(b, 2)
        self.assertEqual([round(p.approval, 9) for p in a.k_pops()], [round(p.approval, 9) for p in b.k_pops()])


class MinistryGrievances(unittest.TestCase):
    def test_a_grievance_costs_the_minister_bond_and_is_capped(self):
        w = world()
        bond = w.mil.army.bond
        g = ministries.aggrieve(w, "army", .1, "the joint inquiry with the Union into a shooting on its border")
        self.assertAlmostEqual(g, .1)
        self.assertAlmostEqual(w.mil.army.bond, max(0.0, bond - .1), places=6)
        self.assertEqual(ministries.aggrieve(w, "army", 1.0, "more"), ministries.MAX)
        events = [e for e in w.events if e["kind"] == "ministry_grievance"]
        self.assertEqual(events[0]["text"], "Army Command resents the joint inquiry with the Union into a shooting on its border.")
        self.assertEqual(len(events), 2)

    def test_a_grieving_army_grows_less_loyal_and_the_grievance_fades(self):
        base, hit = world(), world()
        ministries.aggrieve(hit, "army", .3, "test")
        # The General Staff's standing request (staff.py) would add its own grievance in a new world; this test is
        # about one grievance and how it fades.
        with mock.patch.object(staff, "request", return_value=None):
            month(base, 3)
            month(hit, 3)
        self.assertLess(hit.mil.army.loyalty, base.mil.army.loyalty - .005)
        self.assertLess(hit.mil.army.morale, base.mil.army.morale)
        self.assertAlmostEqual(hit.mil.police.loyalty, base.mil.police.loyalty, places=6)
        self.assertAlmostEqual(ministries.grievance(hit, "army"), .3 * ministries.DECAY ** 3, places=3)

    def test_soothing_and_unknown_offices(self):
        w = world()
        ministries.aggrieve(w, "interior", .05, "test")
        self.assertAlmostEqual(ministries.soothe(w, "interior", .02, "asked and done"), .03)
        self.assertEqual(ministries.aggrieve(w, "treasury", .1, "test"), 0.0)
        self.assertEqual(ministries.drag(w, "navy"), (0.0, 0.0))

    def test_only_the_holder_reads_the_mood_and_only_once_it_is_felt(self):
        w = world()
        self.assertEqual(ministries.briefing(w, "D"), "")
        ministries.aggrieve(w, "army", .01, "a small slight")
        self.assertEqual(ministries.briefing(w, "D"), "")
        ministries.aggrieve(w, "army", .1, "the joint inquiry with the Union")
        text = ministries.briefing(w, "D")
        self.assertIn("Army Command is resentful toward the government", text)
        self.assertIn("the joint inquiry with the Union (Month 1)", text)
        self.assertEqual(ministries.briefing(w, "A"), "")

    def test_no_grievance_changes_nothing(self):
        a, b = world(), world()
        ministries.state(b)
        month(a, 2)
        month(b, 2)
        self.assertEqual(a.mil.army.loyalty, b.mil.army.loyalty)
        self.assertEqual(a.mil.police.morale, b.mil.police.morale)


if __name__ == "__main__":
    unittest.main()
