"""World engine 18: who fired at the border becomes clearer in the months after (attribution.py).

In run 20261010-070501-seed1, Month 5, a shooting on the eastern border left casualties and each side blamed the other.
The Army post's accounts contradicted each other, and the forensic results "will take weeks". They never came. The
council, unsure who had fired, invited the Union into a joint inquiry, and that inquiry's finding was drawn 60/30/10
whatever had happened: the truth the engine had drawn for the shooting was never revealed. These tests pin the Army
staff's forensic reports (when they come, how sure they are, and how the staff reads its own soldiers), the press
learning the truth three months on, and the finding of a joint inquiry, which the evidence steers. No delegate is told
what to decide: the world reacts to what happened on the border.
"""
import copy
import os
import random
import sys
import unittest
from collections import Counter
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import agents, attribution, dilemmas, engine, fine_print, foreign, intelligence, public_mood  # noqa: E402
from karamaniya.world import new_world, rng_for  # noqa: E402

OLD_ARMY = ("union_strength", "union_intent", "officer_loyalty", "readiness", "net_assessment", "staff_request")
# The catalogue with only the border incident possible, and certain to be raised when the month ends (dilemmas.generate).
BORDER_ONLY = {"border_incident": {**dilemmas.CATALOGUE["border_incident"], "weight": lambda _w: 1.0}}
FORENSIC_OPENING = ("Army forensic report on the border incident: the evidence puts the chance that Solvaran Union "
                    "soldiers fired at ")


def world(seed: int = 5, press: str | None = None):
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    agents.ensure(w)                  # the office audiences (senior officers, sailors ...) follow the offices held
    if press is not None:
        w.const.press = press
    return w


def incident(w, month: int, perpetrator: str) -> dict:
    """A border incident that started in `month`, on record as dilemmas.generate puts it: the issue's fields, with its
    hidden truth set to `perpetrator`. Returns the record."""
    spec = dilemmas.CATALOGUE["border_incident"]
    issue = {"id": f"I{month + 1}-border_incident", "kind": "border_incident", "title": spec["title"], "month": month,
             "text": spec["text"], "region": spec["region"], "truth": {"perpetrator": perpetrator}, "status": "active",
             "expires_month": month + 1, "applied": {}, "started": False}
    return attribution.record(w, issue)


def army(w) -> dict:
    """This month's Army reports, by subject."""
    return {r["subject"]: r for r in intelligence.generate(w) if r["office"] == "army"}


def reactions(w) -> list:
    return [(r["kind"], r["where"], r["value"], r["months_left"], r["reason"]) for r in public_mood.state(w)]


def findings(seeds, who, incident_month: int = 4) -> Counter:
    """What a joint inquiry opened in Month 5 (index 4) finds, for each seed, when it reports in Month 7 (index 6).
    `who` is the perpetrator of a border incident that started in `incident_month`, or None for no incident."""
    out = Counter()
    for seed in seeds:
        w = world(seed)
        if who is not None:
            incident(w, incident_month, who)
        w.month = 4
        fine_print.open_inquiry(w, "union")
        w.month = 6
        fine_print.monthly(w)
        out.update(e["finding"] for e in w.events if e["kind"] == "inquiry_finding")
    return out


def roll(seed: int) -> float:
    """The one draw fine_print.monthly makes for an inquiry that reports in Month 7 (index 6)."""
    return rng_for(seed, 6, "fine-print:finding").random()


