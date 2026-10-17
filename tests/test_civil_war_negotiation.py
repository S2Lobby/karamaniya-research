"""Civil war (Wave C, C4): ceasefire, settlement terms, and the war's ends.

The rules come from notes/CIVIL_WAR-design.md section 6-7 and the lead's decisions:

- either side may offer a ceasefire; it holds when both sides accept it, and an attack breaks it
  and is recorded as a breach;
- settlement terms come from a closed list: amnesty, power sharing (named offices divided),
  regional autonomy (a named region), integration or disarmament of forces, and an election date,
  which may never fall before Month 36;
- when both sides accept the same terms in the same month, the settlement applies and the run goes
  on;
- victory: one side holds the capital and the other's armed force is below 15% of its pre-war
  strength; the run goes on, and on a rebel victory the rebels take the offices by faction rank;
- partition: six consecutive months of stalemate and a ceasefire both accept, which ends the run
  with `partitioned`;
- collapse: no faction holds the capital, which ends the run with `no_government`;
- an ended run gets no second outcome, and `civil_war = "off"` changes nothing.

C2's `civil_war_combat` is not in this worktree's base. The ceasefire tests assert the state flag
C2 reads (`{"active": True, "broken": False}`) and, when the module is present, call its
`ceasefire_active`/`combat` too; if it is absent the flag itself is the integration contract left
to the lead.
"""
import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import civil_war  # noqa: E402
from karamaniya.world import ARMED_OFFICES, OFFICES, World, new_world  # noqa: E402

try:  # C2 is a separate workstream; the base may not carry it yet.
    from karamaniya import civil_war_combat  # noqa: E402
except ImportError:  # pragma: no cover - the integration note in the report covers this branch
    civil_war_combat = None


def world(seed: int = 11, option: str = "on", month: int = 1) -> World:
    w = new_world(seed, 36, civil_war_option=option)
    w.month = month
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def war_world(seed: int = 11, month: int = 1) -> World:
    """A running war: A (head) and D (army) are the rebels, B, C and E the government."""
    w = world(seed=seed, month=month)
    civil_war.start(w, "failed_coup", plotters=["D"], stances={"A": "join"})
    return w


def state(w: World) -> dict:
    return civil_war.state(w)


def scale_rebel_strength(w: World, factor: float) -> None:
    """Scale every rebel service share so the faction's strength is `factor` of its pre-war one."""
    for office in ARMED_OFFICES:
        entry = state(w)["factions"]["rebels"]["forces"][office]
        entry["share"] = round(entry["share"] * factor, 6)
        entry["size"] = round(entry["size"] * factor, 1)


def scale_government_strength(w: World, factor: float) -> None:
    for office in ARMED_OFFICES:
        entry = state(w)["factions"]["government"]["forces"][office]
        entry["share"] = round(entry["share"] * factor, 6)
        entry["size"] = round(entry["size"] * factor, 1)


def settle(w: World, terms: dict, side: str = "government") -> dict:
    offered = civil_war.offer(w, side, terms)
    assert offered["ok"], offered
    other = "rebels" if side == "government" else "government"
    return civil_war.respond(w, other, offer_id=offered["offer"]["id"], accept=True)


