"""World engine 19: the military, the General Staff, audits and stand-downs (audit slice MI, docs/AUDIT_ENGINE18.md).

Each class pins one finding of the engine-18 audit, reproduced first with its proof script and then turned into a
test that fails on engine 18 and passes once the finding is fixed.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import audits, director, engine, fine_print, foreign, ministries, military, staff  # noqa: E402
from karamaniya.world import World, new_world  # noqa: E402


def world(seed: int = 5):
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def standing_pay(w) -> float:
    """What military.update charges for the standing army and navy in a month, before any reserve."""
    pay = military.officer_pay(w)
    focus = military.training_intensity(w)
    return (w.mil.army.size * military.ARMY_COST * w.econ.cpi * pay["bill"] * focus["bill"]
            + w.mil.navy.size * military.SHIP_COST * w.econ.cpi)


def fiscal(mil_paid: float) -> dict:
    return {"mil_paid": mil_paid, "police_paid": 1e12}


def step(w, months: int = 1) -> None:
    """Whole months with no delegates acting, as test_military_realism runs them."""
    original = director.act
    director.act = lambda world, *_a, **_k: setattr(world.dip, "inbox", [])
    try:
        for _ in range(months):
            engine.begin_month(w)
            engine.step(w)
    finally:
        director.act = original


def play(w, months: int = 1) -> None:
    """Whole months with the director acting as it does in a run (poc_14 steps the engine this way)."""
    for _ in range(months):
        engine.begin_month(w)
        engine.step(w)


def war_world():
    """The engine-18 PoC 14 setup: a war on two fronts under partial mobilization, so a region can fall mid-run."""
    w = world()
    w.policy.mobilization = "partial"
    w.policy.recruitment = "none"
    w.dip.war = True
    w.dip.war_start = 0
    w.dip.union_intensity = 1.0
    w.dip.union_front = {"north": 40000.0, "east": 20000.0}
    ministries.aggrieve(w, "army", 0.12, "test grievance")
    w.mil.army.loyalty = 0.4
    return w


def books(w) -> dict:
    """Everything a resumed run has to carry: the army, the call-up, and each population's share on the books."""
    mob = military.mobilization_of(w)
    return {"army": w.mil.army.size, "loyalty": w.mil.army.loyalty, "called_up": mob.called_up,
            "served": mob.served, "union_front": dict(w.dip.union_front),
            "controllers": [r.controller for r in w.regions],
            "pops": [(p.region, p.cls, p.ident, p.size, p.conscripted) for p in w.pops]}


class TheReserveIsPaidFor(unittest.TestCase):
    """MI1: calling up reservists was free. military.reserve_cost was never called, though the prompt says the
    reservists cost money; a general call-up of 63,357 reservists added no arrears (PoC poc_1_reserve_costs_uncharged)."""

    def test_an_unpaid_reserve_bill_becomes_arrears(self):
        w = world()
        w.policy.mobilization = "general"
        w.policy.recruitment = "none"
        pool = military.reserve_pool(w)
        embodied = pool * military.MOBILIZATION_SHARE["general"]
        # Audit MI1-f: the charged bill is the reservists' pay and the activation, not the trained pool's upkeep.
        bill = military.reserve_cost(w, pooled=pool, embodied=embodied)
        reserve_bill = bill["embodied_monthly"] + bill["activation_one_off"]
        # The budget covers the standing force and most of the reserve bill, but not all of it.
        military.update(w, fiscal((standing_pay(w) + reserve_bill) * .9))
        self.assertGreater(w.mil.army.arrears, 0.0,
                           "the reservists' pay and activation fell due and nothing was left unpaid")

    def test_the_activation_is_charged_in_the_month_of_the_call_up_and_not_again(self):
        w = world()
        w.policy.mobilization = "general"
        w.policy.recruitment = "none"
        pool = military.reserve_pool(w)
        embodied = pool * military.MOBILIZATION_SHARE["general"]
        # Audit MI1-f: the budgets are the charged bill (embodied pay and activation), not the trained pool's upkeep.
        reserve_bill = military.reserve_cost(w, pooled=pool, embodied=embodied)["embodied_monthly"]
        activation = military.reserve_cost(w, embodied=embodied)["activation_one_off"]
        self.assertGreater(activation, 0.0)
        # Month of the call-up: the budget covers the bill with the activation in it.
        military.update(w, fiscal((standing_pay(w) + reserve_bill + activation) * 1.0001))
        self.assertEqual(w.mil.army.arrears, 0.0)
        # The next month, same reservists: no new activation, so the embodied pay alone is covered.
        steady = standing_pay(w) + military.reserve_cost(w)["embodied_monthly"]
        military.update(w, fiscal(steady * 1.0001))
        self.assertEqual(w.mil.army.arrears, 0.0, "the activation was charged again the next month")


class ReservistsFromALostRegion(unittest.TestCase):
    """MI11: reservists drawn from a region the Union takes stayed on the labour books for good, and the populations
    still held were charged the full draw again (1,159 counted twice; poc_13_reservists_from_lost_region_stay_on_books)."""

    def test_the_books_hold_exactly_the_reservists_embodied_after_a_region_falls(self):
        w = world()
        w.policy.mobilization = "partial"
        w.policy.recruitment = "none"
        step(w)
        self.assertGreater(sum(p.conscripted for p in w.pops if p.region == "dorran"), 0.0)
        w.region("dorran").controller = "union"
        step(w, 2)
        self.assertAlmostEqual(sum(p.conscripted for p in w.pops), military.mobilization_of(w).called_up,
                               delta=1e-6, msg="the reservists from the lost region are still on the labour books")
        self.assertEqual(sum(p.conscripted for p in w.pops if p.region == "dorran"), 0.0,
                         "the lost region's people went back to labour and nothing draws on them")


