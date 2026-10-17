"""The study analysis (brief S6 and S7): Kaplan-Meier and restricted means against hand-computed values, censoring,
a bootstrap that is fixed by its seed, exit extraction on synthetic run folders, the label and plan formats, the
rates, the protocol pairs, and one end-to-end pass over a small synthetic grid. Nothing here reads research\\runs or
calls a model: every run folder is written into a temporary directory."""
import csv
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import study_analysis as sa  # noqa: E402

LETTERS = "ABCDE"
FORMATION = {"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"}


def write_run(root, name, *, seed=1, mapping=None, months=3, formation=None, log=(), removals=None,
              final_offices=None, outcome=None, elections=(), stopped="", office_assignment=None,
              action_order=None, scripted=False):
    """A minimal run folder in the shape the engine writes: manifest.json, config.json, checkpoint.json and
    log.jsonl. removals maps a letter to (month, how); every other member is active at the checkpoint."""
    mapping = mapping or {L: f"seat-{L}" for L in LETTERS}
    removals = removals or {}
    formation = formation or dict(FORMATION)
    final_offices = final_offices if final_offices is not None else dict(formation)
    provider = "scripted" if scripted else "openrouter"
    d = os.path.join(root, name)
    os.makedirs(d)
    seats = [{"seat": L, "label": mapping[L], "model": f"model-{mapping[L]}", "provider": provider}
             for L in LETTERS]
    run = {"months": months, "seed": seed}
    if office_assignment:
        run["office_assignment"] = office_assignment
    if action_order:
        run["action_order"] = action_order
    manifest = {"seeds": {"run_seed": seed, "months_total": months}, "seats": seats,
                "served_models": {L: [f"model-{mapping[L]}"] for L in LETTERS}}
    members = []
    for L in LETTERS:
        if L in removals:
            month_index, how = removals[L]
            members.append({"id": L, "name": f"Delegate {L}", "status": "removed",
                            "removed_month": month_index, "removed_how": how})
        else:
            members.append({"id": L, "name": f"Delegate {L}", "status": "active", "removed_month": -1,
                            "removed_how": ""})
    checkpoint = {"world": {"month": months - 1, "members": members,
                            "const": {"offices": dict(final_offices), "elections": list(elections)},
                            "outcome": outcome or {}},
                  "council": {}, "meta": {"stopped": stopped}}
    config = {"run": run, "mapping": dict(mapping),
              "seats": [{"label": mapping[L], "provider": provider} for L in LETTERS]}
    for name_, data in (("manifest.json", manifest), ("config.json", config), ("checkpoint.json", checkpoint)):
        with open(os.path.join(d, name_), "w", encoding="utf-8") as f:
            json.dump(data, f)
    records = [{"type": "government_formation", "month": -1, "offices": dict(formation)}] + list(log)
    with open(os.path.join(d, "log.jsonl"), "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    return d


def month(index, offices, **fields):
    """A month record. pre_resolution holds the holders before the month's resolution, as the engine writes it."""
    rec = {"type": "month", "month": index, "pre_resolution": {"offices": dict(offices)}, "motions": [],
           "rejected_motions": [], "calls": [], "compliance": [], "vote_intent_mismatches": [], "resigned": [],
           "coups": [], "decisions": {}}
    rec.update(fields)
    return rec


def motion(mid, proposer, mtype, subject, value="", passed=True, status="EXECUTED"):
    return {"id": mid, "proposer": proposer, "type": mtype, "subject": subject, "value": value, "passed": passed,
            "execution_status": status, "votes": {}}


class KaplanMeierAndRestrictedMean(unittest.TestCase):
    def test_km_matches_a_hand_computed_example(self):
        # Durations 2, 3, 3, 5, 6 with an exit at 2, an exit at 3, a censoring at 3, an exit at 5, a censoring at 6.
        #   t=2: 5 at risk, 1 exit                        S = 4/5           = 0.8
        #   t=3: 4 at risk (one left at 2), 1 exit        S = 0.8 * 3/4     = 0.6
        #   t=5: 2 at risk (the 5 and the 6), 1 exit      S = 0.6 * 1/2     = 0.3
        steps = sa.km_steps([2, 3, 3, 5, 6], [1, 1, 0, 1, 0])
        self.assertEqual([(t, n, d) for t, n, d, _ in steps], [(2, 5, 1), (3, 4, 1), (5, 2, 1)])
        self.assertAlmostEqual(steps[0][3], 0.8)
        self.assertAlmostEqual(steps[1][3], 0.6)
        self.assertAlmostEqual(steps[2][3], 0.3)
        self.assertAlmostEqual(sa.km_survival_at(steps, 1), 1.0)
        self.assertAlmostEqual(sa.km_survival_at(steps, 4), 0.6)
        self.assertAlmostEqual(sa.km_survival_at(steps, 6), 0.3)
        self.assertEqual(sa.km_median(steps), 5)

    def test_restricted_mean_is_the_area_under_the_km_curve(self):
        # Area to 6: 1*2 + 0.8*1 + 0.6*2 + 0.3*1 = 4.3. Area to 4: 1*2 + 0.8*1 + 0.6*1 = 3.4.
        steps = sa.km_steps([2, 3, 3, 5, 6], [1, 1, 0, 1, 0])
        self.assertAlmostEqual(sa.rmst(steps, 6), 4.3)
        self.assertAlmostEqual(sa.rmst(steps, 4), 3.4)

    def test_all_censored_keeps_survival_at_one(self):
        steps = sa.km_steps([4, 7, 10], [0, 0, 0])
        self.assertEqual(steps, [])
        self.assertAlmostEqual(sa.km_survival_at(steps, 9), 1.0)
        self.assertIsNone(sa.km_median(steps))
        self.assertAlmostEqual(sa.rmst(steps, 10), 10.0)

    def test_a_censored_subject_leaves_the_risk_set_without_an_exit(self):
        # The subject censored at 2 is no longer at risk at 3, so the exit at 3 has 2 at risk: S = 1 * (1 - 1/2).
        steps = sa.km_steps([2, 3, 4], [0, 1, 1])
        self.assertEqual([(t, n, d) for t, n, d, _ in steps], [(3, 2, 1), (4, 1, 1)])
        self.assertAlmostEqual(steps[0][3], 0.5)
        self.assertEqual(sa.km_median(steps), 3)


class Bootstrap(unittest.TestCase):
    def observations(self):
        obs = []
        models, offices = ["m1", "m2"], ["head", "army"]
        for seed in (11, 12, 13, 14):
            for rot in (0, 1):
                for i, letter in enumerate("AB"):
                    t = 2 + (seed + rot + i) % 5
                    obs.append({"run": f"s{seed}-r{rot}", "seed": seed, "rotation": rot, "protocol": "p1",
                                "letter": letter, "model": models[i], "office": offices[i], "complete": True,
                                "last_month": 6, "raw_time": t, "raw_event": int((seed + rot) % 2 == 0),
                                "val_time": t, "val_event": 0})
        return obs

    def test_the_same_seed_gives_the_same_intervals(self):
        obs = self.observations()
        first = sa.persistence_table(obs, tau=6, reps=60, seed=7, variant="raw")
        second = sa.persistence_table(obs, tau=6, reps=60, seed=7, variant="raw")
        self.assertEqual(first, second)
        for row in first:
            if row["ci_low"] is not None:
                self.assertLessEqual(row["ci_low"], row["ci_high"])

    def test_a_different_seed_changes_the_resampling(self):
        obs = self.observations()
        first = sa.persistence_table(obs, tau=6, reps=60, seed=7, variant="raw")
        other = sa.persistence_table(obs, tau=6, reps=60, seed=8, variant="raw")
        self.assertNotEqual(first, other)

    def test_protocol_differences_are_paired_and_measured_from_seeded_shuffle(self):
        base = []
        for seed in (21, 22):
            for protocol, t in (("seeded_shuffle", 2), ("fixed_precedence", 5)):
                base.append({"run": f"{protocol}-{seed}", "seed": seed, "rotation": 0, "protocol": protocol,
                             "letter": "A", "model": "m1", "office": "head", "complete": True, "last_month": 6,
                             "raw_time": t, "raw_event": 1, "val_time": t, "val_event": 1})
        rows = sa.protocol_differences(base, tau=6, reps=20, seed=3, variant="raw")
        overall = [r for r in rows if r["scope"] == "all"]
        self.assertEqual(len(overall), 1)
        self.assertEqual(overall[0]["run_pairs"], 2)
        self.assertEqual(overall[0]["seat_pairs"], 2)
        # Each matched seat moves from 2 months (seeded_shuffle) to 5 (fixed_precedence): +3 in every pair.
        self.assertAlmostEqual(overall[0]["mean_diff"], 3.0)


class ExtractionOnSyntheticRuns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def office_run(self):
        log = [
            month(0, FORMATION, resigned=["B"], motions=[motion("M1", "A", "vacate_office", "navy")]),
            month(1, {"head": "A", "treasury": None, "interior": "C", "army": "D", "navy": None},
                  motions=[motion("M2", "B", "assign_office", "treasury", "A"),
                           motion("M3", "C", "assign_office", "army", "C")]),
            month(2, {"head": "A", "treasury": "A", "interior": "C", "army": "C", "navy": None},
                  outcome={"type": "conquered", "month": 2, "text": "conquered"}),
        ]
        return write_run(self.tmp.name, "office-run", months=3, log=log, removals={"B": (0, "resigned")},
                         final_offices={"head": "A", "treasury": "A", "interior": "C", "army": "C", "navy": None},
                         outcome={"type": "conquered", "month": 2, "text": "conquered"})

    def test_member_office_and_government_exits_are_extracted(self):
        run = sa.load_run(self.office_run())
        kinds = sorted((e["month"], e["exit_class"], e["event_type"], e["member"]) for e in sa.extract_exits(run))
        self.assertEqual(kinds, [
            (0, "member", "resigned", "B"),
            (0, "office", "vacate_office", "E"),
            (1, "office", "office_displaced", "D"),
            (2, "government", "conquered", ""),
        ])

    def test_an_assignment_into_an_empty_office_is_not_an_exit(self):
        run = sa.load_run(self.office_run())
        self.assertEqual([e for e in sa.extract_exits(run)
                          if e["exit_class"] == "office" and e["office"] == "treasury"], [])

    def test_a_government_outcome_applies_to_seats_still_in_office(self):
        run = sa.load_run(self.office_run())
        timelines = sa.seat_timelines(run, sa.extract_exits(run))
        first = {letter: (events[0]["month"], events[0]["event_type"]) for letter, events in timelines.items()}
        self.assertEqual(first, {
            "A": (2, "conquered"),
            "B": (0, "resigned"),
            "C": (2, "conquered"),
            "D": (1, "office_displaced"),
            "E": (0, "vacate_office"),
        })

    def test_a_run_with_no_exit_is_censored_at_its_last_month(self):
        log = [month(0, FORMATION), month(1, FORMATION), month(2, FORMATION)]
        run = sa.load_run(write_run(self.tmp.name, "quiet", months=3, log=log))
        obs = sa.build_observations([run], labels=None, horizon=3, complete_only=False)
        self.assertEqual(sorted(o["letter"] for o in obs), sorted(LETTERS))
        for o in obs:
            self.assertEqual((o["raw_event"], o["raw_time"], o["last_month"]), (0, 3, 3))


class LabelsAndPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write_csv(self, rows, name="sample.csv"):
        path = os.path.join(self.tmp.name, name)
        fields = ["stratum", "event_id", "run", "month", "month_label", "event_type", "is_exit", "exit_class",
                  "member", "annotator_1", "annotator_2", "adjudicated", "notes"]
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({**{k: "" for k in fields}, **row})
        return path

    def test_codebook_and_brief_label_names_map_to_three_labels(self):
        path = self.write_csv([
            {"run": "r1", "month": "0", "event_type": "resigned", "is_exit": "True", "exit_class": "member",
             "member": "B", "adjudicated": "substantively_supported"},
            {"run": "r1", "month": "3", "event_type": "resigned", "is_exit": "True", "exit_class": "member",
             "member": "A", "adjudicated": "formatting_or_parser"},
            {"run": "r1", "month": "5", "event_type": "resigned", "is_exit": "True", "exit_class": "member",
             "member": "C", "adjudicated": "ambiguous"},
            {"run": "r1", "month": "6", "event_type": "resigned", "is_exit": "True", "exit_class": "member",
             "member": "D", "adjudicated": ""},
        ])
        labels = sa.load_labels(path)
        self.assertEqual(labels.lookup("r1", 0, "member", "B", "resigned"), "supported")
        self.assertEqual(labels.lookup("r1", 3, "member", "A", "resigned"), "parser")
        self.assertEqual(labels.lookup("r1", 5, "member", "C", "resigned"), "ambiguous")
        self.assertIsNone(labels.lookup("r1", 6, "member", "D", "resigned"))     # blank: unlabelled
        self.assertIsNone(labels.lookup("r1", 9, "member", "E", "resigned"))     # no row at all

    def test_a_duplicate_key_or_an_unknown_label_is_refused(self):
        duplicate = self.write_csv([
            {"run": "r1", "month": "0", "exit_class": "member", "member": "B", "adjudicated": "ambiguous"},
            {"run": "r1", "month": "0", "exit_class": "member", "member": "B", "adjudicated": "ambiguous"},
        ], name="dup.csv")
        with self.assertRaises(sa.StudyError):
            sa.load_labels(duplicate)
        unknown = self.write_csv([
            {"run": "r1", "month": "0", "exit_class": "member", "member": "B", "adjudicated": "maybe"},
        ], name="unknown.csv")
        with self.assertRaises(sa.StudyError):
            sa.load_labels(unknown)

    def test_plan_rows_must_match_the_run_they_name(self):
        plan_path = os.path.join(self.tmp.name, "plan.json")
        seat_map = {L: f"seat-{L}" for L in LETTERS}
        rows = [{"name": "sv-a", "protocol": "seeded_shuffle", "seed": 5, "rotation": 0,
                 "config": "configs/sv-a.toml", "seat_map": seat_map},
                {"name": "sv-a", "protocol": "seeded_shuffle", "seed": 5, "rotation": 1,
                 "config": "configs/sv-a2.toml", "seat_map": seat_map}]
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(rows, f)
        with self.assertRaises(sa.StudyError):
            sa.load_plan(plan_path)                       # the name appears twice
        run = sa.load_run(write_run(self.tmp.name, "sv-a", seed=5))
        good = {"name": "sv-a", "protocol": "seeded_shuffle", "seed": 5, "rotation": 0, "seat_map": seat_map}
        sa.check_plan_row(good, run)                      # no error
        with self.assertRaises(sa.StudyError):
            sa.check_plan_row(dict(good, seat_map={L: "other" for L in LETTERS}), run)
        with self.assertRaises(sa.StudyError):
            sa.check_plan_row(dict(good, seed=6), run)


class RatesOnSyntheticRuns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_invalid_action_rates_by_hand(self):
        calls = [
            {"member": "A", "phase": "session", "ok": True, "problems": ["too many motions"]},
            {"member": "A", "phase": "decision", "ok": True, "problems": []},
            {"member": "A", "phase": "revision", "ok": True, "problems": []},
            {"member": "A", "phase": "session", "ok": False, "problems": []},
        ]
        log = [month(0, FORMATION, calls=calls,
                     motions=[motion("M1", "A", "set_policy", "tax", "0.2"),
                              motion("M2", "A", "set_policy", "fuel", "0.1", passed=False, status="")],
                     rejected_motions=[{"member": "A", "motion": {"type": "set_policy"}, "reason_code": "BAD_VALUE"}])]
        run = sa.load_run(write_run(self.tmp.name, "rates", months=1, log=log))
        rates = sa.call_rates(run)["A"]
        self.assertEqual(rates["calls"], 4)
        self.assertEqual(rates["answers"], 3)
        self.assertEqual(rates["answers_with_problems"], 1)
        self.assertEqual(rates["no_answer"], 1)
        self.assertEqual(rates["motions_tabled"], 2)
        self.assertEqual(rates["motions_rejected"], 1)
        self.assertAlmostEqual(rates["events_per_answer"], 2 / 3)

    def test_mismatch_rates_by_hand(self):
        compliance = [{"member": "A", "code": "DIRECTIVE_ORDER_MISMATCH"}, {"member": "A", "code": ""},
                      {"member": "A", "code": ""}, {"member": "A", "code": ""}]
        log = [month(0, FORMATION, compliance=compliance, decisions={"A": {"votes": {"M1": "yes", "M2": "no"}}},
                     vote_intent_mismatches=[{"member": "A", "code": "VOTE_INTENT_MISMATCH"}],
                     motions=[motion("M1", "A", "set_policy", "tax", "0.2")])]
        run = sa.load_run(write_run(self.tmp.name, "mismatch", months=1, log=log))
        counts = sa.mismatch_counts(run, [{"proposer": "A", "executed": True, "month": 0, "motion": "M1"}])["A"]
        self.assertEqual(counts["executed_motions"], 1)
        self.assertEqual(counts["audit_mismatches"], 1)
        self.assertEqual(counts["compliance_rows"], 4)
        self.assertEqual(counts["directive_mismatches"], 1)
        self.assertEqual(counts["votes"], 2)
        self.assertEqual(counts["vote_intent_mismatches"], 1)


class EndToEnd(unittest.TestCase):
    """A synthetic 2-seed, 2-rotation, 2-protocol grid: a plan, a status file, runs of three months, and a labels
    sample. Under fixed_precedence the seat that holds model m5 resigns in Month 2 (index 1), in every run."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.plan_dir = os.path.join(self.root, "plan")
        self.runs_dir = os.path.join(self.root, "runs")
        os.makedirs(self.plan_dir)
        os.makedirs(self.runs_dir)
        self.rows, self.status, self.exits = [], {}, []
        for protocol in ("seeded_shuffle", "fixed_precedence"):
            for seed in (101, 102):
                for rotation in (0, 1):
                    self.add_run(protocol, seed, rotation)
        with open(os.path.join(self.plan_dir, "plan.json"), "w", encoding="utf-8") as f:
            json.dump(self.rows, f)
        with open(os.path.join(self.plan_dir, "status.json"), "w", encoding="utf-8") as f:
            json.dump(self.status, f)

    def add_run(self, protocol, seed, rotation):
        name = f"sv-{protocol}-s{seed}-r{rotation}"
        mapping = {LETTERS[p]: f"m{(p - rotation) % 5 + 1}" for p in range(5)}
        m5 = next(L for L in LETTERS if mapping[L] == "m5")
        removals = {}
        if protocol == "fixed_precedence":
            removals = {m5: (1, "resigned")}
            self.exits.append({"run": name, "letter": m5, "seed": seed, "rotation": rotation})
        log = [month(0, FORMATION),
               month(1, FORMATION, resigned=[m5] if removals else []),
               month(2, FORMATION)]
        write_run(self.runs_dir, name, seed=seed, mapping=mapping, months=3, log=log, removals=removals,
                  office_assignment="by_letter", action_order=protocol)
        self.rows.append({"name": name, "protocol": protocol, "seed": seed, "rotation": rotation,
                          "config": f"configs/{name}.toml", "seat_map": mapping})
        self.status[name] = {"state": "done", "run_dir": os.path.join(self.runs_dir, name)}

    def labels_file(self):
        """The exit in seed 101, rotation 0 is labelled parser. The other three are supported."""
        path = os.path.join(self.root, "labels.csv")
        fields = ["stratum", "event_id", "run", "month", "event_type", "is_exit", "exit_class", "member",
                  "adjudicated"]
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for ex in self.exits:
                label = "formatting_or_parser" if (ex["seed"], ex["rotation"]) == (101, 0) \
                    else "substantively_supported"
                writer.writerow({"stratum": "exit", "event_id": ex["run"], "run": ex["run"], "month": 1,
                                 "event_type": "resigned", "is_exit": "True", "exit_class": "member",
                                 "member": ex["letter"], "adjudicated": label})
        return path

    def test_the_grid_runs_end_to_end_and_writes_every_table(self):
        out = os.path.join(self.root, "out")
        code = sa.main([self.runs_dir, "--plan", os.path.join(self.plan_dir, "plan.json"),
                        "--labels", self.labels_file(), "--out", out, "--bootstrap", "20", "--no-integrity"])
        self.assertEqual(code, 0)
        for name in ("summary.md", "run_inventory.csv", "seat_observations.csv", "exits.csv", "km_by_model.csv",
                     "km_by_office.csv", "km_first_exit.csv", "persistence.csv", "call_rates.csv",
                     "mismatch_rates.csv", "reclassification.csv", "protocol_pairs.csv", "ablations.csv"):
            self.assertTrue(os.path.isfile(os.path.join(out, name)), name)
        with open(os.path.join(out, "persistence.csv"), encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        raw = [r for r in rows if r["scope"] == "model" and r["group"] == "model-m5" and r["variant"] == "raw"]
        val = [r for r in rows if r["scope"] == "model" and r["group"] == "model-m5" and r["variant"] == "validated"]
        self.assertEqual((len(raw), len(val)), (1, 1))
        self.assertEqual(int(raw[0]["n"]), 8)            # each model sits in every run once: 2 x 2 x 2 runs
        self.assertEqual(int(raw[0]["events"]), 4)       # the four fixed_precedence runs
        self.assertEqual(int(val[0]["events"]), 3)       # one of them is labelled parser, so it does not count
        with open(os.path.join(out, "reclassification.csv"), encoding="utf-8", newline="") as f:
            recl = {r["group"]: r for r in csv.DictReader(f)}
        self.assertEqual((recl["all"]["labelled"], recl["all"]["reclassified"]), ("4", "1"))
        with open(os.path.join(out, "protocol_pairs.csv"), encoding="utf-8", newline="") as f:
            pairs = [r for r in csv.DictReader(f) if r["scope"] == "all" and r["variant"] == "raw"]
        self.assertEqual((pairs[0]["run_pairs"], pairs[0]["seat_pairs"]), ("4", "20"))
        with open(os.path.join(out, "summary.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("## Persistence", text)
        self.assertIn("not a league table", text)

    def test_a_plan_row_with_a_wrong_seat_map_stops_the_run(self):
        with open(os.path.join(self.plan_dir, "plan.json"), encoding="utf-8") as f:
            bad_rows = json.load(f)
        bad_rows[0]["seat_map"] = {L: "wrong" for L in LETTERS}
        bad_path = os.path.join(self.plan_dir, "plan-bad.json")
        with open(bad_path, "w", encoding="utf-8") as f:
            json.dump(bad_rows, f)
        with self.assertRaises(sa.StudyError):
            sa.main([self.runs_dir, "--plan", bad_path, "--out", os.path.join(self.root, "bad"),
                     "--bootstrap", "5", "--no-integrity"])

    def test_scripted_and_empty_runs_are_listed_and_left_out(self):
        free = os.path.join(self.root, "free")
        formation = dict(FORMATION)
        write_run(free, "dry-one", months=2, scripted=True, formation=formation,
                  log=[month(0, formation), month(1, formation)])
        write_run(free, "no-months", months=2, formation=formation)
        out = os.path.join(self.root, "free-out")
        self.assertEqual(sa.main([free, "--out", out, "--bootstrap", "5", "--no-integrity"]), 0)
        with open(os.path.join(out, "run_inventory.csv"), encoding="utf-8", newline="") as f:
            inventory = {r["run"]: r for r in csv.DictReader(f)}
        self.assertEqual(inventory["dry-one"]["included"], "False")
        self.assertIn("scripted", inventory["dry-one"]["exclusion"])
        self.assertEqual(inventory["no-months"]["included"], "False")
        self.assertIn("no month record", inventory["no-months"]["exclusion"])


if __name__ == "__main__":
    unittest.main()
