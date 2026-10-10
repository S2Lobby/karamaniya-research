"""World engine 18: a resentful service carries out its orders badly, and a bitter officer corps plots (plots.py).

In run 20261010-070501-seed1 the army stayed at 28,000 against a Union army of 100,000, the Army minister volunteered
his border post's records to a joint inquiry with the Union, and army loyalty rose all the same. Engine 17 gave the
ministries grievances that drag loyalty and morale, but nothing stood for an officer corps that resented the government:
the officers' coup needed unpaid soldiers or a vacant army office, and a resentful police carried out every order as
before. These tests pin what a grievance costs an office's capacity, the plot that forms and fades with it, the special
branch that finds it and the report the Interior minister gets, the coup a strong plot can end the run with, and the
rule that a world from before agent architecture 2 sees none of it.
"""
import copy
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import agents, engine, foreign, intelligence, ministries, plots, staff, standing  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

OLD_INTERIOR = ("unrest_outlook", "protest_turnout", "police_loyalty", "foreign_backing")
DETECTED_SEED = 5       # the special branch finds the plot that forms in Month 1
COUP_SEED = 1           # a strong plot's officers act in Month 1
OLD_RULE_SEED = 2       # the old officers' coup fires in Month 3, with the army office vacant and loyalty low


def world(seed: int = 5, version: int | None = None):
    w = new_world(seed, 36, agent_architecture_version=version)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    for m in w.members:                      # the audiences a seat carries once its offices are set (agents.py)
        m.agent_state["constituencies"] = agents.audiences_for(w, m.id)
    return w


def month(w, n=1):
    for _ in range(n):
        engine.begin_month(w)
        engine.step(w)


def no_general_staff():
    # The General Staff's standing request would add its own grievance in a new world (staff.py); these tests
    # are about one grievance and what it does.
    return mock.patch.object(staff, "request", return_value=None)


def grieve(w, loyalty: float, grievance: float = .3):
    """The army holds this grievance against the government and its loyalty to the state is at this level."""
    ministries.aggrieve(w, "army", grievance, "a joint inquiry with the Union into a shooting on its border")
    w.mil.army.loyalty = loyalty


def interior_reports(w) -> dict:
    return {r["subject"]: r for r in intelligence.generate(w) if r["office"] == "interior"}


def events_of(events, kind: str) -> list:
    return [e for e in events if e["kind"] == kind]


class ResentfulMinistriesImplementLess(unittest.TestCase):
    def test_a_full_grievance_costs_the_army_eighteen_points_of_capacity(self):
        base, hit = world(), world()
        ministries.aggrieve(hit, "army", .3, "test")
        drop = standing.update_capacity(base)["army"] - standing.update_capacity(hit)["army"]
        self.assertAlmostEqual(drop, .18, places=2)          # CAPACITY_DRAG (.6) times a full .3 grievance

    def test_the_navy_and_the_police_are_dragged_and_the_other_offices_are_not(self):
        base, hit = world(), world()
        for office in ("navy", "interior"):
            ministries.aggrieve(hit, office, .3, "test")
        a, b = standing.update_capacity(base), standing.update_capacity(hit)
        self.assertAlmostEqual(a["navy"] - b["navy"], .18, places=2)
        self.assertAlmostEqual(a["interior"] - b["interior"], .18, places=2)
        for office in ("head", "treasury", "army"):
            self.assertEqual(a[office], b[office], office)

    def test_a_version_one_world_is_not_dragged(self):
        base, hit = world(version=1), world(version=1)
        ministries.aggrieve(hit, "army", .3, "test")
        self.assertEqual(standing.update_capacity(base)["army"], standing.update_capacity(hit)["army"])


