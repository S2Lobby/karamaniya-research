"""World engine 17: the engine watch (karamaniya/watch.py), which says what moved the crown's prices and national
approval each month and flags a mechanism that looks wrong or dominates.

In run 20261010-070501-seed1 prices across the crown rose 42% in nine months and approval fell from 0.45 to 0.33.
Every statement or offer of talks by a neighbour's cabinet was charged against that neighbour's real output, so two
shrinking neighbours inflated the shared crown, and nothing reported it. These tests hold the watch to three things:
the recorded decomposition is the economy's own arithmetic, recording changes no value the simulation computes, and
the flags name a neighbour when its output is cut with nothing to account for it. Nothing here is ever shown to the
delegates.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import engine, foreign, rivals, watch  # noqa: E402
from karamaniya.analytics import run_metrics  # noqa: E402
from karamaniya.report import build_report, report_data  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")


def world(seed: int = 5, version: int | None = None):
    w = new_world(seed, 36, agent_architecture_version=version)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def month(w, n=1):
    for _ in range(n):
        engine.begin_month(w)
        engine.step(w)


def cut_veleria(w, share=0.04):
    """The bad engine: Veleria's real output is charged a share of itself at the start of every month."""
    w.rivals["veleria"].gdp_real *= 1 - share


class TheDecompositionIsExact(unittest.TestCase):
    def test_contributions_add_up_to_the_change_in_the_target(self):
        w = world()
        month(w, 3)
        entries = [e for e in watch.state(w)["months"] if "price" in e]
        self.assertEqual([e["month"] for e in entries], [1, 2])
        for e in entries:
            total = sum(e["price"]["money"].values()) + sum(e["price"]["output"].values()) + e["price"]["velocity"]
            # The contributions are shares of the totals and the target moves in logs. ln(1 + x) differs from x
            # by about x**2 / 2, so for monthly moves of a few per cent the sum misses the logged change by a few
            # millionths. The bound is 1e-3, which leaves room for the bigger moves of a bad-engine run.
            self.assertLess(abs(total - e["target_change"]), 1e-3, f"month {e['month']}")

    def test_the_named_opinion_terms_add_up_to_the_mean_target(self):
        w = world()
        month(w, 3)
        entries = [e for e in watch.state(w)["months"] if "opinion" in e]
        self.assertEqual(len(entries), 3)
        for e in entries:
            # Each term is recomputed from the same values as the target, so their sum is the target to rounding.
            self.assertLess(abs(sum(e["opinion"].values()) - e["opinion_target"]), 1e-9, f"month {e['month']}")

    def test_the_tally_weights_each_group_by_its_population(self):
        tally = watch.OpinionTally()
        tally.add(1.0, {"legitimacy": 0.2}, 0.4)
        tally.add(3.0, {"legitimacy": -0.4}, 0.0)
        means, target = tally.means()
        self.assertAlmostEqual(means["legitimacy"], (0.2 - 1.2) / 4.0)
        self.assertAlmostEqual(target, 0.1)

    def test_a_currency_launch_starts_a_new_record_instead_of_a_contribution(self):
        w = world()
        w.econ.currency_launch = 1
        month(w, 3)
        self.assertEqual(w.zone_of("karamaniya").id, "karam")
        by_month = {e["month"]: e for e in watch.state(w)["months"]}
        self.assertNotIn("price", by_month[1])     # the zone changed this month, so nothing is compared
        self.assertIn("price", by_month[2])


class RecordingChangesNothing(unittest.TestCase):
    def test_with_the_recorders_off_every_computed_value_is_the_same(self):
        recorded, silent = world(), world()
        month(recorded, 3)
        with mock.patch.object(watch, "record_price"), mock.patch.object(watch, "record_opinion"), \
                mock.patch.object(watch, "evaluate"):
            month(silent, 3)
        self.assertTrue(watch.state(recorded)["months"])          # the recorder ran in one world ...
        self.assertEqual(watch.state(silent)["months"], [])        # ... and was really off in the other
        self.assertEqual(recorded.zone_of("karamaniya").price, silent.zone_of("karamaniya").price)
        self.assertEqual([p.approval for p in recorded.pops], [p.approval for p in silent.pops])
        self.assertEqual([p.indep for p in recorded.pops], [p.indep for p in silent.pops])
        self.assertEqual([h["approval"] for h in recorded.history], [h["approval"] for h in silent.history])

    def test_a_version_one_world_records_nothing(self):
        w = world(version=1)
        month(w, 2)
        self.assertNotIn("engine_watch", w.institutions)

    def test_the_record_is_plain_json_and_survives_a_save_and_load(self):
        w = world()
        month(w, 3)
        before = json.loads(json.dumps(w.to_dict()["institutions"]["engine_watch"]))
        self.assertEqual(before, json.loads(json.dumps(watch.state(w))))
        resumed = type(w).from_dict(json.loads(json.dumps(w.to_dict(), default=str)))  # as storage.py writes it
        self.assertEqual(watch.state(resumed), watch.state(w))

    def test_only_the_last_sixty_months_are_kept(self):
        w = world()
        tally = watch.OpinionTally()
        tally.add(1.0, {"baseline": 0.52}, 0.52)
        for m in range(70):
            w.month = m
            watch.record_opinion(w, tally)
        months = watch.state(w)["months"]
        self.assertEqual(len(months), watch.KEEP_MONTHS)
        self.assertEqual(months[-1]["month"], 69)
        self.assertEqual(months[0]["month"], 10)


