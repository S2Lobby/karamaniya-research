"""Civil war (Wave C, C1): the option, the two triggers, the factions, the forces and the territory.

The state's rules come from notes/CIVIL_WAR-design.md and the lead's decisions:
- the run option is `civil_war = "on" | "off"`, off by default, and an off run reads no state and
  behaves as engine 29 did;
- a civil war can start from Month 2, never in Month 1, on a failed coup whose plotters keep a
  company of armed force, or on a handover coup in which the government keeps a quarter of the
  armed power;
- rebels keep their seats and are listed in `w.civil_war`, not removed;
- the shares are the ones `military.anticipated_response` already returns, weighted by
  `politics._power`;
- territory reuses `controller = "rebels"` and `"karamaniya"`; the contested set is kept in the
  state rather than in a new controller value.

The two trigger thresholds (0.30 of the armed power on a failed coup, 0.25 kept by the government
on a handover coup) are assumptions; the scripted hawk sweep calibrates them.

`tests/fixtures/civil_war_off_month.json` is the history row of one scripted engine month recorded
on engine 29 (commit 6fb526b), with `engine_source_fingerprint` removed because it hashes the
source on disk, including this wave's new module.
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import civil_war, engine, politics  # noqa: E402
from karamaniya.world import ARMED_OFFICES, OFFICES, World, new_world  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OFF_MONTH_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "civil_war_off_month.json")


class FixedRng:
    """A die the test holds: resolve_coups' success draw and its casualty draw are both fixed."""

    def __init__(self, value: float):
        self.value = value

    def random(self) -> float:
        return self.value

    def uniform(self, low: float, high: float) -> float:
        return (low + high) / 2


def coup_draw(success: bool):
    """Patch the coup stream so the outcome of a coup attempt is not left to a seed."""
    return mock.patch.object(politics, "rng_for", return_value=FixedRng(0.01 if success else 0.99))


def world(seed: int = 11, option: str = "on", month: int = 1) -> World:
    w = new_world(seed, 36, civil_war_option=option)
    w.month = month
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def loyal_plotter_world(**kwargs) -> World:
    """A coup by the army minister that fails even though a company of the army would follow him:
    the police is large and loyal, the government is popular, and the commander's bond is high while
    his force's loyalty to the state is low (one of the trigger's force conditions)."""
    w = world(**kwargs)
    for p in w.pops:
        p.approval = 0.75
    m = w.mil
    m.army.size, m.army.bond, m.army.loyalty, m.army.morale = 30000, 0.95, 0.30, 0.50
    m.deploy = {"north": 0.2, "east": 0.2, "capital": 0.6}
    m.police.size, m.police.loyalty = 30000, 0.90
    m.navy.loyalty = 0.90
    return w


def attempt_remove(w: World, targets=("A", "B"), stances=None):
    """One failed-coup attempt by D (the army) as resolve_coups receives it from the council."""
    stances = stances or {mid: "resist" for mid in "ABCE"}
    with coup_draw(success=False):
        return politics.resolve_coups(
            w, {"D": {"action": "remove", "members": list(targets)}}, stances)


def handover_world(**kwargs) -> World:
    """The handover month: the government lost the vote and a coup tries to keep it in office. The
    army follows its minister, but a large loyal police and navy keep a share of the armed power."""
    w = loyal_plotter_world(**kwargs)
    w.const.handover_month = w.month
    return w


def attempt_handover(w: World, action="remove", members=("A",), stances=None):
    stances = stances or {mid: "resist" for mid in "ABCE"}
    with coup_draw(success=True):
        return politics.resolve_coups(
            w, {"D": {"action": action, "members": list(members)}}, stances)


def division(w: World, office: str) -> dict:
    """The division anticipated_response returns for an office, as the state stores it."""
    wars = civil_war.armed_divisions(w)
    return wars[office]


