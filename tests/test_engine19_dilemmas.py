"""World engine 19, dilemmas slice: issues, emergency measures, leaks, forecasts and provenance.

Each test pins one finding of the engine-18 audit (docs/AUDIT_ENGINE18.md) and the scenario of its proof script. The
audit id is named in each test's docstring and in the comments of the code it changes.
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import attribution, dilemmas, provenance, public_mood, standing  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

OFFICES = {"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"}


class FixedRng:
    """A stand-in for the random stream that always returns the same draw."""

    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


def _procurement_world(month=3):
    w = new_world(1)
    w.const.offices.update(OFFICES)
    w.month = month
    return w


def _procurement_issue(w, draw):
    """A procurement scandal set up with a fixed draw: draw 0.0 makes it true, 0.99 makes it false."""
    details = dilemmas._setup(w, "procurement_scandal", FixedRng(draw))
    issue = {"id": "I4-procurement_scandal", "kind": "procurement_scandal", "title": "t", "month": w.month,
             "text": details["text"], "readings": [], "tradeoffs": [], "tags": [], "office_notes": {},
             "region": None, "target": details["target"], "truth": details["truth"], "status": "active",
             "expires_month": w.month + 3, "applied": {}, "started": False}
    return issue


class ProcurementTruthTests(unittest.TestCase):
    """IN-M7: a procurement scandal is worded as an allegation, and its reputation hit follows its hidden truth."""

    def test_text_is_an_allegation_not_a_finding(self):
        for draw, true in ((0.0, True), (0.99, False)):
            with self.subTest(true=true):
                issue = _procurement_issue(_procurement_world(), draw)
                self.assertEqual(issue["truth"], {"true": true})
                self.assertIn("Documents allege padded contracts", issue["text"])
                self.assertNotIn("Auditors found", issue["text"])

    def test_reputation_hit_follows_the_hidden_truth(self):
        hits = {}
        for draw, true in ((0.0, True), (0.99, False)):
            w = _procurement_world()
            issue = _procurement_issue(w, draw)
            target = issue["target"]
            before = standing.ensure(w, target)["reputation"].get("corrupt", 50)
            dilemmas._effect(w, issue, True, lambda *a: None)
            hits[true] = standing.ensure(w, target)["reputation"].get("corrupt", 50) - before
        self.assertGreater(hits[True], 0)
        self.assertGreater(hits[False], 0)
        self.assertLess(hits[False], hits[True])


def _world(month=0):
    from karamaniya import foreign
    w = new_world(4)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update(OFFICES)
    w.month = month
    return w


def _live_issue(w, kind, region, month):
    spec = dilemmas.CATALOGUE[kind]
    issue = {"id": f"I{month + 1}-{kind}", "kind": kind, "title": "t", "month": month, "text": "", "readings": [],
             "tradeoffs": [], "tags": [], "office_notes": {}, "region": region, "target": None, "truth": {},
             "status": "active", "expires_month": month + 1 + spec["duration"], "applied": {}, "started": False}
    dilemmas.state(w)["active"].append(issue)
    return issue


def _play_until_ended(w, first_month, limit=12):
    """Run an issue's monthly effects and its review until it ends, as the engine does; returns the month it ended."""
    for month in range(first_month, first_month + limit):
        w.month = month
        dilemmas.apply_ongoing(w)
        if dilemmas.review(w, None):
            return month
    raise AssertionError("the issue never ended")


class FlooredLogisticsUndoTests(unittest.TestCase):
    """IN-L2: ending an issue that cut logistics restores what the cut took, not the nominal drop the floor clipped."""

    def test_undo_restores_the_logistics_each_issue_started_from(self):
        # The start values are low enough that the .3 floor clips the cut (rail, storm, governor).
        cases = (("rail_blockade", "kessel", {"kessel": 0.35}),
                 ("storm", "lissen", {"lissen": 0.32}),
                 ("governor_defiance", "highlands", {"highlands": 0.31}))
        for kind, region, starts in cases:
            with self.subTest(kind=kind):
                w = _world()
                for rid, value in starts.items():
                    w.region(rid).logistics = value
                before = {r.id: r.logistics for r in w.regions}
                issue = _live_issue(w, kind, region, month=6)
                _play_until_ended(w, first_month=6)
                self.assertIn(issue["status"], ("resolved", "faded"))
                for r in w.regions:
                    self.assertAlmostEqual(r.logistics, before[r.id], places=9, msg=r.id)