class ThePlotForms(unittest.TestCase):
    def test_it_forms_at_grievance_point_two_with_loyalty_point_four(self):
        w = world()
        grieve(w, loyalty=.4, grievance=.2)
        plots.monthly(w)
        plot = plots.current(w)
        self.assertEqual(plot["since"], w.month)
        self.assertAlmostEqual(plot["strength"], plots.GROWTH + plots.GROWTH_GRIEVANCE * .02 / plots.GRIEVANCE_SPAN,
                               places=3)
        # The branch may find it in the month it forms (seed 5 does): a found plot has counted one month.
        self.assertEqual(plot["months_detected"], 1 if plot["detected"] else 0)
        formed = events_of(w.events, "officers_plot")
        self.assertEqual([(e["public"], e["importance"]) for e in formed], [(False, 1)])

    def test_nothing_forms_below_the_grievance_line_or_with_a_loyal_army(self):
        for grievance, loyalty in ((.17, .4), (.3, .5), (.3, .6)):
            with self.subTest(grievance=grievance, loyalty=loyalty):
                w = world()
                grieve(w, loyalty=loyalty, grievance=grievance)
                plots.monthly(w)
                self.assertIsNone(plots.current(w))
                self.assertEqual(events_of(w.events, "officers_plot"), [])

    def test_it_grows_month_by_month_while_both_hold(self):
        w = world()
        grieve(w, loyalty=.4, grievance=.2)
        growth = plots.GROWTH + plots.GROWTH_GRIEVANCE * .02 / plots.GRIEVANCE_SPAN
        seen = []
        for _ in range(4):                   # four months stay under COUP_STRENGTH, so no coup can be drawn
            plots.monthly(w)
            seen.append(plots.strength(w))
            w.month += 1
        for k, got in enumerate(seen, 1):
            self.assertAlmostEqual(got, growth * k, places=3)
        self.assertLess(seen[-1], plots.COUP_STRENGTH)

    def test_its_strength_is_capped_at_one(self):
        w = world()
        grieve(w, loyalty=.4, grievance=.3)  # the fastest growth: .40 a month
        with mock.patch.object(plots, "_coup"):       # hold the officers back, so only the cap is measured
            for _ in range(3):
                plots.monthly(w)
                w.month += 1
        self.assertEqual(plots.strength(w), 1.0)
        self.assertFalse(w.ended())

    def test_it_fades_and_dissolves_once_either_condition_lapses(self):
        def answer_the_grievance(w):
            ministries.soothe(w, "army", .3, "the government acting on the General Staff's request")

        def restore_loyalty(w):
            w.mil.army.loyalty = .6

        for name, lapse in (("the grievance answered", answer_the_grievance),
                            ("the army's loyalty restored", restore_loyalty)):
            with self.subTest(name):
                w = world()
                grieve(w, loyalty=.4, grievance=.2)
                for _ in range(3):
                    plots.monthly(w)
                    w.month += 1
                start = plots.strength(w)
                lapse(w)
                plots.monthly(w)
                w.month += 1
                self.assertAlmostEqual(plots.strength(w), start * plots.FADE, places=3)
                months = 1
                while plots.current(w) is not None:
                    plots.monthly(w)
                    w.month += 1
                    months += 1
                    self.assertLess(months, 20)
                self.assertGreaterEqual(months, 4)     # a plot does not vanish in a month


class ThePlotIsFound(unittest.TestCase):
    def test_the_special_branch_finds_a_forming_plot_with_a_fixed_seed(self):
        w = world(DETECTED_SEED)
        grieve(w, loyalty=.4)
        with no_general_staff():
            month(w)
        plot = plots.current(w)
        self.assertTrue(plots.detected(w))
        self.assertEqual(plot["months_detected"], 1)
        self.assertEqual([(e["public"], e["importance"]) for e in events_of(w.last_events, "officers_plot_detected")],
                         [(False, 2)])

    def test_the_interior_holder_gets_the_report_only_once_the_branch_has_found_the_plot(self):
        w = world(DETECTED_SEED)
        grieve(w, loyalty=.4)
        with no_general_staff():
            intelligence.generate(w)                        # Month 1, before any plot
            self.assertNotIn("Special branch", intelligence.office_context(w, "C"))
            month(w)                                        # the plot forms in Month 1 and is found
            intelligence.generate(w)                        # Month 2: the branch's report reaches the holder
        self.assertIn("Special branch: officers in Army Command are discussing removing the government",
                      intelligence.office_context(w, "C"))
        self.assertNotIn("Special branch", intelligence.office_context(w, "A"))
        self.assertNotIn("Special branch", intelligence.office_context(w, "B"))

    def test_the_report_is_low_confidence_and_states_the_strength_out_of_one_hundred(self):
        w = world(DETECTED_SEED)
        grieve(w, loyalty=.4)
        with no_general_staff():
            month(w)
            report = interior_reports(w)["officers_plot"]
        self.assertEqual(report["id"], f"R{w.month + 1}-INT5")
        self.assertEqual(report["confidence"], "low")
        self.assertEqual(report["truth"], round(100 * plots.strength(w), 2))
        self.assertIn(f"the plot is assessed at {report['low']:.0f}-{report['high']:.0f}/100 of what it would need to act",
                      report["text"])
        self.assertTrue(report["text"].endswith("Confidence: low."), report["text"])

    def test_it_is_alarming_from_fifty(self):
        self.assertTrue(intelligence._alarming("officers_plot", 50))
        self.assertFalse(intelligence._alarming("officers_plot", 49.9))

    def test_the_four_older_interior_reports_keep_their_ids_and_text(self):
        w = world(DETECTED_SEED)
        w.institutions["plot"] = {"since": 0, "strength": .6, "detected": True, "months_detected": 1}
        w.tuning = {"intelligence": {"contested": False}}    # a contested reading can add a report to the office
        without = copy.deepcopy(w)
        with mock.patch.dict(intelligence.SUBJECTS, {"interior": OLD_INTERIOR}):
            before = {(r["office"], r["subject"]): r for r in intelligence.generate(without)}
        after = {(r["office"], r["subject"]): r for r in intelligence.generate(w)}
        self.assertEqual({s for o, s in before if o == "interior"}, set(OLD_INTERIOR))
        self.assertNotIn(("interior", "officers_plot"), before)
        self.assertIn(("interior", "officers_plot"), after)
        for key in before:
            for field in ("id", "estimate", "low", "high", "error", "text"):
                self.assertEqual(after[key][field], before[key][field], (key, field))

    def test_the_branch_finds_more_plots_with_loyal_police_and_more_surveillance(self):
        self.assertAlmostEqual(plots.detection_chance(.7, "low"), .53, places=6)
        self.assertAlmostEqual(plots.detection_chance(.7, "high"), .73, places=6)
        self.assertGreater(plots.detection_chance(.9, "low"), plots.detection_chance(.3, "low"))


