"""Wave A W8: the neighbours' open acts end to end (plan 4.4).

Under `harness = "open"` only, Veleria and Dorsania may put one `open_act` among their four monthly acts.
The reader (foreign._read_act/_read_cabinet_open_act) checks its text and target and refuses what belongs
to another kind of act; the council asks W4's referee after both cabinets answer, in the fixed order
veleria then dorsania; a valid ruling draws once on the shared "open_act" stream, its total cost is charged
once through the cabinet's own budget path (foreign._spend), and its effects are scheduled through the
effect bus with source kind "cabinet_open_act". A public act is reported to the delegates; a covert act is
applied and recorded and can be exposed on the Interior's surveillance and capacity, drawn on the separate
"covert_exposure" stream.

No model is called here: the scripted referee, the scripted cabinets and a small stub answer from fixed
data.

    python -m unittest tests.test_open_w8_cabinets
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import (briefing, cabinet_acts, effects, foreign, foreign_force,  # noqa: E402
                        open_acts, referee)
from karamaniya.backends.base import Backend, CallResult  # noqa: E402
from karamaniya.council import RunPaused  # noqa: E402
from karamaniya.world import new_world, rng_for  # noqa: E402


def world(seed: int = 11, harness: str = "open") -> object:
    w = new_world(seed)
    w.harness = harness
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def cabinet_answer(*actions, **over) -> dict:
    data = {"public_statement": "", "strategic_assessment": "", "strategy": "hold the line",
            "union_position": None, "diplomatic_messages": [], "belief_updates": [],
            "decision_factors": [], "actions": list(actions)}
    data.update(over)
    return data


def open_act(text: str = "Fund friendly newspapers in the Vell Highlands.", target: str = "highlands",
             **over) -> dict:
    data = {"type": "open_act", "text": text, "target": target}
    data.update(over)
    return data


def read(actor: str, *actions, harness: str = "open"):
    return foreign.normalize_cabinet_output(actor, cabinet_answer(*actions), harness=harness)


def ruling(**over) -> dict:
    data = {
        "feasible": True,
        "reason": "The cabinet has the means to carry this out.",
        "category": "communication",
        "cost": {"one_off": .002, "monthly": 0, "months": 0},
        "success": "medium",
        "public": True,
        "effects": [{"channel": "confidence", "target": "*", "value": .005, "months": 2},
                    {"channel": "approval", "target": "highlands", "value": .01, "months": 2}],
        "public_report": "The government of Veleria announced a programme of friendly newspapers.",
    }
    data.update(over)
    return data


def refusal(**over) -> dict:
    data = ruling(feasible=False, reason="The cabinet cannot do this with the means it has.",
                  cost={"one_off": 0, "monthly": 0, "months": 0}, effects=[], public=False,
                  public_report="")
    data.update(over)
    return data


def covert(**over) -> dict:
    return ruling(public=False, public_report="The cabinet's measure went ahead quietly.",
                  effects=[{"channel": "confidence", "target": "*", "value": .005, "months": 2}], **over)


class StubBackend(Backend):
    """Answers from a fixed list (the last answer repeats); every complete() is one call."""

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


class FakeStore:
    def __init__(self):
        self.logs = []
        self.prompts = []

    def log(self, record: dict) -> None:
        self.logs.append(record)

    def log_prompt(self, record: dict) -> None:
        self.prompts.append(record)


def referee_for(answers: list) -> referee.Referee:
    return referee.Referee(backend=StubBackend(answers))


def month_where(w, worked: bool, level: str = "medium", index: int = 0) -> int:
    """A month whose draw on the open-act stream gives `worked` against `level`."""
    start = w.month
    try:
        for month in range(0, 500):
            w.month = month
            if referee.draw_success(w, level, index)[0] == worked:
                return month
    finally:
        w.month = start
    raise AssertionError("no month found")


def process(w, decisions, answers=None, *, zeroed=False, store=None, next_call_id=None,
            referee_obj=None):
    settings = {"harness": "open", "referee_effects": "zeroed" if zeroed else "applied"}
    return cabinet_acts.process(
        w, decisions, settings=settings,
        referee=referee_obj if referee_obj is not None else referee_for(answers),
        store=store, next_call_id=next_call_id, names=None)


def notes_next_month(w, actor: str = "veleria") -> list:
    """What the cabinet is shown the month after the acts were taken (foreign_force.cabinet_view)."""
    w.month += 1
    try:
        return foreign_force.cabinet_view(w, actor)["your_acts_refused_last_month"]
    finally:
        w.month -= 1


class ReadingTests(unittest.TestCase):
    """The reader: one open act among the four, its text, its target, and what it may not be."""

    def test_the_open_act_is_read_with_its_text_and_target(self):
        out, problems = read("veleria", open_act())
        self.assertEqual(problems, [])
        self.assertEqual(out["actions"], [{"type": "open_act", "text": open_act()["text"],
                                           "target": "highlands"}])
        self.assertEqual(out["act_notes"], [])

    def test_a_region_named_in_words_is_read_as_its_id(self):
        out, problems = read("veleria", open_act(target="Kessel Valley"))
        self.assertTrue(any("was read as kessel" in problem for problem in problems), problems)
        self.assertEqual(out["actions"][0]["target"], "kessel")
        # A plain reading is not sent back as a refusal.
        self.assertEqual(out["act_notes"], [])

    def test_karamaniya_and_the_cabinets_own_country_are_targets(self):
        for target in ("karamaniya", "veleria"):
            with self.subTest(target=target):
                out, problems = read("veleria", open_act(target=target))
                self.assertEqual(problems, [])
                self.assertEqual(out["actions"][0]["target"], target)

    def test_the_other_country_is_not_a_target(self):
        out, problems = read("veleria", open_act(target="dorsania"))
        self.assertEqual(out["actions"], [])
        self.assertTrue(any("target" in problem for problem in problems))
        self.assertEqual(out["act_notes"][0]["code"], "OPEN_ACT_BAD_TARGET")

    def test_a_missing_or_unknown_target_is_refused(self):
        for target in (None, "the moon"):
            with self.subTest(target=target):
                act = open_act()
                if target is None:
                    act.pop("target")
                else:
                    act["target"] = target
                out, problems = read("veleria", act)
                self.assertEqual(out["actions"], [])
                self.assertTrue(any("target" in problem for problem in problems))

    def test_a_text_over_sixty_words_is_refused(self):
        out, problems = read("veleria", open_act(text="word " * 61))
        self.assertEqual(out["actions"], [])
        self.assertTrue(any("60 words" in problem for problem in problems))
        self.assertEqual(out["act_notes"][0]["code"], "OPEN_ACT_TOO_LONG")

    def test_a_missing_text_is_refused(self):
        act = open_act()
        act.pop("text")
        out, problems = read("veleria", act)
        self.assertEqual(out["actions"], [])
        self.assertTrue(any("text" in problem for problem in problems))

    def test_an_unknown_field_is_refused_in_words(self):
        out, problems = read("veleria", open_act(magnitude=.5))
        self.assertEqual(out["actions"], [])
        self.assertTrue(any("magnitude" in problem for problem in problems))
        self.assertEqual(out["act_notes"][0]["code"], "UNKNOWN_FIELD")

    def test_the_open_act_counts_within_the_four_act_cap(self):
        acts = [{"type": "offer_talks", "magnitude": .5},
                {"type": "public_statement", "magnitude": .5},
                {"type": "intelligence_collection", "magnitude": .5},
                open_act()]
        out, problems = read("veleria", *acts)
        self.assertEqual([a["type"] for a in out["actions"]],
                         ["offer_talks", "public_statement", "intelligence_collection", "open_act"])
        self.assertEqual(problems, [])

    def test_a_fifth_act_is_not_read_whether_or_not_it_is_the_open_act(self):
        four = [{"type": "offer_talks", "magnitude": .5},
                {"type": "public_statement", "magnitude": .5},
                {"type": "intelligence_collection", "magnitude": .5},
                {"type": "propaganda", "target": "country", "message": "government_failing", "magnitude": .5}]
        out, problems = read("veleria", *(four + [open_act()]))
        self.assertEqual(len(out["actions"]), 4)
        self.assertNotIn("open_act", [a["type"] for a in out["actions"]])
        self.assertTrue(any("only the first 4" in problem for problem in problems))
        self.assertTrue(any("only the first 4" in note["reason"] for note in out["act_notes"]))

    def test_validate_action_accepts_the_kind_only_under_the_open_arm(self):
        act = {"type": "open_act", "text": "Fund friendly newspapers in the Vell Highlands.",
               "target": "highlands"}
        self.assertIsNone(foreign.validate_action("veleria", dict(act), {}, world(harness="open")))
        self.assertIn("Unsupported", foreign.validate_action("veleria", dict(act), {}, world(harness="menu")))
        self.assertIn("target", foreign.validate_action("veleria", dict(act, target="dorsania"), {},
                                                        world(harness="open")))

    def test_the_open_act_is_not_read_under_menu_or_language(self):
        for harness in ("menu", "language"):
            with self.subTest(harness=harness):
                out, problems = read("veleria", open_act(), harness=harness)
                self.assertEqual(out["actions"], [])
                self.assertIn("unsupported cabinet action", problems)


class ForbiddenActTests(unittest.TestCase):
    """Plan 4.4: never war, invasion, blockade, an ultimatum or propaganda; nor an election, the
    constitution or a change of government. The reader refuses it and tells the cabinet next month; the
    referee's own guard (W4) refuses a ruling that makes one feasible."""

    TEXTS = {
        "war or peace": "Declare war on Karamaniya and invade the northern plain.",
        "naval blockade": "Impose a naval blockade on Port Aster until it submits.",
        "ultimatum": "Issue an ultimatum demanding Kessel Valley within three months.",
        "propaganda": "Run a propaganda campaign in the capital against the government.",
        "election": "Call an election in Karamaniya and put our friends in power.",
        "constitution": "Amend the constitution to abolish the presidency.",
        "change of government": "Overthrow the Karamaniyan government and install a loyal one.",
    }

    def test_each_is_refused_by_the_reader_and_told_to_the_cabinet_next_month(self):
        for topic, text in self.TEXTS.items():
            with self.subTest(topic=topic):
                w = world()
                out, problems = read("veleria", open_act(text=text))
                self.assertEqual(out["actions"], [], topic)
                self.assertTrue(any("open act cannot" in problem for problem in problems), problems)
                self.assertEqual(out["act_notes"][0]["code"], "OPEN_ACT_FORBIDDEN")
                foreign._apply_cabinet_decisions(w, foreign.positions(w), {"veleria": out})
                told = notes_next_month(w)
                self.assertTrue(told)
                self.assertTrue(any("open act" in item["reason"].lower() for item in told), told)

    def test_the_reader_records_the_refusal_code_in_the_error_log(self):
        # cabinet_acts records the reader's codes once both cabinets have answered (the council path).
        w = world()
        out, _ = read("veleria", open_act(text=self.TEXTS["election"]))
        process(w, {"veleria": out}, answers=[ruling()])
        self.assertIn("OPEN_ACT_FORBIDDEN", {e["code"] for e in w.audit_errors})

    def test_the_referee_guard_refuses_a_feasible_ruling_for_a_forbidden_act(self):
        for text in (self.TEXTS["war or peace"], self.TEXTS["election"],
                     self.TEXTS["constitution"], self.TEXTS["propaganda"]):
            with self.subTest(text=text):
                clean, problems = referee.validate(world(), ruling(), {"text": text, "target": "karamaniya"},
                                                   cabinet=True, actor="veleria")
                self.assertIsNone(clean)
                self.assertIn("REFEREE_FORBIDDEN_ACT", {p["code"] for p in problems})

    def test_the_month_one_war_guard_still_holds_unchanged(self):
        w = world()
        # Troops already at the border, as only a test can put them before Month 1.
        w.dip.border_forces = {"veleria": {"north": 20000.0, "east": 0.0}}
        w.mil.navy.size = 3
        for action in ({"type": "invade", "front": "north", "aim": "full"}, {"type": "naval_blockade"}):
            with self.subTest(action=action["type"]):
                error = foreign.validate_action("veleria", dict(action), {"mobilized_reserve": 0}, w)
                self.assertIn("before Month 2", error)
        self.assertFalse(w.dip.war or w.dip.blockade)


