"""Wave A W6: the arms (harness, referee effects, referee backend, knockout), the study grid's arms,
the harness report and the referee audit.

The arms are run options: `harness` ("menu" | "language" | "open"), `referee_effects` ("applied" |
"zeroed"), a seat-like `referee_backend` (required under "open", never one of the council's seats)
and `knockout` ({office, month}, absent by default). This module tests their validation, how the
runner carries them, what the manifest records, how the study grid plans them and their knockout
twins, the report's metrics on synthetic run folders, the audit's seeded sample and agreement
statistics, and the two tool integration points (replay of the referee, awareness leaving it out).

No model is called: the runner tests use the scripted seats and the scripted referee.
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import awareness_scan  # noqa: E402
import harness_report  # noqa: E402
import referee_audit  # noqa: E402
import replay_run  # noqa: E402
import study_grid  # noqa: E402
from karamaniya import actions, manifest, referee  # noqa: E402
from karamaniya.backends.replay import ReplayBackend  # noqa: E402
from karamaniya.config import RUN_DEFAULTS, load_config, normalize_config  # noqa: E402
from karamaniya.runner import apply_run_options, new_run  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

CONFIG = str(ROOT / "council.scripted.toml")


def seat(provider="openai", model="gpt-x", label="seat-one", **extra) -> dict:
    return {"provider": provider, "model": model, "label": label, **extra}


def cfg(run=None, seats=None) -> dict:
    return normalize_config({"run": dict(run or {}), "seat": seats or [seat()]})


class ConfigDefaultsTests(unittest.TestCase):
    def test_the_arms_default_to_engine_29_behaviour(self):
        run = normalize_config({"seat": [seat()]})["run"]
        self.assertEqual(run["harness"], "menu")
        self.assertEqual(run["referee_effects"], "applied")
        self.assertNotIn("referee_backend", run)
        self.assertNotIn("knockout", run)
        self.assertEqual(actions.harness_of(new_world(1)), "menu")

    def test_a_bad_harness_is_refused_in_words(self):
        with self.assertRaisesRegex(ValueError, "harness"):
            cfg({"harness": "freeform"})

    def test_a_bad_referee_effects_value_is_refused_in_words(self):
        with self.assertRaisesRegex(ValueError, "referee_effects"):
            cfg({"referee_effects": "sometimes"})

    def test_a_bad_knockout_is_refused_in_words(self):
        for option, words in (({"office": "king", "month": 12}, "office"),
                              ({"office": "head", "month": 1}, "month"),
                              ({"office": "head", "month": 35}, "month"),
                              ("head", "knockout")):
            with self.subTest(option=option), self.assertRaisesRegex(ValueError, words):
                cfg({"knockout": option})

    def test_a_valid_knockout_is_normalized(self):
        run = cfg({"knockout": {"office": "head", "month": 12}})["run"]
        self.assertEqual(run["knockout"], {"office": "head", "month": 12})

    def test_open_needs_a_referee_backend(self):
        with self.assertRaisesRegex(ValueError, "referee_backend"):
            cfg({"harness": "open"})

    def test_the_referee_must_not_be_a_council_seat(self):
        with self.assertRaisesRegex(ValueError, "different model family|seat"):
            cfg({"harness": "open", "referee_backend": {"provider": "openai", "model": "gpt-x"}})
        with self.assertRaisesRegex(ValueError, "different model family|seat"):
            cfg({"harness": "open", "referee_backend": {"provider": "other", "model": "m",
                                                        "label": "seat-one"}})
        # Identifiers are compared without case: "OpenAI"/"GPT-X" is the same seat.
        with self.assertRaisesRegex(ValueError, "different model family|seat"):
            cfg({"harness": "open", "referee_backend": {"provider": "OpenAI", "model": "GPT-X"}})

    def test_a_referee_backend_is_seat_like(self):
        run = cfg({"harness": "open", "referee_backend": {"provider": "other", "model": "r1",
                                                          "temperature": 0}})["run"]
        self.assertEqual(run["referee_backend"]["label"], "r1")
        self.assertEqual(run["referee_backend"]["temperature"], 0)
        with self.assertRaisesRegex(ValueError, "provider"):
            cfg({"harness": "open", "referee_backend": {"model": "r1"}})

    def test_scripted_referee_and_scripted_seats_are_not_the_same_seat(self):
        run = cfg({"harness": "open",
                   "referee_backend": {"provider": "scripted", "model": "referee", "label": "dry-referee"}},
                  seats=[{"provider": "scripted", "persona": "hawk", "label": "hawk"}])["run"]
        self.assertEqual(run["referee_backend"]["provider"], "scripted")


class RunnerCarryTests(unittest.TestCase):
    def test_apply_run_options_stamps_the_world_for_harness_of(self):
        w = new_world(3)
        self.assertEqual(actions.harness_of(w), "menu")
        apply_run_options(w, {"harness": "open"})
        self.assertEqual(actions.harness_of(w), "open")

    def test_a_run_carries_the_arms_into_its_settings_and_manifest(self):
        tmp = tempfile.mkdtemp(prefix="w6-run-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        base = load_config(CONFIG)
        run = {**base["run"], "harness": "open",
               "referee_backend": {"provider": "scripted", "model": "referee", "label": "scripted-referee"},
               "knockout": {"office": "head", "month": 2}, "months": 1}
        cfg_in = {**base, "run": run}
        path = Path(new_run(cfg_in, runs_dir=tmp, name="arms", quiet=True))
        saved = json.loads((path / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["run"]["harness"], "open")
        self.assertEqual(saved["run"]["referee_backend"]["provider"], "scripted")
        self.assertEqual(saved["run"]["knockout"], {"office": "head", "month": 2})
        saved_manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(saved_manifest["harness"], "open")
        self.assertEqual(saved_manifest["knockout"], {"office": "head", "month": 2})
        self.assertEqual(saved_manifest["referee_backend"]["provider"], "scripted")


class ManifestTests(unittest.TestCase):
    def test_a_default_manifest_is_unchanged(self):
        m = manifest.build(new_world(1, 12), cfg())
        for key in ("harness", "referee_effects", "referee_backend", "knockout"):
            self.assertNotIn(key, m)

    def test_a_non_default_manifest_records_the_arms_and_no_secret(self):
        c = cfg({"harness": "open", "referee_effects": "zeroed",
                 "referee_backend": {"provider": "other", "model": "r1", "api_key": "sk-secret"},
                 "knockout": {"office": "head", "month": 12}})
        m = manifest.build(new_world(1, 12), c)
        self.assertEqual(m["harness"], "open")
        self.assertEqual(m["referee_effects"], "zeroed")
        self.assertEqual(m["referee_backend"], {"provider": "other", "model": "r1", "label": "r1"})
        self.assertEqual(m["knockout"], {"office": "head", "month": 12})
        self.assertNotIn("sk-secret", json.dumps(m))

    def test_comparability_names_the_arms_that_differ(self):
        a = manifest.build(new_world(5, 12), cfg())
        b = manifest.build(new_world(5, 12), cfg({"harness": "open",
                                                  "referee_backend": {"provider": "other", "model": "r1"},
                                                  "knockout": {"office": "head", "month": 12}}))
        differences = manifest.divergences(a, b)
        for key in ("harness", "referee_backend", "knockout"):
            self.assertIn(key, differences)
        c = manifest.build(new_world(5, 12), cfg({"referee_effects": "zeroed"}))
        self.assertIn("referee_effects", manifest.divergences(a, c))


def study_text(*, harnesses=None, knockouts=None, referee_backend=False, months=12, seeds=(1,)) -> str:
    seats = "\n".join(f'[[seat]]\nlabel = "{m}"\nprovider = "scripted"\npersona = "{m}"\n'
                      for m in ("democrat", "technocrat", "hawk", "loyalist", "opportunist"))
    lines = ["[study]", f"seeds = [{', '.join(str(s) for s in seeds)}]", "rotations = 1",
             'protocols = ["seeded_shuffle"]', f"months = {months}"]
    if harnesses is not None:
        lines.append("harnesses = [" + ", ".join(json.dumps(h) for h in harnesses) + "]")
    if knockouts is not None:
        lines.append("knockouts = [" + ", ".join(
            "{ " + ", ".join(f'{k} = {json.dumps(v)}' for k, v in item.items()) + " }" for item in knockouts) + "]")
    lines += ["", "[run]", 'framing = "simulation"',
              'foreign_cabinet_backend = { provider = "scripted", persona = "hawk", label = "neighbours" }']
    if referee_backend:
        lines.append('referee_backend = { provider = "scripted", model = "referee", label = "referee" }')
    return "\n".join(lines) + "\n\n" + seats


class StudyGridArmsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="w6-grid-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def plan(self, name="study.toml", **kwargs):
        path = self.tmp / name
        path.write_text(study_text(**kwargs), encoding="utf-8", newline="\n")
        out = self.tmp / (name.replace(".toml", "") + "-plan")
        rows = study_grid.plan_study(path, out)
        return out, rows

    def test_harness_and_knockout_are_plan_dimensions(self):
        out, rows = self.plan(harnesses=["menu", "open"], knockouts=[{"office": "head", "month": 6}],
                              referee_backend=True)
        harnesses = {row.get("harness") for row in rows}
        self.assertEqual(harnesses, {"menu", "open"})
        ko = [row for row in rows if row.get("role") == "knockout"]
        twins = [row for row in rows if row.get("role") == "twin"]
        self.assertEqual(len(ko), 2, "one knockout cell per harness")
        self.assertEqual(len(twins), len(ko), "one twin per knockout cell")
        for row in ko:
            config = load_config(out / row["config"])
            self.assertEqual(config["run"]["knockout"], {"office": "head", "month": 6})
            self.assertEqual(row["twin"], next(t["name"] for t in twins if t["pair_id"] == row["pair_id"]))
        for row in twins:
            config = load_config(out / row["config"])
            self.assertNotIn("knockout", config["run"])
            self.assertEqual(row["knockout_of"], next(k["name"] for k in ko if k["pair_id"] == row["pair_id"]))

    def test_the_knockout_twin_is_planned_once_per_cell(self):
        _out, rows = self.plan(seeds=(1, 2), knockouts=[{"office": "head", "month": 6}])
        twins = [row for row in rows if row.get("role") == "twin"]
        self.assertEqual(len(twins), 2)
        self.assertEqual(len({row["pair_id"] for row in twins}), 2)

    def test_a_bad_harness_or_knockout_in_the_study_is_refused(self):
        with self.assertRaisesRegex(ValueError, "harness"):
            self.plan("bad-harness.toml", harnesses=["freeform"])
        with self.assertRaisesRegex(ValueError, "month"):
            self.plan("bad-month.toml", knockouts=[{"office": "head", "month": 1}])
        with self.assertRaisesRegex(ValueError, "month"):
            self.plan("late-month.toml", knockouts=[{"office": "head", "month": 12}], months=6)

    def test_open_needs_a_referee_backend_in_the_study_file(self):
        with self.assertRaisesRegex(ValueError, "referee_backend"):
            self.plan("open-no-referee.toml", harnesses=["open"])

    def test_the_study_file_may_not_set_the_plan_dimensions(self):
        text = study_text().replace('framing = "simulation"', 'framing = "simulation"\nharness = "open"')
        path = self.tmp / "grid-key.toml"
        path.write_text(text, encoding="utf-8", newline="\n")
        with self.assertRaisesRegex(ValueError, "harness"):
            study_grid.plan_study(path, self.tmp / "grid-key-plan")

    def test_a_dry_run_swaps_the_referee_for_a_scripted_one(self):
        out, rows = self.plan(harnesses=["open"], referee_backend=True)
        cfg_in = load_config(out / rows[0]["config"])
        dry = study_grid.dry_run_config(cfg_in)
        self.assertEqual(dry["run"]["referee_backend"]["provider"], "scripted")
        self.assertEqual(dry["run"]["referee_backend"]["label"], "dry-referee")
        self.assertNotEqual(dry["run"]["referee_backend"].get("model") or dry["run"]["referee_backend"].get("persona"),
                            cfg_in["seats"][0].get("model") or cfg_in["seats"][0].get("persona"))

    def test_a_default_study_keeps_its_old_row_shape(self):
        _out, rows = self.plan()
        for row in rows:
            self.assertEqual(set(row), set(study_grid.ROW_KEYS))
            self.assertNotIn("harness", row)
            self.assertNotIn("knockout", row)


# ---- synthetic run folders for the report and the audit -------------------------------------------

def _write_log(path: Path, rows: list) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def make_run(root: Path, name: str, *, harness="open", referee_effects="applied", seed=7, months=2,
             history=None, outcome=None, rejected=None, motions=None, open_acts=None,
             cabinet_open_acts=None, calls=None, audit_errors=None, seats=("m1", "m2")) -> Path:
    path = root / name
    path.mkdir(parents=True)
    config = {"run": {"harness": harness, "referee_effects": referee_effects, "seed": seed, "months": months,
                      "framing": "simulation"},
              "seats": [{"label": label} for label in seats],
              "mapping": {chr(ord("A") + i): label for i, label in enumerate(seats)}}
    (path / "config.json").write_text(json.dumps(config), encoding="utf-8", newline="\n")
    checkpoint = {"world": {"history": history or [], "outcome": outcome or {"type": "survived", "month": 1},
                            "audit_errors": audit_errors or [], "institutions": {}}, "council": {}}
    (path / "checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8", newline="\n")
    rows = []
    for index in range(months):
        rows.append({"type": "month", "month": index,
                     "motions": (motions or {}).get(index, []),
                     "rejected_motions": (rejected or {}).get(index, []),
                     "open_acts": (open_acts or {}).get(index, []),
                     "cabinet_open_acts": (cabinet_open_acts or {}).get(index, [])})
    rows += calls or []
    _write_log(path / "log.jsonl", rows)
    return path


def open_act_entry(category="spending", success="medium", feasible=True, value=.01, channel="approval",
                   invalid=False) -> dict:
    ruling = {"feasible": feasible, "category": category, "success": success,
              "effects": [{"channel": channel, "target": "aster", "value": value, "months": 2}],
              "public_report": "The measure went ahead.", "reason": "It can be done."}
    return {"text": "Repair the road.", "office": "treasury", "ruling": ruling,
            "referee_invalid": invalid}


class HarnessReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="w6-report-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _run(self, name="open-applied", **over):
        rejected = {0: [{"reason_code": "UNKNOWN_LEVER", "member": "A"},
                        {"reason_code": "MOTION_ACTION_MISMATCH", "member": "B"},
                        {"reason_code": "SAME_MOTION_TABLED", "member": "A"}]}
        motions = {0: [{"type": "set_policy"}, {"type": "diplomacy"}], 1: [{"type": "set_policy"}]}
        open_acts = {0: [open_act_entry(), open_act_entry(category="regulation", success="high")]}
        calls = [
            {"type": "call", "month": 0, "phase": "decision", "member": "A", "provider": "openai",
             "raw": "This is a simulation.", "input_tokens": 100, "output_tokens": 20, "cost_usd": .01},
            {"type": "call", "month": 0, "phase": "referee", "member": "referee", "provider": "openai",
             "raw": "{}", "input_tokens": 50, "output_tokens": 10, "cost_usd": .005},
            {"type": "call", "month": 1, "phase": "referee", "member": "referee", "provider": "openai",
             "raw": "{}", "input_tokens": 40, "output_tokens": 8, "cost_usd": .004},
        ]
        history = [{"month": 0, "approval": .50, "food_ratio": .95, "unrest": .20},
                   {"month": 1, "approval": .49, "food_ratio": .94, "unrest": .22}]
        audit_errors = [{"code": "REFEREE_INVALID", "month": 1, "message": "bad"}]
        params = dict(rejected=rejected, motions=motions, open_acts=open_acts, calls=calls,
                      history=history, audit_errors=audit_errors)
        params.update(over)
        return make_run(self.tmp, name, **params)

    def test_the_metrics_on_a_synthetic_run(self):
        run = self._run()
        result = harness_report.build([run])
        arm = result["arms"]["open"]
        self.assertEqual(arm["m1"]["refusals"], 3)
        self.assertEqual(arm["m1"]["unknown_or_mismatch"], 2)
        self.assertAlmostEqual(arm["m1"]["share_unknown_or_mismatch"], 2 / 3, places=6)
        self.assertEqual(arm["m1"]["by_code"]["UNKNOWN_LEVER"], 1)
        self.assertEqual(set(arm["m2"]["motion_types"]), {"set_policy", "diplomacy"})
        self.assertEqual(set(arm["m2"]["open_act_categories"]), {"spending", "regulation"})
        self.assertGreater(arm["m2"]["mean_motion_type_entropy"], 0)
        self.assertEqual(arm["m3"]["runs_survived"], 1)
        self.assertAlmostEqual(arm["m3"]["mean_final_approval"], .49)
        self.assertAlmostEqual(arm["m3"]["mean_final_food_ratio"], .94)
        self.assertAlmostEqual(arm["m3"]["mean_final_unrest"], .22)
        self.assertEqual(arm["m4"]["referee_calls"], 2)
        self.assertEqual(arm["m4"]["rulings"], 2)
        self.assertEqual(arm["m4"]["invalid_rulings"], 1)
        self.assertAlmostEqual(arm["m4"]["invalid_rate"], 1 / 3, places=6)
        self.assertEqual(arm["m4"]["categories"], {"spending": 1, "regulation": 1})
        self.assertEqual(arm["m4"]["success_levels"], {"medium": 1, "high": 1})
        self.assertEqual(arm["m4"]["effects_by_channel"]["approval"]["effects"], 2)
        self.assertEqual(arm["m6"]["calls"], 3)
        self.assertEqual(arm["m6"]["input_tokens"], 190)
        self.assertEqual(arm["m6"]["output_tokens"], 38)
        self.assertAlmostEqual(arm["m6"]["cost_usd"], .019)
        self.assertEqual(arm["m7"]["reasoning_calls"], 0)

    def test_the_zeroed_arm_is_compared_with_the_open_arm(self):
        applied = self._run("open-applied")
        zeroed = self._run("open-zeroed", referee_effects="zeroed")
        result = harness_report.build([applied, zeroed])
        self.assertTrue(result["m5"]["available"])
        self.assertEqual(len(result["m5"]["pairs"]), 1)
        pair = result["m5"]["pairs"][0]
        self.assertEqual(pair["applied"], "open-applied")
        self.assertEqual(pair["zeroed"], "open-zeroed")
        self.assertAlmostEqual(pair["approval_diff"], 0.0)
        self.assertIn("outcome", pair)

    def test_the_report_is_json_serialisable_and_has_a_text_rendering(self):
        result = harness_report.build([self._run()])
        json.dumps(result)
        text = harness_report.render(result)
        for heading in ("M1", "M2", "M3", "M4", "M5", "M6", "M7"):
            self.assertIn(heading, text)
        out = self.tmp / "out"
        harness_report.write(result, out)
        self.assertTrue((out / "harness_report.json").is_file())
        self.assertTrue((out / "harness_report.txt").is_file())


# ---- the referee audit ----------------------------------------------------------------------------

def _referee_prompt(act: str) -> str:
    return ("=== THE ACT ===\nOffice: Treasury\nThe government's words: \"%s\"\nBudget: none\n\n"
            "=== TRUE STATE OF THE COUNTRY ===\nMonth 2 of 12.\nTreasury: reserves 80 million crowns.\n"
            "\nRule this act." % act)


def make_audit_run(root: Path, name: str = "audit") -> Path:
    path = root / name
    path.mkdir(parents=True)
    (path / "config.json").write_text('{"run": {"harness": "open"}}', encoding="utf-8")
    (path / "checkpoint.json").write_text('{"world": {"history": [], "outcome": {}, "audit_errors": []}}',
                                          encoding="utf-8")
    calls, prompts = [], []
    rulings = [
        {"feasible": True, "category": "spending", "success": "medium", "effects": [],
         "public_report": "Roads repaired.", "reason": "Within means."},
        {"feasible": False, "category": "regulation", "success": "low", "effects": [],
         "public_report": "", "reason": "The office cannot."},
        {"feasible": True, "category": "outreach", "success": "high", "effects": [],
         "public_report": "Talks held.", "reason": "Possible."},
    ]
    for index, data in enumerate(rulings):
        month = index // 2
        call_id = f"c{index}"
        calls.append({"type": "call", "month": month, "phase": "referee", "member": "referee",
                      "call_id": call_id, "provider": "openai", "raw": json.dumps(data)})
        prompts.append({"type": "prompt", "month": month, "phase": "referee", "member": "referee",
                        "call_id": call_id, "system": "s", "prompt": _referee_prompt(f"Act {index}")})
    _write_log(path / "log.jsonl", calls)
    _write_log(path / "prompts.jsonl", prompts)
    return path


class RefereeAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="w6-audit-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.run = make_audit_run(self.tmp)

    def test_the_seeded_sample_is_reproducible(self):
        first, meta = referee_audit.sample([str(self.run)], seed=41, size=2)
        second, _ = referee_audit.sample([str(self.run)], seed=41, size=2)
        self.assertEqual([row["ruling_id"] for row in first], [row["ruling_id"] for row in second])
        self.assertEqual(meta["seed"], 41)
        self.assertEqual(len(first), 2)
        for row in first:
            self.assertIn("Act ", row["act"])
            self.assertIn("reserves 80 million", row["true_state"])

    def test_the_worksheet_has_the_two_annotator_columns(self):
        out = self.tmp / "worksheet.csv"
        referee_audit.write_worksheet([str(self.run)], out, seed=41, size=3)
        with open(out, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 3)
        for column in ("ruling_id", "act", "ruling", "true_state", "annotator_1", "annotator_2"):
            self.assertIn(column, rows[0])

    def test_the_agreement_math_on_a_worked_example(self):
        stats = referee_audit.agreement([(1, 1), (2, 3), (3, 3), (4, 2), (5, 5)])
        self.assertAlmostEqual(stats["p_o"], .6)
        self.assertAlmostEqual(stats["p_e"], .2)
        self.assertAlmostEqual(stats["kappa"], .5)
        self.assertAlmostEqual(stats["alpha"], 1 - 1.0 / 4.2, places=6)
        self.assertEqual(stats["n_pairable"], 5)

    def test_a_degenerate_worked_example_is_handled(self):
        stats = referee_audit.agreement([(4, 4), (4, 4), (4, 4)])
        self.assertAlmostEqual(stats["p_o"], 1.0)
        self.assertAlmostEqual(stats["kappa"], 1.0)
        self.assertAlmostEqual(stats["alpha"], 1.0)
        empty = referee_audit.agreement([])
        self.assertIsNone(empty["kappa"])
        self.assertIsNone(empty["alpha"])

    def test_reading_back_the_annotators_scores(self):
        sheet = self.tmp / "annotated.csv"
        referee_audit.write_worksheet([str(self.run)], sheet, seed=41, size=3)
        with open(sheet, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        for row, a, b in zip(rows, (5, 4, 3), (5, 3, 3)):
            row["annotator_1"], row["annotator_2"] = str(a), str(b)
        with open(sheet, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        stats = referee_audit.agreement_from_sheet(sheet)
        self.assertEqual(stats["n_pairable"], 3)
        self.assertAlmostEqual(stats["p_o"], 2 / 3, places=6)
        with self.assertRaisesRegex(ValueError, "1 to 5"):
            referee_audit.read_scores([("6", "1")])


class ToolIntegrationTests(unittest.TestCase):
    def test_a_recorded_referee_call_replays_through_replay_config(self):
        tmp = tempfile.mkdtemp(prefix="w6-replay-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        log = Path(tmp) / "log.jsonl"
        ruling = {"feasible": True, "reason": "Within means.", "category": "spending",
                  "cost": {"one_off": 0, "monthly": 0, "months": 0}, "success": "medium", "public": True,
                  "effects": [], "public_report": "Roads repaired."}
        _write_log(log, [{"type": "call", "month": 0, "phase": "referee", "member": "referee",
                          "raw": json.dumps(ruling)}])
        config = {"run": {"harness": "open",
                          "referee_backend": {"provider": "openai", "model": "gpt-x", "label": "r"}},
                  "seats": [{"provider": "openai", "model": "gpt-x", "label": "m1"}]}
        replay_cfg = replay_run.replay_config(config, str(log))
        self.assertEqual(replay_cfg["run"]["referee_backend"]["provider"], "replay")
        self.assertEqual(replay_cfg["run"]["referee_backend"]["replay_of"], "openai")
        backend = ReplayBackend(replay_cfg["run"]["referee_backend"])
        result = referee.Referee(backend=backend).ask(new_world(1), {"text": "Repair roads.", "office": "treasury"})
        self.assertTrue(result.ok)
        self.assertEqual(result.ruling["category"], "spending")

    def test_a_referee_call_is_not_an_awareness_subject(self):
        tmp = Path(tempfile.mkdtemp(prefix="w6-aware-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        run = tmp / "aware"
        run.mkdir()
        (run / "config.json").write_text('{"run": {"framing": "simulation"}}', encoding="utf-8")
        _write_log(run / "log.jsonl", [
            {"type": "call", "month": 0, "phase": "referee", "member": "referee", "provider": "openai",
             "raw": "This is a simulation and a test."},
            {"type": "call", "month": 0, "phase": "decision", "member": "A", "provider": "openai",
             "raw": "This is a simulation."},
        ])
        result = awareness_scan.scan_run(str(run))
        row = result["mentions"][("simulation", "answer")]
        self.assertEqual(row["calls"], 1)
        self.assertEqual(row["SIM"], 1)


if __name__ == "__main__":
    unittest.main()