class MovementRestrictionTests(unittest.TestCase):
    """IN2: a movement restriction lowers the regions' logistics only while it is in force (the proof script's scenario:
    imposed in Month 6, 0-based 5, for four months)."""

    def _region(self, w):
        return next(r for r in w.k_regions() if not r.capital)

    def test_logistics_comes_back_when_the_measure_expires(self):
        w = _world(month=5)
        region = self._region(w)
        start = region.logistics
        dilemmas.set_emergency_measure(w, "movement_restrictions", True, "A", "")
        for month in range(5, 9):
            w.month = month
            dilemmas.apply_ongoing(w)
        self.assertLess(region.logistics, start)
        for month in range(9, 12):
            w.month = month
            dilemmas.apply_ongoing(w)
        self.assertNotIn("movement_restrictions", w.institutions.get("emergency_measures") or {})
        self.assertAlmostEqual(region.logistics, start, places=9)

    def test_lifting_the_measure_restores_logistics(self):
        w = _world(month=5)
        region = self._region(w)
        start = region.logistics
        dilemmas.set_emergency_measure(w, "movement_restrictions", True, "A", "")
        w.month = 5
        dilemmas.apply_ongoing(w)
        self.assertLess(region.logistics, start)
        w.month = 6
        dilemmas.set_emergency_measure(w, "movement_restrictions", False, "A", "")
        self.assertAlmostEqual(region.logistics, start, places=9)

    def test_an_extended_measure_undoes_every_cut_it_made(self):
        w = _world(month=5)
        region = self._region(w)
        start = region.logistics
        dilemmas.set_emergency_measure(w, "movement_restrictions", True, "A", "")
        for month in range(5, 8):
            w.month = month
            dilemmas.apply_ongoing(w)
        w.month = 7
        dilemmas.set_emergency_measure(w, "movement_restrictions", True, "A", "")
        for month in range(8, 13):
            w.month = month
            dilemmas.apply_ongoing(w)
        self.assertNotIn("movement_restrictions", w.institutions.get("emergency_measures") or {})
        self.assertAlmostEqual(region.logistics, start, places=9)


class LeakUnderPressTests(unittest.TestCase):
    """TO12: a border-incident leak under a censored press is recorded but not published (no public event, reaction or
    propaganda change, as opposition.py leaves a censored statement unheard); restricted reporting halves the reaction."""

    def _learned(self, press, perpetrator):
        w = new_world(1)
        w.const.press = press
        w.month = 3
        entry = attribution.record(w, {"id": "incident-test", "month": 0, "region": "dorran",
                                       "truth": {"perpetrator": perpetrator}})
        before = {"propaganda": w.dip.propaganda, "rally": w.dip.rally, "reactions": len(public_mood.state(w))}
        attribution.learn(w, entry)
        return w, entry, before

    def _reaction(self, w, reason):
        return next((e for e in public_mood.state(w) if e["reason"] == reason), None)

    def test_censored_press_records_the_truth_without_publishing_it(self):
        for perpetrator, reason in ((attribution.UNION_PATROL, "incident:union_fired"),
                                    (attribution.OWN_TROOPS, "incident:our_troops")):
            with self.subTest(perpetrator=perpetrator):
                w, entry, before = self._learned("censored", perpetrator)
                self.assertIs(entry.get("published"), False)
                public = [e for e in w.events if e["kind"] == "incident_leak" and e.get("public", True)]
                self.assertEqual(public, [])
                self.assertEqual(len([e for e in w.events if e["kind"] == "incident_leak"]), 1)
                self.assertIsNone(self._reaction(w, reason))
                self.assertEqual(len(public_mood.state(w)), before["reactions"])
                self.assertEqual(w.dip.propaganda, before["propaganda"])
                self.assertEqual(w.dip.rally, before["rally"])

    def test_restricted_press_halves_the_public_reaction(self):
        free_w, _, _ = self._learned("free", attribution.UNION_PATROL)
        restricted_w, restricted_entry, _ = self._learned("restricted", attribution.UNION_PATROL)
        free = self._reaction(free_w, "incident:union_fired")
        restricted = self._reaction(restricted_w, "incident:union_fired")
        self.assertAlmostEqual(free["value"], attribution.LEAK_UNION_APPROVAL, places=6)
        self.assertAlmostEqual(restricted["value"], attribution.LEAK_UNION_APPROVAL * 0.5, places=6)
        self.assertIs(restricted_entry["published"], True)
        public = [e for e in restricted_w.events if e["kind"] == "incident_leak" and e.get("public", True)]
        self.assertEqual(len(public), 1)


