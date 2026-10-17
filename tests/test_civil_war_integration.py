"""Wave C integration: the engine calls the civil-war combat, and the militia path stands down during a war.

    python -m unittest tests.test_civil_war_integration
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import civil_war_combat, engine, society  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


class _Always:
    """A stand-in rng whose draws are zero, so the militia chance always succeeds."""
    def random(self):
        return 0.0

    def uniform(self, a, b):
        return a


class TheEngineCallsTheCombat(unittest.TestCase):
    def test_combat_is_called_once_a_month_when_the_arm_is_on(self):
        w = new_world(1, 36)
        w.civil_war_option = "on"
        with mock.patch.object(civil_war_combat, "combat", wraps=civil_war_combat.combat) as called:
            engine.step(w)
        self.assertEqual(called.call_count, 1)

    def test_with_the_arm_off_the_combat_is_not_called(self):
        w = new_world(1, 36)
        self.assertEqual(w.civil_war_option, "off")
        with mock.patch.object(civil_war_combat, "combat", wraps=civil_war_combat.combat) as called:
            engine.step(w)
        self.assertEqual(called.call_count, 0)


class TheMilitiaPathStandsDownDuringAWar(unittest.TestCase):
    def _angry_region(self):
        w = new_world(1, 36)
        r = w.region("kessel")
        r.controller = "karamaniya"
        r.unrest = 0.6
        rp = [p for p in w.pops if p.region == "kessel"]
        for p in rp:
            p.ident = "imperial"
        w.dip.arms_smuggling = True
        # A garrison too weak to hold the region, so the uprising condition is met.
        w.mil.army.size = 0.0
        w.mil.police.size = 0.0
        return w, r

    def test_a_war_stops_the_militia_uprising(self):
        w, r = self._angry_region()
        w.civil_war = {"since": w.month, "factions": {}, "contested": []}
        society._rebel_regions(w, _Always())
        self.assertEqual(r.controller, "karamaniya")

    def test_without_a_war_the_same_region_rises(self):
        w, r = self._angry_region()
        w.civil_war = None
        society._rebel_regions(w, _Always())
        self.assertEqual(r.controller, "rebels")


if __name__ == "__main__":
    unittest.main()
