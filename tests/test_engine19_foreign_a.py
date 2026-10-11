"""Engine 19, slice A: the neighbours' forces, their economies and how firm Karamaniya looks.

Each test pins one finding of the engine-18 audit (docs/AUDIT_ENGINE18.md) against the behaviour its proof script
(audit/poc_*.py) reproduced. Each test fails on engine 18 and passes once the finding is fixed. The files are
foreign_force.py, rivals.py and resolve.py. Nothing here calls a model.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import foreign, foreign_force, military, politics, resolve, rivals, territory  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def world(seed: int = 5, month: int = 0):
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    w.month = month
    return w


def act(w, actor, **action):
    """check() and then apply(), as an act is taken when a cabinet's decision is applied."""
    action.setdefault("magnitude", .5)
    error = foreign_force.check(w, actor, action)
    if error is None:
        foreign_force.apply(w, actor, action)
    return error


class CallUpsPerMonth(unittest.TestCase):
    """FO1: a neighbour's call-ups in one month stay within its monthly cap, however many acts it takes them in."""

    def test_four_call_ups_in_one_decision_cannot_pass_the_monthly_cap(self):
        w = world(month=3)
        army0 = w.rivals["veleria"].army
        call_up = {"type": "mobilize", "troops": 12000, "magnitude": .5}
        foreign._apply_cabinet_decisions(w, foreign.positions(w),
                                         {"veleria": {"actions": [dict(call_up) for _ in range(4)]}})
        self.assertEqual(w.rivals["veleria"].army - army0, foreign_force.MOBILIZE_CAP["veleria"])
        refused = [m["text"] for m in w.foreign["actors"]["veleria"]["memory"] if m.get("kind") == "rejected_action"]
        self.assertEqual(len(refused), 3)
        self.assertIn("at most 0 reservists", refused[0])

    def test_what_remains_of_the_cap_is_what_the_next_act_may_call(self):
        w = world(month=3)
        self.assertIsNone(act(w, "veleria", type="mobilize", troops=5000))
        error = act(w, "veleria", type="mobilize", troops=8000)
        self.assertIsNotNone(error, "a second act of 8,000 in the same month should exceed the cap")
        self.assertIn("at most 7,000 reservists", error)
        self.assertIsNone(act(w, "dorsania", type="mobilize", troops=6000))     # the other neighbour has its own cap

    def test_the_cap_renews_in_the_next_month(self):
        w = world(month=3)
        self.assertIsNone(act(w, "veleria", type="mobilize", troops=12000))
        w.month = 4
        self.assertIsNone(act(w, "veleria", type="mobilize", troops=12000))


class CallUpsDrawTheReserves(unittest.TestCase):
    """FO2: a call-up is taken out of the reserve pool, so the pool and the reservists a cabinet can still call fall."""

    def test_a_call_up_takes_its_soldiers_out_of_the_pool_one_for_one(self):
        w = world(month=3)
        mil = w.foreign["actors"]["veleria"]["military"]
        reserves0, room0 = mil["reserves"], foreign_force.reserve_room(w, "veleria")
        self.assertIsNone(act(w, "veleria", type="mobilize", troops=12000))
        self.assertEqual(mil["reserves"], reserves0 - 12000)
        # The room is reserves less .45 of the active army, and the active army rose by the same 12,000: the pool gives
        # up 12,000, and the ratio asks it to keep .45 x 12,000 more.
        self.assertAlmostEqual(room0 - foreign_force.reserve_room(w, "veleria"), 12000 * 1.45, places=6)

    def test_the_pool_is_never_overdrawn(self):
        w = world(month=3)
        mil = w.foreign["actors"]["veleria"]["military"]
        reserves0 = mil["reserves"]
        called = 0
        for month in range(3, 80):
            w.month = month
            troops = int(min(foreign_force.MOBILIZE_CAP["veleria"], foreign_force.reserve_room(w, "veleria")))
            if troops < 1:
                break
            self.assertIsNone(act(w, "veleria", type="mobilize", troops=troops))
            called += troops
        self.assertGreater(called, 0)
        self.assertLessEqual(called, reserves0)
        self.assertGreaterEqual(mil["reserves"], 0)
        self.assertAlmostEqual(mil["reserves"], reserves0 - called, places=6)

    def test_a_call_up_is_seen_as_reservists_called_up(self):
        w = world(month=2)
        rivals.monthly(w)                              # the watch's first record, for the month before
        w.month = 3
        self.assertIsNone(act(w, "veleria", type="mobilize", troops=12000))
        rivals.monthly(w)
        marks = [e["signal"] for e in w.foreign["escalation_chains"] if e.get("observed") and e["month"] == 3]
        self.assertIn("called up reserve units", marks)