class Ceasefire(unittest.TestCase):
    def test_one_sided_offer_does_not_hold(self):
        w = war_world()
        result = civil_war.ceasefire(w, "government")
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "offered")
        self.assertFalse(civil_war.ceasefire_active(w))
        self.assertFalse(state(w)["ceasefire"]["active"])
        # An offer alone stops no combat: C2 reads the flag, and it is not set.
        self.assertEqual(state(w)["ceasefire"]["offers"][-1]["side"], "government")

    def test_both_sides_accepting_holds(self):
        w = war_world()
        civil_war.ceasefire(w, "government")
        result = civil_war.ceasefire(w, "rebels")
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "accepted")
        self.assertTrue(civil_war.ceasefire_active(w))
        self.assertEqual(state(w)["ceasefire"]["active"], True)
        self.assertEqual(state(w)["ceasefire"]["broken"], False)
        self.assertEqual(state(w)["ceasefire"]["accepted_month"], w.month)
        self.assertTrue(any(o.get("status") == "accepted"
                            for o in state(w)["ceasefire"]["offers"]))

    def test_the_flag_is_the_shape_c2_reads(self):
        w = war_world()
        civil_war.ceasefire(w, "government")
        civil_war.ceasefire(w, "rebels")
        flag = state(w)["ceasefire"]
        self.assertIsInstance(flag, dict)
        self.assertIs(flag["active"], True)
        self.assertIs(flag["broken"], False)
        if civil_war_combat is not None:
            self.assertTrue(civil_war_combat.ceasefire_active(state(w)))
            record = civil_war_combat.combat(w)
            self.assertTrue(record["ceasefire"])
            self.assertEqual(record["control_changes"], [])

    def test_an_attack_breaks_it_and_is_recorded(self):
        w = war_world()
        civil_war.ceasefire(w, "government")
        civil_war.ceasefire(w, "rebels")
        result = civil_war.breach(w, "rebels", "attack")
        self.assertTrue(result["ok"])
        self.assertFalse(civil_war.ceasefire_active(w))
        flag = state(w)["ceasefire"]
        self.assertIs(flag["active"], False)
        self.assertIs(flag["broken"], True)
        self.assertEqual(flag["breach"]["side"], "rebels")
        self.assertEqual(flag["breach"]["month"], w.month)
        self.assertEqual(state(w)["breaches"][-1]["reason"], "attack")
        if civil_war_combat is not None:
            self.assertFalse(civil_war_combat.ceasefire_active(state(w)))

    def test_an_attack_order_breaks_it_at_the_month_check(self):
        w = war_world()
        civil_war.ceasefire(w, "government")
        civil_war.ceasefire(w, "rebels")
        state(w)["orders"] = {"rebels": {"kessel": "attack"},
                              "government": {"kessel": "defend"}}
        outcome = civil_war.check_end(w)
        self.assertIsNone(outcome)
        self.assertFalse(civil_war.ceasefire_active(w))
        self.assertEqual(state(w)["ceasefire"]["breach"]["side"], "rebels")
        self.assertEqual(state(w)["breaches"][-1]["reason"], "attack")
        self.assertEqual(state(w)["breaches"][-1]["order"], "attack")

    def test_the_order_breach_helper_is_the_one_c3_calls_before_combat(self):
        w = war_world()
        civil_war.ceasefire(w, "government")
        civil_war.ceasefire(w, "rebels")
        state(w)["orders"] = {"government": {"aster": "attack"}}
        result = civil_war.orders_break_ceasefire(w)
        self.assertTrue(result["ok"])
        self.assertFalse(civil_war.ceasefire_active(w))
        self.assertEqual(state(w)["breaches"][-1]["side"], "government")
        # A second call finds no ceasefire in force.
        self.assertIsNone(civil_war.orders_break_ceasefire(w))

    def test_a_refused_offer_is_recorded_and_does_not_hold(self):
        w = war_world()
        civil_war.ceasefire(w, "government")
        result = civil_war.refuse_ceasefire(w, "rebels", "no talks")
        self.assertTrue(result["ok"])
        self.assertFalse(civil_war.ceasefire_active(w))
        offers = state(w)["ceasefire"]["offers"]
        self.assertEqual(offers[-1]["side"], "government")
        self.assertEqual(offers[-1]["status"], "refused")
        self.assertEqual(offers[-1]["reason"], "no talks")

    def test_an_explicit_acceptance_activates_an_offer(self):
        w = war_world()
        civil_war.ceasefire(w, "government")
        result = civil_war.ceasefire(w, "rebels", accept=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "accepted")
        self.assertTrue(civil_war.ceasefire_active(w))

    def test_accepting_without_an_offer_is_refused(self):
        w = war_world()
        result = civil_war.ceasefire(w, "rebels", accept=True)
        self.assertFalse(result["ok"])
        self.assertTrue(result["problems"])
        self.assertFalse(civil_war.ceasefire_active(w))


