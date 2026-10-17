"""Engine 28 (backlog T176): the ballot repair ask puts back every vote its own reason contradicts, and says so.

Engine 26 moved the ask to the reason check (T155) but kept the stance check's three-word filter, so only a reason under
three words ("No.") was asked about: "I will vote no on this motion." with a yes vote was not. The ask's text still
named the response-round position, and read "You said you would NO M1". The end-to-end cases are in
test_vote_intent_prose.py (EndToEndThroughARealCouncilMonth).

    python -m unittest tests.test_engine28_repair_ask
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import council  # noqa: E402

REASON_CLASH = {"code": "VOTE_INTENT_MISMATCH", "motion": "M2", "stance": "no", "vote": "yes",
                "reason": "No. It raises taxes in a famine.", "source": "reason"}
CONDITION_CLASH = {"code": "VOTE_CONDITION_REASON_MISMATCH", "motion": "M3", "metric": "food_ratio",
                   "reason_metrics": ["reserves"], "reason": "Only while reserves hold.", "motion_conflicts": []}


class TheAskNamesWhatConflicts(unittest.TestCase):
    def test_a_vote_against_its_reason_is_named_with_the_reason(self):
        text = "\n".join(council._repair_ask_lines([REASON_CLASH]))
        self.assertIn('- Your reason for M2 says NO, but your vote is YES: "No. It raises taxes in a famine."', text)
        self.assertIn("cast the vote you intend, with a reason that states it", text)
        self.assertNotIn("response-round", text)
        self.assertNotIn("conditional", text)           # no condition was asked about

    def test_a_condition_clash_keeps_its_instruction(self):
        text = "\n".join(council._repair_ask_lines([CONDITION_CLASH]))
        self.assertIn('- M3 tests food_ratio, but your reason refers to reserves: "Only while reserves hold."', text)
        self.assertIn("If no available condition can test your safeguard, choose yes, no or abstain instead of "
                      "conditional.", text)
        self.assertNotIn("cast the vote you intend", text)

    def test_both_kinds_in_one_ask(self):
        text = "\n".join(council._repair_ask_lines([REASON_CLASH, CONDITION_CLASH]))
        self.assertIn("Your reason for M2 says NO", text)
        self.assertIn("M3 tests food_ratio", text)
        self.assertIn("cast the vote you intend", text)
        self.assertIn("instead of conditional", text)


if __name__ == "__main__":
    unittest.main()
