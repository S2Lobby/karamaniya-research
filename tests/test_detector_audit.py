"""Tests for tools/detector_audit.py: the statistics, the fixed D1 sample, and the text helpers.

These tests use no recorded runs. The sample test pins the seed that the report and the labels use, so a change
to the seed or to the flag order shows up here.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import detector_audit as da  # noqa: E402


class WilsonTests(unittest.TestCase):
    def test_half_of_forty(self):
        lo, hi = da.wilson(20, 40)
        self.assertAlmostEqual(lo, 0.3520, places=3)
        self.assertAlmostEqual(hi, 0.6480, places=3)

    def test_no_success_in_forty(self):
        lo, hi = da.wilson(0, 40)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.0876, places=3)          # z^2 / (n + z^2)

    def test_all_successes_in_forty(self):
        lo, hi = da.wilson(40, 40)
        self.assertAlmostEqual(lo, 0.9124, places=3)
        self.assertEqual(hi, 1.0)

    def test_no_trials(self):
        self.assertEqual(da.wilson(0, 0), (0.0, 1.0))


class SampleTests(unittest.TestCase):
    def test_d1_sample_is_the_recorded_one(self):
        # The 40 flags the report samples (1-based flag numbers D1-001 .. D1-137, seed 20261017).
        recorded = {1, 2, 8, 11, 12, 18, 21, 23, 24, 32, 33, 41, 42, 44, 46, 47, 49, 58, 64, 66, 71, 72, 73, 85,
                    91, 98, 101, 102, 103, 109, 110, 113, 116, 123, 124, 125, 126, 129, 134, 137}
        chosen = {i + 1 for i in da.sample_indices(137, da.SAMPLE, da.SEED)}
        self.assertEqual(chosen, recorded)

    def test_sample_is_deterministic_and_in_range(self):
        first = da.sample_indices(137, 40, 20261017)
        self.assertEqual(first, da.sample_indices(137, 40, 20261017))
        self.assertEqual(len(first), len(set(first)))
        self.assertTrue(all(0 <= i < 137 for i in first))


class LocateTests(unittest.TestCase):
    def test_finds_the_figure_by_value(self):
        text = "As of Month 6, reserves are 6M gold."
        start, end, how = da.locate(text, 6000000.0, "6 m")
        self.assertEqual(text[start:end], "6M")
        self.assertEqual(how, "value")

    def test_skips_a_month_label(self):
        # "Month 6" is a date, not a claim of 6% (the bug fixed in the engine's _is_label as well).
        text = "As of Month 6: Reserves confirmed 0M."
        self.assertEqual(da.locate(text, 0.06, "6%")[2], "not_found")

    def test_bare_number_is_matched_when_the_value_is_converted(self):
        text = "Fleet 6 vs 14 Union ships, readiness 60-72."
        start, end, how = da.locate(text, 0.06, "6")
        self.assertEqual(text[start:end].strip(), "6")
        self.assertEqual(how, "bare_number")

    def test_sentence_is_cut_at_full_stops_not_decimals(self):
        text = "We ran 0.5 costs. Reserves are 8M. Done."
        start, end, _ = da.locate(text, 8000000.0, "8 m")
        self.assertEqual(da.sentence_around(text, start, end), "Reserves are 8M")


class DirectiveTests(unittest.TestCase):
    def test_decimal_values_are_kept_whole(self):
        prompt = "Current directives: tax = 0.2; welfare = 0.02; military = 0.03."
        self.assertEqual(da.directive_in_force(prompt, "tax"), "0.2")
        self.assertEqual(da.directive_in_force(prompt, "military"), "0.03")

    def test_missing_lever(self):
        self.assertEqual(da.directive_in_force("Current directives: tax = 0.2.", "navy_mission"), "(not listed)")

    def test_patronage_order_is_read_under_its_key(self):
        raw = '{"orders": {"army": {"patronage": false}}}'
        self.assertIs(da.raw_order(raw, "army", "patronage_army"), False)


if __name__ == "__main__":
    unittest.main()
