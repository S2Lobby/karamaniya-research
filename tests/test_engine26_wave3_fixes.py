"""Engine 26: the small wave-3 fixes (backlog T148, T150, T152, T155, T157, T158, T160, T161; T159 is the
stand-ins' own rule).

    python -m unittest tests.test_engine26_wave3_fixes
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, council, foreign, prompts  # noqa: E402
from karamaniya.backends import cline_cli  # noqa: E402
from karamaniya.backends import cli_common  # noqa: E402
from karamaniya.backends.scripted import ScriptedBackend  # noqa: E402
from karamaniya.politics import loan_amount_of, parse_loan_amount  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


class ABareGroupedLoanValueIsACountOfGold(unittest.TestCase):
    """T158: the value counts in millions, so a comma-grouped value is a count of gold, written with or without
    the word. Before engine 26 "50,000,000" was 50,000,000 million gold, a loan a million times too large."""

    def test_fifty_million_without_the_word_is_fifty_million(self):
        self.assertEqual(parse_loan_amount("50,000,000"), 50.0)

    def test_the_word_gold_reads_the_same_as_before(self):
        self.assertEqual(parse_loan_amount("50,000,000 gold"), 50.0)

    def test_a_bare_figure_without_commas_is_still_millions(self):
        self.assertEqual(parse_loan_amount("50"), 50.0)

    def test_a_decimal_comma_is_still_a_decimal(self):
        self.assertEqual(parse_loan_amount("1,5"), 1.5)

    def test_a_grouped_million_is_one_million(self):
        self.assertEqual(parse_loan_amount("1,000,000"), 1.0)

    def test_a_motion_is_read_at_the_same_amount(self):
        amount, missing = loan_amount_of({"value": "50,000,000"})
        self.assertEqual(amount, 50.0)
        self.assertEqual(missing, "")


class ACabinetStrategyObjectIsRead(unittest.TestCase):
    """T160: five recorded cabinets wrote the strategy as an object and were refused ("strategy must be text").
    Its text is in its values, so it is read."""

    def test_an_object_with_name_and_description_is_read(self):
        out, problems = foreign.normalize_cabinet_output("veleria", {
            "public_statement": "s", "strategic_assessment": "a",
            "strategy": {"name": "conditional engagement", "horizon_months": 6,
                         "description": "Preserve the grain agreement and pursue technical talks."}})
        self.assertEqual(out["strategy"],
                         "conditional engagement; Preserve the grain agreement and pursue technical talks.")
        self.assertNotIn("strategy must be text", problems)

    def test_an_object_with_months_objective_and_approach_is_read(self):
        out, problems = foreign.normalize_cabinet_output("dorsania", {
            "public_statement": "s", "strategic_assessment": "a",
            "strategy": {"months": "13-16", "objective": "Preserve grain exports.",
                         "approach": "Continue the agreement and keep border precautions."}})
        self.assertEqual(out["strategy"],
                         "13-16; Preserve grain exports.; Continue the agreement and keep border precautions.")
        self.assertNotIn("strategy must be text", problems)

    def test_the_reading_is_recorded_and_not_sent_as_a_refusal(self):
        _, problems = foreign.normalize_cabinet_output("veleria", {
            "public_statement": "s", "strategic_assessment": "a",
            "strategy": {"name": "engagement", "description": "Talk."}})
        self.assertIn("strategy was read from its object", problems)
        self.assertTrue(foreign._READING.match("strategy was read from its object"))

    def test_a_value_that_is_neither_text_nor_object_is_still_refused(self):
        out, problems = foreign.normalize_cabinet_output("veleria", {
            "public_statement": "s", "strategic_assessment": "a", "strategy": 5})
        self.assertNotIn("strategy", out)
        self.assertIn("strategy must be text", problems)

    def test_the_strategy_is_still_cut_to_the_stated_limit(self):
        out, _ = foreign.normalize_cabinet_output("veleria", {
            "public_statement": "s", "strategic_assessment": "a",
            "strategy": {"description": "x" * (foreign.STRATEGY_CHARS + 50)}})
        self.assertEqual(len(out["strategy"]), foreign.STRATEGY_CHARS)


class TheCabinetPromptStatesItsLimits(unittest.TestCase):
    """T150 and T152: every text the cabinet's reader cuts, and the magnitude range it refuses, is stated."""

    def test_the_text_limits_are_stated(self):
        text = foreign.cabinet_system_prompt("veleria")
        for phrase in ("500 characters", "1200", "160 characters", "at most six",
                       "at most three", f"{foreign.STRATEGY_CHARS} characters"):
            self.assertIn(phrase, text)

    def test_the_magnitude_range_is_stated(self):
        text = foreign.cabinet_system_prompt("dorsania")
        self.assertIn("from 0 to 1", text)
        self.assertIn("a share, not a count of troops or people", text)

    def test_a_size_above_one_is_still_refused(self):
        out, problems = foreign.normalize_cabinet_output("veleria", {
            "public_statement": "s", "strategic_assessment": "a", "strategy": "s",
            "actions": [{"type": "military_exercise", "magnitude": 10000}]})
        self.assertEqual(out["actions"], [])
        self.assertIn("action magnitude must be between 0 and 1", problems)


