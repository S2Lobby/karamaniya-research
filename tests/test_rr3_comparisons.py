"""Regime realism RR3: the comparison councils face the run's own recorded neighbours (plan 4.5).

The four rule-played councils are unchanged. Two replayed modes run the same scripted and passive councils,
but the two neighbour cabinets answer from the finished run's log.jsonl through backends/replay.py, month by
month, so an invasion or campaign the run's own neighbours chose happens in the comparison when the
comparison world allows it. An act the comparison world refuses is recorded as skipped with its reason. The
report names the neighbours each comparison faced. A run without a replayable log still gets only the
rule-played modes.

The replayed fixture is a small scripted run with `foreign_cabinets = false`, whose log is then given two
synthetic recorded cabinet answers per month: Veleria masses 8,000 soldiers on the north border in Month 1,
tries an invasion across the east border in Month 2 (refused: no troops have stood there), and invades across
the north border in Month 3 (carried out). No real model is called.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import baseline  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.report import build_report  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")
RULE_MODES = ("scripted", "passive", "hawk", "dove")
REPLAYED_MODES = ("scripted_replayed", "passive_replayed")
# The four rule-played councils' summaries on this fixture, computed on base 49a8d5b before the replayed modes
# existed. They pin "the existing rule-played modes stay unchanged": same figures, to the last digit.
BASE_SUMMARIES = {
    "scripted": {"approval_final": 0.4596, "approval_mean": 0.4632, "army_final": 37991, "deaths": 30,
                 "democracy_final": 1.0, "democracy_min": 1.0, "food_ratio_mean": 0.9956,
                 "food_ratio_min": 0.9938, "inflation_final": -0.0382, "inflation_mean": -0.0214,
                 "inflation_peak": -0.0006, "months": 3, "months_at_war": 0, "outcome": "survived",
                 "output_final": 0.9354, "regions_lost_final": 0, "unemployment_mean": 0.0684},
    "passive": {"approval_final": 0.4631, "approval_mean": 0.4639, "army_final": 28000, "deaths": 29,
                "democracy_final": 1.0, "democracy_min": 1.0, "food_ratio_mean": 0.9957,
                "food_ratio_min": 0.9938, "inflation_final": -0.0343, "inflation_mean": -0.0206,
                "inflation_peak": -0.0001, "months": 3, "months_at_war": 0, "outcome": "survived",
                "output_final": 0.9394, "regions_lost_final": 0, "unemployment_mean": 0.0685},
    "hawk": {"approval_final": 0.462, "approval_mean": 0.4642, "army_final": 38000, "deaths": 30,
             "democracy_final": 1.0, "democracy_min": 1.0, "food_ratio_mean": 0.9941,
             "food_ratio_min": 0.9938, "inflation_final": -0.0293, "inflation_mean": -0.015,
             "inflation_peak": -0.0006, "months": 3, "months_at_war": 0, "outcome": "survived",
             "output_final": 0.9337, "regions_lost_final": 0, "unemployment_mean": 0.0686},
    "dove": {"approval_final": 0.4646, "approval_mean": 0.4651, "army_final": 28000, "deaths": 29,
             "democracy_final": 1.0, "democracy_min": 1.0, "food_ratio_mean": 0.9949,
             "food_ratio_min": 0.9938, "inflation_final": -0.0312, "inflation_mean": -0.0192,
             "inflation_peak": -0.0006, "months": 3, "months_at_war": 0, "outcome": "survived",
             "output_final": 0.9382, "regions_lost_final": 0, "unemployment_mean": 0.0686},
}


def scripted(**run):
    """The test council's run settings, with the baselines off (a baseline's own run has none)."""
    cfg = load_config(CONFIG)
    return normalize_config({"run": {**cfg["run"], "survey": False, "baseline": False, "report": False,
                                     "foreign_cabinets": False, "seed": 1, "months": 3, **run},
                             "seat": cfg["seats"]},
                           "test")


def finished(tmp, name, months=3, **run):
    return new_run(scripted(**run), runs_dir=tmp, name=name, months=months, quiet=True, check=False)


def answer(actions):
    """One recorded cabinet answer, in the shape the reader takes (foreign.normalize_cabinet_output)."""
    return {"strategic_assessment": "", "strategy": "", "union_position": "consult", "public_statement": "",
            "actions": actions, "decision_factors": []}


def foreign_record(month, actor, data):
    """A log.jsonl `foreign_call` line as council._foreign_cabinets writes it (structured_read, engine 24)."""
    return {"type": "foreign_call", "month": month, "actor": actor, "provider": "openrouter",
            "seat": "recorded-neighbours", "model": "recorded-model",
            "raw": json.dumps(data), "structured": data, "structured_read": True}


def append_log(run_dir, records):
    with open(Path(run_dir) / "log.jsonl", "a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


class TheModes(unittest.TestCase):
    def test_the_four_rule_modes_are_kept_and_two_replayed_modes_added(self):
        self.assertEqual(baseline.RULE_MODES, RULE_MODES)
        self.assertEqual(baseline.MODES, RULE_MODES + REPLAYED_MODES)

    def test_a_replayed_mode_needs_a_recorded_log_and_keeps_the_run_settings(self):
        replay = {"provider": "replay", "replay_log": "C:/runs/recorded/log.jsonl", "replay_of": "openrouter",
                  "label": "replayed neighbours from recorded"}
        run = baseline._config({"seed": 1, "human_factor": True, "foreign_cabinets": False}, 5,
                               "scripted_replayed", 3, replay=replay)["run"]
        self.assertIs(run["foreign_cabinets"], True)
        self.assertEqual(run["foreign_cabinet_backend"], replay)
        self.assertEqual(run["seed"], 1)
        with self.assertRaises(ValueError):
            baseline._config({"seed": 1}, 5, "scripted_replayed", 3)

    def test_the_rule_played_config_is_unchanged_and_gains_no_backend(self):
        run = baseline._config({"seed": 1, "human_factor": True, "foreign_cabinets": False}, 5,
                               "passive", 3)["run"]
        self.assertNotIn("foreign_cabinet_backend", run)
        self.assertIs(run["foreign_cabinets"], True)
        self.assertEqual([s["persona"] for s in baseline._config({"seed": 1}, 5, "scripted", 3)["seats"]],
                         ["democrat", "technocrat", "hawk", "loyalist", "opportunist"])
        replayed = baseline._config({"seed": 1}, 5, "scripted_replayed", 3,
                                    replay={"provider": "replay", "replay_log": "x"})["seats"]
        self.assertEqual([s["persona"] for s in replayed], ["democrat", "technocrat", "hawk", "loyalist",
                                                            "opportunist"])


class ReplayedNeighbours(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-rr3-")
        cls.run_dir = finished(cls.tmp, "recorded")
        records = []
        for month in range(3):
            if month == 0:
                actions = [{"type": "deploy_to_border", "front": "north", "troops": 8000, "magnitude": .5}]
            elif month == 1:
                # No soldiers have stood on the east border since last month: the comparison world must refuse.
                actions = [{"type": "invade", "front": "east", "aim": "limited", "magnitude": .5}]
            else:
                actions = [{"type": "invade", "front": "north", "aim": "limited", "magnitude": .5}]
            records.append(foreign_record(month, "veleria", answer(actions)))
            records.append(foreign_record(month, "dorsania", answer([])))
        append_log(cls.run_dir, records)
        cls.data = baseline.compute(cls.run_dir, force=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_replayed_modes_run_and_name_the_run_they_replay(self):
        self.assertEqual(self.data["status"], "ok", self.data)
        self.assertEqual(set(self.data["modes"]), set(baseline.MODES))
        self.assertEqual(self.data["replay"]["status"], "ok")
        for mode in REPLAYED_MODES:
            with self.subTest(mode=mode):
                self.assertEqual(self.data["modes"][mode]["status"], "ok", self.data["modes"][mode])
                self.assertEqual(self.data["modes"][mode]["neighbours"], "replayed from recorded")
        self.assertEqual(self.data["modes"]["passive"]["neighbours"], "rule-played")

    def test_the_recorded_invasion_is_carried_out_in_the_comparison(self):
        for mode in REPLAYED_MODES:
            with self.subTest(mode=mode):
                summary = self.data["modes"][mode]["summary"]
                applied = [(a["month"], a["actor"], a["action"]) for a in summary["foreign_acts_applied"]]
                self.assertIn((0, "veleria", "deploy_to_border"), applied)
                self.assertIn((2, "veleria", "invade"), applied)
                self.assertGreater(summary["months_at_war"], 0,
                                   f"the recorded invasion did not start a war: {applied}")

    def test_an_act_the_comparison_world_refuses_is_recorded_as_skipped_with_its_reason(self):
        for mode in REPLAYED_MODES:
            with self.subTest(mode=mode):
                skipped = self.data["modes"][mode]["summary"]["foreign_acts_skipped"]
                east = [s for s in skipped if (s.get("action") or {}).get("type") == "invade"
                        and (s.get("action") or {}).get("front") == "east"]
                self.assertEqual(len(east), 1, skipped)
                self.assertEqual(east[0]["actor"], "veleria")
                self.assertEqual(east[0]["month"], 1)
                self.assertIn("east border needs at least", east[0]["reason"])
                self.assertFalse([s for s in skipped if (s.get("action") or {}).get("front") == "north"],
                                 "the recorded northern invasion was refused too")

    def test_deltas_carry_each_mode_and_its_neighbours(self):
        deltas = baseline.deltas(self.data)
        self.assertEqual(set(deltas), set(baseline.MODES))
        self.assertEqual(deltas["scripted_replayed"]["neighbours"], "replayed from recorded")
        self.assertEqual(deltas["scripted"]["neighbours"], "rule-played")
        self.assertIn("months_at_war", deltas["scripted_replayed"])

    def test_the_report_names_each_comparisons_neighbours(self):
        html = build_report(RunStore(self.run_dir)).read_text(encoding="utf-8")
        for needle in ('"neighbours":"rule-played"', '"neighbours":"replayed from recorded"',
                       'scripted_replayed: "Rule-following stand-ins, replayed neighbours"',
                       "do not react to the comparison council", "refused by the comparison world"):
            with self.subTest(needle=needle):
                self.assertTrue(needle in html, needle)


class ARunWithoutAReplayableLog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-rr3-nolog-")
        cls.run_dir = finished(cls.tmp, "nolog")
        cls.data = baseline.compute(cls.run_dir, force=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_only_the_rule_played_modes_are_computed(self):
        self.assertEqual(self.data["status"], "ok")
        self.assertEqual(set(self.data["modes"]), set(RULE_MODES))
        self.assertEqual(self.data["replay"]["status"], "unavailable")

    def test_the_rule_played_summaries_are_unchanged(self):
        for mode in RULE_MODES:
            with self.subTest(mode=mode):
                self.assertEqual(self.data["modes"][mode]["summary"], BASE_SUMMARIES[mode])

    def test_an_old_log_of_placeholders_is_not_replayed(self):
        tmp = tempfile.mkdtemp(prefix="karamaniya-rr3-old-")
        try:
            old = finished(tmp, "old")
            append_log(old, [foreign_record(month, actor, answer([])) for month in range(3)
                             for actor in ("veleria", "dorsania")])
            # A log written before engine 24 keeps "(scripted)" instead of the answer.
            path = Path(old) / "log.jsonl"
            lines = path.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines):
                record = json.loads(line)
                if record.get("type") == "foreign_call":
                    record["raw"] = "(scripted)"
                    record.pop("structured", None)
                    record.pop("structured_read", None)
                    lines[i] = json.dumps(record)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            data = baseline.compute(old, force=True)
            self.assertEqual(set(data["modes"]), set(RULE_MODES))
            self.assertEqual(data["replay"]["status"], "unavailable")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
