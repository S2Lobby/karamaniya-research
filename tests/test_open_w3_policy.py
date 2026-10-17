"""Wave A W3: the policy language's execution (karamaniya/policy.py).

A `policy` motion carries one to four items. Each is carried out deterministically by the engine:
`set_lever` holds a setting while its condition holds and its schedule runs, and restores it at the end
unless a later decision changed it; `transfer`, `public_works` and `commission` spend money through the
engine's funding paths and reach the world through the effect bus and the society step. Conditions are
tested at the start of each month with motion_actions.evaluate_conditions; schedules run start_in 0-6
months and 1-24 months.

These tests use the real engine and call no model.

    python -m unittest tests.test_open_w3_policy
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import actions, calibration, effects, engine, errors, motion_actions, policy, politics  # noqa: E402
from karamaniya.world import World, new_world  # noqa: E402

GDP = 552_676_524.75       # starting monthly output, for the cut-share arithmetic (see new_world)


def policy_world(seed: int = 1, harness: str = "language"):
    w = new_world(seed)
    w.harness = harness
    return w


def adopt(w, items, proposer="A", mid="P-1", text="A policy for the country."):
    """Carry a policy motion the way the council does after the vote."""
    motion = {"id": mid, "type": "policy", "proposer": proposer, "text": text, "items": items}
    return politics.apply_motion(w, motion)


def item(instrument, **fields):
    return {"instrument": instrument, **fields}


def set_lever(lever, value, start_in=0, months=2, condition=None):
    entry = item("set_lever", lever=lever, value=value, start_in=start_in, months=months)
    if condition is not None:
        entry["condition"] = condition
    return entry


def transfer(target, amount, funding="reserves", start_in=0, months=1, condition=None):
    entry = item("transfer", target=target, amount=amount, funding=funding,
                 start_in=start_in, months=months)
    if condition is not None:
        entry["condition"] = condition
    return entry


def public_works(target, amount, funding="reserves", start_in=0, months=1, condition=None):
    entry = item("public_works", target=target, amount=amount, funding=funding,
                 start_in=start_in, months=months)
    if condition is not None:
        entry["condition"] = condition
    return entry


def commission(mandate, amount, funding="reserves", start_in=0, months=1, condition=None):
    entry = item("commission", mandate=mandate, amount=amount, funding=funding,
                 start_in=start_in, months=months)
    if condition is not None:
        entry["condition"] = condition
    return entry


def record_of(w, month=None):
    """The policies record of a month's history row, or None."""
    rows = [row for row in w.history if month is None or row.get("month") == month]
    return (rows[-1].get("policies") if rows else None)


def entries(record, section, instrument=None, mid=None):
    if not record:
        return []
    return [entry for entry in record.get(section) or []
            if (instrument is None or entry.get("instrument") == instrument)
            and (mid is None or entry.get("id") == mid)]


def applied_value(w, channel, target, month=None):
    """The sum the bus reports applying on one channel and target in a month's history row."""
    row = [r for r in w.history if month is None or r.get("month") == month][-1]
    return round(sum(abs(float(rec["value"])) for rec in row.get("effects_applied") or []
                     if rec.get("channel") == channel and rec.get("target") == target), 6)


def quiet_month(w):
    """One policy month without the rest of the engine: the call engine.step makes, then the bus step."""
    policy.monthly(w)
    effects.step(w)
    w.month += 1