class ThePlotCanActAndTheCoupEndsTheRun(unittest.TestCase):
    def test_a_strong_plot_ends_the_run_with_an_officers_coup(self):
        w = world(COUP_SEED)
        grieve(w, loyalty=.4)
        w.institutions["plot"] = {"since": 0, "strength": .9, "detected": False, "months_detected": 0}
        with no_general_staff():
            for _ in range(12):
                if w.ended():
                    break
                month(w)
        self.assertEqual(w.outcome["type"], "officers_coup")
        self.assertEqual(w.outcome["text"], "Army officers who had lost faith in the government seized power.")
        self.assertEqual(w.active_members(), [])
        self.assertEqual(w.counters.get("coups_succeeded"), 1)

    def test_a_found_plot_under_a_purge_is_less_likely_to_act(self):
        for purge, coup in ((False, True), (True, False)):
            with self.subTest(purge=purge):
                w = world(3)
                w.policy.purge = purge
                grieve(w, loyalty=.4)
                w.institutions["plot"] = {"since": 0, "strength": .9, "detected": True, "months_detected": 1}
                draw = mock.Mock(random=mock.Mock(return_value=.3))     # between the purged .15 and the unpurged .5
                with mock.patch.object(plots, "rng_for", return_value=draw):
                    plots.monthly(w)
                self.assertEqual(w.ended(), coup)

    def test_the_coup_chance_is_lower_once_a_found_plot_meets_a_purge(self):
        self.assertEqual(plots.coup_chance(False, False), .5)
        self.assertEqual(plots.coup_chance(False, True), .5)     # a purge does not touch a plot it has not found
        self.assertEqual(plots.coup_chance(True, False), .5)
        self.assertEqual(plots.coup_chance(True, True), .15)


class TheOldRuleIsUnchanged(unittest.TestCase):
    def test_with_no_grievance_the_old_officers_coup_runs_exactly_as_before(self):
        def play(patched: bool):
            w = world(OLD_RULE_SEED)
            w.const.offices["army"] = None           # the army office vacant for three months: the old rule's condition
            w.mil.army.loyalty = .2                  # and loyalty below .3
            with no_general_staff():
                if patched:
                    with mock.patch.object(plots, "monthly", lambda _w: None):
                        month(w, 14)
                else:
                    month(w, 14)
            return w

        real, without = play(False), play(True)
        self.assertEqual(real.outcome.get("type"), "officers_coup")
        self.assertEqual(real.outcome["text"], "Army officers, unpaid and loyal to no one in the government, seized power.")
        self.assertEqual(real.outcome, without.outcome)
        self.assertEqual(real.to_dict(), without.to_dict())
        self.assertIsNone(plots.current(real))


class VersionOneWorlds(unittest.TestCase):
    def test_nothing_forms_is_found_or_acts_in_a_version_one_world(self):
        w = world(DETECTED_SEED, version=1)
        grieve(w, loyalty=.4)
        with no_general_staff():
            month(w, 3)
            plots.monthly(w)
        self.assertNotIn("plot", w.institutions)
        self.assertFalse(w.ended())
        self.assertNotIn("officers_plot", interior_reports(w))
        self.assertEqual([e for e in w.last_events if e["kind"].startswith("officers")], [])


if __name__ == "__main__":
    unittest.main()