def _warning_world(seed, month):
    from karamaniya import foreign
    w = new_world(seed)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update(OFFICES)
    w.dip.union_formed = True
    w.dip.war = False
    w.month = month
    return w


def _raised_false_warning(test):
    """The first world (seed, month) in which dilemmas.generate, run at the end of that month, raises a false warning."""
    for seed in range(1, 40):
        for month in range(0, 24):
            w = _warning_world(seed, month)
            for issue in dilemmas.generate(w):
                if issue["kind"] == "false_warning":
                    return w, issue
    test.fail("no false warning was raised in the search")


class FalseWarningTimingTests(unittest.TestCase):
    """IN-M1: a false warning's urgent office reports are filed when its issue is raised, dated for the month the issue
    starts, so the session of that month reads them with its other reports. Beliefs move on them only once they are
    readable; before, they were written after the council had met and moved beliefs the holders never saw."""

    def test_the_warnings_are_filed_for_the_month_the_issue_starts(self):
        from karamaniya import intelligence
        w, issue = _raised_false_warning(self)
        filed = [r for r in intelligence.state(w)["reports"] if r.get("issue") == issue["id"]]
        self.assertEqual(sorted(r["office"] for r in filed), ["army", "head"])
        self.assertTrue(all(r["month"] == issue["month"] for r in filed))

    def test_the_session_of_the_issue_month_reads_the_warnings_with_its_reports(self):
        from karamaniya import intelligence
        w, issue = _raised_false_warning(self)
        w.month = issue["month"]
        intelligence.generate(w)                   # the start of the month, before the sessions (council.py)
        army = w.holder("army")
        self.assertIn("URGENT: a source inside the Union command warns", intelligence.office_context(w, army.id))
        regular = [r["id"] for r in intelligence.reports_for(w, army.id) if not r.get("issue")]
        self.assertIn(f"R{issue['month'] + 1}-ARM1", regular)

    def test_beliefs_move_on_the_warnings_only_from_the_issue_month(self):
        from karamaniya import intelligence
        w, issue = _raised_false_warning(self)
        army = w.holder("army")

        def warnings_in_evidence():
            own, _ = intelligence.office_evidence(w)
            return [e for e in own.get(army.id, []) if e["id"].endswith("ARMW")]

        self.assertEqual(warnings_in_evidence(), [])        # not yet readable: the month is still the filing month
        dilemmas.apply_ongoing(w)                           # the filing month's step must not file them again
        w.month = issue["month"]
        self.assertEqual(len(warnings_in_evidence()), 1)

    def test_a_forced_warning_issue_still_files_its_reports_at_its_first_effect(self):
        from karamaniya import intelligence
        w = _warning_world(1, 0)
        issue = _live_issue(w, "false_warning", None, month=0)
        issue["truth"] = {"real": False}
        dilemmas.apply_ongoing(w)
        self.assertEqual(sorted(r["office"] for r in intelligence.state(w)["reports"] if r["id"].endswith("W")),
                         ["army", "head"])


