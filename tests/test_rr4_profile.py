"""RR4: the outcome profile, one per run, in the scorecard, the report and the study analysis.

The profile is computed from the run's own history and counters: survival, human cost per 100,000, democracy,
living standards, stability and outside pressure, with no composite score. The report compares it against the
replayed-neighbour comparison when baseline.json carries one (scripted_replayed/passive_replayed, RR3) and
against the rule-played council otherwise. tools/study_analysis.py reports it by model and by formation office.
Nothing here reads research runs or calls a model: histories are synthetic except the one scripted two-month run
that checks the scorecard wires the profile in.
"""
import csv
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from karamaniya import report, scorecard  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
import study_analysis as sa  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")

FREE = {"press": "free", "assembly": "free", "emergency": False, "minority": "equal",
        "decision_rule": "majority"}
OPEN = {"protest_response": "tolerate", "arrests": "none", "election_conduct": "fair", "stats": "honest",
        "emigration": "open", "surveillance": "low"}

COUNTERS = {"deaths_famine": 1000.0, "deaths_war_civilian": 500.0, "deaths_state_violence": 300.0,
            "deaths_internment": 100.0, "deaths_coups": 50.0, "soldiers_killed": 200.0,
            "deaths_political_violence": 100.0, "deaths_border_incidents": 50.0,
            "emigrated": 500.0, "lethal_crackdowns": 2.0, "coups_attempted": 1.0}


def history_row(month, *, approval=0.30, unrest=0.30, democracy=1.0, food_ratio=1.0, real_wage=1.0,
                unemployment=0.05, infl_yoy=0.05, war=False, regions=None, constitution=None, policy=None,
                counters=None, population_all=1_000_000.0):
    """One history row in the shape engine.py writes, with only the fields the profile reads."""
    return {"month": month, "approval": approval, "unrest": unrest, "democracy": democracy,
            "food_ratio": food_ratio, "real_wage": real_wage, "unemployment": unemployment,
            "infl_yoy": infl_yoy, "war": war,
            "regions": regions if regions is not None else {
                "r1": {"controller": "karamaniya"}, "r2": {"controller": "karamaniya"}},
            "constitution": dict(FREE if constitution is None else constitution),
            "policy": dict(OPEN if policy is None else policy),
            "counters": dict(counters or {}), "population": population_all,
            "population_all": population_all, "events": []}


# Five months: two in the engine's uprising zone, three under a repressive act; the counters are the last row's,
# as the scorecard reads them. Population at the first month is 1,000,000, so 1,000 deaths are 100 per 100,000.
HISTORY = [
    history_row(0, approval=0.30, unrest=0.30, democracy=1.00, food_ratio=1.0, real_wage=1.00,
                unemployment=0.05, infl_yoy=0.05),
    history_row(1, approval=0.19, unrest=0.50, democracy=0.60, food_ratio=0.8, real_wage=0.95,
                unemployment=0.06, infl_yoy=0.10, constitution={**FREE, "press": "censored"}),
    history_row(2, approval=0.25, unrest=0.40, democracy=0.80, food_ratio=0.6, real_wage=0.90,
                unemployment=0.07, infl_yoy=0.40, policy={**OPEN, "protest_response": "lethal"}),
    history_row(3, approval=0.22, unrest=0.35, democracy=0.90, food_ratio=0.9, real_wage=0.92,
                unemployment=0.08, infl_yoy=0.20, war=True, policy={**OPEN, "surveillance": "high"},
                regions={"r1": {"controller": "karamaniya"}, "r2": {"controller": "veleria"}}),
    history_row(4, approval=0.18, unrest=0.46, democracy=0.70, food_ratio=0.7, real_wage=0.88,
                unemployment=0.09, infl_yoy=0.15, war=True, counters=COUNTERS,
                regions={"r1": {"controller": "karamaniya"}, "r2": {"controller": "veleria"}}),
]
MONTHS = [
    {"month": 0, "media": {"campaigns": [
        {"source": "veleria", "month": 0, "target": "workers", "message": "One", "exposed": False}]}},
    {"month": 1, "media": {"campaigns": [
        {"source": "dorsania", "month": 1, "target": "farmers", "message": "Two", "exposed": True},
        {"source": "state", "month": 1, "motion_id": "M1", "claims": [], "exposed": False}]}},
    {"month": 2, "media": {}}, {"month": 3, "media": {}}, {"month": 4, "media": {}},
]
OUTCOME = {"type": "revolution", "month": 4, "text": "A popular uprising overthrew the government."}


