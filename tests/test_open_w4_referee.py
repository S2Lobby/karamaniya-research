"""Wave A W4: the referee (karamaniya/referee.py), its scripted stand-in, and its replay.

The referee decides what an approved open act achieves. It is machinery, not a seat: it is called with
phase "referee" and member "referee", so backends/replay.py keys its calls like a delegate's (month, phase,
member). This module tests the promp, the answer contract, the validation (every effect through
effects.validate, the cost against the act's funding, the word limits, the forbidden areas), the one
re-ask and the second-invalid failure, the logging shape, the success draw on its own stream, the cabinet
variant's channels and half caps, and a recorded referee answer replaying through ReplayBackend.

No model is called here; the scripted backend and a small stub answer from fixed data.

    python -m unittest tests.test_open_w4_referee
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import effects, errors, referee  # noqa: E402
from karamaniya.backends.base import Backend, CallResult  # noqa: E402
from karamaniya.backends.replay import ReplayBackend  # noqa: E402
from karamaniya.backends.scripted import ScriptedBackend  # noqa: E402
from karamaniya.world import new_world, rng_for  # noqa: E402


def world(seed: int = 11):
    return new_world(seed)


def act(text: str = "Repair the road from Port Aster to the Kessel Valley.", office: str = "treasury",
        budget: dict | None = None, funding: str | None = None) -> dict:
    return {"text": text, "office": office, "budget": budget, "funding": funding}


def budget_act(**over) -> dict:
    return act(budget={"amount": 5.0, "months": 6}, funding="reserves", **over)


def ruling(**over) -> dict:
    data = {
        "feasible": True,
        "reason": "The office has the staff and the budget to carry this out.",
        "category": "spending",
        "cost": {"one_off": 0, "monthly": 1.0, "months": 3},
        "success": "medium",
        "public": True,
        "effects": [{"channel": "approval", "target": "aster", "value": .01, "months": 3}],
        "public_report": "The government repaired the port road this month.",
    }
    data.update(over)
    return data


def refusal(**over) -> dict:
    data = ruling(feasible=False, reason="The office cannot do this with the means it has.",
                  cost={"one_off": 0, "monthly": 0, "months": 0}, effects=[], public_report="")
    data.update(over)
    return data


def codes(problems: list) -> set:
    return {p["code"] for p in problems}


def words(problems: list) -> str:
    return " ".join(p["problem"] for p in problems)


class StubBackend(Backend):
    """A backend that answers from a fixed list (the last answer repeats). No format retry: every complete()
    is exactly one call, so the referee's own re-ask is the only second call."""

    provider = "stub"

    def __init__(self, answers: list):
        super().__init__({})
        self.answers = list(answers)
        self.calls = []

    def call(self, system: str, user: str, schema: dict, context: dict) -> CallResult:
        self.calls.append({"system": system, "user": user, "schema": schema, "context": dict(context)})
        data = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(data, CallResult):
            return data
        raw = json.dumps(data, ensure_ascii=False) if data is not None else ""
        return CallResult(data=data, raw=raw, served_model="stub")

    def complete(self, system: str, user: str, schema: dict, context: dict | None = None) -> CallResult:
        return self.call(system, user, schema, context or {})


class SchemaTests(unittest.TestCase):
    def test_the_answer_contract_is_closed_and_lists_the_enums(self):
        schema = referee.answer_schema()
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertEqual(set(schema["properties"]["category"]["enum"]), set(referee.CATEGORIES))
        self.assertEqual(set(schema["properties"]["success"]["enum"]), set(referee.SUCCESS_LEVELS))
        item = schema["properties"]["effects"]["items"]
        self.assertIs(item["additionalProperties"], False)
        self.assertEqual(set(item["required"]), {"channel", "target", "value", "months"})
        self.assertEqual(set(item["properties"]["channel"]["enum"]), set(effects.CHANNELS))
        self.assertEqual(schema["properties"]["cost"]["required"], ["one_off", "monthly", "months"])

    def test_the_cabinet_schema_offers_only_the_channels_it_may_reach(self):
        item = referee.answer_schema(cabinet=True)["properties"]["effects"]["items"]
        self.assertEqual(set(item["properties"]["channel"]["enum"]), set(referee.CABINET_CHANNELS))