class ForecastScoringTimingTests(unittest.TestCase):
    """IN-M3: a forecast is scored against approval, unemployment and army morale after this month's society and military
    updates, which set them; scored before, it read last month's figures (the proof script's scenario: horizon 3 from
    Month 6, 0-based 5, due and scored in the step of Month 9, 0-based 8)."""

    def test_the_figures_scored_are_the_figures_at_the_end_of_the_month(self):
        from karamaniya import engine, forecasts, foreign
        w = new_world(4, 36)
        w.foreign = foreign.initial_state(w.seed)
        w.const.offices.update(OFFICES)
        w.month = 5
        for metric, direction, threshold in (("approval", "below", 0.5), ("unemployment", "above", 0.05),
                                             ("army_morale", "below", 0.5)):
            forecasts.record(w, "A", metric, 3, direction, threshold, 0.6)
        read_at_scoring = {}
        original = forecasts.resolve_due

        def capturing(w_):
            read_at_scoring.update({"approval": w_.avg("approval"), "unemployment": w_.econ.unemployment,
                                    "army_morale": w_.mil.army.morale})
            return original(w_)

        with mock.patch.object(forecasts, "resolve_due", capturing):
            for _ in range(4):
                engine.begin_month(w)
                engine.step(w)
        at_month_end = {"approval": w.avg("approval"), "unemployment": w.econ.unemployment,
                        "army_morale": w.mil.army.morale}
        for metric, value in at_month_end.items():
            self.assertAlmostEqual(read_at_scoring[metric], value, places=9, msg=metric)


class LagRegistryDocTests(unittest.TestCase):
    """IN-L6: only the fiscal impulse is lagged through the queue (causality.schedule has one caller); the backlog's C2
    line must not say policies schedule effects at every horizon, which the engine does not do."""

    def test_backlog_c2_says_only_the_fiscal_impulse_is_lagged(self):
        with open(os.path.join(ROOT, "docs", "ENGINEERING_BACKLOG.md"), encoding="utf-8") as f:
            c2 = next(line for line in f if line.startswith("| C2 |"))
        self.assertIn("fiscal", c2)
        self.assertNotIn("Policies schedule effects", c2)


class HedgeWordBoundaryTests(unittest.TestCase):
    """IN-L5: a hedge word inside another word ("mayor", "dismayed", "mayhem") does not make a statement a hedge."""

    def test_statements_of_intent_with_hedge_substrings_assert_intent(self):
        for text in ("We will use the army to remove the council, and the mayor agrees.",
                     "We are dismayed by the vote, so we will seize the palace by force.",
                     "We will seize the capital and bring mayhem to the ministries."):
            with self.subTest(text=text):
                fact = provenance.canonical(text)
                self.assertFalse(fact["hedged"])
                self.assertTrue(fact["asserts_intent"])
                self.assertEqual(fact["readable_as"], "a statement of intent")

    def test_real_hedges_still_hedge(self):
        fact = provenance.canonical("We may use the army to remove the council.")
        self.assertTrue(fact["hedged"])
        self.assertFalse(fact["asserts_intent"])
        self.assertEqual(fact["readable_as"], "a warning or speculation about a risk")

    def test_plain_inflections_of_hedges_still_hedge(self):
        for text in ("Concerns about the army are growing.", "The risks of a coup are rising.",
                     "We fear the council will fall.", "Worrying signs from the barracks."):
            with self.subTest(text=text):
                self.assertTrue(provenance._is_hedged(text))

    def test_distortion_does_not_report_a_dropped_hedge_that_was_not_there(self):
        # "mayor" contains "may", but only "might" is a hedge in this text: one dropped hedge, not two.
        class FixedRng:
            def random(self):
                return 0.99

        press, added = provenance._distort("We might use the army, and the mayor agrees.", FixedRng())
        self.assertEqual(added.count("dropped the hedge"), 1)
        self.assertIn("is preparing to", press)


if __name__ == "__main__":
    unittest.main()