class ReaderAndKeyTests(unittest.TestCase):
    """The interface W2 built is the one the execution reads, and the duplicate key is the canonical items."""

    def test_a_valid_policy_is_accepted_at_resolution_under_language_and_refused_under_menu(self):
        w = policy_world()
        mo = {"id": "P-1", "type": "policy", "proposer": "A", "text": "Ration the cities.",
              "items": [set_lever("rationing", True)]}
        self.assertIsNone(politics.validate_motion(w, mo))
        menu = policy_world(harness="menu")
        rejection = politics.validate_motion(menu, {**mo, "items": [set_lever("rationing", True)]})
        self.assertIsNotNone(rejection)
        self.assertIn("unknown motion type", rejection)

    def test_the_duplicate_key_is_the_canonical_items_and_the_month(self):
        w = policy_world()
        first = {"id": "P-1", "type": "policy", "proposer": "A", "text": "x",
                 "items": [set_lever("rationing", True), transfer("ident:vell", 4.0)]}
        second = {"id": "P-2", "type": "policy", "proposer": "B", "text": "y",
                  "items": [transfer("ident:vell", 4.0), set_lever("rationing", True)]}
        different = {"id": "P-3", "type": "policy", "proposer": "C", "text": "z",
                     "items": [set_lever("rationing", True), transfer("ident:vell", 5.0)]}
        self.assertEqual(motion_actions.execution_key(w, first), motion_actions.execution_key(w, second))
        self.assertNotEqual(motion_actions.execution_key(w, first), motion_actions.execution_key(w, different))
        before = motion_actions.execution_key(w, first)
        w.month = 1
        self.assertNotEqual(motion_actions.execution_key(w, first), before,
                            "the same policy in another month is another act")

    def test_a_contradictory_policy_is_blocked_before_execution(self):
        w = policy_world()
        two_values = {"id": "P-1", "type": "policy", "proposer": "A", "text": "x",
                      "items": [set_lever("welfare", 0.05), set_lever("welfare", 0.06)]}
        gate = motion_actions.validate_execution(w, {**two_values, "passed": True})
        self.assertEqual(gate["code"], "POLICY_LIMIT")
        set_and_cut = {"id": "P-2", "type": "policy", "proposer": "A", "text": "x",
                       "items": [set_lever("welfare", 0.05),
                                 transfer("ident:vell", 4.0, funding="cut:welfare")]}
        self.assertEqual(motion_actions.validate_execution(w, {**set_and_cut, "passed": True})["code"],
                         "POLICY_LIMIT")

    def test_a_spending_item_without_funding_is_refused_at_tabling(self):
        w = policy_world()
        mo = {"id": "P-1", "type": "policy", "proposer": "A", "text": "Pay the Vell.",
              "action": {"items": [{"instrument": "transfer", "target": "ident:vell", "amount": 4.0,
                                    "months": 2}]}}
        rejection = actions.validate_new_motion(w, mo, "language")
        self.assertEqual(rejection["reason_code"], "POLICY_UNFUNDED")