class FlagsOnABadEngine(unittest.TestCase):
    def test_a_neighbour_whose_output_is_cut_is_flagged_by_name(self):
        w = world()
        for _ in range(5):
            cut_veleria(w)
            month(w)
        self.assertFalse(w.dip.war)
        self.assertFalse(w.foreign["embargoes"])
        flags = watch.state(w)["flags"]
        fall = [f for f in flags if f["kind"] == "rival_output_fall"]
        self.assertEqual(fall[0]["month"], 1)                    # the first month only sets the baseline
        self.assertIn("Veleria's output fell", fall[0]["text"])
        self.assertIn("with no war, embargo or disaster: check the engine.", fall[0]["text"])
        self.assertTrue(all("Veleria" in f["text"] for f in fall))
        inflation = [f for f in flags if f["kind"] == "unexplained_zone_inflation"]
        self.assertTrue(inflation)
        self.assertIn("The largest contributor was Veleria's output", inflation[0]["text"])

    def test_no_month_and_kind_is_flagged_twice(self):
        w = world()
        for _ in range(5):
            cut_veleria(w)
            month(w)
        keys = [(f["month"], f["kind"]) for f in watch.state(w)["flags"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_a_dominant_driver_is_flagged_by_name_when_one_term_holds_the_move(self):
        w = world()
        w.month = 3
        rec = watch.state(w)
        for m in (1, 2, 3):
            rec["months"].append({"month": m, "price": {
                "money": {"veleria": 0.001, "dorsania": 0.0005, "karamaniya": 0.0005},
                "output": {"veleria": 0.02, "dorsania": 0.0, "karamaniya": 0.0}, "velocity": 0.001}})
        watch.evaluate(w)
        dominant = [f for f in rec["flags"] if f["kind"] == "dominant_driver"]
        self.assertEqual(len(dominant), 1)
        self.assertIn("Veleria's output was at least", dominant[0]["text"])
        self.assertIn("Months 2 to 4", dominant[0]["text"])

    def test_a_month_below_the_share_means_no_dominant_driver(self):
        w = world()
        w.month = 3
        rec = watch.state(w)
        # The middle month's output is a quarter of the absolute sum (0.001 of 0.004), so the run of three is broken.
        shares = (0.02, 0.001, 0.02)
        for m, out in zip((1, 2, 3), shares):
            rec["months"].append({"month": m, "price": {
                "money": {"veleria": 0.001, "dorsania": 0.0005, "karamaniya": 0.0005},
                "output": {"veleria": out, "dorsania": 0.0, "karamaniya": 0.0}, "velocity": 0.001}})
        watch.evaluate(w)
        self.assertFalse([f for f in rec["flags"] if f["kind"] == "dominant_driver"])

    def test_a_war_an_embargo_or_a_disaster_explains_a_neighbours_fall(self):
        # Each step is a different month, so a flag of the same kind is never hidden by the one-per-month rule.
        w = world()
        watch.evaluate(w)                          # Month 1: sets the baseline
        w.month = 1
        w.rivals["veleria"].gdp_real *= 0.95
        w.rivals["dorsania"].gdp_real *= 0.95
        w.dip.war = True                           # a war touches every rival, so the fall is explained
        watch.evaluate(w)
        self.assertFalse([f for f in watch.state(w)["flags"] if f["kind"] == "rival_output_fall"])
        # The war is over and a coal embargo by Veleria explains its fall; Dorsania's is still unexplained.
        w.month = 2
        w.dip.war = False
        w.dip.coal_embargo = 0.2
        w.rivals["veleria"].gdp_real *= 0.95
        w.rivals["dorsania"].gdp_real *= 0.95
        watch.evaluate(w)
        text = [f["text"] for f in watch.state(w)["flags"] if f["kind"] == "rival_output_fall"]
        self.assertEqual(len(text), 1)
        self.assertIn("Dorsania's output fell", text[0])
        self.assertNotIn("Veleria", text[0])
        # A disaster in Veleria's own region explains its fall; Dorsania does not fall this month.
        w.month = 3
        w.dip.coal_embargo = 0.0
        w.dilemmas = {"active": [{"region": "arven", "tags": ["weather", "disaster"]}]}
        w.rivals["veleria"].gdp_real *= 0.95
        watch.evaluate(w)
        self.assertEqual([f["month"] for f in watch.state(w)["flags"] if f["kind"] == "rival_output_fall"], [2])
        # Without the disaster the same fall is flagged in Veleria's name.
        w.month = 4
        w.dilemmas = {"active": []}
        w.rivals["veleria"].gdp_real *= 0.95
        watch.evaluate(w)
        self.assertIn("Veleria's output fell", watch.state(w)["flags"][-1]["text"])


class ApprovalSlide(unittest.TestCase):
    def history(self, levels, opinions):
        w = world()
        w.month = len(levels) - 1
        w.history = [{"month": i, "approval": a} for i, a in enumerate(levels)]
        rec = watch.state(w)
        rec["months"] = [{"month": i, "opinion": o} for i, o in enumerate(opinions)]
        return w

    def test_three_falls_in_a_row_are_flagged_and_the_worst_term_is_named(self):
        opinions = [{"baseline": .52, "legitimacy": .05, "income": .10},
                    {"baseline": .52, "legitimacy": .03, "income": .09},
                    {"baseline": .52, "legitimacy": .01, "income": .08},
                    {"baseline": .52, "legitimacy": -.01, "income": .10}]
        w = self.history([.50, .49, .47, .44], opinions)
        watch.evaluate(w)
        slide = [f for f in watch.state(w)["flags"] if f["kind"] == "approval_slide"]
        self.assertEqual(len(slide), 1)
        self.assertIn("National approval fell in each of Months 2 to 4, from 50.0% to 44.0%.", slide[0]["text"])
        self.assertIn("The opinion term that worsened most was legitimacy (-0.060).", slide[0]["text"])

    def test_a_flat_history_is_not_flagged(self):
        w = self.history([.50, .50, .50, .50], [{"baseline": .52}] * 4)
        watch.evaluate(w)
        self.assertFalse([f for f in watch.state(w)["flags"] if f["kind"] == "approval_slide"])

    def test_falls_below_the_threshold_are_not_flagged(self):
        w = self.history([.500, .496, .492, .488], [{"baseline": .52}] * 4)
        watch.evaluate(w)
        self.assertFalse([f for f in watch.state(w)["flags"] if f["kind"] == "approval_slide"])


class Summaries(unittest.TestCase):
    def test_the_summary_gives_the_three_largest_contributions_and_moves(self):
        w = world()
        month(w, 3)
        last = watch.summary(w)["last_month"]
        self.assertEqual(last["month"], 2)          # the months stepped were 0, 1 and 2
        self.assertEqual(len(last["price"]), 3)
        sizes = [abs(p["value"]) for p in last["price"]]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertEqual(len(last["opinion"]), 3)
        self.assertTrue(all(o["change"] == round(o["now"] - o["before"], 12) for o in last["opinion"]))

    def test_the_analytics_carry_the_flags_and_no_record_is_empty(self):
        bare = run_metrics(new_world(1).to_dict(), [])
        self.assertEqual(bare["engine_watch"], {"flags": [], "last_month": None})
        w = world()
        for _ in range(5):
            cut_veleria(w)
            month(w)
        carried = run_metrics(w.to_dict(), [])["engine_watch"]
        self.assertTrue(any(f["kind"] == "rival_output_fall" for f in carried["flags"]))
        self.assertIsNotNone(carried["last_month"])

    def test_the_report_view_lists_the_flags_newest_first(self):
        w = world()
        for _ in range(5):
            cut_veleria(w)
            month(w)
        view = watch.report_view(watch.state(w), w.names)
        months = [f["month"] for f in view["flags"]]
        self.assertEqual(months, sorted(months, reverse=True))
        self.assertEqual([r["month"] for r in view["months"]], list(range(5)))


class TheReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-watch-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_report_has_the_section_and_a_flag(self):
        real = rivals.monthly

        def bad(w):
            cut_veleria(w)
            return real(w)

        with mock.patch.object(rivals, "monthly", new=bad):
            path = new_run(CONFIG, runs_dir=self.tmp, name="bad", months=5, quiet=True)
        store = RunStore(path)
        html_path = build_report(store)
        html = html_path.read_text(encoding="utf-8")
        self.assertIn('id="engine-watch"', html)
        self.assertIn("Engine watch", html)
        flags = report_data(store)["engine_watch"]["flags"]
        self.assertTrue(any(f["kind"] == "rival_output_fall" and "Veleria's output fell" in f["text"] for f in flags))
        self.assertIn("Veleria's output fell", html)
        analytics_json = json.loads((store.path / "analytics.json").read_text(encoding="utf-8"))
        # analytics.json holds the run_metrics block under analytics.metrics, beside political, council and the rest.
        self.assertTrue(analytics_json["analytics"]["metrics"]["engine_watch"]["flags"])


if __name__ == "__main__":
    unittest.main()
