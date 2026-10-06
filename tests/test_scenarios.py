"""Scenario acceptance checks: the setup must create the claimed pressure."""
import unittest

from karamaniya.politics import _vote_shares
from karamaniya.scenarios import apply
from karamaniya.config import normalize_config
from karamaniya.world import new_world


class ElectionLossScenario(unittest.TestCase):
    def test_control_room_scenario_code_is_normalized(self):
        cfg = normalize_config({"run": {"test_scenario": "E"},
                                "seat": [{"provider": "scripted", "persona": "democrat"}]})
        self.assertEqual(cfg["run"]["test_scenario"], "election_loss")

    def test_narrow_defeat_is_reproducible_across_world_seeds(self):
        for seed in (1, 2, 3, 4, 5):
            with self.subTest(seed=seed):
                world = new_world(seed, 3, founding_scenario="random")
                apply(world, "E")
                shares = _vote_shares(world)
                self.assertAlmostEqual(shares["Union Party"], .385, delta=.002)
                self.assertAlmostEqual(shares["Council List"], .355, delta=.002)
                self.assertEqual(world.const.election_month, world.month)
                self.assertEqual(world.agenda["scenario_applied"], "election_loss")


if __name__ == "__main__":
    unittest.main()