class LeverHoldTests(unittest.TestCase):
    """set_lever: the programme's directive path, a hold while the schedule runs, a restore at the end."""

    def test_a_hold_sets_the_directive_and_restores_the_prior_value(self):
        w = policy_world()
        self.assertFalse(w.policy.rationing)
        adopt(w, [set_lever("rationing", True, months=2)])
        engine.step(w)
        self.assertTrue(w.policy.rationing)
        self.assertTrue(w.const.directives["rationing"])
        self.assertEqual(w.const.directive_bounds["rationing"], {"min": True, "max": True})
        record = record_of(w)
        applied = entries(record, "applied", "set_lever")
        self.assertEqual(len(applied), 1)
        self.assertTrue(applied[0]["holds"][0]["held"])
        self.assertFalse(applied[0]["holds"][0]["prior"])

        engine.step(w)
        self.assertTrue(w.policy.rationing, "the hold runs its second month")
        engine.step(w)
        self.assertFalse(w.policy.rationing, "the setting returns to the value from before the hold")
        self.assertNotIn("rationing", w.const.directives)
        self.assertNotIn("rationing", w.const.directive_bounds)
        ended = entries(record_of(w), "ended", "set_lever")
        self.assertTrue(ended, "the end is recorded in the month after the last one it ran")
        self.assertTrue(ended[0]["holds"][0]["restored"])
        self.assertEqual(ended[0]["holds"][0]["prior"], False)

    def test_a_later_decision_supersedes_the_hold_and_is_not_undone(self):
        w = policy_world()
        self.assertAlmostEqual(w.policy.welfare, 0.04)
        adopt(w, [set_lever("welfare", 0.05, months=1)])
        engine.step(w)
        self.assertAlmostEqual(w.policy.welfare, 0.05)
        # A later council decision on the same setting (a programme or set_policy writes the same ledger).
        w.const.directives["welfare"] = 0.06
        w.const.directive_bounds["welfare"] = {"min": 0.06, "max": 0.06}
        politics.set_lever(w, "welfare", 0.06)
        engine.step(w)
        self.assertAlmostEqual(w.policy.welfare, 0.06, msg="the later decision stands")
        ended = entries(record_of(w), "ended", "set_lever")
        self.assertTrue(ended)
        hold = ended[0]["holds"][0]
        self.assertTrue(hold["superseded"])
        self.assertFalse(hold["restored"])
        self.assertAlmostEqual(hold["prior"], 0.04)
        self.assertAlmostEqual(hold["current"], 0.06)

    def test_a_condition_pauses_the_hold_and_resuming_takes_a_fresh_prior(self):
        w = policy_world()
        adopt(w, [set_lever("rationing", True, months=4,
                            condition={"metric": "approval", "operator": ">=", "value": 0.9})])
        engine.step(w)
        self.assertFalse(w.policy.rationing, "the condition is false: the hold is not established")
        paused = entries(record_of(w), "in_force", "set_lever")
        self.assertEqual(paused[0]["status"], "paused")
        self.assertIn("condition", paused[0]["reason"])
        # The condition is true at the start of the next month.
        for pop in w.k_pops():
            pop.approval = 0.95
        engine.step(w)
        self.assertTrue(w.policy.rationing)
        # It stops holding again: the setting goes back.
        for pop in w.k_pops():
            pop.approval = 0.2
        engine.step(w)
        self.assertFalse(w.policy.rationing)
        ended = entries(record_of(w), "ended", "set_lever")
        self.assertTrue(ended)
        self.assertEqual(ended[0]["reason"], "its condition stopped holding")
        self.assertTrue(ended[0]["holds"][0]["restored"])

    def test_an_office_order_against_the_hold_is_a_compliance_row(self):
        w = policy_world()
        w.const.offices["army"] = "D"
        adopt(w, [set_lever("posture", "fortify", months=2)])
        engine.step(w)
        self.assertEqual(w.policy.posture, "fortify")
        rows = []
        politics.apply_orders(w, "D", {"army": {"posture": "attack"}}, compliance=rows)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["compliance_status"], politics.EXPLICIT_VIOLATION)
        self.assertEqual(rows[0]["lever"], "posture")
        self.assertEqual(rows[0]["directive_value"], "fortify")
        self.assertEqual(rows[0]["office_order_value"], "attack")


