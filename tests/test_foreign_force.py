"""Veleria and Dorsania can use force, and it is checked against what they actually have.

In the first engine-6 run with real models (20261008-130316-seed1) the two cabinets issued 14 statements,
7 exercises and 4 intelligence operations in 17 months and never moved a soldier: their menu had no
military move but an "exercise", their instructions said to avoid war and to act only when the benefit
justified the listed costs, and war was left to fixed thresholds that never fired. Engine 12 gives the
cabinets the acts (foreign_force.py), checks each against the real state, and lets the cabinet rather
than the thresholds decide on war when it answers.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import director, foreign, foreign_force  # noqa: E402
from karamaniya.backends import scripted  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import World, new_world  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")


def world(seed: int = 3) -> World:
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    return w


def act(w, actor, **action):
    action.setdefault("magnitude", .5)
    error = foreign_force.check(w, actor, action)
    if error is None:
        foreign_force.apply(w, actor, action)
    return error


def seed_with(actor: str, temperament: str) -> int:
    return next(s for s in range(1, 500) if foreign_force.draw_temperament(actor, s) == temperament)


class Temperament(unittest.TestCase):
    def test_one_per_run_from_the_seed(self):
        for actor in ("veleria", "dorsania"):
            draws = {foreign_force.draw_temperament(actor, s) for s in range(1, 300)}
            self.assertEqual(draws, set(foreign_force.TEMPERAMENTS))
            self.assertEqual(foreign_force.draw_temperament(actor, 7), foreign_force.draw_temperament(actor, 7))
        hawks = {a: sum(foreign_force.draw_temperament(a, s) == "hawk" for s in range(1, 1001))
                 for a in ("veleria", "dorsania")}
        self.assertGreater(hawks["veleria"], hawks["dorsania"])

    def test_it_moves_the_disposition_the_rules_read(self):
        hawk = foreign.initial_state(seed_with("veleria", "hawk"))["actors"]["veleria"]
        patient = foreign.initial_state(seed_with("veleria", "calculating"))["actors"]["veleria"]
        self.assertEqual((hawk["temperament"], patient["temperament"]), ("hawk", "calculating"))
        self.assertGreater(hawk["disposition"]["aggressiveness"], patient["disposition"]["aggressiveness"])
        self.assertLess(hawk["disposition"]["patience"], patient["disposition"]["patience"])

    def test_a_checkpoint_from_before_gets_a_label_and_keeps_its_disposition(self):
        state = foreign.initial_state(5)
        old = state["actors"]["veleria"]
        del old["temperament"]
        disposition = dict(old["disposition"])
        foreign._ensure_actor_shape(old, "veleria", 5)
        self.assertEqual(old["temperament"], foreign_force.draw_temperament("veleria", 5))
        self.assertEqual(old["disposition"], disposition)

    def test_the_cabinet_is_told_its_temperament_and_not_told_to_avoid_war(self):
        text = foreign.cabinet_system_prompt("veleria", "hawk")
        self.assertIn(foreign_force.TEMPERAMENT_TEXT["veleria"]["hawk"], text)
        self.assertNotIn("avoid a damaging war", text)
        self.assertNotIn("only when their likely benefit justifies", text)
        self.assertIn("an act that cannot happen is refused and reported back to you", text)
        self.assertNotIn("hard-line", foreign.cabinet_system_prompt("dorsania", "calculating"))


class Checks(unittest.TestCase):
    def setUp(self):
        self.w = world()

    def test_only_its_own_border(self):
        self.assertIn("east front", act(self.w, "dorsania", type="deploy_to_border", front="north", troops=3000))
        self.assertIsNone(act(self.w, "dorsania", type="deploy_to_border", front="east", troops=3000))

    def test_soldiers_it_does_not_have(self):
        free = foreign_force.free_troops(self.w, "veleria")
        self.assertIn("free to send", act(self.w, "veleria", type="deploy_to_border", front="north",
                                          troops=int(free) + 1000))
        self.assertIn("reservists", act(self.w, "veleria", type="mobilize", troops=50000))

    def test_an_invasion_needs_troops_already_at_the_border(self):
        error = act(self.w, "veleria", type="invade", front="north", aim="limited")
        self.assertIn(f"{foreign_force.MIN_INVASION:,}", error)
        self.assertFalse(self.w.dip.war)

    def test_a_blockade_needs_the_ships(self):
        self.w.mil.navy.size = 10
        self.assertIn("naval advantage", act(self.w, "veleria", type="naval_blockade"))
        self.w.mil.navy.size = 4
        self.w.month = 1                  # no blockade begins in Month 1 (engine 15)
        self.assertIsNone(act(self.w, "veleria", type="naval_blockade"))
        self.assertTrue(self.w.dip.blockade)

    def test_an_ultimatum_names_terms_and_a_deadline(self):
        self.assertIn("terms must be", act(self.w, "veleria", type="ultimatum", terms="surrender", deadline_months=3))
        self.assertIn("deadline_months", act(self.w, "veleria", type="ultimatum", terms="status_talks",
                                             deadline_months=12))

    def test_weapons_need_unrest_to_feed(self):
        calm = self.w.region("lissen")
        calm.unrest = .05
        self.assertIn("no unrest", act(self.w, "veleria", type="covert_support", region="lissen"))
        self.w.region("kessel").unrest = .5
        self.assertIsNone(act(self.w, "veleria", type="covert_support", region="kessel"))


class Acts(unittest.TestCase):
    def setUp(self):
        self.w = world()

    def test_massing_is_visible_and_frightening(self):
        fear = sum(p.fear for p in self.w.pops if p.region == "kessel")
        self.assertIsNone(act(self.w, "veleria", type="deploy_to_border", front="north", troops=12000))
        self.assertEqual(foreign_force.at_border(self.w, "veleria", "north"), 12000)
        self.assertGreater(sum(p.fear for p in self.w.pops if p.region == "kessel"), fear)
        self.assertTrue(any(e["kind"] == "foreign_massing" for e in self.w.events))
        self.assertEqual(foreign_force.massing_text(self.w), "north border (Veleria)")
        self.assertIsNone(act(self.w, "veleria", type="withdraw_from_border", front="north", troops=5000))
        self.assertEqual(foreign_force.at_border(self.w, "veleria", "north"), 7000)

    def test_an_incident_kills_and_is_reported(self):
        act(self.w, "veleria", type="deploy_to_border", front="north", troops=8000)
        army = self.w.mil.army.size
        self.assertIsNone(act(self.w, "veleria", type="border_incident", front="north", magnitude=.8))
        self.assertLess(self.w.mil.army.size, army)
        incident = next(e for e in self.w.events if e["kind"] == "border_incident")
        self.assertIn("Kessel Valley", incident["text"])
        self.assertTrue(incident.get("deliberate"))

    def test_weapons_feed_the_uprising_and_run_out(self):
        self.w.region("kessel").unrest = .5
        act(self.w, "veleria", type="covert_support", region="kessel", magnitude=1.0)
        self.assertTrue(self.w.dip.arms_smuggling)
        self.assertGreater(self.w.region("kessel").unrest, .5)
        self.w.month += 3
        foreign_force.expire_covert_support(self.w)
        self.assertFalse(self.w.dip.arms_smuggling)

    def test_a_limited_invasion_takes_the_border_region_and_stops(self):
        act(self.w, "veleria", type="deploy_to_border", front="north", troops=15000)
        self.w.month += 1                 # troops cross the month after they reach the border (engine 15)
        self.assertIsNone(act(self.w, "veleria", type="invade", front="north", aim="limited"))
        dip = self.w.dip
        self.assertTrue(dip.war)
        self.assertEqual(dip.aggressor, "union")
        self.assertEqual((dip.war_aim["aim"], dip.war_aim["objective"]), ("limited", "kessel"))
        self.assertEqual(dip.union_front, {"north": 15000, "east": 0.0})
        self.assertEqual(foreign_force.at_border(self.w, "veleria"), 0)
        # The front holds what it committed; it is not refilled from the whole Union army.
        director._union_forces(self.w)
        self.assertEqual(dip.union_front, {"north": 15000, "east": 0.0})
        self.w.region("kessel").controller = "union"
        director._union_forces(self.w)
        self.assertFalse(dip.war)
        self.assertTrue(dip.ceasefire)
        self.assertEqual(dip.war_aim, {})
        self.assertTrue(any("halted its operations" in m["text"] for m in dip.inbox))

    def test_a_limited_war_stays_on_its_own_front(self):
        act(self.w, "veleria", type="deploy_to_border", front="north", troops=9000)
        self.w.month += 1
        act(self.w, "veleria", type="invade", front="north", aim="limited")
        self.assertEqual(foreign_force.war_fronts(self.w), ("north",))
        # Troops sent to the other border mass there; they do not open a second front.
        self.assertIsNone(act(self.w, "dorsania", type="deploy_to_border", front="east", troops=4000))
        self.assertEqual(self.w.dip.union_front, {"north": 9000, "east": 0.0})
        self.assertEqual(foreign_force.at_border(self.w, "dorsania", "east"), 4000)
        self.assertIsNone(act(self.w, "dorsania", type="withdraw_from_border", front="east", troops=1000))
        self.assertIn("fighting", act(self.w, "veleria", type="withdraw_from_border", front="north", troops=1000))
        # Only the country at war has soldiers at the front.
        self.assertEqual(foreign_force.at_war_front(self.w, "dorsania"), 0.0)
        self.assertEqual(foreign_force.at_war_front(self.w, "veleria"), 9000)

    def test_a_neighbour_that_sends_troops_to_the_fighting_joins_the_war(self):
        self.w.foreign["dorsania_position"] = "oppose"
        act(self.w, "veleria", type="deploy_to_border", front="north", troops=9000)
        self.w.month += 1
        act(self.w, "veleria", type="invade", front="north", aim="full")
        self.assertEqual(self.w.dip.war_aim["participants"], ["veleria"])
        self.assertEqual(foreign_force.war_fronts(self.w), ("north", "east"))
        self.assertIsNone(act(self.w, "dorsania", type="deploy_to_border", front="east", troops=5000))
        self.assertEqual(self.w.dip.union_front["east"], 5000)
        self.assertEqual(self.w.dip.war_aim["participants"], ["veleria", "dorsania"])
        self.assertTrue(any(e["kind"] == "war" and e.get("actor") == "dorsania" for e in self.w.events))
        self.assertGreater(foreign_force.at_war_front(self.w, "dorsania"), 0)

    def test_a_ceasefire_stops_a_war_it_started(self):
        act(self.w, "veleria", type="deploy_to_border", front="north", troops=9000)
        self.w.month += 1
        self.assertIsNone(act(self.w, "veleria", type="invade", front="north", aim="full"))
        self.assertIsNone(act(self.w, "veleria", type="ceasefire"))
        self.assertFalse(self.w.dip.war)

    def test_an_ultimatum_and_the_facts_it_is_judged_on(self):
        self.assertIsNone(act(self.w, "veleria", type="ultimatum", terms="status_talks", deadline_months=3))
        ult = self.w.dip.ultimatum
        self.assertEqual((ult["by"], ult["deadline"]), ("veleria", self.w.month + 3))
        self.assertIn("Deadline Month 4", foreign_force.ultimatum_text(self.w))
        view = foreign_force.ultimatum_compliance(self.w)
        self.assertEqual(view["observed"], {"karamaniyan_proposals_since_the_ultimatum": []})
        self.w.foreign["proposal_log"] = [{"month": self.w.month, "kind": "trade_talks", "party": "union"}]
        self.assertEqual(foreign_force.ultimatum_compliance(self.w)["observed"],
                         {"karamaniyan_proposals_since_the_ultimatum": ["trade_talks"]})

    def test_the_state_survives_a_checkpoint(self):
        act(self.w, "veleria", type="deploy_to_border", front="north", troops=9000)
        self.w.month += 1
        self.assertIsNone(act(self.w, "veleria", type="invade", front="north", aim="limited"))
        back = World.from_dict(self.w.to_dict())
        self.assertEqual(back.dip.war_aim, self.w.dip.war_aim)
        self.assertEqual(back.dip.border_forces, self.w.dip.border_forces)


class TheCabinetDecides(unittest.TestCase):
    def test_the_unions_rule_only_decides_when_no_cabinet_did(self):
        w = world()
        with mock.patch.object(director, "war_rule", return_value=True):
            w.foreign["cabinet_month"] = {"veleria": w.month}
            director._union_forces(w)
            self.assertFalse(w.dip.war)
            w.foreign["cabinet_month"] = {"veleria": w.month - 1}
            director._union_forces(w)
            self.assertTrue(w.dip.war)

    def test_an_ultimatum_its_cabinet_does_not_act_on_lapses(self):
        w = world()
        act(w, "veleria", type="ultimatum", terms="status_talks", deadline_months=2)
        deadline = w.dip.ultimatum["deadline"]
        aggressiveness = w.foreign["actors"]["veleria"]["reputation"]["military_aggressiveness"]
        for month in (deadline, deadline + 1):
            w.month = month
            w.foreign["cabinet_month"] = {"veleria": month}
            director._deadline_policy(w)
            if month == deadline:
                # The month the deadline falls in is the cabinet's to act in.
                self.assertTrue(w.dip.ultimatum)
        self.assertEqual(w.dip.ultimatum, {})
        self.assertFalse(w.dip.blockade)
        self.assertTrue(any(e["kind"] == "ultimatum_lapsed" for e in w.events))
        self.assertLess(w.foreign["actors"]["veleria"]["reputation"]["military_aggressiveness"], aggressiveness)
        self.assertIsNone(act(w, "veleria", type="ultimatum", terms="cut_league_ties", deadline_months=3))

    def test_an_ultimatum_acted_on_does_not_lapse(self):
        w = world()
        act(w, "veleria", type="ultimatum", terms="status_talks", deadline_months=2)
        w.month = w.dip.ultimatum["deadline"] + 1
        w.foreign["cabinet_month"] = {"veleria": w.month}
        w.mil.navy.size = 3
        act(w, "veleria", type="naval_blockade")
        director._deadline_policy(w)
        self.assertTrue(w.dip.ultimatum)
        self.assertFalse(any(e["kind"] == "ultimatum_lapsed" for e in w.events))

    def test_the_unions_ultimatum_rule_waits_for_a_month_without_a_cabinet(self):
        w = world()
        positions = foreign.positions(w)
        positions["veleria"].update(ultimatum=True, coal_embargo=0.0)
        positions["dorsania"].update(union="support", grain_embargo=0.0)
        w.foreign["union"]["cohesion"] = .9
        with mock.patch.object(foreign, "_issue_ultimatum") as issue:
            w.foreign["cabinet_month"] = {"veleria": w.month}
            foreign.resolve_union(w, positions, {})
            issue.assert_not_called()
            w.foreign["cabinet_month"] = {}
            foreign.resolve_union(w, positions, {})
            issue.assert_called_once()

    def test_the_scripted_stand_in_follows_the_rule_masses_then_invades(self):
        w = world()
        with mock.patch.object(director, "war_rule", return_value=True):
            first = scripted.ScriptedBackend._velerian_force(w)
            self.assertEqual([a["type"] for a in first], ["deploy_to_border"])
            act(w, "veleria", **first[0])
            second = scripted.ScriptedBackend._velerian_force(w)
            self.assertEqual([(a["type"], a["aim"]) for a in second], [("invade", "full")])


class TheAnswer(unittest.TestCase):
    def test_fields_an_act_names_are_kept_only_from_their_lists(self):
        out, problems = foreign.normalize_cabinet_output("veleria", {
            "public_statement": "", "strategic_assessment": "", "strategy": "", "union_position": None,
            "diplomatic_messages": [], "belief_updates": [], "decision_factors": [],
            "actions": [{"type": "invade", "front": "north", "aim": "limited", "magnitude": 1},
                        {"type": "invade", "front": "west", "aim": "limited"},
                        {"type": "ultimatum", "terms": "status_talks", "deadline_months": 3.0},
                        {"type": "ultimatum", "terms": "status_talks", "deadline_months": "soon"}]})
        self.assertEqual(out["actions"], [
            {"type": "invade", "magnitude": 1.0, "front": "north", "aim": "limited"},
            {"type": "ultimatum", "magnitude": .5, "terms": "status_talks", "deadline_months": 3}])
        self.assertEqual(len(problems), 2)

    def test_the_schema_offers_the_acts_and_their_fields(self):
        schema = foreign.cabinet_schema("dorsania")
        action = schema["properties"]["actions"]["items"]
        self.assertIn("invade", action["properties"]["type"]["enum"])
        self.assertEqual(action["properties"]["front"]["enum"], ["north", "east"])
        self.assertEqual(action["required"], ["type"])

    def test_a_refusal_is_shown_to_the_cabinet_the_next_month(self):
        w = world()
        foreign._apply_cabinet_decisions(w, foreign.positions(w), {"veleria": {
            "actions": [{"type": "invade", "front": "north", "aim": "full", "magnitude": 1.0}]}})
        w.month += 1
        refused = foreign_force.cabinet_view(w, "veleria")["your_acts_refused_last_month"]
        self.assertEqual(refused[0]["action"], "invade")
        self.assertIn("needs at least", refused[0]["reason"])


class AScriptedRunWithAnAggressiveNeighbour(unittest.TestCase):
    """Eight months with a Velerian cabinet that masses, provokes and invades for Kessel Valley."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-force-")
        plan = {0: [{"type": "deploy_to_border", "front": "north", "troops": 20000, "magnitude": .6}],
                1: [{"type": "border_incident", "front": "north", "magnitude": .8}],
                2: [{"type": "invade", "front": "north", "aim": "limited", "magnitude": 1.0}]}
        original = scripted.ScriptedBackend._foreign

        def hawk(self, ctx):
            answer = original(self, ctx)
            w = ctx.get("world")
            if ctx.get("actor") == "veleria" and w is not None:
                answer["actions"] = list(plan.get(w.month, []))
            return answer

        with mock.patch.object(scripted.ScriptedBackend, "_foreign", hawk):
            cls.path = new_run(CONFIG, runs_dir=cls.tmp, name="force", months=8, quiet=True)
        cls.store = RunStore(cls.path)
        cls.months = cls.store.read_log("month")
        cls.world = cls.store.load_checkpoint()[0]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def events(self, kind):
        return [e for e in self.world.events + [x for h in self.world.history for x in h.get("events", [])]
                if e.get("kind") == kind]

    def test_the_war_follows_the_cabinets_acts(self):
        rows = {h["month"]: h for h in self.world.history}
        self.assertEqual(rows[0]["fronts"]["north"]["massing"], 20000)
        self.assertEqual(rows[0]["fronts"]["north"]["massing_by"], {"veleria": 20000})
        war_months = [h["month"] for h in self.world.history if h.get("war")]
        self.assertEqual(war_months[0], 2)
        self.assertTrue(any("crossed into Kessel Valley" in e.get("text", "") or "near Kessel Valley" in e.get("text", "")
                            for h in self.world.history for e in h.get("events", [])
                            if e.get("kind") == "border_incident"))

    def test_the_council_was_told(self):
        with open(os.path.join(self.path, "prompts.jsonl"), encoding="utf-8") as f:
            prompts_seen = f.read()
        self.assertIn("Foreign troops are massed at the north border (Veleria)", prompts_seen)
        self.assertIn("massing troops on the border near Kessel Valley", prompts_seen)