def lost_regions(month: int = 6):
    """Kessel Valley held by the Union, Port Aster held by rebels with unrest, as a front and a rising leave them."""
    w = world(month=month)
    military.occupy(w, "kessel", "union")
    aster = w.region("aster")
    aster.controller, aster.unrest = "rebels", .9
    return w


class CabinetsSeeLostRegions(unittest.TestCase):
    """FO3: a cabinet is told of a region the Union holds or the rebels hold, and covert support can reach one they hold."""

    def test_a_cabinet_is_told_which_regions_the_union_occupies(self):
        view = foreign_force.cabinet_view(lost_regions(), "veleria")
        self.assertEqual(view["confrontation"]["occupied_regions"], ["Kessel Valley"])

    def test_a_cabinet_is_told_of_the_unrest_in_a_region_the_union_or_rebels_hold(self):
        unrest = foreign_force.cabinet_view(lost_regions(), "veleria")["karamaniya_as_you_see_it"]["unrest"]
        self.assertIsInstance(unrest, dict, f"the cabinet is told {unrest!r}")
        self.assertEqual(unrest["Kessel Valley"], "occupied by the Union")
        self.assertEqual(unrest["Port Aster"], "held by rebels")

    def test_covert_support_is_refused_where_the_union_holds_and_allowed_where_rebels_hold(self):
        w = lost_regions()
        self.assertIn("already held by the Union", foreign_force.check(
            w, "veleria", {"type": "covert_support", "region": "kessel", "magnitude": .6}))
        self.assertIsNone(foreign_force.check(w, "veleria", {"type": "covert_support", "region": "aster",
                                                             "magnitude": .6}))


def union_war(w, north: float = 8000, east: float = 3000):
    """A war the Union fights on both fronts, with the combat record military.update writes: keyed by front."""
    w.dip.war, w.dip.aggressor, w.dip.ceasefire = True, "union", False
    w.dip.war_aim = {"by": "veleria", "aim": "full", "participants": ["veleria", "dorsania"], "month": w.month - 1}
    w.mil.last_combat = {
        "north": {"region": "kessel", "ratio": 1.4, "k_loss": 2000, "u_loss": north, "k_soldiers": 40000,
                  "k_active_soldiers": 30000, "k_reserve_soldiers": 10000, "u_soldiers": 30000, "progress": .1,
                  "month": w.month - 1},
        "east": {"region": "dorran", "ratio": 1.1, "k_loss": 900, "u_loss": east, "k_soldiers": 20000,
                 "k_active_soldiers": 15000, "k_reserve_soldiers": 5000, "u_soldiers": 12000, "progress": 0.0,
                 "month": w.month - 1},
        "k_loss_rate": .02}


class TheUnionsLossesAreReplaced(unittest.TestCase):
    """FO4: the Union's losses are replaced from a neighbour's reserves, one soldier for each reserve drawn, in the
    share of each front that neighbour's army holds."""

    def test_each_neighbour_replaces_its_losses_one_soldier_for_each_reserve_drawn(self):
        w = world(month=10)
        union_war(w)
        army0 = {a: w.rivals[a].army for a in ("veleria", "dorsania")}
        pool0 = {a: w.foreign["actors"][a]["military"]["reserves"] for a in army0}
        rivals.monthly(w)
        for actor in army0:
            with self.subTest(actor=actor):
                drawn = pool0[actor] - w.foreign["actors"][actor]["military"]["reserves"]
                gained = w.rivals[actor].army - army0[actor]
                self.assertGreater(drawn, 0)
                self.assertAlmostEqual(gained, drawn, delta=.1)

    def test_the_losses_on_each_front_are_shared_by_the_neighbours_that_hold_it(self):
        w = world(month=10)
        union_war(w, north=8000, east=3000)
        # The north is Veleria's alone; the east is shared by army (65,000 against 30,000).
        loss = {"veleria": 8000 + 3000 * 65000 / 95000, "dorsania": 3000 * 30000 / 95000}
        readiness = {"veleria": .58, "dorsania": .47}
        army0 = {a: w.rivals[a].army for a in loss}
        rivals.monthly(w)
        for actor in loss:
            with self.subTest(actor=actor):
                expected = loss[actor] * rivals.REPLACEMENT_RATE * (.5 + .5 * readiness[actor])
                self.assertAlmostEqual(w.rivals[actor].army - army0[actor], expected, delta=.5)

    def test_a_front_only_one_neighbour_holds_is_its_alone(self):
        w = world(month=10)
        union_war(w, north=8000, east=0)
        army0 = {a: w.rivals[a].army for a in ("veleria", "dorsania")}
        rivals.monthly(w)
        self.assertGreater(w.rivals["veleria"].army, army0["veleria"])
        self.assertEqual(w.rivals["dorsania"].army, army0["dorsania"])