class TransferTests(unittest.TestCase):
    """transfer: money each month, the funding path, and a per-head effect through the bus."""

    def test_a_transfer_spends_from_reserves_and_reaches_the_target_group(self):
        plain, treated = policy_world(3), policy_world(3)
        gold_before = treated.econ.gold
        adopt(treated, [transfer("ident:vell", 6.0, funding="reserves", months=1)])
        engine.step(plain)
        engine.step(treated)
        self.assertAlmostEqual(gold_before - treated.econ.gold,
                               (gold_before - plain.econ.gold) + 6e6, delta=1e4,
                               msg="the month's payment is six million crowns in gold")
        vell = [p for p in treated.k_pops() if p.ident == "vell"]
        kara = [p for p in treated.k_pops() if p.ident == "karamanian"]
        plain_vell = [p for p in plain.k_pops() if p.ident == "vell"]
        plain_kara = [p for p in plain.k_pops() if p.ident == "karamanian"]
        self.assertGreater(treated.avg("income", vell), plain.avg("income", plain_vell) + 0.002,
                           "the transfer's income modifier reaches the Vell")
        self.assertAlmostEqual(treated.avg("income", kara), plain.avg("income", plain_kara), places=9,
                               msg="and no one else")
        record = record_of(treated)
        applied = entries(record, "applied", "transfer")[0]
        self.assertEqual(applied["funding"]["source"], "reserves")
        self.assertAlmostEqual(applied["funding"]["paid"], 6.0)

    def test_the_effect_is_scaled_per_head_and_capped(self):
        small, large = policy_world(4), policy_world(4)
        adopt(small, [transfer("ident:vell", 0.25)])
        adopt(large, [transfer("ident:vell", 0.5)])
        policy.monthly(small)
        effects.step(small)
        policy.monthly(large)
        effects.step(large)
        small_value = effects.modifiers(small, "income")["ident:vell"]
        large_value = effects.modifiers(large, "income")["ident:vell"]
        self.assertGreater(large_value, small_value)
        self.assertAlmostEqual(large_value / small_value, 2.0, places=3)
        capped = policy_world(4)
        adopt(capped, [transfer("ident:vell", 50.0)])
        policy.monthly(capped)
        effects.step(capped)
        self.assertLessEqual(abs(effects.modifiers(capped, "income")["ident:vell"]), 0.02 + 1e-9)
        self.assertLessEqual(abs(effects.modifiers(capped, "hunger")["ident:vell"]), 0.02 + 1e-9)

    def test_the_bus_records_income_hunger_grievance_and_a_capped_approval_part(self):
        w = policy_world(5)
        adopt(w, [transfer("class:farmers", 3.0, months=2)])
        engine.step(w)
        engine.step(w)
        recs = [r for row in w.history for r in row.get("effects_applied") or []
                if r.get("channel") in ("income", "hunger", "grievance", "approval")
                and r.get("target") == "class:farmers"]
        self.assertEqual({r["channel"] for r in recs}, {"income", "hunger", "grievance", "approval"})
        self.assertTrue(all(r["source"]["kind"] == "policy" for r in recs))
        self.assertTrue(all(abs(float(r["value"])) <= effects.CHANNELS[r["channel"]]["cap"] + 1e-9
                            for r in recs))
        income = next(r for r in recs if r["channel"] == "income")
        grievance = next(r for r in recs if r["channel"] == "grievance")
        approval = next(r for r in recs if r["channel"] == "approval")
        self.assertGreater(income["value"], 0)
        self.assertLess(grievance["value"], 0)
        self.assertGreater(approval["value"], 0)
        self.assertLessEqual(abs(approval["value"]), 0.01 + 1e-9, "the approval part is capped")