class PromptTests(unittest.TestCase):
    def test_the_delegate_prompt_states_every_channel_and_its_limits(self):
        text = referee.system_prompt()
        for channel, spec in effects.CHANNELS.items():
            with self.subTest(channel=channel):
                self.assertIn(channel, text)
                self.assertIn(f"{spec['cap']:g}", text)
        self.assertIn("24 months", text)
        for level in referee.SUCCESS_LEVELS:
            self.assertIn(level, text)
        for topic in ("election", "constitution", "war or peace"):
            self.assertIn(topic, text)
        self.assertIn("simulated country", text)
        self.assertIn("Month 36", text)

    def test_the_prompt_carries_no_error_codes_or_engine_words(self):
        text = referee.system_prompt()
        self.assertNotIn("REFEREE_", text)
        self.assertNotIn("EFFECT_", text)
        for word in ("schema", "engine", "simulation"):
            self.assertNotIn(word, text.lower())

    def test_the_cabinet_prompt_lists_only_the_channels_a_cabinet_may_reach(self):
        text = referee.system_prompt(cabinet=True)
        for channel in referee.CABINET_CHANNELS:
            self.assertIn(channel, text)
        for channel in set(effects.CHANNELS) - set(referee.CABINET_CHANNELS):
            self.assertNotIn(channel, text)
        self.assertIn("0.015", text)
        self.assertIn("0.004", text)
        for forbidden in ("war", "invasion", "blockade", "ultimatum", "propaganda"):
            self.assertIn(forbidden, text)

    def test_the_user_prompt_carries_the_act_office_budget_funding_and_state(self):
        w = world()
        text = referee.user_prompt(w, budget_act(), precedents=[])
        for part in ("Repair the road from Port Aster to the Kessel Valley.", "Treasury",
                     "5", "6", "reserves", "approval", "Month 1"):
            self.assertIn(part, text)

    def test_the_user_prompt_includes_the_named_region_and_identity_figures(self):
        w = world()
        text = referee.user_prompt(
            w, act(text="Reassure the imperial families of Kessel Valley and the vell minority."),
            precedents=[])
        self.assertIn("kessel", text.lower())
        self.assertIn("ident:vell", text)
        self.assertIn("ident:imperial", text)

    def test_up_to_five_precedents_are_chosen_by_similarity(self):
        w = world()
        for month, text in enumerate([
                "Repair the port road in Aster with local contractors.",
                "Repair the port road in Lissen.",
                "Fund a school in the highlands.",
                "Repair the port road in Aster again.",
                "Open a clinic in Kessel Valley.",
                "Repair the port road in Aster and Kessel.",
                "Repair the port road in Dorran."]):
            w.month = month
            referee.remember_ruling(w, act(text=text), ruling())
        similar = referee.similar_rulings(w, "Repair the port road in Aster once more.")
        self.assertEqual(len(similar), 5)
        self.assertIn("port road", similar[0]["text"])
        self.assertTrue(all("road" in item["text"] for item in similar))
        self.assertNotIn("Fund a school in the highlands.", [item["text"] for item in similar])

    def test_no_precedent_block_is_added_when_no_earlier_act_shares_a_word(self):
        w = world()
        referee.remember_ruling(w, act(text="Repair the port road."), ruling())
        self.assertEqual(referee.similar_rulings(w, "Purchase weather forecasting equipment."), [])
        self.assertNotIn("EARLIER RULINGS", referee.user_prompt(w, act(text="Purchase weather forecasting equipment.")))


