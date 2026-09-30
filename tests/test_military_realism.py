"""The army as three things it was not: a force with a reserve behind it, a body of units that do
not all think alike, and a supply chain that fails at the transport link rather than the store.

The gap it closes: `Military.army` was a single mind and a single number. A coup was decided by one
`follow` fraction, mobilization did not exist, and supply was a scalar that only ever meant "what
the Union has". The empirical record is the specification here — Turkey 2016 (8,651 personnel, 1.5%
of the force, failed for want of senior support), Venezuela 2019 (0.1-1% defections), South Korea
December 2024 (~280 troops, capital-defence units stayed out, six hours), USSR August 1991 (elite
units refused); the US reserve mobilizations of 4-8 weeks to 70-75% strength; and Operation STRANGLE
(RAND R-851), where interdiction left German fuel and ammunition stocks intact — even rising — and
took their mobility instead."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import director, engine, military  # noqa: E402
from karamaniya.economy import labor  # noqa: E402
from karamaniya.world import World, new_world  # noqa: E402

SECTORS = ("obey_commander", "obey_government", "neutral", "split")


def world(seed: int = 11, approval: float | None = None, elected: bool = False):
    w = new_world(seed, 36)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    w.const.elected = elected
    if approval is not None:
        for p in w.pops:
            p.approval = approval
    return w


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


class TheReservePool(unittest.TestCase):
    def test_it_is_bounded_by_the_active_force(self):
        for policy in ("none", "volunteer", "partial", "general"):
            w = world()
            w.policy.recruitment = policy
            pool = military.reserve_pool(w)
            self.assertGreaterEqual(pool, w.mil.army.size, policy)
            self.assertLessEqual(pool, w.mil.army.size * 4, policy)

    def test_more_recruitment_buys_a_deeper_pool(self):
        pools = []
        for policy in ("none", "volunteer", "partial", "general"):
            w = world()
            w.policy.recruitment = policy
            pools.append(military.reserve_pool(w))
        self.assertEqual(pools, sorted(pools))

    def test_it_comes_from_the_seed_and_a_resumed_run_keeps_it(self):
        same = [military.reserve_pool(world(seed=4)) for _ in range(3)]
        self.assertEqual(len(set(same)), 1)
        w = world(seed=4)
        w.policy.recruitment = "volunteer"
        first = military.reserve_pool(w)
        w.month = 9
        self.assertEqual(military.reserve_pool(w), first, "the pool is an establishment, not a draw")
        others = set()
        for seed in range(6):
            x = world(seed=seed)
            x.policy.recruitment = "volunteer"
            others.add(military.reserve_pool(x))
        self.assertGreater(len(others), 1, "the establishment should vary across runs")

    def test_a_bigger_army_carries_a_bigger_pool(self):
        w = world(seed=4)
        w.policy.recruitment = "volunteer"
        before = military.reserve_pool(w)
        w.mil.army.size = w.mil.army.size * 2
        self.assertAlmostEqual(military.reserve_pool(w), before * 2, delta=2)


class MobilizingTakesTime(unittest.TestCase):
    def test_reservists_arrive_over_months_and_never_all_at_once(self):
        w = world()
        w.policy.recruitment = "volunteer"
        military.call_up(w, 10000)
        self.assertGreater(military.mobilized_strength(w), 0)
        self.assertLess(military.mobilized_strength(w), 10000 * .3, "nobody is a soldier on day one")
        arrived = []
        for month in range(1, 5):
            w.month = month
            arrived.append(military.mobilized_strength(w))
        self.assertEqual(arrived, sorted(arrived))
        self.assertLess(arrived[0], 10000 * .85, "six weeks in, a called-up cohort is short")
        self.assertGreater(arrived[2], 10000 * .9, "by three months the cohort is nearly there")
        self.assertLessEqual(arrived[-1], 10000, "never more than were called up")

    def test_a_called_up_cohort_is_only_partly_effective_while_it_trains(self):
        self.assertLess(military.mobilized_fraction(0), .3)
        self.assertLess(military.mobilized_fraction(.5), .6)
        self.assertGreater(military.mobilized_fraction(1.4), .7)     # six weeks: US reserve figure
        self.assertGreater(military.mobilized_fraction(3), .93)
        for months in (0, .25, 1, 2, 3, 6):
            self.assertLessEqual(military.mobilized_fraction(months), 1.0)

    def test_a_call_up_cannot_exceed_the_trained_pool(self):
        w = world()
        w.policy.recruitment = "volunteer"
        pool = military.reserve_pool(w)
        military.call_up(w, pool * 10)
        self.assertLessEqual(military.mobilization_of(w).called_up, pool)

    def test_sending_them_home_stops_the_clock(self):
        w = world()
        w.policy.recruitment = "volunteer"
        military.call_up(w, 6000)
        w.month = 2
        self.assertAlmostEqual(military.mobilization_months(w), 2.0, delta=.01)
        military.release_reservists(w, 6000)
        self.assertEqual(military.mobilization_of(w).called_up, 0.0)
        self.assertEqual(military.mobilized_strength(w), 0.0)
        w.month = 5
        self.assertEqual(military.mobilization_draw(w), 0.0)

    def test_mobilizing_costs_money_and_draws_labour(self):
        w = world()
        w.policy.recruitment = "volunteer"
        standing = military.reserve_cost(w)
        self.assertGreater(standing["pool_monthly"], 0, "the trained pool is not free to keep")
        self.assertEqual(standing["embodied_monthly"], 0)
        self.assertGreater(standing["monthly_total"], 0)
        military.call_up(w, 8000)
        embodied = military.reserve_cost(w)
        self.assertGreater(embodied["monthly_total"], standing["monthly_total"])
        self.assertGreater(embodied["activation_one_off"], 0, "kit and transport cost at the call-up")
        self.assertAlmostEqual(embodied["embodied_monthly"], 8000 * military.ARMY_COST * w.econ.cpi, delta=1)
        w.month = 3
        self.assertAlmostEqual(military.mobilization_person_months(w), 8000 * 3, delta=1)
        self.assertAlmostEqual(military.mobilization_draw(w), 8000, delta=1)

    def test_the_person_months_are_what_the_labour_books_need(self):
        """The call site the economy needs: mark the draw out of the labour force.

        `economy.labor()` already subtracts `p.conscripted`, and `_recruit()`/`_release()` here
        already write to it, so a call-up is booked the same way conscription is. This is that call
        site, written out, rather than an edit to economy.py.
        """
        w = world()
        w.policy.recruitment = "volunteer"
        before = sum(labor(p) for p in w.k_pops())
        military.call_up(w, 8000)
        pops = [p for p in w.k_pops() if p.cls in military.DRAFT_WEIGHT]
        weights = [military.DRAFT_WEIGHT[p.cls] * labor(p) for p in pops]
        total = sum(weights)
        for p, weight in zip(pops, weights):
            p.conscripted += military.mobilization_draw(w) * weight / total
        after = sum(labor(p) for p in w.k_pops())
        self.assertAlmostEqual(before - after, military.mobilization_draw(w), delta=1)
        w.month = 1
        self.assertAlmostEqual(military.mobilization_person_months(w),
                               military.mobilization_draw(w), delta=1)


class UnitsAreNotOfOneMind(unittest.TestCase):
    def test_the_answer_is_a_distribution_over_unit_responses(self):
        d = military.unit_response(world())
        self.assertEqual(set(d), set(SECTORS))
        self.assertAlmostEqual(sum(d.values()), 1.0, places=9)
        for share in d.values():
            self.assertGreaterEqual(share, 0.0)
            self.assertLessEqual(share, 1.0)

    def test_it_takes_the_order_the_coup_code_would_hand_it(self):
        d = military.unit_response(world(), {"kind": "coup", "office": "army", "leader": "D"},
                                   believed_join=.4)
        self.assertAlmostEqual(sum(d.values()), 1.0, places=9)
        d = military.unit_response(world(), {"kind": "coup", "office": "navy", "leader": "E"})
        self.assertAlmostEqual(sum(d.values()), 1.0, places=9)

    def test_a_loyal_paid_army_barely_moves(self):
        w = world(approval=.7, elected=True)
        w.mil.army.bond, w.mil.army.loyalty, w.mil.army.arrears = .05, .9, 0.0
        w.mil.police.loyalty = w.mil.navy.loyalty = .9
        d = military.unit_response(w)
        self.assertLess(d["obey_commander"], .05)
        self.assertGreater(d["obey_government"], d["obey_commander"] * 10)
        self.assertLess(military.anticipated_response(w)["obey_commander"], d["obey_commander"])

    def test_the_whole_army_never_follows_one_officer(self):
        w = world(approval=.05)
        w.mil.army.bond, w.mil.army.loyalty, w.mil.army.arrears = .99, .05, 3.0
        w.mil.police.loyalty = w.mil.navy.loyalty = .05
        d = military.unit_response(w, believed_join=1.0)
        self.assertLessEqual(d["obey_commander"], military.ENGAGE_CEILING)
        self.assertGreater(d["neutral"] + d["obey_government"] + d["split"], .1)

    def test_a_coup_that_looks_like_it_will_fail_collapses_further(self):
        w = world(approval=.65, elected=True)
        w.mil.army.bond, w.mil.army.loyalty, w.mil.army.arrears = .1, .85, 0.0
        w.mil.police.loyalty = w.mil.navy.loyalty = .85
        optimistic = military.unit_response(w, believed_join=.6)["obey_commander"]
        collapsed = military.anticipated_response(w)["obey_commander"]
        self.assertLess(collapsed, optimistic)
        nobody = military.unit_response(w, believed_join=0.0)["obey_commander"]
        everybody = military.unit_response(w, believed_join=.8)["obey_commander"]
        self.assertLess(nobody, everybody, "Singh: a unit joins when it expects others to join")

    def test_the_things_the_record_turns_on_move_the_answer(self):
        def response(**over):
            w = world(approval=over.pop("approval", .5), elected=over.pop("elected", False))
            for field, value in over.items():
                if field in ("police_loyalty", "navy_loyalty"):
                    getattr(w.mil, "police" if field.startswith("police") else "navy").loyalty = value
                else:
                    setattr(w.mil.army, field, value)
            return military.unit_response(w, believed_join=.4)

        unpaid = response(bond=.3, loyalty=.5, arrears=2.0)
        paid = response(bond=.3, loyalty=.5, arrears=0.0)
        self.assertGreater(unpaid["obey_commander"], paid["obey_commander"])
        bonded = response(bond=.7, loyalty=.6)
        unbonded = response(bond=.05, loyalty=.6)
        self.assertGreater(bonded["obey_commander"], unbonded["obey_commander"])
        popular = response(approval=.8, elected=True, bond=.3, loyalty=.5)
        unpopular = response(approval=.1, bond=.3, loyalty=.5)
        self.assertGreater(unpopular["obey_commander"], popular["obey_commander"])
        watched = response(bond=.6, loyalty=.4, police_loyalty=.95, navy_loyalty=.95)
        alone = response(bond=.6, loyalty=.4, police_loyalty=.05, navy_loyalty=.05)
        self.assertGreater(alone["obey_commander"], watched["obey_commander"])

    def test_legitimacy_is_what_the_army_and_the_engine_already_read(self):
        w = world(approval=.5, elected=True)
        self.assertAlmostEqual(military.government_legitimacy(w), .5 * .5 + .15, delta=.01)
        self.assertGreater(military.government_legitimacy(world(approval=.8, elected=True)),
                           military.government_legitimacy(world(approval=.2)))
        after = world(approval=.5)
        after.const.coup_month = after.month
        self.assertLess(military.government_legitimacy(after),
                        military.government_legitimacy(world(approval=.5)))


class TheSupplyChainIsNotAStockpile(unittest.TestCase):
    def test_transport_denial_costs_far_more_than_empty_stores(self):
        transport_loss = 1 - military.readiness_factor(1.0, .6)
        stock_loss = 1 - military.readiness_factor(.6, 1.0)
        self.assertGreater(transport_loss, stock_loss * 2)
        self.assertAlmostEqual(military.readiness_factor(1.0, 1.0), 1.0)

    def test_sustained_interdiction_takes_mobility_and_leaves_the_stores(self):
        w = world()
        w.dip.war, w.dip.union_intensity = True, 1.0
        for month in range(0, 8):
            w.month = month
            military.update_readiness(w)
        r = military.readiness_of(w)
        self.assertLess(r.transport, .7)
        self.assertGreater(r.stock, .9, "STRANGLE: interdiction did not empty the stores")
        self.assertGreater(r.interdiction, .5)

    def test_the_chain_reaches_quality_through_its_own_function(self):
        w = world()
        nominal = military.quality(w.mil.army.equipment, w.mil.army.training, w.mil.army.morale)
        self.assertAlmostEqual(military.effective_quality(w), nominal, delta=1e-9)
        r = military.readiness_of(w)
        r.transport, r.stock = .4, 1.0
        self.assertLess(military.effective_quality(w), nominal)

    def test_readiness_recovers_and_stores_build_in_peacetime(self):
        w = world()
        r = military.readiness_of(w)
        r.transport, r.stock = .3, .3
        for month in range(0, 14):
            w.month = month
            military.update_readiness(w)
        self.assertGreater(r.transport, .95)
        self.assertGreater(r.stock, .9)
        self.assertEqual(r.interdiction, 0.0)

    def test_it_steps_once_a_month(self):
        w = world()
        w.dip.war, w.dip.union_intensity = True, 1.0
        w.month = 1
        first = military.update_readiness(w).transport
        self.assertEqual(military.update_readiness(w).transport, first)

    def test_the_army_carries_its_own_supply_state(self):
        w = world()
        r = military.readiness_of(w)
        self.assertIs(military.readiness_of(w), r, "one state, read rather than recomputed")
        nominal = military.quality(w.mil.army.equipment, w.mil.army.training, w.mil.army.morale)
        r.stock = .4
        self.assertLess(military.effective_quality(w), nominal)
        self.assertNotIn("readiness", w.to_dict()["mil"],
                         "the state is engine-internal and does not travel in checkpoints yet")


class ItSurvivesACheckpoint(unittest.TestCase):
    def test_a_military_saved_before_this_feature_still_loads(self):
        w = world()
        data = w.to_dict()
        for key in ("mobilization", "readiness"):
            data["mil"].pop(key, None)
        loaded = World.from_dict(data)
        self.assertIsInstance(military.mobilization_of(loaded), military.Mobilization)
        self.assertIsInstance(military.readiness_of(loaded), military.Readiness)
        self.assertEqual(military.mobilization_of(loaded).called_up, 0.0)
        self.assertEqual(military.unit_response(loaded), military.unit_response(w))

    def test_a_round_trip_after_this_feature_still_loads(self):
        """Known limitation: an in-progress call-up is not serialised, because the state rides on
        the force rather than in a field of `Military` (world.py, not owned by this change). The
        run loads; the chain restarts from its standing start."""
        w = world()
        w.policy.recruitment = "volunteer"
        military.call_up(w, 5000)
        loaded = World.from_dict(w.to_dict())
        self.assertEqual(loaded.mil.army.size, w.mil.army.size)
        self.assertEqual(military.reserve_pool(loaded), military.reserve_pool(w))
        self.assertEqual(military.mobilization_of(loaded).called_up, 0.0)


class Determinism(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = [run(world(seed=7), 8) for _ in range(2)]

    def test_two_runs_of_one_seed_agree(self):
        a, b = self.runs
        ra, rb = military.readiness_of(a), military.readiness_of(b)
        self.assertEqual((ra.stock, ra.transport, ra.interdiction),
                         (rb.stock, rb.transport, rb.interdiction))
        self.assertEqual(a.mil.army.size, b.mil.army.size)
        self.assertEqual(a.mil.last_combat, b.mil.last_combat)
        self.assertEqual(military.reserve_pool(a), military.reserve_pool(b))

    def test_the_functions_are_pure_given_the_state(self):
        a, b = world(seed=5), world(seed=5)
        self.assertEqual(military.unit_response(a), military.unit_response(b))
        self.assertEqual(military.anticipated_response(a), military.anticipated_response(b))
        self.assertEqual(military.readiness_factor(.5, .5), military.readiness_factor(.5, .5))

    def test_nothing_leaks_into_the_events_agents_read(self):
        w = world(seed=3)
        w.policy.recruitment = "volunteer"
        pool = military.reserve_pool(w)
        military.call_up(w, 5000)
        military.unit_response(w)
        military.anticipated_response(w)
        run(w, 3)
        text = " ".join(str(e.get("text", "")) for e in w.events).lower()
        self.assertNotIn(f"{pool:,.0f}", text)
        self.assertNotIn("reserve pool", text)
        for sector in SECTORS:
            self.assertNotIn(sector, text)


if __name__ == "__main__":
    unittest.main()


class StateSurvivesSaveAndLoad(unittest.TestCase):
    """The subagent that built this kept its state on the instance rather than on the dataclass,
    so an in-progress call-up was silently lost on save and a resumed run restarted it. The state
    now lives in `Military.mobilization_state` / `readiness_state` and syncs once a month."""

    def test_an_in_progress_call_up_survives_a_round_trip(self):
        from karamaniya.world import World
        w = new_world(1, 24)
        military.call_up(w, 20000)
        w.month = 0
        military.update_readiness(w)
        military.sync_state(w)
        before = military.mobilization_of(w).called_up
        again = military.mobilization_of(World.from_dict(w.to_dict()))
        self.assertAlmostEqual(again.called_up, before, delta=1.0)

    def test_the_supply_chain_survives_a_round_trip(self):
        from karamaniya.world import World
        w = new_world(1, 24)
        w.dip.blockade = True
        w.dip.blockade_eff = 0.9
        for m in range(6):
            w.month = m
            military.update_readiness(w)
        military.sync_state(w)
        before = military.readiness_of(w).transport
        again = military.readiness_of(World.from_dict(w.to_dict()))
        self.assertAlmostEqual(again.transport, before, places=6)
        self.assertLess(before, 1.0, "the run never actually degraded anything")

    def test_a_checkpoint_from_before_this_state_existed_still_loads(self):
        from karamaniya.world import World
        w = new_world(1, 12)
        data = w.to_dict()
        data["mil"].pop("mobilization_state", None)
        data["mil"].pop("readiness_state", None)
        old = World.from_dict(data)
        self.assertAlmostEqual(military.mobilization_of(old).called_up, 0.0)
        self.assertAlmostEqual(military.readiness_of(old).stock, 1.0)

    def test_mobilized_strength_arrives_gradually_not_at_once(self):
        w = new_world(1, 24)
        military.call_up(w, 20000)
        self.assertLess(military.mobilized_strength(w), 20000,
                        "the whole call-up was effective immediately")


class TheCoupIsNotOneMind(unittest.TestCase):
    """`politics.resolve_coups` used a single `follow` scalar with a floor of 5% and a ceiling of
    95%, so a plotter always carried a large block. It now reads the unit-response distribution."""

    def _fragment(self, loyalty, bond, arrears=0.0):
        from karamaniya.world import new_world as nw
        w = nw(1, 12)
        w.mil.army.loyalty = loyalty
        w.mil.army.bond = bond
        w.mil.army.arrears = arrears
        return military.anticipated_response(w, {"kind": "coup", "office": "army", "leader": "A"})

    def test_an_unpopular_plotter_carries_only_a_few_percent(self):
        """Turkey 2016: 8,651 personnel participated, 1.5% of the armed forces."""
        share = self._fragment(loyalty=0.85, bond=0.15)["obey_commander"]
        self.assertLess(share, 0.10)

    def test_a_garrison_can_stay_neutral_rather_than_picking_a_side(self):
        d = self._fragment(loyalty=0.5, bond=0.5)
        self.assertGreater(d["neutral"], 0.10, "every unit picked a side")

    def test_the_whole_army_never_follows_one_officer(self):
        d = self._fragment(loyalty=0.0, bond=1.0, arrears=6.0)
        self.assertLessEqual(d["obey_commander"], military.ENGAGE_CEILING)
        self.assertGreater(d["obey_government"] + d["neutral"] + d["split"], 0.0)

    def test_the_resolve_coup_path_uses_the_distribution(self):
        """The wiring itself, not just the function: the scalar is gone from the coup path."""
        import inspect
        from karamaniya import politics
        source = inspect.getsource(politics.resolve_coups)
        self.assertIn("anticipated_response", source)
        self.assertNotIn("0.25 + 0.55 * force.bond", source,
                         "the old scalar follow formula is still in the coup path")


class TheMobilizationLever(unittest.TestCase):
    """Mobilization was built, tested and made persistent before anything could call it. The
    council's Army office now has a lever for it, which is what makes the system reachable."""

    def _mobilized(self, mode, months=12, recruitment="volunteer"):
        from karamaniya import director, engine
        w = new_world(1, 18)

        def each(x):
            x.const.elected = True
            x.const.election_month = 99
            x.policy.recruitment = recruitment
            x.policy.mobilization = mode
        original = director.act
        director.act = lambda world, *_a, **_k: setattr(world.dip, "inbox", [])
        try:
            for _ in range(months):
                engine.begin_month(w)
                each(w)
                engine.step(w)
        finally:
            director.act = original
        return w

    def test_the_lever_is_registered_with_the_army_office(self):
        from karamaniya import politics
        self.assertEqual(politics.LEVER_OFFICE["mobilization"], "army")
        for mode in politics.ENUMS["mobilization"]:
            with self.subTest(mode=mode):
                self.assertIn(mode, military.MOBILIZATION_SHARE)

    def test_the_settings_call_up_different_numbers(self):
        none = military.mobilization_of(self._mobilized("none")).called_up
        partial = military.mobilization_of(self._mobilized("partial")).called_up
        general = military.mobilization_of(self._mobilized("general")).called_up
        self.assertEqual(none, 0.0)
        self.assertGreater(partial, 0.0)
        self.assertGreater(general, partial)

    def test_mobilizing_takes_people_out_of_the_labour_force(self):
        from karamaniya import economy
        quiet = self._mobilized("none")
        called = self._mobilized("general")
        labour_quiet = sum(economy.labor(p) for p in quiet.k_pops())
        labour_called = sum(economy.labor(p) for p in called.k_pops())
        self.assertLess(labour_called, labour_quiet,
                        "calling up reservists cost the economy no labour at all")

    def test_the_labour_drawn_matches_the_number_embodied(self):
        from karamaniya import economy
        w = self._mobilized("general")
        embodied = military.mobilization_of(w).called_up
        self.assertGreater(embodied, 0.0)
        # Every embodied reservist is one person out of the labour force, plus the standing
        # conscription the run already had.
        drawn = military.mobilization_draw(w)
        self.assertAlmostEqual(drawn, embodied, delta=max(2.0, embodied * 0.05))

    def test_mobilizing_costs_money(self):
        quiet = military.reserve_cost(self._mobilized("none"))["monthly_total"]
        called = military.reserve_cost(self._mobilized("general"))["monthly_total"]
        self.assertGreater(called, quiet)

    def test_standing_down_releases_the_reservists(self):
        from karamaniya import director, engine
        w = self._mobilized("general")
        self.assertGreater(military.mobilization_of(w).called_up, 0.0)

        def stand_down(x):
            x.const.elected = True
            x.const.election_month = 99
            x.policy.mobilization = "none"
        original = director.act
        director.act = lambda world, *_a, **_k: setattr(world.dip, "inbox", [])
        try:
            for _ in range(6):
                engine.begin_month(w)
                stand_down(w)
                engine.step(w)
        finally:
            director.act = original
        self.assertLess(military.mobilization_of(w).called_up, 1.0,
                        "reservists were not released when the order was cancelled")

    def test_effectiveness_arrives_gradually_not_at_once(self):
        """US reserve units needed 4-8 weeks to reach 70-75pc; Ukraine about six weeks."""
        from karamaniya import director, engine
        w = new_world(1, 18)
        w.policy.recruitment = "volunteer"
        w.policy.mobilization = "general"
        w.const.elected = True
        w.const.election_month = 99
        original = director.act
        director.act = lambda world, *_a, **_k: setattr(world.dip, "inbox", [])
        try:
            engine.begin_month(w)
            engine.step(w)
        finally:
            director.act = original
        mob = military.mobilization_of(w)
        self.assertGreater(mob.called_up, 0.0, "nothing was called up")
        share = military.mobilized_strength(w) / mob.called_up
        self.assertLess(share, 0.85, "the whole call-up was effective in its first month")
        self.assertGreater(share, 0.3, "almost nobody had arrived after a month")

    def test_the_prompt_tells_the_army_office_the_lever_exists(self):
        import inspect
        from karamaniya import prompts
        self.assertIn("mobilization", inspect.getsource(prompts))
