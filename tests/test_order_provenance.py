"""An order is recorded as the delegate wrote it, and the record says what the engine did with it.

Found on run 20260930-173547-seed1, month 4: the Army holder's order read army_target = 3100 in the
month record, in a run whose army was 30,000. The forensic trace (see the commit message) found:

  * the raw model answer really did say 3100 — in the vote-intent repair call; the first answer said
    30000, and the prompt showed 30000 — so the number was not corrupted by the parser, the prompt, the
    serialiser or stale state, and is model behaviour to be preserved, not "corrected" to 31000;
  * the engine's existing bounds (army_target 5000-400000) held it to 5000, which is what reached
    canonical state, and the army then released a quarter of its excess over that target each month;
  * nothing in the record said either of those things: the order showed 3100, the state showed 5000,
    and the two read as one fact.

So there is no parsing bug to fix and no new rule to add. What is missing is provenance: the smallest
thing that lets the requested value and the applied value be read side by side.
"""
import json
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, politics  # noqa: E402
from karamaniya.council import Council  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

# Verbatim from run 20260930-173547-seed1, log.jsonl line 189 (the repair answer that was adopted).
REAL_ARMY_ORDER = {"recruitment": "partial", "army_target": 3100, "posture": "fortify", "purge": False,
                   "deploy_north": 0.42, "deploy_east": 0.17, "deploy_capital": 0.41,
                   "officer_pay": "raised", "training_intensity": "standard", "mobilization": "none",
                   "patronage": False}


def world():
    w = new_world(3, 12, member_ids=list("ABCDE"))
    w.const.offices.update({"head": "B", "treasury": "C", "interior": "E", "army": "D", "navy": "A"})
    w.mil.army.size = 30000.0
    w.policy.army_target = 30000.0
    return w


class TheNumbersAreNotTouched(unittest.TestCase):
    """3100, 31000, 31,000 and 30000 must each come through with no digit lost or gained."""

    def test_the_parser_preserves_every_in_bounds_spelling_exactly(self):
        for raw, want in ((31000, 31000.0), ("31000", 31000.0), ("31,000", 31000.0), (30000, 30000.0),
                          ("30,000", 30000.0), (31000.0, 31000.0), (5000, 5000.0), (400000, 400000.0)):
            with self.subTest(raw=raw):
                self.assertEqual(politics.parse_lever("army_target", raw), want)

    def test_3100_is_not_read_as_31000(self):
        """The brief's warning: do not assume the number should have been 31,000."""
        self.assertNotEqual(politics.parse_lever("army_target", 3100), 31000.0)
        self.assertNotEqual(politics.parse_lever("army_target", "3100"), 31000.0)
        self.assertEqual(politics.parse_lever("army_target", 3100), politics.ARMY_TARGET_BOUNDS[0])

    def test_the_bounds_are_the_engines_existing_ones(self):
        self.assertEqual(politics.ARMY_TARGET_BOUNDS, (5000, 400000))
        self.assertEqual(politics.parse_lever("army_target", 400001), 400000)
        self.assertEqual(politics.parse_lever("army_target", 4999), 5000)

    def test_a_low_but_in_bounds_target_is_applied_as_asked(self):
        """No rule is added that a target must stay near the army's current size. An unusual policy
        is the delegate's; only a harness fault is the engine's."""
        w = world()
        adjusted = []
        politics.apply_orders(w, "D", {"army": {"army_target": 6000}}, adjusted=adjusted)
        self.assertEqual(w.policy.army_target, 6000.0)
        self.assertEqual(adjusted, [])

    def test_the_raw_model_answer_reaches_the_order_untouched(self):
        """json -> normalize_decision_v2 adds, drops and reformats nothing about a lever's value."""
        w = world()
        for written in ("3100", "31000", '"31,000"', "30000", "3100.0"):
            raw = json.loads('{"votes": {}, "orders": {"army": {"army_target": %s}}}' % written)
            out, _ = actions.normalize_decision_v2(w, "D", raw, [], 3)
            with self.subTest(written=written):
                self.assertEqual(out["orders"]["army"]["army_target"], raw["orders"]["army"]["army_target"])
                self.assertIs(type(out["orders"]["army"]["army_target"]),
                              type(raw["orders"]["army"]["army_target"]))

    def test_exact_values_survive_the_whole_order_path(self):
        for raw, want in ((31000, 31000.0), ("31,000", 31000.0), (30000, 30000.0)):
            with self.subTest(raw=raw):
                w = world()
                adjusted = []
                politics.apply_orders(w, "D", {"army": {"army_target": raw}}, adjusted=adjusted)
                self.assertEqual(w.policy.army_target, want)
                self.assertEqual(adjusted, [], "an order applied exactly as written is not an adjustment")


