"""Voting reasons and conditions must survive normalization and affect real tallies."""
import unittest

from karamaniya import actions, agents, deliberation, politics, prompts
from karamaniya.backends.scripted import ScriptedBackend
from karamaniya.council import (Council, _abstain_unresolved_conditional,
                                _conditional_reason_clashes, _decision_ballot_repairs,
                                _merge_vote_repair)
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

    def test_v2_decision_schema_separates_metric_and_motion_condition_fields(self):
        schema = actions.decision_schema_v2(self.w, "A", ["D1", "M3"])
        props = schema["properties"]["vote_conditions"]["items"]["properties"]
        self.assertIn("none", props["metric"]["enum"])
        self.assertIn("none", props["operator"]["enum"])
        self.assertIn("none", props["other_motion"]["enum"])
        instructions = prompts.decision_instructions_v2(
            self.w, "A", [{"id": "D1"}, {"id": "M3"}], 0, False, False)
        self.assertIn("different live motion ID", instructions)
        self.assertIn("never this motion or 'none'", instructions)

    def test_malformed_ballots_get_scoped_repair_targets_and_preserve_other_votes(self):
        raw = {"votes": {"D1": "yes", "M3": "conditional", "M4": "no"},
               "vote_reasons": {"M3": "Only if the other measure passes.",
                                "M4": "This spends too much."},
               "vote_conditions": [{"motion_id": "M3", "kind": "motion",
                                    "other_motion": "M3", "other_outcome": "passes",
                                    "if_unmet": "abstain", "metric": "none",
                                    "operator": "none", "value": 0}],
               "notes": "Keep unrelated decision context."}
        original, problems = actions.normalize_decision_v2(self.w, "A", raw,
                                                            ["D1", "M3", "M4"], 0)
        self.assertIn("invalid motion condition for M3", problems)
        self.assertIn("conditional vote missing valid condition for M3", problems)
        repairs = _decision_ballot_repairs(problems)
        self.assertEqual([(x["motion"], x["reason"], x["condition"]) for x in repairs],
                         [("D1", True, False), ("M3", False, True)])

        repair_raw = {"votes": {"D1": "no", "M3": "conditional", "M4": "yes"},
                      "vote_reasons": {"D1": "The safeguards need a public explanation.",
                                       "M3": "Only if D1 passes.",
                                       "M4": "This is affordable."},
                      "vote_conditions": [{"motion_id": "M3", "kind": "motion",
                                           "other_motion": "D1", "other_outcome": "passes",
                                           "if_unmet": "abstain", "metric": "none",
                                           "operator": "none", "value": 0}],
                      "notes": "A repair must not overwrite these notes."}
        repaired, repaired_problems = actions.normalize_decision_v2(
            self.w, "A", repair_raw, ["D1", "M3", "M4"], 0)
        self.assertEqual(repaired_problems, [])
        merged = _merge_vote_repair(original, repaired, [], repairs)
        self.assertEqual(merged["votes"], {"D1": "yes", "M3": "conditional", "M4": "no"})
        self.assertEqual(merged["vote_reasons"]["D1"], "The safeguards need a public explanation.")
        self.assertEqual(merged["vote_conditions"]["M3"]["other_motion"], "D1")
        self.assertEqual(merged["notes"], "Keep unrelated decision context.")

    def test_multiple_vote_conditions_are_preserved_and_all_must_pass(self):
        raw = {"votes": {"M1": "conditional"},
               "vote_reasons": {"M1": "Only if food supply is stable and army arrears are low."},
               "vote_conditions": [
                   {"motion_id": "M1", "kind": "metric", "metric": "food_ratio",
                    "operator": ">=", "value": .97, "if_unmet": "no"},
                   {"motion_id": "M1", "kind": "metric", "metric": "army_arrears",
                    "operator": "<=", "value": .25, "if_unmet": "no"}]}
        normalized, problems = actions.normalize_decision_v2(self.w, "A", raw, ["M1"], 0)
        self.assertEqual(problems, [])
        self.assertEqual(len(normalized["vote_conditions"]["M1"]), 2)
        w = self.w
        w.econ.food_ratio = 1.1
        w.mil.army.arrears = 1.0
        votes = {mid: {"votes": {"M1": "yes"}, "vote_reasons": {"M1": "Support it."},
                       "vote_conditions": {}, "resign": False, "coup": None,
                       "coup_stance": "resist", "orders": {}, "private_messages": [], "notes": ""}
                 for mid in "ABCDE"}
        votes["A"] = {**votes["A"], **normalized}
        council = Council.__new__(Council)
        council.w, council.pending_dms = w, []
        motion = {"id": "M1", "proposer": "B", "type": "set_policy", "subject": "farm_support",
                  "value": "0.03", "text": "Increase farm support.", "summary": "increase farm support"}
        record = council._resolve(votes, [motion], [], list("ABCDE"), [])
        entry = record["motions"][0]
        self.assertEqual(entry["submitted_votes"]["A"], "conditional")
        self.assertEqual(entry["conditional_votes"]["A"]["counted_as"], "no")
        self.assertEqual(len(entry["conditional_votes"]["A"]["conditions"]), 2)

    def test_long_reverse_order_motion_dependency_chain_resolves(self):
        motions = [{"id": f"M{i}"} for i in range(5, 0, -1)]
        votes = {f"M{i}": {"A": "yes", "B": "yes", "C": "yes", "D": "yes", "E": "yes"}
                 for i in range(1, 6)}
        conditions = {f"M{i}": {"A": {"kind": "motion", "other_motion": f"M{i - 1}",
                                             "other_outcome": "passes", "if_unmet": "abstain"}}
                      for i in range(2, 6)}
        for i in range(2, 6):
            votes[f"M{i}"]["A"] = "conditional"

        details = deliberation.resolve_conditionals(self.w, motions, votes, conditions, {})

        for i in range(2, 6):
            with self.subTest(motion=f"M{i}"):
                self.assertEqual(votes[f"M{i}"]["A"], "yes")
                self.assertTrue(details[f"M{i}"]["A"]["met"])

    def test_resigned_voters_are_preserved_separately_from_counted_ballot(self):
        votes = {mid: {"votes": {"M1": "yes"}, "vote_reasons": {"M1": "Support it."},
                       "vote_conditions": {}, "resign": False, "coup": None,
                       "coup_stance": "resist", "orders": {}, "private_messages": [], "notes": ""}
                 for mid in "ABCDE"}
        votes["C"]["resign"] = True
        council = Council.__new__(Council)
        council.w, council.pending_dms = self.w, []
        motion = {"id": "M1", "proposer": "B", "type": "set_policy", "subject": "farm_support",
                  "value": "0.03", "text": "Increase farm support.", "summary": "increase farm support"}
        record = council._resolve(votes, [motion], [], list("ABCDE"), [])
        entry = record["motions"][0]
        self.assertEqual(entry["submitted_votes"]["C"], "yes")
        self.assertNotIn("C", entry["votes"])
        self.assertNotIn("C", entry["vote_reasons"])
        self.assertEqual(entry["tally"], "(4 yes, 0 no, 0 abstain)")

    def test_conditional_vote_condition_must_match_its_public_reason(self):
        decision = {"votes": {"D2": "conditional"},
                    "vote_conditions": {"D2": {"kind": "metric", "metric": "food_ratio",
                                                 "operator": ">=", "value": 1.0}},
                    "vote_reasons": {"D2": "Only if the League supplies written credit terms for shipbuilding."}}
        clashes = _conditional_reason_clashes(decision)
        self.assertEqual(clashes[0]["code"], "VOTE_CONDITION_REASON_MISMATCH")
        self.assertEqual(clashes[0]["metric"], "food_ratio")

    def test_starting_reserve_threshold_does_not_encode_a_no_draw_safeguard(self):
        decision = {"votes": {"D5": "conditional"},
                    "vote_conditions": {"D5": {"kind": "metric", "metric": "reserves",
                                                 "operator": ">=", "value": 50_000_000}},
                    "vote_reasons": {"D5": "I support this only if there is no draw on reserves."}}
        clashes = _conditional_reason_clashes(decision)
        self.assertEqual(clashes[0]["code"], "VOTE_CONDITION_REASON_MISMATCH")
        self.assertEqual(clashes[0]["metric"], "reserves")
        self.assertIn("no_reserve_draw", clashes[0]["reason_metrics"])

    def test_no_reserve_safeguard_conflicts_with_a_reserve_funded_motion(self):
        decision = {"votes": {"D5": "conditional"},
                    "vote_conditions": {"D5": {"kind": "metric", "metric": "reserves",
                                                 "operator": ">=", "value": 50_000_000}},
                    "vote_reasons": {"D5": "I support this only if there is no draw on reserves."}}
        motions = [{"id": "D5", "text": "Storm relief funded from reserves.",
                    "action": {"funding_plan": [{"source": "reserves", "amount": 5_000_000}]}}]
        clashes = _conditional_reason_clashes(decision, motions)
        self.assertTrue(clashes[0]["motion_conflicts"])

    def test_unresolved_conditional_safeguard_is_counted_as_abstention(self):
        decision = {"votes": {"D5": "conditional"},
                    "vote_conditions": {"D5": {"kind": "metric", "metric": "reserves",
                                                 "operator": ">=", "value": 50_000_000}}}
        clashes = [{"code": "VOTE_CONDITION_REASON_MISMATCH", "motion": "D5"}]
        _abstain_unresolved_conditional(decision, clashes)
        self.assertEqual(decision["votes"]["D5"], "abstain")
        self.assertNotIn("D5", decision["vote_conditions"])
        self.assertEqual(clashes[0]["resolution"], "abstained_after_condition_repair_failed")

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
        motion = {"type": "set_policy", "subject": "tax", "value": str(w.policy.tax), "text": "Set tax to its existing level."}
        self.assertIn("already the binding current directive", politics.validate_motion(w, motion))

    def test_existing_constitution_and_appointment_are_not_new_agenda_items(self):
        w = self.w
        w.const.offices["navy"] = "A"
        self.assertIn("already held", politics.validate_motion(
            w, {"type": "assign_office", "subject": "navy", "value": "A", "text": "Assign A to Navy."}))
        self.assertIn("already vacant", politics.validate_motion(
            w, {"type": "vacate_office", "subject": "army", "value": "", "text": "Leave Army vacant."}))
        self.assertIn("already", politics.validate_motion(
            w, {"type": "constitution", "subject": "decision_rule", "value": w.const.decision_rule,
                "text": "Keep the existing decision rule."}))

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