class CarryOutTests(unittest.TestCase):
    def run_one(self, w, answers, *, zeroed=False, store=None, next_call_id=None, actor="veleria"):
        out, problems = read(actor, open_act())
        self.assertEqual(problems, [])
        entries = process(w, {actor: out}, answers, zeroed=zeroed, store=store,
                          next_call_id=next_call_id)
        self.assertEqual(len(entries), 1)
        return entries[0]

    def test_a_valid_ruling_is_drawn_applied_charged_reported_and_recorded(self):
        w = world()
        w.month = month_where(w, True)
        before = w.foreign["actors"]["veleria"]["domestic"]["fiscal_stress"]
        entry = self.run_one(w, [ruling()])
        self.assertFalse(entry["refused"], entry)
        self.assertTrue(entry["carried_out"])
        self.assertTrue(entry["outcome"]["worked"])
        self.assertTrue(entry["public"])
        # Charged once, the ruling's total, through the cabinet's own budget path.
        self.assertEqual(entry["cost"]["charged"], .002)
        self.assertAlmostEqual(w.foreign["actors"]["veleria"]["domestic"]["fiscal_stress"], before + .002,
                               places=6)
        self.assertEqual(w.institutions.get(open_acts.CHARGES_KEY), None)
        # Applied through the bus, with the cabinet source.
        effects.step(w)
        applied = [a for a in effects.applied(w) if a["source"].get("kind") == "cabinet_open_act"]
        self.assertTrue(applied)
        self.assertTrue(all(a["source"].get("actor") == "veleria" for a in applied))
        self.assertTrue(all(a["source"].get("month") == w.month for a in applied))
        # A public in-world event, and the month record with the cabinet fields.
        self.assertTrue(any(ev.get("kind") == "cabinet_open_act" and ev.get("public")
                            and ev.get("actor") == "veleria" for ev in w.events))
        record = open_acts.month_record(w)
        self.assertIsNotNone(record)
        self.assertEqual(record["open_acts"][0]["kind"], "cabinet_act")
        self.assertTrue(record["open_acts"][0]["cabinet"])
        self.assertEqual(record["open_acts"][0]["actor"], "veleria")
        # The delegates' briefing reports it as that power's announced act; a covert act would not be.
        text = briefing.public_v2(w, {"open_acts": [entry]})
        self.assertIn("THE NEIGHBOURS' ANNOUNCED ACTS LAST MONTH", text)
        self.assertIn("Veleria", text)
        self.assertIn(ruling()["public_report"], text)

    def test_the_cabinet_sees_its_result_next_month(self):
        w = world()
        w.month = month_where(w, True)
        self.run_one(w, [ruling()])
        told = notes_next_month(w)
        self.assertTrue(told)
        reason = told[0]["reason"]
        self.assertIn("carried out", reason)
        self.assertIn("0.002", reason)
        self.assertIn("worked", reason)
        self.assertIn("announced", reason)

    def test_the_effects_stay_within_the_cabinet_caps(self):
        w = world()
        w.month = month_where(w, True)
        # W4's validator is the cap: an effect over half the domestic cap is refused twice and the act fails.
        over = ruling(effects=[{"channel": "approval", "target": "highlands", "value": .02, "months": 1}])
        backend = StubBackend([over])
        out, _ = read("veleria", open_act())
        entries = process(w, {"veleria": out}, referee_obj=referee.Referee(backend=backend))
        entry = entries[0]
        self.assertTrue(entry["refused"])
        self.assertEqual(entry["code"], "REFEREE_INVALID")
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(w.foreign["actors"]["veleria"]["domestic"]["fiscal_stress"], .18)
        self.assertEqual(effects.state(w), [])

    def test_zeroed_still_asks_logs_draws_and_charges_but_applies_nothing(self):
        w = world()
        w.month = month_where(w, True)
        store = FakeStore()
        entry = self.run_one(w, [ruling()], zeroed=True, store=store, next_call_id=lambda: "0.1")
        self.assertTrue(entry["zeroed"])
        self.assertTrue(entry["outcome"]["worked"])
        self.assertEqual(entry["cost"]["charged"], .002)
        self.assertAlmostEqual(w.foreign["actors"]["veleria"]["domestic"]["fiscal_stress"], .182,
                               places=6)
        self.assertEqual(effects.state(w), [])
        effects.step(w)
        self.assertEqual(effects.applied(w), [])
        self.assertEqual([(c["phase"], c["member"]) for c in store.logs], [("referee", "referee")])
        self.assertFalse(any(e.get("applied") for e in entry["effects"]))
        self.assertTrue(any(e.get("channel") == "confidence" for e in entry["effects"]))

    def test_a_failed_draw_pays_the_cost_and_applies_nothing(self):
        w = world()
        w.month = month_where(w, False)
        entry = self.run_one(w, [ruling()])
        self.assertFalse(entry["outcome"]["worked"])
        self.assertEqual(entry["outcome"]["report"], referee.FAILED_REPORT)
        self.assertEqual(entry["cost"]["charged"], .002)
        self.assertAlmostEqual(w.foreign["actors"]["veleria"]["domestic"]["fiscal_stress"], .182,
                               places=6)
        self.assertEqual(effects.state(w), [])
        # A public act that failed is still announced; the report says it did not work.
        self.assertTrue(any(ev.get("kind") == "cabinet_open_act" and ev.get("public")
                            and ev.get("text") == referee.FAILED_REPORT for ev in w.events))
        self.assertIn("did not work", entry["result"])
        self.assertIn("did not work", notes_next_month(w)[0]["reason"])

    def test_a_referee_refusal_costs_nothing_and_draws_nothing(self):
        w = world()
        entry = self.run_one(w, [refusal()])
        self.assertTrue(entry["refused"])
        self.assertFalse(entry["carried_out"])
        self.assertIsNone(entry["outcome"])
        self.assertEqual(entry["cost"]["charged"], 0.0)
        self.assertEqual(w.foreign["actors"]["veleria"]["domestic"]["fiscal_stress"], .18)
        self.assertEqual(effects.state(w), [])
        self.assertIn("cannot do this", notes_next_month(w)[0]["reason"])

    def test_two_invalid_rulings_fail_the_act_as_referee_invalid(self):
        w = world()
        bad = ruling(effects=[{"channel": "approval", "target": "*", "value": .01, "months": 1}])
        backend = StubBackend([bad, bad])
        out, _ = read("veleria", open_act())
        entries = process(w, {"veleria": out}, referee_obj=referee.Referee(backend=backend))
        entry = entries[0]
        self.assertTrue(entry["refused"])
        self.assertEqual(entry["code"], "REFEREE_INVALID")
        self.assertEqual(entry["attempts"], 2)
        self.assertEqual(w.foreign["actors"]["veleria"]["domestic"]["fiscal_stress"], .18)
        self.assertIn("REFEREE_INVALID", {e["code"] for e in w.audit_errors})
        self.assertIn("could not carry it out", notes_next_month(w)[0]["reason"])

    def test_a_missing_referee_is_a_clear_failure(self):
        w = world()
        out, _ = read("veleria", open_act())
        entries = cabinet_acts.process(w, {"veleria": out}, settings={"harness": "open"}, referee=None)
        self.assertTrue(entries[0]["refused"])
        self.assertEqual(entries[0]["code"], "EXECUTION_BLOCKED")
        self.assertEqual(w.foreign["actors"]["veleria"]["domestic"]["fiscal_stress"], .18)

    def test_a_usage_limit_pauses_the_month_and_logs_the_attempt(self):
        w = world()
        store = FakeStore()
        out, _ = read("veleria", open_act())
        backend = StubBackend([CallResult(quota=True, error="usage limit: plan exhausted")])
        with self.assertRaises(RunPaused):
            process(w, {"veleria": out}, store=store, next_call_id=lambda: "0.1",
                    referee_obj=referee.Referee(backend=backend))
        self.assertEqual(len(store.logs), 1)
        self.assertEqual(len(store.prompts), 1)
        self.assertEqual(w.foreign["actors"]["veleria"]["domestic"]["fiscal_stress"], .18)
        self.assertIsNone(open_acts.month_record(w))

    def test_the_cabinet_is_not_charged_for_a_monthly_cost_only_once(self):
        # Decision (a): the ruling's one_off + monthly * months is charged once, in the ruling month, and
        # no monthly schedule is kept (the cabinet's budget path has no later-charge machinery).
        w = world()
        w.month = month_where(w, True)
        entry = self.run_one(w, [ruling(cost={"one_off": .001, "monthly": .001, "months": 3})])
        self.assertEqual(entry["cost"]["charged"], .004)
        self.assertAlmostEqual(w.foreign["actors"]["veleria"]["domestic"]["fiscal_stress"], .184,
                               places=6)
        self.assertNotIn(open_acts.CHARGES_KEY, w.institutions)


