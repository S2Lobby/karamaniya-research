"""Engine 34 (backlog T193): a communication a model writes as `warn` is read as `warning`.

Run 20261018-123257-seed1, Month 1: delegate D's model wrote a public communication to Delegate B as `warn`. The output
schema named fourteen kinds, `warning` among them, so `warn` was refused as an unknown kind and the seat was told so in
its next prompt. The alias reads it as the kind it means. Every other spelling is read as before, and an unknown kind
is still refused. Nothing here calls a model.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import actions, versions  # noqa: E402
from karamaniya.standing import COMM_KIND_ALIASES, COMM_KINDS  # noqa: E402


class CommunicationKindAlias(unittest.TestCase):
    def test_warn_is_read_as_warning(self):
        problems, refused = [], []
        out = actions._comms([{"kind": "warn", "target": "dorsania", "about": "Withdraw your forces."}], problems, refused)
        self.assertEqual(out, [{"kind": "warning", "target": "dorsania", "about": "Withdraw your forces."}])
        self.assertEqual(problems, [])
        self.assertEqual(refused, [])

    def test_the_spelling_is_not_case_or_space_sensitive(self):
        problems = []
        out = actions._comms([{"kind": "  WARN ", "target": "public", "about": ""}], problems)
        self.assertEqual([item["kind"] for item in out], ["warning"])
        self.assertEqual(problems, [])

    def test_an_unknown_kind_is_still_refused(self):
        problems, refused = [], []
        out = actions._comms([{"kind": "summons", "target": "public", "about": ""}], problems, refused)
        self.assertEqual(out, [])
        self.assertEqual(problems, ["unknown communication kind 'summons'"])
        self.assertEqual([r["reason"] for r in refused], ["unknown communication kind 'summons'"])

    def test_warning_and_the_other_kinds_are_read_as_before(self):
        problems = []
        out = actions._comms([{"kind": "warning", "target": "league", "about": "Withdraw your forces."},
                              {"kind": "endorse", "target": "public", "about": "Withdraw your forces."}], problems)
        self.assertEqual([item["kind"] for item in out], ["warning", "endorse"])
        self.assertEqual(problems, [])

    def test_every_alias_names_a_kind_the_schema_offers(self):
        for alias, kind in COMM_KIND_ALIASES.items():
            self.assertIn(kind, COMM_KINDS)
            self.assertNotIn(alias, COMM_KINDS)

    def test_the_version_is_engine_34_or_later(self):
        self.assertGreaterEqual(versions.WORLD_ENGINE, 34)


if __name__ == "__main__":
    unittest.main()
