"""Codex's --output-schema is strict: every property required, optional ones nullable. The council's
own schemas have optional fields (a motion's action and conditions), so they are converted on the
way in and the nulls dropped on the way out."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions  # noqa: E402
from karamaniya.backends.codex_cli import drop_optional_nulls, strict_schema  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def objects(node):
    if isinstance(node, dict):
        if isinstance(node.get("properties"), dict):
            yield node
        for value in node.values():
            yield from objects(value)
    elif isinstance(node, list):
        for value in node:
            yield from objects(value)


class StrictSchema(unittest.TestCase):
    def test_every_object_requires_all_its_properties(self):
        schema = actions.motion_schema(new_world(3))
        self.assertTrue(any(set(o.get("required", [])) != set(o["properties"]) for o in objects(schema)))
        for o in objects(strict_schema(schema)):
            self.assertEqual(set(o["required"]), set(o["properties"]))
            self.assertIs(o["additionalProperties"], False)

    def test_optional_fields_become_nullable_and_required_ones_do_not(self):
        schema = {"type": "object", "additionalProperties": False, "required": ["kind"],
                  "properties": {"kind": {"type": "string", "enum": ["a", "b"]},
                                 "note": {"type": "string"},
                                 "pick": {"type": "string", "enum": ["x", "y"]},
                                 "extra": {"type": "object", "properties": {"n": {"type": "number"}}}}}
        out = strict_schema(schema)["properties"]
        self.assertEqual(out["kind"], {"type": "string", "enum": ["a", "b"]})
        self.assertEqual(out["note"]["type"], ["string", "null"])
        self.assertEqual(out["pick"]["enum"], ["x", "y", None])
        self.assertEqual(out["extra"]["anyOf"][1], {"type": "null"})
        self.assertEqual(out["extra"]["anyOf"][0]["required"], ["n"])

    def test_nulls_for_optional_fields_are_dropped_from_the_answer(self):
        schema = actions.motion_schema(new_world(3))
        answer = {"type": "set_policy", "subject": "tax", "value": "0.2", "text": "", "summary": "tax",
                  "action": {"action_type": None, "target": None, "issue": None, "terms": None},
                  "conditions": [{"metric": "reserves", "operator": ">=", "value": 45, "source": None}]}
        cleaned = drop_optional_nulls(answer, schema)
        self.assertEqual(cleaned["action"], {})                       # optional act fields left out
        self.assertEqual(cleaned["conditions"], [{"metric": "reserves", "operator": ">=", "value": 45}])
        self.assertEqual(cleaned["subject"], "tax")
        # A required field keeps whatever the model sent, null included: nothing is invented or hidden.
        self.assertIn("text", drop_optional_nulls({**answer, "text": None}, schema))


if __name__ == "__main__":
    unittest.main()
