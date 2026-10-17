"""The study package studies/karamaniya_trust (brief item S8): the wrap must reproduce the legacy loop.

The reference is the legacy runner's own loop, karamaniya.runner.new_run, on scripted seats
(council.scripted.toml). Scripted seats call no model and need no key. Three checks compare against it:

1. LegacySeam (studies/karamaniya_trust/adapter/engine_seam.py) takes the same legacy steps one month
   at a time. It needs only the standard library, so these tests always run.
2. The SocioVerse2 wrap (adapter/providers.py) runs through socioverse2's LongitudinalSimulator. It
   needs socioverse2 0.2.0 in the Python that runs the tests, so these tests skip without it.
3. run.py --dry-run, the one-command check, reports the same equality. It also needs socioverse2.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "studies" / "karamaniya_trust"
COUNCIL = ROOT / "council.scripted.toml"
SEED = 4201  # a fresh seed: the pilot used seed 1 and seeds 1001-1013
MONTHS = 2
SKIP_NO_SOCIOVERSE = "socioverse2 is not installed in this Python (see studies/karamaniya_trust/README.md)"


def _socioverse_installed() -> bool:
    return importlib.util.find_spec("socioverse") is not None


FULL_HORIZON = 36  # the study's default horizon: the Charter's election month


def _reference(runs_dir: Path, months: int = MONTHS):
    """The legacy loop's per-month state and its final world, from new_run's observer and checkpoint."""
    from karamaniya.config import load_config
    from karamaniya.runner import new_run

    events = []
    path = new_run(load_config(COUNCIL), runs_dir=runs_dir, name="reference", months=months, seed=SEED,
                   quiet=True, check=False, observer=events.append)
    months = [{k: e[k] for k in ("stats", "members", "offices", "removed")}
              for e in events if e["type"] == "month_done"]
    world = json.loads((Path(path) / "checkpoint.json").read_text(encoding="utf-8"))["world"]
    return months, world


class LegacyRootTest(unittest.TestCase):
    def test_default_root_is_this_repository(self):
        from studies.karamaniya_trust.adapter.engine_seam import legacy_root

        with mock.patch.dict(os.environ):
            os.environ.pop("KARAMANIYA_ROOT", None)
            self.assertEqual(legacy_root(), ROOT)

    def test_env_var_must_name_a_checkout(self):
        from studies.karamaniya_trust.adapter.engine_seam import legacy_root

        with tempfile.TemporaryDirectory() as empty, mock.patch.dict(os.environ, {"KARAMANIYA_ROOT": empty}):
            with self.assertRaises(RuntimeError):
                legacy_root()


class LegacySeamReplaysNewRun(unittest.TestCase):
    """The seam takes the legacy runner's steps one month at a time: the same state, month by month."""

    @classmethod
    def setUpClass(cls):
        from studies.karamaniya_trust.adapter.engine_seam import LegacySeam

        cls.tmp = Path(tempfile.mkdtemp(prefix="kt-seam-"))
        cls.reference_months, cls.reference_world = _reference(cls.tmp / "reference")
        seam = LegacySeam(COUNCIL, runs_dir=cls.tmp / "seam", name="seam", months=MONTHS, seed=SEED,
                          check=False)
        seam.open()
        seam.form_government()
        cls.months = []
        for _ in range(MONTHS):
            seam.run_month()
            cls.months.append(seam.month_state())
        seam.finish()
        cls.run_dir = seam.run_dir

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_each_month_matches_new_run(self):
        self.assertEqual(self.months, self.reference_months)

    def test_saved_world_matches_new_run(self):
        saved = json.loads((self.run_dir / "checkpoint.json").read_text(encoding="utf-8"))["world"]
        self.assertEqual(saved, self.reference_world)


class LegacySeamFullHorizon(unittest.TestCase):
    """The seam runs the study's default horizon to the legacy end, handover extension included."""

    @classmethod
    def setUpClass(cls):
        from studies.karamaniya_trust.adapter.engine_seam import LegacySeam

        cls.tmp = Path(tempfile.mkdtemp(prefix="kt-full-"))
        cls.reference_months, cls.reference_world = _reference(cls.tmp / "reference", months=FULL_HORIZON)
        seam = LegacySeam(COUNCIL, runs_dir=cls.tmp / "seam", name="seam", months=FULL_HORIZON, seed=SEED,
                          check=False)
        seam.open()
        seam.form_government()
        while seam.may_run():
            seam.run_month()
        seam.finish()
        cls.trace = seam.trace
        cls.run_dir = seam.run_dir

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_legacy_month_matches_new_run(self):
        # The Month-36 election leaves a handover owed, so the legacy run goes one month past the nominal horizon.
        self.assertGreater(len(self.reference_months), FULL_HORIZON)
        self.assertEqual(self.trace, self.reference_months)

    def test_saved_world_matches_new_run(self):
        saved = json.loads((self.run_dir / "checkpoint.json").read_text(encoding="utf-8"))["world"]
        self.assertEqual(saved, self.reference_world)