class WhatWasAskedAndWhatWasDone(unittest.TestCase):
    def test_the_real_order_is_applied_at_the_floor_and_says_so(self):
        w = world()
        adjusted = []
        politics.apply_orders(w, "D", {"army": dict(REAL_ARMY_ORDER)}, adjusted=adjusted)
        self.assertEqual(w.policy.army_target, 5000.0)
        self.assertEqual(len(adjusted), 1)
        gap = adjusted[0]
        self.assertEqual((gap["member"], gap["office"], gap["lever"]), ("D", "army", "army_target"))
        self.assertEqual((gap["requested"], gap["applied"]), (3100, 5000))
        self.assertIn("bounds", gap["reason"])
        self.assertIn("5,000", gap["reason"])

    def test_every_other_lever_of_the_real_order_is_applied_as_written(self):
        w = world()
        politics.apply_orders(w, "D", {"army": dict(REAL_ARMY_ORDER)}, adjusted=[])
        self.assertEqual((w.policy.recruitment, w.policy.posture, w.policy.officer_pay,
                          w.policy.training_intensity, w.policy.mobilization),
                         ("partial", "fortify", "raised", "standard", "none"))
        # (The deployment split is re-normalised as each share is applied, which is existing engine
        # behaviour and not what is under test: only that it stays a split of the whole army.)
        self.assertAlmostEqual(sum(w.mil.deploy.values()), 1.0)

    def test_a_value_the_setting_does_not_take_is_recorded_not_silently_dropped(self):
        w = world()
        adjusted = []
        before = w.policy.officer_pay
        politics.apply_orders(w, "D", {"army": {"officer_pay": "hugely_raised"}}, adjusted=adjusted)
        self.assertEqual(w.policy.officer_pay, before)
        self.assertEqual([(a["lever"], a["requested"], a["applied"]) for a in adjusted],
                         [("officer_pay", "hugely_raised", None)])

    def test_a_share_is_reported_only_when_it_was_clamped_not_when_it_was_converted(self):
        w = world()
        w.const.offices["treasury"] = "D"
        adjusted = []
        politics.apply_orders(w, "D", {"treasury": {"tax": 0.9}}, adjusted=adjusted)       # above the 0.60 ceiling
        self.assertEqual([(a["lever"], a["requested"], a["applied"]) for a in adjusted], [("tax", 0.9, 0.6)])
        for raw, want in (("22%", 0.22), (22, 0.22), (0.22, 0.22), ("0.22", 0.22)):
            with self.subTest(raw=raw):
                again = []
                politics.apply_orders(w, "D", {"treasury": {"tax": raw}}, adjusted=again)
                self.assertAlmostEqual(w.policy.tax, want)
                self.assertEqual(again, [])

    def test_callers_that_do_not_ask_for_the_record_are_unaffected(self):
        w = world()
        politics.apply_orders(w, "D", {"army": dict(REAL_ARMY_ORDER)})
        self.assertEqual(w.policy.army_target, 5000.0)


class TheMonthRecordShowsBoth(unittest.TestCase):
    def resolve(self, w, orders):
        council = Council.__new__(Council)
        council.w, council.pending_dms, council.observer, council._lock, council.spend = \
            w, [], None, threading.Lock(), 0.0
        decisions = {mid: {"votes": {}, "vote_reasons": {}, "vote_conditions": {}, "resign": False, "coup": None,
                           "coup_stance": "resist", "orders": orders.get(mid, {}), "operations": {},
                           "private_messages": [], "notes": "", "belief_updates": [], "decision_factors": []}
                     for mid in "ABCDE"}
        return council._resolve_v2(decisions, [], [], [], list("ABCDE"), [], {}, {}, [], False)

    def test_the_order_as_written_and_the_adjustment_sit_in_one_record(self):
        w = world()
        record = self.resolve(w, {"D": {"army": dict(REAL_ARMY_ORDER)}})
        self.assertEqual(record["decisions"]["D"]["orders"]["army"]["army_target"], 3100)
        self.assertEqual([(a["member"], a["lever"], a["requested"], a["applied"])
                          for a in record["order_adjustments"]], [("D", "army_target", 3100, 5000)])
        self.assertEqual(w.policy.army_target, 5000.0)

    def test_a_month_with_nothing_adjusted_records_an_empty_list(self):
        record = self.resolve(world(), {"D": {"army": {"army_target": 30000}}})
        self.assertEqual(record["order_adjustments"], [])


if __name__ == "__main__":
    unittest.main()
