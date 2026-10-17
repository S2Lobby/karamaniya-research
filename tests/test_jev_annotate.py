"""Tests for tools/jev_annotate.py: Jev (TypeSafe System One) as the blind second annotator.

The HTTP path runs against tests/stub_servers.py's fake TypeSafe endpoint, so the tests use no key and no network.
The expected values are worked out by hand from the codebook and the report's cost rule; the agreement arithmetic
is checked against small tables whose counts are given in the comments.

Wave 3, worker C. No real TypeSafe call is made by any test.
"""
import csv
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests import stub_servers  # noqa: E402
from tools import exit_audit as ea  # noqa: E402
from tools import jev_annotate as ja  # noqa: E402

SUP, AMB, FMT = ea.LABELS
KEY = "test-key-3f9c-never-print"


def sample_row(event_id="syn|m0|resigned|B", **fields):
    """One row of the exit audit's sample CSV, as DictReader returns it (every value a string)."""
    row = {name: "" for name in ea.CSV_FIELDS}
    row.update({
        "stratum": "exit", "event_id": event_id, "run": "syn", "month": "0", "month_label": "Month 1",
        "event_type": "resigned", "is_exit": "True", "exit_class": "member", "member": "B", "seat": "seat-b",
        "model": "model-b", "office": "treasury", "motion_id": "", "motion_type": "",
        "raw_answers": '--- B decision c1\n{"resign": true, "notes": "The arrears crisis is beyond my ministry."}',
        "parsed": json.dumps({"source": "decision", "resign": True}),
        "state_change": json.dumps({"status_after": "removed", "removed_how": "resigned"}),
        "engine_flags": "", "parser_checks": "",
        "raw_reading": json.dumps({"plain_json": True, "resign_tokens": ["true"]}),
        "annotator_1": "ambiguous", "annotator_2": "", "adjudicated": "", "notes": "",
    })
    row.update(fields)
    return row


def write_sample(path, rows, fields=None):
    fields = fields or ea.CSV_FIELDS
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class BlindStateTests(unittest.TestCase):
    def test_the_state_carries_the_raw_answers_and_the_recorded_facts(self):
        state = ja.build_state(sample_row())
        self.assertIn("The arrears crisis is beyond my ministry.", state)
        self.assertIn("Month 1", state)
        self.assertIn("resigned", state)
        self.assertIn("removed", state)

    def test_the_state_leaves_out_the_engine_reading_and_the_annotator_labels(self):
        state = ja.build_state(sample_row())
        self.assertNotIn('"source": "decision"', state)      # parsed
        self.assertNotIn("plain_json", state)                # raw_reading
        self.assertNotIn("resign_tokens", state)
        self.assertNotIn("annotator_1", state)
        self.assertNotIn('"ambiguous"', state)               # the first annotator's label

    def test_parser_checks_and_engine_flags_are_shown_because_the_codebook_reads_them(self):
        row = sample_row(parser_checks="placeholder:notes", engine_flags="refusal")
        state = ja.build_state(row)
        self.assertIn("placeholder:notes", state)
        self.assertIn("refusal", state)


class QuestionTests(unittest.TestCase):
    def test_the_exit_question_is_a_three_way_choice_with_the_codebook_rules(self):
        q = ja.exit_question()
        self.assertEqual(q["kind"], "choice")
        self.assertEqual(q["options"], list(ea.LABELS))
        self.assertEqual(set(q["criteria"]), set(ea.LABELS))
        fmt = q["criteria"]["formatting_or_parser"]
        for rule in ("F1", "F2", "F3", "F4"):
            self.assertIn(rule, fmt)
        amb = q["criteria"]["ambiguous"]
        for rule in ("A1", "A2", "A3", "A4"):
            self.assertIn(rule, amb)
        self.assertIn("raw answer", q["text"].lower())

    def test_the_detector_questions_use_the_report_s_three_labels(self):
        d1 = ja.detector_question("d1")
        self.assertEqual(d1["options"], ["TRUE_ERROR", "FALSE_POSITIVE", "UNCLEAR"])
        self.assertIn("current or past level", d1["criteria"]["TRUE_ERROR"])
        d2 = ja.detector_question("d2")
        self.assertEqual(d2["options"], ["TRUE_MISMATCH", "FALSE_POSITIVE", "UNCLEAR"])
        self.assertIn("argues against the vote", d2["criteria"]["TRUE_MISMATCH"])