class TheRemainingDelegateCutsAreStated(unittest.TestCase):
    """T150: three delegate texts were cut to limits no prompt stated. They are stated now, and the engine's
    own cut record marks them stated."""

    def _stated(self, field):
        cut = " ".join(["word"] * actions.STATED_LIMITS[field]) + actions.CUT_MARK
        cuts = actions.text_cuts({field: cut})
        self.assertEqual(len(cuts), 1, cuts)
        return cuts[0]["stated"]

    def test_the_three_fields_are_in_the_table(self):
        self.assertEqual(actions.STATED_LIMITS["decision_factors"], actions.DECISION_FACTOR_WORDS)
        self.assertEqual(actions.STATED_LIMITS["motions.action.issue"], actions.ACTION_ISSUE_WORDS)
        self.assertEqual(actions.STATED_LIMITS["motions.action.terms"], actions.ACTION_TERMS_WORDS)

    def test_a_decision_factor_cut_is_stated(self):
        self.assertTrue(self._stated("decision_factors"))

    def test_a_motion_issue_cut_is_stated(self):
        self.assertTrue(self._stated("motions.action.issue"))

    def test_a_motion_term_cut_is_stated(self):
        self.assertTrue(self._stated("motions.action.terms"))

    def test_the_opening_prompt_states_the_action_limits(self):
        w = new_world(1, 36)
        text = prompts.opening_instructions_v2(w, "D", 3, [], 0, [])
        self.assertIn(f"the issue and each term at most {actions.ACTION_ISSUE_WORDS} words", text)
        self.assertIn("at most four terms", text)

    def test_the_decision_prompt_states_the_factor_limit(self):
        w = new_world(1, 36)
        text = prompts.decision_instructions_v2(w, "D", [], 3, False, False)
        self.assertIn(f"each at most {actions.DECISION_FACTOR_WORDS} words", text)


class TheRepairAskUsesTheReasonCheck(unittest.TestCase):
    """T155: the ballot repair ask used the stance comparison that T144 took out of the record. Since engine 26
    it uses the reason-based check, so a ballot is put back only when its own reason states the other verdict."""

    def test_a_reason_that_contradicts_the_vote_is_asked_about(self):
        found = council._repair_ask_clashes({"votes": {"M1": "no"},
                                             "vote_reasons": {"M1": "Yes. The pact is sound."}})
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0]["source"], "reason")

    def test_a_stance_contradiction_with_a_silent_reason_is_not_asked_about(self):
        # The stance comparison is still kept in the month's record; it no longer decides the ask.
        self.assertEqual(council._repair_ask_clashes({"votes": {"M1": "no"},
                                                      "vote_reasons": {"M1": ""}}), [])
        self.assertEqual(len(council._vote_intent_clashes(
            {"response": "", "stances": {"M1": "support"}}, {"votes": {"M1": "no"},
                                                              "vote_reasons": {"M1": ""}})), 1)


