"""T141: the democracy index registers what the government does (engine 24).

Before engine 24 the index was a fixed sum of the seven constitutional terms, so nothing a government did in force reached
it: it stood at 1.0 in every month of every recorded run (docs/DETECTOR_PRECISION.md, R4). Now the repressive acts in force
are penalties taken off that sum: arrests, emergency measures and party bans while they are in force, and an officers'
coup through the coup term. The constitutional terms are unchanged. The tests check each new lever on its own, that more
repression gives a lower index, that the index recovers when the acts end, that a run which is never repressive stays at
1.0, and that the history records the value the index gives. Scripted seats only; no server, no browser.
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import dilemmas, engine, plots, politics  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import democracy_index, new_world  # noqa: E402

COERCIVE = ("curfew", "police_powers", "movement_restrictions", "military_aid_civil")
EMERGENCY_MEASURES = COERCIVE + ("ration_enforcement", "fiscal_authority")


class FixedRng:
    """A stand-in for the month's random stream that always gives the same draw."""

    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


def _world(month=5):
    w = new_world(seed=1, months=36)
    w.month = month
    return w


def _arrests(level):
    def act(w):
        w.policy.arrests = level
    return act


def _measure(name, on=True):
    def act(w):
        dilemmas.set_emergency_measure(w, name, on, "A", "")
    return act


def _parties(value):
    def act(w):
        w.const.parties = value
    return act


def _constitution(field, raw):
    def act(w):
        politics._constitution(w, field, raw, "A")
    return act


# Each new repressive lever on its own, and the index it gives (the penalties are documented in world.py).
NEW_LEVERS = (
    ("arrests targeted", _arrests("targeted"), 0.95),
    ("arrests mass", _arrests("mass"), 0.90),
    ("emergency measure curfew", _measure("curfew"), 0.95),
    ("emergency measure police powers", _measure("police_powers"), 0.95),
    ("emergency measure movement restrictions", _measure("movement_restrictions"), 0.95),
    ("emergency measure military aid to the civil power", _measure("military_aid_civil"), 0.95),
    ("emergency measure ration enforcement", _measure("ration_enforcement"), 0.97),
    ("emergency measure fiscal authority", _measure("fiscal_authority"), 0.98),
    ("parties ban_opposition", _parties("ban_opposition"), 0.85),
    ("parties one_party", _parties("one_party"), 0.80),
)

# The levers the engine already read before engine 24. They must keep moving the index.
EXISTING_LEVERS = (
    ("press restricted", _constitution("press", "restricted"), 0.90),
    ("press censored", _constitution("press", "censored"), 0.80),
    ("election postponed to Month 50", _constitution("election_month", "50"), 0.84),
)


class EachRepressiveLeverMovesIt(unittest.TestCase):
    def test_each_new_repressive_lever_on_its_own_moves_the_index(self):
        for label, act, expected in NEW_LEVERS:
            with self.subTest(lever=label):
                w = _world()
                act(w)
                self.assertAlmostEqual(democracy_index(w), expected, places=9)

    def test_each_lever_the_engine_already_read_still_moves_the_index(self):
        for label, act, expected in EXISTING_LEVERS:
            with self.subTest(lever=label):
                w = _world()
                act(w)
                self.assertAlmostEqual(democracy_index(w), expected, places=9)

    def test_an_officers_coup_moves_the_index_through_the_politics_path(self):
        w = _world(month=12)
        w.mil.army.loyalty = 0.1          # unpaid and disloyal: the officers' conditions
        w.mil.army.arrears = 5.0
        politics._officers(w, FixedRng(0.0))  # the draw below 0.12 is the coup
        self.assertEqual(w.outcome.get("type"), "officers_coup")
        self.assertEqual(w.const.coup_month, 12)       # recorded the way a successful coup is
        self.assertAlmostEqual(democracy_index(w), 0.90, places=9)

    def test_an_officers_coup_moves_the_index_through_the_plot_path(self):
        w = _world(month=12)
        plots._coup(w)
        self.assertEqual(w.outcome.get("type"), "officers_coup")
        self.assertEqual(w.const.coup_month, 12)
        self.assertAlmostEqual(democracy_index(w), 0.90, places=9)


class MoreRepressionGivesALowerIndex(unittest.TestCase):
    def test_each_further_act_of_repression_lowers_the_index(self):
        w = _world()
        seen = [democracy_index(w)]
        for act in (_arrests("targeted"), _measure("curfew"), _arrests("mass"),
                    _parties("one_party"), _measure("police_powers")):
            act(w)
            seen.append(democracy_index(w))
        self.assertEqual(seen[0], 1.0)
        self.assertTrue(all(a > b for a, b in zip(seen, seen[1:])), seen)


