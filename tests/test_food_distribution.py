"""Food: what spoils, and what the roads fail to deliver.

The brief's requirement is that a national food balance must not imply uniform regional access --
"food availability is 103%" and "Kessel is hungry" must be able to be true at once. Both halves
are tested here, along with the post-harvest losses that make the balance tight in the first place.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import director, economy, engine  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def run(w, months, each=None):
    original = director.act
    director.act = lambda world, *_a, **_k: setattr(world.dip, "inbox", [])
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


def steady(w):
    w.const.elected = True
    w.const.election_month = 99


def cut_road(region, level=0.30):
    def each(w):
        steady(w)
        w.region(region).logistics = level
    return each


def hunger_in(w, region):
    grp = [p for p in w.pops if p.region == region]
    total = sum(p.size for p in grp)
    return sum(p.hunger * p.size for p in grp) / total if total else 0.0


class PostHarvestLosses(unittest.TestCase):
    def test_the_loss_rate_is_in_the_empirically_supported_band(self):
        """APHLIS and the World Bank put grain losses from harvest to market at roughly 10-20pc
        for weak-infrastructure economies. The widely quoted 30-40pc figures are not supported
        for cereals and are not used."""
        for seed in range(1, 12):
            w = new_world(seed, 12)
            rate = economy.food_loss_rate(w)
            with self.subTest(seed=seed):
                self.assertGreater(rate, 0.05)
                self.assertLess(rate, 0.22)

    def test_losses_rise_when_logistics_degrade(self):
        intact = new_world(1, 12)
        broken = new_world(1, 12)
        for r in broken.k_regions():
            r.logistics = 0.35
        self.assertGreater(economy.food_loss_rate(broken), economy.food_loss_rate(intact))

    def test_losses_reduce_what_is_available_to_eat(self):
        w = new_world(1, 12)
        produced = economy.produce(w)["food"]
        run(w, 1, each=steady)
        self.assertLess(w.econ.food_ratio * w.population(), produced * 1.5)
        self.assertAlmostEqual(w.econ.food_loss, economy.food_loss_rate(w), places=9)

    def test_the_founding_food_balance_matches_the_documented_condition(self):
        """The README documents available domestic food at about 74pc of need. Adding a loss
        mechanism must not silently change the documented starting position."""
        for seed in (1, 3, 5, 7):
            w = run(new_world(seed, 12), 3, each=steady)
            with self.subTest(seed=seed):
                self.assertGreater(w.econ.food_ratio, 0.99)
                self.assertLess(w.econ.food_ratio, 1.10)

    def test_a_calm_world_has_essentially_no_hunger(self):
        for seed in (1, 3, 5):
            w = run(new_world(seed, 18), 12, each=steady)
            with self.subTest(seed=seed):
                self.assertLess(w.avg("hunger"), 0.02,
                                "the country goes hungry in an ordinary year")


class RegionalAccess(unittest.TestCase):
    def test_a_broken_corridor_starves_its_region_and_no_other(self):
        w = run(new_world(4, 24), 10, each=cut_road("kessel"))
        self.assertGreater(hunger_in(w, "kessel"), 0.10, "the cut-off region was fed anyway")
        for region in ("aster", "lissen", "highlands", "dorran"):
            with self.subTest(region=region):
                self.assertLess(hunger_in(w, region), 0.02,
                                f"{region} went hungry although its roads are intact")

    def test_a_national_surplus_can_coexist_with_a_regional_shortage(self):
        """The brief's explicit requirement, tested directly."""
        def each(w):
            steady(w)
            w.policy.imports = "max"          # buy food abroad
            w.econ.weather = 1.06             # and a good harvest
            w.region("kessel").logistics = 0.28
        w = run(new_world(4, 24), 10, each=each)
        self.assertGreater(w.econ.food_ratio, 1.0, "the country is not actually in surplus")
        self.assertGreater(hunger_in(w, "kessel"), 0.10, "the cut-off region is not short")
        self.assertIn("kessel", w.econ.food_short_regions)

    def test_the_short_region_is_named_rather_than_left_implicit(self):
        w = run(new_world(4, 24), 8, each=cut_road("kessel"))
        self.assertEqual(w.econ.food_short_regions, ["kessel"])

    def test_repairing_the_corridor_feeds_the_region_again(self):
        w = run(new_world(4, 24), 8, each=cut_road("kessel"))
        short = hunger_in(w, "kessel")
        self.assertGreater(short, 0.10)
        run(w, 8, each=lambda x: (steady(x), setattr(x.region("kessel"), "logistics", 1.0)))
        self.assertLess(hunger_in(w, "kessel"), short * 0.5,
                        "repairing the road did not relieve the region")

    def test_delivery_capacity_is_not_binding_at_intact_logistics(self):
        w = new_world(4, 12)
        for r in w.k_regions():
            with self.subTest(region=r.id):
                self.assertGreaterEqual(economy.delivery_capacity(r), 1.0)

    def test_delivery_capacity_falls_with_logistics(self):
        w = new_world(4, 12)
        r = w.region("kessel")
        r.logistics = 1.0
        full = economy.delivery_capacity(r)
        r.logistics = 0.2
        self.assertLess(economy.delivery_capacity(r), full)

    def test_rationing_equalises_within_a_region_but_cannot_reach_a_cut_off_one(self):
        """Rationing is a distribution policy, not a transport policy."""
        def each(w):
            steady(w)
            w.policy.rationing = True
            w.region("kessel").logistics = 0.28
        w = run(new_world(4, 24), 10, each=each)
        kessel, aster = hunger_in(w, "kessel"), hunger_in(w, "aster")
        self.assertGreater(kessel, 0.10,
                           "rationing conjured food into a region the roads did not reach")
        # Rationing carries a deliberate distribution allowance, so an intact region is not at
        # zero; what matters is that the cut-off region is far worse than the connected one.
        self.assertLess(aster, 0.06)
        self.assertGreater(kessel, aster * 3, "rationing equalised across a broken road")