class ValidationTests(unittest.TestCase):
    def check(self, data, act_=None, cabinet=False, actor=None):
        return referee.validate(world(), data, act_ or budget_act(), cabinet=cabinet, actor=actor)

    def test_a_valid_ruling_is_canonicalised(self):
        clean, problems = self.check(ruling())
        self.assertEqual(problems, [])
        self.assertTrue(clean["feasible"])
        self.assertEqual(clean["effects"][0]["channel"], "approval")
        self.assertEqual(clean["effects"][0]["months"], 3)
        self.assertEqual(clean["cost"], {"one_off": 0.0, "monthly": 1.0, "months": 3})

    def test_a_ruling_s_effects_are_ready_for_the_bus(self):
        # the bus's schedule() passes a society entry's reason to public_mood.react; the smoke script found
        # that a canonical effect without one raised KeyError.
        w = world()
        clean, problems = self.check(ruling())
        self.assertEqual(problems, [])
        stored = effects.schedule(w, clean["effects"],
                                  {"kind": "open_act", "actor": "A", "motion": "M-1", "month": w.month})
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["kind"], "approval")
        self.assertTrue(stored[0]["bus"])
        self.assertIn("reason", clean["effects"][0])

    def test_an_unknown_channel_is_refused_in_words(self):
        clean, problems = self.check(ruling(effects=[
            {"channel": "public_joy", "target": "*", "value": .01, "months": 1}]))
        self.assertIsNone(clean)
        self.assertIn("EFFECT_UNKNOWN_CHANNEL", codes(problems))
        self.assertIn("public_joy", words(problems))

    def test_an_effect_over_its_cap_is_refused_in_words(self):
        clean, problems = self.check(ruling(effects=[
            {"channel": "approval", "target": "*", "value": .05, "months": 1}]))
        self.assertIsNone(clean)
        self.assertIn("EFFECT_OVER_CAP", codes(problems))
        self.assertIn("0.03", words(problems))

    def test_two_effects_over_the_month_cap_are_refused(self):
        clean, problems = self.check(ruling(effects=[
            {"channel": "grievance", "target": "kessel", "value": .02, "months": 1},
            {"channel": "grievance", "target": "kessel", "value": .02, "months": 1}]))
        self.assertIsNone(clean)
        self.assertIn("EFFECT_MONTH_CAP", codes(problems))

    def test_a_cost_over_the_monthly_budget_is_refused(self):
        clean, problems = self.check(ruling(cost={"one_off": 0, "monthly": 6.0, "months": 3}))
        self.assertIsNone(clean)
        self.assertIn("REFEREE_OVER_BUDGET", codes(problems))
        self.assertIn("5", words(problems))

    def test_a_cost_over_the_total_budget_envelope_is_refused(self):
        clean, problems = self.check(ruling(cost={"one_off": 10.0, "monthly": 4.0, "months": 6}))
        self.assertIsNone(clean)
        self.assertIn("REFEREE_OVER_BUDGET", codes(problems))

    def test_a_cost_longer_than_the_budget_is_refused(self):
        clean, problems = self.check(ruling(cost={"one_off": 0, "monthly": 1.0, "months": 7}))
        self.assertIsNone(clean)
        self.assertIn("REFEREE_OVER_BUDGET", codes(problems))

    def test_a_cost_with_no_budget_is_refused(self):
        clean, problems = self.check(ruling(), act_=act())
        self.assertIsNone(clean)
        self.assertIn("REFEREE_OVER_BUDGET", codes(problems))

    def test_a_negative_or_garbled_cost_is_refused(self):
        for cost in ({"one_off": -1, "monthly": 0, "months": 0},
                     {"one_off": 0, "monthly": "a lot", "months": 1},
                     {"one_off": 0, "monthly": 1, "months": 1.5}):
            with self.subTest(cost=cost):
                clean, problems = self.check(ruling(cost=cost))
                self.assertIsNone(clean)
                self.assertIn("REFEREE_BAD_COST", codes(problems))

    def test_a_reason_or_public_report_over_forty_words_is_refused(self):
        long_reason = " ".join(["word"] * 41)
        clean, problems = self.check(ruling(reason=long_reason))
        self.assertIsNone(clean)
        self.assertIn("REFEREE_TOO_LONG", codes(problems))
        clean, problems = self.check(ruling(public_report=long_reason))
        self.assertIsNone(clean)
        self.assertIn("REFEREE_TOO_LONG", codes(problems))

    def test_a_malformed_answer_is_refused(self):
        for data in (None, [], {"feasible": "yes"}, ruling(category="miracle"),
                     ruling(success="certain"), ruling(public="yes"),
                     ruling(effects="none"), ruling(reason=""), ruling(public_report="")):
            with self.subTest(data=data):
                clean, problems = self.check(data)
                self.assertIsNone(clean)
                self.assertIn("REFEREE_BAD_ANSWER", codes(problems))

    def test_a_refusal_with_effects_or_cost_is_refused(self):
        clean, problems = self.check(refusal(effects=[
            {"channel": "approval", "target": "*", "value": .01, "months": 1}]))
        self.assertIsNone(clean)
        self.assertIn("REFEREE_BAD_ANSWER", codes(problems))
        clean, problems = self.check(refusal(cost={"one_off": 1, "monthly": 0, "months": 0}))
        self.assertIsNone(clean)
        self.assertIn("REFEREE_BAD_ANSWER", codes(problems))

    def test_a_valid_refusal_passes(self):
        clean, problems = self.check(refusal())
        self.assertEqual(problems, [])
        self.assertFalse(clean["feasible"])
        self.assertEqual(clean["effects"], [])

    def test_an_act_about_an_election_constitution_or_war_cannot_be_made_feasible(self):
        cases = [
            ("Schedule the election for Month 20.", "election"),
            ("Amend the constitution to extend the assembly's term.", "constitution"),
            ("Declare war on Veleria at dawn.", "war or peace"),
            ("Sign a peace treaty with the Union.", "war or peace"),
        ]
        for text, topic in cases:
            with self.subTest(text=text):
                w = world()
                clean, problems = referee.validate(w, ruling(), act(text=text))
                self.assertIsNone(clean)
                self.assertIn("REFEREE_FORBIDDEN_ACT", codes(problems))
                self.assertIn(topic, words(problems))
                self.assertIn("council", words(problems))
                # The same act, refused by the referee, is a valid ruling.
                clean, problems = referee.validate(w, refusal(), act(text=text))
                self.assertEqual(problems, [])
                self.assertFalse(clean["feasible"])

    def test_every_problem_code_is_registered_and_the_sentences_are_free_of_codes(self):
        cases = [
            ruling(effects=[{"channel": "public_joy", "target": "*", "value": .01, "months": 1}]),
            ruling(effects=[{"channel": "approval", "target": "*", "value": .05, "months": 1}]),
            ruling(cost={"one_off": 0, "monthly": 6, "months": 3}),
            ruling(cost={"one_off": -1, "monthly": 0, "months": 0}),
            ruling(reason=" ".join(["word"] * 41)),
            ruling(category="miracle"),
            refusal(effects=[{"channel": "approval", "target": "*", "value": .01, "months": 1}]),
        ]
        for data in cases:
            with self.subTest(data=data):
                _clean, problems = self.check(data)
                self.assertTrue(problems)
                for problem in problems:
                    self.assertTrue(errors.is_registered(problem["code"]), problem["code"])
                    self.assertNotIn(problem["code"], problem["problem"])