class DefenceBurdenFollowsTheEconomy(unittest.TestCase):
    """FO10: a neighbour's defence burden is its army's money cost over its current output, so a smaller economy feels
    a heavier burden; a founding army sits near seventy per cent of the cap and readiness holds in peace."""

    def test_a_founding_army_sits_near_seventy_per_cent_of_the_cap(self):
        w = world(month=0)
        _, burden, mood = rivals._defence_budget(w, "veleria")
        self.assertAlmostEqual(burden / rivals.DEFENCE_BURDEN_CAP, .70, delta=.05)
        self.assertNotEqual(mood, "overstretched")

    def test_a_smaller_economy_carries_a_heavier_burden(self):
        # A fifth off the economy, so the burden stays under the cap and the ratio is the output ratio.
        w = world(month=0)
        _, full, mood = rivals._defence_budget(w, "dorsania")
        self.assertLess(full, rivals.DEFENCE_BURDEN_CAP)
        dorsania = w.foreign["actors"]["dorsania"]
        dorsania["economy"]["gdp"] *= .8
        w.rivals["dorsania"].gdp_real *= .8
        _, smaller, _ = rivals._defence_budget(w, "dorsania")
        self.assertAlmostEqual(smaller / full, 1 / .8, places=3)

    def test_a_doubled_army_is_overstretched(self):
        w = world(month=0)
        w.rivals["veleria"].army = 2 * 65000
        _, burden, mood = rivals._defence_budget(w, "veleria")
        self.assertEqual(mood, "overstretched")
        self.assertEqual(burden, rivals.DEFENCE_BURDEN_CAP)

    def test_readiness_holds_in_a_year_of_peace_at_the_founding_army(self):
        for actor in ("veleria", "dorsania"):
            for domestic in (False, True):
                with self.subTest(actor=actor, domestic=domestic):
                    w = world(month=0)
                    start = w.foreign["actors"][actor]["military"]["readiness"]
                    for month in range(12):
                        w.month = month
                        if domestic:                  # the foreign cabinets' monthly update of the treasury
                            foreign._domestic(w)
                        rivals.monthly(w)
                    end = w.foreign["actors"][actor]["military"]["readiness"]
                    self.assertGreaterEqual(end, start - .03, f"{actor}: readiness {start:.3f} -> {end:.3f}")


class FirstLookAtTheArming(unittest.TestCase):
    """FO12: the neighbours' first look at Karamaniya's policy compares it with the policy the run started with, so an
    arming made in Month 1 counts as it would in any later month."""

    def test_an_arming_made_in_month_one_is_seen(self):
        w = world(month=0)
        w.policy.recruitment, w.policy.mobilization = "general", "general"
        w.policy.military = w.policy.military + .01
        resolve.monthly(w)
        reasons = [x["reason"] for x in resolve.recent(w, 12, 10)]
        self.assertTrue(any("recruitment raised to general" in r for r in reasons), reasons)
        self.assertTrue(any("reservists called up (general)" in r for r in reasons), reasons)
        self.assertTrue(any("military budget raised" in r for r in reasons), reasons)

    def test_a_month_one_policy_left_as_it_started_is_no_move(self):
        w = world(month=0)
        resolve.monthly(w)
        self.assertEqual(resolve.recent(w, 12, 10), [])


def cession_motion(region: str = "Kessel Valley", target: str = "VELERIA"):
    """A council motion to cede a region to a neighbour, as politics.validate_motion_detail reads it."""
    return {"id": "M1", "type": "diplomacy", "subject": "cede_region", "value": region,
            "text": f"Cede {region} to {target.title()}.", "action": {"target": target}, "proposer": "A"}