class SettlementOffers(unittest.TestCase):
    def test_an_accepted_offer_in_the_same_month_settles(self):
        w = war_world()
        result = settle(w, {"amnesty": True})
        self.assertTrue(result["ok"])
        self.assertTrue(result["settled"])
        self.assertEqual(state(w)["outcome"]["type"], "settled")
        self.assertEqual(w.policy.amnesty, "release")
        # The run goes on: the settlement is a war outcome, not a run outcome.
        self.assertEqual(w.outcome, {})
        self.assertFalse(w.ended())
        self.assertEqual(state(w)["settlement"]["terms"], {"amnesty": True})
        self.assertEqual(state(w)["offers"][0]["status"], "settled")
        self.assertEqual(state(w)["offers"][0]["responses"][-1]["side"], "rebels")
        self.assertTrue(state(w)["offers"][0]["responses"][-1]["accept"])

    def test_identical_offers_from_both_sides_in_the_same_month_settle(self):
        w = war_world()
        terms = {"amnesty": True, "regional_autonomy": "kessel"}
        first = civil_war.offer(w, "government", terms)
        self.assertTrue(first["ok"])
        self.assertFalse(first["settled"])
        second = civil_war.offer(w, "rebels", terms)
        self.assertTrue(second["ok"])
        self.assertTrue(second["settled"])
        self.assertEqual(state(w)["outcome"]["type"], "settled")
        self.assertEqual(w.const.kessel_status, "devolved")
        self.assertEqual(w.policy.amnesty, "release")

    def test_a_refusal_is_recorded_and_settles_nothing(self):
        w = war_world()
        offered = civil_war.offer(w, "government", {"amnesty": True})
        result = civil_war.respond(w, "rebels", offer_id=offered["offer"]["id"], accept=False)
        self.assertTrue(result["ok"])
        self.assertFalse(result["settled"])
        self.assertIsNone(state(w)["outcome"])
        self.assertEqual(state(w)["offers"][0]["status"], "refused")
        self.assertFalse(state(w)["offers"][0]["responses"][-1]["accept"])
        self.assertEqual(w.policy.amnesty, "none")

    def test_the_offer_must_come_from_the_other_side(self):
        w = war_world()
        offered = civil_war.offer(w, "government", {"amnesty": True})
        result = civil_war.respond(w, "government", offer_id=offered["offer"]["id"], accept=True)
        self.assertFalse(result["ok"])
        self.assertIsNone(state(w)["outcome"])

    def test_an_offer_expires_at_the_month_check(self):
        w = war_world(month=3)
        offered = civil_war.offer(w, "government", {"amnesty": True})
        self.assertTrue(offered["ok"])
        w.month = 4
        civil_war.check_end(w)
        self.assertEqual(state(w)["offers"][0]["status"], "expired")
        result = civil_war.respond(w, "rebels", offer_id=offered["offer"]["id"], accept=True)
        self.assertFalse(result["ok"])
        self.assertIsNone(state(w)["outcome"])

    def test_accepting_a_stale_offer_does_not_settle(self):
        w = war_world(month=3)
        offered = civil_war.offer(w, "government", {"amnesty": True})
        w.month = 4
        result = civil_war.respond(w, "rebels", offer_id=offered["offer"]["id"], accept=True)
        self.assertFalse(result["ok"])
        self.assertFalse(result["settled"])
        self.assertIsNone(state(w)["outcome"])
        self.assertEqual(state(w)["offers"][0]["status"], "expired")

    def test_responding_by_terms_finds_the_matching_offer(self):
        w = war_world()
        civil_war.offer(w, "government", {"amnesty": True})
        result = civil_war.respond(w, "rebels", terms={"amnesty": True}, accept=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["settled"])
        self.assertEqual(state(w)["outcome"]["type"], "settled")

    def test_unknown_terms_are_refused_in_words(self):
        w = war_world()
        before = json.dumps(state(w), sort_keys=True)
        for terms, needle in (
            ({"reparations": True}, "closed list"),
            ({"power_sharing": {"throne": "rebels"}}, "office"),
            ({"power_sharing": {"head": "royalists"}}, "side"),
            ({"regional_autonomy": "atlantis"}, "region"),
            ({"forces": "merge"}, "integrate"),
            ({"election_date": 35}, "Month 36"),
            ({"amnesty": True, "election_date": "soon"}, "election"),
            ({"amnesty": True, "regional_autonomy": "arven"}, None),
        ):
            with self.subTest(terms=terms):
                result = civil_war.offer(w, "government", terms)
                if needle is None:
                    # `arven` is a rival capital, not Karamaniya: refused.
                    self.assertFalse(result["ok"])
                    continue
                self.assertFalse(result["ok"], terms)
                self.assertTrue(any(needle.lower() in p.lower() for p in result["problems"]),
                                result["problems"])
        # Invalid offers are recorded too, and nothing was applied.
        self.assertEqual(state(w)["offers"][-1]["status"], "invalid")
        self.assertNotEqual(json.dumps(state(w), sort_keys=True), before)

    def test_an_empty_offer_is_refused(self):
        w = war_world()
        result = civil_war.offer(w, "government", {})
        self.assertFalse(result["ok"])
        self.assertTrue(result["problems"])

    def test_no_offers_after_the_war_has_ended(self):
        w = war_world()
        settle(w, {"amnesty": True})
        result = civil_war.offer(w, "government", {"amnesty": True})
        self.assertFalse(result["ok"])
        self.assertTrue(result["problems"])


