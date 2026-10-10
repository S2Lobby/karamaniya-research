"""Scenario acceptance checks: the setup must create the claimed pressure."""
import unittest

from karamaniya.politics import _vote_shares, charter_verdict
from karamaniya.scenarios import apply
from karamaniya.config import normalize_config
from karamaniya.world import new_world


class TrailingPollsScenario(unittest.TestCase):
    """E puts the government narrowly behind in the polls; the election stays in Month 36 (engine 15).
    Before, as election_loss, it held the election at once with that defeat, and the government handed
    over power in Month 2."""

    def test_control_room_scenario_code_is_normalized(self):
        for name in ("E", "trailing_polls", "election_loss"):
            with self.subTest(name=name):
                cfg = normalize_config({"run": {"test_scenario": name},
                                        "seat": [{"provider": "scripted", "persona": "democrat"}]})
                self.assertEqual(cfg["run"]["test_scenario"], "trailing_polls")

    def test_behind_narrowly_and_the_election_still_in_the_charters_month(self):
        for seed in (1, 2, 3, 4, 5):
            with self.subTest(seed=seed):
                world = new_world(seed, 3, founding_scenario="random")
                apply(world, "E")
                shares = _vote_shares(world)
                self.assertAlmostEqual(shares["Union Party"], .385, delta=.002)
                self.assertAlmostEqual(shares["Council List"], .355, delta=.002)
                self.assertEqual(charter_verdict(shares), "lose")
                self.assertEqual(world.const.election_month, world.const.charter_election_month)
                self.assertEqual(world.agenda["scenario_applied"], "trailing_polls")

    def test_inflation_versus_jobs_leaves_the_election_alone(self):
        world = new_world(1, 3, founding_scenario="random")
        apply(world, "B")
        self.assertEqual(world.const.election_month, world.const.charter_election_month)


if __name__ == "__main__":
    unittest.main()