class OptionValidation(unittest.TestCase):
    def test_absent_or_none_is_off(self):
        self.assertEqual(civil_war.validate_option(None), "off")

    def test_on_and_off_are_accepted(self):
        self.assertEqual(civil_war.validate_option("on"), "on")
        self.assertEqual(civil_war.validate_option("off"), "off")
        self.assertEqual(civil_war.validate_option(" ON "), "on")

    def test_an_unknown_value_is_refused(self):
        for value in ("maybe", "", 1, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    civil_war.validate_option(value)

    def test_a_new_world_has_no_war_and_the_option_off(self):
        w = new_world(1, 36)
        self.assertIsNone(w.civil_war)
        self.assertEqual(w.civil_war_option, "off")
        self.assertIsNone(civil_war.state(w))
        self.assertFalse(civil_war.enabled(w))
        with self.assertRaises(ValueError):
            new_world(1, 36, civil_war_option="maybe")


class NoTriggerInMonthOne(unittest.TestCase):
    """The user's rule: neighbours are hostile, but there is no civil war in Month 1."""

    def test_a_failed_coup_with_a_loyal_force_takes_the_old_path_in_month_one(self):
        w = loyal_plotter_world(month=0)
        res = attempt_remove(w)
        self.assertFalse(res[0]["success"])
        self.assertIsNone(civil_war.state(w))
        self.assertEqual(w.member("D").status, "removed")
        self.assertEqual(w.member("D").removed_how, "failed_coup")
        self.assertNotIn("civil_war", res[0])

    def test_a_split_handover_takes_the_old_outcome_in_month_one(self):
        w = handover_world(month=0)
        self.assertEqual(w.const.handover_month, 0)
        res = attempt_handover(w)
        self.assertTrue(res[0]["success"])
        self.assertIsNone(civil_war.state(w))
        self.assertEqual(w.counters.get("handover_blocked_month"), 0.0)


class FailedCoupTrigger(unittest.TestCase):
    def test_a_failed_coup_with_a_loyal_force_starts_the_war(self):
        w = loyal_plotter_world()
        res = attempt_remove(w)
        coup = res[0]
        self.assertFalse(coup["success"])
        self.assertIsNotNone(civil_war.state(w))
        state = civil_war.state(w)
        self.assertEqual(state["cause"], "failed_coup")
        self.assertEqual(state["since"], w.month)
        self.assertEqual(state["factions"]["rebels"]["members"], ["D"])
        self.assertEqual(w.member("D").status, "active")
        self.assertEqual(w.member("D").removed_how, "")
        self.assertEqual(w.const.offices["army"], "D")
        self.assertEqual(coup["civil_war"], {"started": True, "cause": "failed_coup"})
        self.assertTrue(any(e["kind"] == "civil_war" for e in w.events))
        # The government side is everyone else who is still active.
        self.assertEqual(state["factions"]["government"]["members"], ["A", "B", "C", "E"])

    def test_a_failed_coup_without_the_loyal_force_takes_the_old_path(self):
        w = world()
        w.mil.army.bond, w.mil.army.loyalty = 0.05, 0.60
        for p in w.pops:
            p.approval = 0.75
        res = attempt_remove(w)
        self.assertFalse(res[0]["success"])
        self.assertIsNone(civil_war.state(w))
        self.assertEqual(w.member("D").status, "removed")
        self.assertEqual(w.member("D").removed_how, "failed_coup")

    def test_the_armed_divisions_are_kept_in_the_coup_record(self):
        w = world(option="off")
        w.mil.army.bond, w.mil.army.loyalty = 0.05, 0.60
        before = civil_war.armed_divisions(w)
        res = attempt_remove(w)
        divisions = res[0]["divisions"]
        self.assertEqual(set(divisions), set(ARMED_OFFICES))
        self.assertEqual(divisions["army"]["holder"], "D")
        for office in ARMED_OFFICES:
            for key in ("obey_commander", "obey_government", "neutral", "split", "power"):
                self.assertIn(key, divisions[office])
        # The stored army division is the one the coup used, before its morale hit and removal.
        self.assertAlmostEqual(divisions["army"]["obey_commander"],
                               before["army"]["obey_commander"], places=6)
        # With the arm off the record still carries the divisions, but no state is built.
        self.assertIsNone(civil_war.state(w))

    def test_the_commander_share_alone_is_not_enough_without_bond_or_low_loyalty(self):
        w = world()
        w.mil.army.bond, w.mil.army.loyalty = 0.10, 0.60
        # The army is all of the weighted power; the other offices carry none in this record, so
        # the plotters' share is the army's obey_commander exactly.
        rec = {"plotters": ["D"], "armed": ["D"],
               "divisions": {office: {"holder": w.holder(office).id if w.holder(office) else None,
                                      "power": 1.0 if office == "army" else 0.0,
                                      "obey_commander": 0.5 if office == "army" else 0.0,
                                      "obey_government": 0.2, "neutral": 0.2, "split": 0.1}
                             for office in ARMED_OFFICES}}
        # The plotters' share is above 0.30 of the power weighted here, but the force is neither
        # bonded nor disloyal, so the condition fails.
        self.assertFalse(civil_war.failed_coup_starts(w, rec))
        w.mil.army.bond = 0.30
        self.assertTrue(civil_war.failed_coup_starts(w, rec))
        w.mil.army.bond = 0.10
        w.mil.army.loyalty = 0.45
        self.assertTrue(civil_war.failed_coup_starts(w, rec))

    def test_the_share_threshold_holds(self):
        w = world()
        w.mil.army.bond = 0.50
        rec = {"plotters": ["D"], "armed": ["D"],
               "divisions": {office: {"holder": w.holder(office).id if w.holder(office) else None,
                                      "power": 1.0 if office == "army" else 0.0,
                                      "obey_commander": 0.0, "obey_government": 0.2,
                                      "neutral": 0.2, "split": 0.1}
                             for office in ARMED_OFFICES}}
        rec["divisions"]["army"]["obey_commander"] = 0.29
        self.assertFalse(civil_war.failed_coup_starts(w, rec))
        rec["divisions"]["army"]["obey_commander"] = 0.30
        self.assertTrue(civil_war.failed_coup_starts(w, rec))


class HandoverTrigger(unittest.TestCase):
    def test_a_split_handover_starts_the_war(self):
        w = handover_world()
        res = attempt_handover(w)
        coup = res[0]
        self.assertTrue(coup["success"])
        self.assertTrue(coup["handover"])
        self.assertIsNotNone(civil_war.state(w))
        state = civil_war.state(w)
        self.assertEqual(state["cause"], "handover_coup")
        self.assertEqual(state["factions"]["rebels"]["members"], ["D"])
        self.assertEqual(w.const.handover_month, -1)
        self.assertEqual(w.const.election_month, -1)
        self.assertNotIn("handover_blocked_month", w.counters)
        self.assertEqual(coup["civil_war"], {"started": True, "cause": "handover_coup"})

    def test_a_total_takeover_keeps_the_old_outcome(self):
        w = handover_world()
        m = w.mil
        # Every other office holder joins the plot and the army follows its commander almost
        # wholly: the government keeps less than a quarter of the armed power.
        m.army.size, m.army.bond, m.army.loyalty, m.army.morale = 70000, 0.95, 0.1, 0.9
        m.deploy = {"north": 0.05, "east": 0.05, "capital": 0.9}
        stances = {mid: "join" for mid in "ABCE"}
        res = attempt_handover(w, stances=stances)
        self.assertTrue(res[0]["success"])
        self.assertIsNone(civil_war.state(w))
        self.assertEqual(w.counters.get("handover_blocked_month"), float(w.month))
        self.assertNotIn("civil_war", res[0])

    def test_the_government_must_keep_a_quarter_of_the_armed_power(self):
        w = world()
        rec = {"divisions": {office: {"holder": w.holder(office).id if w.holder(office) else None,
                                      "power": 1.0, "obey_commander": 0.5, "obey_government": 0.24,
                                      "neutral": 0.26, "split": 0.0}
                             for office in ARMED_OFFICES}}
        self.assertFalse(civil_war.handover_starts(w, rec))
        for d in rec["divisions"].values():
            d["obey_government"] = 0.25
        self.assertTrue(civil_war.handover_starts(w, rec))


class FactionsForcesAndTerritory(unittest.TestCase):
    def start(self, w, plotters=("D",), stances=None):
        stances = {"A": "join"} if stances is None else stances
        return civil_war.start(w, "failed_coup", plotters=list(plotters), stances=stances)

    def test_members_rebels_and_seats(self):
        w = loyal_plotter_world()
        state = self.start(w)
        self.assertEqual(state["factions"]["rebels"]["members"], ["A", "D"])
        self.assertEqual(state["factions"]["government"]["members"], ["B", "C", "E"])
        self.assertEqual(state["factions"]["rebels"]["id"], "rebels")
        self.assertEqual(state["factions"]["government"]["id"], "government")
        # Rebels keep their seats and are not removed.
        for mid in ("A", "D"):
            self.assertEqual(w.member(mid).status, "active")
            self.assertEqual(w.member(mid).removed_how, "")
        self.assertEqual(w.const.offices["head"], "A")
        self.assertEqual(w.const.offices["army"], "D")

    def test_the_leader_is_the_highest_office_then_power(self):
        w = loyal_plotter_world()
        state = self.start(w, plotters=("D",), stances={"A": "join"})
        # A holds the head office (rank 0) and leads the rebels even though D commands the army.
        self.assertEqual(state["factions"]["rebels"]["leader"], "A")
        # B (treasury) outranks C (interior) and E (navy) in the government.
        self.assertEqual(state["factions"]["government"]["leader"], "B")

    def test_forces_are_the_anticipated_shares_weighted_by_power(self):
        w = loyal_plotter_world()
        state = self.start(w, plotters=("D",), stances={"A": "join"})
        rebels, government = state["factions"]["rebels"]["forces"], state["factions"]["government"]["forces"]
        army = division(w, "army")
        # The army's holder is a rebel: the rebel share is obey_commander.
        self.assertIn("army", rebels)
        self.assertAlmostEqual(rebels["army"]["share"], army["obey_commander"], places=4)
        self.assertEqual(rebels["army"]["holder"], "D")
        self.assertAlmostEqual(rebels["army"]["size"], w.mil.army.size * army["obey_commander"], places=0)
        # The police and the navy are held by the government: their share is
        # obey_government + 0.5 * split.
        for office, force in (("interior", w.mil.police), ("navy", w.mil.navy)):
            d = division(w, office)
            self.assertIn(office, government)
            self.assertAlmostEqual(government[office]["share"],
                                   d["obey_government"] + 0.5 * d["split"], places=4)
            self.assertAlmostEqual(government[office]["size"],
                                   force.size * (d["obey_government"] + 0.5 * d["split"]), places=0)
            self.assertNotIn(office, rebels)
        # No unit joins both sides.
        for office in ARMED_OFFICES:
            self.assertFalse(office in rebels and office in government, office)
        # Neutral joins neither: the stored neutral share is reported, not assigned.
        self.assertTrue(all("neutral_share" in d for d in list(rebels.values()) + list(government.values())))
        self.assertLessEqual(state["factions"]["rebels"]["power_share"]
                             + state["factions"]["government"]["power_share"]
                             + state["neutral_power_share"], 1.0001)

    def test_territory_follows_the_army_share_and_existing_rebel_regions(self):
        w = loyal_plotter_world()
        w.region("kessel").controller = "rebels"          # a region the engine already lost to rebels
        w.region("lissen").controller = "union"           # a Union-held region is not the war's territory
        state = self.start(w)
        # The army's rebel share is above one half, so the capital and both fronts are contested.
        self.assertGreaterEqual(division(w, "army")["obey_commander"], 0.5)
        self.assertEqual(sorted(state["contested"]), sorted(["aster", "dorran"]))
        self.assertIn("kessel", state["factions"]["rebels"]["territory"])
        self.assertNotIn("kessel", state["factions"]["government"]["territory"])
        self.assertIn("aster", state["factions"]["government"]["territory"])
        self.assertIn("dorran", state["factions"]["government"]["territory"])
        self.assertNotIn("lissen", state["factions"]["government"]["territory"])
        # No new controller values: contested regions stay under the government's controller.
        for rid in state["contested"]:
            self.assertEqual(w.region(rid).controller, "karamaniya")
        for r in w.regions:
            self.assertNotIn("faction:", r.controller)

    def test_a_weak_rebel_army_leaves_the_capital_and_fronts_government(self):
        w = world()
        w.mil.army.bond, w.mil.army.loyalty = 0.05, 0.60
        state = self.start(w)
        self.assertLess(division(w, "army")["obey_commander"], 0.5)
        self.assertEqual(state["contested"], [])
        self.assertIn("aster", state["factions"]["government"]["territory"])
        self.assertIn("kessel", state["factions"]["government"]["territory"])
        self.assertIn("dorran", state["factions"]["government"]["territory"])

    def test_a_war_starts_once(self):
        w = loyal_plotter_world()
        first = self.start(w)
        second = civil_war.start(w, "handover_coup", plotters=["B"])
        self.assertIs(first, second)
        self.assertEqual(second["cause"], "failed_coup")
        self.assertEqual(second["factions"]["rebels"]["members"], ["A", "D"])


class OffChangesNothing(unittest.TestCase):
    def test_off_takes_the_old_failed_coup_path(self):
        w = loyal_plotter_world(option="off")
        res = attempt_remove(w)
        self.assertFalse(res[0]["success"])
        self.assertIsNone(civil_war.state(w))
        self.assertEqual(w.member("D").removed_how, "failed_coup")
        self.assertNotIn("civil_war", res[0])

    def test_off_never_reads_a_state_that_is_present(self):
        """A checkpoint written by an on run, loaded by an off run, changes no month."""
        plain = loyal_plotter_world(option="off")
        loaded = loyal_plotter_world(option="off")
        donor = loyal_plotter_world(option="on")
        loaded.civil_war = json.loads(json.dumps(civil_war.start(
            donor, "failed_coup", plotters=["D"], stances={"A": "join"})))
        engine.begin_month(plain)
        engine.step(plain)
        engine.begin_month(loaded)
        engine.step(loaded)
        self.assertEqual(plain.history[-1], loaded.history[-1])
        # The off arm left the state untouched.
        self.assertIsNotNone(loaded.civil_war)
        self.assertIsNone(plain.civil_war)

    def test_a_scripted_month_with_the_option_off_matches_engine_29(self):
        """Recorded on the base commit (6fb526b) before this wave; see the module docstring."""
        with open(OFF_MONTH_FIXTURE, encoding="utf-8") as f:
            expected = json.load(f)
        w = new_world(6, 36)
        w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
        engine.begin_month(w)
        engine.step(w)
        row = json.loads(json.dumps(w.history[-1]))
        row.pop("engine_source_fingerprint", None)
        self.assertEqual(row, expected)


class Checkpoints(unittest.TestCase):
    def test_an_old_checkpoint_loads_without_a_war(self):
        w = new_world(3, 36)
        data = w.to_dict()
        self.assertNotIn("civil_war", data)
        self.assertNotIn("civil_war_option", data)
        restored = World.from_dict(data)
        self.assertIsNone(restored.civil_war)
        self.assertEqual(restored.civil_war_option, "off")

    def test_the_state_is_preserved_in_a_checkpoint(self):
        w = loyal_plotter_world()
        state = civil_war.start(w, "failed_coup", plotters=["D"], stances={"A": "join"})
        data = w.to_dict()
        self.assertEqual(data["civil_war"], json.loads(json.dumps(state)))
        self.assertEqual(data["civil_war_option"], "on")
        restored = World.from_dict(data)
        self.assertEqual(restored.civil_war, data["civil_war"])
        self.assertEqual(restored.civil_war_option, "on")
        self.assertEqual(civil_war.state(restored)["factions"]["rebels"]["members"], ["A", "D"])

    def test_an_off_checkpoint_has_no_civil_war_keys(self):
        w = world(option="off")
        self.assertNotIn("civil_war", w.to_dict())
        self.assertNotIn("civil_war_option", w.to_dict())


if __name__ == "__main__":
    unittest.main()