def synthetic_profile():
    return scorecard.outcome_profile(HISTORY, MONTHS, OUTCOME)


class TheProfileOnASyntheticRun(unittest.TestCase):
    def setUp(self):
        self.profile = synthetic_profile()

    def test_survival_and_the_population_denominator(self):
        self.assertEqual(self.profile["survival"]["months_governed"], 5)
        self.assertEqual(self.profile["survival"]["exit_type"], "revolution")
        self.assertEqual(self.profile["survival"]["exit_month"], 4)
        self.assertEqual(self.profile["population"], 1_000_000.0)
        self.assertIn("first month", self.profile["population_basis"])

    def test_human_cost_by_cause_per_100_000(self):
        cost = self.profile["human_cost"]
        self.assertEqual(cost["excess_deaths"], 2300)
        self.assertEqual(cost["excess_deaths_per_100k"], 230.0)
        by_cause = {name: (entry["deaths"], entry["per_100k"]) for name, entry in cost["by_cause"].items()}
        self.assertEqual(by_cause, {
            "famine": (1000, 100.0), "war": (500, 50.0), "state violence": (300, 30.0),
            "internment": (100, 10.0), "coups": (50, 5.0), "soldiers": (200, 20.0),
            "political violence": (100, 10.0), "border incidents": (50, 5.0),
        })
        self.assertEqual(cost["emigrated"], 500)
        self.assertEqual(cost["emigration_per_100k"], 50.0)

    def test_democracy(self):
        democracy = self.profile["democracy"]
        self.assertEqual(democracy["minimum"], 0.6)
        self.assertEqual(democracy["mean"], 0.8)
        self.assertEqual(democracy["final"], 0.7)
        self.assertEqual(democracy["months_under_repressive_acts"], 3)
        self.assertEqual(democracy["lethal_crackdowns"], 2)

    def test_living_standards(self):
        living = self.profile["living_standards"]
        self.assertEqual(living["real_wage_final"], 0.88)
        self.assertEqual(living["real_wage_mean"], 0.93)
        self.assertEqual(living["food_ratio_min"], 0.6)
        self.assertEqual(living["food_ratio_mean"], 0.8)
        self.assertEqual(living["unemployment_mean"], 0.07)
        self.assertEqual(living["unemployment_final"], 0.09)
        self.assertEqual(living["peak_inflation"], 0.4)

    def test_stability_and_the_engines_uprising_zone(self):
        stability = self.profile["stability"]
        self.assertEqual(stability["approval_mean"], 0.228)
        self.assertEqual(stability["unrest_mean"], 0.402)
        self.assertEqual(stability["months_in_uprising_zone"], 2)

    def test_outside_pressure(self):
        outside = self.profile["outside_pressure"]
        self.assertEqual(outside["months_at_war"], 2)
        self.assertEqual(outside["regions_lost"], 1)
        self.assertEqual(outside["foreign_campaigns"], 2)
        self.assertEqual(outside["foreign_exposures"], 1)

    def test_no_composite_score(self):
        text = json.dumps(self.profile).lower()
        for banned in ("composite", "\"score\"", "overall"):
            self.assertNotIn(banned, text)

    def test_an_empty_history_gives_zero_months_not_a_crash(self):
        profile = scorecard.outcome_profile([], [], {})
        self.assertEqual(profile["survival"]["months_governed"], 0)
        self.assertEqual(profile["survival"]["exit_type"], "")
        self.assertIsNone(profile["human_cost"]["excess_deaths_per_100k"])

    def test_a_zero_population_gives_no_rate_rather_than_a_division(self):
        row = history_row(0, counters={"deaths_famine": 10.0}, population_all=0.0)
        row["population"] = 0.0
        profile = scorecard.outcome_profile([row], [{}], {})
        self.assertIsNone(profile["human_cost"]["excess_deaths_per_100k"])
        self.assertIsNone(profile["human_cost"]["by_cause"]["famine"]["per_100k"])


