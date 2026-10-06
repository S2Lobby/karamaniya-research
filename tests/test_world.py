"""The world without AIs: stability, pressure, money, food, determinism, save/load."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import director, engine  # noqa: E402
from karamaniya.world import World, new_world  # noqa: E402


def run(w: World, months: int, pressure: bool = True, each=None) -> World:
    original = director.act
    if not pressure:
        director.act = lambda world, *_args, **_kwargs: setattr(world.dip, "inbox", [])
    try:
        for _ in range(months):
            if w.ended():
                break
            engine.begin_month(w)
            if each:
                each(w)
            engine.step(w)
    finally:
        director.act = original
    return w


def no_election(w: World) -> None:
    """Keep runs going past Month 18 without the government losing office."""
    w.const.elected = True
    w.const.election_month = 99


class World_(unittest.TestCase):
    def test_league_trust_changes_clamp_and_sync_on_repeated_updates(self):
        w = new_world(8, 3)
        w.set_league_trust(.1)

        for _ in range(5):
            w.adjust_league_trust(-.2)
            self.assertEqual(w.dip.league_trust, 0.0)
            self.assertEqual(w.foreign["league"]["trust_in_karamaniya"], 0.0)

        for _ in range(10):
            w.adjust_league_trust(.2)
            self.assertGreaterEqual(w.dip.league_trust, 0.0)
            self.assertLessEqual(w.dip.league_trust, 1.0)
            self.assertEqual(w.dip.league_trust, w.foreign["league"]["trust_in_karamaniya"])
        self.assertEqual(w.dip.league_trust, 1.0)

        for _ in range(5):
            w.adjust_league_trust(.2)
            self.assertEqual(w.dip.league_trust, 1.0)
            self.assertEqual(w.foreign["league"]["trust_in_karamaniya"], 1.0)

    def test_load_clamps_and_synchronizes_legacy_league_trust(self):
        w = new_world(9, 3)
        data = w.to_dict()
        data["dip"]["league_trust"] = -0.06
        data["foreign"]["league"]["trust_in_karamaniya"] = .9

        restored = World.from_dict(data)

        self.assertEqual(restored.dip.league_trust, 0.0)
        self.assertEqual(restored.foreign["league"]["trust_in_karamaniya"], 0.0)

    def test_calm_world_is_stable(self):
        w = run(new_world(1, 36), 24, pressure=False, each=no_election)
        infl = [h["infl_yoy"] for h in w.history[12:]]
        self.assertTrue(all(-0.02 < x < 0.10 for x in infl), infl)
        self.assertTrue(0.40 < w.history[-1]["approval"] < 0.62, w.history[-1]["approval"])
        self.assertLess(w.counters["deaths_famine"], 100)
        self.assertEqual(w.outcome.get("type"), None)

    def test_unattended_world_can_collapse_or_survive_on_its_own_trajectory(self):
        w = run(new_world(1, 36), 36, each=no_election)
        self.assertIn(w.outcome.get("type"), ("survived", "revolution", "revolution_union", "officers_coup", "conquered"))
        if w.outcome["type"] == "survived":
            self.assertEqual(len(w.history), 36)
            self.assertEqual(w.history[-1]["outcome"], w.outcome)
        else:
            self.assertLess(w.outcome["month"], 30)

    def test_printing_causes_inflation(self):
        def printer(world):
            no_election(world)
            world.policy.printing = 0.05
        w = run(new_world(2, 36), 12, pressure=False, each=printer)
        base = run(new_world(2, 36), 12, pressure=False, each=no_election)
        self.assertGreater(w.econ.cpi, base.econ.cpi * 1.08)

    def test_survival_outcome_is_in_the_final_month_snapshot(self):
        w = run(new_world(12, 1, human_factor=False), 1, pressure=False, each=no_election)
        self.assertEqual(w.outcome["type"], "survived")
        self.assertEqual(w.history[-1]["outcome"], w.outcome)

    def test_own_currency_launch_is_smooth(self):
        def launch(world):
            no_election(world)
            if world.month == 1:
                world.econ.currency_launch = 3
        w = run(new_world(3, 36), 8, pressure=False, each=launch)
        self.assertEqual(w.econ.currency, "karam")
        jump = w.history[3]["cpi"] / w.history[2]["cpi"] - 1
        self.assertLess(abs(jump), 0.05)

    def test_rationing_spreads_hunger_more_evenly(self):
        def famine(world, rationing):
            no_election(world)
            world.dip.grain_embargo = 0.9
            world.econ.weather = 0.7
            world.policy.rationing = rationing

        def worst_gap(rationing):
            w = new_world(4, 36)
            for _ in range(8):
                engine.begin_month(w)
                famine(w, rationing)
                engine.step(w)
            hungry = [p.hunger for p in w.k_pops() if p.cls != "farmers"]
            return max(hungry) - min(hungry)

        self.assertLess(worst_gap(True), worst_gap(False))

    def test_same_seed_same_history_and_save_load(self):
        a = run(new_world(5, 36), 10, each=no_election)
        b = new_world(5, 36)
        run(b, 5, each=no_election)
        b = World.from_dict(b.to_dict())
        run(b, 5, each=no_election)
        for key in ("cpi", "approval", "unrest", "army", "gold"):
            self.assertAlmostEqual(a.history[-1][key], b.history[-1][key], places=6, msg=key)

    def test_each_month_snapshot_records_the_loaded_engine_source(self):
        from karamaniya.manifest import RUNTIME_SOURCE_FINGERPRINT
        w = run(new_world(6, 36), 4, pressure=False, each=no_election)
        self.assertTrue(RUNTIME_SOURCE_FINGERPRINT)
        self.assertEqual([h["engine_source_fingerprint"] for h in w.history],
                         [RUNTIME_SOURCE_FINGERPRINT] * 4)


if __name__ == "__main__":
    unittest.main()
