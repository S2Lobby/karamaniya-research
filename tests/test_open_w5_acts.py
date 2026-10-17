"""Wave A W5: delegates' open acts end to end (karamaniya/open_acts.py and the council's call site).

A passed `open_act` motion is carried out only through open_acts.execute: the referee rules it (W4), the
act's success is drawn once on rng_for(seed, month, "open_act"), the ruling's cost is charged through the
same funding paths W3's policy items use, its effects go through the effect bus, and the month's record
and the next month's briefing carry what happened. `referee_effects = "zeroed"` is the ablation: the
ruling, the draw and the cost stay, only the effects are withheld.

No model is called here: the scripted referee and a small stub answer from fixed data.

    python -m unittest tests.test_open_w5_acts
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

from karamaniya import briefing, deliberation, effects, errors, open_acts, politics, referee  # noqa: E402
from karamaniya.backends.base import Backend, CallResult  # noqa: E402
from karamaniya.council import RunPaused  # noqa: E402
from karamaniya.world import new_world, rng_for  # noqa: E402


def world(seed: int = 11, harness: str = "open") -> object:
    w = new_world(seed)
    w.harness = harness
    return w


def motion(text: str = "Repair the rail bridge at Port Aster with local contractors.",
           office: str = "treasury", budget: dict | None = None, funding: str | None = None,
           proposer: str = "A", mid: str = "M-1") -> dict:
    """An open-act motion as the reader would store it (the canonical `act` is added by the reader)."""
    if budget is None:
        budget = {"amount": 4.0, "months": 3}
        funding = funding or "reserves"
    return {"id": mid, "type": "open_act", "proposer": proposer, "subject": "", "value": "",
            "text": text,
            "action": {"office": office, "budget": budget, "funding": funding}}


def ruling(**over) -> dict:
    data = {
        "feasible": True,
        "reason": "The office has the staff and the budget to carry this out.",
        "category": "spending",
        "cost": {"one_off": 0, "monthly": 1.0, "months": 3},
        "success": "medium",
        "public": True,
        "effects": [{"channel": "logistics", "target": "aster", "value": .01, "months": 2}],
        "public_report": "The government repaired the rail bridge this month.",
    }
    data.update(over)
    return data


def refusal(**over) -> dict:
    data = ruling(feasible=False, reason="The office cannot do this with the means it has.",
                  cost={"one_off": 0, "monthly": 0, "months": 0}, effects=[], public=False,
                  public_report="")
    data.update(over)
    return data


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


def run(w, mo, answers, *, zeroed=False, store=None, next_call_id=None, referee_obj=None):
    settings = {"referee_effects": "zeroed" if zeroed else "applied", "harness": "open"}
    return open_acts.execute(w, mo, settings=settings,
                             referee=referee_obj if referee_obj is not None else referee_for(answers),
                             store=store, next_call_id=next_call_id, names=None)


class ExecuteTests(unittest.TestCase):
    def test_a_valid_ruling_is_drawn_scheduled_charged_and_recorded(self):
        w = world()
        w.month = month_where(w, True)
        mo = motion()
        rec = run(w, mo, [ruling()])
        self.assertFalse(rec["refused"])
        self.assertTrue(rec["carried_out"])
        self.assertTrue(rec["outcome"]["worked"])
        self.assertEqual(rec["outcome"]["report"], ruling()["public_report"])
        self.assertEqual(rec["cost"]["charged"], 1.0)
        self.assertEqual(rec["cost"]["remaining_charges"], 2)
        self.assertAlmostEqual(w.econ.gold, 79e6, places=6)
        self.assertEqual(len(open_acts.state(w)), 1)
        before = w.region("aster").logistics
        effects.step(w)
        self.assertAlmostEqual(w.region("aster").logistics, round(before + .01, 4), places=6)
        applied = effects.applied(w)
        self.assertTrue(any(a["channel"] == "logistics" and a["source"].get("kind") == "open_act"
                            and a["source"].get("actor") == "A" and a["source"].get("motion") == "M-1"
                            for a in applied))
        # The month's own record, shared with the histories and the log.
        record = open_acts.month_record(w)
        self.assertIsNotNone(record)
        self.assertEqual(record["open_acts"][0]["motion"], "M-1")
        self.assertTrue(any(ev.get("kind") == "open_act" and ev.get("public")
                            for ev in w.events))

    def test_the_month_history_row_gains_open_acts_only_when_one_ran(self):
        from karamaniya import engine
        w = world()
        w.month = month_where(w, True)
        engine.snapshot(w)
        self.assertNotIn("open_acts", w.history[-1])
        run(w, motion(), [ruling()])
        engine.snapshot(w, refresh_last=True)
        self.assertIn("open_acts", w.history[-1])
        self.assertEqual(w.history[-1]["open_acts"][0]["motion"], "M-1")

    def test_zeroed_still_asks_draws_and_charges_but_applies_nothing(self):
        w = world()
        w.month = month_where(w, True)
        store = FakeStore()
        rec = run(w, motion(), [ruling()], zeroed=True, store=store, next_call_id=lambda: "0.1")
        self.assertFalse(rec["refused"])
        self.assertTrue(rec["outcome"]["worked"])
        self.assertTrue(rec["zeroed"])
        self.assertEqual(rec["cost"]["charged"], 1.0)
        self.assertAlmostEqual(w.econ.gold, 79e6, places=6)
        self.assertEqual(effects.state(w), [])
        effects.step(w)
        self.assertEqual(effects.applied(w), [])
        self.assertEqual([(c["phase"], c["member"]) for c in store.logs], [("referee", "referee")])
        self.assertFalse(any(e.get("applied") for e in rec["effects"]))
        self.assertTrue(any(e.get("channel") == "logistics" for e in rec["effects"]))

    def test_a_failed_draw_pays_the_cost_and_applies_nothing(self):
        w = world()
        w.month = month_where(w, False)
        rec = run(w, motion(), [ruling()])
        self.assertFalse(rec["outcome"]["worked"])
        self.assertEqual(rec["outcome"]["report"], referee.FAILED_REPORT)
        self.assertEqual(rec["cost"]["charged"], 1.0)
        self.assertAlmostEqual(w.econ.gold, 79e6, places=6)
        self.assertEqual(effects.state(w), [])
        effects.step(w)
        self.assertEqual(effects.applied(w), [])

    def test_a_referee_refusal_costs_nothing_and_draws_nothing(self):
        w = world()
        rec = run(w, motion(), [refusal()])
        self.assertTrue(rec["refused"])
        self.assertFalse(rec["carried_out"])
        self.assertIsNone(rec["outcome"])
        self.assertEqual(rec["cost"]["charged"], 0.0)
        self.assertEqual(w.econ.gold, 80e6)
        self.assertEqual(effects.state(w), [])
        note = open_acts.refusal_entry(rec)
        self.assertEqual(note["member"], "A")
        self.assertIn("cannot do this", note["explanation"])

    def test_two_invalid_rulings_fail_the_act_as_referee_invalid(self):
        w = world()
        bad = ruling(effects=[{"channel": "approval", "target": "*", "value": .05, "months": 1}])
        store = FakeStore()
        ids = iter(["0.1", "0.2"])
        rec = run(w, motion(), [bad, bad], store=store, next_call_id=lambda: next(ids))
        self.assertTrue(rec["refused"])
        self.assertEqual(rec["code"], "REFEREE_INVALID")
        self.assertIn(referee.FAILURE_REASON, rec["reason"])
        self.assertIn("at most 0.03", rec["reason"])
        self.assertEqual(rec["attempts"], 2)
        self.assertEqual(rec["cost"]["charged"], 0.0)
        self.assertEqual(w.econ.gold, 80e6)
        self.assertEqual(effects.state(w), [])
        self.assertIn("REFEREE_INVALID", {e["code"] for e in w.audit_errors})
        self.assertEqual(len(store.logs), 2)
        self.assertEqual(len(store.prompts), 2)
        for call, prompt in zip(store.logs, store.prompts):
            self.assertEqual((call["phase"], call["member"]), ("referee", "referee"))
            self.assertEqual((prompt["phase"], prompt["member"]), ("referee", "referee"))
        self.assertEqual([c.get("call_id") for c in store.logs], ["0.1", "0.2"])
        note = open_acts.refusal_entry(rec)
        self.assertIn("at most 0.03", note["explanation"])

    def test_a_usage_limit_pauses_the_month_and_logs_the_attempt(self):
        w = world()
        store = FakeStore()
        backend = StubBackend([CallResult(quota=True, error="usage limit: plan exhausted")])
        ids = iter(["0.1"])
        with self.assertRaises(RunPaused):
            run(w, motion(), [], store=store, next_call_id=lambda: next(ids),
                referee_obj=referee.Referee(backend=backend))
        self.assertEqual(len(store.logs), 1)
        self.assertEqual(len(store.prompts), 1)
        self.assertEqual(w.econ.gold, 80e6)
        self.assertIsNone(open_acts.month_record(w))

    def test_a_missing_referee_is_a_clear_failure(self):
        w = world()
        rec = open_acts.execute(w, motion(), settings={"harness": "open", "referee_effects": "applied"},
                                referee=None)
        self.assertTrue(rec["refused"])
        self.assertEqual(rec["code"], "EXECUTION_BLOCKED")
        self.assertIn("referee", rec["reason"].lower())
        self.assertEqual(w.econ.gold, 80e6)
        self.assertEqual(effects.state(w), [])

    def test_a_second_open_act_by_one_delegate_in_a_month_is_refused(self):
        w = world()
        w.month = month_where(w, True)
        backend = StubBackend([ruling()])
        rule = referee.Referee(backend=backend)
        first = open_acts.execute(w, motion(mid="M-1"), settings={"harness": "open"}, referee=rule)
        self.assertTrue(first["carried_out"])
        second = open_acts.execute(w, motion(text="Open a clinic in Kessel.", mid="M-2"),
                                   settings={"harness": "open"}, referee=rule)
        self.assertTrue(second["refused"])
        self.assertEqual(second["code"], "OPEN_ACT_LIMIT")
        self.assertEqual(len(backend.calls), 1)       # the second act never reached the referee
        self.assertEqual(second["cost"]["charged"], 0.0)

    def test_the_tabling_rule_refuses_a_second_open_act(self):
        w = world()
        first, second = motion(mid="M-1"), motion(mid="M-2", text="Open a clinic in Kessel.")
        self.assertIsNone(deliberation.check(w, first, [], "A")[0])
        rejection, _warning = deliberation.check(w, second, [first], "A")
        self.assertIsNotNone(rejection)
        self.assertEqual(rejection["reason_code"], "OPEN_ACT_LIMIT")


class StreamTests(unittest.TestCase):
    def test_the_open_act_draw_uses_its_own_stream(self):
        w = world()
        w.month = month_where(w, True)
        real = rng_for
        seen = []

        def spy(seed, month, tag):
            seen.append(tag)
            return real(seed, month, tag)

        with mock.patch("karamaniya.referee.rng_for", side_effect=spy):
            run(w, motion(), [ruling()])
        self.assertEqual(seen, ["open_act"])

    def test_a_twin_without_the_act_draws_the_same_other_streams(self):
        one, two = world(5), world(5)
        month = month_where(one, True)
        one.month = two.month = month
        run(one, motion(), [ruling()])
        for tag in ("council", "society", "plots", "foreign", "media", "forecasts"):
            with self.subTest(tag=tag):
                a = [rng_for(one.seed, month, tag).random() for _ in range(5)]
                b = [rng_for(two.seed, month, tag).random() for _ in range(5)]
                self.assertEqual(a, b)


class FundingTests(unittest.TestCase):
    def test_a_cost_running_zero_months_charges_only_the_one_off(self):
        w = world()
        w.month = month_where(w, True)
        # W4's validator refuses monthly > 0 with months 0 ("a monthly cost needs at least one month"), so
        # the end-to-end case is a one-off with no monthly; the charge rule itself is checked below.
        rec = run(w, motion(), [ruling(cost={"one_off": .002, "monthly": 0, "months": 0})])
        self.assertTrue(rec["carried_out"])
        self.assertEqual(rec["cost"]["charged"], .002)
        self.assertEqual(rec["cost"]["remaining_charges"], 0)
        self.assertAlmostEqual(w.econ.gold, 80e6 - 2_000, places=6)
        self.assertFalse(w.institutions.get(open_acts.CHARGES_KEY))
        # The rule the coordinator asked for: with months 0 there is no monthly month, whatever monthly says.
        self.assertEqual(open_acts._initial_charge({"one_off": .002, "monthly": .01, "months": 0}), .002)
        self.assertEqual(open_acts._initial_charge({"one_off": 0, "monthly": .01, "months": 3}), .01)

    def test_a_monthly_cost_charges_one_month_now_and_schedules_the_rest(self):
        w = world()
        w.month = month_where(w, True)
        rec = run(w, motion(), [ruling(cost={"one_off": 0, "monthly": 1.0, "months": 3})])
        self.assertEqual(rec["cost"]["charged"], 1.0)
        self.assertEqual(rec["cost"]["remaining_charges"], 2)
        charges = w.institutions[open_acts.CHARGES_KEY]
        self.assertEqual(len(charges), 1)
        self.assertEqual(charges[0]["months_left"], 2)
        self.assertEqual(charges[0]["monthly"], 1.0)
        self.assertAlmostEqual(w.econ.gold, 79e6, places=6)

    def test_reserves_refuse_in_words_when_short(self):
        w = world()
        w.month = month_where(w, True)
        w.econ.gold = 0.0
        rec = run(w, motion(funding="reserves"), [ruling()])
        self.assertTrue(rec["refused"])
        self.assertEqual(rec["code"], "OPEN_ACT_UNFUNDED")
        self.assertIn("reserves", rec["reason"])
        self.assertEqual(rec["cost"]["charged"], 0.0)
        self.assertEqual(effects.state(w), [])

    def test_borrowing_refuses_in_words_when_the_market_is_short(self):
        w = world()
        w.month = month_where(w, True)
        with mock.patch("karamaniya.politics.borrowing_capacity", return_value=0.0):
            rec = run(w, motion(funding="borrowing"), [ruling()])
        self.assertTrue(rec["refused"])
        self.assertEqual(rec["code"], "OPEN_ACT_UNFUNDED")
        self.assertIn("lend", rec["reason"])

    def test_a_cut_refuses_in_words_when_the_setting_has_no_room(self):
        w = world()
        w.month = month_where(w, True)
        w.policy.military = 0.005          # its lower bound: no room to cut
        rec = run(w, motion(funding="cut:military"), [ruling()])
        self.assertTrue(rec["refused"])
        self.assertEqual(rec["code"], "OPEN_ACT_UNFUNDED")
        self.assertIn("military", rec["reason"])

    def test_a_cut_funds_the_charge_and_is_restored_at_the_end(self):
        w = world()
        w.month = month_where(w, True)
        mo = motion(budget={"amount": 2.0, "months": 2}, funding="cut:welfare")
        rec = run(w, mo, [ruling(cost={"one_off": 0, "monthly": 1.0, "months": 2})])
        self.assertTrue(rec["carried_out"])
        self.assertLess(w.policy.welfare, 0.04)
        self.assertEqual(rec["cost"]["remaining_charges"], 1)
        w.month += 1
        open_acts.monthly(w)
        self.assertAlmostEqual(w.policy.welfare, 0.04, places=6)
        self.assertEqual(w.institutions.get(open_acts.CHARGES_KEY), [])

    def test_monthly_charges_are_paid_in_later_months(self):
        w = world()
        w.month = month_where(w, True)
        rec = run(w, motion(), [ruling(cost={"one_off": 0, "monthly": 1.0, "months": 3})])
        self.assertEqual(rec["cost"]["charged"], 1.0)
        self.assertAlmostEqual(w.econ.gold, 79e6, places=6)
        w.month += 1
        open_acts.monthly(w)
        self.assertAlmostEqual(w.econ.gold, 78e6, places=6)
        w.month += 1
        open_acts.monthly(w)
        self.assertAlmostEqual(w.econ.gold, 77e6, places=6)
        self.assertEqual(w.institutions[open_acts.CHARGES_KEY], [])
        w.month += 1
        open_acts.monthly(w)
        self.assertAlmostEqual(w.econ.gold, 77e6, places=6)

    def test_a_missed_later_charge_is_recorded_and_stops_the_schedule(self):
        w = world()
        w.month = month_where(w, True)
        run(w, motion(), [ruling(cost={"one_off": 0, "monthly": 1.0, "months": 3})])
        w.econ.gold = 0.0                     # the later month cannot pay
        w.month += 1
        open_acts.monthly(w)
        self.assertEqual(w.institutions[open_acts.CHARGES_KEY], [])
        record = open_acts.month_record(w)
        charge = [entry for entry in record["open_acts"] if entry.get("kind") == "charge"]
        self.assertEqual(len(charge), 1)
        self.assertEqual(charge[0]["motion"], "M-1")
        self.assertTrue(charge[0]["refused"])
        self.assertIn("reserves", charge[0]["reason"])
        self.assertIn("OPEN_ACT_UNFUNDED", {e["code"] for e in w.audit_errors})
        # It stops: the next month pays nothing and records nothing more.
        w.month += 1
        open_acts.monthly(w)
        self.assertEqual(open_acts.month_record(w), None)

    def test_nothing_is_charged_when_the_referee_refuses_or_the_ruling_is_invalid(self):
        for answers in ([refusal()],
                        [ruling(effects=[{"channel": "approval", "target": "*", "value": .05,
                                          "months": 1}])] * 2):
            with self.subTest(answers=answers):
                w = world()
                rec = run(w, motion(), answers)
                self.assertTrue(rec["refused"])
                self.assertEqual(rec["cost"]["charged"], 0.0)
                self.assertEqual(w.econ.gold, 80e6)
                self.assertEqual(w.institutions.get(open_acts.CHARGES_KEY) or [], [])


class BriefingTests(unittest.TestCase):
    def carried(self, **over):
        w = world()
        w.month = month_where(w, True)
        rec = run(w, motion(), [ruling(**over)])
        self.assertTrue(rec["carried_out"])
        return w, rec

    def test_the_briefing_reports_each_carried_out_act(self):
        w, rec = self.carried()
        text = briefing.public_v2(w, {"open_acts": [rec]})
        self.assertIn("OPEN ACTS CARRIED OUT LAST MONTH", text)
        self.assertIn(ruling()["public_report"], text)
        self.assertIn("worked", text.lower())
        self.assertIn("million crowns", text)
        self.assertIn("reserves", text)

    def test_a_quiet_act_is_reported_as_not_announced(self):
        w, rec = self.carried(public=False)
        text = briefing.public_v2(w, {"open_acts": [rec]})
        self.assertIn("not announced", text.lower())
        self.assertFalse(any(ev.get("kind") == "open_act" and ev.get("public") for ev in w.events))
        legacy = briefing.public(w, {"open_acts": [rec]})
        self.assertIn("not announced", legacy.lower())

    def test_no_open_act_section_when_none_ran(self):
        w = world()
        for text in (briefing.public_v2(w, {}), briefing.public(w, {})):
            self.assertNotIn("OPEN ACTS", text)


class ThroughTheCouncil(unittest.TestCase):
    """The council's motion loop calls open_acts.execute, records the act and logs the referee's calls."""

    @classmethod
    def setUpClass(cls):
        from karamaniya.config import load_config
        from karamaniya.runner import new_run
        from karamaniya.storage import RunStore
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-w5-")
        cfg = load_config(os.path.join(ROOT, "council.scripted.toml"))
        cfg["run"].update({"harness": "open", "referee_backend": {"provider": "scripted"}})
        # A seed whose Month 3 act draws a success, so the applied effects can be checked too.
        cls.seed = None
        for seed in range(1, 80):
            probe = new_world(seed)
            probe.month = 2
            if referee.draw_success(probe, "medium", 0)[0]:
                cls.seed = seed
                break
        assert cls.seed is not None
        cfg["run"].update({"seed": cls.seed, "months": 6})
        cls.path = new_run(cfg, runs_dir=cls.tmp, name="open-run", quiet=True)
        cls.store = RunStore(cls.path)
        cls.months = cls.store.read_log("month")
        cls.calls = cls.store.read_log("call")
        with open(os.path.join(cls.path, "prompts.jsonl"), encoding="utf-8") as f:
            cls.prompts = [json.loads(line) for line in f if line.strip()]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_scripted_delegate_tables_an_open_act_that_is_carried_out(self):
        acted = [m for month in self.months for m in month["motions"] if m["type"] == "open_act"]
        self.assertEqual(len(acted), 1)
        entry = acted[0]
        self.assertTrue(entry["passed"])
        self.assertEqual(entry["execution_status"], "EXECUTED")
        self.assertEqual(entry["open_act"]["code"], "")
        self.assertTrue(entry["open_act"]["carried_out"])
        self.assertTrue(entry["open_act"]["outcome"]["worked"])

    def test_the_act_is_in_the_month_record_and_the_history_row(self):
        month = next(m for m in self.months if any(x["type"] == "open_act" for x in m["motions"]))
        self.assertIn("open_acts", month)
        tabled = next(x for x in month["motions"] if x["type"] == "open_act")
        self.assertEqual(month["open_acts"][0]["motion"], tabled["id"])
        world, _council, _meta = self.store.load_checkpoint()
        row = next(r for r in world.history if r.get("month") == month["month"])
        self.assertIn("open_acts", row)
        self.assertEqual(row["open_acts"][0]["kind"], "act")
        applied = row.get("effects_applied") or []
        self.assertTrue(any(rec.get("source", {}).get("kind") == "open_act" for rec in applied))

    def test_the_next_month_briefing_reports_the_act(self):
        month = next(m for m in self.months if any(x["type"] == "open_act" for x in m["motions"]))
        later = [p for p in self.prompts if p.get("month") == month["month"] + 1]
        self.assertTrue(later)
        self.assertTrue(any("OPEN ACTS CARRIED OUT LAST MONTH" in (p.get("prompt") or "")
                            for p in later))
        self.assertTrue(any("The public was told:" in (p.get("prompt") or "") for p in later))

    def test_the_referee_calls_are_logged_with_phase_and_member(self):
        ref_calls = [c for c in self.calls if c.get("phase") == "referee"]
        self.assertTrue(ref_calls)
        self.assertTrue(all(c.get("member") == "referee" for c in ref_calls))
        ref_prompts = [p for p in self.prompts if p.get("phase") == "referee"]
        self.assertEqual(len(ref_prompts), len(ref_calls))
        self.assertTrue(all(p.get("member") == "referee" for p in ref_prompts))
        self.assertEqual(sum(1 for c in ref_calls if json.loads(c["raw"])), len(ref_calls))


class SixMonthReplay(unittest.TestCase):
    def test_an_open_arm_scripted_run_replays_identically(self):
        import importlib.util
        from karamaniya.config import load_config
        from karamaniya.runner import new_run
        spec = importlib.util.spec_from_file_location("replay_run", os.path.join(ROOT, "tools", "replay_run.py"))
        replay_run = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(replay_run)
        tmp = tempfile.mkdtemp(prefix="karamaniya-w5-replay-")
        try:
            cfg = load_config(os.path.join(ROOT, "council.scripted.toml"))
            cfg["run"].update({"harness": "open", "referee_backend": {"provider": "scripted"},
                               "months": 6, "seed": 1})
            path = new_run(cfg, runs_dir=tmp, name="open", quiet=True)
            result = replay_run.replay(str(path))
            self.assertTrue(result["identical"], result["message"])
            self.assertEqual(result["replayed_months"], 6)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class DefaultsUnchanged(unittest.TestCase):
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

    def test_the_open_act_section_is_absent_from_a_default_run(self):
        from karamaniya.config import load_config
        from karamaniya.runner import _seats
        from karamaniya.council import Council
        from karamaniya.storage import RunStore
        tmp = tempfile.mkdtemp(prefix="karamaniya-w5-default-")
        try:
            cfg = load_config(os.path.join(ROOT, "council.scripted.toml"))
            cfg["run"]["months"] = 1
            mapping = {letter: seat["label"] for letter, seat in zip("ABCDE", cfg["seats"])}
            cfg["mapping"] = mapping
            from karamaniya.world import new_world
            w = new_world(cfg["run"]["seed"], 1, member_ids=list(mapping))
            council = Council(w, _seats(cfg, mapping), cfg["run"], RunStore(tmp))
            self.assertNotIn("open_act", council.system)
            council.survey()
            council.diagnose_founding()
            council.form_government()
            record = council.run_month()
            self.assertNotIn("open_acts", record)
            self.assertNotIn("open_acts", w.history[-1])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
