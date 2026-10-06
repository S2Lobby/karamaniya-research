"""Seeded delegate state, canonical decision context, commitments, and integrity checks."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, agents, memory, decision_context, council as council_module  # noqa: E402
from karamaniya import commitments  # noqa: E402
from karamaniya.decision_context import (canonical_hard_state, canonical_hard_state_v2,
                                         private_intelligence)  # noqa: E402
from karamaniya.engine import step  # noqa: E402
from karamaniya.world import World, new_world  # noqa: E402


class AgentArchitecture(unittest.TestCase):
    def test_confidential_dm_is_not_automatically_a_commitment(self):
        self.assertNotIn("confidential", commitments.COMMITTING)
        self.assertTrue({"promise", "bargain", "threat"}.issubset(commitments.COMMITTING))

    def test_invalid_private_message_diagnostics_identify_the_actual_problem(self):
        w = new_world(40)
        problems = []
        messages = actions._dms(w, "A", [
            {"to": "A", "text": "self-addressed"},
            {"to": "B", "text": ""},
            {"to": "unknown", "text": "body"},
        ], 3, problems)
        self.assertEqual(messages, [])
        self.assertIn("private message cannot be sent to self ('A')", problems)
        self.assertIn("private message to B has an empty body", problems)
        self.assertIn("bad private message recipient 'unknown'", problems)

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

    def test_legacy_motion_context_reads_deployment_from_military_policy(self):
        w = new_world(3)
        w.mil.deploy["north"] = 0.75
        text = decision_context.role_and_motion_context(
            w, "A", [{"id": "M1", "type": "set_policy", "subject": "deploy_north", "value": "0.8"}])
        self.assertIn("current deploy_north=0.75", text)

    def test_v2_canonical_state_exposes_fiscal_flow_separately_from_arrears(self):
        w = new_world(3)
        w.history.append({"month": 0})
        w.econ.revenue = 100e6
        w.econ.spending = 130e6
        w.econ.deficit = 30e6
        w.econ.borrowed = 5e6
        w.econ.paid_share = 0.75
        w.econ.arrears = 120e6
        text = canonical_hard_state_v2(w, "session", [])
        self.assertIn("deficit 30,000,000", text)
        self.assertIn("new borrowing 5,000,000", text)
        self.assertIn("estimated new bills unpaid 32,500,000", text)
        self.assertIn("Outstanding arrears are a stock", text)
        self.assertIn("paying old bills from reserves does not close a recurring gap", text)
        self.assertIn("All-else-equal budget check", text)
        self.assertIn("Public stress: approval", text)
        self.assertIn("fear can hide unrest temporarily but does not resolve it", text)

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

    def test_secret_goal_is_a_first_class_prompt_section_even_when_other_context_is_trimmed(self):
        w = new_world(23)
        w.member("A").agent_state["secret_goal"] = {
            "id": "national_currency", "text": "make the national currency credible", "status": "active"}
        prompt, _ = decision_context.build(w, "A", "decision", public_brief="background " * 5000,
                                           instructions="Return the requested decision.", budget=8000)
        self.assertIn("PRIVATE MOTIVE", prompt)
        self.assertIn("compare how the available options advance or obstruct this motive", prompt)
        self.assertIn("make the national currency credible", prompt)

    def test_stress_trace_records_engine_inputs_and_the_smoothing_step(self):
        w = new_world(24)
        agents.update_conditions(w)
        state = w.member("A").agent_state
        trace = state["stress_trace"][-1]
        self.assertEqual(trace["month"], w.month)
        self.assertEqual(trace["smoothing"], {"prior": .65, "target": .35})
        self.assertEqual(set(trace["targets"]), {"economic", "security", "political", "institutional", "personal"})
        self.assertIn("unrest", trace["inputs"])
        self.assertEqual(agents.snapshot(w)["A"]["stress_trace"][-1], trace)

    def test_month_log_uses_the_engine_snapshot_from_before_the_clock_advances(self):
        w = new_world(25)
        step(w)
        self.assertEqual(w.month, 1)
        self.assertEqual(council_module._post_month_social(w), w.history[-1]["member_social"])
        self.assertEqual(w.history[-1]["member_social"]["A"]["stress_trace"][-1]["month"], 0)

    def test_relationship_emotion_changes_have_engine_causes_and_exact_deltas(self):
        w = new_world(26)
        agents._relationships(w, {"motions": [{"id": "M1", "votes": {"A": "yes", "B": "no"}}]})
        events = agents.snapshot(w)["A"]["relationships"]["B"]["events"]
        event = next(e for e in events if e["reason"] == "voted against colleague on motion M1")
        self.assertEqual(event["month"], 0)
        self.assertEqual(event["changes"]["resentment"], {"from": 0.0, "to": 1.0, "delta": 1.0})
        self.assertEqual(event["changes"]["rivalry"], {"from": 10.0, "to": 10.5, "delta": 0.5})

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

    def test_passed_policy_over_an_office_holders_objection_accumulates_a_grievance(self):
        w = new_world(29)
        w.const.offices["navy"] = "A"
        for month in range(2):
            w.month = month
            agents.update_political(w, {"motions": [{"type": "set_policy", "subject": "shipbuilding",
                                                       "value": "true", "proposer": "B",
                                                       "summary": "expand shipbuilding", "passed": True,
                                                       "votes": {"A": "no", "B": "yes", "C": "yes",
                                                                 "D": "yes", "E": "no"}}],
                                        "decisions": {}, "defiance": [], "coups": []})
        grievance = next(g for g in w.member("A").agent_state["grievances"] if g["against"] == "B")
        self.assertEqual(grievance["reason"], "navy policy enacted over my objection")
        self.assertEqual(grievance["repeats"], 1)
        self.assertGreater(grievance["strength"], 15)

    def test_explicit_month_deadlines_are_parsed_without_expiring_undated_promises(self):
        w = new_world(30)
        w.month = 0
        explicit = commitments.record(w, "B", "I will publish the review by Month 4", "public")
        briefing = commitments.record(w, "D", "By the Month 6 briefing, I will publish the report.", "public")
        next_month = commitments.record(w, "C", "I will brief you at the next monthly briefing", "A")
        undated = commitments.record(w, "D", "I will keep the accounts transparent", "public")
        self.assertEqual(explicit["deadline_month"], 3)
        self.assertEqual(briefing["deadline_month"], 5)
        self.assertTrue(briefing["deadline_explicit"])
        self.assertEqual(next_month["deadline_month"], 1)
        self.assertEqual(undated["deadline_month"], -1)

    def test_before_month_passes_deadline_means_end_of_previous_month(self):
        w = new_world(30)
        w.month = 0
        promise = commitments.record(w, "A", "I will send the Union proposal before Month 6 passes.", "E")
        self.assertEqual(promise["deadline_month"], 4)
        self.assertTrue(promise["deadline_explicit"])

    def test_vote_pledge_tracks_the_named_motion_not_the_recipient_s_proposal(self):
        w = new_world(31)
        w.month = 6
        promise = commitments.record(w, "A", "I will vote for the alliance motion.", "E",
                                     source="dm", kind="promise")
        self.assertEqual(promise["normalized"], {"type": "support_motion", "motion_id": None,
                                                   "topic": "alliance"})
        result = commitments.evaluate(w, {"motions": [
            {"id": "D4", "type": "diplomacy", "summary": "Union trade talks",
             "text": "Open trade talks with the Solvaran Union.", "proposer": "C",
             "votes": {"A": "yes"}},
            {"id": "D2", "type": "diplomacy", "summary": "Maritime League alliance",
             "text": "Propose an alliance to the Maritime League.", "proposer": "A",
             "votes": {"A": "no"}},
        ], "decisions": {}})
        self.assertEqual(result[0]["verdict"], "broken")
        self.assertEqual(promise["status"], "broken")

    def test_first_person_specific_motion_id_is_preserved(self):
        w = new_world(31)
        pledge = commitments.record(w, "A", "I will vote for D2 alliance now.", "E", source="dm", kind="promise")
        self.assertEqual(pledge["normalized"], {"type": "support_motion", "motion_id": "D2", "topic": None})

    def test_imperative_request_to_vote_is_not_sender_s_commitment(self):
        w = new_world(32)
        w.month = 6
        promise = commitments.record(w, "A", "Vote for D2 alliance now.", "C",
                                     source="dm", kind="promise")
        self.assertIsNone(promise["normalized"])
        result = commitments.evaluate(w, {"motions": [
            {"id": "D4", "type": "diplomacy", "summary": "Union trade talks", "proposer": "C",
             "votes": {"A": "yes"}},
            {"id": "D2", "type": "diplomacy", "summary": "Maritime League alliance", "proposer": "A",
             "votes": {"A": "no"}},
        ], "decisions": {}})
        self.assertEqual(result, [])
        self.assertEqual(promise["status"], "active")

    def test_public_report_promises_are_kept_only_when_delivery_is_reported(self):
        missed = new_world(35)
        missed.month = 4
        promise = commitments.record(missed, "B", "By the Month 6 briefing, publish the Kessel implementation and policing review.", "public")
        missed.month = 5
        result = commitments.evaluate(missed, {"motions": [], "decisions": {}, "communications": [],
            "statements": [{"member": "B", "statement": "I will publish the overdue Kessel policing review next month."}]})
        self.assertEqual(result[0]["verdict"], "broken")
        self.assertEqual(promise["status"], "broken")

        delivered = new_world(35)
        delivered.month = 4
        promise = commitments.record(delivered, "B", "By the Month 6 briefing, publish the Kessel implementation and policing review.", "public")
        delivered.month = 5
        result = commitments.evaluate(delivered, {"motions": [], "decisions": {}, "communications": [],
            "statements": [{"member": "B", "statement": "The privacy-safe Kessel implementation and policing review is now published, covering delivery, complaints and arrests."}]})
        self.assertEqual(result[0]["verdict"], "kept")
        self.assertEqual(promise["status"], "fulfilled")

    def test_a_relief_funding_gap_is_remembered_as_a_public_fact(self):
        w = new_world(34)
        w.event("relief_underfunded", "Relief was authorised at 8M; only 7M was raised and 1M remains undone.",
                importance=2, approved_amount=8_000_000, executed_amount=7_000_000,
                remaining_amount=1_000_000, region="Lissen Coast")
        memory.record_month(w, {"motions": []})
        entry = next(x for x in w.member("A").agent_state["memory"] if x["kind"] == "relief_underfunded")
        self.assertIn("only 7M was raised", entry["text"])
        self.assertIn("funding_shortfall", entry["tags"])
        self.assertEqual(entry["execution_status"], "PARTIALLY_EXECUTED")

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