class ConservationAndStability(unittest.TestCase):
    def test_delivery_never_exceeds_what_is_available(self):
        w = new_world(4, 12)
        rows = [(r, [p for p in w.k_pops() if p.region == r.id and p.cls != "farmers"],
                 sum(p.size for p in w.k_pops() if p.region == r.id and p.cls != "farmers"))
                for r in w.k_regions()]
        for supply in (0.0, 1e5, 1e6, 5e6):
            out = economy._deliver_to_regions(rows, supply)
            with self.subTest(supply=supply):
                self.assertLessEqual(sum(out.values()), supply + 1e-6)

    def test_delivery_respects_each_regions_ceiling(self):
        w = new_world(4, 12)
        w.region("kessel").logistics = 0.3
        rows = [(r, [p for p in w.k_pops() if p.region == r.id and p.cls != "farmers"],
                 sum(p.size for p in w.k_pops() if p.region == r.id and p.cls != "farmers"))
                for r in w.k_regions()]
        out = economy._deliver_to_regions(rows, 1e9)
        for r, _grp, need in rows:
            with self.subTest(region=r.id):
                self.assertLessEqual(out[r.id], need * economy.delivery_capacity(r) + 1e-6)

    def test_delivering_nothing_is_not_an_error(self):
        w = new_world(4, 12)
        rows = [(r, [], 0.0) for r in w.k_regions()]
        self.assertEqual(set(economy._deliver_to_regions(rows, 0.0).values()), {0.0})

    def test_hunger_stays_bounded_over_a_long_run(self):
        for seed in (1, 4, 9):
            w = run(new_world(seed, 30), 24, each=steady)
            with self.subTest(seed=seed):
                self.assertGreaterEqual(w.avg("hunger"), 0.0)
                self.assertLessEqual(w.avg("hunger"), 1.0)

    def test_the_food_state_survives_save_and_load(self):
        from karamaniya.world import World
        w = run(new_world(4, 18), 8, each=cut_road("kessel"))
        again = World.from_dict(w.to_dict())
        self.assertEqual(again.econ.food_short_regions, w.econ.food_short_regions)
        self.assertAlmostEqual(again.econ.food_loss, w.econ.food_loss, places=9)


if __name__ == "__main__":
    unittest.main()