class TheForensicReports(unittest.TestCase):
    def test_the_army_staff_gives_its_first_report_in_the_month_after_the_shooting_starts(self):
        w = world()
        incident(w, 4, "union patrol")
        w.month = 5
        r = army(w)["incident_attribution"]
        self.assertEqual(r["id"], "R6-ARM7")
        self.assertEqual(r["confidence"], "low")
        self.assertTrue(r["text"].startswith(FORENSIC_OPENING), r["text"])
        self.assertTrue(r["text"].endswith("Accounts from the post still conflict. Confidence: low."), r["text"])
        self.assertIn(r["text"], intelligence.office_context(w, "D"))        # the Army minister holds it
        self.assertNotIn(r["text"], intelligence.office_context(w, "A"))     # nobody else in the council does

    def test_the_second_report_comes_two_months_on_at_medium_confidence_without_the_conflict(self):
        w = world()
        incident(w, 4, "union patrol")
        w.month = 6
        r = army(w)["incident_attribution"]
        self.assertEqual((r["id"], r["confidence"], r["forensic_step"]), ("R7-ARM7", "medium", 2))
        self.assertNotIn("still conflict", r["text"])
        self.assertTrue(r["text"].endswith("Confidence: medium."), r["text"])

    def test_there_is_no_forensic_report_before_the_shooting_or_from_its_third_month_on(self):
        for month in (3, 4, 7, 8):
            with self.subTest(month=month):
                w = world()
                incident(w, 4, "union patrol")
                w.month = month
                self.assertNotIn("incident_attribution", army(w))

    def test_it_is_the_last_army_subject_so_the_older_reports_keep_their_ids_and_draws(self):
        self.assertEqual(intelligence.SUBJECTS["army"][:6], OLD_ARMY)
        self.assertEqual(intelligence.SUBJECTS["army"][-1], "incident_attribution")

    def test_the_estimate_follows_the_evidence_with_the_error_machinery_patched_out(self):
        # The own-troops reading is the evidence's 10 raised by the staff's 20 points; the other two are the evidence.
        for who, estimate in (("union patrol", 85.0), ("smugglers", 25.0), ("our own troops", 30.0)):
            with self.subTest(who=who):
                w = world()
                incident(w, 4, who)
                w.month = 5
                with mock.patch.object(intelligence, "_error", return_value="none"), \
                        mock.patch.object(random.Random, "gauss", return_value=0.0):
                    r = army(w)["incident_attribution"]
                self.assertAlmostEqual(r["estimate"], estimate, places=6)
                self.assertEqual(r["truth"], {"union patrol": 85.0, "smugglers": 25.0, "our own troops": 10.0}[who])
                self.assertTrue(r["accurate"])
                self.assertEqual(r["alarming"], estimate >= 70)

    def test_a_second_shooting_does_not_lend_the_first_ones_report_its_truth(self):
        # Two shootings a month apart: in Month 7 both are due a report, and the older one's is given. Its truth and
        # its staff bias must both be the older one's (a union patrol: 85, no bias), not the newer one's.
        w = world()
        incident(w, 4, "union patrol")
        incident(w, 5, "our own troops")
        w.month = 6
        self.assertEqual(attribution.due(w)["perpetrator"], "union patrol")
        self.assertEqual((attribution.truth(w), attribution.staff_bias(w)), (85.0, 0.0))
        self.assertEqual(army(w)["incident_attribution"]["truth"], 85.0)

    def test_a_staff_that_is_slow_to_blame_its_own_soldiers_reads_twenty_points_high_before_the_error(self):
        w = world()
        incident(w, 4, "our own troops")
        w.month = 5
        # A bureaucratic error moves the staff's reading up by .25 to .6 of itself: 30 x 1.25 to 30 x 1.6. Had the bias
        # come after the error, the reading would be at most 10 x 1.6 + 20 = 36.
        with mock.patch.object(intelligence, "_error", return_value="bureaucratic"), \
                mock.patch.object(random.Random, "gauss", return_value=0.0):
            r = army(w)["incident_attribution"]
        self.assertTrue(30 * 1.25 - 1e-6 <= r["estimate"] <= 30 * 1.6 + 1e-6, r["estimate"])
        self.assertGreater(r["estimate"], 10 * 1.6 + 20)
        self.assertEqual((r["truth"], r["error"]), (10.0, "bureaucratic"))   # the record keeps the true figure

    def test_the_other_army_reports_are_the_same_with_and_without_the_forensic_subject(self):
        w = world()
        incident(w, 4, "our own troops")
        w.month = 5
        without = copy.deepcopy(w)
        with mock.patch.dict(intelligence.SUBJECTS, {"army": OLD_ARMY}):
            before = {(r["office"], r["subject"]): r for r in intelligence.generate(without)}
        after = {(r["office"], r["subject"]): r for r in intelligence.generate(w)}
        self.assertNotIn(("army", "incident_attribution"), before)
        self.assertIn(("army", "incident_attribution"), after)
        self.assertEqual(set(before), set(after) - {("army", "incident_attribution")})
        self.assertIn(("army", "staff_request"), before)                  # the General Staff's own report is still there
        for key in before:
            for field in ("id", "estimate", "low", "high", "error", "text", "confidence", "accurate"):
                self.assertEqual(after[key][field], before[key][field], (key, field))