class SettlementTerms(unittest.TestCase):
    def test_power_sharing_assigns_the_named_offices_by_faction_rank(self):
        w = war_world()
        result = settle(w, {"power_sharing": {"head": "rebels", "treasury": "government"}})
        self.assertTrue(result["settled"])
        # A holds the head office and is the highest-ranked rebel, so the head stays with the rebels.
        self.assertIn(w.const.offices["head"], ("A", "D"))
        self.assertEqual(w.const.offices["head"], "A")
        # B is the highest-ranked government member after A and D left, so the treasury stays there.
        self.assertIn(w.const.offices["treasury"], ("B", "C", "E"))
        self.assertEqual(w.const.offices["treasury"], "B")
        assignments = state(w)["settlement"]["assigned_offices"]
        self.assertEqual(assignments["head"], "A")
        self.assertEqual(assignments["treasury"], "B")

    def test_regional_autonomy_uses_the_engine_status_for_kessel_and_the_highlands(self):
        w = war_world()
        result = settle(w, {"regional_autonomy": "kessel"})
        self.assertTrue(result["settled"])
        self.assertEqual(w.const.kessel_status, "devolved")

    def test_regional_autonomy_for_another_region_is_recorded(self):
        w = war_world()
        result = settle(w, {"regional_autonomy": "dorran"})
        self.assertTrue(result["settled"])
        grants = w.institutions["civil_war_settlement"]["autonomy"]
        self.assertIn("dorran", grants)
        self.assertNotIn("dorran_status", vars(w.const))

    def test_integration_moves_the_rebel_share_to_the_government(self):
        w = war_world()
        state(w)["factions"]["rebels"]["forces"]["army"]["share"] = 0.25
        result = settle(w, {"forces": "integrate"})
        self.assertTrue(result["settled"])
        forces = state(w)["forces"]
        for office in ARMED_OFFICES:
            self.assertAlmostEqual(forces[office]["government"], 1.0, places=6)
            self.assertAlmostEqual(forces[office]["rebels"], 0.0, places=6)
            self.assertAlmostEqual(forces[office]["neutral"], 0.0, places=6)

    def test_disarmament_takes_the_rebel_share_out_of_the_forces(self):
        w = war_world()
        state(w)["factions"]["rebels"]["forces"]["army"]["share"] = 0.25
        before = w.mil.army.size
        result = settle(w, {"forces": "disarm"})
        self.assertTrue(result["settled"])
        self.assertAlmostEqual(w.mil.army.size, before * 0.75, places=1)
        forces = state(w)["forces"]
        self.assertAlmostEqual(forces["army"]["rebels"], 0.0, places=6)

    def test_an_election_date_is_stored_one_based(self):
        w = war_world()
        w.const.elected = True
        w.const.handover_month = w.month
        result = settle(w, {"election_date": 40})
        self.assertTrue(result["settled"])
        self.assertEqual(w.const.election_month, 39)
        self.assertFalse(w.const.elected)
        self.assertEqual(w.const.handover_month, -1)

    def test_an_election_before_month_36_is_refused(self):
        w = war_world()
        result = civil_war.offer(w, "rebels", {"election_date": 35})
        self.assertFalse(result["ok"])
        self.assertTrue(any("Month 36" in p for p in result["problems"]))
        self.assertEqual(w.const.election_month, w.const.charter_election_month)

    def test_all_terms_together(self):
        w = war_world()
        result = settle(w, {
            "amnesty": True,
            "power_sharing": {"head": "rebels"},
            "regional_autonomy": "highlands",
            "forces": "integrate",
            "election_date": 36,
        })
        self.assertTrue(result["settled"])
        self.assertEqual(w.policy.amnesty, "release")
        self.assertEqual(w.const.highlands_status, "devolved")
        self.assertEqual(w.const.election_month, 35)
        self.assertEqual(state(w)["settlement"]["terms"]["forces"], "integrate")
        self.assertEqual(state(w)["outcome"]["type"], "settled")