class FundingTests(unittest.TestCase):
    """Every funding source, its capacity, and its refusal."""

    def test_reserves_are_refused_below_the_floor(self):
        w = policy_world(6)
        w.econ.gold = 5e6
        item_ = transfer("ident:vell", 10.0, funding="reserves")
        item_["condition"] = {"metric": "reserves", "operator": ">=", "value": 10.0}   # 10 million
        adopt(w, [item_])
        policy.monthly(w)
        record = w.institutions["policy_record"]
        refused = entries(record, "refused", "transfer")
        self.assertTrue(refused)
        self.assertEqual(refused[0]["code"], "POLICY_UNFUNDED")
        self.assertAlmostEqual(w.econ.gold, 5e6)
        self.assertEqual(w.institutions.get("effects") or [], [], "nothing is scheduled")

    def test_borrowing_is_charged_to_domestic_debt_and_refused_over_capacity(self):
        w = policy_world(7)
        adopt(w, [transfer("ident:vell", 10.0, funding="borrowing")])
        debt = w.econ.debt_dom
        policy.monthly(w)
        self.assertAlmostEqual(w.econ.debt_dom, debt + 10e6, delta=1.0)
        poor = policy_world(7)
        poor.econ.confidence = 0.05
        adopt(poor, [transfer("ident:vell", 10.0, funding="borrowing")])
        debt_before = poor.econ.debt_dom
        policy.monthly(poor)
        refused = entries(poor.institutions["policy_record"], "refused", "transfer")
        self.assertTrue(refused)
        self.assertEqual(refused[0]["code"], "POLICY_UNFUNDED")
        self.assertAlmostEqual(poor.econ.debt_dom, debt_before)

    def test_a_cut_lowers_the_spending_setting_and_restores_it(self):
        w = policy_world(8)
        prior = w.policy.welfare
        adopt(w, [transfer("ident:vell", 5.0, funding="cut:welfare", months=1)])
        policy.monthly(w)
        self.assertAlmostEqual(w.policy.welfare, prior - 5e6 / w.econ.gdp_nominal, places=6)
        self.assertIn("welfare", w.const.directives)
        record = w.institutions["policy_record"]
        applied = entries(record, "applied", "transfer")[0]
        self.assertEqual(applied["funding"]["source"], "cut:welfare")
        w.month += 1
        policy.monthly(w)
        self.assertAlmostEqual(w.policy.welfare, prior, places=6, msg="the cut ends with the policy")
        self.assertNotIn("welfare", w.const.directives)

    def test_a_cut_beyond_the_setting_spends_is_refused(self):
        w = policy_world(9)
        prior = w.policy.military
        adopt(w, [transfer("ident:vell", 20.0, funding="cut:military")])
        policy.monthly(w)
        refused = entries(w.institutions["policy_record"], "refused", "transfer")
        self.assertTrue(refused)
        self.assertEqual(refused[0]["code"], "POLICY_UNFUNDED")
        self.assertAlmostEqual(w.policy.military, prior)
        self.assertNotIn("military", w.const.directives)

    def test_a_cut_stops_at_the_settings_lower_bound(self):
        w = policy_world(10)
        lo = politics.lever_bounds("health_edu")[0]
        room = (w.policy.health_edu - lo) * w.econ.gdp_nominal / 1e6
        refused_world = policy_world(10)
        adopt(refused_world, [transfer("ident:vell", room + 1.0, funding="cut:health_edu")])
        policy.monthly(refused_world)
        self.assertEqual(entries(refused_world.institutions["policy_record"], "refused", "transfer")[0]["code"],
                         "POLICY_UNFUNDED")
        ok_world = policy_world(10)
        adopt(ok_world, [transfer("ident:vell", room - 1.0, funding="cut:health_edu")])
        policy.monthly(ok_world)
        self.assertGreaterEqual(ok_world.policy.health_edu, lo - 1e-9)


class PublicWorksTests(unittest.TestCase):
    """public_works: money in a region, repairs through the bus with a one- to two-month lag."""

    def setUp(self):
        self.w = policy_world(11)
        region = self.w.region("kessel")
        region.damage = 0.10
        region.logistics = 0.70

    def test_logistics_land_after_one_month_and_damage_after_two(self):
        adopt(self.w, [public_works("kessel", 10.0, funding="reserves", months=2)])
        quiet_month(self.w)
        self.assertAlmostEqual(self.w.region("kessel").damage, 0.10)
        self.assertAlmostEqual(self.w.region("kessel").logistics, 0.70)
        quiet_month(self.w)
        self.assertAlmostEqual(self.w.region("kessel").damage, 0.10, msg="damage waits two months")
        self.assertGreater(self.w.region("kessel").logistics, 0.70, msg="logistics after one month")
        quiet_month(self.w)
        self.assertLess(self.w.region("kessel").damage, 0.10, msg="damage after two months")

    def test_the_repairs_are_capped_and_an_income_effect_reaches_the_region(self):
        adopt(self.w, [public_works("kessel", 10.0, funding="reserves", months=2)])
        quiet_month(self.w)
        quiet_month(self.w)
        applied = self.w.institutions.get("effects_applied") or []
        logistics = [r for r in applied if r.get("channel") == "logistics" and r.get("target") == "kessel"]
        self.assertTrue(logistics)
        self.assertLessEqual(abs(logistics[0]["value"]), 0.05 + 1e-9)
        income = [r for r in applied if r.get("channel") == "income" and r.get("target") == "kessel"]
        self.assertTrue(income, "the works buy labour in the region")
        self.assertLessEqual(abs(income[0]["value"]), 0.01 + 1e-9)

    def test_unemployment_is_not_a_channel_the_engine_can_move_directly(self):
        # Documented gap: the bus has no unemployment channel, and society derives unemployment from output.
        # public_works therefore lowers income and hunger risk indirectly, not unemployment itself.
        self.assertNotIn("unemployment", effects.CHANNELS)
        adopt(self.w, [public_works("kessel", 10.0, funding="reserves", months=1)])
        for _ in range(3):
            quiet_month(self.w)
        channels = {r.get("channel") for r in self.w.institutions.get("effects_applied") or []}
        self.assertNotIn("unemployment", channels)

    def test_a_works_budget_without_capacity_is_refused_and_nothing_is_queued(self):
        self.w.econ.gold = 0.0
        adopt(self.w, [public_works("kessel", 10.0, funding="reserves", months=2)])
        policy.monthly(self.w)
        refused = entries(self.w.institutions["policy_record"], "refused", "public_works")
        self.assertTrue(refused)
        self.assertEqual(refused[0]["code"], "POLICY_UNFUNDED")
        self.assertFalse(self.w.institutions["policies"]["active"][0].get("pending"))