class VisibilityTests(unittest.TestCase):
    def covert_entry(self, w, chance: float, *, answers=None, decisions=None):
        with mock.patch.object(foreign, "covert_exposure_chance", return_value=chance):
            out, problems = read("veleria", open_act(text="Quietly fund friendly newspapers in the Highlands."))
            self.assertEqual(problems, [])
            return process(w, decisions if decisions is not None else {"veleria": out},
                           answers if answers is not None else [covert()])

    def test_a_covert_act_is_applied_and_not_reported(self):
        w = world()
        w.month = month_where(w, True)
        entries = self.covert_entry(w, 0.0)
        entry = entries[0]
        self.assertTrue(entry["carried_out"])
        self.assertFalse(entry["public"])
        self.assertFalse(entry["exposed"])
        self.assertTrue(entry["outcome"]["worked"])
        effects.step(w)
        self.assertTrue(any(a["source"].get("kind") == "cabinet_open_act" for a in effects.applied(w)))
        self.assertFalse(any(ev.get("kind") in ("cabinet_open_act", "scandal") and ev.get("public")
                             for ev in w.events))
        text = briefing.public_v2(w, {"open_acts": [entry]})
        self.assertNotIn("THE NEIGHBOURS' ANNOUNCED ACTS", text)
        self.assertNotIn(covert()["public_report"], text)

    def test_the_exposure_draw_is_on_its_own_stream_and_the_media_stream_does_not_move(self):
        w = world()
        w.month = month_where(w, True)
        twin = world()
        twin.month = w.month
        real = rng_for
        seen = []

        def spy(seed, month, tag):
            seen.append(tag)
            return real(seed, month, tag)

        with mock.patch.object(foreign, "rng_for", side_effect=spy):
            self.covert_entry(w, 0.0)
        self.assertIn("covert_exposure", seen)
        self.assertNotIn("media", seen)
        a = [rng_for(w.seed, w.month, "media").random() for _ in range(5)]
        b = [rng_for(twin.seed, twin.month, "media").random() for _ in range(5)]
        self.assertEqual(a, b)

    def test_one_draw_per_covert_act_in_a_month(self):
        w = world()
        w.month = month_where(w, True)
        out_v, _ = read("veleria", open_act(text="Quietly fund newspapers in the Highlands."))
        out_d, _ = read("dorsania", open_act(text="Quietly fund newspapers in the marshes."))
        real = rng_for
        seen = []

        def spy(seed, month, tag):
            seen.append(tag)
            return real(seed, month, tag)

        with mock.patch.object(foreign, "rng_for", side_effect=spy), \
                mock.patch.object(foreign, "covert_exposure_chance", return_value=0.0):
            process(w, {"veleria": out_v, "dorsania": out_d}, [covert()])
        self.assertEqual(seen.count("covert_exposure"), 2)

    def test_the_exposure_chance_combines_the_interior_surveillance_and_capacity(self):
        w = world()
        # surveillance low, Interior capacity 1.0, focus public_order: .04 + .05.
        self.assertAlmostEqual(foreign.covert_exposure_chance(w), .09, places=6)
        w.policy.surveillance = "high"
        self.assertAlmostEqual(foreign.covert_exposure_chance(w), .25, places=6)
        w.institutions["operations"] = {"interior": {"focus": "smuggling"}}
        self.assertAlmostEqual(foreign.covert_exposure_chance(w), .29, places=6)
        w.institutions["capacity"] = {"interior": 0.5}
        self.assertAlmostEqual(foreign.covert_exposure_chance(w), .265, places=6)

    def test_an_exposed_act_becomes_public_with_an_event_and_a_relations_cost(self):
        w = world()
        w.month = month_where(w, True)
        relations = w.foreign["actors"]["veleria"]["relations"]["karamaniya"]
        trust, hostility = relations["trust"], relations["hostility"]
        entries = self.covert_entry(w, 1.0)
        entry = entries[0]
        self.assertTrue(entry["exposed"])
        exposure = next(e for e in open_acts.month_record(w)["open_acts"]
                        if e.get("kind") == "cabinet_exposure")
        self.assertTrue(exposure["public"])
        self.assertEqual(exposure["actor"], "veleria")
        event = next(ev for ev in w.events if ev.get("kind") == "scandal" and ev.get("public"))
        self.assertEqual(event.get("actor"), "veleria")
        self.assertIn("Veleria", event["text"])
        self.assertAlmostEqual(relations["trust"], trust - foreign.EXPOSURE_TRUST, places=6)
        self.assertAlmostEqual(relations["hostility"], hostility + foreign.EXPOSURE_HOSTILITY, places=6)
        told = notes_next_month(w)
        self.assertTrue(any("exposed" in item["reason"].lower() for item in told), told)
        self.assertIn("exposed", briefing.public_v2(w, {"open_acts": [exposure]}).lower())

    def test_a_live_covert_act_is_rolled_again_next_month_until_it_expires(self):
        w = world()
        w.month = month_where(w, True)
        entries = self.covert_entry(w, 0.0)
        self.assertFalse(entries[0]["exposed"])
        live = cabinet_acts.live(w)
        self.assertEqual(len(live), 1)
        # The effect runs two months, so the act is still live next month and is rolled again.
        w.month += 1
        with mock.patch.object(foreign, "covert_exposure_chance", return_value=1.0):
            exposure_entries = cabinet_acts.process(w, {}, settings={"harness": "open"})
        self.assertTrue(exposure_entries)
        self.assertEqual(exposure_entries[0]["kind"], "cabinet_exposure")
        self.assertEqual(cabinet_acts.live(w), [])
        # And with no live act, a later month draws nothing and records nothing.
        w.month += 1
        self.assertEqual(cabinet_acts.process(w, {}, settings={"harness": "open"}), [])


