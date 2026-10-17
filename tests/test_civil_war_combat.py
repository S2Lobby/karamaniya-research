"""Civil-war combat: the force-ratio model, territory, losses, refugees and determinism.

These tests pin the C2 contract. The faction state is the one C1 builds in `w.civil_war`;
`combat(w, rng=None)` is the only entry point the engine, C1, C3, C4 and C5 need.
"""
import copy
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import civil_war_combat as cwc  # noqa: E402
from karamaniya.world import new_world, rng_for  # noqa: E402


def world(seed: int = 5, rebel_region: str = "kessel"):
    """A small but complete civil-war state: the rebels hold one region, the government the rest."""
    w = new_world(seed, 36)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    r = w.region(rebel_region)
    r.controller = "rebels"
    r.rebels = 3000.0
    w.civil_war = {
        "since": 1,
        "cause": "failed_coup",
        "factions": {
            "government": {"members": ["A", "B", "C"],
                           "territory": [x.id for x in w.k_regions() if x.id != rebel_region]},
            "rebels": {"members": ["D"], "territory": [rebel_region]},
        },
        "forces": {
            "army": {"government": 0.55, "rebels": 0.30, "neutral": 0.15},
            "navy": {"government": 0.50, "rebels": 0.30, "neutral": 0.20},
            "interior": {"government": 0.55, "rebels": 0.25, "neutral": 0.20},
        },
        "contested": [rebel_region],
    }
    return w


def dominant_government(w):
    """The government holds almost all of every force; the rebels a token."""
    w.civil_war["forces"] = {
        "army": {"government": 0.97, "rebels": 0.02, "neutral": 0.01},
        "navy": {"government": 0.97, "rebels": 0.02, "neutral": 0.01},
        "interior": {"government": 0.97, "rebels": 0.02, "neutral": 0.01},
    }
    return w


def fingerprint(w):
    """Everything combat is allowed to touch, so 'changes nothing' is checkable exactly."""
    state = copy.deepcopy(getattr(w, "civil_war", None))
    if isinstance(state, dict):
        state.pop("last_combat", None)   # the record itself, written on every call
    return {
        "month": w.month,
        "controllers": tuple(r.controller for r in w.regions),
        "damage": tuple(round(r.damage, 9) for r in w.regions),
        "rebels": tuple(round(r.rebels, 9) for r in w.regions),
        "army": round(w.mil.army.size, 9),
        "navy": round(w.mil.navy.size, 9),
        "police": round(w.mil.police.size, 9),
        "pops": tuple((p.region, p.cls, p.ident, round(p.size, 6)) for p in w.pops),
        "counters": dict(w.counters),
        "events": tuple((e["kind"], e["text"]) for e in w.events),
        "state": state,
    }


class NoWarIsInert(unittest.TestCase):
    def test_none_changes_nothing(self):
        w = new_world(5, 36)
        w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
        w.civil_war = None
        before = fingerprint(w)
        self.assertIsNone(cwc.combat(w))
        self.assertEqual(before, fingerprint(w))

    def test_absent_state_changes_nothing(self):
        w = new_world(5, 36)
        before = fingerprint(w)
        self.assertIsNone(cwc.combat(w))
        self.assertEqual(before, fingerprint(w))
        self.assertFalse(hasattr(w, "civil_war") and w.civil_war)

    def test_empty_state_changes_nothing(self):
        w = new_world(5, 36)
        w.civil_war = {}
        before = fingerprint(w)
        self.assertIsNone(cwc.combat(w))
        self.assertEqual(before, fingerprint(w))

    def test_a_finished_war_fights_no_more(self):
        w = world()
        w.civil_war["outcome"] = {"type": "partitioned", "month": 5}
        before = fingerprint(w)
        self.assertIsNone(cwc.combat(w))
        self.assertEqual(before, fingerprint(w))

    def test_an_ended_run_fights_no_more(self):
        w = world()
        w.outcome = {"type": "survived", "month": 5}
        before = fingerprint(w)
        self.assertIsNone(cwc.combat(w))
        self.assertEqual(before, fingerprint(w))


