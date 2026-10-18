"""RR5: the calibration sweep's records and band checks (tools/regime_sweep.py).

The sweep itself is expensive (dozens of 36-month scripted runs); these tests exercise the parts that turn a run
into a record and a set of records into the three bands, plus one short real run through the same `_run` path a
worker uses. The band arithmetic is checked on fabricated records so each branch — no quiet revolutions, the stress
ratio, an empty crackdown sample — is covered without waiting for a seed to produce it.

    python -m unittest tests.test_rr5_sweep
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, ROOT)
sys.path.insert(0, TOOLS)

import regime_sweep  # noqa: E402


def check(month, *, security=0.6, met=False, fired=False, crackdown=None):
    row = {"month": month, "uprising_check": {
        "month": month, "security": security, "thresholds_met": met, "fired": fired}}
    if crackdown is not None:
        row["uprising_check"]["crackdown"] = {"outcome": crackdown}
    return row


def record(model, mode, seed, *, outcome="survived", zone=0, crackdowns=None, history=None, preset="stress"):
    if history is None:
        history = [check(m, met=True) for m in range(zone)]
    return regime_sweep.summary(mode, seed, model, history, {"type": outcome, "month": 35},
                                {"regime_relief": {"head_changes": [
                                    {"granted": True, "why": "new_head"},
                                    {"granted": False, "why": "coup_blocked"}]}},
                                [{"kind": "protest", "concession_credibility": 0.3},
                                 {"kind": "protest", "concession_credibility": 0.0},
                                 {"kind": "protest"}], preset=preset)


class SummaryTests(unittest.TestCase):
    def test_the_record_counts_the_zone_the_crackdowns_and_the_relief(self):
        history = [
            check(0),                                                    # idle, no draw
            check(1, met=True, fired=True, crackdown="massacre"),
            check(2, security=0.7, met=True, fired=True, crackdown="uprising_succeeds"),
            check(3, security=0.5, met=True, fired=True, crackdown="civil_war"),
        ]
        r = regime_sweep.summary("scripted", 4, "legitimacy", history, {"type": "kept_power_by_force", "month": 3},
                                 {}, [])
        self.assertEqual(r["zone_months"], 3)
        self.assertEqual(r["fired_months"], 3)
        self.assertEqual(r["crackdowns"]["attempted"], 3)
        self.assertEqual(r["crackdowns"]["failed"], 2)
        self.assertEqual(r["crackdowns"]["outcomes"], {"massacre": 1, "uprising_succeeds": 1, "civil_war": 1})
        self.assertEqual(r["crackdowns"]["in_security_band"], 1)
        self.assertEqual(r["crackdowns"]["failed_in_security_band"], 0)

    def test_talks_are_read_from_every_month_row_not_the_last_month_only(self):
        history = [{"month": 0, "events": [{"kind": "protest", "concession_credibility": 0.4}]},
                   {"month": 1, "events": [{"kind": "protest"}]}]
        r = regime_sweep.summary("dove", 1, "legitimacy", history, {"type": "survived"}, {}, [])
        self.assertEqual(r["talks"]["count"], 1)
        self.assertEqual(r["talks"]["with_concessions"], 1)

    def test_the_honeymoon_and_talk_figures_read_the_final_state(self):
        history = [check(0)]
        events = [{"kind": "protest", "concession_credibility": 0.4},
                  {"kind": "protest", "concession_credibility": 0.2},
                  {"kind": "protest", "concession_credibility": 0.0},
                  {"kind": "protest"}]
        changes = [{"granted": True, "why": "new_head"}, {"granted": False, "why": "coup_blocked"},
                   {"granted": False, "why": "within_12_months"}]
        r = regime_sweep.summary("hawk", 1, "legitimacy", history, {"type": "survived", "month": 0},
                                 {"regime_relief": {"head_changes": changes}}, events)
        self.assertEqual(r["honeymoons"], {"changes": 3, "granted": 1,
                                           "blocked": {"coup_blocked": 1, "within_12_months": 1}})
        self.assertEqual(r["talks"]["count"], 3)
        self.assertEqual(r["talks"]["with_concessions"], 2)
        self.assertEqual(r["talks"]["mean_concession_credibility"], 0.2)
        self.assertEqual(r["talks"]["max_concession_credibility"], 0.4)

    def test_a_legacy_row_has_no_checks_and_records_zeros(self):
        r = regime_sweep.summary("dove", 2, "legacy", [{"month": 0, "approval": 0.4, "unrest": 0.2}],
                                 {"type": "voted_out", "month": 0}, {}, [])
        self.assertEqual(r["zone_months"], 0)
        self.assertEqual(r["crackdowns"]["attempted"], 0)
        self.assertEqual(r["honeymoons"]["changes"], 0)

    def test_a_legacy_run_zone_is_read_from_its_own_thresholds(self):
        history = [{"month": 0, "approval": 0.19, "unrest": 0.5},
                   {"month": 1, "approval": 0.25, "unrest": 0.6},
                   {"month": 2, "approval": 0.1, "unrest": 0.44}]
        r = regime_sweep.summary("scripted", 3, "legacy", history, {"type": "revolution", "month": 2})
        self.assertEqual(r["zone_months"], 1, "only the row under both thresholds is in the zone")


class BandTests(unittest.TestCase):
    def test_a_quiet_run_that_ends_in_revolution_fails_the_quiet_band(self):
        records = [record("legitimacy", "dove", 1, outcome="revolution", zone=0),
                   record("legacy", "dove", 2, outcome="survived", zone=0)]
        band = regime_sweep.bands(records)["quiet_no_revolution"]
        self.assertEqual(band["quiet_runs"], 2)
        self.assertEqual(band["quiet_revolutions"], 1)
        self.assertFalse(band["met"])
        self.assertIn("dove-s1 (legitimacy)", band["revolution_runs"])

    def test_the_stress_ratio_uses_pairs_where_legacy_entered_the_zone(self):
        pairs = []
        # Four stress pairs: legacy enters the zone in all; it revolts in two, legitimacy in one (ratio .5, met).
        for seed in (1, 2):
            pairs.append(record("legacy", "scripted", seed, outcome="revolution", zone=2))
        for seed in (3, 4):
            pairs.append(record("legacy", "scripted", seed, outcome="survived", zone=2))
        for seed in (1, 2):
            pairs.append(record("legitimacy", "scripted", seed, outcome="survived", zone=1))
        for seed in (3, 4):
            pairs.append(record("legitimacy", "scripted", seed, outcome="survived", zone=0))
        # One quiet pair and one relief pair do not count.
        pairs += [record("legacy", "dove", 9, zone=0), record("legitimacy", "dove", 9, zone=0)]
        pairs += [record("legacy", "scripted", 10, preset="relief", outcome="revolution", zone=1),
                  record("legitimacy", "scripted", 10, preset="relief", outcome="survived", zone=1)]
        band = regime_sweep.bands(pairs)["legitimacy_against_legacy"]
        self.assertEqual(band["pairs"], 4)
        self.assertEqual(band["legacy_revolutions"], 2)
        self.assertEqual(band["legitimacy_revolutions"], 0)
        self.assertEqual(band["legacy_share"], 0.5)
        self.assertEqual(band["legitimacy_share"], 0.0)
        self.assertFalse(band["met"])

        for r in pairs:
            if r["model"] == "legitimacy" and r["seed"] == 1 and r["mode"] == "scripted":
                r["outcome"] = "revolution_union"
        band = regime_sweep.bands(pairs)["legitimacy_against_legacy"]
        self.assertEqual(band["legitimacy_revolutions"], 1)
        self.assertTrue(band["met"])

    def test_an_empty_crackdown_sample_does_not_pass_silently(self):
        records = [record("legitimacy", "scripted", 1, zone=0), record("legacy", "scripted", 1, zone=0)]
        band = regime_sweep.bands(records, [])["crackdown_failure"]
        self.assertEqual(band["observed"]["attempts"], 0)
        self.assertIsNone(band["observed"]["met"])
        self.assertFalse(band["met"], "the census alone is not the observed band")
        self.assertTrue(band["census"]["met"])
        self.assertEqual((band["census"]["min_failure"], band["census"]["max_failure"]), (0.2902, 0.3955))

    def test_the_forced_sample_carries_the_observed_band(self):
        history = [check(0, met=True, fired=True, crackdown="massacre"),
                   check(1, met=True, fired=True, crackdown="uprising_succeeds"),
                   check(2, met=True, fired=True, crackdown="uprising_succeeds"),
                   check(3, met=True, fired=True, crackdown="massacre")]
        records = [regime_sweep.summary("scripted", 1, "legitimacy", history, {"type": "survived"}, {}, [])]
        probes = [{"security": 0.6, "outcome": o} for o in
                  ("massacre", "uprising_succeeds", "uprising_succeeds", "massacre")]
        band = regime_sweep.bands(records, probes)["crackdown_failure"]
        self.assertEqual(band["observed"]["attempts"], 4)
        self.assertEqual(band["observed"]["failures"], 2)
        self.assertAlmostEqual(band["observed"]["failure_share"], 0.5)
        self.assertFalse(band["met"], "50% is outside 20-40% even though the census is inside")
        self.assertEqual(band["in_run"]["legitimacy"]["attempts"], 4)

    def test_a_probe_outside_the_security_band_is_not_counted(self):
        probes = [{"security": 0.6, "outcome": "massacre"}, {"security": 0.8, "outcome": "uprising_succeeds"}]
        sample = regime_sweep.crackdown_sample(probes)
        self.assertEqual((sample["attempts"], sample["failures"]), (1, 0))

    def test_a_real_probe_takes_its_own_draw_stream(self):
        probe = regime_sweep._crackdown_probe({"seed": 1, "month": 3})
        self.assertEqual((probe["seed"], probe["month"], probe["security"]), (1, 3, 0.6))
        self.assertIn(probe["outcome"], ("massacre", "uprising_succeeds", "civil_war"))

    def test_the_seed_and_name_parsers(self):
        self.assertEqual(regime_sweep._parse_ints("1-3,7"), [1, 2, 3, 7])
        self.assertEqual(regime_sweep._parse_names("legacy, legitimacy", ("legacy", "legitimacy")),
                         ["legacy", "legitimacy"])
        with self.assertRaises(SystemExit):
            regime_sweep._parse_names("pedigree", ("legacy", "legitimacy"))


class RealRunTests(unittest.TestCase):
    def test_one_short_run_travels_the_worker_path(self):
        r = regime_sweep._run({"preset": "default", "mode": "dove", "seed": 1, "model": "legitimacy", "months": 2})
        self.assertEqual((r["preset"], r["model"], r["mode"], r["seed"], r["months"]),
                         ("default", "legitimacy", "dove", 1, 2))
        self.assertTrue(r["outcome"])
        self.assertGreaterEqual(r["zone_months"], 0)


if __name__ == "__main__":
    unittest.main()