class OrderTests(unittest.TestCase):
    def test_cabinets_are_processed_veleria_then_dorsania_then_act_order(self):
        w = world()
        w.month = month_where(w, True)
        out_v, _ = read("veleria", open_act(text="Fund newspapers in the Highlands."),
                        open_act(text="Open a clinic in Kessel Valley.", target="kessel"))
        out_d, _ = read("dorsania", open_act(text="Fund a school in Dorran March.", target="dorran"))
        backend = StubBackend([ruling(public=False)])
        entries = process(w, {"dorsania": out_d, "veleria": out_v},
                          referee_obj=referee.Referee(backend=backend))
        self.assertEqual([e["actor"] for e in entries], ["veleria", "veleria", "dorsania"])
        self.assertEqual([e["text"] for e in entries],
                         ["Fund newspapers in the Highlands.", "Open a clinic in Kessel Valley.",
                          "Fund a school in Dorran March."])
        # The shared success stream: the three rulings took successive draws.
        self.assertEqual([e["outcome"]["roll"] for e in entries],
                         [referee.draw_success(w, "medium", i)[1] for i in range(3)])


class DefaultsTests(unittest.TestCase):
    def test_the_kind_is_not_offered_under_menu_or_language(self):
        for harness in ("menu", "language"):
            with self.subTest(harness=harness):
                kinds = foreign.cabinet_schema("veleria", harness=harness)["properties"]["actions"] \
                    ["items"]["properties"]["type"]["enum"]
                self.assertNotIn("open_act", kinds)
                self.assertNotIn("open act", foreign.cabinet_system_prompt("veleria", harness=harness).lower())
        kinds = foreign.cabinet_schema("veleria", harness="open")["properties"]["actions"] \
            ["items"]["properties"]["type"]["enum"]
        self.assertIn("open_act", kinds)

    def test_previously_valid_cabinet_answers_are_unchanged(self):
        answer = cabinet_answer(
            {"type": "offer_talks", "magnitude": .5},
            {"type": "propaganda", "target": "Kessel Valley", "message": "government_failing",
             "magnitude": .4})
        default, default_problems = foreign.normalize_cabinet_output("veleria", answer)
        for harness in ("menu", "language"):
            with self.subTest(harness=harness):
                out, problems = foreign.normalize_cabinet_output("veleria", answer, harness=harness)
                self.assertEqual(out, default)
                self.assertEqual(problems, default_problems)
        self.assertEqual(len(default["actions"]), 2)
        # A display-name target is read to its id in every arm, so the plain reading is in `problems` as it
        # is for a menu propaganda act today; that is the engine-29 behaviour the open arm must preserve.
        self.assertTrue(any("was read as kessel" in problem for problem in default_problems))

    def test_the_prompt_freeze_still_reports_prompts_unchanged(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("prompt_freeze",
                                                      os.path.join(ROOT, "tools", "prompt_freeze.py"))
        prompt_freeze = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prompt_freeze)
        with open(prompt_freeze.FIXTURE, encoding="utf-8") as f:
            recorded = json.load(f)
        now = prompt_freeze.current(recorded["months"])
        self.assertEqual(now["system_prompt_sha256"], recorded["system_prompt_sha256"])
        self.assertEqual(now["prompts"], recorded["prompts"])


