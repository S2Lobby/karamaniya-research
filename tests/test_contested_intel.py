"""Two departments read one subject differently each month: seeded, attributed, honest, groundable."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import intelligence, motion_actions  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

OFFICES = {"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"}


def world(seed=5, month=0, **tuning):
    w = new_world(seed)
    w.const.offices.update(OFFICES)
    w.month = month
    if tuning:
        w.tuning = {"intelligence": tuning}
    return w


def contested(reports):
    return [r for r in reports if r.get("contested")]


class ContestedReports(unittest.TestCase):
    def test_one_subject_a_month_is_read_two_ways(self):
        for month in range(8):
            with self.subTest(month=month):
                w = world(month=month)
                reports = intelligence.generate(w)
                pair = contested(reports)
                self.assertEqual(len(pair), 2)
                a, b = pair
                self.assertEqual(a["subject"], b["subject"])
                self.assertEqual({a["office"], b["office"]}, set(intelligence.CONTESTED[a["subject"]]))
                self.assertGreaterEqual(abs(a["estimate"] - b["estimate"]), 6)
                entry = intelligence.state(w)["contested"][-1]
                self.assertEqual((entry["month"], entry["subject"]), (month, a["subject"]))
                self.assertIn(entry["closer"], (a["office"], b["office"]))
                # No office sees two reports on the same subject.
                keys = [(r["office"], r["subject"]) for r in reports]
                self.assertEqual(len(keys), len(set(keys)))

    def test_reports_are_attributed_and_never_give_the_rival_figure_or_the_truth(self):
        w = world(month=2)
        a, b = contested(intelligence.generate(w))
        for r, other in ((a, b), (b, a)):
            self.assertTrue(r["text"].startswith(intelligence.LENS_SOURCE[(r["subject"], r["office"])]))
            direction = "higher" if other["estimate"] > r["estimate"] else "lower"
            self.assertIn(f"puts this {direction}, working from different sources", r["text"])
            self.assertNotIn(f"{other['low']:.0f}-{other['high']:.0f}", r["text"])
            self.assertEqual(r["error"], "lens")
            self.assertNotIn("truth", r["text"].lower())

    def test_dispute_is_deterministic_and_leaves_ordinary_reports_alone(self):
        one, two = intelligence.generate(world(month=4)), intelligence.generate(world(month=4))
        strip = lambda rs: [{k: v for k, v in r.items() if k != "text"} for r in rs]
        self.assertEqual(strip(one), strip(two))
        plain = intelligence.generate(world(month=4, contested=False))
        self.assertEqual(contested(plain), [])
        disputed = {(r["office"], r["subject"]) for r in contested(one)}
        before = {(r["office"], r["subject"]): r for r in plain}
        for r in one:
            if (r["office"], r["subject"]) not in disputed:
                self.assertEqual(r["estimate"], before[(r["office"], r["subject"])]["estimate"])
                self.assertEqual(r["id"], before[(r["office"], r["subject"])]["id"])

    def test_needs_both_departments_held(self):
        w = world(month=1)
        w.const.offices.update({"treasury": None})
        pair = contested(intelligence.generate(w))
        self.assertEqual(len(pair), 2)
        self.assertNotIn("treasury", {r["office"] for r in pair})
        self.assertEqual(pair[0]["subject"], "union_intent")
        empty = world(month=1)
        empty.const.offices.update({"treasury": None, "head": None})
        self.assertEqual(contested(intelligence.generate(empty)), [])

    def test_food_reading_bears_on_the_food_belief_and_can_be_urgent(self):
        with mock.patch.dict(intelligence.CONTESTED, {"food_outlook": {"treasury": 1, "interior": -1}}, clear=True):
            w = world(month=3)
            w.econ.food_ratio = .9
            pair = {r["office"]: r for r in contested(intelligence.generate(w))}
        grain, police = pair["treasury"], pair["interior"]
        self.assertGreater(grain["estimate"], police["estimate"])
        self.assertIn("food supply next month expected to cover", police["text"])
        self.assertEqual(police["proposition"], "food_holds")
        self.assertTrue(police["alarming"])
        low = intelligence._report_evidence(w, police, "office")
        high = intelligence._report_evidence(w, grain, "office")
        self.assertLess(low["lr"], high["lr"])
        self.assertIn(police["id"], [r["id"] for r in intelligence.reports_for(w, "C")])
        self.assertIn(police["text"], intelligence.office_context(w, "C"))


class GroundingAcceptsWhatWasShown(unittest.TestCase):
    INTERIOR = ("PRIVATE OFFICE INFORMATION\n- [R4-INT1] Interior field reports (police district returns): national "
                "unrest next month assessed at 58-68/100. Staff note: the Treasury puts this lower, working from "
                "different sources. Confidence: high.")

    def calm_world(self):
        w = world()
        for p in w.k_pops():
            p.unrest = .2
        return w

    def test_a_figure_inside_a_reported_range_is_grounded(self):
        w = self.calm_world()
        with mock.patch.object(intelligence, "office_context", lambda *a, **k: self.INTERIOR):
            self.assertIsNone(motion_actions.check_numeric_grounding(w, "C", "Unrest will reach 63% next month."))
        with mock.patch.object(intelligence, "office_context", lambda *a, **k: ""):
            claim = motion_actions.check_numeric_grounding(w, "C", "Unrest will reach 63% next month.")
        self.assertEqual(claim["code"], "NUMERIC_GROUNDING_ERROR")

    def test_a_figure_from_an_unrelated_sentence_does_not_ground_it(self):
        w = self.calm_world()
        text = "PRIVATE OFFICE INFORMATION\n- Cabinet secretariat: council working trust assessed at 58-68/100."
        with mock.patch.object(intelligence, "office_context", lambda *a, **k: text):
            claim = motion_actions.check_numeric_grounding(w, "C", "Unrest will reach 63% next month.")
        self.assertIsNotNone(claim)

    def test_a_shortage_can_be_the_complement_of_a_coverage_figure(self):
        w = world()
        w.econ.food_ratio = .96
        with mock.patch.object(intelligence, "office_context", lambda *a, **k: ""):
            self.assertIsNone(motion_actions.check_numeric_grounding(w, "C", "The food shortage is 4%."))
        police = ("- [R4-INT2] Interior market watch (police reports on queues and prices): food supply next month "
                  "expected to cover 70-76% of needs.")
        with mock.patch.object(intelligence, "office_context", lambda *a, **k: police):
            self.assertIsNone(motion_actions.check_numeric_grounding(w, "C", "We face a food shortage of 27%."))
        with mock.patch.object(intelligence, "office_context", lambda *a, **k: ""):
            self.assertIsNotNone(motion_actions.check_numeric_grounding(w, "C", "We face a food shortage of 27%."))

    def test_a_colleague_shared_reading_grounds_the_recipient_at_decision_time(self):
        w = world(month=0)
        for p in w.k_pops():            # calm now, but grievances point to trouble next month
            p.unrest, p.grievance = .1, .9
        with mock.patch.dict(intelligence.CONTESTED, {"unrest_outlook": {"interior": 1, "treasury": -1}}, clear=True):
            reports = intelligence.generate(w)
        interior = next(r for r in contested(reports) if r["office"] == "interior")
        claim = f"Unrest is heading to {interior['estimate']:.0f}% next month."
        self.assertGreater(interior["estimate"], 40)
        # Shared in the response round with E alone: E may cite it in its vote; D, who never saw it, may not.
        shared = intelligence.share(w, "C", [{"report_id": interior["id"], "with": "E"}], "revision")
        self.assertEqual(len(shared), 1)
        self.assertIn(interior["text"], intelligence.office_context(w, "E", "decision"))
        self.assertIsNone(motion_actions.check_numeric_grounding(w, "E", claim))
        self.assertIsNone(motion_actions.check_numeric_grounding(w, "C", claim))
        self.assertEqual(motion_actions.check_numeric_grounding(w, "D", claim)["code"], "NUMERIC_GROUNDING_ERROR")


if __name__ == "__main__":
    unittest.main()