class EstimateTests(unittest.TestCase):
    def test_the_estimate_is_characters_over_four_at_the_input_only_price(self):
        # 2 requests: 400-char and 800-char states, both with the same question.
        # tokens = (state + json(question)) // 4; cost = tokens / 1e6 * $0.042.
        states = ["x" * 400, "y" * 800]
        question = ja.exit_question()
        qlen = len(json.dumps(question))
        est = ja.estimate_cost(states, question)
        self.assertEqual(est["tokens_per_request"], [(400 + qlen) // 4, (800 + qlen) // 4])
        self.assertEqual(est["total_tokens"], (400 + qlen) // 4 + (800 + qlen) // 4)
        self.assertAlmostEqual(est["cost_usd"],
                               est["total_tokens"] / 1e6 * ja.PRICE_PER_MTOK, places=12)
        self.assertEqual(est["oversized"], [])

    def test_a_request_beyond_the_stated_context_is_reported_not_sent(self):
        # The contract gives 32k tokens for the state plus the single longest question.
        est = ja.estimate_cost(["x" * (ja.MAX_EST_TOKENS * 4 + 100)], ja.exit_question())
        self.assertEqual(est["oversized"], [0])
        with self.assertRaises(ja.AnnotateError):
            ja.check_sizes(est, ["row-1"])


class DryRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jev-dry-")
        self.sample = os.path.join(self.tmp, "sample.csv")
        write_sample(self.sample, [sample_row("e1"), sample_row("e2")])
        self.out = os.path.join(self.tmp, "out.csv")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dry_run_prints_the_estimate_and_sends_nothing(self):
        # An empty TYPESAFE_API_KEY would make the backend refuse; a dry run must never construct it.
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}), redirect_stdout(buf):
            code = ja.main(["sample", self.sample, "--out", self.out, "--dry-run"])
        self.assertEqual(code, 0)
        text = buf.getvalue()
        self.assertIn("Cost estimate", text)
        self.assertIn("2 rows", text)
        self.assertIn("No request was sent", text)
        self.assertIn("blind", text.lower())
        self.assertFalse(os.path.exists(self.out))


class StubSampleTests(unittest.TestCase):
    def setUp(self):
        self.server, self.state, self.url = stub_servers.start()
        self.state.systemone_reply = {"exit_label": {
            "type": "choice", "choice": SUP,
            "probabilities": {SUP: 0.7, AMB: 0.2, FMT: 0.1}, "confidence": 0.55}}
        self.tmp = tempfile.mkdtemp(prefix="jev-stub-")
        self.sample = os.path.join(self.tmp, "sample.csv")
        write_sample(self.sample, [sample_row("e1"), sample_row("e2")])
        self.out = os.path.join(self.tmp, "out.csv")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_tool(self, argv):
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": KEY}), \
                redirect_stdout(buf), redirect_stderr(buf):
            code = ja.main(argv)
        return code, buf.getvalue()

    def test_the_stub_run_writes_annotator_2_probabilities_confidence_and_model(self):
        code, text = self.run_tool(["sample", self.sample, "--out", self.out, "--base-url", self.url])
        self.assertEqual(code, 0, text)
        rows = read_csv(self.out)
        self.assertEqual([r["annotator_2"] for r in rows], [SUP, SUP])
        self.assertEqual(json.loads(rows[0]["annotator_2_probabilities"]),
                         {SUP: 0.7, AMB: 0.2, FMT: 0.1})
        self.assertAlmostEqual(float(rows[0]["annotator_2_confidence"]), 0.55)
        self.assertEqual(rows[0]["annotator_2_model"], "jev-stub-1")
        self.assertEqual(rows[0]["raw_answers"], sample_row()["raw_answers"])
        self.assertEqual(rows[0]["annotator_1"], "ambiguous")   # preserved, never sent
        self.assertNotIn(KEY, text)                             # the key is never printed
        self.assertIn("Cost estimate", text)
        self.assertIn("jev-stub-1", text)                       # the resolved model id is reported

    def test_the_request_is_blind_and_uses_the_contract_shape(self):
        code, _ = self.run_tool(["sample", self.sample, "--out", self.out, "--base-url", self.url])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.state.requests), 2)
        path, headers, body = self.state.requests[0]
        self.assertTrue(path.endswith("/v1/systemone"))
        self.assertEqual(headers.get("Authorization"), f"Bearer {KEY}")
        self.assertEqual(set(body["questions"]), {"exit_label"})
        question = body["questions"]["exit_label"]
        self.assertEqual(question["type"], "choice")
        self.assertEqual(set(question["criteria"]), set(ea.LABELS))
        self.assertNotIn('"source": "decision"', body["state"])
        self.assertNotIn("plain_json", body["state"])
        self.assertIn("The arrears crisis is beyond my ministry.", body["state"])

    def test_the_openrouter_mode_uses_the_decisions_path_and_its_key(self):
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": KEY}), \
                redirect_stdout(buf), redirect_stderr(buf):
            code = ja.main(["sample", self.sample, "--out", self.out,
                            "--base-url", self.url + "/api/alpha", "--openrouter"])
        text = buf.getvalue()
        self.assertEqual(code, 0, text)
        self.assertEqual(len(self.state.requests), 2)
        path, headers, body = self.state.requests[0]
        self.assertTrue(path.endswith("/api/alpha/decisions"), path)
        self.assertEqual(headers.get("Authorization"), f"Bearer {KEY}")
        self.assertEqual(body["model"], "typesafe/jev-latest")
        self.assertNotIn(KEY, text)
        rows = read_csv(self.out)
        self.assertEqual([row["annotator_2"] for row in rows], [SUP, SUP])
        self.assertEqual(rows[0]["annotator_2_model"], "jev-stub-1")

    def test_the_output_sheet_can_be_compared_with_exit_audit_agreement(self):
        code, _ = self.run_tool(["sample", self.sample, "--out", self.out, "--base-url", self.url])
        self.assertEqual(code, 0)
        stats = ea.agreement_report(self.sample, self.out, "annotator_1", "annotator_2")
        self.assertEqual(stats["n_pairable"], 2)
        # annotator_1 says ambiguous twice; Jev says supported twice: two disagreements, p_o = 0.
        self.assertEqual(len(stats["disagreements"]), 2)

    def test_an_answer_outside_the_codebook_is_an_error_and_no_sheet_is_written(self):
        self.state.systemone_reply = {"exit_label": {"type": "choice", "choice": "maybe",
                                                     "probabilities": {"maybe": 1.0}, "confidence": 0.9}}
        code, text = self.run_tool(["sample", self.sample, "--out", self.out, "--base-url", self.url])
        self.assertNotEqual(code, 0)
        self.assertIn("maybe", text)
        self.assertFalse(os.path.exists(self.out))

    def test_a_refused_request_is_reported_and_no_sheet_is_written(self):
        self.state.systemone_status = 422
        self.state.systemone_error = "invalid questions"
        code, text = self.run_tool(["sample", self.sample, "--out", self.out, "--base-url", self.url])
        self.assertNotEqual(code, 0)
        self.assertIn("422", text)
        self.assertFalse(os.path.exists(self.out))


class KeyAndInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jev-input-")
        self.sample = os.path.join(self.tmp, "sample.csv")
        write_sample(self.sample, [sample_row("e1")])
        self.out = os.path.join(self.tmp, "out.csv")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_run_without_the_key_names_the_variable_and_writes_nothing(self):
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}), \
                redirect_stdout(buf), redirect_stderr(buf):
            code = ja.main(["sample", self.sample, "--out", self.out, "--base-url", "http://127.0.0.1:9"])
        self.assertNotEqual(code, 0)
        self.assertIn("TYPESAFE_API_KEY", buf.getvalue())
        self.assertFalse(os.path.exists(self.out))

    def test_a_csv_that_is_not_an_exit_audit_sample_is_refused(self):
        wrong = os.path.join(self.tmp, "wrong.csv")
        write_sample(wrong, [{"foo": "bar"}], ["foo"])
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            code = ja.main(["sample", wrong, "--out", self.out, "--dry-run"])
        self.assertNotEqual(code, 0)
        self.assertIn("event_id", buf.getvalue())
        self.assertFalse(os.path.exists(self.out))


class ReauditTests(unittest.TestCase):
    """A synthetic detector-labels folder. The stub answers FALSE_POSITIVE for every row, as the single annotator
    does for every synthetic label here, so agreement is perfect and the arithmetic is checked by hand."""

    D1_FIELDS = ["flag_id", "in_sample", "run", "month_no", "month_name", "member", "field", "metric",
                 "claim_text", "claimed", "observed", "located", "sentence", "briefing", "prompt_found"]
    D2_FIELDS = ["flag_id", "run", "month_no", "month_name", "member", "motion", "motion_type", "motion_subject",
                 "motion_text", "passed", "tally", "stance", "vote", "source", "statement", "vote_condition",
                 "reason_full"]

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jev-reaudit-")
        d = self.tmp
        write_sample(os.path.join(d, "D1_evidence_all137.csv"), [
            {"flag_id": "D1-001", "in_sample": "yes", "run": "r", "month_no": "1", "month_name": "Month 1",
             "member": "A", "field": "notes", "metric": "reserves", "claim_text": "8 m", "claimed": "8000000.0",
             "observed": "74912000.0", "located": "value", "sentence": "We spent 8M on farm support this month.",
             "briefing": "reserves about 80M gold", "prompt_found": "True"},
            {"flag_id": "D1-002", "in_sample": "yes", "run": "r", "month_no": "2", "month_name": "Month 2",
             "member": "B", "field": "statement", "metric": "unemployment", "claim_text": "82", "claimed": "82",
             "observed": "10.1", "located": "value", "sentence": "Economy: output 82, unemployment 10%.",
             "briefing": "unemployment 10.1%", "prompt_found": "True"},
            {"flag_id": "D1-003", "in_sample": "no", "run": "r", "month_no": "3", "month_name": "Month 3",
             "member": "C", "field": "notes", "metric": "inflation", "claim_text": "15", "claimed": "15",
             "observed": "0.7", "located": "value",
             "sentence": "Inflation rises further into 15% annually.", "briefing": "", "prompt_found": "False"},
        ], self.D1_FIELDS)
        write_sample(os.path.join(d, "D1_labels_sample40.csv"), [
            {"flag_id": "D1-001", "label": "FALSE_POSITIVE", "reason": "a flow, not a reserves level"},
            {"flag_id": "D1-002", "label": "FALSE_POSITIVE", "reason": "the 82 is output"},
        ], ["flag_id", "label", "reason"])
        write_sample(os.path.join(d, "D1_labels_replay_unsampled11.csv"), [
            {"flag_id": "D1-003", "label": "FALSE_POSITIVE", "reason": "a forecast"},
        ], ["flag_id", "label", "reason"])
        write_sample(os.path.join(d, "D1_replay_current_main.csv"), [
            {"flag_id": "D1-001", "in_sample": "yes", "recorded_metric": "reserves", "replay": "clear",
             "replay_metric": "", "replay_code": ""},
            {"flag_id": "D1-002", "in_sample": "yes", "recorded_metric": "unemployment", "replay": "unverifiable",
             "replay_metric": "", "replay_code": ""},
            {"flag_id": "D1-003", "in_sample": "no", "recorded_metric": "inflation", "replay": "clear",
             "replay_metric": "", "replay_code": ""},
        ], ["flag_id", "in_sample", "recorded_metric", "replay", "replay_metric", "replay_code"])
        write_sample(os.path.join(d, "D2_evidence_36.csv"), [
            {"flag_id": "D2-001", "run": "r", "month_no": "9", "month_name": "Month 9", "member": "A",
             "motion": "M5", "motion_type": "diplomacy", "motion_subject": "non_aggression",
             "motion_text": "Ratify the non-aggression pact.", "passed": "True", "tally": "(5 yes, 0 no)",
             "stance": "oppose", "vote": "yes", "source": "stance", "statement": "",
             "vote_condition": "", "reason_full": "The pact secures border calm."},
            {"flag_id": "D2-002", "run": "r", "month_no": "9", "month_name": "Month 9", "member": "B",
             "motion": "M2", "motion_type": "set_policy", "motion_subject": "printing",
             "motion_text": "Cap printing.", "passed": "True", "tally": "(4 yes, 1 no)",
             "stance": "support", "vote": "no", "source": "stance", "statement": "",
             "vote_condition": "", "reason_full": "A binding printing cap is unnecessary discipline."},
        ], self.D2_FIELDS)
        write_sample(os.path.join(d, "D2_labels_36.csv"), [
            {"flag_id": "D2-001", "label": "FALSE_POSITIVE", "reason": "the reason supports the vote"},
            {"flag_id": "D2-002", "label": "FALSE_POSITIVE", "reason": "the reason is a no"},
        ], ["flag_id", "label", "reason"])
        self.runs = os.path.join(self.tmp, "runs")
        os.makedirs(self.runs)          # empty: the current reason rule sees no ballots
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.out)
        self.server, self.state, self.url = stub_servers.start()
        self.state.systemone_reply = {
            "d1_label": {"type": "choice", "choice": "FALSE_POSITIVE",
                         "probabilities": {"TRUE_ERROR": 0.05, "FALSE_POSITIVE": 0.9, "UNCLEAR": 0.05},
                         "confidence": 0.8},
            "d2_label": {"type": "choice", "choice": "FALSE_POSITIVE",
                         "probabilities": {"TRUE_MISMATCH": 0.1, "FALSE_POSITIVE": 0.8, "UNCLEAR": 0.1},
                         "confidence": 0.7},
        }

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_tool(self, argv):
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": KEY}), \
                redirect_stdout(buf), redirect_stderr(buf):
            code = ja.main(argv)
        return code, buf.getvalue()

    def test_the_reaudit_labels_the_detector_rows_and_reports_before_and_after(self):
        code, text = self.run_tool(["reaudit", "--labels-dir", self.tmp, "--out-dir", self.out,
                                    "--runs", self.runs, "--base-url", self.url])
        self.assertEqual(code, 0, text)
        d1 = {r["flag_id"]: r for r in read_csv(os.path.join(self.out, "D1_jev_labels.csv"))}
        self.assertEqual(set(d1), {"D1-001", "D1-002", "D1-003"})
        self.assertEqual(d1["D1-001"]["annotator_2"], "FALSE_POSITIVE")
        self.assertAlmostEqual(float(d1["D1-001"]["annotator_2_confidence"]), 0.8)
        self.assertEqual(d1["D1-001"]["annotator_2_model"], "jev-stub-1")
        d2 = {r["flag_id"]: r for r in read_csv(os.path.join(self.out, "D2_jev_labels.csv"))}
        self.assertEqual(set(d2), {"D2-001", "D2-002"})
        self.assertEqual(d2["D2-001"]["annotator_2"], "FALSE_POSITIVE")
        # Every Jev label equals the single annotator's, so p_o = 1 and kappa = alpha = 1.
        self.assertIn("D1 sample (recorded flags, before T144): 2 rows", text)
        self.assertIn("2/2 = 1.0000", text)
        self.assertIn("D1 replay-labelled remainder (after the replay): 1 rows", text)
        self.assertIn("D1 all labelled rows: 3 rows", text)
        self.assertIn("D2 recorded stance flags (before T144): 2 rows", text)
        self.assertIn("0 flagged of 3 recorded texts", text)
        self.assertIn("0 flagged of 0 ballots", text)
        self.assertNotIn(KEY, text)

    def test_the_reaudit_dry_run_needs_no_key_and_sends_nothing(self):
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}), redirect_stdout(buf):
            code = ja.main(["reaudit", "--labels-dir", self.tmp, "--out-dir", self.out,
                            "--runs", self.runs, "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("cost estimate", buf.getvalue().lower())
        self.assertIn("No request was sent", buf.getvalue())
        self.assertEqual(self.state.requests, [])


class AgreementMathTests(unittest.TestCase):
    def test_the_agreement_table_uses_the_exit_audit_statistics(self):
        # Same 50-row table as tests/test_engine24_exit_audit.AgreementTests: p_o = 0.70, kappa = 0.40.
        spec = [(20, SUP, SUP), (5, SUP, AMB), (10, AMB, SUP), (15, AMB, AMB)]
        pairs = []
        for count, jev, human in spec:
            pairs += [(jev, human)] * count
        line = ja.agreement_line("test", pairs)
        self.assertIn("50 rows", line)
        self.assertIn("35/50 = 0.7000", line)
        self.assertIn("0.4000", line)
        self.assertEqual(ja.agreement_line("empty", []),
                         "empty: no paired labels; agreement undefined.")


if __name__ == "__main__":
    unittest.main()