class ThroughTheCouncil(unittest.TestCase):
    """The council calls the referee after both cabinets answer, before engine.step, and the run replays."""

    @classmethod
    def setUpClass(cls):
        from karamaniya.backends.scripted import ScriptedBackend
        from karamaniya.config import load_config
        from karamaniya.runner import new_run
        from karamaniya.storage import RunStore
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-w8-")
        original = ScriptedBackend._foreign

        def patched(self, ctx):
            out = original(self, ctx)
            w = ctx.get("world")
            if getattr(w, "harness", None) == "open" and getattr(w, "month", None) == 2:
                out = dict(out)
                out["actions"] = ([{"type": "open_act",
                                    "text": "Fund friendly newspapers in the Vell Highlands.",
                                    "target": "highlands"}]
                                  + list(out.get("actions") or []))[:foreign.ACTS_PER_MONTH]
            return out

        cls.patch = mock.patch.object(ScriptedBackend, "_foreign", patched)
        cls.patch.start()
        cls.config = load_config(os.path.join(ROOT, "council.scripted.toml"))
        cls.config["run"].update({"harness": "open", "referee_backend": {"provider": "scripted"},
                                  "months": 4, "seed": 1})
        cls.path = new_run(cls.config, runs_dir=cls.tmp, name="open-cabinets", quiet=True)
        cls.store = RunStore(cls.path)
        cls.months = cls.store.read_log("month")
        with open(os.path.join(cls.path, "prompts.jsonl"), encoding="utf-8") as f:
            cls.prompts = [json.loads(line) for line in f if line.strip()]

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_both_cabinets_acts_are_ruled_and_recorded(self):
        acts = [e for month in self.months for e in month.get("open_acts") or []
                if e.get("kind") == "cabinet_act"]
        self.assertEqual(sorted(e["actor"] for e in acts), ["dorsania", "veleria"])
        self.assertTrue(all(e["carried_out"] or e["refused"] for e in acts))
        row = next(r for r in self.store.load_checkpoint()[0].history if r.get("month") == 2)
        self.assertTrue(any(e.get("kind") == "cabinet_act" for e in row["open_acts"]))

    def test_the_cabinet_referee_calls_are_logged_in_order(self):
        ref = [p for p in self.prompts if p.get("phase") == "referee" and p.get("month") == 2]
        cabinets = [p["prompt"] for p in ref if "The cabinet of" in p["prompt"]]
        self.assertEqual(len(cabinets), 2)
        self.assertIn("The cabinet of Veleria acts.", cabinets[0])
        self.assertIn("The cabinet of Dorsania acts.", cabinets[1])
        self.assertTrue(all(p.get("member") == "referee" for p in ref))

    def test_the_recorded_run_replays_identically(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("replay_run", os.path.join(ROOT, "tools", "replay_run.py"))
        replay_run = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(replay_run)
        result = replay_run.replay(str(self.path))
        self.assertTrue(result["identical"], result["message"])
        self.assertEqual(result["replayed_months"], 4)


if __name__ == "__main__":
    unittest.main()
