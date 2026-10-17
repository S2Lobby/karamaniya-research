"""T143: the control room counts a run finished only when the engine says it is (gui.py `_run_state`).

The Month-36 election can owe a handover after the planned months, and the engine then runs up to HANDOVER_EXTENSION
(4) months more (engine.py, the last-month block of `step`). A run that has reached its planned months but has no
outcome yet is not finished, so a batch restart must resume it, not skip it. The extended checkpoint here is the one
the engine itself writes: `engine.step` is run on a bare world whose handover is owed past its last planned month. The
batch test starts from a real two-month scripted run and sets its horizon the same way. No server, no browser.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import engine  # noqa: E402
from karamaniya.gui import Controller  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def _row(name, months=2):
    return {"name": name, "council": "council.scripted.toml", "seed": 901, "months": months,
            "framing": "", "severity": "", "scenario": ""}


def _world_owing_a_handover_past_its_plan(planned):
    """The engine's own run of a world whose lost Charter election owes a handover in the month after the planned end:
    after `planned` months the history has `planned` rows, the horizon is one month longer, and no outcome is written."""
    w = new_world(seed=1, months=planned)
    w.const.handover_month = planned
    for _ in range(planned):
        engine.begin_month(w)
        engine.step(w)
    return w


def _record(controller):
    """Keep the run events the worker emits, and pass each one on to the controller as before."""
    events = []

    def observe(event):
        events.append(event)
        Controller.observer(controller, event)

    controller.observer = observe
    return events


class RunStateReadsTheEngine(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="karamaniya-e24-run-state-"))
        shutil.copy(os.path.join(ROOT, "council.scripted.toml"), self.root)
        self.runs = self.root / "runs"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def save(self, name, world):
        store = RunStore(self.runs / name)
        store.save_checkpoint(world, {}, {"stopped": "", "log_mark": store.mark()})
        return self.runs / name

    def state(self, run_dir, months):
        return Controller(self.root, self.runs)._run_state(run_dir, months)

    def test_a_run_extended_past_its_planned_months_is_not_finished(self):
        w = _world_owing_a_handover_past_its_plan(2)
        # the shape the engine wrote: the planned months are done, one more is owed, and there is no outcome yet
        self.assertEqual((len(w.history), w.months_total, w.ended()), (2, 3, False))
        run_dir = self.save("extended", w)
        # before the fix this read "done", because the history had reached the planned months
        self.assertEqual(self.state(run_dir, 2)["state"], "partial")

    def test_a_finished_run_is_done(self):
        w = new_world(seed=1, months=2)
        for _ in range(2):
            engine.begin_month(w)
            engine.step(w)
        self.assertEqual(w.outcome.get("type"), "survived")
        self.assertEqual(self.state(self.save("finished", w), 2)["state"], "done")

    def test_a_run_with_no_checkpoint_is_new(self):
        self.assertEqual(self.state(self.runs / "absent", 2)["state"], "new")

    def test_a_batch_restart_runs_the_extra_month_of_an_extended_run(self):
        # a real two-month scripted run, finished the way the engine finishes one
        c = Controller(self.root, self.runs)
        c.batch_start({"name": "t143-first", "items": [_row("t143-a")]})
        c.thread.join(timeout=600)
        run_dir = self.runs / "t143-a"
        store = RunStore(run_dir)
        w, council_state, meta = store.load_checkpoint()
        self.assertEqual(w.outcome.get("type"), "survived")
        # the state a handover owed past the plan leaves behind (see _world_owing_a_handover_past_its_plan)
        w.outcome = {}
        w.months_total = 3
        store.save_checkpoint(w, council_state, meta)
        # the room restarts and the batch runs again: the extended run must be resumed for its third month
        fresh = Controller(self.root, self.runs)
        events = _record(fresh)
        fresh.batch_start({"name": "t143-first", "items": [_row("t143-a")]})
        fresh.thread.join(timeout=600)
        started = [(e["run_id"], e["months_done"]) for e in events if e["type"] == "started"]
        self.assertEqual(started, [("t143-a", 2)])          # resumed at its planned end, not skipped
        self.assertEqual(len(RunStore(run_dir).read_log("month")), 3)
        self.assertEqual(RunStore(run_dir).load_checkpoint()[0].outcome.get("type"), "survived")
        plan = json.loads((self.root / "batches" / "t143-first.json").read_text(encoding="utf-8"))
        self.assertEqual([it["status"] for it in plan["items"]], ["done"])


if __name__ == "__main__":
    unittest.main()
