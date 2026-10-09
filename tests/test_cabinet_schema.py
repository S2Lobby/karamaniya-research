"""Foreign cabinet reply schemas must pass strict validators: no enum may repeat an item."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import foreign  # noqa: E402


def enums(node):
    if isinstance(node, dict):
        if isinstance(node.get("enum"), list):
            yield node["enum"]
        for value in node.values():
            yield from enums(value)
    elif isinstance(node, list):
        for value in node:
            yield from enums(value)


class CabinetSchema(unittest.TestCase):
    def test_no_enum_repeats_an_item(self):
        for actor in (None, "veleria", "dorsania"):
            with self.subTest(actor=actor):
                for items in enums(foreign.cabinet_schema(actor)):
                    self.assertEqual(len(items), len(set(items)), items)

    def test_each_cabinet_is_offered_only_its_own_actions(self):
        kinds = lambda actor: foreign.cabinet_schema(actor)["properties"]["actions"]["items"]["properties"]["type"]["enum"]
        self.assertEqual(kinds("veleria"), [a["type"] for a in foreign.action_catalog("veleria")])
        self.assertEqual(kinds("dorsania"), [a["type"] for a in foreign.action_catalog("dorsania")])
        self.assertNotIn("grain_embargo", kinds("veleria"))
        self.assertNotIn("partial_embargo", kinds("dorsania"))
        # Engine 12: both cabinets can use force and set an ultimatum (foreign_force).
        for kind in ("deploy_to_border", "invade", "ultimatum"):
            self.assertIn(kind, kinds("veleria"))
            self.assertIn(kind, kinds("dorsania"))
        self.assertEqual(set(kinds(None)), set(kinds("veleria")) | set(kinds("dorsania")))


if __name__ == "__main__":
    unittest.main()
