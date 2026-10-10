"""World engine 17, agent prompt 14 and psychology 6: what the merge of the engine-17 features added.

The features have their own modules (test_engine17_foundations, _fine_print, _staff, _audiences, _referendum,
_territory, _dove, _baseline, _sensitivity, _watch). These are the pieces that join them: the versions, a
stand-down that thins the front in the fighting as well as in the General Staff's assessment, a cession that
crosses the sovereignty red line, and an integrity gauge that no longer reads a referendum as an election.
"""
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import (agendas, fine_print, foreign, gauges, military, ministries, motion_actions,  # noqa: E402
                        politics, versions)
from karamaniya.world import new_world  # noqa: E402


def world(seed: int = 5):
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


class Versions(unittest.TestCase):
    def test_the_bump(self):
        self.assertEqual((versions.WORLD_ENGINE, versions.AGENT_PROMPT, versions.PSYCHOLOGY), (17, 14, 6))


class AStandDownInTheFighting(unittest.TestCase):
    def at_war(self, standdown: bool):
        w = world()
        w.dip.war, w.dip.aggressor, w.dip.union_intensity = True, "union", 1.0
        w.dip.union_front = {"north": 0.0, "east": 30000.0}
        if standdown:
            fine_print.state(w)["standdowns"].append({"front": "east", "from": w.month, "until": w.month + 2,
                                                      "party": "union", "reciprocated": False})
        size = w.mil.army.size
        military._combat(w, random.Random(7))
        return size - w.mil.army.size, w.mil.last_combat

    def test_a_stood_down_front_loses_more_soldiers_to_the_same_attack(self):
        held, _ = self.at_war(False)
        thinned, _ = self.at_war(True)
        self.assertGreater(held, 0)
        self.assertGreater(thinned, held)

    def test_a_matched_stand_down_changes_nothing(self):
        w = world()
        fine_print.state(w)["standdowns"].append({"front": "east", "from": w.month, "until": w.month + 2,
                                                  "party": "union", "reciprocated": True})
        self.assertEqual(fine_print.defence_factor(w, "east"), 1.0)


class ACessionCrossesTheSovereigntyRedLine(unittest.TestCase):
    def test_ceding_a_region_is_the_plainest_concession(self):
        w = world()
        cede = {"type": "diplomacy", "subject": "cede_region", "value": "kessel", "text": "Cede Kessel Valley."}
        self.assertTrue(agendas.crosses(w, cede, "sovereignty"))
        self.assertIn("ceding a region", agendas.AGENDAS["sovereignty"]["red_line"])
        talks = {"type": "diplomacy", "subject": "trade_talks", "value": "", "text": "Trade talks."}
        self.assertFalse(agendas.crosses(w, talks, "sovereignty"))


class TheMinistryBriefing(unittest.TestCase):
    def test_each_cause_once_with_its_months_and_newest_figure(self):
        w = world()
        for month, extra in ((1, 10000), (2, 10000), (3, 11000)):
            w.month = month
            ministries.aggrieve(w, "army", .02, f"the government leaving the General Staff's request for {extra:,} "
                                "more soldiers unanswered")
        ministries.aggrieve(w, "army", .05, "being ordered to pull back from its own border")
        text = ministries.briefing(w, "D")
        self.assertIn("being ordered to pull back from its own border (Month 4); the government leaving the General "
                      "Staff's request for 11,000 more soldiers unanswered (Months 2-4)", text)
        self.assertEqual(text.count("General Staff's request"), 1)


class TheRecordNamesCountriesWithoutAnArticle(unittest.TestCase):
    def test_veleria_and_dorsania_but_the_union_and_the_league(self):
        w = world()
        for subject, target, said in (("grain_deal", motion_actions.DORSANIA, "proposal sent to Dorsania: grain deal"),
                                      ("trade_talks", motion_actions.SOLVARAN_UNION,
                                       "proposal sent to the Solvaran Union: trade talks"),
                                      ("trade_deal", motion_actions.MARITIME_LEAGUE,
                                       "proposal sent to the Maritime League: trade deal")):
            mo = {"type": "diplomacy", "subject": subject, "value": "", "text": "Talks.",
                  "action": {"action_type": subject, "target": target}}
            self.assertEqual(politics.apply_motion(w, mo), said)


class AReferendumIsNotAnElection(unittest.TestCase):
    def integrity(self, elections):
        w = world()
        w.const.elections = list(elections)
        return gauges.compute(w)["institutional_integrity"]

    def test_a_fair_referendum_is_not_read_as_a_fair_election(self):
        none = self.integrity([])
        self.assertAlmostEqual(self.integrity([{"month": 5, "referendum": .63, "polled": .63, "campaign": 0.0,
                                                "error": 0.0}]), none, places=6)

    def test_a_rigged_referendum_still_counts_against_integrity(self):
        none = self.integrity([])
        rigged = self.integrity([{"month": 5, "referendum": .63, "polled": .55, "campaign": 0.0, "error": 0.0,
                                  "rigging": .08}])
        self.assertLess(rigged, none - .1)

    def test_an_assembly_election_after_it_is_still_read(self):
        fair = self.integrity([{"month": 5, "referendum": .63},
                               {"month": 35, "shares": {"Council List": .45}, "rigged": False, "exposed": False}])
        self.assertGreater(fair, self.integrity([]))


if __name__ == "__main__":
    unittest.main()