class ThePressLearnsTheTruth(unittest.TestCase):
    def learned(self, seed: int, press: str) -> bool:
        w = world(seed, press=press)
        incident(w, 4, "smugglers")
        w.month = 7                    # three months after the shooting starts
        return bool(attribution.leaks(w))

    def test_three_months_on_the_press_learns_the_truth_about_half_the_time_and_more_often_when_free(self):
        for press, expected in (("free", .8), ("restricted", .5), ("censored", .5)):
            with self.subTest(press=press):
                share = sum(self.learned(seed, press) for seed in range(20)) / 20
                self.assertAlmostEqual(share, expected, delta=.2)

    def test_the_press_considers_the_shooting_only_in_its_third_month(self):
        for seed in range(5):
            with self.subTest(seed=seed):
                w = world(seed)
                entry = incident(w, 4, "union patrol")
                for month in (6, 8):
                    w.month = month
                    self.assertEqual(attribution.leaks(w), [])
                self.assertIsNone(entry["learned"])

    def test_a_learned_union_patrol_rallies_the_country_and_lowers_the_unions_propaganda(self):
        w = world()
        entry = incident(w, 4, "union patrol")
        w.dip.propaganda, w.dip.rally = .2, .1
        attribution.learn(w, entry)
        self.assertIn(("approval", "ident:karamanian", .003, 3, "incident:union_fired"), reactions(w))
        self.assertAlmostEqual(w.dip.rally, .15)
        self.assertAlmostEqual(w.dip.propaganda, .17)

    def test_the_union_loses_no_more_propaganda_than_it_has(self):
        w = world()
        entry = incident(w, 4, "union patrol")
        attribution.learn(w, entry)
        self.assertEqual(w.dip.propaganda, 0.0)

    def test_a_learned_shot_by_our_own_troops_costs_approval_and_hands_the_union_propaganda(self):
        w = world()
        entry = incident(w, 4, "our own troops")
        w.dip.propaganda = .2
        attribution.learn(w, entry)
        self.assertIn(("approval", "*", -.004, 3, "incident:our_troops"), reactions(w))
        self.assertAlmostEqual(w.dip.propaganda, .25)
        self.assertEqual(w.dip.rally, 0.0)

    def test_a_learned_shot_by_smugglers_is_an_event_and_nothing_more(self):
        w = world()
        entry = incident(w, 4, "smugglers")
        attribution.learn(w, entry)
        self.assertEqual(reactions(w), [])
        self.assertEqual((w.dip.propaganda, w.dip.rally), (0.0, 0.0))
        self.assertEqual([e["kind"] for e in w.events], ["incident_leak"])

    def test_what_the_press_learns_is_a_public_event_of_importance_two(self):
        w = world()
        entry = incident(w, 4, "our own troops")
        w.month = 7
        attribution.learn(w, entry)
        (event,) = [e for e in w.events if e["kind"] == "incident_leak"]
        self.assertTrue(event["public"])
        self.assertEqual(event["importance"], 2)
        self.assertEqual(event["incident"], entry["id"])
        self.assertIn("Month 5", event["text"])                # the shooting's own month, as the council reads months
        self.assertIn("our own troops", event["text"])


class TheInquiryFinding(unittest.TestCase):
    def test_with_our_own_troops_the_finding_blames_karamanian_soldiers_about_85_times_in_100(self):
        found = findings(range(40), "our own troops")
        self.assertEqual(sum(found.values()), 40)
        self.assertAlmostEqual(found["karamanian"] / 40, .85, delta=.1)

    def test_with_a_union_patrol_the_finding_blames_karamanian_soldiers_about_30_times_in_100(self):
        found = findings(range(40), "union patrol")
        self.assertEqual(sum(found.values()), 40)
        self.assertAlmostEqual(found["karamanian"] / 40, .3, delta=.1)

    def test_with_no_incident_on_record_the_finding_is_still_sixty_thirty_ten(self):
        found = findings(range(40), None)
        self.assertEqual(sum(found.values()), 40)
        self.assertAlmostEqual(found["karamanian"] / 40, .6, delta=.15)
        self.assertAlmostEqual(found["inconclusive"] / 40, .3, delta=.15)
        self.assertAlmostEqual(found["other"] / 40, .1, delta=.1)

    def test_each_finding_is_the_one_draw_read_through_the_cut_points_of_its_incident(self):
        # (perpetrator, month it started): the cut points are the chances of blaming Karamanian soldiers, and of
        # being inconclusive. The default 60/30/10 applies with no incident, and to one that started six or more
        # months before the inquiry reports (month 0 here, against a report in month 6).
        cases = ((None, 4, (.6, .9)), ("union patrol", 4, (.3, .9)), ("smugglers", 4, (.4, .9)),
                 ("our own troops", 4, (.85, 1.0)), ("our own troops", 1, (.85, 1.0)), ("our own troops", 0, (.6, .9)))
        for who, month, (blame, inconclusive) in cases:
            for seed in range(12):
                with self.subTest(who=who, month=month, seed=seed):
                    r = roll(seed)
                    expected = "karamanian" if r < blame else "inconclusive" if r < inconclusive else "other"
                    self.assertEqual(list(findings([seed], who, incident_month=month)), [expected])