class CommissionTests(unittest.TestCase):
    """commission: a standing body whose monthly effect scales with administration and budget, capped."""

    def _hunger_effect(self, capacity, amount):
        w = policy_world(12)
        w.econ.admin_capacity = capacity
        adopt(w, [commission("food_distribution", amount)])
        policy.monthly(w)
        effects.step(w)
        return effects.modifiers(w, "hunger").get("*", 0.0)

    def test_the_effect_scales_with_admin_capacity_and_budget(self):
        full = self._hunger_effect(1.0, 5.0)
        half = self._hunger_effect(0.5, 5.0)
        self.assertLess(full, 0)
        self.assertAlmostEqual(half / full, 0.5, places=3)
        quarter_budget = self._hunger_effect(1.0, 1.25)
        self.assertAlmostEqual(quarter_budget / full, 0.25, places=3)

    def test_the_effect_is_capped(self):
        w = policy_world(12)
        w.econ.admin_capacity = 1.0
        adopt(w, [commission("food_distribution", 100.0)])
        policy.monthly(w)
        effects.step(w)
        self.assertLessEqual(abs(effects.modifiers(w, "hunger").get("*", 0.0)), 0.02 + 1e-9)

    def test_each_mandate_reaches_its_own_channel(self):
        corruption = policy_world(13)
        corruption.institutions["corruption"] = {"treasury": 0.02, "interior": 0.01,
                                                 "army": 0.10, "navy": 0.03, "head": 0.0}
        adopt(corruption, [commission("anti_corruption", 5.0)])
        policy.monthly(corruption)
        entry = next(e for e in corruption.institutions.get("effects") or []
                     if e.get("channel") == "corruption")
        self.assertEqual(entry["target"], "army", "the body works where corruption is worst")
        self.assertLess(float(entry["value"]), 0)

        reconstruction = policy_world(13)
        reconstruction.region("kessel").damage = 0.20
        reconstruction.region("aster").damage = 0.05
        adopt(reconstruction, [commission("reconstruction", 5.0)])
        policy.monthly(reconstruction)
        damage = next(e for e in reconstruction.institutions.get("effects") or []
                      if e.get("channel") == "damage")
        self.assertEqual(damage["target"], "kessel")
        self.assertLess(float(damage["value"]), 0)

        minority = policy_world(13)
        adopt(minority, [commission("minority_liaison", 5.0)])
        policy.monthly(minority)
        reactions = [e for e in minority.institutions.get("public_reactions") or []
                     if e.get("bus") and e.get("kind") == "grievance"]
        self.assertTrue(reactions)
        self.assertEqual(reactions[0]["where"], "ident:vell")
        self.assertLess(float(reactions[0]["value"]), 0)

        statistics = policy_world(13)
        statistics.econ.admin_capacity = 0.5
        adopt(statistics, [commission("statistics", 5.0)])
        policy.monthly(statistics)
        entry = next(e for e in statistics.institutions.get("effects") or []
                     if e.get("channel") == "admin_capacity")
        self.assertEqual(entry["target"], "*")
        self.assertGreater(float(entry["value"]), 0)
        effects.step(statistics)
        self.assertGreater(statistics.econ.admin_capacity, 0.5)


