"""Integrity checks for malformed canonical state."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya.state_validation import refresh
from karamaniya.world import new_world


class StateValidationTests(unittest.TestCase):
    def test_malformed_numeric_state_is_reported_without_raising(self):
        cases = (
            ("debt_dom", "debt_dom", None),
            ("debt_for", "debt_for", "not-a-number"),
            ("gold", "reserves", -1.0),
        )
        for field, label, value in cases:
            with self.subTest(field=field, value=value):
                world = new_world(1, human_factor=False)
                setattr(world.econ, field, value)

                result = refresh(world)

                self.assertEqual(result["status"], "warnings")
                self.assertTrue(any(
                    warning["code"] == "invalid_numeric_state"
                    and label in warning["detail"]
                    for warning in result["warnings"]
                ))

    def test_league_trust_must_be_finite_and_in_unit_interval(self):
        for value in (None, "not-a-number", -0.06, 1.01):
            with self.subTest(value=value):
                world = new_world(1, human_factor=False)
                world.dip.league_trust = value

                result = refresh(world)

                self.assertEqual(result["status"], "warnings")
                self.assertTrue(any(
                    warning["code"] == "invalid_numeric_state"
                    and "league_trust" in warning["detail"]
                    for warning in result["warnings"]
                ))


if __name__ == "__main__":
    unittest.main()