class Victory(unittest.TestCase):
    def test_a_government_victory_needs_the_capital_and_a_broken_rebel_force(self):
        w = war_world()
        self.assertEqual(w.region("aster").controller, "karamaniya")
        prewar = civil_war.prewar_strength(w, "rebels")
        scale_rebel_strength(w, 0.151)
        # Just above 15% is not below the threshold.
        self.assertGreater(civil_war.strength(w, "rebels"), 0.15 * prewar)
        self.assertIsNone(civil_war.check_end(w))
        self.assertIsNone(state(w)["outcome"])
        scale_rebel_strength(w, 0.98)  # ~14.8% of the pre-war strength
        self.assertLess(civil_war.strength(w, "rebels"), 0.15 * prewar)
        outcome = civil_war.check_end(w)
        self.assertEqual(outcome["type"], "civil_war_won_by_government")
        self.assertEqual(state(w)["outcome"]["type"], "civil_war_won_by_government")
        # The run continues: no run outcome, and the offices are unchanged.
        self.assertEqual(w.outcome, {})
        self.assertFalse(w.ended())
        self.assertEqual(w.const.offices["head"], "A")

    def test_a_rebel_victory_makes_the_rebels_the_government_and_the_run_goes_on(self):
        w = war_world()
        w.region("aster").controller = "rebels"
        prewar = civil_war.prewar_strength(w, "government")
        scale_government_strength(w, 0.14)
        self.assertLess(civil_war.strength(w, "government"), 0.15 * prewar)
        outcome = civil_war.check_end(w)
        self.assertEqual(outcome["type"], "civil_war_won_by_rebels")
        self.assertEqual(state(w)["outcome"]["type"], "civil_war_won_by_rebels")
        self.assertEqual(w.outcome, {})
        self.assertFalse(w.ended())
        # Offices are assigned by faction rank: A (the rebel leader, formerly head) keeps the head,
        # D (the army) takes the treasury, and the rest are left vacant for the usual appointments.
        self.assertEqual(w.const.offices["head"], "A")
        self.assertEqual(w.const.offices["treasury"], "D")
        self.assertIsNone(w.const.offices["interior"])
        self.assertIsNone(w.const.offices["army"])
        self.assertIsNone(w.const.offices["navy"])
        for office in OFFICES:
            holder = w.const.offices[office]
            if holder is not None:
                self.assertIn(holder, state(w)["factions"]["rebels"]["members"])

    def test_a_side_that_does_not_hold_the_capital_does_not_win(self):
        w = war_world()
        w.region("aster").controller = "rebels"
        scale_rebel_strength(w, 0.0)  # the rebels are broken but the government lacks the capital
        civil_war.check_end(w)
        self.assertIsNone(state(w)["outcome"])


class PartitionAndCollapse(unittest.TestCase):
    def test_six_months_of_stalemate_and_a_ceasefire_partition_the_country(self):
        w = war_world(month=1)
        civil_war.ceasefire(w, "government")
        civil_war.ceasefire(w, "rebels")
        for month in range(1, 6):
            w.month = month
            self.assertIsNone(civil_war.check_end(w))
        self.assertEqual(state(w)["stalemate"]["months"], 5)
        w.month = 6
        outcome = civil_war.check_end(w)
        self.assertEqual(outcome["type"], "partitioned")
        self.assertEqual(state(w)["outcome"]["type"], "partitioned")
        self.assertEqual(w.outcome["type"], "partitioned")
        self.assertTrue(w.ended())
        self.assertEqual(w.outcome["month"], 6)

    def test_stalemate_without_a_ceasefire_does_not_partition(self):
        w = war_world(month=1)
        for month in range(1, 8):
            w.month = month
            civil_war.check_end(w)
        self.assertIsNone(state(w)["outcome"])
        self.assertEqual(w.outcome, {})

    def test_a_front_that_moves_resets_the_stalemate(self):
        w = war_world(month=1)
        civil_war.ceasefire(w, "government")
        civil_war.ceasefire(w, "rebels")
        for month in range(1, 4):
            w.month = month
            civil_war.check_end(w)
        self.assertEqual(state(w)["stalemate"]["months"], 3)
        w.region("kessel").controller = "rebels"
        w.month = 4
        civil_war.check_end(w)
        self.assertEqual(state(w)["stalemate"]["months"], 1)
        self.assertIsNone(state(w)["outcome"])

    def test_c2s_control_change_record_resets_the_stalemate(self):
        w = war_world(month=1)
        civil_war.ceasefire(w, "government")
        civil_war.ceasefire(w, "rebels")
        for month in range(1, 4):
            w.month = month
            civil_war.check_end(w)
        self.assertEqual(state(w)["stalemate"]["months"], 3)
        state(w)["last_combat"] = {"month": 4,
                                   "control_changes": [{"region": "kessel"}]}
        w.month = 4
        civil_war.check_end(w)
        self.assertEqual(state(w)["stalemate"]["months"], 1)
        self.assertIsNone(state(w)["outcome"])

    def test_no_faction_in_the_capital_is_no_government(self):
        w = war_world()
        w.region("aster").controller = "union"
        outcome = civil_war.check_end(w)
        self.assertEqual(outcome["type"], "no_government")
        self.assertEqual(state(w)["outcome"]["type"], "no_government")
        self.assertEqual(w.outcome["type"], "no_government")
        self.assertTrue(w.ended())

    def test_an_ended_run_gets_no_second_outcome(self):
        w = war_world()
        w.region("aster").controller = "union"
        first = civil_war.check_end(w)
        w.region("aster").controller = "rebels"
        second = civil_war.check_end(w)
        self.assertEqual(first["type"], "no_government")
        self.assertEqual(second["type"], "no_government")
        self.assertEqual(w.outcome["type"], "no_government")

    def test_an_outcome_set_elsewhere_is_not_overwritten(self):
        w = war_world()
        w.outcome = {"type": "survived", "month": 1, "text": "the engine ended the run"}
        w.region("aster").controller = "union"
        self.assertIsNone(civil_war.check_end(w))
        self.assertEqual(w.outcome["type"], "survived")
        self.assertIsNone(state(w)["outcome"])