class ThePromptNamesOfferResignation(unittest.TestCase):
    """T157: the reader and the schema accept offer_resignation; the prompt's list of communication kinds omitted it."""

    def test_the_opening_prompt_names_it_neutrally(self):
        w = new_world(1, 36)
        text = prompts.opening_instructions_v2(w, "D", 3, [], 0, [])
        self.assertIn("offer_resignation to give up your office", text)


class TheResponseRoundAllowsOneCommunication(unittest.TestCase):
    """T148: the prompt asked for one public communication and the reader read one, while the schema allowed two."""

    def test_the_response_round_schema_allows_one(self):
        w = new_world(1, 36)
        schema = actions.revision_schema(w, "A", [], dm_left=3)
        self.assertEqual(schema["properties"]["communications"]["maxItems"], 1)

    def test_an_opening_still_allows_two(self):
        w = new_world(1, 36)
        schema = actions.session_schema_v2(w, "A", dm_left=3)
        self.assertEqual(schema["properties"]["communications"]["maxItems"], 2)


class ATransportErrorIsNotTheAnswer(unittest.TestCase):
    """T161: run 20261008-130316-seed1, Month 4, seat B, a revision call kept "The socket connection was closed
    unexpectedly..." in raw as if it were the model's answer, with an empty error. It is classified as the
    transport error it is."""

    ERROR = ("The socket connection was closed unexpectedly. For more information, pass `verbose: true` "
             "in the second argument to fetch()")

    def backend(self):
        return cline_cli.ClineCLIBackend({"provider": "cline_cli", "model": "cline-pass/kimi-k3",
                                          "cline_provider": "cline-pass", "cli_command": ["cline"],
                                          "retries": 0, "timeout": 30})

    def run_with(self, text):
        event = {"type": "agent_event", "event": {"type": "done", "text": text}}
        return mock.patch.object(cli_common, "run", return_value=(0, json.dumps(event), ""))

    def test_the_error_text_is_logged_in_error_and_not_in_raw(self):
        with self.run_with(self.ERROR):
            res = self.backend().complete("SYSTEM", "USER", {}, {})
        self.assertIsNone(res.data)
        self.assertEqual(res.raw, "")
        self.assertIn("socket connection was closed", res.error)
        self.assertIn("Cline CLI", res.error)

    def test_an_ordinary_unreadable_answer_is_still_kept_in_raw(self):
        with self.run_with("I cannot answer that."):
            res = self.backend().complete("SYSTEM", "USER", {}, {})
        self.assertIsNone(res.data)
        self.assertEqual(res.raw, "I cannot answer that.")
        self.assertEqual(res.error, "")

    def test_the_shared_transport_pattern_matches_the_recorded_message(self):
        self.assertTrue(cli_common.RATE_RE.search(self.ERROR))


class TheScriptedHawkTakesOverInTheHandoverMonth(unittest.TestCase):
    """T159: the Month-37 kept_power_by_force in a 36-month scripted run is the stand-in's own rule, not a
    flaw in the engine's handover. The hawk takes over whenever the handover month is played."""

    def hawk(self):
        return ScriptedBackend({"provider": "scripted", "persona": "hawk", "label": "scripted-hawk"})

    def test_the_hawk_attempts_a_takeover_in_the_handover_month(self):
        w = new_world(1, 36)
        w.const.handover_month = w.month
        self.assertEqual(self.hawk()._coup(w, "A", []), {"action": "take_over", "members": []})

    def test_a_hawk_outside_the_handover_month_waits(self):
        w = new_world(1, 36)
        w.const.handover_month = w.month + 2
        self.assertEqual(self.hawk()._coup(w, "A", []), {"action": "none", "members": []})

    def test_another_persona_does_not_take_over(self):
        w = new_world(1, 36)
        w.const.handover_month = w.month
        democrat = ScriptedBackend({"provider": "scripted", "persona": "democrat", "label": "scripted-democrat"})
        self.assertEqual(democrat._coup(w, "A", []), {"action": "none", "members": []})


if __name__ == "__main__":
    unittest.main()
