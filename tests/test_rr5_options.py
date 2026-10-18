"""RR5: the `uprising_model` run option through config, runner, manifest and the study grid.

The engine modules read the option themselves (RR1, RR2); this file tests the lead's wiring: a config validates and
normalizes it, `runner.apply_run_options` stamps it on the world (and into the checkpointed institutions under
`legitimacy`), the manifest records a non-default model and reports it as a divergence, and
`tools/study_grid.py` plans it as a world dimension. A one-month scripted run under each model checks the chain end
to end and that a legacy run writes no `uprising_check` row.

    python -m unittest tests.test_rr5_options
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, ROOT)
sys.path.insert(0, TOOLS)

import study_grid  # noqa: E402
from karamaniya import manifest, regime_relief, uprising  # noqa: E402
from karamaniya.config import check_uprising_model, load_config, normalize_config  # noqa: E402
from karamaniya.runner import apply_run_options, new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")


def cfg_with(**run_over) -> dict:
    cfg = load_config(CONFIG)
    return {**cfg, "run": {**cfg["run"], **run_over}}


def one_seat(**run_over) -> dict:
    return {"run": run_over, "seat": [{"provider": "scripted", "persona": "democrat", "label": "democrat"}]}


class ConfigTests(unittest.TestCase):
    def test_the_default_is_legacy_and_stays_in_the_run(self):
        run = normalize_config(one_seat())["run"]
        self.assertEqual(run["uprising_model"], "legacy")

    def test_the_model_is_normalized_and_an_unknown_one_is_refused(self):
        run = {"uprising_model": " Legitimacy "}
        check_uprising_model(run)
        self.assertEqual(run["uprising_model"], "legitimacy")
        with self.assertRaisesRegex(ValueError, "uprising_model"):
            check_uprising_model({"uprising_model": "pedigree"})
        with self.assertRaisesRegex(ValueError, "uprising_model"):
            normalize_config(one_seat(uprising_model="pedigree"))
        with self.assertRaisesRegex(ValueError, "uprising_model"):
            check_uprising_model({"uprising_model": 3})


class RunnerTests(unittest.TestCase):
    def test_apply_run_options_stamps_both_readers_and_the_institutions(self):
        w = new_world(3)
        apply_run_options(w, {"uprising_model": "legitimacy"})
        self.assertEqual(uprising.model(w), "legitimacy")
        self.assertEqual(regime_relief.model(w), "legitimacy")
        self.assertEqual(w.institutions["uprising_model"], "legitimacy")
        # A world loaded from this checkpoint without its config still reads the model it ran under.
        del w.uprising_model
        self.assertEqual(uprising.model(w), "legitimacy")
        self.assertEqual(regime_relief.model(w), "legitimacy")

    def test_a_legacy_run_writes_no_option_into_the_checkpointed_institutions(self):
        w = new_world(3)
        apply_run_options(w, {})
        self.assertEqual(uprising.model(w), "legacy")
        self.assertNotIn("uprising_model", w.institutions)
        self.assertNotIn("uprising_model", w.to_dict()["institutions"])

    def test_new_run_refuses_a_bad_model_on_a_dict_config(self):
        tmp = tempfile.mkdtemp(prefix="rr5-config-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with self.assertRaisesRegex(ValueError, "uprising_model"):
            new_run(cfg_with(uprising_model="pedigree"), runs_dir=tmp, name="bad", quiet=True, check=False)
        self.assertFalse((Path(tmp) / "bad").exists())


class BaselineInheritanceTests(unittest.TestCase):
    def test_a_comparison_plays_the_run_s_world_model(self):
        from karamaniya import baseline
        run = cfg_with(uprising_model="legitimacy", months=2)["run"]
        config = baseline._config(run, 5, "scripted", 2)
        self.assertEqual(config["run"]["uprising_model"], "legitimacy")
        legacy = baseline._config(cfg_with(months=2)["run"], 5, "scripted", 2)
        self.assertEqual(legacy["run"]["uprising_model"], "legacy")


class ManifestTests(unittest.TestCase):
    def test_a_default_manifest_does_not_record_the_option(self):
        self.assertNotIn("uprising_model", manifest.build(new_world(1, 12), cfg_with()))

    def test_a_named_model_is_recorded_and_is_a_divergence(self):
        a = manifest.build(new_world(5, 12), cfg_with())
        b = manifest.build(new_world(5, 12), cfg_with(uprising_model="legitimacy"))
        self.assertEqual(b["uprising_model"], "legitimacy")
        self.assertIn("uprising_model", manifest.divergences(a, b))
        self.assertNotIn("uprising_model", manifest.divergences(a, manifest.build(new_world(5, 12), cfg_with())))


class RunCarryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rr5-run-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_one(self, model: str) -> tuple:
        path = Path(new_run(cfg_with(uprising_model=model, months=1, survey=False),
                            runs_dir=self.tmp, name=model, quiet=True))
        world, _council, _meta = RunStore(path).load_checkpoint()
        saved = json.loads((path / "config.json").read_text(encoding="utf-8"))
        saved_manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        return world, saved, saved_manifest

    def test_a_legitimacy_run_records_its_world_and_a_legacy_run_is_unchanged(self):
        world, saved, saved_manifest = self.run_one("legitimacy")
        self.assertEqual(saved["run"]["uprising_model"], "legitimacy")
        self.assertEqual(saved_manifest["uprising_model"], "legitimacy")
        # The checkpoint keeps the option in institutions; resume_run stamps the live attribute from config.
        self.assertEqual(uprising.model(world), "legitimacy")
        self.assertEqual(regime_relief.model(world), "legitimacy")
        self.assertEqual(world.institutions["uprising_model"], "legitimacy")
        first = world.history[0]
        self.assertIn("uprising_check", first)
        self.assertIn("L", first["uprising_check"])

        world, saved, saved_manifest = self.run_one("legacy")
        self.assertEqual(saved["run"]["uprising_model"], "legacy")
        self.assertNotIn("uprising_model", saved_manifest)
        self.assertEqual(uprising.model(world), "legacy")
        self.assertNotIn("uprising_model", world.institutions)
        first = world.history[0]
        self.assertNotIn("uprising_check", first)


def study_text(uprising_models=None, harnesses=None, run_extra: str = "") -> str:
    seats = "\n".join(f'[[seat]]\nlabel = "{m}"\nprovider = "scripted"\npersona = "{m}"\n'
                      for m in ("democrat", "technocrat", "hawk", "loyalist", "opportunist"))
    lines = ["[study]", "seeds = [1]", "rotations = 1", 'protocols = ["seeded_shuffle"]', "months = 2"]
    if uprising_models is not None:
        lines.append("uprising_models = [" + ", ".join(json.dumps(m) for m in uprising_models) + "]")
    if harnesses is not None:
        lines.append("harnesses = [" + ", ".join(json.dumps(h) for h in harnesses) + "]")
    lines += ["", "[run]", 'framing = "simulation"',
              'foreign_cabinet_backend = { provider = "scripted", persona = "hawk", label = "neighbours" }']
    if run_extra:
        lines.append(run_extra)
    return "\n".join(lines) + "\n\n" + seats


class StudyGridTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rr5-grid-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def plan(self, name="study.toml", **kwargs):
        path = self.tmp / name
        path.write_text(study_text(**kwargs), encoding="utf-8", newline="\n")
        out = self.tmp / (name.replace(".toml", "") + "-plan")
        return out, study_grid.plan_study(path, out)

    def test_the_world_is_a_plan_dimension_and_the_default_keeps_its_row_name(self):
        out, rows = self.plan(uprising_models=["legacy", "legitimacy"])
        by_model = {row["uprising_model"]: row for row in rows}
        self.assertEqual(set(by_model), {"legacy", "legitimacy"})
        self.assertEqual(by_model["legacy"]["name"], "sv-seeded_shuffle-s1-r0")
        self.assertEqual(by_model["legitimacy"]["name"], "sv-legitimacy-seeded_shuffle-s1-r0")
        for model, row in by_model.items():
            config = load_config(out / row["config"])
            self.assertEqual(config["run"]["uprising_model"], model)

    def test_a_study_without_the_dimension_plans_the_old_rows_and_carries_no_tag(self):
        _out, rows = self.plan()
        self.assertEqual(len(rows), 1)
        self.assertNotIn("uprising_model", rows[0])

    def test_both_dimensions_compose_in_the_name(self):
        _out, rows = self.plan(
            uprising_models=["legacy", "legitimacy"], harnesses=["menu", "open"],
            run_extra='referee_backend = { provider = "scripted", model = "referee", label = "referee" }')
        self.assertEqual({row["name"] for row in rows},
                         {"sv-seeded_shuffle-s1-r0", "sv-legitimacy-seeded_shuffle-s1-r0",
                          "sv-open-seeded_shuffle-s1-r0", "sv-open-legitimacy-seeded_shuffle-s1-r0"})
        self.assertEqual({(row.get("harness"), row.get("uprising_model")) for row in rows},
                         {("menu", "legacy"), ("menu", "legitimacy"),
                          ("open", "legacy"), ("open", "legitimacy")})

    def test_a_bad_model_or_a_study_file_grid_key_is_refused(self):
        with self.assertRaisesRegex(ValueError, "uprising_models"):
            self.plan("bad.toml", uprising_models=["pedigree"])
        with self.assertRaisesRegex(ValueError, "take them out of the study file"):
            self.plan("grid-key.toml", run_extra='uprising_model = "legacy"')


if __name__ == "__main__":
    unittest.main()