@unittest.skipUnless(_socioverse_installed(), SKIP_NO_SOCIOVERSE)
class SocioVerseWrapFullHorizon(unittest.TestCase):
    """The SocioVerse2 wrap over the default horizon: the steps the legacy run ran match it, and the world matches."""

    @classmethod
    def setUpClass(cls):
        from studies.karamaniya_trust.adapter.providers import build_karamaniya_simulator

        cls.tmp = Path(tempfile.mkdtemp(prefix="kt-full-sv-"))
        cls.reference_months, cls.reference_world = _reference(cls.tmp / "reference", months=FULL_HORIZON)
        sim, seam = build_karamaniya_simulator(config=COUNCIL, runs_dir=cls.tmp / "wrapped", name="wrapped",
                                               months=FULL_HORIZON, seed=SEED,
                                               trajectory_dir=cls.tmp / "trajectory", check=False)
        cls.history = sim.run()
        seam.finish()
        cls.trace = seam.trace
        cls.run_dir = seam.run_dir

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_legacy_month_matches_new_run(self):
        self.assertGreater(len(self.reference_months), FULL_HORIZON)
        self.assertEqual(self.trace, self.reference_months)
        ran = [row["step"] for row in self.history.rows if row["month_ran"]]
        self.assertEqual(ran, list(range(1, len(self.reference_months) + 1)))

    def test_final_world_matches_new_run(self):
        saved = json.loads((self.run_dir / "checkpoint.json").read_text(encoding="utf-8"))["world"]
        self.assertEqual(saved, self.reference_world)


@unittest.skipUnless(_socioverse_installed(), SKIP_NO_SOCIOVERSE)
class SocioVerseWrapReplaysNewRun(unittest.TestCase):
    """The SocioVerse2 wrap, run by LongitudinalSimulator, matches the legacy loop step by step."""

    @classmethod
    def setUpClass(cls):
        from studies.karamaniya_trust.adapter.providers import build_karamaniya_simulator

        cls.tmp = Path(tempfile.mkdtemp(prefix="kt-sv-"))
        cls.reference_months, cls.reference_world = _reference(cls.tmp / "reference")
        cls.trajectory = cls.tmp / "trajectory"
        sim, seam = build_karamaniya_simulator(config=COUNCIL, runs_dir=cls.tmp / "wrapped", name="wrapped",
                                               months=MONTHS, seed=SEED, trajectory_dir=cls.trajectory,
                                               check=False)
        cls.history = sim.run()
        seam.finish()
        cls.run_dir = seam.run_dir

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_each_step_matches_new_run(self):
        from studies.karamaniya_trust.adapter.engine_seam import step_bound

        bound = step_bound(MONTHS)
        rows = {row["step"]: row for row in self.history.rows}
        self.assertEqual(sorted(rows), list(range(bound + 1)))  # step 0 (the founding state), then up to the bound
        ran = [t for t in range(1, bound + 1) if rows[t]["month_ran"]]
        self.assertEqual(ran, list(range(1, MONTHS + 1)))  # the legacy run ends after MONTHS months here
        for t, ref in enumerate(self.reference_months, start=1):
            row = rows[t]
            self.assertEqual(row["approval"], ref["stats"]["approval"], f"approval at step {t}")
            self.assertEqual(row["inflation_yoy"], ref["stats"]["infl_yoy"], f"inflation at step {t}")
            self.assertEqual(row["unrest"], ref["stats"]["unrest"], f"unrest at step {t}")
            self.assertEqual(row["food_ratio"], ref["stats"]["food_ratio"], f"food at step {t}")
            self.assertEqual(row["army"], ref["stats"]["army"], f"army at step {t}")
            self.assertEqual(row["active_members"], sum(s == "active" for s in ref["members"].values()),
                             f"active members at step {t}")

    def test_final_world_matches_new_run(self):
        saved = json.loads((self.run_dir / "checkpoint.json").read_text(encoding="utf-8"))["world"]
        self.assertEqual(saved, self.reference_world)

    def test_store_holds_one_panel_row_per_delegate_per_step(self):
        from socioverse.io import open_readonly
        from studies.karamaniya_trust.adapter.engine_seam import step_bound

        steps = step_bound(MONTHS) + 1  # step 0 and every step up to the bound
        con = open_readonly(self.trajectory / "study.duckdb")
        try:
            panel = con.execute("SELECT count(*) FROM panel").fetchone()[0]
            metrics = con.execute("SELECT count(*) FROM metrics").fetchone()[0]
        finally:
            con.close()
        self.assertEqual(panel, 5 * steps)
        self.assertEqual(metrics, steps)

    def test_artifacts_validate_against_socioverse_schemas(self):
        import yaml
        from socioverse.schemas import EnvironmentBundle, PopulationBundle, SimulationConfig, StudySpec
        from socioverse.validation import validate_handoff

        StudySpec.model_validate(yaml.safe_load((STUDY / "study.yaml").read_text(encoding="utf-8")))
        validate_handoff(STUDY / "environment" / "environment.json", EnvironmentBundle)
        validate_handoff(STUDY / "population" / "population.json", PopulationBundle)
        validate_handoff(STUDY / "simulation" / "simulation.json", SimulationConfig)

    def test_one_command_dry_run_reports_equal(self):
        tmp = Path(tempfile.mkdtemp(prefix="kt-dry-"))
        try:
            out, reports = tmp / "dry-run", tmp / "reports"
            proc = subprocess.run(
                [sys.executable, str(STUDY / "run.py"), "--dry-run", "--out", str(out),
                 "--report-dir", str(reports)],
                capture_output=True, text=True, timeout=900)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            check = json.loads((out / "parity_check.json").read_text(encoding="utf-8"))
            self.assertTrue(check["equal"], check)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
