"""World engine 21: a refused amendment goes back to its proposer once, and a refusal that stands is shown (T100).

In run 20261011-105713-seed1 the proposer of M7 announced an amendment to partial recruitment and an army target of
38,000. One of its six measures had a value its lever does not take (regional_fund "0.01"), so the whole amendment was
refused, and no one was told: the council voted 5-0 on the text as tabled, and three delegates' notes recorded the
amendment as law. The seats here are the engine's scripted stand-ins with Delegate A's answers set by each test.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import decision_context, prompts, versions  # noqa: E402
from tests.test_engine19_council import scripted_council, seat_backend  # noqa: E402

PACKAGE_TEXT = "Kessel package: regional development money for Kessel, farm support raised, volunteer recruitment."
AMENDED_TEXT = "Kessel package: regional development money for Kessel, farm support raised, partial recruitment."
PACKAGE = {"type": "program", "subject": "", "value": "", "text": PACKAGE_TEXT,
           "action": {"measures": [{"lever": "regional_fund", "value": "kessel"},
                                   {"lever": "farm_support", "value": "0.02"},
                                   {"lever": "recruitment", "value": "volunteer"}]},
           "conditions": [], "force_agenda": True}


def amendment(motion_id: str, fund: str) -> dict:
    return {"motion_id": motion_id, "value": "", "text": AMENDED_TEXT,
            "measures": [{"lever": "regional_fund", "value": fund}, {"lever": "farm_support", "value": "0.02"},
                         {"lever": "recruitment", "value": "partial"}]}


def package_seat(sent_again, calls: list, prompts_seen: dict):
    """Delegate A tables PACKAGE in the second month and amends it with a regional fund the lever does not take
    ("0.01"); asked again, it sends `sent_again(motion_id)`. Every delegate votes yes."""
    def on_answer(context, res):
        phase, mid, w = context.get("phase"), context.get("member"), context.get("world")
        calls.append((phase, mid))
        package = next((m for m in context.get("motions") or [] if m.get("text") == PACKAGE_TEXT), None)
        if phase == "amendment_repair":
            res.data = {"amend": sent_again(package["id"])}
            return
        if w is None or w.month != 1 or not isinstance(res.data, dict):
            return
        if phase == "session":
            res.data["agenda_priorities"] = []
            res.data["motions"] = [dict(PACKAGE)] if mid == "A" else []
        if phase == "revision":
            res.data["withdraw"] = []
            res.data["amend"] = [amendment(package["id"], "0.01")] if mid == "A" and package else []
        if phase == "decision":
            motions = context.get("motions") or []
            res.data["votes"] = {m["id"]: "yes" for m in motions}
            res.data["vote_reasons"] = {m["id"]: "yes" for m in motions}
            res.data["vote_conditions"] = []
    return seat_backend(on_answer)


class Versions(unittest.TestCase):
    def test_the_bump(self):
        self.assertEqual((versions.WORLD_ENGINE, versions.AGENT_PROMPT, versions.PSYCHOLOGY), (21, 18, 8))


class ARefusedAmendmentGoesBackOnce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="engine21-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def month(self, sent_again):
        calls, seen = [], {}
        council, w = scripted_council(self.tmp, package_seat(sent_again, calls, seen))
        council.run_month()
        record = council.run_month()
        package = next(m for m in record["motions"] if m.get("text") in (PACKAGE_TEXT, AMENDED_TEXT))
        return council, w, record, package, calls

    def test_the_proposer_sends_it_again_corrected_and_it_is_voted_and_executed(self):
        _, w, record, package, calls = self.month(lambda motion_id: [amendment(motion_id, "kessel")])
        self.assertEqual(calls.count(("amendment_repair", "A")), 1)
        self.assertTrue(package["amended"])
        self.assertNotIn("amendment_refused", package)
        self.assertEqual(package["text"], AMENDED_TEXT)
        repairs = record["revisions"]["A"]["amendment_repairs"]
        self.assertEqual([(r["motion"], r["amended"], r["refused"]["reason_code"]) for r in repairs],
                         [(package["id"], True, "BAD_VALUE")])
        self.assertEqual(record["revisions"]["A"]["rejected_amendments"], [])
        self.assertTrue(package["passed"])
        self.assertEqual(w.policy.recruitment, "partial")

    def test_a_refusal_that_stands_is_shown_to_every_voter(self):
        council, w, record, package, calls = self.month(lambda motion_id: [])
        self.assertEqual(calls.count(("amendment_repair", "A")), 1)
        self.assertFalse(package.get("amended"))
        self.assertEqual(package["text"], PACKAGE_TEXT)
        self.assertIn("regional_fund", package["amendment_refused"]["explanation"])
        self.assertEqual(record["revisions"]["A"]["amendment_repairs"][0]["amended"], False)
        self.assertEqual(len(record["revisions"]["A"]["rejected_amendments"]), 1)
        self.assertEqual(w.policy.recruitment, "volunteer")         # the text as tabled, as voted
        block = decision_context.motion_block(w, "B", [package])
        self.assertIn("an amendment its proposer sent was refused (bad value '0.01' for regional_fund", block)
        self.assertIn("the vote is on this text as tabled", block)
        transcript = prompts.transcript_v2(w, record["statements"], [package], [], record["revisions"])
        self.assertIn(f"amendment of {package['id']} was refused, so it stands as tabled", transcript)

    def test_no_refusal_no_repair_call(self):
        def seat_without_bad_amendment(sent_again, calls, seen):
            inner = package_seat(sent_again, calls, seen)

            class Seat(inner):
                def call(self, system, user, schema, context):
                    res = super().call(system, user, schema, context)
                    if context.get("phase") == "revision" and isinstance(res.data, dict):
                        res.data["amend"] = []
                    return res
            return Seat
        calls = []
        council, w = scripted_council(self.tmp, seat_without_bad_amendment(lambda motion_id: [], calls, {}))
        council.run_month()
        council.run_month()
        self.assertNotIn("amendment_repair", [phase for phase, _ in calls])


if __name__ == "__main__":
    unittest.main()