class AskTests(unittest.TestCase):
    def test_the_scripted_referee_rules_deterministically(self):
        a = referee.Referee({"provider": "scripted"})
        b = referee.Referee({"provider": "scripted"})
        first = a.ask(world(4), budget_act())
        second = b.ask(world(4), budget_act())
        self.assertTrue(first.ok)
        self.assertEqual(first.ruling, second.ruling)
        self.assertEqual(first.ruling["success"], "medium")

    def test_the_scripted_referee_follows_its_keyword_table(self):
        rule = referee.Referee({"provider": "scripted"})

        def channel(text):
            result = rule.ask(world(), budget_act(text=text))
            self.assertTrue(result.ok)
            return result.ruling["effects"][0]["channel"]

        self.assertEqual(channel("Buy grain for the cities."), "grievance")
        self.assertEqual(channel("Open a clinic in Kessel."), "approval")
        self.assertEqual(channel("Repair the road from Port Aster to the Kessel Valley."), "logistics")
        roads = rule.ask(world(), budget_act()).ruling
        self.assertAlmostEqual(roads["effects"][0]["value"], referee.SCRIPTED_EFFECT)

    def test_a_valid_ruling_is_remembered_for_consistency(self):
        w = world()
        result = referee.Referee({"provider": "scripted"}).ask(w, budget_act())
        self.assertTrue(result.ok)
        remembered = w.institutions.get("referee_precedents") or []
        self.assertEqual(len(remembered), 1)
        self.assertEqual(remembered[0]["text"], budget_act()["text"])
        self.assertTrue(remembered[0]["feasible"])

    def test_an_invalid_ruling_is_reasked_once_with_the_problems_in_words(self):
        bad = ruling(effects=[{"channel": "approval", "target": "*", "value": .05, "months": 1}])
        backend = StubBackend([bad, ruling()])
        result = referee.Referee(backend=backend).ask(world(), budget_act())
        self.assertTrue(result.ok)
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(result.attempts, 2)
        self.assertIn("at most 0.03", backend.calls[1]["user"])
        self.assertNotIn("EFFECT_OVER_CAP", backend.calls[1]["user"])

    def test_a_second_invalid_ruling_fails_the_act_as_referee_invalid(self):
        w = world()
        bad = ruling(effects=[{"channel": "approval", "target": "*", "value": .05, "months": 1}])
        backend = StubBackend([bad, bad])
        result = referee.Referee(backend=backend).ask(w, budget_act())
        self.assertFalse(result.ok)
        self.assertTrue(result.failed)
        self.assertEqual(result.reason, referee.FAILURE_REASON)
        self.assertIn("at most 0.03", result.detail)
        self.assertEqual(len(backend.calls), 2)
        self.assertIn("REFEREE_INVALID", {e["code"] for e in w.audit_errors})
        # A failed act is not a precedent.
        self.assertFalse(w.institutions.get("referee_precedents"))

    def test_an_unreadable_answer_twice_fails_the_act(self):
        w = world()
        backend = StubBackend([None, None])
        result = referee.Referee(backend=backend).ask(w, budget_act())
        self.assertTrue(result.failed)
        self.assertIn("REFEREE_INVALID", {e["code"] for e in w.audit_errors})

    def test_a_quota_answer_pauses_instead_of_failing_the_act(self):
        w = world()
        backend = StubBackend([CallResult(quota=True, error="usage limit: plan exhausted")])
        result = referee.Referee(backend=backend).ask(w, budget_act())
        self.assertFalse(result.ok)
        self.assertTrue(result.paused)
        self.assertFalse(result.failed)
        self.assertEqual(len(backend.calls), 1)
        self.assertNotIn("REFEREE_INVALID", {e["code"] for e in w.audit_errors})

    def test_an_unreachable_seat_is_unavailable_not_a_failed_act(self):
        w = world()
        backend = StubBackend([CallResult(error="gave up after 5 attempts: timeout")])
        result = referee.Referee(backend=backend).ask(w, budget_act())
        self.assertTrue(result.unavailable)
        self.assertFalse(result.failed)
        self.assertNotIn("REFEREE_INVALID", {e["code"] for e in w.audit_errors})

    def test_the_referee_makes_no_success_draw(self):
        backend = ScriptedBackend({"provider": "scripted"})
        with mock.patch("karamaniya.referee.rng_for", side_effect=AssertionError("a draw was made")):
            self.assertTrue(referee.Referee(backend=backend).ask(world(), budget_act()).ok)