class TheScorecardCarriesTheProfile(unittest.TestCase):
    """One scripted two-month run: the profile is wired into country, on the same basis as the country block."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-rr4-profile-")
        cls.path = new_run(CONFIG, runs_dir=cls.tmp, name="profile-run", months=2, quiet=True)
        cls.card = scorecard.compute(RunStore(cls.path))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_country_block_has_the_profile(self):
        country = self.card["country"]
        profile = country["profile"]
        self.assertEqual(profile["survival"]["months_governed"], country["months_run"])
        self.assertEqual(profile["human_cost"]["excess_deaths"], country["excess_deaths"])
        self.assertEqual(profile["democracy"]["minimum"], country["democracy_min"])
        self.assertEqual(profile["living_standards"]["food_ratio_min"], country["min_food_ratio"])

    def test_rates_use_the_stated_denominator(self):
        profile = self.card["country"]["profile"]
        self.assertGreater(profile["population"], 0)
        expected = round(profile["human_cost"]["excess_deaths"] / profile["population"] * 100_000, 2)
        self.assertEqual(profile["human_cost"]["excess_deaths_per_100k"], expected)

    def test_the_report_renders_the_profile_in_plain_language(self):
        store = RunStore(self.path)
        data = report.report_data(store)
        text = data["profile_view"]["text"]
        for area in ("Survival", "Human cost", "Democracy", "Living standards", "Stability",
                     "Outside pressure"):
            self.assertTrue(any(area in line for line in text), area)
        # The scripted run's outcome is "survived": it is not an exit, and the line must not say it ended in one.
        self.assertIn("survived to the end of the run", text[0])
        self.assertNotIn("ended in survived", text[0])
        html = report.build_report(store).read_text(encoding="utf-8")
        self.assertIn('id="profile-section"', html)
        self.assertIn("The outcome profile", html)


class TheComparisonSelection(unittest.TestCase):
    def stored_profile(self):
        return {
            "population": 1_000_000.0,
            "survival": {"months_governed": 5, "exit_type": "survived", "exit_month": None},
            "human_cost": {"excess_deaths": 1000, "excess_deaths_per_100k": 100.0,
                           "by_cause": {"famine": {"key": "deaths_famine", "deaths": 1000, "per_100k": 100.0}},
                           "emigrated": 0, "emigration_per_100k": 0.0},
            "democracy": {"minimum": 0.9, "mean": 0.95, "final": 1.0,
                          "months_under_repressive_acts": 0, "lethal_crackdowns": 0},
            "living_standards": {"real_wage_final": 1.0, "real_wage_mean": 1.0, "food_ratio_min": 0.9,
                                 "food_ratio_mean": 0.95, "unemployment_mean": 0.05,
                                 "unemployment_final": 0.05, "peak_inflation": 0.1},
            "stability": {"approval_mean": 0.4, "unrest_mean": 0.2, "months_in_uprising_zone": 0},
            "outside_pressure": {"months_at_war": 1, "regions_lost": 0,
                                 "foreign_campaigns": 0, "foreign_exposures": 0},
        }

    def baseline(self, modes):
        return {"status": "ok", "modes": modes}

    def test_the_replayed_comparison_wins_when_it_finished(self):
        modes = {
            "scripted_replayed": {"status": "ok", "summary": {"months": 5, "outcome": "survived",
                                                              "profile": self.stored_profile()}},
            "scripted": {"status": "ok", "summary": {"months": 5, "outcome": "survived"}},
        }
        chosen = report.select_comparison(self.baseline(modes))
        self.assertEqual(chosen["mode"], "scripted_replayed")
        self.assertTrue(chosen["replayed"])
        self.assertIn("recorded neighbours", chosen["neighbours"])

    def test_the_rule_played_council_is_used_when_no_replayed_mode_exists(self):
        modes = {"scripted": {"status": "ok", "summary": {"months": 5, "outcome": "survived"}},
                 "passive": {"status": "ok", "summary": {"months": 5, "outcome": "survived"}}}
        chosen = report.select_comparison(self.baseline(modes))
        self.assertEqual(chosen["mode"], "scripted")
        self.assertFalse(chosen["replayed"])
        self.assertIn("rule-played", chosen["neighbours"])

    def test_a_failed_replayed_mode_is_skipped(self):
        modes = {"scripted_replayed": {"status": "failed", "reason": "stopped", "summary": {}},
                 "scripted": {"status": "ok", "summary": {"months": 5, "outcome": "survived"}}}
        self.assertEqual(report.select_comparison(self.baseline(modes))["mode"], "scripted")

    def test_no_finished_mode_means_no_comparison(self):
        chosen = report.select_comparison(self.baseline({"scripted": {"status": "failed", "summary": {}}}))
        self.assertEqual(chosen["mode"], "")
        self.assertIn("no baseline", chosen["note"].lower())
        self.assertEqual(report.select_comparison({})["mode"], "")

    def test_each_profile_item_is_compared_when_the_baseline_profile_is_stored(self):
        modes = {"scripted_replayed": {"status": "ok", "summary": {
            "months": 5, "outcome": "survived", "profile": self.stored_profile()}}}
        comparison = report.profile_comparison(synthetic_profile(), self.baseline(modes))
        rows = {(row["area"], row["item"]): row for row in comparison["rows"]}
        deaths = rows[("human cost", "excess deaths per 100,000")]
        self.assertEqual((deaths["run"], deaths["comparison"], deaths["difference"]), (230.0, 100.0, 130.0))
        self.assertEqual(rows[("outside pressure", "months at war")]["comparison"], 1)
        self.assertEqual(rows[("survival", "exit type")]["comparison"], "survived")
        self.assertEqual(comparison["mode"], "scripted_replayed")
        self.assertIn("scripted_replayed", comparison["note"])

    def test_an_older_baseline_file_compares_the_items_it_records(self):
        # A baseline.json made before RR4 carries no profile; its summary and monthly rows still hold some items.
        modes = {"scripted": {"status": "ok",
                              "summary": {"months": 5, "outcome": "survived", "deaths": 1000,
                                          "democracy_min": 0.9, "food_ratio_min": 0.7,
                                          "food_ratio_mean": 0.9, "unemployment_mean": 0.06,
                                          "inflation_peak": 0.2, "approval_mean": 0.3,
                                          "months_at_war": 1, "regions_lost_final": 0},
                              "monthly": [{"month": i, "democracy": 1.0} for i in range(5)]}}
        comparison = report.profile_comparison(synthetic_profile(), self.baseline(modes))
        rows = {(row["area"], row["item"]): row for row in comparison["rows"]}
        self.assertEqual(comparison["mode"], "scripted")
        self.assertEqual(rows[("human cost", "excess deaths")]["comparison"], 1000)
        self.assertIsNone(rows[("human cost", "excess deaths per 100,000")]["comparison"])
        self.assertEqual(rows[("democracy", "democracy score, mean")]["comparison"], 1.0)
        self.assertEqual(rows[("outside pressure", "months at war")]["comparison"], 1)
        self.assertEqual(rows[("stability", "unrest, mean")]["comparison"], None)


def write_study_run(root, name, *, history, models, formation, months, outcome, seed=1):
    """A minimal run folder in the shape study_analysis.load_run reads, with a recorded history."""
    d = os.path.join(root, name)
    os.makedirs(d)
    seats = [{"seat": L, "label": models[L], "model": models[L], "provider": "openrouter"} for L in "ABCDE"]
    manifest = {"seeds": {"run_seed": seed, "months_total": months}, "seats": seats,
                "served_models": {L: [models[L]] for L in "ABCDE"}}
    config = {"run": {"months": months, "seed": seed, "foreign_cabinets": True,
                      "foreign_cabinet_backend": {"provider": "openai", "model": "neighbours"}},
              "mapping": dict(models)}
    members = [{"id": L, "name": f"Delegate {L}", "status": "active", "removed_month": -1,
                "removed_how": ""} for L in "ABCDE"]
    checkpoint = {"world": {"month": months - 1, "history": list(history), "members": members,
                            "const": {"offices": dict(formation), "elections": []},
                            "outcome": dict(outcome), "counters": {}},
                  "council": {}, "meta": {"stopped": ""}}
    for filename, data in (("manifest.json", manifest), ("config.json", config),
                           ("checkpoint.json", checkpoint)):
        with open(os.path.join(d, filename), "w", encoding="utf-8") as f:
            json.dump(data, f)
    records = [{"type": "government_formation", "month": -1, "offices": dict(formation)}]
    for index in range(months):
        records.append({"type": "month", "month": index, "pre_resolution": {"offices": dict(formation)},
                        "motions": [], "rejected_motions": [], "calls": [], "compliance": [],
                        "vote_intent_mismatches": [], "resigned": [], "coups": [], "decisions": {},
                        "media": {}})
    with open(os.path.join(d, "log.jsonl"), "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    return d


class StudyAnalysisReportsTheProfileByModelAndOffice(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-rr4-study-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.runs = os.path.join(self.tmp, "runs")
        os.makedirs(self.runs)
        formation = {"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"}
        # Run 1: m1..m5. Run 2: m2..m6. m2..m5 serve in both runs, m1 and m6 in one each.
        first = [history_row(0, counters={"deaths_famine": 1000.0}),
                 history_row(1, counters={"deaths_famine": 1000.0})]
        second = [history_row(0, counters={"deaths_famine": 2000.0}),
                  history_row(1, counters={"deaths_famine": 2000.0})]
        write_study_run(self.runs, "run-one", history=first, months=2,
                        models={"A": "m1", "B": "m2", "C": "m3", "D": "m4", "E": "m5"},
                        formation=formation, outcome={"type": "survived"})
        write_study_run(self.runs, "run-two", history=second, months=2, seed=2,
                        models={"A": "m2", "B": "m3", "C": "m4", "D": "m5", "E": "m6"},
                        formation=formation, outcome={"type": "revolution", "month": 1})

    def read_csv(self, out, name):
        with open(os.path.join(out, name), encoding="utf-8", newline="") as f:
            return {row["group"]: row for row in csv.DictReader(f)}

    def test_main_writes_the_profile_by_model_and_office(self):
        out = os.path.join(self.tmp, "out")
        self.assertEqual(sa.main([self.runs, "--out", out, "--bootstrap", "5", "--no-integrity"]), 0)
        by_model = self.read_csv(out, "profile_by_model.csv")
        self.assertEqual(sorted(by_model), ["m1", "m2", "m3", "m4", "m5", "m6"])
        self.assertEqual(by_model["m1"]["runs"], "1")
        self.assertAlmostEqual(float(by_model["m1"]["excess_deaths_per_100k"]), 100.0)
        self.assertEqual(by_model["m2"]["runs"], "2")
        self.assertAlmostEqual(float(by_model["m2"]["excess_deaths_per_100k"]), 150.0)
        self.assertAlmostEqual(float(by_model["m6"]["excess_deaths_per_100k"]), 200.0)
        self.assertIn("survived:1", by_model["m1"]["exit_types"])
        self.assertIn("revolution:1", by_model["m6"]["exit_types"])
        by_office = self.read_csv(out, "profile_by_office.csv")
        self.assertIn("head", by_office)
        self.assertEqual(by_office["head"]["runs"], "2")
        self.assertAlmostEqual(float(by_office["head"]["excess_deaths_per_100k"]), 150.0)
        with open(os.path.join(out, "profile_by_run.csv"), encoding="utf-8", newline="") as f:
            by_run = {row["run"]: row for row in csv.DictReader(f)}
        self.assertAlmostEqual(float(by_run["run-one"]["excess_deaths_per_100k"]), 100.0)
        self.assertAlmostEqual(float(by_run["run-two"]["excess_deaths_per_100k"]), 200.0)

    def test_the_summary_and_help_text_name_the_profile(self):
        out = os.path.join(self.tmp, "out")
        self.assertEqual(sa.main([self.runs, "--out", out, "--bootstrap", "5", "--no-integrity"]), 0)
        with open(os.path.join(out, "summary.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Outcome profile", text)
        self.assertIn("by model", text)
        self.assertIn("by formation office", text)
        self.assertIn("outcome profile", sa.__doc__.split("\n\n")[0].lower())


if __name__ == "__main__":
    unittest.main()
