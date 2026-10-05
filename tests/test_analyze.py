"""The run-analysis teammate must separate engine gaps from correct rejections, and flag
degenerate dynamics and impossible states. Uses a synthetic run dir so it needs no real runs."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import analyze  # noqa: E402


def _write_run(root, rid, history, log_lines):
    d = os.path.join(root, rid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "checkpoint.json"), "w", encoding="utf-8") as f:
        json.dump({"world": {"history": history, "econ": {"gold": 100.0, "arrears": 0.0}}}, f)
    with open(os.path.join(d, "log.jsonl"), "w", encoding="utf-8") as f:
        for obj in log_lines:
            f.write(json.dumps(obj) + "\n")
    return d


class AnalyzeRun(unittest.TestCase):
    def test_expected_rejections_are_classified_as_procedural(self):
        self.assertEqual(analyze._bucket("NO_EXISTING_DEAL"), "procedural")
        self.assertEqual(analyze._bucket("MOTION_NOT_HEARD"), "procedural")

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # approval drifts down every month (an attractor); democracy and army never move (pinned).
        history = [{"month": i, "approval": 0.5 - 0.03 * i, "unrest": 0.2 + 0.01 * i,
                    "democracy": 1.0, "army": 28000.0, "arrears_gdp": 0.1 + 0.02 * i,
                    "paid_share": 0.9} for i in range(8)]
        log = [
            {"type": "call", "member": "A", "refusal": False, "error": "", "format_retry": True},
            {"type": "month", "month": 0, "rejected_motions": [
                {"member": "A", "reason_code": "UNKNOWN_LEVER",
                 "motion": {"type": "set_policy", "subject": "fiscal_prudence", "value": "0.25",
                            "text": "an austerity package"}, "explanation": "unknown policy lever"},
                {"member": "B", "reason_code": "SAME_MOTION_TABLED",
                 "motion": {"type": "set_policy", "subject": "tax", "value": "0.2"},
                 "explanation": "already tabled"},
                {"member": "C", "reason_code": "MOTION_ACTION_MISMATCH_AFTER_REPAIR",
                 "motion": {"type": "diplomacy", "subject": "trade_deal", "value": "", "text": "protest"},
                 "explanation": "text and action disagree"},
            ]},
        ]
        self.run_dir = _write_run(self.tmp, "fixture-run", history, log)

    def test_separates_gaps_from_correct_rejections(self):
        r = analyze.analyze_run(self.run_dir)
        self.assertEqual(r["friction"]["gap"], 1)           # the one UNKNOWN_LEVER
        self.assertEqual(r["friction"]["procedural"], 1)    # SAME_MOTION_TABLED
        self.assertEqual(r["friction"]["guard"], 1)         # the mismatch
        self.assertEqual(r["gap_examples"][0]["code"], "UNKNOWN_LEVER")
        self.assertEqual(r["gap_examples"][0]["subject"], "fiscal_prudence")

    def test_flags_degenerate_dynamics_and_pinned_states(self):
        r = analyze.analyze_run(self.run_dir)
        drift = {d["var"]: d["drift"] for d in r["dynamics"]}
        self.assertEqual(drift.get("approval"), "down")
        self.assertEqual(drift.get("arrears_gdp"), "up")
        anomalies = " ".join(r["anomalies"])
        self.assertIn("democracy", anomalies)
        self.assertIn("army", anomalies)

    def test_flags_scorecard_stale_against_checkpoint_history(self):
        with open(os.path.join(self.run_dir, "scorecard.json"), "w", encoding="utf-8") as f:
            json.dump({"country": {"months_run": 1, "final_approval": 0.5 - 0.03}}, f)
        r = analyze.analyze_run(self.run_dir)
        anomalies = " ".join(r["anomalies"])
        self.assertIn("scorecard reports 1 months", anomalies)
        self.assertIn("scorecard final_approval", anomalies)

    def test_call_health_and_aggregate(self):
        r = analyze.analyze_run(self.run_dir)
        self.assertEqual(r["calls"]["total"], 1)
        self.assertEqual(r["calls"]["format_retries"], 1)
        agg = analyze.aggregate([r, analyze.analyze_run(self.run_dir)])
        self.assertEqual(agg["runs"], 2)
        self.assertEqual(agg["friction"]["gap"], 2)
        self.assertEqual(agg["anomalous_runs"], 2)

    def test_discover_and_report_run_without_error(self):
        dirs = analyze.discover(self.tmp)
        self.assertEqual(len(dirs), 1)
        result = analyze.analyze(self.tmp)         # must not raise; prints a report
        self.assertEqual(result["aggregate"]["runs"], 1)


if __name__ == "__main__":
    unittest.main()