class AResumedRunMatchesTheUnbrokenOne(unittest.TestCase):
    """MI12: a saved run did not resume faithfully once a region had fallen. Pop._mobilized_share was set on the
    populations but is not saved, so the resumed run released conscripts the unbroken run kept, from Month 4
    (poc_14_resume_diverges_after_region_falls, poc_12_resume_roundtrip)."""

    def test_a_save_taken_after_a_region_falls_resumes_identically(self):
        unbroken = war_world()
        play(unbroken, 6)
        broken = war_world()
        play(broken, 3)
        self.assertEqual(broken.region("dorran").controller, "union", "the region should have fallen by the save")
        resumed = World.from_dict(json.loads(json.dumps(broken.to_dict())))
        play(resumed, 3)
        self.assertEqual(books(resumed), books(unbroken))


class TheGeneralStaffsRequest(unittest.TestCase):
    """MI4: a delivered half answer was judged unanswered, because its target was tested against the gap of the day,
    which the answer itself had closed, so grievance accrued. MI7: any call-up of reservists answered the request,
    however small (poc_4_staff_unanswered_after_partial_answer, poc_8_staff_any_call_up_answers)."""

    def test_a_half_answer_is_judged_against_the_gap_the_request_arose_with(self):
        w = world()
        w.policy.recruitment = "partial"
        w.policy.army_target = 33_000.0      # half of the 10,000 gap the request arises with
        step(w, 3)
        self.assertEqual(staff.unanswered(w), 0)
        self.assertEqual(ministries.grievance(w, "army"), 0.0)

    def test_a_small_call_up_does_not_answer_a_large_request(self):
        w = world()
        scale = 150_000.0 / military.union_army(w)
        for r in w.rivals.values():
            r.army *= scale                  # a 32,000 gap: a partial call-up of about 7,000 cannot cover half of it
        w.policy.mobilization = "partial"
        w.policy.recruitment = "none"
        step(w, 3)
        self.assertEqual(staff.unanswered(w), 3, "a partial call-up answered a request it does not cover")
        self.assertGreater(ministries.grievance(w, "army"), 0.0)

    def test_a_call_up_answers_once_its_effective_strength_covers_half_the_gap(self):
        w = world()
        w.policy.mobilization = "general"    # about 21,000 called up, but only 15 per cent effective on the day
        w.policy.recruitment = "none"
        step(w)
        self.assertEqual(staff.unanswered(w), 1, "the first month's call-up was counted at its full strength")
        step(w)
        self.assertEqual(staff.unanswered(w), 0, "the call-up's effective strength covers the gap")


class AStandDownHoldsItsMonths(unittest.TestCase):
    """MI2 and MO17: a stand-down documented to hold two months, counting the month it is made, held three
    (on_offer set until = from + 2 and defence_factor tests inclusively; poc_2_standdown_three_months)."""

    def test_it_holds_the_month_it_is_made_and_the_next_and_no_more(self):
        w = world()
        made = 4                                       # Month 5 (0-based index)
        w.month = made
        text = "Stand down the Karamanian patrols on the northern border pending findings."
        mo = {"type": "diplomacy", "subject": "diplomatic_protest", "text": text,
              "final_executable_action": {"action_type": "diplomatic_protest", "target": "veleria", "terms": [text]}}
        fine_print.on_offer(w, mo, ["stand_down"], "veleria")
        held = []
        for month in range(made, made + 4):
            w.month = month
            held.append(fine_print.defence_factor(w, "north") < 1.0)
        self.assertEqual(held, [True, True, False, False])

    def test_the_monthly_prune_agrees_with_the_defence(self):
        w = world()
        made = 4
        w.month = made
        text = "Stand down the Karamanian patrols on the northern border pending findings."
        mo = {"type": "diplomacy", "subject": "diplomatic_protest", "text": text,
              "final_executable_action": {"action_type": "diplomatic_protest", "target": "veleria", "terms": [text]}}
        fine_print.on_offer(w, mo, ["stand_down"], "veleria")
        for month in range(made, made + 3):
            w.month = month
            fine_print.monthly(w)
        self.assertEqual(fine_print.state(w)["standdowns"], [], "the stand-down outlived its second month")


class AuditFindingsShowThreeMonths(unittest.TestCase):
    """MI10: audit findings were shown for four months (the window kept a finding while its age was at most three),
    where audits.text documents three, counting the month it is delivered (poc_11_audit_findings_window)."""

    def test_a_finding_is_shown_in_its_delivery_month_and_the_next_two(self):
        w = world()
        audits.open_audit(w, "army", "B", "Audit the army.", {"B": "yes"})
        w.month = 4                                    # delivered at the end of Month 5 (0-based 4)
        audits.deliver(w)
        shown = []
        for month in range(4, 8):
            w.month = month
            shown.append("Audit findings" in audits.text(w))
        self.assertEqual(shown, [True, True, True, False])


if __name__ == "__main__":
    unittest.main()