class OffAndCheckpoints(unittest.TestCase):
    def test_the_off_arm_never_reads_or_writes_a_war(self):
        w = world(option="off")
        before = json.dumps(w.to_dict(), sort_keys=True)
        self.assertFalse(civil_war.ceasefire(w, "government")["ok"])
        self.assertFalse(civil_war.offer(w, "government", {"amnesty": True})["ok"])
        self.assertFalse(civil_war.respond(w, "rebels", offer_id=1, accept=True)["ok"])
        self.assertFalse(civil_war.breach(w, "rebels")["ok"])
        self.assertIsNone(civil_war.check_end(w))
        self.assertEqual(json.dumps(w.to_dict(), sort_keys=True), before)
        self.assertEqual(w.outcome, {})

    def test_an_off_run_does_not_end_on_a_lost_capital(self):
        w = world(option="off")
        w.region("aster").controller = "union"
        self.assertIsNone(civil_war.check_end(w))
        self.assertEqual(w.outcome, {})

    def test_an_old_checkpoint_is_unchanged(self):
        w = new_world(3, 36)
        data = w.to_dict()
        restored = World.from_dict(data)
        before = json.dumps(restored.to_dict(), sort_keys=True)
        self.assertIsNone(civil_war.check_end(restored))
        civil_war.ceasefire(restored, "government")
        civil_war.offer(restored, "rebels", {"amnesty": True})
        self.assertEqual(json.dumps(restored.to_dict(), sort_keys=True), before)
        self.assertIsNone(restored.civil_war)
        self.assertEqual(restored.civil_war_option, "off")

    def test_an_on_checkpoint_carries_the_negotiation_state(self):
        w = war_world()
        civil_war.ceasefire(w, "government")
        civil_war.ceasefire(w, "rebels")
        civil_war.offer(w, "government", {"amnesty": True})
        data = w.to_dict()
        restored = World.from_dict(copy.deepcopy(data))
        self.assertEqual(restored.civil_war, data["civil_war"])
        self.assertTrue(civil_war.ceasefire_active(restored))
        offered = civil_war.respond(restored, "rebels", offer_id=data["civil_war"]["offers"][0]["id"],
                                    accept=True)
        self.assertTrue(offered["settled"])
        self.assertEqual(restored.policy.amnesty, "release")

    def test_a_c1_state_without_the_c4_keys_still_works(self):
        """A checkpoint written between C1 and C4 has no C4 keys; C4 fills them on first use."""
        w = war_world()
        for key in ("prewar_strength", "stalemate", "breaches", "next_offer_id", "settlement"):
            state(w).pop(key, None)
        state(w)["offers"] = []
        state(w)["ceasefire"] = False
        self.assertIsNone(civil_war.check_end(w))
        self.assertIn("prewar_strength", state(w))
        # The fallback pre-war strength is C1's per-faction sizes.
        self.assertGreater(civil_war.prewar_strength(w, "government"), 0.0)
        result = civil_war.offer(w, "government", {"amnesty": True})
        self.assertTrue(result["ok"])
        settled = civil_war.respond(w, "rebels", offer_id=result["offer"]["id"], accept=True)
        self.assertTrue(settled["settled"])
        self.assertEqual(state(w)["outcome"]["type"], "settled")


if __name__ == "__main__":
    unittest.main()
