"""Regression tests for run checkpoints and month-zero governance state."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya.config import load_config  # noqa: E402
from karamaniya.council import RunPaused  # noqa: E402
from karamaniya.runner import _loop, new_run, resume_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "council.scripted.toml")


class GovernanceLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-lifecycle-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _world(self, months=3):
        return new_world(41, months, member_ids=list("ABCDE"), human_factor=False,
                         founding_scenario="none")

    def _end_without_report(self, store, world, council, stopped, quiet, observer):
        return store.path

    def test_cost_cap_prevents_an_extra_month_on_resume(self):
        store = RunStore(os.path.join(self.tmp, "cap"))
        world = self._world()

        class CouncilStub:
            spend = 0.25

            def state(self):
                return {"spend": self.spend}

            def run_month(self):
                raise AssertionError("the cap should stop before another month starts")

        council = CouncilStub()
        with patch("karamaniya.runner._end", side_effect=self._end_without_report):
            _loop(store, world, council, {"max_cost_usd": 0.25}, True)

        saved_world, saved_council, meta = store.load_checkpoint()
        self.assertEqual(saved_world.month, 0)
        self.assertEqual(saved_council["spend"], 0.25)
        self.assertEqual(meta["stopped"], "spending cap of $0.25 reached")

    def test_paused_month_keeps_attempted_spend_but_rewinds_partial_world(self):
        store = RunStore(os.path.join(self.tmp, "pause"))
        world = self._world()
        store.save_checkpoint(world, {"spend": 0.10, "pending_dms": []},
                              {"run_id": "pause", "stopped": "", "log_mark": store.mark()})

        class CouncilStub:
            spend = 0.10

            def __init__(self):
                self.store = store

            def state(self):
                return {"spend": self.spend, "pending_dms": []}

            def run_month(self):
                self.store.log({"type": "call", "month": 0, "cost_usd": 0.07})
                self.spend += 0.07
                world.const.provisional = False  # Simulate partial mutation before the pause.
                raise RunPaused("A", "scripted", "quota")

        council = CouncilStub()
        with patch("karamaniya.runner._end", side_effect=self._end_without_report):
            _loop(store, world, council, {"max_cost_usd": 1.0}, True)

        saved_world, saved_council, meta = store.load_checkpoint()
        self.assertEqual(saved_world.month, 0, "an incomplete month must not replace its checkpoint")
        self.assertTrue(saved_world.const.provisional, "partial world state must be discarded")
        self.assertAlmostEqual(saved_council["spend"], 0.17)
        self.assertTrue(meta["stopped"].startswith("paused in Month 1"))
        self.assertEqual(store.read_log("call"), [], "the paused month's call record should be rolled back")

    def test_resume_recovers_costs_from_an_orphaned_crashed_month_once(self):
        cfg = load_config(CONFIG)
        mapping = {letter: seat["label"] for letter, seat in zip("ABCDE", cfg["seats"])}
        cfg = {**cfg, "mapping": mapping, "run": {**cfg["run"], "months": 3}}
        store = RunStore(os.path.join(self.tmp, "crash"))
        store.save_config(cfg)
        world = self._world()
        store.save_checkpoint(world, {"spend": 0.10, "pending_dms": []},
                              {"run_id": "crash", "stopped": "", "log_mark": store.mark()})
        store.log({"type": "call", "month": 0, "cost_usd": 0.23})
        store.log({"type": "statement", "month": 0, "text": "partial"})

        observed = []

        def stop_before_month(store_arg, world_arg, council, run, quiet, observer=None,
                              stop_event=None, live_report=False):
            observed.append(council.spend)
            return store_arg.path

        with patch("karamaniya.runner._loop", side_effect=stop_before_month):
            resume_run(store.path, quiet=True, check=False)
            resume_run(store.path, quiet=True, check=False)

        self.assertEqual(observed, [0.33, 0.33], "replaying recovery must not charge the orphaned call twice")
        _, saved_council, _ = store.load_checkpoint()
        self.assertAlmostEqual(saved_council["spend"], 0.33)
        self.assertEqual(store.read_log(), [], "orphaned partial records should be truncated")

    def test_resume_checkpoints_completed_pre_month_governance_phases(self):
        from karamaniya import runner

        cfg = load_config(CONFIG)
        mapping = {letter: seat["label"] for letter, seat in zip("ABCDE", cfg["seats"])}
        cfg = {**cfg, "mapping": mapping, "run": {**cfg["run"], "months": 3}}
        store = RunStore(os.path.join(self.tmp, "pre-month"))
        store.save_config(cfg)
        world = new_world(43, 3, member_ids=list(mapping), human_factor=True,
                          founding_scenario="random")
        store.save_checkpoint(world, {"spend": 0.05, "pending_dms": []}, {
            "run_id": "pre-month", "stopped": "interrupted", "log_mark": store.mark(),
            "survey_pending": True, "founding_diagnosis_pending": True,
            "government_formation_pending": True,
        })

        def survey(_store, council, _observer, _quiet):
            member = council.w.member("A")
            member.ideology = "protect peaceful opposition"
            member.ideology_history.append({"month": 0, "text": member.ideology})
            council.spend += 0.10
            return ""

        def diagnose(_store, council, _observer, _quiet):
            council.w.founding["diagnoses"] = {"A": {"status": "submitted"}}
            council.spend += 0.20
            return ""

        def form(_store, council, _observer, _quiet):
            council.w.founding["formation"] = {"month": -1}
            council.w.const.offices = {office: "A" for office in council.w.const.offices}
            council.spend += 0.30
            return ""

        captured = []

        def stop_before_month(store_arg, _world, _council, _run, _quiet, observer=None,
                              stop_event=None, live_report=False):
            captured.append(store_arg.load_checkpoint())
            return store_arg.path

        with patch.object(runner, "_survey", side_effect=survey), \
                patch.object(runner, "_diagnose", side_effect=diagnose), \
                patch.object(runner, "_form_government", side_effect=form), \
                patch.object(runner, "_loop", side_effect=stop_before_month):
            resume_run(store.path, quiet=True, check=False)

        saved_world, saved_council, meta = captured[0]
        self.assertEqual(saved_world.member("A").ideology, "protect peaceful opposition")
        self.assertEqual(saved_world.founding["diagnoses"]["A"]["status"], "submitted")
        self.assertEqual(saved_world.founding["formation"]["month"], -1)
        self.assertEqual(set(saved_world.const.offices.values()), {"A"})
        self.assertAlmostEqual(saved_council["spend"], 0.65)
        self.assertFalse(meta["survey_pending"])
        self.assertFalse(meta["founding_diagnosis_pending"])
        self.assertFalse(meta["government_formation_pending"])
        self.assertEqual(meta["stopped"], "")

    def test_invalid_month_override_is_rejected_before_creating_a_run(self):
        with self.assertRaisesRegex(ValueError, "months must be between 1 and 120"):
            new_run(CONFIG, runs_dir=self.tmp, name="invalid-months", months=0,
                    quiet=True, check=False)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "invalid-months")))

    def test_inherited_grain_deal_covers_exactly_months_one_through_six(self):
        world = new_world(42, 3, member_ids=list("ABCDE"), founding_scenario="random")
        commitments = world.foreign["actors"]["dorsania"]["diplomacy"]["commitments"]
        grain = next(c for c in commitments if c.get("type") == "grain agreement"
                     and c.get("partner") == "karamaniya")
        self.assertEqual((grain["month"], grain["until"]), (0, 5))
        self.assertEqual(world.counters["dorsania_trade_until"], 5.0)


if __name__ == "__main__":
    unittest.main()
