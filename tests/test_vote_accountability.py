"""Voting reasons and conditions must survive normalization and affect real tallies."""
import unittest

from karamaniya import actions, agents, politics, prompts
from karamaniya.backends.scripted import ScriptedBackend
from karamaniya.council import Council
from karamaniya.world import new_world


class VoteAccountability(unittest.TestCase):
    def setUp(self):
        self.w = new_world(3, 6, member_ids=list("ABCDE"))

    def test_conditional_vote_uses_month_opening_state_and_records_reason(self):
        w = self.w
        w.econ.food_ratio = .91
        raw = {"votes": {"M1": "conditional"},
               "vote_reasons": {"M1": "Support aid only if food supply is already stable."},
               "vote_conditions": [{"motion_id": "M1", "metric": "food_ratio", "operator": ">=", "value": .95}]}
        normalized, problems = actions.normalize_decision(w, "A", raw, ["M1"], 0)
        self.assertEqual(problems, [])
        votes = {mid: {**normalized, "resign": False, "coup": None, "coup_stance": "resist",
                       "orders": {}, "private_messages": [], "notes": ""} for mid in "A"}
        for mid in "BCDE":
            votes[mid] = {**votes["A"], "votes": {"M1": "yes"}, "vote_conditions": {},
                          "vote_reasons": {"M1": "Food aid is urgent."}}
        council = Council.__new__(Council)
        council.w, council.pending_dms = w, []
        motion = {"id": "M1", "proposer": "B", "type": "set_policy", "subject": "farm_support",
                  "value": "0.03", "text": "", "summary": "farm support"}
        record = council._resolve(votes, [motion], [], list("ABCDE"), [])
        self.assertEqual(record["motions"][0]["votes"]["A"], "abstain")
        self.assertEqual(record["motions"][0]["tally"], "(4 yes, 0 no, 1 abstain)")
        self.assertFalse(record["motions"][0]["conditional_votes"]["A"]["met"])
        self.assertIn("food supply", record["motions"][0]["vote_reasons"]["A"])

    def test_missing_condition_cannot_become_an_unconditional_yes(self):
        out, problems = actions.normalize_decision(
            self.w, "A", {"votes": {"M1": "conditional"}, "vote_reasons": {"M1": "Needs proof."},
                           "vote_conditions": []}, ["M1"], 0)
        self.assertEqual(out["votes"]["M1"], "conditional")
        self.assertNotIn("M1", out["vote_conditions"])
        self.assertTrue(any("missing valid condition" in problem for problem in problems))

    def test_repeated_charter_clause_is_rejected_and_rewrites_cost_capacity(self):
        w = self.w
        text = "The Constituent Assembly election shall be held in Month 18 without postponement by decree."
        motion = {"type": "amend", "subject": "", "value": "", "text": text, "proposer": "A"}
        politics.apply_motion(w, motion)
        self.assertIn("duplicates", politics.validate_motion(w, motion))
        same_date = {**motion, "text": "The election for the Constituent Assembly must occur in Month 18 even during an emergency."}
        self.assertIn("duplicates", politics.validate_motion(w, same_date))
        first = w.econ.admin_capacity
        for index in range(2):
            politics.apply_motion(w, {**motion, "text": f"Article {index}: a distinct commission shall publish its accounts every spring."})
        politics.apply_motion(w, {**motion, "text": "Another distinct article will establish port budget hearings."})
        self.assertLess(w.econ.admin_capacity, first)
        self.assertGreater(w.counters.get("charter_fatigue", 0), 0)

    def test_fiscal_tradeoff_can_produce_a_no_without_random_dissent(self):
        w = self.w
        w.econ.arrears = 1e6
        backend = ScriptedBackend({"persona": "technocrat"})
        mo = {"type": "set_policy", "subject": "military", "value": "0.10"}
        self.assertEqual(backend._vote(w, "A", mo), "no")
        w.econ.arrears = 0
        self.assertEqual(backend._vote(w, "A", mo), "yes")

    def test_identical_binding_policy_is_redundant(self):
        w = self.w
        w.const.directives["tax"] = w.policy.tax
        motion = {"type": "set_policy", "subject": "tax", "value": str(w.policy.tax)}
        self.assertIn("already the binding current directive", politics.validate_motion(w, motion))

    def test_existing_constitution_and_appointment_are_not_new_agenda_items(self):
        w = self.w
        w.const.offices["navy"] = "A"
        self.assertIn("already held", politics.validate_motion(
            w, {"type": "assign_office", "subject": "navy", "value": "A"}))
        self.assertIn("already vacant", politics.validate_motion(
            w, {"type": "vacate_office", "subject": "army", "value": ""}))
        self.assertIn("already", politics.validate_motion(
            w, {"type": "constitution", "subject": "decision_rule", "value": w.const.decision_rule}))

    def test_prompt_gives_office_tradeoff_and_demands_motion_reason(self):
        w = self.w
        w.const.offices["treasury"] = "A"
        motion = {"id": "M1", "proposer": "B", "type": "set_policy", "subject": "military",
                  "value": "0.10", "summary": "increase military budget"}
        text = prompts.decision_prompt(w, "A", "brief", "", [], [], [motion],
                                       actions.decision_schema(w, "A", ["M1"]), 0)
        self.assertIn("solvency, prices, debt", text)
        self.assertIn("readiness against fiscal space", text)
        self.assertIn("vote_reasons", text)

    def test_failed_motion_enters_persistent_memory_and_stops_scripted_repeat(self):
        w = self.w
        agents.ensure(w)
        w.const.offices["army"] = "C"
        w.dip.union_formed = True
        w.month = 2
        backend = ScriptedBackend({"persona": "hawk"})
        first = backend._session(w, "C", {"motions": []})
        proposal = next(m for m in first["motions"] if m["subject"] == "military")
        record = {"motions": [{**proposal, "id": "M1", "proposer": "C", "summary": "increase military budget",
                               "passed": False, "votes": {}}]}
        agents.update_political(w, record)
        from karamaniya import memory
        memory.record_month(w, record)
        w.month = 6
        later = backend._session(w, "C", {"motions": []})
        self.assertFalse(any(m["subject"] == "military" for m in later["motions"]))
        # Version 2 keeps the failure in the delegate's political memory, retrieved when the topic returns.
        self.assertIn("failed", memory.context(w, "C", {"military"}))


if __name__ == "__main__":
    unittest.main()
