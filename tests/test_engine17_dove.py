"""World engine 17: the dove, the stand-in that never raises the military and answers a deadline with talks.

The all-dove baseline (baseline.py) is five seats of this persona. The dove keeps the democrat's rules
(backends/scripted.py, DEMOCRAT_LIKE) and departs from them in four places: it never proposes or votes for raising
the military (the budget, the army's target, its recruitment or mobilization) or setting posture to attack; it
offers talks while a deadline is open; it votes against alliances; and its orders keep the military where it is.
These are checked here on a world built for the purpose. The councils themselves are run in
test_engine17_sensitivity.py.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import agents, foreign  # noqa: E402
from karamaniya.backends import make_backend  # noqa: E402
from karamaniya.backends.scripted import ScriptedBackend  # noqa: E402
from karamaniya.config import normalize_config  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

TALKS = {("diplomacy", "status_talks"), ("diplomacy", "trade_talks")}


def world(seed: int = 3):
    w = new_world(seed, 36, member_ids=list("ABCDE"))
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    agents.ensure(w)
    return w


def deadline(by: str = "veleria", terms_id: str = "status_talks") -> dict:
    """An active deadline, as foreign_force.apply records one."""
    return {"issued": 0, "deadline": 4, "terms": "Open negotiations on Karamaniya's status in the Solvaran Union.",
            "terms_id": terms_id, "by": by}


class DoveVotes(unittest.TestCase):
    def setUp(self):
        self.w = world()
        self.dove = ScriptedBackend({"persona": "dove"})

    def vote(self, motion: dict, proposer: str = "B") -> str:
        return self.dove._vote(self.w, "A", {"id": "M1", "proposer": proposer, **motion})

    def test_a_dove_votes_no_on_every_motion_that_raises_the_military(self):
        w = self.w
        raises = [
            {"type": "set_policy", "subject": "military", "value": f"{w.policy.military + .02:.3f}"},
            {"type": "set_policy", "subject": "army_target", "value": f"{w.policy.army_target + 10000:.0f}"},
            {"type": "set_policy", "subject": "recruitment", "value": "partial"},
            {"type": "set_policy", "subject": "mobilization", "value": "general"},
            {"type": "set_policy", "subject": "posture", "value": "attack"},
        ]
        for motion in raises:
            with self.subTest(motion=motion):
                self.assertEqual(self.vote(motion), "no")

    def test_a_trusted_friends_motion_does_not_talk_a_dove_into_raising_arms(self):
        w = self.w
        w.econ.food_ratio = .8                       # a shortage: the democrat would vote no on a rise
        w.member("A").relationships["B"] = {"trust": 90, "rivalry": 0}
        motion = {"type": "set_policy", "subject": "military", "value": f"{w.policy.military + .02:.3f}"}
        # The democrat's no becomes an abstention for a trusted friend; the dove's stays a no.
        democrat = ScriptedBackend({"persona": "democrat"})._vote(w, "A", {"id": "M1", "proposer": "B", **motion})
        self.assertEqual(democrat, "abstain")
        self.assertEqual(self.vote(motion), "no")

    def test_a_dove_votes_yes_on_a_cut_to_the_military_budget(self):
        motion = {"type": "set_policy", "subject": "military", "value": f"{max(.006, self.w.policy.military - .01):.3f}"}
        self.assertEqual(self.vote(motion), "yes")

    def test_a_dove_votes_yes_on_non_aggression_and_no_on_alliances_and_unions(self):
        self.assertEqual(self.vote({"type": "diplomacy", "subject": "non_aggression", "value": "", "text": ""}), "yes")
        for subject in ("alliance", "join_union", "federation"):
            with self.subTest(subject=subject):
                self.assertEqual(self.vote({"type": "diplomacy", "subject": subject, "value": "", "text": ""}), "no")


class DoveTalks(unittest.TestCase):
    def setUp(self):
        self.w = world()
        self.dove = ScriptedBackend({"persona": "dove"})

    def tabled(self) -> list:
        return [(m["type"], m["subject"]) for m in self.dove._session(self.w, "A", {"motions": []})["motions"]]

    def test_a_dove_tables_status_talks_under_a_deadline_for_status_talks(self):
        self.w.dip.ultimatum = deadline()
        self.assertIn(("diplomacy", "status_talks"), self.tabled())

    def test_a_dove_tables_trade_talks_under_any_other_deadline(self):
        self.w.dip.ultimatum = deadline(terms_id="cut_league_ties")
        tabled = self.tabled()
        self.assertIn(("diplomacy", "trade_talks"), tabled)
        self.assertNotIn(("diplomacy", "status_talks"), tabled)

    def test_no_talks_without_a_deadline(self):
        self.assertEqual(TALKS & set(self.tabled()), set())

    def test_no_talks_once_a_proposal_to_the_issuer_has_passed_in_the_last_two_months(self):
        w = self.w
        w.dip.ultimatum = deadline()
        w.foreign["proposal_log"] = [{"month": w.month - 1, "kind": "trade_talks", "party": "union"}]
        self.assertEqual(TALKS & set(self.tabled()), set())

    def test_an_older_proposal_does_not_stop_the_talks(self):
        w = self.w
        w.dip.ultimatum = deadline()
        w.foreign["proposal_log"] = [{"month": w.month - 3, "kind": "status_talks", "party": "union"}]
        self.assertIn(("diplomacy", "status_talks"), self.tabled())

    def test_a_proposal_to_the_union_answers_a_demand_from_veleria(self):
        w = self.w
        w.foreign["proposal_log"] = [{"month": w.month, "kind": "status_talks", "party": "union"}]
        w.dip.ultimatum = deadline(by="veleria")
        self.assertEqual(TALKS & set(self.tabled()), set())

    def test_a_proposal_to_the_union_does_not_answer_a_demand_from_dorsania(self):
        w = self.w
        w.foreign["proposal_log"] = [{"month": w.month, "kind": "status_talks", "party": "union"}]
        w.dip.ultimatum = deadline(by="dorsania")
        self.assertIn(("diplomacy", "status_talks"), self.tabled())

    def test_the_talks_are_kept_under_the_two_motion_cap(self):
        self.w.dip.ultimatum = deadline()
        tabled = self.tabled()                       # month 0: the democrat's military aid is due as well
        self.assertEqual(tabled[0], ("diplomacy", "status_talks"))
        self.assertLessEqual(len(tabled), 2)

    def test_a_dove_never_tables_a_raise_in_arms_where_the_hawk_would(self):
        w = self.w
        w.month = 2
        w.dip.union_formed = True
        w.mil.army.morale = .3
        hawk = ScriptedBackend({"persona": "hawk"})._session(w, "D", {"motions": []})["motions"]
        self.assertIn(("set_policy", "military"), [(m["type"], m["subject"]) for m in hawk])   # the scene does call for it
        dove = self.dove._session(w, "A", {"motions": []})["motions"]
        self.assertFalse(any(m["type"] == "set_policy" and m["subject"] in ("military", "army_target", "recruitment",
                                                                           "mobilization", "posture")
                             for m in dove))


class DoveOrders(unittest.TestCase):
    def setUp(self):
        self.w = world()
        self.dove = ScriptedBackend({"persona": "dove"})
        self.hawk = ScriptedBackend({"persona": "hawk"})

    def test_the_army_holder_keeps_defence_and_no_recruitment_at_war_or_under_a_deadline(self):
        w = self.w
        for setup in ({"war": True}, {"ultimatum": deadline()}):
            with self.subTest(setup=setup):
                w.dip.war = bool(setup.get("war"))
                w.dip.ultimatum = setup.get("ultimatum", {})
                orders = self.dove._orders(w, "army")
                self.assertEqual((orders["recruitment"], orders["posture"]), ("none", "defend"))
                self.assertEqual(orders["army_target"], w.policy.army_target)
        w.dip.war, w.dip.ultimatum = True, {}
        self.assertEqual(self.hawk._orders(w, "army")["recruitment"], "general")     # what the hawk would order

    def test_the_treasury_keeps_the_military_budget_and_the_navy_builds_no_warships(self):
        w = self.w
        w.dip.war = True
        self.assertEqual(self.dove._orders(w, "treasury")["military"], w.policy.military)
        self.assertEqual(self.hawk._orders(w, "treasury")["military"], 0.08)
        w.dip.war = False
        w.dip.ultimatum = deadline()
        self.assertFalse(self.dove._orders(w, "navy")["shipbuilding"])
        self.assertTrue(self.hawk._orders(w, "navy")["shipbuilding"])


class DoveIsAPersona(unittest.TestCase):
    def test_a_seat_may_name_the_dove_and_gets_the_dove_backend(self):
        cfg = normalize_config({"run": {}, "seat": [{"provider": "scripted", "persona": "dove"}]}, "test")
        seat = cfg["seats"][0]
        self.assertEqual(seat["label"], "dove")
        self.assertEqual(make_backend(seat).model, "scripted:dove")


if __name__ == "__main__":
    unittest.main()