class TheModel(unittest.TestCase):
    def test_combat_follows_the_model(self):
        w = world()
        before_pop = sum(p.size for p in w.pops if p.region == "kessel")
        rec = cwc.combat(w, rng=random.Random(7))
        front = rec["fronts"]["kessel"]
        self.assertEqual(front["attacker"], "government")   # rebels hold Kessel, so the government attacks
        self.assertEqual(front["defender"], "rebels")
        self.assertGreater(front["ratio"], 0.0)
        self.assertGreaterEqual(rec["losses"]["government"], 0.0)
        self.assertGreaterEqual(rec["losses"]["rebels"], 0.0)
        self.assertGreater(rec["losses"]["government"] + rec["losses"]["rebels"], 0.0)
        self.assertGreater(rec["losses"]["civilians"], 0.0)
        self.assertGreater(w.region("kessel").damage, 0.0)
        self.assertLessEqual(w.region("kessel").damage, 1.0)
        # Civilian deaths are 0.03% of the contested region's population a month.
        self.assertAlmostEqual(rec["losses"]["civilians"], 0.0003 * before_pop, delta=1.0)

    def test_loss_coefficients_are_in_the_agreed_band(self):
        w = world()
        for shares in ("army", "navy", "interior"):
            w.civil_war["forces"][shares] = {"government": 0.45, "rebels": 0.45, "neutral": 0.10}
        rec = cwc.combat(w, rng=random.Random(11))
        front = rec["fronts"]["kessel"]
        intensity = cwc.intensity_of(w.civil_war)
        for side, enemy_factor in (("government", 1.0 / front["ratio"]),
                                   ("rebels", front["ratio"])):
            engaged = front["engaged_equivalent"][side]
            lost = front["losses_equivalent"][side]
            coefficient = lost / (engaged * min(cwc.RATIO_CAP, enemy_factor) ** 0.5 * intensity)
            self.assertGreaterEqual(coefficient, cwc.SOLDIER_LOSS_MIN - 1e-9)
            self.assertLessEqual(coefficient, cwc.SOLDIER_LOSS_MAX + 1e-9)

    def test_damage_is_in_the_agreed_band(self):
        w = world()
        rec = cwc.combat(w, rng=random.Random(3))
        delta = rec["fronts"]["kessel"]["damage"]
        self.assertGreaterEqual(delta, cwc.DAMAGE_MIN - 1e-9)
        self.assertLessEqual(delta, cwc.DAMAGE_MAX + 1e-9)

    def test_losses_are_bounded_by_the_engaged_force(self):
        w = world()
        army_before = w.mil.army.size
        rec = cwc.combat(w, rng=random.Random(5))
        front = rec["fronts"]["kessel"]
        for side in ("government", "rebels"):
            self.assertLessEqual(front["losses_equivalent"][side],
                                 0.4 * front["engaged_equivalent"][side] + 1e-6)
        self.assertLessEqual(w.mil.army.size, army_before)
        self.assertGreaterEqual(w.mil.army.size, 0.0)

    def test_losses_reduce_the_force_and_both_sides_shares(self):
        w = world()
        army_before = w.mil.army.size
        government_share = w.civil_war["forces"]["army"]["government"]
        rec = cwc.combat(w, rng=random.Random(5))
        army_losses = (rec["losses_by_office"]["army"]["government"]
                       + rec["losses_by_office"]["army"]["rebels"])
        self.assertLess(w.mil.army.size, army_before)
        self.assertAlmostEqual(w.mil.army.size, army_before - army_losses, places=2)
        self.assertNotEqual(w.civil_war["forces"]["army"]["government"], government_share)
        self.assertAlmostEqual(sum(w.civil_war["forces"]["army"].values()), 1.0, places=9)

    def test_the_record_is_stored_for_the_month(self):
        w = world()
        rec = cwc.combat(w)
        self.assertEqual(w.civil_war["last_combat"], rec)
        self.assertEqual(rec["month"], w.month)

    def test_zero_intensity_pauses_the_fighting(self):
        w = world()
        w.civil_war["intensity"] = 0.0
        before_damage = w.region("kessel").damage
        rec = cwc.combat(w)
        self.assertEqual(rec["fronts"], {})
        self.assertEqual(w.region("kessel").damage, before_damage)
        self.assertEqual(rec["losses"]["civilians"], 0.0)
        self.assertIn("army", rec["defections"])

    def test_casualties_are_counted(self):
        w = world()
        cwc.combat(w, rng=random.Random(5))
        self.assertGreater(w.counters.get("civil_war_soldiers_killed", 0.0), 0.0)
        self.assertGreater(w.counters.get("civil_war_civilians_killed", 0.0), 0.0)
        self.assertGreater(w.counters.get("deaths_war_civilian", 0.0), 0.0)
        self.assertGreater(w.counters.get("soldiers_killed", 0.0), 0.0)


