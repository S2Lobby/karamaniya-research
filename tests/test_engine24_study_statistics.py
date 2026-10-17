"""Wave 3, workstream F: the plain-SVG survival writer and the study's secondary measures.

Every run folder here is written into a temporary directory. Nothing reads research\\runs and no model is called.
The hand values follow the formulas written in docs/STATISTICS.md: the opening position is the engine's
analytics.initial_stance read of `pre_positions`, the response position is the revision round's `stances`, and the
debate measure compares response-round opposition with the final ballots.
"""
import csv
import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import study_analysis as sa  # noqa: E402

LETTERS = "ABCDE"
FORMATION = {"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"}
SVG_NS = "{http://www.w3.org/2000/svg}"


def write_run(root, name, *, seed=1, mapping=None, months=1, formation=None, log=(), removals=None, outcome=None):
    """A minimal run folder in the shape the engine writes."""
    mapping = mapping or {L: f"seat-{L}" for L in LETTERS}
    removals = removals or {}
    formation = formation or dict(FORMATION)
    d = os.path.join(root, name)
    os.makedirs(d)
    seats = [{"seat": L, "label": mapping[L], "model": f"model-{mapping[L]}", "provider": "openrouter"}
             for L in LETTERS]
    run = {"months": months, "seed": seed}
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
                            "const": {"offices": dict(formation), "elections": []},
                            "outcome": outcome or {}},
                  "council": {}, "meta": {"stopped": ""}}
    config = {"run": run, "mapping": dict(mapping),
              "seats": [{"label": mapping[L], "provider": "openrouter"} for L in LETTERS]}
    for name_, data in (("manifest.json", manifest), ("config.json", config), ("checkpoint.json", checkpoint)):
        with open(os.path.join(d, name_), "w", encoding="utf-8") as f:
            json.dump(data, f)
    records = [{"type": "government_formation", "month": -1, "offices": dict(formation)}] + list(log)
    with open(os.path.join(d, "log.jsonl"), "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    return d


def month(index, offices, **fields):
    rec = {"type": "month", "month": index, "pre_resolution": {"offices": dict(offices)}, "motions": [],
           "rejected_motions": [], "calls": [], "compliance": [], "vote_intent_mismatches": [], "resigned": [],
           "coups": [], "decisions": {}, "pre_positions": {}, "revisions": {}}
    rec.update(fields)
    return rec


def motion(mid, proposer, mtype, subject, value="", passed=True, status="PASSED", votes=None,
           eligible=None, withdrawn=False):
    return {"id": mid, "proposer": proposer, "type": mtype, "subject": subject, "value": value,
            "passed": passed, "status": status, "votes": dict(votes or {}),
            "eligible_voters": list(eligible or LETTERS), "withdrawn": withdrawn}


class SvgWriter(unittest.TestCase):
    def test_km_path_is_a_hand_computed_step_curve(self):
        # Durations 2, 3, 3, 5, 6 with exits at 2, 3 and 5 (the hand example of the existing tests):
        # S = 1 -> 0.8 at 2 -> 0.6 at 3 -> 0.3 at 5, carried to 6. The map is x = 10 + 10 t, y = 100 - 100 S.
        steps = [(2.0, 0.8), (3.0, 0.6), (5.0, 0.3)]
        path = sa.km_path(steps, 6.0, lambda t: 10 + 10 * t, lambda s: 100 - 100 * s)
        self.assertEqual(path,
                         "M 10.00,0.00 L 30.00,0.00 L 30.00,20.00 L 40.00,20.00 L 40.00,40.00 "
                         "L 60.00,40.00 L 60.00,70.00 L 70.00,70.00")

    def test_svg_is_well_formed_escapes_labels_and_draws_one_curve_per_group(self):
        series = [
            {"label": "m1 & co", "n": 3, "durations": [2, 4, 4], "events": [1, 0, 0]},
            {"label": "m2 <fast>", "n": 2, "durations": [1, 3], "events": [1, 1]},
        ]
        svg = sa.survival_svg(series, title="Time to exit by model", subtitle="raw labels", x_max=4)
        root = ET.fromstring(svg)                     # well-formed XML, or this raises
        self.assertEqual(root.tag, SVG_NS + "svg")
        text = "".join(root.itertext())
        self.assertIn("m1 & co", text)
        self.assertIn("m2 <fast>", text)
        self.assertIn("&amp;", svg)                   # the label was escaped in the source
        self.assertIn("&lt;fast&gt;", svg)
        self.assertEqual(svg.count('class="km-curve"'), 2)
        self.assertNotIn("None", text)
        self.assertNotIn("nan", text.lower())

    def test_svg_caps_the_number_of_series_and_says_how_many_are_omitted(self):
        series = [{"label": f"model-{i}", "n": i + 1, "durations": [2], "events": [1]} for i in range(10)]
        svg = sa.survival_svg(series, title="t", subtitle="s", x_max=2)
        self.assertEqual(svg.count('class="km-curve"'), sa.SVG_MAX_GROUPS)
        self.assertIn("2 more group", "".join(ET.fromstring(svg).itertext()))

    def test_svg_with_no_observations_still_renders(self):
        svg = sa.survival_svg([], title="t", subtitle="s", x_max=1)
        ET.fromstring(svg)
        self.assertIn("No observations", "".join(ET.fromstring(svg).itertext()))


class PositionChange(unittest.TestCase):
    """S1: finally, did the delegate vote the way it opened? Hand-computed on one month."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        pre = {
            "A": {"would_support": "raise the tax rate"},
            "B": {"would_oppose": "raise the tax rate"},
            "C": {"would_support": "raise the tax rate"},
            "D": {"would_oppose": "raise the tax rate"},
            "E": {"would_support": "raise the tax rate"},
        }
        revisions = {
            "B": {"stances": {"M1": "support"}},
            "C": {"stances": {"M1": "oppose"}},
            "E": {"stances": {"M1": "oppose"}},
        }
        motions = [
            motion("M1", "A", "set_policy", "tax", "0.20",
                   votes={"A": "yes", "B": "no", "C": "no", "D": "no", "E": "yes"}),
            motion("M2", "D", "set_policy", "farm_support", "0.05", passed=False, status="DEFEATED",
                   votes={"A": "yes", "B": "yes", "C": "yes", "D": "yes", "E": "no"}),
        ]
        log = [month(0, FORMATION, pre_positions=pre, revisions=revisions, motions=motions)]
        self.run = sa.load_run(write_run(self.tmp.name, "s1", months=1, log=log))

    def row(self, member, mid="M1"):
        return next(r for r in sa.position_change_rows(self.run)
                    if r["member"] == member and r["motion_id"] == mid)

    def test_opening_response_and_final_vote_by_hand(self):
        a, b, c, d, e = (self.row(L) for L in "ABCDE")
        self.assertEqual((a["opening"], a["opening_basis"], a["counted_opening"]), ("support", "proposer", False))
        self.assertEqual((b["opening"], b["opening_basis"], b["counted_opening"]), ("oppose", "private_position", True))
        self.assertFalse(b["changed_opening_to_final"])          # no -> no
        self.assertTrue(c["changed_opening_to_final"])           # yes -> no
        self.assertFalse(d["changed_opening_to_final"])          # no -> no
        self.assertFalse(e["changed_opening_to_final"])          # yes -> yes
        self.assertEqual((b["response"], b["changed_response_to_final"]), ("yes", True))
        self.assertEqual((c["response"], c["changed_response_to_final"]), ("no", False))
        self.assertEqual((e["response"], e["changed_response_to_final"]), ("no", True))
        self.assertEqual((d["response"], d["counted_response"]), ("", False))

    def test_rates_use_the_documented_denominators(self):
        rows = {r["group"]: r for r in sa.position_change_rates([self.run])}
        row = rows["model-seat-C"]
        self.assertEqual((row["seats"], row["opening_known"], row["opening_changes"]), (1, 1, 1))
        self.assertEqual((row["response_known"], row["response_changes"]), (1, 0))
        self.assertAlmostEqual(row["opening_share"], 1.0)
        self.assertAlmostEqual(row["response_share"], 0.0)
        self.assertIn("office: interior", rows)
        self.assertEqual(row["pairs"], 2)                        # both motions reached a vote

    def test_conditional_and_abstaining_final_votes_are_not_changes(self):
        pre = {"A": {"would_support": "raise the tax rate"}, "B": {"would_support": "raise the tax rate"}}
        revisions = {"A": {"stances": {"M9": "oppose"}}, "B": {"stances": {"M9": "conditional"}}}
        motions = [motion("M9", "C", "set_policy", "tax", "0.2",
                          votes={"A": "abstain", "B": "no", "C": "yes", "D": "yes", "E": "yes"})]
        run = sa.load_run(write_run(self.tmp.name, "s1b", months=1,
                                    log=[month(0, FORMATION, pre_positions=pre, revisions=revisions,
                                               motions=motions)]))
        rows = {(r["member"], r["motion_id"]): r for r in sa.position_change_rows(run)}
        self.assertFalse(rows[("A", "M9")]["counted_opening"])    # abstention is not a yes/no final vote
        self.assertFalse(rows[("A", "M9")]["counted_response"])
        self.assertFalse(rows[("B", "M9")]["counted_response"])   # a conditional stance is not a change
        self.assertFalse(rows[("B", "M9")]["changed_response_to_final"])

    def test_a_tabled_competing_motion_is_the_strongest_opening_position(self):
        # D tabled a rival tax motion in the same family; its opening on M1 is support even though its private
        # position text is silent about tax. The engine's structured rule says so.
        pre = {"D": {}}
        revisions = {}
        motions = [motion("M1", "A", "set_policy", "tax", "0.20", votes={"A": "yes", "D": "no"}),
                   motion("M2", "D", "set_policy", "tax", "0.05", passed=False, status="DEFEATED",
                          votes={"A": "yes", "D": "yes"})]
        run = sa.load_run(write_run(self.tmp.name, "s1c", months=1,
                                    log=[month(0, FORMATION, pre_positions=pre, revisions=revisions,
                                               motions=motions)]))
        d = next(r for r in sa.position_change_rows(run) if r["member"] == "D" and r["motion_id"] == "M1")
        self.assertEqual((d["opening"], d["opening_basis"]), ("support", "tabled_motion"))
        self.assertTrue(d["changed_opening_to_final"])            # yes -> no


class DebateDisagreement(unittest.TestCase):
    """S2: response-round opposition against the final ballots, per motion family."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def make(self, name, motions, revisions):
        return sa.load_run(write_run(self.tmp.name, name, months=1,
                                     log=[month(0, FORMATION, motions=motions, revisions=revisions)]))

    def test_debate_rows_by_hand(self):
        motions = [motion("M1", "A", "set_policy", "tax", "0.20",
                          votes={"A": "yes", "B": "no", "C": "no", "D": "no", "E": "yes"}),
                   motion("M2", "D", "set_policy", "farm_support", "0.05", passed=False, status="DEFEATED",
                          votes={"A": "yes", "B": "yes", "C": "yes", "D": "yes", "E": "no"})]
        revisions = {"B": {"stances": {"M1": "support"}},
                     "C": {"stances": {"M1": "oppose"}},
                     "E": {"stances": {"M1": "oppose", "M2": "oppose"}},
                     "D": {"stances": {"M2": "oppose"}}}
        run = self.make("s2", motions, revisions)
        rows = {r["family"]: r for r in sa.debate_rows(run)}
        tax, farm = rows["set_policy:tax"], rows["set_policy:farm_support"]
        self.assertEqual((tax["response_opposition"], tax["competing_alternatives"]), (2, 1))
        self.assertEqual((tax["yes"], tax["no"], tax["abstain"], tax["ballots"]), (2, 3, 0, 5))
        self.assertEqual((tax["final_dissent"], tax["gap"]), (3, -1))
        self.assertEqual((tax["divergence_score"], tax["divergence_level"]), (2, "LOW"))
        self.assertEqual((farm["response_opposition"], farm["final_dissent"], farm["gap"]), (2, 1, 1))

    def test_a_contested_withdrawal_counts_in_the_divergence_score(self):
        motions = [motion("M1", "A", "set_policy", "tax", "0.20",
                          votes={"A": "yes", "B": "yes", "C": "yes", "D": "no", "E": "yes"}),
                   motion("M2", "D", "set_policy", "tax", "0.05", passed=False, status="WITHDRAWN",
                          votes={}, withdrawn=True)]
        revisions = {"D": {"stances": {"M2": "oppose"}, "withdrawn": ["M2"]}}
        run = self.make("s2w", motions, revisions)
        row = next(r for r in sa.debate_rows(run) if r["family"] == "set_policy:tax")
        self.assertEqual((row["competing_alternatives"], row["contested_withdrawals"]), (2, 1))
        self.assertEqual(row["response_opposition"], 1)
        # 2 for a live contest + 1 for the opposing stance + 2 for the contested withdrawal = 5, MODERATE.
        self.assertEqual((row["divergence_score"], row["divergence_level"]), (5, "MODERATE"))
        self.assertEqual((row["ballots"], row["final_dissent"], row["gap"]), (5, 1, 0))

    def test_amendment_families_follow_the_engines_narrow_rule(self):
        # Two procurement amendments share enough content and anchors to be one family; a police amendment does not.
        t1 = "Open procurement contracts to independent audit and publish every award above the threshold."
        t2 = "Open procurement contracts to independent audit and publish every award above the threshold, with penalties."
        t3 = "Let the police complaints office investigate misconduct and report quarterly to the Assembly."
        rec = {"motions": [{"id": "M1", "type": "amend", "subject": "", "text": t1},
                           {"id": "M2", "type": "amend", "subject": "", "text": t2},
                           {"id": "M3", "type": "amend", "subject": "", "text": t3}]}
        fams = sa.motion_families(rec)
        self.assertEqual(fams["M1"], fams["M2"])
        self.assertNotEqual(fams["M1"], fams["M3"])


class VoteIntentDiagnostic(unittest.TestCase):
    """The reviewer dropped the vote-mismatch flag from the paper's measures; it stays a diagnostic."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_output_separates_the_diagnostic_from_the_measures(self):
        log = [month(0, FORMATION,
                     motions=[motion("M1", "A", "set_policy", "tax", "0.2")],
                     decisions={"A": {"votes": {"M1": "yes", "M2": "no"}}},
                     compliance=[{"member": "A", "code": "DIRECTIVE_ORDER_MISMATCH"}],
                     vote_intent_mismatches=[{"member": "A", "code": "VOTE_INTENT_MISMATCH", "motion": "M1"}])]
        run_dir = write_run(self.tmp.name, "diag", months=1, log=log)
        out = os.path.join(self.tmp.name, "out")
        self.assertEqual(sa.main([run_dir, "--out", out, "--bootstrap", "5", "--no-integrity"]), 0)
        with open(os.path.join(out, "mismatch_rates.csv"), encoding="utf-8", newline="") as f:
            fields = csv.DictReader(f).fieldnames
        self.assertNotIn("votes", fields)
        self.assertNotIn("vote_intent_mismatches", fields)
        self.assertIn("directive_mismatches", fields)
        with open(os.path.join(out, "vote_intent_diagnostic.csv"), encoding="utf-8", newline="") as f:
            rows = {r["group"]: r for r in csv.DictReader(f)}
        row = rows["model-seat-A"]
        self.assertEqual((row["votes"], row["vote_intent_mismatches"]), ("2", "1"))
        self.assertAlmostEqual(float(row["vote_intent_share"]), 0.5)
        with open(os.path.join(out, "summary.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Diagnostic, not a measure", text)
        self.assertIn("Two separate rates", text)
        self.assertNotIn("Three separate rates", text)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_main_writes_svgs_and_secondary_measures(self):
        pre = {"B": {"would_oppose": "raise the tax rate"}, "C": {"would_support": "raise the tax rate"}}
        revisions = {"B": {"stances": {"M1": "support"}}, "C": {"stances": {"M1": "oppose"}}}
        motions = [motion("M1", "A", "set_policy", "tax", "0.20",
                          votes={"A": "yes", "B": "no", "C": "no", "D": "no", "E": "yes"})]
        log = [month(0, FORMATION, pre_positions=pre, revisions=revisions, motions=motions,
                     resigned=["B"]),
               month(1, FORMATION)]
        run_dir = write_run(self.tmp.name, "e2e", months=2, log=log, removals={"B": (0, "resigned")})
        out = os.path.join(self.tmp.name, "out")
        self.assertEqual(sa.main([run_dir, "--out", out, "--bootstrap", "5", "--no-integrity"]), 0)
        for name in ("position_changes.csv", "position_change_rates.csv", "debate_disagreement.csv",
                     "debate_by_family.csv", "km_by_model.svg", "km_by_office.svg", "km_first_exit.svg"):
            self.assertTrue(os.path.isfile(os.path.join(out, name)), name)
        for name in ("km_by_model.svg", "km_by_office.svg", "km_first_exit.svg"):
            with open(os.path.join(out, name), encoding="utf-8") as f:
                root = ET.fromstring(f.read())
            self.assertEqual(root.tag, SVG_NS + "svg")
        with open(os.path.join(out, "km_by_model.svg"), encoding="utf-8") as f:
            self.assertIn('class="km-curve"', f.read())
        with open(os.path.join(out, "debate_by_family.csv"), encoding="utf-8", newline="") as f:
            families = {r["family"]: r for r in csv.DictReader(f)}
        self.assertEqual(families["set_policy:tax"]["response_opposition"], "1")
        with open(os.path.join(out, "summary.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Secondary measure S1", text)
        self.assertIn("Secondary measure S2", text)


if __name__ == "__main__":
    unittest.main()