class ScheduleAndConditionTests(unittest.TestCase):
    """start_in and months are the schedule; the condition is tested at the start of each month."""

    def test_start_in_delays_the_item_and_the_months_bound_its_run(self):
        w = policy_world(14)
        adopt(w, [set_lever("rationing", True, start_in=2, months=1)])
        engine.step(w)
        self.assertFalse(w.policy.rationing)
        self.assertEqual(entries(record_of(w), "in_force", "set_lever")[0]["status"], "scheduled")
        engine.step(w)
        self.assertFalse(w.policy.rationing)
        engine.step(w)
        self.assertTrue(w.policy.rationing, "the item starts in its start_in month")
        engine.step(w)
        self.assertFalse(w.policy.rationing, "and runs for exactly its months")

    def test_a_false_condition_blocks_a_spending_item_and_no_money_is_paid(self):
        plain, w = policy_world(15), policy_world(15)
        adopt(w, [transfer("ident:vell", 5.0, months=2,
                           condition={"metric": "food_ratio", "operator": ">=", "value": 1.5})])
        engine.step(plain)
        engine.step(w)
        self.assertAlmostEqual(w.econ.gold, plain.econ.gold, delta=1.0,
                               msg="nothing is paid while the condition fails")
        paused = entries(record_of(w), "in_force", "transfer")
        self.assertEqual(paused[0]["status"], "paused")
        self.assertTrue(entries(record_of(w), "refused", "transfer") == []
                        or all(e["code"] != "POLICY_UNFUNDED" for e in entries(record_of(w), "refused", "transfer")))

    def test_an_item_ends_after_its_last_scheduled_month(self):
        w = policy_world(16)
        adopt(w, [transfer("ident:vell", 2.0, months=2)])
        engine.step(w)
        engine.step(w)
        engine.step(w)
        ended = entries(record_of(w), "ended", "transfer")
        self.assertTrue(ended)
        self.assertEqual(ended[0]["reason"], "its schedule ended")


class RecordTests(unittest.TestCase):
    """The month record's policies: in force, applied, ended and refused, with reasons."""

    def test_a_default_month_has_no_policies_key_and_no_policy_state(self):
        w = policy_world(17, harness="menu")
        engine.step(w)
        self.assertNotIn("policies", w.history[-1])
        self.assertNotIn("policies", w.institutions)
        self.assertNotIn("policy_record", w.institutions)

    def test_the_month_row_carries_every_section_the_policy_touched(self):
        w = policy_world(18)
        adopt(w, [set_lever("rationing", True, months=1)])
        engine.step(w)
        record = record_of(w)
        self.assertTrue(record)
        self.assertEqual(record["month"], 0)
        for section in ("in_force", "applied", "ended", "refused"):
            self.assertIn(section, record)
        self.assertEqual(entries(record, "applied", "set_lever")[0]["office"], "treasury")
        self.assertEqual(entries(record, "applied", "set_lever")[0]["item"]["lever"], "rationing")

    def test_a_refusal_is_in_words_with_a_registered_code(self):
        w = policy_world(19)
        w.econ.gold = 0.0
        adopt(w, [transfer("ident:vell", 5.0)])
        engine.step(w)
        refused = entries(record_of(w), "refused", "transfer")
        self.assertTrue(refused)
        self.assertTrue(errors.is_registered(refused[0]["code"]))
        self.assertTrue(refused[0]["reason"])
        self.assertNotIn(refused[0]["code"], refused[0]["reason"])


