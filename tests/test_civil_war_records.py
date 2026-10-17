"""Civil war (Wave C, C5): the month record, the report's measures and the sweep's band logic.

The month record is the history row's ``civil_war`` key added by ``engine.snapshot``: C2's combat
record and C3's faction record, referenced rather than copied, with C4's offers, breaches,
ceasefire state, settlement and outcome filtered to the month. It is absent entirely under the
default arm, and after a war has ended it appears only on the month the outcome was recorded.

The report is ``tools/civil_war_report.py``; the sweep is ``tools/civil_war_sweep.py``. Both are
read-only and call no model. The report tests use a synthetic pair, so every metric is checked
against numbers the test itself wrote; the sweep's band logic is checked on synthetic run folders,
so the suite does not spend minutes on 36-month scripted runs (the real sweep is the tool).

    python -m unittest tests.test_civil_war_records
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import civil_war, engine  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402
from tools import civil_war_report, civil_war_sweep  # noqa: E402


def world(seed: int = 11, option: str = "on", month: int = 1):
    w = new_world(seed, 36, civil_war_option=option)
    w.month = month
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def start(w):
    return civil_war.start(w, "failed_coup", plotters=["D"], stances={"A": "join"})


class TheMonthRecord(unittest.TestCase):
    def test_the_off_arm_puts_no_key_on_the_row(self):
        w = world(option="off")
        # A state loaded from an on run's checkpoint must be ignored by an off run (C3's rule).
        w.civil_war = {"since": 0, "cause": "failed_coup", "factions": {}, "contested": []}
        engine.begin_month(w)
        engine.step(w)
        self.assertNotIn("civil_war", w.history[-1])

    def test_an_on_run_before_any_war_puts_no_key_on_the_row(self):
        w = world(option="on")
        engine.begin_month(w)
        engine.step(w)
        self.assertNotIn("civil_war", w.history[-1])

    def test_a_running_war_records_the_state_and_references_the_combat(self):
        w = world()
        state = start(w)
        engine.begin_month(w)
        engine.step(w)
        record = w.history[-1]["civil_war"]
        self.assertEqual(record["month"], 1)
        self.assertEqual(record["since"], 1)
        self.assertEqual(record["cause"], "failed_coup")
        self.assertIs(record["combat"], state["last_combat"])
        self.assertEqual(record["combat"]["month"], 1)
        self.assertIn("losses", record["combat"])
        self.assertIn("fronts", record["combat"])
        self.assertEqual(record["offers"], [])
        self.assertEqual(record["breaches"], [])
        self.assertIsNone(record["settlement"])
        self.assertIsNone(record["war_outcome"])
        self.assertIsNone(record["ceasefire_state"])

    def test_the_c3_faction_record_is_enriched_in_place(self):
        w = world()
        state = start(w)
        faction = {"month": 1, "leader": "D", "spoke": ["D"], "answer": {"statement": "We stand."},
                   "orders": {"north": "defend"}, "problems": [], "refused": []}
        state["last_faction"] = faction
        engine.begin_month(w)
        engine.step(w)
        record = w.history[-1]["civil_war"]
        self.assertIs(record, faction)
        # C3's own keys are untouched; the war's month data sits beside them.
        self.assertEqual(record["leader"], "D")
        self.assertEqual(record["orders"], {"north": "defend"})
        self.assertIs(record["combat"], state["last_combat"])

    def test_offers_breaches_and_the_ceasefire_filter_to_the_month(self):
        w = world()
        state = start(w)
        state["offers"] = [
            {"id": 1, "kind": "settlement", "month": 1, "status": "pending", "responses": []},
            {"id": 2, "kind": "settlement", "month": 0, "status": "expired", "responses": []},
        ]
        state["breaches"] = [{"side": "rebels", "month": 1, "reason": "attack"},
                             {"side": "government", "month": 0, "reason": "attack"}]
        state["ceasefire"] = {"active": True, "broken": False, "accepted_month": 1,
                              "offers": [{"side": "rebels", "month": 1, "status": "accepted"},
                                         {"side": "rebels", "month": 0, "status": "pending"}]}
        state["settlement"] = {"month": 1, "terms": {"amnesty": True}}
        engine.begin_month(w)
        engine.step(w)
        record = w.history[-1]["civil_war"]
        self.assertEqual([offer["id"] for offer in record["offers"]], [1])
        self.assertEqual([breach["side"] for breach in record["breaches"]], ["rebels"])
        self.assertEqual(record["settlement"], {"month": 1, "terms": {"amnesty": True}})
        self.assertEqual(record["ceasefire_state"]["offers"],
                         [{"side": "rebels", "month": 1, "status": "accepted"}])
        self.assertTrue(record["ceasefire_state"]["active"])

    def test_the_outcome_month_carries_the_outcome_and_a_later_month_does_not(self):
        w = world(month=3)
        w.civil_war = {"since": 2, "cause": "failed_coup", "factions": {}, "contested": [],
                       "forces": {}, "offers": [], "breaches": [],
                       "outcome": {"type": "settled", "month": 3, "text": "Settled."},
                       "last_combat": {"month": 3, "fronts": {}, "losses": {}}}
        engine.begin_month(w)
        engine.step(w)
        record = w.history[-1]["civil_war"]
        self.assertEqual(record["war_outcome"]["type"], "settled")
        self.assertEqual(record["month"], 3)
        # The next month: the war is over and its outcome month has passed, so the row is engine
        # 29's again and carries no civil_war key.
        engine.begin_month(w)
        engine.step(w)
        self.assertNotIn("civil_war", w.history[-1])


# ---- the report on a synthetic pair ---------------------------------------------------------

def _row(month, approval, unrest, fear, food):
    return {"month": month, "approval": approval, "unrest": unrest, "fear": fear,
            "food_ratio": food, "offices": {"head": "A", "army": "D", "interior": "C", "navy": "E",
                                            "treasury": "B"}}


def _war_record(month, soldiers, civilians, offers=(), breaches=(), spokes=()):
    return {"month": month, "since": 2, "cause": "failed_coup",
            "combat": {"month": month,
                       "fronts": {"kessel": {"damage": 0.03}, "dorran": {"damage": 0.02}},
                       "losses": {"government": soldiers[0], "rebels": soldiers[1],
                                  "civilians": civilians},
                       "losses_equivalent": {"government": soldiers[0], "rebels": soldiers[1]},
                       "refugees": 100.0,
                       "control_changes": [{"region": "kessel", "from": "karamaniya",
                                            "to": "rebels", "refugees": 100}],
                       "defections": {"army": {"before": {"government": 1.0, "rebels": 0.0,
                                                          "neutral": 0.0},
                                               "after": {"government": 0.9, "rebels": 0.1,
                                                         "neutral": 0.0}}}},
            "offers": list(offers), "breaches": list(breaches),
            "ceasefire_state": None, "settlement": None, "war_outcome": None,
            "leader": "D", "spoke": list(spokes), "orders": {"north": "attack"},
            "government_reply": {"accept": False} if offers else None}


def _write_run(root, name, *, seed=1, option="on", source=None, twin=None, history=None,
               state=None, outcome=None, counters=None):
    folder = Path(root) / name
    RunStore(folder).save_config({
        "run": {"seed": seed, "civil_war": option, **({"twin": twin} if twin else {})},
        "seats": [{"label": "s", "provider": "scripted", "persona": "hawk"}],
        "source": source or f"cw-sweep:{option}:{option}",
    })
    world_dict = {"history": history or [], "civil_war": state, "outcome": outcome or {},
                  "counters": counters or {}, "const": {"offices": {}}}
    (folder / "checkpoint.json").write_text(
        json.dumps({"world": world_dict, "council": {}, "meta": {}}), encoding="utf-8")
    (folder / "log.jsonl").write_text("", encoding="utf-8")


class TheReportMeasures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cw-report-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _pair(self):
        twin_history = [_row(m, 0.50, 0.20, 0.10, 1.00) for m in range(4)]
        war_history = [_row(0, 0.50, 0.20, 0.10, 1.00), _row(1, 0.50, 0.20, 0.10, 1.00),
                       _row(2, 0.40, 0.25, 0.15, 0.95), _row(3, 0.35, 0.30, 0.20, 0.90)]
        record_two = _war_record(2, (100, 80), 10,
                                 offers=[{"id": 1, "month": 2, "status": "refused",
                                          "responses": [{"side": "government", "accept": False}]}],
                                 breaches=[{"side": "rebels", "month": 2, "reason": "attack"}],
                                 spokes=["D", "A"])
        record_three = _war_record(3, (50, 40), 5)
        war_history[2]["civil_war"] = record_two
        war_history[3]["civil_war"] = record_three
        war_state = {
            "since": 2, "cause": "failed_coup",
            "factions": {"government": {"members": ["A", "B", "C", "E"], "leader": "A",
                                        "forces": {"army": {"holder": "D", "share": 0.8},
                                                   "interior": {"holder": "C", "share": 0.7}}},
                         "rebels": {"members": ["D"], "leader": "D",
                                    "forces": {"army": {"holder": "D", "share": 0.8}}}},
            "offers": [{"id": 1, "month": 2, "status": "refused", "from": "rebels",
                        "terms": {"amnesty": True}, "responses": [{"side": "government",
                                                                   "accept": False}]}],
            "breaches": [{"side": "rebels", "month": 2, "reason": "attack"}],
            "ceasefire": {"active": False, "broken": True, "offers": []},
            "settlement": None,
            "outcome": {"type": "settled", "month": 3, "text": "Settled."},
        }
        _write_run(self.tmp, "war", seed=1, option="on", source="cw-sweep:plotter:on",
                   twin="twin", history=war_history, state=war_state, outcome={"type": "survived"},
                   counters={"civil_war_soldiers_killed": 45.0, "civil_war_civilians_killed": 4.5})
        _write_run(self.tmp, "twin", seed=1, option="off", source="cw-sweep:plotter:off",
                   history=twin_history)
        return os.path.join(self.tmp, "war"), os.path.join(self.tmp, "twin")

    def test_the_war_run_metrics(self):
        war_path, _ = self._pair()
        measure = civil_war_report.war_measure(civil_war_report.Run(war_path))
        self.assertTrue(measure["started"])
        self.assertEqual(measure["since"], 2)
        self.assertEqual(measure["duration"], 2)
        self.assertEqual(measure["end"], "settlement")
        self.assertEqual(measure["soldiers_lost"], {"government": 150.0, "rebels": 120.0,
                                                    "civilians": 15.0})
        self.assertEqual(measure["refugees"], 200.0)
        self.assertAlmostEqual(measure["damage"], 0.10)
        self.assertEqual(measure["offers"]["total"], 1)
        self.assertEqual(measure["government_replies"]["refused"], 1)
        self.assertEqual(measure["breaches"]["total"], 1)
        self.assertEqual(measure["factions"]["rebel_offices"], {"army": "D"})
        self.assertEqual(measure["factions"]["negotiated_by"], ["A", "D"])
        self.assertEqual(measure["defections"]["army"]["rebels"], 0.2)
        self.assertEqual(measure["killed_counters"]["civil_war_soldiers_killed"], 45.0)
        self.assertEqual(len(measure["control_changes"]), 2)

    def test_the_twin_difference_in_differences(self):
        war_path, twin_path = self._pair()
        pair = civil_war_report.pair_measure(war_path, twin_path)
        self.assertEqual(pair["start"], 2)
        self.assertTrue(pair["twin_identical_before"])
        rows = {row["month"]: row for row in pair["did"]["months"]}
        self.assertEqual(rows[2]["approval"]["diff"], -0.10)
        self.assertEqual(rows[2]["approval"]["did"], -0.10)
        self.assertEqual(rows[3]["approval"]["diff"], -0.15)
        self.assertEqual(rows[3]["approval"]["did"], -0.15)
        self.assertEqual(rows[2]["unrest"]["did"], 0.05)
        self.assertEqual(rows[3]["food_ratio"]["did"], -0.10)
        self.assertEqual(pair["did"]["base_difference"]["approval"], 0.0)

    def test_a_non_twin_is_refused(self):
        war_path, twin_path = self._pair()
        twin = civil_war_report.Run(twin_path)
        twin.history[0]["approval"] = 0.99
        war = civil_war_report.Run(war_path)
        self.assertTrue(civil_war_report.twin_differences(war, twin, 2))
        # pair_measure reads the folder, so a mismatch has to be written back to be refused there.
        twin_folder = Path(twin_path) / "checkpoint.json"
        data = json.loads(twin_folder.read_text(encoding="utf-8"))
        data["world"]["history"][0]["approval"] = 0.99
        twin_folder.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(civil_war_report.ReportError):
            civil_war_report.pair_measure(war_path, twin_path)

    def test_the_arm_summary_counts_on_runs_not_twins(self):
        war_path, twin_path = self._pair()
        runs = civil_war_report.discover([self.tmp])
        by_arm = {}
        for run in runs:
            by_arm.setdefault(run.arm, []).append(civil_war_report.war_measure(run))
        summary = civil_war_report.arm_measure(by_arm["plotter"])
        self.assertEqual(summary["runs"], 1)
        self.assertEqual(summary["twins"], 1)
        self.assertEqual(summary["started"], 1)
        self.assertEqual(summary["started_share"], 1.0)

    def test_the_report_writes_text_and_json(self):
        war_path, twin_path = self._pair()
        report = civil_war_report.analyse([self.tmp], [(war_path, twin_path)])
        out = Path(self.tmp) / "out"
        out.mkdir()
        (out / "civil_war_report.json").write_text(json.dumps(report), encoding="utf-8")
        civil_war_report.write_markdown(report, out / "civil_war_report.md")
        text = (out / "civil_war_report.md").read_text(encoding="utf-8")
        self.assertIn("Civil-war report", text)
        self.assertIn("soldiers gov / rebels", text)
        self.assertIn("difference in differences", text.lower())
        self.assertEqual(report["arms"]["plotter"]["started"], 1)


class TheSweepChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cw-sweep-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, seed, arm, option, war):
        w = new_world(seed, 36, civil_war_option=option)
        w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D",
                                "navy": "E"})
        if war:
            civil_war.start(w, "failed_coup", plotters=["D"], stances={"A": "join"})
        name = f"seed{seed}-{arm}-{option}"
        folder = Path(self.tmp) / name
        RunStore(folder).save_config({"run": {"seed": seed, "civil_war": option},
                                      "seats": [{"label": "s", "provider": "scripted",
                                                 "persona": "hawk"}],
                                      "source": f"cw-sweep:{arm}:{option}"})
        RunStore(folder).save_checkpoint(w, {}, {})

    def test_quiet_arms_are_zero_and_the_band_is_read_from_the_run_folders(self):
        arms = ("passive", "scripted", "dove", "plotter")
        for seed in (1, 2):
            for arm in ("passive", "scripted", "dove"):
                self._run(seed, arm, "on", war=False)
                self._run(seed, arm, "off", war=False)
        # Two wars in six runs: 33%, inside the agreed 10-40% band.
        for seed in range(1, 7):
            self._run(seed, "plotter", "on", war=seed in (4, 6))
            self._run(seed, "plotter", "off", war=False)
        data = civil_war_sweep.summarise(Path(self.tmp), list(range(1, 7)), arms)
        self.assertTrue(data["checks"]["quiet_zero"])
        self.assertTrue(data["checks"]["hawk_band"])
        self.assertEqual(data["per_arm"]["plotter"]["started"], 2)
        self.assertEqual(data["per_arm"]["plotter"]["started_share"], round(2 / 6, 4))
        self.assertEqual(data["per_arm"]["passive"]["started"], 0)

    def test_the_band_check_fails_when_no_hawk_run_starts_a_war(self):
        arms = ("plotter",)
        for seed in range(1, 7):
            self._run(seed, "plotter", "on", war=False)
        data = civil_war_sweep.summarise(Path(self.tmp), list(range(1, 7)), arms)
        self.assertFalse(data["checks"]["hawk_band"])

    def test_every_arm_is_a_council_of_stand_ins(self):
        for arm in civil_war_sweep.ARMS:
            cfg = civil_war_sweep.config_for(arm, 1, 36, "on", None)
            self.assertEqual({seat["provider"] for seat in cfg["seats"]}, {"scripted"})
            self.assertEqual(cfg["run"]["civil_war"], "on")
        plotter = civil_war_sweep.config_for("plotter", 1, 36, "on", None)
        self.assertEqual(plotter["seats"][0]["persona"], "hawk")
        self.assertEqual(plotter["seats"][0]["formation_office"], "army")


if __name__ == "__main__":
    unittest.main()
