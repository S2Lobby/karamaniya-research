"""The two research detectors, measured on the hand labels in docs/detector_labels (worker 25, backlog T144).

- VOTE_INTENT_MISMATCH is recorded only where the vote's own stated reason contradicts the vote. The labelled rows
  (D2_labelled_36.csv) are the test set: none of the 34 false positives may be flagged. The one true mismatch (D2-013)
  is a known miss: its reason argues the point in words, with no plain verdict, and this check does not parse that.
- NUMERIC_GROUNDING_ERROR flags a figure only when it is tied unambiguously to one metric and is clearly wrong. The
  labelled sentences (D1_evidence_all137.csv, D1_labels_sample40.csv) are the test set, and the cases below are the
  failure causes the labels name.

Nothing here reads recorded runs (research\\runs): every input is a committed file or a literal.
"""
import csv
import os
import sys
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import council as C  # noqa: E402
from karamaniya import motion_actions as ma  # noqa: E402

LABELS = os.path.join(ROOT, "docs", "detector_labels")


def _rows(name):
    with open(os.path.join(LABELS, name), encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ---- VOTE_INTENT_MISMATCH: the vote against its own reason ---------------------------------------------------------
class ReasonVerdictOnTheLabelledBallots(unittest.TestCase):
    """The 36 ballots that the stance comparison flagged. The reason, not the stance, is the reference."""

    def test_no_labelled_false_positive_is_flagged(self):
        flagged = []
        for row in _rows("D2_labelled_36.csv"):
            decision = {"votes": {"M": row["vote"]}, "vote_reasons_full": {"M": row["reason_full"]}}
            if C._reason_contradictions(decision):
                flagged.append((row["flag_id"], row["label"]))
        false_positives = [f for f in flagged if f[1] != "TRUE_MISMATCH"]
        self.assertEqual(false_positives, [], "a labelled false positive is still flagged")

    def test_the_one_true_mismatch_is_a_known_miss(self):
        # D2-013: "Reducing surveillance is essential ..." against a yes. No plain verdict, so it is not read.
        row = next(r for r in _rows("D2_labelled_36.csv") if r["flag_id"] == "D2-013")
        self.assertEqual(row["label"], "TRUE_MISMATCH")
        decision = {"votes": {"M": row["vote"]}, "vote_reasons_full": {"M": row["reason_full"]}}
        self.assertEqual(C._reason_contradictions(decision), [],
                         "the known miss changed: re-measure precision and recall on the labelled rows")


class ReasonVerdicts(unittest.TestCase):
    def flags(self, vote, reason, motion="M2"):
        return C._reason_contradictions({"votes": {motion: vote}, "vote_reasons_full": {motion: reason}})

    def test_an_opening_verdict_against_the_vote_is_flagged(self):
        found = self.flags("yes", "No. Raising taxes now deepens the slump.")
        self.assertEqual([(f["motion"], f["vote"], f["stance"], f["source"]) for f in found],
                         [("M2", "yes", "no", "reason")])

    def test_an_opening_verdict_that_agrees_with_the_vote_is_not_flagged(self):
        self.assertEqual(self.flags("no", "No. Raising taxes now deepens the slump."), [])
        self.assertEqual(self.flags("yes", "Yes, the pact secures border calm."), [])

    def test_a_first_person_verdict_against_the_vote_is_flagged(self):
        self.assertEqual(len(self.flags("yes", "I oppose this, because the cost is too high.")), 1)
        self.assertEqual(len(self.flags("no", "I will vote yes; the audit is overdue.")), 1)

    def test_a_first_person_verdict_that_agrees_with_the_vote_is_not_flagged(self):
        self.assertEqual(self.flags("yes", "I support the review, but the cost is too high."), [])

    def test_a_conditional_reason_states_no_verdict(self):
        self.assertEqual(self.flags("yes", "I would oppose it unless the cost falls."), [])
        self.assertEqual(self.flags("yes", "No, unless the terms change."), [])

    def test_a_reason_that_argues_the_other_way_is_not_read(self):
        # The direction of "reducing surveillance is essential" depends on the motion's wording: not parsed.
        self.assertEqual(self.flags("yes", "Reducing surveillance is essential to prevent capital flight."), [])

    def test_a_determiner_no_is_not_a_verdict(self):
        self.assertEqual(self.flags("yes", "No conditions are needed for the loan."), [])

    def test_contradictory_first_person_verdicts_say_nothing(self):
        self.assertEqual(self.flags("yes", "I support the goal, but I oppose the text."), [])

    def test_abstentions_and_conditional_votes_are_not_flagged(self):
        self.assertEqual(self.flags("abstain", "No. Raising taxes now deepens the slump."), [])
        self.assertEqual(self.flags("conditional", "No. Raising taxes now deepens the slump."), [])

    def test_an_empty_reason_says_nothing(self):
        self.assertEqual(self.flags("yes", ""), [])
        self.assertEqual(C._reason_contradictions({"votes": {"M2": "yes"}}), [])


# ---- NUMERIC_GROUNDING_ERROR: a figure tied to one metric, clearly wrong -------------------------------------------
class _World:
    """Only the attributes check_numeric_grounding reads (as tools/detector_audit.py's replay stub)."""
    month = 0
    econ = SimpleNamespace(food_ratio=1.0, gold=0.0, arrears=0.0, unemployment=0.0)
    mil = SimpleNamespace(army=SimpleNamespace(size=0.0, morale=0.0, loyalty=0.0))

    def k_pops(self):
        return []

    def population(self):
        return 1.0


def check(text, metric, truth, sources=""):
    """The check on `text`, with `truth` as the canonical value of `metric` and `sources` as what the delegate was shown."""
    orig_truth, orig_src = ma._grounding_truth, ma.information_available_to

    def _truth(w, key):
        if key == "hunger":
            return 0.0
        if key != metric:
            raise KeyError(key)
        return truth

    ma._grounding_truth = _truth
    ma.information_available_to = lambda w, mid: [{"label": "briefing", "text": sources}]
    try:
        return ma.check_numeric_grounding(_World(), "A", text)
    finally:
        ma._grounding_truth, ma.information_available_to = orig_truth, orig_src


class LabelledSentences(unittest.TestCase):
    """The 40 sampled flags, judged from their committed sentence, the observed value and the briefing lines."""

    def test_no_labelled_false_positive_is_flagged(self):
        labels = {}
        for name in ("D1_labels_sample40.csv", "D1_labels_replay_unsampled11.csv"):
            for row in _rows(name):
                labels[row["flag_id"]] = row["label"]
        flagged = []
        for row in _rows("D1_evidence_all137.csv"):
            if row["in_sample"] != "yes" or labels.get(row["flag_id"]) != "FALSE_POSITIVE":
                continue
            claim = check(row["sentence"], row["metric"], float(row["observed"]), row["briefing"])
            if claim:
                flagged.append((row["flag_id"], claim["metric"], claim["claim_text"]))
        self.assertEqual(flagged, [], "labelled false positives still flagged")


class TieToOneMetric(unittest.TestCase):
    """Each case is a cause the labels name. A figure whose metric is not tied unambiguously is unverifiable."""

    def test_a_count_of_output_is_not_unemployment(self):
        self.assertIsNone(check("Economy: output 82, unemployment 10%, food 98%.", "unemployment", 0.101))

    def test_a_troop_figure_beside_an_other_side_word_is_not_the_unions(self):
        self.assertIsNone(check("Army actual 36.5k vs Union 98k.", "union_forces", 95000.0))

    def test_a_count_of_ships_is_not_readiness(self):
        self.assertIsNone(check("We count roughly 20 Union warships against our six, while fleet readiness is 57-69/100.", "army_readiness", 0.525))

    def test_a_figure_between_two_sides_is_not_judged(self):
        self.assertIsNone(check("Union 14 warships, ~106k troops vs our 59k under arms.", "army_size", 58690.0))

    def test_a_comparison_figure_is_not_readiness(self):
        self.assertIsNone(check("Fleet readiness 53-65/100 vs 13-16 Union warships.", "army_readiness", 0.56))

    def test_a_projection_is_not_the_current_level(self):
        self.assertIsNone(check("M2 League loan 50M: reserves 53M->~103M, pay buffer restored.", "reserves", 52.5e6))

    def test_a_threshold_after_the_figure_is_not_a_level(self):
        self.assertIsNone(check("Treasury reported nil arrears and a 60M floor in M4.", "arrears", 0.0))

    def test_a_monthly_accrual_is_not_the_stock(self):
        self.assertIsNone(check("4M still accrues as arrears (~127M next month).", "arrears", 138.1e6))

    def test_a_money_figure_is_never_a_troop_count(self):
        self.assertIsNone(check("Soldiers stand at 9-10M.", "army_size", 58589.0))

    def test_a_stated_level_is_still_checked(self):
        self.assertIsNotNone(check("Inflation is 40%.", "inflation", 0.0))
        self.assertIsNotNone(check("Unemployment has reached 9%.", "unemployment", 0.02))

    def test_a_reserves_level_is_still_checked(self):
        claim = check("Our reserves stand at 20,000,000 gold.", "reserves", 0.0)
        self.assertIsNotNone(claim)
        self.assertEqual(claim["metric"], "reserves")

    def test_a_union_figure_named_with_its_side_is_still_checked(self):
        claim = check("The Solvaran Union fields 95,000 troops against our 28,000.", "union_forces", 60000.0)
        self.assertIsNotNone(claim)
        self.assertEqual(claim["metric"], "union_forces")

    def test_an_amount_to_be_paid_is_not_a_level(self):
        self.assertIsNone(check("We will pay 10 million gold in wages.", "reserves", 5e6))


if __name__ == "__main__":
    unittest.main()