class Territory(unittest.TestCase):
    def test_a_dominant_government_takes_a_rebel_region(self):
        w = dominant_government(world())
        record = None
        for _ in range(8):
            record = cwc.combat(w)
            if w.region("kessel").controller == "karamaniya":
                break
            w.month += 1
        self.assertEqual(w.region("kessel").controller, "karamaniya")
        self.assertEqual(w.region("kessel").rebels, 0.0)
        self.assertNotIn("kessel", w.civil_war["contested"])
        self.assertIn("kessel", w.civil_war["factions"]["government"]["territory"])
        self.assertNotIn("kessel", w.civil_war["factions"]["rebels"]["territory"])
        self.assertTrue(any(c["region"] == "kessel" and c["to"] == "karamaniya"
                            for c in record["control_changes"]))
        self.assertGreaterEqual(record["fronts"]["kessel"]["progress"], 1.0)

    def test_a_dominant_rebel_side_takes_a_government_region(self):
        w = dominant_government(world())
        for office in ("army", "navy", "interior"):
            shares = w.civil_war["forces"][office]
            shares["government"], shares["rebels"] = shares["rebels"], shares["government"]
        w.region("kessel").controller = "karamaniya"
        w.region("kessel").rebels = 0.0
        w.civil_war["contested"] = ["kessel"]
        record = None
        for _ in range(8):
            record = cwc.combat(w)
            if w.region("kessel").controller == "rebels":
                break
            w.month += 1
        self.assertEqual(w.region("kessel").controller, "rebels")
        self.assertGreater(w.region("kessel").rebels, 0.0)
        self.assertTrue(any(c["region"] == "kessel" and c["to"] == "rebels"
                            for c in record["control_changes"]))
        self.assertTrue(any(e["kind"] == "occupation" for e in w.events))

    def test_a_withdrawing_defender_cedes_without_a_battle(self):
        w = world()
        w.civil_war["orders"] = {"rebels": {"kessel": "withdraw"}}
        rec = cwc.combat(w)
        self.assertEqual(w.region("kessel").controller, "karamaniya")
        self.assertEqual(rec["losses"]["government"] + rec["losses"]["rebels"], 0.0)
        self.assertTrue(rec["control_changes"][0]["routed"])

    def test_a_defending_attacker_does_not_attack(self):
        w = world()
        w.civil_war["orders"] = {"government": {"kessel": "defend"}}
        before = fingerprint(w)
        rec = cwc.combat(w)
        self.assertEqual(rec["fronts"]["kessel"]["note"], "attacker held")
        self.assertEqual(rec["fronts"]["kessel"]["ratio"], 0.0)
        self.assertEqual(rec["losses"]["civilians"], 0.0)
        self.assertEqual(w.region("kessel").controller, "rebels")
        # The only state change is the monthly defection update.
        self.assertEqual(before["controllers"], fingerprint(w)["controllers"])
        self.assertEqual(before["damage"], fingerprint(w)["damage"])

    def test_a_falling_region_sends_refugees(self):
        w = dominant_government(world())
        pop_before_fall = None
        civilians = 0.0
        for _ in range(8):
            if w.region("kessel").controller == "karamaniya":
                break
            pop_before_fall = sum(p.size for p in w.pops if p.region == "kessel")
            record = cwc.combat(w)
            civilians = record["losses"]["civilians"] if record["control_changes"] else 0.0
            w.month += 1
        self.assertEqual(w.region("kessel").controller, "karamaniya")
        moved = w.counters.get("refugees", 0.0)
        self.assertGreater(moved, 0.0)
        self.assertGreaterEqual(moved, cwc.REFUGEE_MIN * pop_before_fall * 0.97)
        self.assertLessEqual(moved, cwc.REFUGEE_MAX * pop_before_fall * 1.03)
        # The civilians killed in the falling month are gone before the refugees are counted.
        self.assertAlmostEqual(sum(p.size for p in w.pops if p.region == "kessel"),
                               pop_before_fall - moved - civilians, delta=2.0)

    def test_refugees_go_to_a_region_held_by_the_other_side(self):
        w = dominant_government(world())
        for _ in range(8):
            if w.region("kessel").controller == "karamaniya":
                break
            cwc.combat(w)
            w.month += 1
        # The government won, so refugees flee to the remaining rebel-held regions;
        # Kessel was the only one, so they stay inside government territory instead.
        self.assertEqual(w.region("kessel").controller, "karamaniya")
        self.assertGreater(w.counters.get("refugees", 0.0), 0.0)


