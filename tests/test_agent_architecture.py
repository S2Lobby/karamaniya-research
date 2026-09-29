"""Seeded delegate state, canonical decision context, commitments, and integrity checks."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import agents  # noqa: E402
from karamaniya.decision_context import canonical_hard_state, private_intelligence  # noqa: E402
from karamaniya.engine import step  # noqa: E402
from karamaniya.world import World, new_world  # noqa: E402


class AgentArchitecture(unittest.TestCase):
    def test_psychology_is_seeded_persistent_and_not_a_role_stereotype(self):
        one, same, other = new_world(41), new_world(41), new_world(42)
        a = one.member("A").agent_state
        self.assertEqual(a, same.member("A").agent_state)
        self.assertNotEqual(a, other.member("A").agent_state)
        self.assertEqual(set(a["traits"]), set(agents.TRAITS))
        self.assertNotEqual(one.member("A").agent_state["traits"],
                            one.member("D").agent_state["traits"])
        context = agents.context(one, "A")
        self.assertIn("PRIVATE INTERNAL DISPOSITION", context)       # version 2 wording (spec 6)
        legacy = new_world(41, agent_architecture_version=1)
        self.assertIn("PRIVATE DISPOSITION", agents.context(legacy, "A"))
        self.assertNotIn("ambition:", context.lower())
        self.assertNotIn("paranoia:", context.lower())

    def test_legacy_world_migrates_without_relabeling_its_architecture(self):
        data = new_world(7).to_dict()
        data.pop("agent_architecture_version")
        data.pop("integrity")
        for member in data["members"]:
            for key in ("agent_state", "relationships", "commitments", "promises"):
                member.pop(key, None)
        old = World.from_dict(data)
        self.assertEqual(old.agent_architecture_version, 0)
        self.assertTrue(all(not m.agent_state and not m.relationships for m in old.members))

    def test_previous_agent_state_receives_new_nested_defaults(self):
        w = new_world(8)
        state = w.member("A").agent_state
        state["version"] = 1
        state["beliefs"].pop("economic_outlook")
        state["stress"].pop("security")
        state["constituencies"]["national electorate"].pop("support_for_delegate")
        agents.ensure(w)
        self.assertIn("economic_outlook", state["beliefs"])
        self.assertIn("security", state["stress"])
        self.assertIn("support_for_delegate", state["constituencies"]["national electorate"])
        agents.update_conditions(w)

    def test_canonical_state_tracks_current_offices_currency_and_constraints(self):
        w = new_world(3)
        w.const.offices["treasury"] = "B"
        w.econ.currency = "karam"
        text = canonical_hard_state(w, "simultaneous decisions", [])
        self.assertIn("treasury: Delegate B", text)
        self.assertIn("Currency: karam", text)
        self.assertIn("second currency launch is invalid", text)

    def test_office_reports_are_private_and_repeatable(self):
        w = new_world(9)
        w.const.offices.update({"treasury": "A", "army": "B"})
        a = private_intelligence(w, "A")
        b = private_intelligence(w, "B")
        public = canonical_hard_state(w, "decision", [])
        self.assertIn("Treasury cash desk", a)
        self.assertNotIn("Treasury cash desk", b)
        self.assertIn("Army intelligence", b)
        self.assertIn("reserves", a)
        self.assertNotIn(f"{w.econ.gold:,.0f}", public)
        self.assertNotIn("constitutional loyalty about", public)
        self.assertEqual(a, private_intelligence(w, "A"))

    def test_security_pressure_is_office_specific_and_changes_coping_context(self):
        w = new_world(22)
        w.const.offices["army"] = "A"
        w.const.offices["treasury"] = "B"
        w.dip.union_formed = True
        w.mil.army.loyalty = .15
        w.mil.army.arrears = 2
        agents.update_conditions(w)
        self.assertGreater(w.member("A").agent_state["stress"]["security"],
                           w.member("B").agent_state["stress"]["security"])
        w.member("A").agent_state["stress"].update(general=65, security=75)
        self.assertIn("Under this pressure", agents.context(w, "A"))
        legacy = new_world(22, agent_architecture_version=1)
        legacy.member("A").agent_state["stress"].update(general=65, security=75)
        self.assertIn("Under current pressure", agents.context(legacy, "A"))

    def test_new_office_constituency_attention_is_seeded_per_delegate(self):
        a, same, other = new_world(32), new_world(32), new_world(33)
        for w in (a, same, other):
            w.const.offices["navy"] = "A"
            agents.ensure(w)
        name = "sailors and dockworkers"
        first = a.member("A").agent_state["constituencies"][name]["attention"]
        self.assertEqual(first, same.member("A").agent_state["constituencies"][name]["attention"])
        self.assertNotEqual(first, other.member("A").agent_state["constituencies"][name]["attention"])

    def test_principle_violation_is_recorded_and_relationships_are_directional(self):
        w = new_world(11)
        commitment = agents.add_commitment(w, "A", "I will protect civil liberties and peaceful protest.")
        record = {
            "motions": [{"type": "set_policy", "subject": "protest_response", "value": "lethal",
                         "votes": {"A": "yes", "B": "no"}, "passed": True}],
            "decisions": {"A": {"orders": {"interior": {"protest_response": "lethal"}}}},
            "defiance": [], "coups": [],
        }
        agents.update_political(w, record)
        self.assertEqual(len(commitment["violations"]), 1)
        self.assertLess(w.member("B").relationships["A"]["trust"],
                        w.member("A").relationships["B"]["trust"])
        self.assertTrue(any(e["kind"] == "principle_violation" for e in w.events))

    def test_routine_unanimity_does_not_create_an_instant_alliance(self):
        w = new_world(14)
        votes = {mid: "yes" for mid in "ABCDE"}
        for month in range(10):
            w.month = month
            agents.update_political(w, {"motions": [{"type": "diplomacy", "subject": "trade_talks",
                                                      "value": "", "proposer": "A", "summary": "trade talks",
                                                      "votes": votes, "passed": True}],
                                        "decisions": {}, "defiance": [], "coups": []})
        self.assertLess(w.member("B").relationships["C"]["trust"], 53)
        self.assertLess(w.member("B").relationships["A"]["trust"], 54)

    def test_pivotal_support_creates_repayable_favor_and_expulsion_creates_grievance(self):
        w = new_world(19)
        first = {"motions": [{"type": "set_policy", "subject": "tax", "value": "0.23",
                              "proposer": "A", "summary": "fund payroll", "passed": True,
                              "votes": {"A": "yes", "B": "yes", "C": "yes", "D": "no", "E": "no"}},
                             {"type": "expel", "subject": "D", "value": "", "proposer": "E",
                              "summary": "expel D", "passed": False,
                              "votes": {"A": "no", "B": "no", "C": "no", "D": "no", "E": "yes"}}],
                 "decisions": {}, "defiance": [], "coups": []}
        agents.update_political(w, first)
        debts = w.member("A").agent_state["favor_debts"]
        self.assertEqual({d["to"] for d in debts}, {"B", "C"})
        self.assertEqual(w.member("D").agent_state["grievances"][0]["against"], "E")
        w.month = 1
        agents.update_political(w, {"motions": [{"type": "set_policy", "subject": "welfare", "value": "0.05",
                                                   "proposer": "B", "summary": "fund relief", "passed": True,
                                                   "votes": {"A": "yes", "B": "yes", "C": "no", "D": "yes", "E": "no"}}],
                                    "decisions": {}, "defiance": [], "coups": []})
        self.assertEqual(next(d for d in debts if d["to"] == "B")["status"], "repaid")
        self.assertEqual(next(d for d in debts if d["to"] == "C")["status"], "active")

    def test_pivotal_favor_uses_rule_at_vote_not_later_rule(self):
        w = new_world(26)
        w.const.decision_rule = "unanimity"  # a later motion changed the rule
        record = {"motions": [{"type": "set_policy", "subject": "tax", "value": "0.23",
                               "proposer": "A", "summary": "fund payroll", "passed": True,
                               "eligible_voters": list("ABCDE"), "decision_rule_at_vote": "majority",
                               "votes": {"A": "yes", "B": "yes", "C": "yes", "D": "no", "E": "no"}}],
                  "decisions": {}, "defiance": [], "coups": []}
        agents.update_political(w, record)
        self.assertEqual({d["to"] for d in w.member("A").agent_state["favor_debts"]}, {"B", "C"})

    def test_scheduling_a_fair_election_is_not_misread_as_delaying_it(self):
        w = new_world(12)
        commitment = agents.add_commitment(w, "A", "I will defend constitutional democracy and timely elections.")
        record = {"pre_resolution": {"election_month": -1},
                  "motions": [{"type": "constitution", "subject": "election_month", "value": "18",
                               "votes": {"A": "yes"}}],
                  "decisions": {"A": {}}, "defiance": [], "coups": []}
        self.assertNotIn("election_delay", agents._action_tags(record, "A"))
        delayed = {**record, "pre_resolution": {"election_month": 17},
                   "motions": [{"type": "constitution", "subject": "election_month", "value": "30",
                                "votes": {"A": "yes"}}]}
        self.assertIn("election_delay", agents._action_tags(delayed, "A"))
        self.assertEqual(commitment["violations"], [])

    def test_engine_writes_integrity_warnings_without_crashing(self):
        w = new_world(13, months=1)
        step(w)
        self.assertEqual(w.integrity["status"], "clean")
        self.assertEqual(w.history[-1]["integrity"]["warnings"], [])
        w.const.offices["head"] = "missing"
        from karamaniya.state_validation import refresh
        state = refresh(w)
        self.assertEqual(state["status"], "warnings")
        self.assertEqual(state["warnings"][0]["code"], "officeholder_invalid")

    def test_zero_fatality_counter_changes_do_not_create_chronicle_events(self):
        w = new_world(27)
        before = len(w.events)
        w.count("deaths_hunger", 0)
        self.assertEqual(len(w.events), before)
        w.count("deaths_hunger", 2)
        self.assertEqual(w.events[-1]["kind"], "fatality_counter")
        self.assertEqual(w.events[-1]["amount"], 2)


if __name__ == "__main__":
    unittest.main()