class LogRecordTests(unittest.TestCase):
    def test_the_log_record_is_a_call_with_phase_and_member_referee(self):
        w = world()
        backend = StubBackend([ruling()])
        result = referee.Referee(backend=backend, label="referee-model").ask(w, budget_act())
        records = result.log_records(w, call_ids=["0.7"])
        call, prompt = records[0]["call"], records[0]["prompt"]
        self.assertEqual(call["type"], "call")
        self.assertEqual(call["month"], w.month)
        self.assertEqual(call["phase"], "referee")
        self.assertEqual(call["member"], "referee")
        self.assertEqual(call["seat"], "referee-model")
        self.assertEqual(call["raw"], json.dumps(ruling(), ensure_ascii=False))
        self.assertEqual(call["call_id"], "0.7")
        self.assertEqual(prompt["phase"], "referee")
        self.assertEqual(prompt["member"], "referee")
        self.assertEqual(prompt["call_id"], "0.7")
        self.assertEqual(prompt["prompt"], backend.calls[0]["user"])

    def test_a_seat_like_temperature_reaches_the_backend_and_the_log(self):
        w = world()
        backend = StubBackend([ruling()])
        result = referee.Referee({"temperature": 0}, backend=backend).ask(w, budget_act())
        self.assertEqual(backend.calls[0]["context"]["temperature"], 0.0)
        self.assertEqual(result.log_records(w)[0]["call"]["temperature"], 0.0)

    def test_the_reask_is_a_second_call_record_on_the_same_key(self):
        w = world()
        bad = ruling(effects=[{"channel": "approval", "target": "*", "value": .05, "months": 1}])
        backend = StubBackend([bad, ruling()])
        result = referee.Referee(backend=backend).ask(w, budget_act())
        records = result.log_records(w)
        self.assertEqual(len(records), 2)
        self.assertEqual([(r["call"]["month"], r["call"]["phase"], r["call"]["member"]) for r in records],
                         [(w.month, "referee", "referee")] * 2)
        self.assertIn("COULD NOT BE USED", records[1]["prompt"]["prompt"])