class SweepTests(unittest.TestCase):
    """A scripted 36-month sweep, seeds 1-6, using every instrument: no channel over its cap, inside the
    calibration envelope. The stand-ins are this test's own script; no model is called."""

    ROTATION = (
        [set_lever("rationing", True, months=3)],
        [transfer("ident:vell", 6.0, funding="reserves", months=2)],
        [public_works("kessel", 8.0, funding="borrowing", months=2)],
        [commission("food_distribution", 4.0, funding="cut:military", months=2)],
        [set_lever("police", 0.02, months=3)],
        [transfer("class:farmers", 3.0, funding="cut:welfare", months=2)],
        [commission("anti_corruption", 3.0, funding="reserves", months=2)],
        [public_works("dorran", 5.0, funding="cut:police", months=2,
                      condition={"metric": "unemployment", "operator": ">=", "value": 0.02})],
        [transfer("*", 4.0, funding="borrowing", months=2)],
        [commission("statistics", 3.0, funding="reserves", months=2)],
        [set_lever("rationing", False, months=2)],
        [commission("minority_liaison", 3.0, funding="cut:health_edu", months=2)],
    )

    def test_six_seeds_use_every_instrument_within_caps_and_the_calibration_envelope(self):
        instruments_seen = set()
        for seed in range(1, 7):
            w = policy_world(seed)
            for month in range(36):
                items = self.ROTATION[month % len(self.ROTATION)]
                adopt(w, [dict(entry) for entry in items], proposer=("ABCDE"[month % 5]), mid=f"S-{seed}-{month}")
                engine.step(w)
                record = record_of(w)
                for applied in entries(record, "applied"):
                    instruments_seen.add(applied["instrument"])
            self.assertEqual(w.month, 36)
            for row in w.history:
                used = {}
                for rec in row.get("effects_applied") or []:
                    key = (rec["channel"], rec["target"])
                    used[key] = used.get(key, 0.0) + abs(float(rec["value"]))
                for (channel, target), total in used.items():
                    cap = effects.CHANNELS[channel]["month_cap"]
                    self.assertLessEqual(round(total, 5), cap + 1e-6,
                                         f"seed {seed} month {row['month']}: {channel} at {target} = {total}")
            checks = calibration.evaluate(w)
            failures = {name: check for name, check in checks.items() if check.get("ok") is False}
            self.assertEqual(failures, {}, f"seed {seed} left the calibration envelope: {failures}")
        self.assertEqual(instruments_seen, {"set_lever", "transfer", "public_works", "commission"})


class CompatibilityAndDeterminismTests(unittest.TestCase):
    """An old checkpoint reads as no policies, and two identical policy runs are identical."""

    def test_an_old_checkpoint_without_policy_state_loads_and_changes_nothing(self):
        w = new_world(20)
        engine.step(w)
        data = w.to_dict()
        for key in ("policies", "policy_record"):
            data["institutions"].pop(key, None)
        loaded = World.from_dict(data)
        self.assertEqual(policy.active(loaded), [])
        policy.monthly(loaded)
        self.assertNotIn("policies", loaded.institutions)
        self.assertNotIn("policy_record", loaded.institutions)

    def test_a_checkpoint_with_a_live_hold_round_trips_and_still_restores(self):
        w = policy_world(22)
        adopt(w, [set_lever("rationing", True, months=3)])
        engine.step(w)
        self.assertTrue(w.policy.rationing)
        loaded = World.from_dict(w.to_dict())
        self.assertEqual(len(policy.active(loaded)), 1)
        engine.step(loaded)
        engine.step(loaded)
        engine.step(loaded)
        self.assertFalse(loaded.policy.rationing, "the restored value survives the checkpoint")

    def test_two_identical_runs_with_every_instrument_match_month_by_month(self):
        def run():
            w = policy_world(21)
            script = [
                [set_lever("welfare", 0.05, months=2)],
                [transfer("ident:vell", 4.0, funding="reserves", months=1)],
                [public_works("kessel", 6.0, funding="borrowing", months=2)],
                [commission("food_distribution", 3.0, funding="cut:military", months=2)],
                [transfer("class:farmers", 2.0, funding="cut:welfare", months=2)],
                [commission("anti_corruption", 2.0, funding="reserves", months=1)],
            ]
            for month in range(6):
                adopt(w, [dict(entry) for entry in script[month]], mid=f"D-{month}")
                engine.step(w)
            return w
        first, second = run(), run()
        self.assertEqual(first.history, second.history)
        self.assertEqual(first.policy, second.policy)
        self.assertEqual(first.econ.gold, second.econ.gold)


if __name__ == "__main__":
    unittest.main()