class TheIncidentGoesOnRecord(unittest.TestCase):
    def test_a_border_issue_raised_at_the_end_of_a_month_is_put_on_record_with_its_hidden_truth(self):
        w = world()
        w.month = 0
        w.tuning = {"dilemmas": {"base_rate": 1.0}}
        with mock.patch.dict(dilemmas.CATALOGUE, BORDER_ONLY, clear=True):
            (issue,) = dilemmas.generate(w)
        self.assertEqual((issue["kind"], issue["month"]), ("border_incident", 1))
        (entry,) = attribution.records(w)
        self.assertEqual((entry["id"], entry["month"], entry["learned"]), (issue["id"], 1, None))
        self.assertEqual(entry["perpetrator"], issue["truth"]["perpetrator"])
        self.assertIn(entry["perpetrator"], attribution.TRUTH)

    def test_other_issues_are_not_put_on_record(self):
        w = world()
        w.month = 0
        w.tuning = {"dilemmas": {"base_rate": 1.0}}
        storm = {**dilemmas.CATALOGUE["storm"], "weight": lambda _w: 1.0}
        with mock.patch.dict(dilemmas.CATALOGUE, {"storm": storm}, clear=True):
            raised = dilemmas.generate(w)
        self.assertEqual([i["kind"] for i in raised], ["storm"])
        self.assertNotIn(attribution.KEY, w.institutions)

    def test_a_world_with_no_incident_has_no_record_and_creates_no_key(self):
        w = world()
        self.assertEqual(attribution.records(w), [])
        self.assertIsNone(attribution.due(w))
        self.assertIsNone(attribution.finding_cuts(w))
        self.assertEqual(attribution.leaks(w), [])
        self.assertNotIn(attribution.KEY, w.institutions)


class TheMonthsAfterAShooting(unittest.TestCase):
    def test_a_shooting_raised_by_the_month_loop_is_reported_twice_and_learned_of_on_schedule(self):
        w = world(5)
        w.tuning = {"dilemmas": {"base_rate": 1.0}}           # the border incident is raised at once
        timeline = {}
        # The press learns the truth whatever it draws: the schedule is what this test pins.
        with mock.patch.dict(dilemmas.CATALOGUE, BORDER_ONLY, clear=True), \
                mock.patch.object(attribution, "LEAK_CHANCE", 1.0):
            for month in range(5):
                w.month = month
                engine.begin_month(w)
                reports = [r for r in intelligence.generate(w) if r["subject"] == "incident_attribution"]
                for r in reports:
                    self.assertIn(r["text"], intelligence.office_context(w, "D"))
                engine.step(w)
                leaks = [e for e in w.last_events if e["kind"] == "incident_leak"]
                timeline[month] = (reports, leaks)
        (entry,) = attribution.records(w)
        self.assertEqual((entry["month"], entry["learned"]), (1, True))
        self.assertEqual([m for m in timeline if timeline[m][0]], [2, 3])
        self.assertEqual([r["confidence"] for r in timeline[2][0]], ["low"])
        self.assertEqual([r["confidence"] for r in timeline[3][0]], ["medium"])
        self.assertEqual(timeline[2][0][0]["truth"], attribution.TRUTH[entry["perpetrator"]])
        self.assertEqual([m for m in timeline if timeline[m][1]], [4])
        (leak,) = timeline[4][1]
        self.assertEqual((leak["incident"], leak["importance"]), (entry["id"], 2))


if __name__ == "__main__":
    unittest.main()