class ReplayTests(unittest.TestCase):
    def test_a_recorded_referee_answer_replays_under_the_referee_key(self):
        w = world()
        bad = ruling(effects=[{"channel": "approval", "target": "*", "value": .05, "months": 1}])
        good = ruling(cost={"one_off": 0, "monthly": 1, "months": 3})
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                for data in (bad, good):
                    f.write(json.dumps({"type": "call", "month": w.month, "phase": "referee",
                                        "member": "referee", "raw": json.dumps(data)}) + "\n")
            backend = ReplayBackend({"provider": "replay", "replay_of": "openai", "replay_log": path})
            result = referee.Referee(backend=backend).ask(w, budget_act())
        self.assertTrue(result.ok)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.ruling["effects"][0]["value"], .01)
        for answer in result.answers:
            self.assertEqual(answer.context["member"], "referee")
            self.assertEqual(answer.context["phase"], "referee")


class DrawTests(unittest.TestCase):
    def test_the_draw_is_one_stream_per_month_and_is_deterministic(self):
        w = world(7)
        first = referee.draw_success(w, "low", 0)
        self.assertEqual(first, referee.draw_success(world(7), "low", 0))
        rolls = [referee.draw_success(w, "low", index)[1] for index in range(5)]
        self.assertGreaterEqual(len(set(rolls)), 4)
        # The i-th act's roll is the (i+1)-th draw on rng_for(seed, month, "open_act").
        rng = rng_for(w.seed, w.month, "open_act")
        self.assertEqual(rolls, [round(rng.random(), 6) for _ in range(5)])

    def test_the_odds_are_the_documented_assumption(self):
        w = world(3)
        for level, odd in referee.SUCCESS_ODDS.items():
            wins = 0
            total = 200
            for month in range(total):
                w.month = month
                wins += referee.draw_success(w, level, 0)[0]
            self.assertAlmostEqual(wins / total, odd, delta=.12)
        w.month = 0

    def test_outcome_without_an_index_takes_successive_draws_and_a_replay_repeats_them(self):
        w = world(3)
        data = ruling()
        rolls = [referee.outcome(w, data)["roll"] for _ in range(3)]
        self.assertEqual(rolls, [referee.draw_success(w, "medium", index)[1] for index in range(3)])
        self.assertEqual(len(set(rolls)), 3)
        replay = world(3)
        self.assertEqual([referee.outcome(replay, data)["roll"] for _ in range(3)], rolls)

    def test_the_referee_instance_exposes_the_draw_and_the_outcome(self):
        w = world(3)
        rule = referee.Referee({"provider": "scripted"})
        self.assertEqual(rule.draw_success(w, "high", 0), referee.draw_success(w, "high", 0))
        data = ruling()
        self.assertEqual(rule.outcome(w, data, 0), referee.outcome(w, data, 0))

    def test_a_failed_act_says_so_in_its_report(self):
        w = world(3)
        data = ruling(public_report="The government opened the new clinic in Kessel.")
        found_failure = found_success = False
        for month in range(60):
            w.month = month
            outcome = referee.outcome(w, data, 0)
            if outcome["worked"]:
                found_success = True
                self.assertEqual(outcome["report"], data["public_report"])
            else:
                found_failure = True
                self.assertEqual(outcome["report"], referee.FAILED_REPORT)
                self.assertLess(referee.SUCCESS_ODDS[data["success"]], 1.0)
        self.assertTrue(found_success and found_failure)


