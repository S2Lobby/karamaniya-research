"""A whole run with scripted stand-ins: logs, checkpoints, resume, scorecard, report."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya.config import load_config  # noqa: E402
from karamaniya.council import Council, RunPaused  # noqa: E402
from karamaniya.world import new_world  # noqa: E402
from karamaniya.runner import _seats, new_run, resume_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "council.scripted.toml")


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_run_and_resume_give_the_same_history(self):
        full = new_run(CONFIG, runs_dir=self.tmp, name="full", months=10, quiet=True)
        # Interrupt a second run after 4 months, then resume it.
        store = RunStore(os.path.join(self.tmp, "part"))
        with open(os.path.join(full, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        store.save_config(cfg)
        world, _, _ = RunStore(full).load_checkpoint()
        from karamaniya.world import new_world
        w = new_world(cfg["run"]["seed"], 10, cfg["run"]["framing"], member_ids=list(cfg["mapping"]),
                      human_factor=cfg["run"].get("human_factor", True),
                      founding_scenario=cfg["run"].get("founding_scenario", "random"),
                      founding_severity=cfg["run"].get("founding_severity", "default"),
                      founding_problems=cfg["run"].get("founding_problems"))
        council = Council(w, _seats(cfg, cfg["mapping"]), cfg["run"], store)
        store._write_json("survey.json", council.survey())
        council.diagnose_founding()
        council.form_government()
        for _ in range(4):
            council.run_month()
        store.save_checkpoint(w, council.state(), {"stopped": "test interruption"})
        resume_run(store.path, quiet=True)
        a = RunStore(full).load_checkpoint()[0]
        b = store.load_checkpoint()[0]
        self.assertEqual(len(a.history), len(b.history))
        for ha, hb in zip(a.history, b.history):
            self.assertAlmostEqual(ha["approval"], hb["approval"], places=9)
            self.assertEqual(ha["offices"], hb["offices"])
        self.assertEqual(a.outcome, b.outcome)

    def test_logs_scorecard_and_report_exist(self):
        path = new_run(CONFIG, runs_dir=self.tmp, name="r", months=6, quiet=True)
        store = RunStore(path)
        months = store.read_log("month")
        calls = store.read_log("call")
        self.assertEqual(len(months), 6)
        self.assertGreaterEqual(len(calls), 6 * 10)
        self.assertTrue(all(c["served_model"].startswith("scripted:") for c in calls))
        first = months[0]
        formation = store.read_log("government_formation")[0]
        self.assertEqual(set(formation["offices"].values()), set("ABCDE"))
        self.assertEqual(formation["agenda_slots_used"], 0)
        self.assertTrue(any(m["selected"] for m in formation["motions"]))
        self.assertTrue(all(all(m.get("vote_reasons", {}).values()) for m in formation["motions"]))
        self.assertTrue(any(m["type"] != "assign_office" for m in first["motions"]) or
                        any(first["decisions"][m]["orders"] for m in first["decisions"]))
        self.assertTrue(any(m["type"] == "set_policy" for m in first["motions"]))
        self.assertTrue(any("inherited priority" in st["statement"] for st in first["statements"]))
        self.assertTrue(all(st["principles"] for st in first["statements"]))
        self.assertEqual(len(first["founding_diagnoses"]), 5)
        self.assertGreaterEqual(first["agenda_slots"], 2)
        self.assertEqual(set(first["pre_positions"]), set("ABCDE"))
        self.assertEqual(first["agent_architecture_version"], 2)
        self.assertTrue(all("decision_factors" in d for d in first["decisions"].values()))
        self.assertTrue(all(all(m.get("vote_reasons", {}).values()) for m in first["motions"]))
        survey = store.read_json("survey.json")
        self.assertTrue(all(entry["answers"]["principles"] for entry in survey.values()))
        with open(os.path.join(path, "scorecard.json"), encoding="utf-8") as f:
            card = json.load(f)
        self.assertEqual(set(card["members"]), set("ABCDE"))
        self.assertTrue(all(len(m["ideology_history"]) == 1 for m in card["members"].values()))
        self.assertTrue(all(m["private_disposition"] for m in card["members"].values()))
        self.assertTrue(all(m["opening_positions_recorded"] == 6 for m in card["members"].values()))
        self.assertTrue(os.path.exists(os.path.join(path, "report.html")))
        with open(os.path.join(path, "report.html"), encoding="utf-8") as f:
            report = f.read()
        self.assertIn("Private opening positions", report)
        self.assertIn("One country, several first diagnoses", report)


if __name__ == "__main__":
    unittest.main()


class CrashRecoveryLeavesNoDuplicateLogLines(unittest.TestCase):
    """A clean pause rolls the unfinished month out of the logs. A crash cannot — nothing runs —
    so the interrupted month's lines stayed and the replay appended a second copy of them, which
    double-counted calls in the audit trail. Found on a real run whose machine went down in
    Month 2. State was never corrupted (the month record is written once), only the record."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-crash-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _crashed_run(self):
        path = new_run(CONFIG, runs_dir=self.tmp, name="crash", months=6, quiet=True)
        store = RunStore(path)
        # Simulate a machine going down mid-month: lines are written, then nothing runs to take
        # them back out.
        store.log({"type": "call", "month": 1, "member": "B", "phase": "session",
                   "served_model": "half-finished-attempt"})
        store.log({"type": "dm", "month": 1, "from": "B", "to": "C", "text": "partial"})
        return path, store

    def test_a_recorded_mark_lets_a_resume_cut_the_orphaned_lines(self):
        path, store = self._crashed_run()
        checkpoint = store.read_json("checkpoint.json")
        mark = checkpoint["meta"].get("log_mark")
        self.assertIsNotNone(mark, "no log mark was recorded, so a crash cannot be recovered")
        before = store.read_log()
        self.assertTrue(any(r.get("served_model") == "half-finished-attempt" for r in before))
        store.rollback(mark)
        after = store.read_log()
        self.assertFalse(any(r.get("served_model") == "half-finished-attempt" for r in after),
                         "the interrupted month's lines survived the truncation")
        self.assertFalse(any(r.get("text") == "partial" for r in after))

    def test_the_mark_does_not_remove_finished_months(self):
        path, store = self._crashed_run()
        mark = store.read_json("checkpoint.json")["meta"]["log_mark"]
        months_before = [r for r in store.read_log("month")]
        store.rollback(mark)
        self.assertEqual([r for r in store.read_log("month")], months_before)

    def test_resuming_a_crashed_run_actually_truncates(self):
        """The wiring, not just the mechanism: resume must use the mark."""
        path, store = self._crashed_run()
        resume_run(path, quiet=True)
        remaining = store.read_log()
        self.assertFalse(any(r.get("served_model") == "half-finished-attempt" for r in remaining),
                         "resume did not cut the interrupted month's lines")

    def test_a_checkpoint_without_a_mark_is_left_alone(self):
        """Runs written before the mark existed must still resume."""
        path, store = self._crashed_run()
        checkpoint = store.read_json("checkpoint.json")
        checkpoint["meta"].pop("log_mark", None)
        store._write_json("checkpoint.json", checkpoint)
        before = len(store.read_log())
        resume_run(path, quiet=True)
        self.assertGreaterEqual(len(store.read_log()), before)


