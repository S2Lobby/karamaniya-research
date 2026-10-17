"""E4: a finished batch row stays finished in the control room's batch queue.

The batch's rows were written by its own display: a poll that landed while a row's result was being saved made
that row "running", the save kept it, and once the batch was idle the display showed it "pending" for good.
These tests call the Controller's methods directly, with scripted seats and one to three month runs: no server
and no browser.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya.council import Council, RunPaused  # noqa: E402
from karamaniya.gui import Controller  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _RoomDied(BaseException):
    """The room's process dying partway through a run. A BaseException, so the worker's own handlers do not
    catch it: the batch keeps whatever it had written at that point, as a killed process would leave it."""


def _row(name, months=1):
    return {"name": name, "council": "council.scripted.toml", "seed": 901, "months": months,
            "framing": "", "severity": "", "scenario": ""}


def _record(controller):
    """Keep the run events the worker emits, and pass each one on to the controller as before."""
    events = []

    def observe(event):
        events.append(event)
        Controller.observer(controller, event)

    controller.observer = observe
    return events


def _poll_as_rows_end(controller):
    """Let a GET /api/batch land at the moment a row's result is saved, while the batch still names that row as
    the run in progress. The page polls about once a second; this makes that moment happen on every run."""
    save = controller._batch_persist

    def save_after_a_poll():
        if controller.batch.get("state") == "running":
            controller.batch_state()
        save()

    controller._batch_persist = save_after_a_poll


class BatchRowsStayFinished(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="karamaniya-e4-"))
        shutil.copy(os.path.join(HERE, "council.scripted.toml"), self.root)
        self.runs = self.root / "runs"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def stored(self, batch):
        return json.loads((self.root / "batches" / f"{batch}.json").read_text(encoding="utf-8"))["items"]

    def run_batch(self, controller, batch, rows):
        controller.batch_start({"name": batch, "items": rows})
        controller.thread.join(timeout=600)
        self.assertFalse(controller.thread.is_alive(), "the batch did not finish in time")

    def test_no_row_stays_running_when_a_poll_lands_as_it_ends(self):
        c = Controller(self.root, self.runs)
        _poll_as_rows_end(c)
        self.run_batch(c, "e4-ends", [_row("e4-ends-a"), _row("e4-ends-b")])
        # the first row (not the last) and the last row both read "done", after the batch and on disk
        self.assertEqual([it["status"] for it in c.batch_state()["items"]], ["done", "done"])
        self.assertEqual([it["status"] for it in self.stored("e4-ends")], ["done", "done"])

    def test_a_row_whose_run_pauses_keeps_its_paused_status(self):
        c = Controller(self.root, self.runs)
        _poll_as_rows_end(c)

        def pause(council):
            # what a seat's usage limit does to a run: the month is abandoned and the run is paused
            raise RunPaused("A", "scripted-democrat", "usage limit reached (test)")

        with patch.object(Council, "run_month", pause):
            self.run_batch(c, "e4-pause", [_row("e4-pause-a")])
        self.assertEqual([it["status"] for it in self.stored("e4-pause")], ["paused"])
        self.assertEqual([it["status"] for it in c.batch_state()["items"]], ["paused"])

        # the paused row resumes from its checkpoint when the batch runs again, and finishes
        self.run_batch(c, "e4-pause", [_row("e4-pause-a")])
        self.assertEqual([it["status"] for it in self.stored("e4-pause")], ["done"])
        self.assertEqual(len(RunStore(self.runs / "e4-pause-a").read_log("month")), 1)

    def test_reading_the_batch_does_not_write_into_its_rows(self):
        c = Controller(self.root, self.runs)
        c.batch = {"name": "e4-read", "state": "running", "current_run": "e4-read-a", "items": [
            {"name": "e4-read-a", "status": "done"},
            {"name": "e4-read-b", "status": "running"}]}
        view = c.batch_state()
        self.assertEqual([it["status"] for it in view["items"]], ["done", "pending"])
        self.assertEqual([it["status"] for it in c.batch["items"]], ["done", "running"])

    def test_room_restart_shows_the_killed_row_pending_and_resumes_it_where_it_stopped(self):
        rows = [_row("e4-kill-a", months=1), _row("e4-kill-b", months=3)]
        c = Controller(self.root, self.runs)
        real_month = Council.run_month

        def die_in_month_three(council):
            if council.w.month == 2:
                raise _RoomDied()
            return real_month(council)

        died = []
        with patch.object(Council, "run_month", die_in_month_three), \
                patch.object(threading, "excepthook", lambda args: died.append(args.exc_type)):
            c.batch_start({"name": "e4-kill", "items": rows})
            c.thread.join(timeout=600)
        self.assertEqual(died, [_RoomDied])             # the worker died in row b's third month
        # the room restarts: a fresh controller reads the same batch file
        fresh = Controller(self.root, self.runs)
        view = fresh.batch_state()
        self.assertEqual([it["status"] for it in view["items"]], ["done", "pending"])
        events = _record(fresh)
        self.run_batch(fresh, "e4-kill", view["items"])
        started = [(e["run_id"], e["months_done"]) for e in events if e["type"] == "started"]
        self.assertEqual(started, [("e4-kill-b", 2)])   # row a is not launched again; row b resumes at index 2, not 0
        self.assertEqual([e["month"] for e in events if e["type"] == "month_start"], [2])
        self.assertEqual(len(RunStore(self.runs / "e4-kill-b").read_log("month")), 3)
        self.assertEqual([it["status"] for it in self.stored("e4-kill")], ["done", "done"])

    def test_a_finished_row_stored_as_pending_is_not_run_again(self):
        c = Controller(self.root, self.runs)
        self.run_batch(c, "e4-again", [_row("e4-again-a")])
        path = self.root / "batches" / "e4-again.json"
        plan = json.loads(path.read_text(encoding="utf-8"))
        plan["items"][0]["status"] = "pending"          # what the stuck display would have left behind
        path.write_text(json.dumps(plan), encoding="utf-8")
        fresh = Controller(self.root, self.runs)
        events = _record(fresh)
        self.run_batch(fresh, "e4-again", fresh.batch_state(name="e4-again")["items"])
        self.assertEqual([e for e in events if e["type"] == "started"], [])   # the complete run is not started again
        self.assertEqual([it["status"] for it in self.stored("e4-again")], ["done"])


if __name__ == "__main__":
    unittest.main()