class CabinetTests(unittest.TestCase):
    CAB = {"text": "Quietly fund friendly newspapers in the Vell Highlands.", "office": "head",
           "target": "highlands", "budget": None, "funding": None, "actor": "veleria"}

    def check(self, data, act_=None, actor="veleria"):
        return referee.validate(world(), data, act_ or self.CAB, cabinet=True, actor=actor)

    def cab_ruling(self, effects, cost=None):
        return ruling(effects=effects, cost=cost or {"one_off": .001, "monthly": 0, "months": 0})

    def test_the_cabinet_reaches_its_channels_at_half_the_society_cap(self):
        effects_ = [{"channel": "grievance", "target": "ident:vell", "value": .015, "months": 6},
                    {"channel": "approval", "target": "highlands", "value": -.015, "months": 3}]
        clean, problems = self.check(self.cab_ruling(effects_))
        self.assertEqual(problems, [])
        self.assertEqual([e["channel"] for e in clean["effects"]], ["grievance", "approval"])

    def test_an_effect_over_the_half_cap_is_refused(self):
        clean, problems = self.check(self.cab_ruling([
            {"channel": "grievance", "target": "ident:vell", "value": .016, "months": 1}]))
        self.assertIsNone(clean)
        self.assertIn("EFFECT_OVER_CAP", codes(problems))
        self.assertIn("0.015", words(problems))

    def test_two_cabinet_effects_summing_over_the_half_cap_are_refused(self):
        clean, problems = self.check(self.cab_ruling([
            {"channel": "approval", "target": "kessel", "value": .01, "months": 1},
            {"channel": "approval", "target": "kessel", "value": .01, "months": 1}]))
        self.assertIsNone(clean)
        self.assertIn("EFFECT_MONTH_CAP", codes(problems))

    def test_a_cabinet_cannot_reach_the_whole_country_or_a_class(self):
        for target in ("*", "class:farmers"):
            with self.subTest(target=target):
                clean, problems = self.check(self.cab_ruling([
                    {"channel": "grievance", "target": target, "value": .01, "months": 1}]))
                self.assertIsNone(clean)
                self.assertIn("REFEREE_CHANNEL_NOT_ALLOWED", codes(problems))

    def test_a_cabinet_cannot_reach_the_domestic_only_channels(self):
        for channel in ("damage", "logistics", "admin_capacity", "corruption", "income",
                        "hunger", "league_trust", "morale", "repression", "indep"):
            with self.subTest(channel=channel):
                target = {"morale": "army", "corruption": "treasury", "relations": "veleria",
                          "league_trust": "league", "admin_capacity": "*", "damage": "kessel",
                          "logistics": "kessel", "income": "kessel", "hunger": "kessel",
                          "repression": "kessel", "indep": "kessel"}[channel]
                clean, problems = self.check(self.cab_ruling([
                    {"channel": channel, "target": target, "value": .005, "months": 1}]))
                self.assertIsNone(clean)
                self.assertIn("REFEREE_CHANNEL_NOT_ALLOWED", codes(problems))

    def test_relations_are_the_acting_cabinets_own_and_confidence_is_available(self):
        clean, problems = self.check(self.cab_ruling([
            {"channel": "relations", "target": "veleria", "value": .01, "months": 3},
            {"channel": "confidence", "target": "*", "value": .005, "months": 2}]))
        self.assertEqual(problems, [])
        clean, problems = self.check(self.cab_ruling([
            {"channel": "relations", "target": "dorsania", "value": .01, "months": 1}]))
        self.assertIsNone(clean)
        self.assertIn("REFEREE_CHANNEL_NOT_ALLOWED", codes(problems))

    def test_the_cabinet_cost_fits_its_budget_path(self):
        clean, problems = self.check(self.cab_ruling([], cost={"one_off": .004, "monthly": 0, "months": 0}))
        self.assertEqual(problems, [])
        clean, problems = self.check(self.cab_ruling([], cost={"one_off": .005, "monthly": 0, "months": 0}))
        self.assertIsNone(clean)
        self.assertIn("REFEREE_OVER_BUDGET", codes(problems))
        clean, problems = self.check(self.cab_ruling([], cost={"one_off": 0, "monthly": .003, "months": 2}))
        self.assertIsNone(clean)
        self.assertIn("REFEREE_OVER_BUDGET", codes(problems))

    def test_a_cabinet_cannot_do_war_invasion_blockade_ultimatum_or_propaganda(self):
        for text, topic in (("Impose a naval blockade on Port Aster.", "war or peace"),
                            ("Invade the Dorran March.", "war or peace"),
                            ("Issue an ultimatum demanding Kessel Valley.", "war or peace"),
                            ("Run a propaganda campaign in the capital.", "propaganda")):
            with self.subTest(text=text):
                clean, problems = referee.validate(world(), ruling(), dict(self.CAB, text=text),
                                                   cabinet=True, actor="veleria")
                self.assertIsNone(clean)
                self.assertIn("REFEREE_FORBIDDEN_ACT", codes(problems))
                self.assertIn(topic, words(problems))
                clean, problems = referee.validate(world(), refusal(), dict(self.CAB, text=text),
                                                   cabinet=True, actor="veleria")
                self.assertEqual(problems, [])

    def test_the_cabinet_true_state_names_the_actor_and_the_target_region(self):
        text = referee.user_prompt(world(), self.CAB, cabinet=True, actor="veleria", precedents=[])
        for part in ("Veleria", "highlands", "approval", "hostility", "KARAMANIYA"):
            self.assertIn(part, text)

    def test_the_scripted_referee_falls_back_to_an_allowed_channel_for_a_cabinet(self):
        # A road act maps to logistics, which a cabinet cannot reach; the stand-in uses approval in a region.
        cab = dict(self.CAB, text="Repair the road in the Vell Highlands.")
        result = referee.Referee({"provider": "scripted"}).ask(world(), cab, cabinet=True, actor="veleria")
        self.assertTrue(result.ok)
        self.assertEqual(result.ruling["effects"][0]["channel"], "approval")
        self.assertLessEqual(abs(result.ruling["effects"][0]["value"]), referee.CABINET_SOCIETY_CAP)


if __name__ == "__main__":
    unittest.main()