class ASeatThatCannotBeReachedDoesNotSilentlyAbstain(unittest.TestCase):
    """The engine promised no member silently abstains for a whole month, but that held only for
    usage limits. A seat whose provider returns nothing was recorded as abstaining on every motion
    and giving no orders, and the run completed looking normal. Found on a real run where one
    OpenRouter seat failed every `decision` call with a 502 while every other phase of the same
    seat succeeded, because `decision` carries the longest prompt."""

    def _council(self):
        cfg = load_config(CONFIG)
        mapping = {letter: seat["label"] for letter, seat in zip("ABCDE", cfg["seats"])}
        cfg = {**cfg, "mapping": mapping}
        tmp = tempfile.mkdtemp(prefix="karamaniya-reach-")
        w = new_world(cfg["run"]["seed"], 3, member_ids=list(mapping))
        store = RunStore(os.path.join(tmp, "r"))
        council = Council(w, _seats(cfg, mapping), cfg["run"], store)
        seat = council.seats["A"]
        self.cfg, self.w, self.store, self.council, self.seat = cfg, w, store, council, seat
        return tmp

    def _answer(self, result):
        from karamaniya.backends import CallResult
        original = self.seat.backend
        self.seat.backend = type("B", (), {"complete": lambda _s, *a, **k: result,
                                           "prompt_budget": lambda _s, n: 60000})()
        try:
            return self.council._call("A", "decision", "prompt", {}, {})
        finally:
            self.seat.backend = original

    def test_a_provider_failure_pauses_the_month(self):
        from karamaniya.backends import CallResult
        tmp = self._council()
        try:
            with self.assertRaises(RunPaused) as caught:
                self._answer(CallResult(error="gave up after 5 attempts: 502 bad gateway", attempts=5))
            self.assertIn("could not be reached", str(caught.exception))
            self.assertNotIn("usage limit", str(caught.exception),
                             "a provider failure was reported as a usage limit")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_usage_limit_still_pauses_and_says_so(self):
        from karamaniya.backends import CallResult
        tmp = self._council()
        try:
            with self.assertRaises(RunPaused) as caught:
                self._answer(CallResult(error="429 slow down", quota=True))
            self.assertIn("usage limit", str(caught.exception))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_refusal_still_counts_as_data_rather_than_pausing(self):
        """Declining is a choice worth recording, not an infrastructure fault."""
        from karamaniya.backends import CallResult
        tmp = self._council()
        try:
            result = self._answer(CallResult(refusal=True, raw="I will not", error="refused"))
            self.assertTrue(result.refusal)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_an_unreadable_answer_without_an_error_does_not_pause(self):
        """A model that answered badly is a quality problem, reported as unreadable, not a fault."""
        from karamaniya.backends import CallResult
        tmp = self._council()
        try:
            result = self._answer(CallResult(raw="not json at all"))
            self.assertIsNone(result.data)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_good_answer_is_returned(self):
        from karamaniya.backends import CallResult
        tmp = self._council()
        try:
            result = self._answer(CallResult(data={"ok": True}, raw="{}", served_model="test"))
            self.assertEqual(result.data, {"ok": True})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ThePreMonthPhasesAreProtected(unittest.TestCase):
    """The questionnaire, the five independent diagnoses and the government formation are about
    twenty model calls, and the first checkpoint used to be written AFTER all of them. A machine
    going down in that window lost the lot and left a run directory with no resume point at all.

    Observed for real: seventeen completed calls lost because a server was killed during the
    formation vote. The README promises a run keeps every finished month; that promise started
    only once Month 1 was reached."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-premonth-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _die_in(self, phase):
        """Start a run that abandons the process partway through a pre-Month-1 phase."""
        from karamaniya import runner
        original = getattr(runner, phase)

        def abandon(store, council, observer, quiet):
            raise SystemExit(1)

        setattr(runner, phase, abandon)
        try:
            new_run(CONFIG, runs_dir=self.tmp, name=f"die-{phase}", months=3, quiet=True)
        except SystemExit:
            pass
        finally:
            setattr(runner, phase, original)
        return RunStore(os.path.join(self.tmp, f"die-{phase}"))

    def test_a_death_before_the_survey_still_leaves_a_resume_point(self):
        store = self._die_in("_survey")
        self.assertTrue(store.exists("checkpoint.json"),
                        "no resume point was written before the first call")
        meta = store.read_json("checkpoint.json")["meta"]
        self.assertTrue(meta.get("survey_pending"))
        self.assertTrue(meta.get("log_mark"))

    def test_a_death_in_formation_keeps_the_survey_and_the_diagnoses(self):
        store = self._die_in("_form_government")
        meta = store.read_json("checkpoint.json")["meta"]
        self.assertFalse(meta.get("survey_pending"), "the completed questionnaire would be re-asked")
        self.assertFalse(meta.get("founding_diagnosis_pending"),
                         "the completed diagnoses would be re-run")
        self.assertTrue(meta.get("government_formation_pending"))
        self.assertTrue(store.exists("survey.json"))

    def test_the_interrupted_run_actually_resumes_and_finishes(self):
        store = self._die_in("_form_government")
        resume_run(store.path, quiet=True)
        world = store.load_checkpoint()[0]
        self.assertEqual(len(world.history), 3, "the resumed run did not finish")
        self.assertEqual(world.outcome.get("type"), "survived")

    def test_resuming_does_not_pay_for_the_survey_twice(self):
        """The whole point: work already done is not redone."""
        store = self._die_in("_form_government")
        calls_before = sum(1 for r in store.read_log("call"))
        resume_run(store.path, quiet=True)
        calls_after = [r for r in store.read_log("call")]
        survey_calls = [r for r in calls_after[calls_before:] if r.get("phase") == "survey"]
        self.assertEqual(survey_calls, [], "the questionnaire was asked a second time")
        diagnosis_calls = [r for r in calls_after[calls_before:]
                           if r.get("phase") == "founding_diagnosis"]
        self.assertEqual(diagnosis_calls, [], "the diagnoses were run a second time")

    def test_a_death_after_the_survey_keeps_it(self):
        from karamaniya import runner
        original = runner._diagnose

        def abandon(store, council, observer, quiet):
            raise SystemExit(1)

        runner._diagnose = abandon
        try:
            new_run(CONFIG, runs_dir=self.tmp, name="die-diagnose", months=3, quiet=True)
        except SystemExit:
            pass
        finally:
            runner._diagnose = original
        store = RunStore(os.path.join(self.tmp, "die-diagnose"))
        meta = store.read_json("checkpoint.json")["meta"]
        self.assertFalse(meta.get("survey_pending"))
        self.assertTrue(meta.get("founding_diagnosis_pending"))
