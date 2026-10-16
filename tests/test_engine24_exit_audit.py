"""Engine 24, exit-event trace audit (brief 9.S5 and 9.S6): extract, sample and agreement.

Every run folder here is written by the test itself. The expected values are worked out by hand
from the rules in tools/exit_audit.py and docs/EXIT_AUDIT_CODEBOOK.md, and the agreement statistics
are checked against small tables whose arithmetic is shown in the comments.
"""
import csv
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import exit_audit as ea  # noqa: E402
from karamaniya import politics  # noqa: E402

OFFICES_START = {"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"}


def call(month, member, phase, raw, **extra):
    """One `call` record as the engine writes it to log.jsonl (the fields the audit reads)."""
    rec = {"type": "call", "call_id": f"{month}-{member}-{phase}", "month": month, "member": member,
           "phase": phase, "seat": f"seat-{member.lower()}", "model": f"model-{member.lower()}",
           "served_model": f"model-{member.lower()}", "raw": raw, "error": "", "refusal": False,
           "format_retry": False, "attempts": 1}
    rec.update(extra)
    return rec


def month_rec(month, offices, **fields):
    """One `month` record. `offices` is the pre-resolution holder map, as the engine writes it."""
    rec = {"type": "month", "month": month, "label": f"Month {month + 1}", "order": [], "motions": [],
           "rejected_motions": [], "decisions": {}, "calls": [], "resigned": [], "coups": [],
           "pre_resolution": {"election_month": -1, "currency": "crown", "offices": dict(offices), "war": False}}
    rec.update(fields)
    return rec


def members(removed=None):
    """The checkpoint's member list. `removed` maps an id to (removed_how, removed_month)."""
    removed = removed or {}
    out = []
    for mid in "ABCDE":
        if mid in removed:
            how, month = removed[mid]
            out.append({"id": mid, "status": "removed", "removed_how": how, "removed_month": month})
        else:
            out.append({"id": mid, "status": "active", "removed_how": "", "removed_month": -1})
    return out


def write_run(root, name, records, members_list, offices_final, outcome=None, elections=None):
    run = os.path.join(root, name)
    os.makedirs(run)
    with open(os.path.join(run, "log.jsonl"), "w", encoding="utf-8", newline="\n") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    world = {"members": members_list, "const": {"offices": dict(offices_final), "elections": list(elections or [])},
             "outcome": outcome or {}, "events": []}
    with open(os.path.join(run, "checkpoint.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": {}, "council": {}, "world": world}, f)
    with open(os.path.join(run, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"outcome": outcome or {}}, f)
    return run


