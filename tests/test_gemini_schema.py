"""Gemini, through the Antigravity CLI, takes a narrower JSON schema than the other providers: an enum
value must be a non-empty string, and a field has one type. The council's schemas use "" for an
office left out of a formation slate and the numbers 3, 6 and 12 for forecast horizons, which Gemini
rejected with INVALID_ARGUMENT before the model saw the prompt. They are rewritten on the way in and
the answer is mapped back on the way out; a schema Gemini already accepts goes out unchanged."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya.backends import base  # noqa: E402
from karamaniya.backends.antigravity_cli import gemini_schema, restore  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")


def nodes(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from nodes(value)


def gemini_rejects(schema) -> list:
    problems = []
    for n in nodes(schema):
        if isinstance(n.get("enum"), list) and any(v == "" or not isinstance(v, str) for v in n["enum"]):
            problems.append(n["enum"])
        if isinstance(n.get("type"), list):
            problems.append(n["type"])
    return problems


class EveryCouncilSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-gemini-")
        cls.sent = {}
        complete = base.Backend.complete

        def record(self, system, user, schema, context=None):
            cls.sent.setdefault((context or {}).get("phase", "?"), []).append(schema)
            return complete(self, system, user, schema, context)

        with mock.patch.object(base.Backend, "complete", record):
            new_run(CONFIG, runs_dir=cls.tmp, name="gemini", months=2, quiet=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_schemas_gemini_rejected_are_among_those_sent(self):
        self.assertTrue(gemini_rejects(self.sent["formation_proposal"][0]))
        self.assertTrue(gemini_rejects(self.sent["decision"][0]))

    def test_every_schema_is_sent_in_a_form_gemini_accepts(self):
        for phase, schemas in self.sent.items():
            for schema in schemas:
                self.assertEqual(gemini_rejects(gemini_schema(schema)), [], phase)

    def test_a_schema_gemini_accepts_goes_out_unchanged(self):
        unchanged = [s for schemas in self.sent.values() for s in schemas if not gemini_rejects(s)]
        self.assertTrue(unchanged)
        for schema in unchanged:
            self.assertEqual(gemini_schema(schema), schema)


class RoundTrip(unittest.TestCase):
    SLATE = {"type": "object", "properties": {"head": {"type": "string", "enum": ["A", "B", ""]},
                                              "second": {"type": "string", "enum": ["fiscal", "none"]}}}

    def test_an_empty_office_is_sent_as_a_word_and_read_back_as_empty(self):
        sent = gemini_schema(self.SLATE)["properties"]["head"]
        self.assertEqual(sent["enum"], ["A", "B", "none"])
        self.assertIn('"none" stands for the empty string', sent["description"])
        self.assertEqual(restore({"head": "none", "second": "none"}, self.SLATE), {"head": "", "second": "none"})
        self.assertEqual(restore({"head": "B"}, self.SLATE), {"head": "B"})

    def test_the_word_for_empty_is_one_the_enum_does_not_use(self):
        schema = {"type": "string", "enum": ["none", "A", ""]}
        self.assertEqual(gemini_schema(schema)["enum"], ["none", "A", "empty"])
        self.assertEqual(restore("empty", schema), "")
        self.assertEqual(restore("none", schema), "none")

    def test_numbers_are_sent_as_their_digits_and_read_back_as_numbers(self):
        schema = {"type": "array", "items": {"type": "object", "properties": {
            "horizon_months": {"type": "integer", "enum": [3, 6, 12], "minimum": 3}}}}
        sent = gemini_schema(schema)["items"]["properties"]["horizon_months"]
        self.assertEqual(sent, {"type": "string", "enum": ["3", "6", "12"]})
        self.assertEqual(restore([{"horizon_months": "6"}, {"horizon_months": "9"}], schema),
                         [{"horizon_months": 6}, {"horizon_months": "9"}])  # the council judges "9" itself

    def test_a_type_list_becomes_one_nullable_type(self):
        self.assertEqual(gemini_schema({"type": ["string", "null"]}), {"type": "string", "nullable": True})


if __name__ == "__main__":
    unittest.main()
