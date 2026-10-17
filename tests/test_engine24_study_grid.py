"""The study runner (tools/study_grid.py): the rotation grid is a Latin square, the plan and status files have
the shape their readers rely on, a dry run of a small grid finishes with every row done, and a row that keeps
pausing is resumed and then failed.

The grid tests need no model: the plans use scripted seats, the dry run uses scripted seats too, and the resume
tests use a fake engine that writes real checkpoints.
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import tomllib
import unittest
from collections import defaultdict
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, ROOT)
sys.path.insert(0, TOOLS)

import study_grid  # noqa: E402
from karamaniya.config import RUN_DEFAULTS, load_config  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

LETTERS = "ABCDE"
MODELS = ["democrat", "technocrat", "hawk", "loyalist", "opportunist"]
PROTOCOLS = ["seeded_shuffle", "fixed_precedence"]
ROW_KEYS = {"name", "protocol", "seed", "rotation", "config", "seat_map"}


def study_text(seeds=(1, 2, 3), rotations=5, protocols=PROTOCOLS, months=12) -> str:
    seats = "\n".join(f'[[seat]]\nlabel = "{m}"\nprovider = "scripted"\npersona = "{m}"\n' for m in MODELS)
    return ("[study]\n"
            f"seeds = [{', '.join(str(s) for s in seeds)}]\n"
            f"rotations = {rotations}\n"
            f"protocols = [{', '.join(json.dumps(p) for p in protocols)}]\n"
            f"months = {months}\n\n"
            "[run]\n"
            'framing = "simulation"\n'
            "survey = true\n"
            'foreign_cabinet_backend = { provider = "scripted", persona = "hawk", label = "neighbours" }\n\n'
            + seats)


class TempDirTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="study-grid-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def study(self, name="study.toml", **kwargs) -> Path:
        path = self.tmp / name
        path.write_text(study_text(**kwargs), encoding="utf-8", newline="\n")
        return path


class LatinSquareTests(TempDirTests):
    def setUp(self):
        super().setUp()
        self.plan_dir = self.tmp / "plan"
        study_grid.plan_study(self.study(), self.plan_dir)
        self.rows = study_grid.load_plan(self.plan_dir / "plan.json")

    def test_each_model_holds_each_letter_once_per_seed(self):
        for protocol in PROTOCOLS:
            for seed in (1, 2, 3):
                held = defaultdict(list)
                for row in self.rows:
                    if row["protocol"] == protocol and row["seed"] == seed:
                        for letter, label in row["seat_map"].items():
                            held[label].append(letter)
                self.assertEqual(sorted(held), sorted(MODELS), (protocol, seed))
                for label in MODELS:
                    self.assertEqual(sorted(held[label]), list(LETTERS), (protocol, seed, label))

    def test_model_i_sits_at_letter_i_plus_rotation_mod_5(self):
        for row in self.rows:
            for i, label in enumerate(MODELS):
                letter = LETTERS[(i + row["rotation"]) % 5]
                self.assertEqual(row["seat_map"][letter], label, row["name"])

    def test_config_seat_order_matches_the_seat_map(self):
        # With shuffle_seats = false the engine maps letters by seat position, so the file must carry the rotation.
        for row in self.rows:
            cfg = load_config(self.plan_dir / row["config"])
            self.assertIs(cfg["run"]["shuffle_seats"], False)
            self.assertEqual([s["label"] for s in cfg["seats"]], [row["seat_map"][x] for x in LETTERS], row["name"])


class PlanShapeTests(TempDirTests):
    def test_rows_are_named_and_have_the_documented_keys(self):
        plan_dir = self.tmp / "plan"
        study_grid.plan_study(self.study(seeds=(11, 12), rotations=5), plan_dir)
        rows = study_grid.load_plan(plan_dir / "plan.json")
        expected = {f"sv-{p}-s{s}-r{r}" for p in PROTOCOLS for s in (11, 12) for r in range(5)}
        self.assertEqual(len(rows), len(expected))
        self.assertEqual({row["name"] for row in rows}, expected)
        raw = json.loads((plan_dir / "plan.json").read_text(encoding="utf-8"))
        self.assertIsInstance(raw, list)
        for row in raw:
            self.assertEqual(set(row), ROW_KEYS)
            self.assertEqual(list(row["seat_map"]), list(LETTERS))
            self.assertTrue((plan_dir / row["config"]).is_file(), row["config"])
            self.assertEqual(row["name"], f"sv-{row['protocol']}-s{row['seed']}-r{row['rotation']}")
            self.assertNotIn("\\", row["config"])

    def test_configs_carry_the_study_keys(self):
        plan_dir = self.tmp / "plan"
        study_grid.plan_study(self.study(seeds=(7,), rotations=1, protocols=["fixed_precedence"], months=9), plan_dir)
        (row,) = study_grid.load_plan(plan_dir / "plan.json")
        raw = tomllib.loads((plan_dir / row["config"]).read_text(encoding="utf-8"))["run"]
        self.assertEqual(raw["office_assignment"], "by_letter")
        self.assertEqual(raw["action_order"], "fixed_precedence")
        self.assertIs(raw["shuffle_seats"], False)
        self.assertEqual(raw["seed"], 7)
        self.assertEqual(raw["months"], 9)
        self.assertEqual(raw["foreign_cabinet_backend"]["provider"], "scripted")

    def test_no_study_options_leaves_out_only_the_two_option_keys(self):
        plan_dir = self.tmp / "plan"
        study_grid.plan_study(self.study(seeds=(7,), rotations=1, protocols=["seeded_shuffle"]), plan_dir,
                              no_study_options=True)
        (row,) = study_grid.load_plan(plan_dir / "plan.json")
        raw = tomllib.loads((plan_dir / row["config"]).read_text(encoding="utf-8"))["run"]
        self.assertNotIn("office_assignment", raw)
        self.assertNotIn("action_order", raw)
        self.assertIs(raw["shuffle_seats"], False)
        self.assertEqual((raw["seed"], raw["months"]), (7, 12))

    def test_the_example_study_makes_the_full_fifty_row_grid(self):
        plan_dir = self.tmp / "example"
        study_grid.plan_study(Path(TOOLS) / "study_example.toml", plan_dir)
        rows = study_grid.load_plan(plan_dir / "plan.json")
        self.assertEqual(len(rows), 2 * 5 * 5)
        self.assertEqual(len({row["seed"] for row in rows}), 5)
        self.assertEqual(len({row["rotation"] for row in rows}), 5)
        self.assertEqual({row["protocol"] for row in rows}, set(PROTOCOLS))

    def test_plan_refuses_to_overwrite_a_plan(self):
        plan_dir = self.tmp / "plan"
        study_grid.plan_study(self.study(), plan_dir)
        with self.assertRaises(FileExistsError):
            study_grid.plan_study(self.study(), plan_dir)

    def test_a_study_must_name_the_neighbours_model(self):
        path = self.tmp / "no-neighbours.toml"
        path.write_text(study_text().replace("foreign_cabinet_backend", "# foreign"), encoding="utf-8", newline="\n")
        with self.assertRaisesRegex(ValueError, "foreign_cabinet_backend"):
            study_grid.plan_study(path, self.tmp / "plan")

    def test_a_study_needs_exactly_five_seats(self):
        text = study_text()
        text = text.replace('[[seat]]\nlabel = "opportunist"\nprovider = "scripted"\npersona = "opportunist"\n', "")
        path = self.tmp / "four.toml"
        path.write_text(text, encoding="utf-8", newline="\n")
        with self.assertRaisesRegex(ValueError, "five"):
            study_grid.plan_study(path, self.tmp / "plan")

    def test_the_grid_keys_belong_to_the_plan_not_the_study_file(self):
        text = study_text().replace('framing = "simulation"', 'framing = "simulation"\nseed = 5')
        path = self.tmp / "seeded.toml"
        path.write_text(text, encoding="utf-8", newline="\n")
        with self.assertRaisesRegex(ValueError, "seed"):
            study_grid.plan_study(path, self.tmp / "plan")


class EngineOptionGuardTests(TempDirTests):
    """The engine keeps unknown [run] keys without complaint, so a study option this engine does not list would be
    ignored silently. The runner refuses instead. RUN_DEFAULTS is patched so the test says the same whether or not
    the office and order branches are merged."""

    today = {k: v for k, v in RUN_DEFAULTS.items() if k not in study_grid.STUDY_OPTIONS}

    def test_an_option_the_engine_does_not_list_is_refused_even_in_a_dry_run(self):
        raw = {"office_assignment": "by_letter", "action_order": "seeded_shuffle", "seed": 1}
        with mock.patch.object(study_grid, "RUN_DEFAULTS", self.today):
            for dry in (False, True):
                with self.assertRaisesRegex(ValueError, "office_assignment"):
                    study_grid.check_engine_options(raw, dry_run=dry)

    def test_a_real_run_refuses_a_config_without_the_study_options(self):
        with mock.patch.object(study_grid, "RUN_DEFAULTS", self.today):
            with self.assertRaisesRegex(ValueError, "no-study-options"):
                study_grid.check_engine_options({"seed": 1, "shuffle_seats": False}, dry_run=False)

    def test_a_dry_run_may_use_a_config_without_the_study_options(self):
        with mock.patch.object(study_grid, "RUN_DEFAULTS", self.today):
            study_grid.check_engine_options({"seed": 1, "shuffle_seats": False}, dry_run=True)

    def test_options_the_engine_lists_pass(self):
        known = dict(self.today, office_assignment="formation", action_order="seeded_shuffle")
        raw = {"office_assignment": "by_letter", "action_order": "fixed_precedence"}
        with mock.patch.object(study_grid, "RUN_DEFAULTS", known):
            study_grid.check_engine_options(raw, dry_run=False)


class DryRunConfigTests(TempDirTests):
    def test_dry_run_swaps_every_seat_and_the_neighbours_for_scripted_ones_and_caps_months(self):
        plan_dir = self.tmp / "plan"
        study_grid.plan_study(self.study(seeds=(4,), rotations=1, protocols=["seeded_shuffle"], months=36),
                              plan_dir, no_study_options=True)
        (row,) = study_grid.load_plan(plan_dir / "plan.json")
        cfg = load_config(plan_dir / row["config"])
        dry = study_grid.dry_run_config(cfg)
        self.assertEqual(dry["run"]["months"], study_grid.DRY_MONTHS)
        self.assertEqual([s["label"] for s in dry["seats"]], [s["label"] for s in cfg["seats"]])
        self.assertEqual({s["provider"] for s in dry["seats"]}, {"scripted"})
        self.assertEqual([s["persona"] for s in dry["seats"]], list(study_grid.DRY_PERSONAS))
        self.assertEqual(dry["run"]["foreign_cabinet_backend"]["provider"], "scripted")
        self.assertIs(dry["run"]["judge"], False)
        self.assertNotIn("judge_backends", dry["run"])


class RunPlanTests(TempDirTests):
    def test_a_running_plan_cannot_be_started_twice(self):
        plan_dir = self.tmp / "plan"
        study_grid.plan_study(self.study(seeds=(1,), rotations=1, protocols=["seeded_shuffle"]), plan_dir,
                              no_study_options=True)
        (plan_dir / ".grid-dry.lock").write_text("123", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "in progress"):
            study_grid.run_plan(plan_dir / "plan.json", dry_run=True, runs_dir=self.tmp / "runs")


class FakeEngine:
    """Stands in for karamaniya.runner. Each attempt on a row takes the next step of its script, and the last step
    repeats: "finish" (the run ends), "pause" (a usage-limit pause, as the engine records it), "cap" (a spending-cap
    stop), "seats" (the seat check refuses, as SystemExit) or "crash" (an exception). It writes real checkpoints
    and config files, so the runner reads what it reads from the engine."""

    def __init__(self, scripts):
        self.scripts = {name: list(steps) for name, steps in scripts.items()}
        self.attempts = []

    def _step(self, name):
        steps = self.scripts[name]
        return steps.pop(0) if len(steps) > 1 else steps[0]

    def new_run(self, config, runs_dir, name, quiet=False, check=True, **kwargs):
        cfg = config if isinstance(config, dict) else load_config(config)
        self.attempts.append((name, "new"))
        step = self._step(name)
        if step == "seats":
            raise SystemExit("These seats cannot answer, so the run was not started: fake")
        if step == "crash":
            raise RuntimeError("fake crash")
        store = RunStore(Path(runs_dir) / name)
        mapping = {letter: seat["label"] for letter, seat in zip(LETTERS, cfg["seats"])}
        store.save_config({"run": cfg["run"], "seats": cfg["seats"], "mapping": mapping})
        if step == "finish_then_crash":                # the engine raises after the run has ended (its report)
            self._checkpoint(store, name, "finish")
            raise RuntimeError("fake report failure")
        self._checkpoint(store, name, step)
        return store.path

    def resume_run(self, run_dir, quiet=False, check=True, **kwargs):
        run_dir = Path(run_dir)
        self.attempts.append((run_dir.name, "resume"))
        step = self._step(run_dir.name)
        if step == "seats":
            raise SystemExit("These seats cannot answer, so the run was not resumed: fake")
        self._checkpoint(RunStore(run_dir), run_dir.name, step)
        return run_dir

    @staticmethod
    def _checkpoint(store, name, step):
        world = new_world(1, 1)
        meta = {"run_id": name, "stopped": ""}
        if step == "finish":
            world.outcome = {"type": "survived", "month": 0, "text": "fake"}
        elif step == "pause":
            meta["stopped"] = "paused in Month 1: fake usage limit"
        elif step == "cap":
            meta["stopped"] = "spending cap of $1.00 reached"
        store.save_checkpoint(world, {"spend": 0.5}, meta)


class ResumeLogicTests(TempDirTests):
    """Dry runs with the fake engine. The engine is handed the run folder's name, which in a dry run is the row
    name with a "dry-" prefix, so the scripts are keyed by that name."""

    def grid(self, seeds):
        plan_dir = self.tmp / "plan"
        study_grid.plan_study(self.study(seeds=seeds, rotations=1, protocols=["seeded_shuffle"]), plan_dir,
                              no_study_options=True)
        names = [row["name"] for row in study_grid.load_plan(plan_dir / "plan.json")]
        return plan_dir / "plan.json", names

    def invoke(self, plan, engine, max_resumes=2):
        with contextlib.redirect_stdout(io.StringIO()):
            return study_grid.run_plan(plan, workers=1, max_resumes=max_resumes, runs_dir=self.tmp / "runs",
                                       dry_run=True, engine=engine, out=lambda s: None)

    def test_a_row_that_pauses_once_is_resumed_and_finishes(self):
        plan, (a, b) = self.grid((1, 2))
        engine = FakeEngine({f"dry-{a}": ["pause", "finish"], f"dry-{b}": ["finish"]})
        status = self.invoke(plan, engine)
        self.assertEqual(status[a]["state"], "paused")
        self.assertIn("usage limit", status[a]["reason"])
        self.assertEqual(status[b]["state"], "done")
        status = self.invoke(plan, engine)
        self.assertEqual(status[a]["state"], "done")
        self.assertEqual(status[a]["resumes"], 1)
        self.assertEqual(engine.attempts[-1], (f"dry-{a}", "resume"))
        before = list(engine.attempts)
        self.invoke(plan, engine)
        self.assertEqual(engine.attempts, before, "a finished grid starts nothing")

    def test_a_row_that_keeps_pausing_is_failed_after_max_resumes(self):
        plan, (a,) = self.grid((1,))
        engine = FakeEngine({f"dry-{a}": ["pause"]})
        self.assertEqual(self.invoke(plan, engine, max_resumes=2)[a]["state"], "paused")
        self.assertEqual(self.invoke(plan, engine, max_resumes=2)[a]["resumes"], 1)
        status = self.invoke(plan, engine, max_resumes=2)
        self.assertEqual(status[a]["state"], "failed")
        self.assertEqual(status[a]["resumes"], 2)
        self.assertIn("2 resume", status[a]["reason"])
        attempts = len(engine.attempts)
        self.invoke(plan, engine, max_resumes=2)
        self.assertEqual(len(engine.attempts), attempts, "a failed row is not tried again")

    def test_a_run_left_running_by_a_killed_invocation_is_resumed(self):
        plan, (a,) = self.grid((1,))
        engine = FakeEngine({f"dry-{a}": ["pause", "finish"]})
        self.invoke(plan, engine)
        status_file = plan.parent / "status-dry-run.json"
        status = json.loads(status_file.read_text(encoding="utf-8"))
        status[a]["state"] = "running"
        status_file.write_text(json.dumps(status), encoding="utf-8")
        status = self.invoke(plan, engine)
        self.assertEqual(status[a]["state"], "done")
        self.assertEqual(status[a]["resumes"], 1)

    def test_a_spending_cap_stop_is_a_failure_not_a_pause(self):
        plan, (a,) = self.grid((1,))
        status = self.invoke(plan, FakeEngine({f"dry-{a}": ["cap"]}))
        self.assertEqual(status[a]["state"], "failed")
        self.assertIn("spending cap", status[a]["reason"])

    def test_refused_seats_pause_the_row_with_the_engines_message(self):
        plan, (a,) = self.grid((1,))
        engine = FakeEngine({f"dry-{a}": ["seats", "finish"]})
        status = self.invoke(plan, engine)
        self.assertEqual(status[a]["state"], "paused")
        self.assertIn("cannot answer", status[a]["reason"])
        status = self.invoke(plan, engine)
        self.assertEqual(status[a]["state"], "done", "the next attempt is a resume, and the seats answer")

    def test_an_unexpected_exception_fails_the_row(self):
        plan, (a,) = self.grid((1,))
        status = self.invoke(plan, FakeEngine({f"dry-{a}": ["crash"]}))
        self.assertEqual(status[a]["state"], "failed")
        self.assertIn("fake crash", status[a]["reason"])

    def test_an_exception_after_the_run_ended_leaves_the_row_done_with_a_note(self):
        plan, (a,) = self.grid((1,))
        status = self.invoke(plan, FakeEngine({f"dry-{a}": ["finish_then_crash"]}))
        self.assertEqual(status[a]["state"], "done")
        self.assertIn("after the run ended", status[a]["reason"])
        self.assertIn("fake report failure", status[a]["reason"])


class DryRunGridTests(TempDirTests):
    """A real dry run: 2 seeds x 2 rotations x 1 protocol, 1 month, 2 worker processes, no model calls."""

    def test_small_grid_finishes_with_every_row_done(self):
        plan_dir = self.tmp / "plan"
        study_grid.plan_study(self.study(seeds=(31, 32), rotations=2, protocols=["seeded_shuffle"], months=1),
                              plan_dir, no_study_options=True)
        plan = plan_dir / "plan.json"
        runs = self.tmp / "runs"
        with contextlib.redirect_stdout(io.StringIO()):
            status = study_grid.run_plan(plan, workers=2, max_resumes=3, runs_dir=runs, dry_run=True,
                                         out=lambda s: None)
        rows = study_grid.load_plan(plan)
        self.assertEqual(set(status), {row["name"] for row in rows})
        for row in rows:
            record = status[row["name"]]
            self.assertEqual(record["state"], "done", record)
            self.assertEqual(record["months_done"], 1)
            self.assertEqual(record["resumes"], 0)
            self.assertTrue((runs / f"dry-{row['name']}" / "checkpoint.json").is_file())
        on_disk = json.loads((plan_dir / "status-dry-run.json").read_text(encoding="utf-8"))
        self.assertEqual({k: v["state"] for k, v in on_disk.items()}, {row["name"]: "done" for row in rows})
        self.assertFalse((plan_dir / "status.json").exists(), "a dry run never writes the real study's status")
        config = json.loads((runs / f"dry-{rows[0]['name']}" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual({seat["provider"] for seat in config["seats"]}, {"scripted"})
        self.assertEqual(config["run"]["months"], 1)

        with contextlib.redirect_stdout(io.StringIO()):
            again = study_grid.run_plan(plan, workers=2, max_resumes=3, runs_dir=runs, dry_run=True,
                                        out=lambda s: None)
        self.assertEqual(again, on_disk, "a second invocation of a finished grid changes nothing")


class CommandLineTests(TempDirTests):
    def test_plan_and_run_report_their_outcome_on_the_command_line(self):
        plan_dir = self.tmp / "cli"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = study_grid.main(["plan", str(self.study(seeds=(5,), rotations=1, protocols=["seeded_shuffle"],
                                                       months=1)), str(plan_dir), "--no-study-options"])
        self.assertEqual(code, 0)
        self.assertTrue((plan_dir / "plan.json").is_file())
        with contextlib.redirect_stdout(io.StringIO()):
            code = study_grid.main(["run", str(plan_dir / "plan.json"), "--dry-run", "--workers", "1",
                                    "--runs-dir", str(self.tmp / "runs")])
        self.assertEqual(code, 0)


class RealEngineTests(TempDirTests):
    """The real engine, with scripted seats and no model calls: a non-dry run from the config file, and a resume of
    a finished or a mismatched run folder."""

    def grid(self, seeds, months=1, no_study_options=True):
        plan_dir = self.tmp / "plan"
        study_grid.plan_study(self.study(seeds=seeds, rotations=2, protocols=["seeded_shuffle"], months=months),
                              plan_dir, no_study_options=no_study_options)
        return plan_dir / "plan.json"

    def dry(self, plan, runs):
        with contextlib.redirect_stdout(io.StringIO()):
            return study_grid.run_plan(plan, workers=2, max_resumes=3, runs_dir=runs, dry_run=True,
                                       out=lambda s: None)

    def test_a_finished_row_resumed_by_hand_stays_done_and_counts_the_resume(self):
        plan, runs = self.grid((41,)), self.tmp / "runs"
        name = next(iter(self.dry(plan, runs)))
        status_file = plan.parent / "status-dry-run.json"
        status = json.loads(status_file.read_text(encoding="utf-8"))
        status[name]["state"] = "paused"
        status_file.write_text(json.dumps(status), encoding="utf-8")
        again = self.dry(plan, runs)
        self.assertEqual((again[name]["state"], again[name]["resumes"]), ("done", 1))
        self.assertEqual(again[name]["months_done"], 1)

    def test_a_folder_that_is_not_the_rows_own_is_failed_not_resumed(self):
        plan, runs = self.grid((42,)), self.tmp / "runs"
        name = next(iter(self.dry(plan, runs)))
        rows = json.loads(plan.read_text(encoding="utf-8"))
        row = next(r for r in rows if r["name"] == name)
        row["seat_map"]["A"], row["seat_map"]["B"] = row["seat_map"]["B"], row["seat_map"]["A"]
        plan.write_text(json.dumps(rows), encoding="utf-8")
        status_file = plan.parent / "status-dry-run.json"
        status = json.loads(status_file.read_text(encoding="utf-8"))
        status[name]["state"] = "paused"
        status_file.write_text(json.dumps(status), encoding="utf-8")
        after = self.dry(plan, runs)
        self.assertEqual(after[name]["state"], "failed")
        self.assertIn("not this row's run", after[name]["reason"])

    def test_a_real_run_of_scripted_seats_starts_from_the_config_file(self):
        plan = self.grid((43,), months=1, no_study_options=False)
        runs = self.tmp / "runs"
        known = dict(RUN_DEFAULTS, office_assignment="formation", action_order="seeded_shuffle")
        with mock.patch.object(study_grid, "RUN_DEFAULTS", known),                 contextlib.redirect_stdout(io.StringIO()):
            status = study_grid.run_plan(plan, workers=2, max_resumes=3, runs_dir=runs, dry_run=False,
                                         out=lambda s: None)
        self.assertEqual({rec["state"] for rec in status.values()}, {"done"})
        name = next(iter(status))
        self.assertTrue((plan.parent / "status.json").is_file())
        self.assertFalse((plan.parent / "status-dry-run.json").exists())
        self.assertTrue((runs / name / "checkpoint.json").is_file(), "a real run keeps the row's own name")

    def test_the_command_line_refuses_a_study_the_engine_would_ignore(self):
        plan_dir = self.tmp / "refused"
        study_grid.plan_study(self.study(seeds=(44,), rotations=1, protocols=["seeded_shuffle"], months=1), plan_dir)
        today = {k: v for k, v in RUN_DEFAULTS.items() if k not in study_grid.STUDY_OPTIONS}
        err = io.StringIO()
        with mock.patch.object(study_grid, "RUN_DEFAULTS", today), contextlib.redirect_stderr(err),                 contextlib.redirect_stdout(io.StringIO()):
            code = study_grid.main(["run", str(plan_dir / "plan.json"), "--dry-run", "--runs-dir",
                                    str(self.tmp / "runs")])
        self.assertEqual(code, 2)
        self.assertIn("office_assignment", err.getvalue())
        self.assertFalse((plan_dir / "status-dry-run.json").exists(), "nothing starts when the plan is refused")


if __name__ == "__main__":
    unittest.main()