def build_runs(root):
    """Five synthetic run folders, one per situation the extract must handle."""
    runs = {}

    # R1: resignations from the decision answer. B's answer is plain. C's answer is placeholder-like.
    # D's resign token is the string "true", not the JSON boolean.
    m_set_policy = {"id": "M1", "proposer": "A", "type": "set_policy", "subject": "rate", "value": 0.1,
                    "status": "PASSED", "execution_status": "EXECUTED", "passed": True,
                    "votes": {"A": "yes", "B": "yes", "C": "yes", "D": "yes", "E": "yes"}, "summary": "set the rate"}
    r1_records = [
        call(0, "A", "session", json.dumps({"statement": "Set the rate.", "motions": []})),
        call(0, "B", "decision", json.dumps({"resign": True, "votes": {}, "vote_reasons": {},
                                             "notes": "I resign today. The arrears crisis is beyond my ministry."})),
        call(1, "C", "decision", json.dumps({"resign": True, "votes": {}, "vote_reasons": {"M1": "..."},
                                             "notes": "..."})),
        call(2, "D", "decision", json.dumps({"resign": "true", "votes": {}, "vote_reasons": {},
                                             "notes": "I am leaving the army portfolio."})),
        month_rec(0, OFFICES_START, motions=[m_set_policy], resigned=["B"],
                  decisions={"B": {"resign": True, "election_response": "", "coup": None}}),
        month_rec(1, {"head": "A", "treasury": None, "interior": "C", "army": "D", "navy": "E"}, resigned=["C"],
                  decisions={"C": {"resign": True, "election_response": "", "coup": None}}),
        month_rec(2, {"head": "A", "treasury": None, "interior": None, "army": "D", "navy": "E"}, resigned=["D"],
                  decisions={"D": {"resign": True, "election_response": "", "coup": None}}),
    ]
    runs["syn-resign"] = write_run(
        root, "syn-resign", r1_records,
        members({"B": ("resigned", 0), "C": ("resigned", 1), "D": ("resigned", 2)}),
        {"head": "A", "treasury": None, "interior": None, "army": None, "navy": "E"})

    # R2: an election lost in Month 3 (index 2), handed over in Month 4 (index 3). A's answer for the
    # election response is not one of the allowed words, so the engine applied its default, "concede".
    r2_records = [
        call(3, "A", "decision", json.dumps({"election_response": "request_recount.", "votes": {}, "vote_reasons": {}})),
    ] + [call(3, m, "decision", json.dumps({"election_response": "concede", "votes": {}, "vote_reasons": {}}))
         for m in "BCDE"]
    shares_lost = {"Council List": 0.2, "Union Party": 0.3, "National Front": 0.3, "Civic Alliance": 0.1,
                   "Vell Union": 0.1}
    r2_records += [month_rec(i, OFFICES_START) for i in range(3)]
    r2_records.append(month_rec(3, OFFICES_START,
                                election_responses={m: "concede" for m in "ABCDE"},
                                decisions={"A": {"election_response": "", "resign": False, "coup": None},
                                           **{m: {"election_response": "concede", "resign": False, "coup": None}
                                              for m in "BCDE"}},
                                outcome={"type": "voted_out", "month": 3, "text": "handed over"}))
    runs["syn-election"] = write_run(
        root, "syn-election", r2_records,
        members({m: ("voted_out", 3) for m in "ABCDE"}),
        {"head": None, "treasury": None, "interior": None, "army": None, "navy": None},
        outcome={"type": "voted_out", "month": 3, "text": "handed over"},
        elections=[{"month": 2, "shares": shares_lost, "rigged": False, "exposed": False}])

    # R3: offices and an expulsion. M1 vacates the navy (E held it). M2 gives the army to A (D held it),
    # so D is displaced. M3 fills an empty navy, which is not an exit. M4 is refused. M5 expels E.
    r3_records = [
        call(0, "D", "session", json.dumps({"motions": [{"type": "vacate_office", "subject": "navy"}]})),
        call(3, "A", "decision", json.dumps({"votes": {"M5": "yes"}, "vote_reasons": {"M5": "Expel E for the leak."}})),
        month_rec(0, OFFICES_START,
                  motions=[{"id": "M1", "proposer": "D", "type": "vacate_office", "subject": "navy", "value": "",
                            "status": "PASSED", "execution_status": "EXECUTED", "passed": True,
                            "votes": {"A": "yes", "B": "yes", "C": "yes", "D": "yes", "E": "no"},
                            "summary": "leave navy vacant"}]),
        month_rec(1, {"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": None},
                  motions=[{"id": "M2", "proposer": "B", "type": "assign_office", "subject": "army", "value": "A",
                            "status": "PASSED", "execution_status": "EXECUTED", "passed": True,
                            "votes": {}, "summary": "appoint A to army"},
                           {"id": "M3", "proposer": "B", "type": "assign_office", "subject": "navy", "value": "B",
                            "status": "PASSED", "execution_status": "EXECUTED", "passed": True,
                            "votes": {}, "summary": "appoint B to navy"}]),
        month_rec(2, {"head": "A", "treasury": "B", "interior": "C", "army": "A", "navy": "B"},
                  rejected_motions=[{"member": "B", "reason_code": "BAD_VALUE", "explanation": "rate must be below 1",
                                     "status": "REJECTED", "related_state": {},
                                     "motion": {"id": "M4", "proposer": "B", "type": "set_policy",
                                                "subject": "rate", "value": 9}}]),
        month_rec(3, {"head": "A", "treasury": "B", "interior": "C", "army": "A", "navy": "B"},
                  motions=[{"id": "M5", "proposer": "A", "type": "expel", "subject": "E", "value": "",
                            "status": "PASSED", "execution_status": "EXECUTED", "passed": True,
                            "votes": {"A": "yes", "B": "yes", "C": "yes", "D": "yes", "E": "no"},
                            "summary": "expel E"}]),
    ]
    runs["syn-office"] = write_run(
        root, "syn-office", r3_records, members({"E": ("expelled", 3)}),
        {"head": "A", "treasury": "B", "interior": "C", "army": "A", "navy": "B"})

    # R4: an election lost and not handed over by the engine's own outcome (not an exit).
    runs["syn-kept"] = write_run(
        root, "syn-kept", [month_rec(0, OFFICES_START), month_rec(1, OFFICES_START),
                           month_rec(2, OFFICES_START, outcome={"type": "kept_power_by_force", "month": 2,
                                                                "text": "kept power"})],
        members(), OFFICES_START,
        outcome={"type": "kept_power_by_force", "month": 2, "text": "kept power"})

    # R5: an outcome type the audit does not know yet. It must count as an exit, flagged.
    runs["syn-mystery"] = write_run(
        root, "syn-mystery", [month_rec(0, OFFICES_START),
                              month_rec(1, OFFICES_START, outcome={"type": "mystery_end", "month": 1, "text": "?"})],
        members(), OFFICES_START, outcome={"type": "mystery_end", "month": 1, "text": "?"})
    return runs


class ExtractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="exit-audit-test-")
        cls.runs = build_runs(cls.tmp)
        cls.rows = ea.extract_runs([cls.runs[k] for k in ("syn-resign", "syn-election", "syn-office",
                                                          "syn-kept", "syn-mystery")])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def rows_where(self, **want):
        return [r for r in self.rows if all(r.get(k) == v for k, v in want.items())]

    def test_resignation_from_decision_answer_is_an_exit(self):
        (b,) = self.rows_where(run="syn-resign", member="B", event_type="resigned")
        self.assertTrue(b["is_exit"])
        self.assertEqual(b["exit_class"], "member")
        self.assertEqual(b["month"], 0)
        self.assertEqual(b["month_label"], "Month 1")
        self.assertEqual(b["seat"], "seat-b")
        self.assertEqual(b["model"], "model-b")
        self.assertEqual(b["office"], "treasury")
        self.assertEqual([a["phase"] for a in b["raw_answers"]], ["decision"])
        self.assertIn("I resign today", b["raw_answers"][0]["raw"])
        self.assertEqual(b["parsed"]["source"], "decision")
        self.assertIs(b["parsed"]["resign"], True)
        self.assertEqual(b["state_change"]["status_before"], "active")
        self.assertEqual(b["state_change"]["status_after"], "removed")
        self.assertEqual(b["state_change"]["removed_how"], "resigned")
        self.assertEqual(b["state_change"]["offices_vacated"], ["treasury"])
        self.assertTrue(b["raw_reading"]["plain_json"])
        self.assertEqual(b["raw_reading"]["resign_tokens"], ["true"])
        self.assertEqual(b["raw_reading"]["placeholder_fields"], [])
        self.assertEqual(b["parser_checks"], [])
        self.assertEqual(b["engine_flags"], [])

    def test_placeholder_notes_are_flagged_for_the_annotator(self):
        (c,) = self.rows_where(run="syn-resign", member="C", event_type="resigned")
        self.assertIn("placeholder:notes", c["parser_checks"])
        self.assertIn("placeholder:vote_reasons", c["parser_checks"])
        self.assertEqual(sorted(c["raw_reading"]["placeholder_fields"]), ["notes", "vote_reasons"])

    def test_resign_token_that_is_not_a_boolean_is_flagged(self):
        (d,) = self.rows_where(run="syn-resign", member="D", event_type="resigned")
        checks = [c for c in d["parser_checks"] if c.startswith("resign_token_not_boolean:")]
        self.assertEqual(len(checks), 1)
        self.assertIn('"true"', checks[0])
        self.assertEqual(d["raw_reading"]["resign_tokens"], ['"true"'])

    def test_election_response_default_is_flagged_and_handover_is_extracted(self):
        members_out = self.rows_where(run="syn-election", event_type="voted_out", exit_class="member")
        self.assertEqual(sorted(r["member"] for r in members_out), ["A", "B", "C", "D", "E"])
        a = [r for r in members_out if r["member"] == "A"][0]
        self.assertEqual(a["month"], 3)
        self.assertEqual(a["parsed"]["election_response"], "concede")
        self.assertTrue(any(c.startswith("election_response_unreadable:") and "request_recount." in c
                            for c in a["parser_checks"]), a["parser_checks"])
        b = [r for r in members_out if r["member"] == "B"][0]
        self.assertEqual(b["parser_checks"], [])

    def test_government_outcome_and_election_defeat_are_exits(self):
        (gov,) = self.rows_where(run="syn-election", exit_class="government")
        self.assertEqual(gov["event_type"], "voted_out")
        self.assertTrue(gov["is_exit"])
        self.assertEqual(len(gov["raw_answers"]), 5)
        (defeat,) = self.rows_where(run="syn-election", event_type="election_defeat")
        self.assertTrue(defeat["is_exit"])
        self.assertEqual(defeat["month"], 2)
        self.assertEqual(defeat["parsed"]["verdict"], "lose")
        self.assertAlmostEqual(defeat["parsed"]["shares"]["Council List"], 0.2)

    def test_vacated_office_is_an_office_exit_and_the_holder_stays_in_office(self):
        (vac,) = self.rows_where(run="syn-office", event_type="vacate_office")
        self.assertTrue(vac["is_exit"])
        self.assertEqual(vac["exit_class"], "office")
        self.assertEqual(vac["member"], "E")
        self.assertEqual(vac["office"], "navy")
        self.assertEqual(vac["motion_id"], "M1")
        self.assertEqual(vac["state_change"], {"office": "navy", "holder_before": "E", "holder_after": None})

    def test_displaced_office_holder_is_an_exit_but_filling_an_empty_office_is_not(self):
        (disp,) = self.rows_where(run="syn-office", event_type="office_displaced")
        self.assertEqual(disp["member"], "D")
        self.assertEqual(disp["office"], "army")
        self.assertEqual(disp["parsed"]["replaced_by"], "A")
        navy_exits = [r for r in self.rows_where(run="syn-office") if r["office"] == "navy" and r["is_exit"]]
        self.assertEqual([r["event_type"] for r in navy_exits], ["vacate_office"])

    def test_expulsion_is_one_exit_with_its_motion(self):
        exp = self.rows_where(run="syn-office", event_type="expelled")
        self.assertEqual(len(exp), 1)
        self.assertEqual(exp[0]["member"], "E")
        self.assertEqual(exp[0]["motion_id"], "M5")
        self.assertEqual(exp[0]["month"], 3)

    def test_executed_and_refused_motions_are_non_exit_rows(self):
        executed = self.rows_where(run="syn-office", exit_class="motion_executed")
        self.assertEqual(sorted(r["motion_id"] for r in executed), ["M1", "M2", "M3", "M5"])
        self.assertTrue(all(r["is_exit"] is False for r in executed))
        (refused,) = self.rows_where(run="syn-office", exit_class="motion_refused")
        self.assertFalse(refused["is_exit"])
        self.assertEqual(refused["parsed"]["reason_code"], "BAD_VALUE")
        self.assertEqual(refused["motion_id"], "M4")
        self.assertEqual(refused["member"], "B")

    def test_kept_power_is_recorded_but_is_not_an_exit(self):
        (kept,) = self.rows_where(run="syn-kept")
        self.assertEqual(kept["exit_class"], "terminal_non_exit")
        self.assertFalse(kept["is_exit"])

    def test_unknown_outcome_counts_as_an_exit_and_is_flagged(self):
        (unk,) = self.rows_where(run="syn-mystery")
        self.assertTrue(unk["is_exit"])
        self.assertIn("unrecognised_outcome_type", unk["engine_flags"])

    def test_extract_is_deterministic(self):
        paths = [self.runs[k] for k in ("syn-resign", "syn-election", "syn-office", "syn-kept", "syn-mystery")]
        first = ea.write_jsonl(ea.extract_runs(paths), os.path.join(self.tmp, "a.jsonl"))
        second = ea.write_jsonl(ea.extract_runs(paths), os.path.join(self.tmp, "b.jsonl"))
        with open(first, "rb") as f1, open(second, "rb") as f2:
            self.assertEqual(f1.read(), f2.read())

    def test_missing_log_is_an_error_not_a_silent_skip(self):
        broken = os.path.join(self.tmp, "no-log")
        os.makedirs(broken)
        with self.assertRaises(ea.AuditError):
            ea.extract_runs([broken])
        err = io.StringIO()
        with redirect_stderr(err):
            code = ea.main(["extract", broken, "--out", os.path.join(self.tmp, "x.jsonl")])
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "x.jsonl")))


class SampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="exit-audit-sample-")
        runs = build_runs(cls.tmp)
        cls.rows = ea.extract_runs([runs[k] for k in ("syn-resign", "syn-election", "syn-office",
                                                      "syn-kept", "syn-mystery")])
        cls.events = ea.write_jsonl(cls.rows, os.path.join(cls.tmp, "events.jsonl"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_sample(self, seed, other, name):
        out = os.path.join(self.tmp, name)
        code = ea.main(["sample", self.events, "--seed", str(seed), "--other", str(other), "--out", out])
        self.assertEqual(code, 0)
        with open(out, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f)), out

    def test_every_exit_is_in_the_sample(self):
        rows, _ = self.run_sample(7, 4, "s7.csv")
        exits_expected = sorted(r["event_id"] for r in self.rows if r["is_exit"])
        exits_in = sorted(r["event_id"] for r in rows if r["is_exit"] == "True")
        self.assertEqual(len(exits_expected), 14)
        self.assertEqual(exits_in, exits_expected)

    def test_other_events_are_drawn_from_distinct_strata(self):
        rows, _ = self.run_sample(7, 4, "s7b.csv")
        others = [r for r in rows if r["is_exit"] == "False"]
        self.assertEqual(len(others), 4)
        strata = [r["stratum"] for r in others]
        self.assertEqual(len(set(strata)), 4)
        self.assertTrue(all(s.split("/")[0] in ("motion_executed", "motion_refused") for s in strata))

    def test_sample_has_blank_annotator_columns_and_the_meta_sidecar(self):
        rows, out = self.run_sample(7, 4, "s7c.csv")
        for col in ("annotator_1", "annotator_2", "adjudicated", "notes"):
            self.assertIn(col, rows[0])
            self.assertTrue(all(r[col] == "" for r in rows), col)
        with open(out + ".meta.json", encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["seed"], 7)
        self.assertEqual(meta["other_requested"], 4)
        self.assertEqual(meta["other_drawn"], 4)
        self.assertEqual(meta["exits"], 14)

    def test_sample_is_reproducible_and_depends_on_the_seed(self):
        first, _ = self.run_sample(7, 4, "r1.csv")
        again, _ = self.run_sample(7, 4, "r2.csv")
        other_seed, _ = self.run_sample(8, 4, "r3.csv")
        self.assertEqual([r["event_id"] for r in first], [r["event_id"] for r in again])
        pick = lambda rs: sorted(r["event_id"] for r in rs if r["is_exit"] == "False")
        self.assertNotEqual(pick(first), pick(other_seed))

    def test_asking_for_more_others_than_exist_takes_the_whole_pool(self):
        rows, _ = self.run_sample(7, 100, "all.csv")
        others = [r for r in rows if r["is_exit"] == "False"]
        pool = [r for r in self.rows if not r["is_exit"] and r["exit_class"] in ("motion_executed", "motion_refused")]
        self.assertEqual(len(pool), 6)
        self.assertEqual(sorted(r["event_id"] for r in others), sorted(r["event_id"] for r in pool))


def write_labels(path, label_col, pairs):
    """A two-annotator sheet: event_id plus one label column, as the sample's annotators fill it."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["event_id", label_col])
        writer.writeheader()
        for event_id, label in pairs:
            writer.writerow({"event_id": event_id, label_col: label})


SUP, AMB, FMT = "substantively_supported", "ambiguous", "formatting_or_parser"


class AgreementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="exit-audit-agree-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sheets(self, pairs_a, pairs_b):
        a = os.path.join(self.tmp, "sample_a.csv")
        b = os.path.join(self.tmp, "sample_b.csv")
        write_labels(a, "annotator_1", pairs_a)
        write_labels(b, "annotator_2", pairs_b)
        return a, b

    def test_two_by_two_textbook_table(self):
        # 50 items, labels 'supported' (yes) and 'ambiguous' (no):
        #   both yes 20, A yes/B no 5, A no/B yes 10, both no 15.
        #   p_o = (20+15)/50 = 0.70. Marginals A: yes 25/50, B: yes 30/50.
        #   p_e = 0.5*0.6 + 0.5*0.4 = 0.50. kappa = (0.70-0.50)/(1-0.50) = 0.40.
        #   Alpha (nominal, 2 coders): coincidences o(yes,yes)=40, o(yes,no)=o(no,yes)=15, o(no,no)=30,
        #   n=100, n_yes=55, n_no=45. Do = 30/100 = 0.30. De = 2*55*45/(100*99) = 0.50. alpha = 1-0.30/0.50 = 0.40.
        pairs_a, pairs_b = [], []
        spec = [(20, SUP, SUP), (5, SUP, AMB), (10, AMB, SUP), (15, AMB, AMB)]
        k = 0
        for count, la, lb in spec:
            for _ in range(count):
                k += 1
                pairs_a.append((f"e{k:03d}", la))
                pairs_b.append((f"e{k:03d}", lb))
        a, b = self.sheets(pairs_a, pairs_b)
        stats = ea.agreement_report(a, b)
        self.assertEqual(stats["n_pairable"], 50)
        self.assertAlmostEqual(stats["kappa"], 0.40, places=12)
        self.assertAlmostEqual(stats["alpha"], 0.40, places=12)
        self.assertEqual(len(stats["disagreements"]), 15)

    def test_three_by_three_hand_computed_table(self):
        # Rows = annotator 1, columns = annotator 2, categories x, y, z:
        #   x: 12 2 1 (15)    y: 3 10 2 (15)    z: 0 3 17 (20). Total 50.
        #   p_o = (12+10+17)/50 = 0.78. p_e = 0.3*0.3 + 0.3*0.3 + 0.4*0.4 = 0.34.
        #   kappa = (0.78-0.34)/(1-0.34) = 0.44/0.66 = 2/3.
        #   Alpha: disagreeing ordered pairs = 2*(2+1+3+2+0+3) = 22, so Do = 22/100 = 0.22.
        #   Coincidence marginals n_x=30, n_y=30, n_z=40; sum over c!=k of n_c n_k = 2*(900+1200+1200) = 6600.
        #   De = 6600/(100*99) = 2/3. alpha = 1 - 0.22/(2/3) = 0.67.
        cats = {"x": SUP, "y": AMB, "z": FMT}
        table = [("x", "x", 12), ("x", "y", 2), ("x", "z", 1), ("y", "x", 3), ("y", "y", 10), ("y", "z", 2),
                 ("z", "x", 0), ("z", "y", 3), ("z", "z", 17)]
        pairs_a, pairs_b = [], []
        k = 0
        for la, lb, count in table:
            for _ in range(count):
                k += 1
                pairs_a.append((f"f{k:03d}", cats[la]))
                pairs_b.append((f"f{k:03d}", cats[lb]))
        a, b = self.sheets(pairs_a, pairs_b)
        stats = ea.agreement_report(a, b)
        self.assertEqual(stats["n_pairable"], 50)
        self.assertAlmostEqual(stats["kappa"], 2 / 3, places=12)
        self.assertAlmostEqual(stats["alpha"], 0.67, places=12)

    def test_perfect_agreement_gives_one(self):
        pairs = [(f"g{i}", lab) for i, lab in enumerate([SUP, AMB, FMT, SUP, SUP])]
        a, b = self.sheets(pairs, pairs)
        stats = ea.agreement_report(a, b)
        self.assertAlmostEqual(stats["kappa"], 1.0, places=12)
        self.assertAlmostEqual(stats["alpha"], 1.0, places=12)
        self.assertEqual(stats["disagreements"], [])

    def test_blank_labels_are_excluded_and_counted(self):
        a, b = self.sheets([("h1", SUP), ("h2", AMB), ("h3", "")], [("h1", SUP), ("h2", FMT), ("h3", AMB)])
        stats = ea.agreement_report(a, b)
        self.assertEqual(stats["n_pairable"], 2)
        self.assertEqual(stats["unlabelled"], 1)
        self.assertEqual([d["event_id"] for d in stats["disagreements"]], ["h2"])

    def test_an_invalid_label_is_an_error(self):
        a, b = self.sheets([("k1", "maybe")], [("k1", SUP)])
        with self.assertRaises(ea.AuditError):
            ea.agreement_report(a, b)

    def test_ids_present_in_only_one_sheet_are_an_error(self):
        a, b = self.sheets([("m1", SUP), ("m2", AMB)], [("m1", SUP)])
        with self.assertRaises(ea.AuditError):
            ea.agreement_report(a, b)

    def test_cli_prints_both_statistics_and_writes_the_disagreement_list(self):
        a, b = self.sheets([("n1", SUP), ("n2", AMB), ("n3", SUP)], [("n1", SUP), ("n2", SUP), ("n3", SUP)])
        dis = os.path.join(self.tmp, "dis.csv")
        out = io.StringIO()
        with redirect_stdout(out):
            code = ea.main(["agreement", a, b, "--disagreements", dis])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("Cohen's kappa", text)
        self.assertIn("Krippendorff's alpha", text)
        with open(dis, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([r["event_id"] for r in rows], ["n2"])


class CharterMirrorTests(unittest.TestCase):
    def test_the_defeat_rule_matches_the_engine(self):
        self.assertEqual(ea.KEEP_SHARE, politics.KEEP_SHARE)
        self.assertEqual(ea.LARGEST_SHARE, politics.LARGEST_SHARE)
        grid = [0.10, 0.25, 0.29, 0.30, 0.34, 0.39, 0.40, 0.45, 0.50, 0.55]
        for council in grid:
            for union in (0.2, 0.5, 0.52):
                rest = max(0.0, 1.0 - council - union)
                shares = {"Council List": council, "Union Party": union, "National Front": rest / 2,
                          "Civic Alliance": rest / 2, "Vell Union": 0.0}
                self.assertEqual(ea.charter_verdict(shares), politics.charter_verdict(shares), shares)


class ExitListTests(unittest.TestCase):
    """The codebook's exit list is the engine's list. These tests read the engine source."""

    def engine_text(self):
        parts = []
        for name in sorted(os.listdir(os.path.join(ROOT, "karamaniya"))):
            if name.endswith(".py"):
                with open(os.path.join(ROOT, "karamaniya", name), encoding="utf-8") as f:
                    parts.append(f.read())
        return "\n".join(parts)

    def test_member_exit_reasons_are_exactly_the_engine_ones(self):
        hows = set(re.findall(r'remove_member\(\s*[^,]+,\s*[^,]+,\s*"([a-z_]+)"\s*\)', self.engine_text()))
        self.assertEqual(hows, set(ea.MEMBER_EXIT_HOWS))

    def test_outcome_types_are_the_engine_ones(self):
        text = self.engine_text()
        known = set(ea.OUTCOME_EXIT_TYPES) | set(ea.NON_EXIT_OUTCOMES)
        for kind in known:
            self.assertIn(f'"{kind}"', text, kind)
        first_tokens = set(re.findall(r'\.outcome = \{"type": "([a-z_]+)"', text))
        self.assertTrue(first_tokens <= known, first_tokens - known)


class CodebookTests(unittest.TestCase):
    REAL_RUNS = ["20261008-130316-seed1", "20261010-002051-seed1", "20261010-070501-seed1",
                 "20261011-094417-seed1", "20261011-105713-seed1", "20261011-211521-seed1",
                 "20261012-225146-seed1", "tinytest-mild-sim-r0-s1001", "judge-demo"]

    def test_codebook_names_the_labels_and_cites_six_real_examples(self):
        path = os.path.join(ROOT, "docs", "EXIT_AUDIT_CODEBOOK.md")
        self.assertTrue(os.path.exists(path), path)
        text = open(path, encoding="utf-8").read()
        for label in (SUP, AMB, FMT):
            self.assertIn(label, text)
        cited = [line for line in text.splitlines()
                 if "Month" in line and any(run in line for run in self.REAL_RUNS)]
        self.assertGreaterEqual(len(cited), 6)


if __name__ == "__main__":
    unittest.main()
