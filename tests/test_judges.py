"""Evaluator models outside the run: the judge panel, and its scoring."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya.config import normalize_config  # noqa: E402
from karamaniya.judges import JudgePanel, score_records  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.config import load_config  # noqa: E402
from tests import stub_servers  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GOOD_REPLY = {"answers": [
    {"id": "survive_to_end", "choice": "no", "score": None, "probability": 0.2, "noul": None,
     "reason": "arrears and unrest are both climbing"},
    {"id": "how_ends", "choice": "collapse_or_force", "score": None, "probability": 0.6, "noul": None,
     "reason": "the army is unpaid"},
    {"id": "crisis_severity", "choice": "", "score": 3, "probability": None, "noul": None,
     "reason": "three fronts at once"},
    {"id": "enough_evidence", "choice": "", "score": None, "probability": 0.7, "noul": True,
     "reason": "no treasury detail in the record"},
]}


class JudgePanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.state, cls.url = stub_servers.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.state.reply = GOOD_REPLY
        self.state.requests.clear()

    def panel(self):
        return JudgePanel({"judge": True, "months": 36, "judge_every_months": 1,
                           "judge_backends": [{"provider": "openai_compat", "model": "stub-judge",
                                               "label": "Stub", "base_url": self.url + "/v1",
                                               "api_key_env": ""}]})

    def test_a_clean_answer_is_parsed_into_typed_records(self):
        panel = self.panel()
        rec = panel._ask_one(panel.judges[0], {"month": 3}, panel._asked())
        self.assertEqual(rec.get("error", ""), "")
        by_id = {a["id"]: a for a in rec["answers"]}
        self.assertEqual(by_id["survive_to_end"]["choice"], "no")
        self.assertAlmostEqual(by_id["survive_to_end"]["probability"], 0.2)
        self.assertEqual(by_id["crisis_severity"]["score"], 3)
        self.assertTrue(by_id["enough_evidence"]["noul"])
        self.assertEqual(rec["problems"], [])

    def test_a_choice_outside_the_options_is_a_recorded_problem(self):
        self.state.reply = {"answers": [
            {"id": "survive_to_end", "choice": "maybe", "score": None, "probability": 0.5,
             "noul": None, "reason": ""}]}
        panel = self.panel()
        rec = panel._ask_one(panel.judges[0], {"month": 0}, panel._asked())
        self.assertTrue(any("not one of" in p for p in rec["problems"]))
        self.assertTrue(rec.get("repaired"))          # the one repair attempt ran
        by_id = {a["id"]: a for a in rec["answers"]}
        self.assertTrue(by_id["survive_to_end"].get("missing"))

    def systemone_panel(self):
        return JudgePanel({"judge": True, "months": 36,
                           "judge_backends": [{"provider": "systemone", "model": "jev-latest",
                                               "label": "Jev", "base_url": self.url, "api_key_env": ""}]})

    def test_systemone_answers_map_to_typed_records(self):
        panel = self.systemone_panel()
        rec = panel._ask_one(panel.judges[0], {"month": 5}, panel._asked())
        self.assertEqual(rec.get("error", ""), "")
        by_id = {a["id"]: a for a in rec["answers"]}
        self.assertEqual(by_id["survive_to_end"]["choice"], "no")
        self.assertAlmostEqual(by_id["survive_to_end"]["probability"], 0.7)
        self.assertAlmostEqual(by_id["how_ends"]["probability"], 0.6)
        self.assertAlmostEqual(by_id["crisis_severity"]["score"], 2.9)   # level index on the 0-4 scale
        self.assertTrue(by_id["enough_evidence"]["noul"])
        self.assertAlmostEqual(rec["cost_usd"], 5000 / 1e6 * 0.042, places=6)
        self.assertEqual(rec["served_model"], "jev-stub-1")

    def test_a_422_from_systemone_is_a_recorded_error(self):
        self.state.systemone_status = 422
        self.state.systemone_error = "questions.0.criteria: too many levels"
        panel = self.systemone_panel()
        rec = panel._ask_one(panel.judges[0], {"month": 0}, panel._asked())
        self.assertIn("refused the request", rec.get("error", ""))
        self.state.systemone_status = 200

    def test_survey_never_raises_and_reports_an_unreachable_judge(self):
        panel = JudgePanel({"judge": True, "months": 4,
                            "judge_backends": [{"provider": "openai_compat", "model": "gone",
                                                "label": "Gone", "base_url": "http://127.0.0.1:1/v1",
                                                "api_key_env": "", "retries": 0}]})

        class W:
            history = [{"month": 0, "events": []}]
            counters = {}
            months_total = 4
            month = 1

            class const:
                offices = {}

            outcome = {}

            def active_members(self):
                return []

        records = panel.survey(W())
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].get("error"))


class JudgeScoring(unittest.TestCase):
    def test_brier_and_end_classificance(self):
        records = []
        for month, p in ((0, 0.9), (1, 0.8), (2, 0.7)):
            records.append({"type": "judge", "month": month, "label": "J", "model": "m",
                            "latency_s": 1.0, "cost_usd": 0.0,
                            "answers": [{"id": "survive_to_end", "kind": "choice", "choice": "yes",
                                         "probability": p},
                                        {"id": "how_ends", "kind": "choice", "choice": "handover_on_time",
                                         "probability": 0.5},
                                        {"id": "crisis_severity", "kind": "score", "score": 2 + month},
                                        {"id": "enough_evidence", "kind": "noul", "noul": month == 0}]})
        world = {"outcome": {"type": "no_government"}, "history": [{}] * 7, "months_total": 36}
        out = score_records(records, world)
        j = out["J"]
        self.assertEqual(j["surveys"], 3)
        self.assertAlmostEqual(j["survive_brier"], (0.81 + 0.64 + 0.49) / 3, places=4)   # the run collapsed
        self.assertEqual(j["ends_accuracy"], 0.0)          # run collapsed, judge always said handover
        self.assertEqual(j["mean_severity"], 3.0)
        self.assertAlmostEqual(j["noul_rate"], 1 / 3, places=3)
        self.assertFalse(j["outcome"]["ended_in_office"])
        # a run that reaches its planned end still governing resolves the opposite way
        survived = {"outcome": {"type": "survived"}, "history": [{}] * 36, "months_total": 36}
        out2 = score_records(records, survived)
        self.assertTrue(out2["J"]["outcome"]["ended_in_office"])
        self.assertEqual(out2["J"]["outcome"]["end_class"], "handover_on_time")
        self.assertAlmostEqual(out2["J"]["survive_brier"], (0.01 + 0.04 + 0.09) / 3, places=4)


class JudgeRunIntegration(unittest.TestCase):
    def test_a_scripted_month_records_a_judge_verdict(self):
        server, state, url = stub_servers.start()
        try:
            state.reply = GOOD_REPLY
            with tempfile.TemporaryDirectory(prefix="karamaniya-judge-") as tmp:
                base = load_config(os.path.join(HERE, "council.scripted.toml"))
                run = dict(base["run"], months=1, seed=7, survey=False, judge=True,
                           judge_backends=[{"provider": "openai_compat", "model": "stub-judge",
                                            "label": "Stub", "base_url": url + "/v1", "api_key_env": ""}])
                cfg = normalize_config({"run": run, "seat": base["seats"]}, "judge test")
                new_run(config=cfg, runs_dir=tmp, name="judge-one", quiet=True, check=False)
                log = Path(tmp) / "judge-one" / "log.jsonl"
                judge_lines = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()
                               if '"type": "judge"' in l]
                self.assertEqual(len(judge_lines), 1)
                rec = judge_lines[0]
                self.assertEqual(rec["month"], 0)
                self.assertEqual(rec["label"], "Stub")
                self.assertEqual(rec.get("error", ""), "")
                self.assertTrue(any(a.get("id") == "crisis_severity" for a in rec["answers"]))
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