class LapsedDemandsForLand(unittest.TestCase):
    """FO16: a demand for land that has lapsed is a basis for a cession only in the month it lapses."""

    def test_a_lapsed_demand_is_a_basis_for_a_cession_only_in_the_month_it_lapses(self):
        w = world(month=0)
        self.assertIsNone(act(w, "veleria", type="ultimatum", terms="cede_region", region="kessel", deadline_months=2))
        deadline = w.dip.ultimatum["deadline"]
        w.month = deadline
        self.assertIsNone(politics.validate_motion_detail(w, cession_motion()))     # the deadline month: still standing
        w.month = deadline + 1
        w.dip.ultimatum = {}                                                       # lapsed in this month
        self.assertIsNone(politics.validate_motion_detail(w, cession_motion()))    # the month it lapses
        w.month = deadline + 2
        problem = politics.validate_motion_detail(w, cession_motion())
        self.assertIsNotNone(problem, "a cession two months after the deadline should not be accepted")
        self.assertEqual(problem["reason_code"], "NOT_DEMANDED")


class TheDeadlineMonth(unittest.TestCase):
    """FO18 and TO7: a demand is due in its deadline month, which its cabinet can still answer, and it has expired the
    month after (the engine lapses it then)."""

    def test_a_demand_is_due_in_its_deadline_month_and_expired_the_month_after(self):
        w = world(month=0)
        self.assertIsNone(act(w, "veleria", type="ultimatum", terms="status_talks", deadline_months=2))
        deadline = w.dip.ultimatum["deadline"]
        w.month = deadline
        ult = foreign_force.cabinet_view(w, "veleria")["confrontation"]["ultimatum"]
        self.assertEqual(ult["deadline_month"], deadline + 1)
        self.assertFalse(ult["expired"])
        w.month = deadline + 1
        self.assertTrue(foreign_force.ultimatum_compliance(w)["expired"])

    def test_a_land_demand_is_due_in_its_deadline_month_and_expired_the_month_after(self):
        w = world(month=0)
        self.assertIsNone(act(w, "veleria", type="ultimatum", terms="cede_region", region="kessel", deadline_months=2))
        deadline = w.dip.ultimatum["deadline"]
        w.month = deadline
        self.assertFalse(foreign_force.ultimatum_compliance(w)["expired"])
        w.month = deadline + 1
        self.assertTrue(foreign_force.ultimatum_compliance(w)["expired"])

    def test_a_demand_met_by_a_cession_is_not_expired_in_its_deadline_month(self):
        w = world(month=0)
        self.assertIsNone(act(w, "veleria", type="ultimatum", terms="cede_region", region="kessel", deadline_months=2))
        deadline = w.dip.ultimatum["deadline"]
        territory.cede(w, "kessel", "veleria")
        w.month = deadline
        met = foreign_force.ultimatum_compliance(w)
        self.assertTrue(met["met"])
        self.assertFalse(met["expired"])


class MobilizationStepDown(unittest.TestCase):
    """FO17: a step down in mobilization is not a call-up; only a step up is, as a rise in recruitment is."""

    def test_stepping_mobilization_down_from_general_to_partial_is_no_call_up(self):
        w = world(month=3)
        w.policy.mobilization = "general"
        resolve.monthly(w)
        w.month = 4
        w.policy.mobilization = "partial"
        resolve.monthly(w)
        self.assertEqual([x for x in resolve.recent(w, 6, 4) if x["month"] == 4], [])

    def test_stepping_mobilization_up_is_a_call_up(self):
        w = world(month=3)
        w.policy.mobilization = "partial"
        resolve.monthly(w)
        w.month = 4
        w.policy.mobilization = "general"
        resolve.monthly(w)
        reasons = [x["reason"] for x in resolve.recent(w, 6, 4) if x["month"] == 4]
        self.assertEqual(reasons, ["reservists called up (general)"])


class DeploymentCostsBudgetNotOutput(unittest.TestCase):
    """FO14: moving soldiers to a border costs budget and not output, since a call-up already took them out of work."""

    def test_a_deployment_costs_no_output_and_keeps_its_fiscal_cost(self):
        w = world(month=0)
        dom = w.foreign["actors"]["veleria"]["domestic"]
        dom["fiscal_stress"] = .1234
        econ = w.foreign["actors"]["veleria"]["economy"]
        gdp0, real0 = econ["gdp"], w.rivals["veleria"].gdp_real
        self.assertIsNone(act(w, "veleria", type="deploy_to_border", front="north", troops=50000))
        self.assertEqual(econ["gdp"], gdp0)
        self.assertEqual(w.rivals["veleria"].gdp_real, real0)
        self.assertGreater(dom["fiscal_stress"], .1234)

    def test_a_call_up_still_costs_output(self):
        w = world(month=0)
        econ = w.foreign["actors"]["veleria"]["economy"]
        gdp0 = econ["gdp"]
        self.assertIsNone(act(w, "veleria", type="mobilize", troops=5000))
        self.assertLess(econ["gdp"], gdp0)


if __name__ == "__main__":
    unittest.main()
