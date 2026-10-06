import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya.backends import CallResult  # noqa: E402
from karamaniya.council import Council  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


class DuplicatePrinciplesRepair(unittest.TestCase):
    def test_only_the_duplicate_gets_a_targeted_restatement(self):
        world = new_world(31)
        council = Council.__new__(Council)
        council.w = world
        council.observer = None
        prompts = []

        def repair(mid, phase, user, schema, context):
            prompts.append((mid, phase, user, schema))
            return CallResult(data={"principles": "I favour local accountability and balanced public budgets."},
                              served_model="test")

        council._call = repair
        duplicate = "I support accountable democracy, peaceful politics, and careful public spending."
        opening = [("A", CallResult(data={}), {"principles": duplicate}, []),
                   ("B", CallResult(data={}), {"principles": duplicate}, [])]
        calls = []
        repaired = council._repair_duplicate_principles(opening, calls)
        self.assertEqual(repaired[0][2]["principles"], duplicate)
        self.assertNotEqual(repaired[1][2]["principles"], duplicate)
        self.assertEqual([(x[0], x[1]) for x in prompts], [("B", "principles_repair")])
        self.assertEqual(calls[0]["phase"], "principles_repair")

    def test_missing_program_payload_gets_one_format_only_retry(self):
        world = new_world(32)
        council = Council.__new__(Council)
        council.w = world
        council.observer = None
        original = {"type": "program", "subject": "", "value": '["fleet_capacity", "build"]',
                    "text": "Naval expansion program: accelerate shipbuilding.", "action": {}, "force_agenda": False}
        calls = []
        response = {"motions": [{**{k: original[k] for k in ("type", "subject", "value", "text")},
                                 "action": {"measures": [{"lever": "shipbuilding", "value": "on"}]}}]}
        council._call = lambda *args, **kwargs: CallResult(data=response, served_model="test")
        fixed, problems = council._repair_structured_action("A", original,
            {"reason_code": "NO_STRUCTURED_ACTION", "explanation": "program requires measures"}, calls)
        self.assertIsNotNone(fixed, problems)
        self.assertEqual(fixed["type"], original["type"])
        self.assertEqual(fixed["value"], original["value"])
        self.assertEqual(fixed["text"], original["text"])
        self.assertEqual(fixed["action"]["measures"], [{"lever": "shipbuilding", "value": "on"}])
        self.assertEqual(len(calls), 1)

    def test_structured_action_repair_cannot_change_the_policy_proposal(self):
        world = new_world(33)
        council = Council.__new__(Council)
        council.w = world
        council.observer = None
        original = {"type": "program", "subject": "", "value": "", "text": "Expand shipbuilding.",
                    "action": {}, "force_agenda": False}
        council._call = lambda *args, **kwargs: CallResult(data={"motions": [{"type": "set_policy",
            "subject": "tax", "value": "0.5", "text": "raise tax"}]}, served_model="test")
        fixed, problems = council._repair_structured_action("A", original,
            {"reason_code": "NO_STRUCTURED_ACTION", "explanation": "missing measures"}, [])
        self.assertIsNone(fixed)
        self.assertTrue(any("changed the stated motion" in x for x in problems))

    def test_invalid_structured_action_repair_is_reported_without_crashing(self):
        world = new_world(34)
        council = Council.__new__(Council)
        council.w = world
        council.observer = None
        original = {"type": "program", "subject": "", "value": '[]',
                    "text": "Expand the navy.", "action": {}, "force_agenda": False}
        response = {"motions": [{**{k: original[k] for k in ("type", "subject", "value", "text")},
                                 "action": {"measures": [{"lever": "unknown_shipbuilding_measure",
                                                            "value": "on"}]}}]}
        council._call = lambda *args, **kwargs: CallResult(data=response, served_model="test")

        fixed, problems = council._repair_structured_action("A", original,
            {"reason_code": "NO_STRUCTURED_ACTION", "explanation": "program requires measures"}, [])

        self.assertIsNone(fixed)
        self.assertTrue(any("repair remained invalid:" in problem for problem in problems))


if __name__ == "__main__":
    unittest.main()
