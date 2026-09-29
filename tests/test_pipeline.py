"""A whole run with scripted stand-ins: logs, checkpoints, resume, scorecard, report."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya.council import Council  # noqa: E402
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