class TheIndexRecoversWhenTheActsEnd(unittest.TestCase):
    def test_lifting_a_measure_and_ending_the_arrests_and_the_ban_restores_the_index(self):
        w = _world(month=5)
        dilemmas.set_emergency_measure(w, "curfew", True, "A", "")
        w.policy.arrests = "mass"
        w.const.parties = "ban_opposition"
        self.assertLess(democracy_index(w), 1.0)
        dilemmas.set_emergency_measure(w, "curfew", False, "A", "")
        w.policy.arrests = "none"
        w.const.parties = "multi_party"
        self.assertEqual(democracy_index(w), 1.0)

    def test_a_measure_counts_while_in_force_and_stops_counting_when_it_expires(self):
        w = _world(month=5)
        dilemmas.set_emergency_measure(w, "police_powers", True, "A", "")   # in force for Months 5 to 8
        self.assertAlmostEqual(democracy_index(w), 0.95, places=9)
        for month in range(5, 9):
            w.month = month
            dilemmas.apply_ongoing(w)
        self.assertAlmostEqual(democracy_index(w), 0.95, places=9)           # still in force in its last month
        w.month = 9
        dilemmas.apply_ongoing(w)                                            # expired
        self.assertNotIn("police_powers", w.institutions.get("emergency_measures") or {})
        self.assertEqual(democracy_index(w), 1.0)


class ARunThatIsNeverRepressiveStaysAtOne(unittest.TestCase):
    def test_a_scripted_run_that_never_represses_stays_at_one_in_every_month(self):
        # the default scripted council, seed 1: nothing in it ever sets an arrest, a measure, a party ban or a press law
        root = Path(tempfile.mkdtemp(prefix="karamaniya-e24-clean-"))
        try:
            shutil.copy(os.path.join(ROOT, "council.scripted.toml"), root)
            run_dir = new_run(config=str(root / "council.scripted.toml"), runs_dir=str(root / "runs"),
                              name="clean-6", months=6, seed=1, quiet=True, check=False)
            w, _council, _meta = RunStore(run_dir).load_checkpoint()
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertEqual(len(w.history), 6)
        for row in w.history:
            c = row["constitution"]
            with self.subTest(month=row["month"]):
                self.assertEqual(row["democracy"], 1.0)
                self.assertEqual(row["policy"].get("arrests"), "none")
                self.assertEqual((c["press"], c["assembly"], c["emergency"], c["minority"]),
                                 ("free", "free", False, "equal"))
                self.assertEqual(((row.get("v2") or {}).get("emergency_measures") or {}), {})
        self.assertEqual(w.const.parties, "multi_party")
        self.assertEqual(w.institutions.get("emergency_measures") or {}, {})


class TheIndexStaysOnItsScaleAndTheHistoryRecordsIt(unittest.TestCase):
    def test_every_lever_at_its_worst_leaves_the_index_at_zero_not_below(self):
        w = _world(month=12)
        _arrests("mass")(w)
        for name in EMERGENCY_MEASURES:
            _measure(name)(w)
        _parties("one_party")(w)
        for field, raw in (("press", "censored"), ("assembly", "banned"), ("emergency", "on"),
                           ("minority", "interned"), ("decision_rule", "head_decides"),
                           ("election_month", "none")):
            _constitution(field, raw)(w)
        w.const.coup_month = 12
        self.assertEqual(democracy_index(w), 0.0)

    def test_the_month_history_row_records_the_index_the_government_produced(self):
        w = _world(month=3)
        _arrests("targeted")(w)
        engine.snapshot(w)
        self.assertEqual(w.history[-1]["democracy"], democracy_index(w))


class TheR4DiagnosticStillRuns(unittest.TestCase):
    def test_the_r4_table_runs_and_shows_the_new_levers(self):
        # tools/detector_audit.py r4-index prints the index for each setting on a bare world. It must still run once the
        # index reads the policy and the emergency measures; before the fix it raised AttributeError on `policy`.
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import detector_audit  # noqa: E402
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(detector_audit.r4_index(), 0)
        table = {}
        for line in out.getvalue().splitlines():
            label, value = line.rsplit(" ", 1)
            table[label.strip()] = float(value)
        self.assertEqual(table["defaults"], 1.0)
        self.assertEqual(table["arrests mass"], 0.9)
        self.assertEqual(table["emergency measure curfew"], 0.95)
        self.assertEqual(table["parties one_party"], 0.8)


if __name__ == "__main__":
    unittest.main()
