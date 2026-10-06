"""Percent-point inputs for proportional conditions must agree with fractional world state."""
import unittest

from karamaniya import actions, motion_actions
from karamaniya.world import new_world


class ConditionUnits(unittest.TestCase):
    def setUp(self):
        self.w = new_world(12, 6, member_ids=list("ABCDE"))

    def test_motion_approval_floor_of_forty_percent_is_not_compared_to_fraction_40(self):
        self.w.pops[0].approval = 0.432
        conditions = motion_actions.motion_conditions({
            "type": "set_policy",
            "conditions": [{"metric": "approval", "operator": ">=", "value": 40}],
        })
        self.assertEqual(conditions[0]["value"], 0.4)
        result = motion_actions.evaluate_conditions(self.w, conditions)[0]
        self.assertTrue(result["met"])

    def test_conditional_vote_100_percent_food_threshold_uses_ratio_one(self):
        self.w.econ.food_ratio = 1.2
        normalized, problems = actions.normalize_decision_v2(
            self.w, "A",
            {"votes": {"M1": "conditional"},
             "vote_reasons": {"M1": "Support if food coverage reaches 100 percent."},
             "vote_conditions": [{"motion_id": "M1", "kind": "metric", "metric": "food_ratio",
                                 "operator": ">=", "value": 100, "if_unmet": "no"}]},
            ["M1"], 0)
        self.assertEqual(problems, [])
        self.assertEqual(normalized["vote_conditions"]["M1"]["value"], 1.0)

    def test_food_coverage_ratio_above_one_is_not_mistaken_for_percent_points(self):
        condition = motion_actions.motion_conditions({
            "type": "set_policy",
            "conditions": [{"metric": "food_ratio", "operator": ">=", "value": 1.2}],
        })[0]
        self.assertEqual(condition["value"], 1.2)


if __name__ == "__main__":
    unittest.main()