class CeasefireAndOrders(unittest.TestCase):
    def test_a_ceasefire_stops_combat(self):
        w = world()
        w.civil_war["ceasefire"] = {"active": True, "month": 4}
        before = fingerprint(w)
        rec = cwc.combat(w)
        self.assertTrue(rec["ceasefire"])
        self.assertEqual(rec["fronts"], {})
        self.assertEqual(before, fingerprint(w))

    def test_a_broken_ceasefire_fights(self):
        w = world()
        w.civil_war["ceasefire"] = {"active": True, "broken": True}
        rec = cwc.combat(w)
        self.assertFalse(rec["ceasefire"])
        self.assertIn("kessel", rec["fronts"])


class Determinism(unittest.TestCase):
    def test_same_seed_same_state_same_result(self):
        a = world(seed=11)
        b = world(seed=11)
        ra = cwc.combat(a)
        rb = cwc.combat(b)
        self.assertEqual(ra, rb)
        self.assertEqual(fingerprint(a), fingerprint(b))

    def test_the_months_other_draws_are_unchanged(self):
        w = world()
        tags = ("media", "society", "military", "foreign_exposure", "open_act")

        def draws(seed, month):
            return {tag: [rng_for(seed, month, tag).random() for _ in range(4)] for tag in tags}

        before = draws(w.seed, w.month)
        global_state = random.getstate()
        cwc.combat(w)
        self.assertEqual(before, draws(w.seed, w.month))
        self.assertEqual(global_state, random.getstate())

    def test_a_supplied_rng_is_the_only_source(self):
        a = world()
        b = world()
        ra = cwc.combat(a, rng=random.Random(99))
        rb = cwc.combat(b, rng=random.Random(99))
        self.assertEqual(ra, rb)


class Defections(unittest.TestCase):
    def test_shares_shift_toward_the_loyal_commander_by_at_most_the_cap(self):
        w = world()
        w.civil_war["contested"] = []
        w.const.offices["army"] = "D"          # a rebel holds the army
        w.mil.army.bond = 0.9
        w.mil.army.loyalty = 0.1
        w.mil.army.arrears = 2.0
        before = dict(w.civil_war["forces"]["army"])
        rec = cwc.combat(w)
        entry = rec["defections"]["army"]
        self.assertLessEqual(abs(entry["after"]["rebels"] - before["rebels"]), cwc.DEFECTION_CAP + 1e-9)
        self.assertGreater(entry["after"]["rebels"], before["rebels"])
        for key in ("government", "rebels", "neutral"):
            self.assertAlmostEqual(w.civil_war["forces"]["army"][key], entry["after"][key], places=6)
        total = sum(w.civil_war["forces"]["army"].values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_missing_shares_are_built_from_the_engine(self):
        w = world()
        w.civil_war.pop("forces")
        rec = cwc.combat(w)
        built = w.civil_war["forces"]
        for office in ("army", "navy", "interior"):
            self.assertIn(office, built)
            self.assertAlmostEqual(sum(built[office].values()), 1.0, places=9)
        self.assertEqual(set(rec["defections"]), {"army", "navy", "interior"})

    def test_complete_forces_sum_to_one(self):
        w = world()
        cwc.combat(w)
        for office, shares in w.civil_war["forces"].items():
            self.assertAlmostEqual(sum(shares.values()), 1.0, places=9)
            self.assertTrue(all(v >= 0.0 for v in shares.values()))


if __name__ == "__main__":
    unittest.main()
