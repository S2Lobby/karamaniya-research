"""What the control room's Live view is fed while a run goes: each seat's calls, the votes, the neighbours,
the month's pace and each member's own seat (engine 12)."""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import foreign, foreign_force, politics  # noqa: E402
from karamaniya.config import load_config  # noqa: E402
from karamaniya.council import _costly_votes, _neighbours_live  # noqa: E402
from karamaniya.gui import Controller, _tally, _tally_from_log  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")


def controller(tmp):
    c = Controller(Path(tmp), Path(tmp) / "runs")
    c._new_job("run", "live", 3)
    return c


class TheObserver(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-live-view-")
        self.c = controller(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def items(self, kind):
        return [i for i in self.c.live(0)["items"] if i["kind"] == kind]

    def test_a_call_brings_its_cost_its_pace_and_the_models_reasoning(self):
        c = self.c
        c.observer({"type": "call_start", "member": "B", "phase": "decision", "month": 0})
        c.observer({"type": "call_end", "member": "B", "phase": "decision", "month": 0, "ok": True, "spend": .2,
                    "latency_s": 12.5, "cost_usd": .015, "reasoning": "If I back M1 the officers turn."})
        c.observer({"type": "call_end", "member": "B", "phase": "decision", "month": 0, "ok": False, "spend": .2,
                    "latency_s": 3.0, "cost_usd": 0, "error": "timeout", "reasoning": ""})
        stats = c.live(0)["job"]["seat_stats"]["B"]
        self.assertEqual((stats["calls"], stats["failed"], stats["last_ok"]), (2, 1, False))
        self.assertAlmostEqual(stats["cost"], .015)
        self.assertEqual(stats["latencies"], [12.5, 3.0])
        thought = self.items("thought")
        self.assertEqual(len(thought), 1)                       # a call with no reasoning adds none
        self.assertEqual((thought[0]["member"], thought[0]["phase"], thought[0]["text"]),
                         ("B", "decision", "If I back M1 the officers turn."))

    def test_votes_are_tallied_with_the_audiences_and_the_word(self):
        motions = [{"id": "M1", "passed": True, "votes": {"A": "yes", "B": "no", "C": "abstain"}},
                   {"id": "M2", "passed": False, "votes": {"A": "yes", "B": "no", "C": "no"}},
                   {"id": "M3", "passed": False, "withdrawn": True, "votes": {}}]
        self.c.observer({"type": "resolved", "month": 0, "motions": motions, "costly": {"M1": ["A"]},
                         "clashes": [{"member": "B", "motion": "M2", "stance": "support", "vote": "no"}]})
        item = self.items("resolved")[0]
        self.assertEqual(item["costly"], {"M1": ["A"]})
        self.assertEqual(item["motions"][0]["votes"]["B"], "no")
        tally = self.c.live(0)["job"]["tally"]
        self.assertEqual(tally["A"], {"voted": 2, "yes": 2, "no": 0, "abstain": 0, "losing_side": 1, "costly": 1,
                                      "clashes": 0})
        self.assertEqual((tally["B"]["losing_side"], tally["B"]["clashes"]), (1, 1))
        self.assertEqual(tally["C"]["abstain"], 1)

    def test_the_neighbours_month_and_who_played_them(self):
        self.c.observer({"type": "foreign_call_start", "actor": "veleria", "month": 0, "seat": "fixed-sonnet"})
        self.c.observer({"type": "foreign_call_end", "actor": "veleria", "month": 0, "seat": "fixed-sonnet",
                         "ok": True, "spend": 0, "reasoning": "Press while they are weak."})
        actors = {"veleria": {"temperament": "hawk", "acts": [{"type": "deploy_to_border", "front": "north"}]},
                  "war": {"on": False}}
        self.c.observer({"type": "neighbours", "month": 0, "actors": actors})
        job = self.c.live(0)["job"]
        self.assertEqual(job["neighbours"], actors)
        self.assertEqual(job["foreign_seats"], {"veleria": "fixed-sonnet"})
        self.assertEqual(self.items("neighbours")[0]["seats"], {"veleria": "fixed-sonnet"})
        self.assertEqual(self.items("thought")[0]["actor"], "veleria")

    def test_the_first_month_says_whether_a_questionnaire_came_first(self):
        self.c.observer({"type": "month_start", "month": 0})
        self.assertFalse(self.items("month")[0]["survey"])      # no answers to ask the inspector for
        c = controller(self.tmp)
        c.observer({"type": "survey"})
        c.observer({"type": "month_start", "month": 0})
        c.observer({"type": "month_start", "month": 1})
        months = [i for i in c.live(0)["items"] if i["kind"] == "month"]
        self.assertEqual([m["survey"] for m in months], [True, False])

    def test_the_month_is_timed_and_its_end_brings_seats_and_removals(self):
        c = self.c
        c.observer({"type": "month_start", "month": 0})
        c.observer({"type": "call_start", "member": "A", "phase": "decision", "month": 0})
        live = c.live(0)["job"]
        self.assertEqual(live["phase"], "decision")
        self.assertGreaterEqual(live["phase_elapsed"], 0)
        self.assertGreaterEqual(live["month_elapsed"], 0)
        time.sleep(.05)
        c.observer({"type": "month_done", "months_done": 1, "spend": 0, "events": ["War."],
                    "events_detail": [{"kind": "war", "text": "War.", "importance": 3}],
                    "seats": {"A": {"band": "close"}}, "removed": {"E": "lost_seat"}, "election_month": 35})
        job = c.live(0)["job"]
        self.assertEqual(len(job["month_times"]), 1)
        self.assertGreater(job["month_times"][0], 0)
        self.assertEqual((job["seats"], job["removed"], job["election_month"]),
                         ({"A": {"band": "close"}}, {"E": "lost_seat"}, 35))
        self.assertEqual(self.items("month_done")[0]["events_detail"][0]["kind"], "war")


class Summaries(unittest.TestCase):
    def test_costly_votes_are_the_net_losses(self):
        rows = [{"member": "A", "motion": "M1", "delta": -.03}, {"member": "A", "motion": "M1", "delta": .01},
                {"member": "B", "motion": "M1", "delta": .02}, {"member": "C", "motion": "M2", "delta": -.001}]
        self.assertEqual(_costly_votes(rows), {"M1": ["A"], "M2": ["C"]})

    def test_the_neighbours_summary_names_refused_acts(self):
        w = new_world(3, 36)
        w.foreign = foreign.initial_state(w.seed)
        decisions = {"veleria": {"actions": [{"type": "deploy_to_border", "front": "north", "troops": 9000, "magnitude": .5},
                                             {"type": "invade", "front": "east", "aim": "full", "magnitude": 1.0}],
                                 "strategy": "pressure"}}
        foreign._apply_cabinet_decisions(w, foreign.positions(w), decisions)
        out = _neighbours_live(w, w.month, decisions)
        acts = out["veleria"]["acts"]
        self.assertEqual(acts[0], {"type": "deploy_to_border", "front": "north", "troops": 9000})
        self.assertIn("needs at least", acts[1]["refused"])
        self.assertEqual(out["veleria"]["border"]["north"], 9000)
        self.assertTrue(out["veleria"]["decided"])
        self.assertEqual(out["veleria"]["temperament"], foreign_force.draw_temperament("veleria", 3))
        self.assertFalse(out["war"]["on"])

    def test_a_seats_band_matches_the_delegates_wording(self):
        w = new_world(5, 36)
        outlooks = politics.seat_outlooks(w)
        self.assertEqual(sorted(outlooks), sorted(m.id for m in w.active_members()))
        for mid, o in outlooks.items():
            self.assertEqual(o["band"], politics.seat_band(politics.seat_estimate(w, mid)))
        w.const.elected = True
        self.assertEqual(politics.seat_outlooks(w), {})


class AScriptedRunFeedsTheLiveView(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-live-run-")
        cls.events = []
        cfg = load_config(CONFIG)
        cfg = {**cfg, "run": {**cfg["run"], "survey": False}}
        cls.path = new_run(cfg, runs_dir=cls.tmp, name="live", months=3, quiet=True, observer=cls.events.append)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def of(self, kind):
        return [e for e in self.events if e.get("type") == kind]

    def test_calls_carry_pace_cost_and_reasoning(self):
        ends = self.of("call_end")
        self.assertTrue(ends)
        for e in ends:
            self.assertIn("latency_s", e)
            self.assertIn("cost_usd", e)
            self.assertIn("reasoning", e)

    def test_votes_neighbours_and_the_months_end(self):
        resolved = self.of("resolved")
        self.assertEqual(len(resolved), 3)
        self.assertTrue(any(m.get("votes") for r in resolved for m in r["motions"]))
        for r in resolved:
            self.assertIsInstance(r["costly"], dict)
            self.assertIsInstance(r["clashes"], list)
        neighbours = self.of("neighbours")
        self.assertEqual([n["month"] for n in neighbours], [0, 1, 2])
        self.assertTrue({"veleria", "dorsania", "war"} <= set(neighbours[0]["actors"]))
        done = self.of("month_done")
        self.assertEqual(len(done), 3)
        for d in done:
            self.assertTrue(all({"kind", "text", "importance"} <= set(e) for e in d["events_detail"]))
            self.assertIsInstance(d["removed"], dict)
        self.assertTrue(done[0]["seats"])                        # the Charter election is still to come
        self.assertEqual(done[0]["election_month"], 35)

    def test_the_tally_read_back_from_the_log_is_the_live_one(self):
        live = {}
        for r in self.of("resolved"):
            _tally(live, r["motions"], r["costly"], r["clashes"])
        self.assertTrue(live)
        self.assertEqual(_tally_from_log(self.path), live)


if __name__ == "__main__":
    unittest.main()
