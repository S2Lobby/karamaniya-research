"""Engine 27, wave 3 Haiku B: the Union's propaganda and Karamaniya's counter.

The Union's cabinets (Veleria and Dorsania) can run a `propaganda` act against Karamaniya: a target
(the whole country or one region), a message (government_failing, stir_minority or blame_government)
and a magnitude from 0 to 1. Approval falls and grievance rises in the target, scaled by
(1 - state media credibility) and by real hardship there; unrest follows grievance in society.update.
Each campaign leaves one record in w.media.campaigns with source set to the actor.

Karamaniya's council can set `foreign_broadcasts` to open (the default) or jammed. Jamming cuts a
foreign campaign's effect, lowers the democracy index while it stands, and costs state media
credibility each month it stays on.

These tests call no model. They read raw cabinet answers with foreign.normalize_cabinet_output,
apply them as the month does (foreign._apply_cabinet_decisions), and step two identical worlds
when the effect itself is under test.
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import briefing, engine, foreign, politics, prompts  # noqa: E402
from karamaniya.world import Policy, World, democracy_index, new_world  # noqa: E402

ACTORS = ("veleria", "dorsania")
MESSAGES = ("government_failing", "stir_minority", "blame_government")


def world(month: int = 0, seed: int = 5, credibility: float | None = None):
    w = new_world(seed, 36, human_factor=False)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    w.month = month
    if credibility is not None:
        w.media["credibility"] = credibility
    return w


def cabinet_answer(**fields):
    base = {"public_statement": "", "strategic_assessment": "", "strategy": "", "union_position": None,
            "diplomatic_messages": [], "belief_updates": [], "decision_factors": [], "actions": []}
    return {**base, **fields}


def read(actor, *acts):
    return foreign.normalize_cabinet_output(actor, cabinet_answer(actions=list(acts)))


def answer_month(w, actor, *acts):
    """One cabinet's month exactly as the engine resolves it: read the answer, then apply it."""
    out, problems = read(actor, *acts)
    foreign._apply_cabinet_decisions(w, foreign.positions(w), {actor: out})
    return out, problems


def pop_avg(w, attr, region=None, ident=None):
    pops = [p for p in w.k_pops()
            if (region is None or p.region == region) and (ident is None or p.ident == ident)]
    total = sum(p.size for p in pops)
    return sum(getattr(p, attr) * p.size for p in pops) / total if total else 0.0


class ThePropagandaActBelongsToBothCabinet(unittest.TestCase):
    def test_both_cabinets_offer_the_act(self):
        for actor in ACTORS:
            with self.subTest(actor=actor):
                kinds = [a["type"] for a in foreign.action_catalog(actor)]
                self.assertIn("propaganda", kinds)
                schema = foreign.cabinet_schema(actor)
                props = schema["properties"]["actions"]["items"]["properties"]
                self.assertIn("propaganda", props["type"]["enum"])
                self.assertEqual(props["message"]["enum"], list(MESSAGES))
                self.assertEqual(props["target"]["enum"][0], "country")
                self.assertIn("kessel", props["target"]["enum"])

    def test_a_valid_act_is_read_for_both_cabinets(self):
        for actor in ACTORS:
            with self.subTest(actor=actor):
                out, problems = read(actor, {"type": "propaganda", "target": "kessel",
                                             "message": "stir_minority", "magnitude": .6})
                self.assertEqual(problems, [])
                self.assertEqual(out["actions"], [{"type": "propaganda", "magnitude": .6,
                                                   "target": "kessel", "message": "stir_minority"}])

    def test_a_region_written_by_its_name_is_read(self):
        out, problems = read("veleria", {"type": "propaganda", "target": "Kessel Valley",
                                         "message": "government_failing"})
        # Engine 30 (T151): the act gave no size, so the size reading is a note. The region name is not a refusal.
        self.assertEqual([note["type"] for note in out["act_notes"]], ["propaganda"], out["act_notes"])
        self.assertIn("the size was taken as 0.5", out["act_notes"][0]["reason"])
        self.assertEqual(out["actions"][0]["target"], "kessel")
        self.assertEqual(out["actions"][0]["magnitude"], .5)
        self.assertIn("target 'Kessel Valley' was read as kessel", problems)

    def test_a_missing_target_is_the_whole_country_with_a_note(self):
        out, problems = read("veleria", {"type": "propaganda", "message": "government_failing"})
        self.assertEqual(out["actions"][0]["target"], "country")
        self.assertTrue(any("target" in note["reason"] and "whole country" in note["reason"]
                            for note in out["act_notes"]), out["act_notes"])

    def test_a_bad_message_is_refused_and_names_the_choices(self):
        out, problems = read("dorsania", {"type": "propaganda", "target": "country",
                                          "message": "the government is bad"})
        self.assertEqual(out["actions"], [])
        joined = " ".join(problems)
        for message in MESSAGES:
            self.assertIn(message, joined)

    def test_a_bad_target_is_refused_and_names_the_regions(self):
        out, problems = read("dorsania", {"type": "propaganda", "target": "nowhere",
                                          "message": "government_failing"})
        self.assertEqual(out["actions"], [])
        self.assertIn("Port Aster", " ".join(problems))

    def test_a_missing_message_is_refused(self):
        out, problems = read("veleria", {"type": "propaganda", "target": "country"})
        self.assertEqual(out["actions"], [])
        self.assertIn("message", " ".join(problems))

    def test_a_magnitude_outside_the_range_is_refused(self):
        out, problems = read("veleria", {"type": "propaganda", "target": "country",
                                         "message": "government_failing", "magnitude": 1.4})
        self.assertEqual(out["actions"], [])
        self.assertIn("between 0 and 1", " ".join(problems))


class PropagandaLandsWithTrustAndHardship(unittest.TestCase):
    def test_approval_falls_and_grievance_rises_in_the_region_targeted(self):
        w = world()
        before = {r: (pop_avg(w, "approval", r), pop_avg(w, "grievance", r)) for r in ("kessel", "lissen")}
        answer_month(w, "veleria", {"type": "propaganda", "target": "kessel",
                                    "message": "government_failing", "magnitude": 1.0})
        self.assertLess(pop_avg(w, "approval", "kessel"), before["kessel"][0])
        self.assertGreater(pop_avg(w, "grievance", "kessel"), before["kessel"][1])
        self.assertEqual((pop_avg(w, "approval", "lissen"), pop_avg(w, "grievance", "lissen")),
                         before["lissen"], "a regional campaign leaves the other regions alone")

    def test_whole_country_reaches_every_region(self):
        w = world()
        before = {p.region: pop_avg(w, "approval", p.region) for p in w.k_pops()}
        answer_month(w, "dorsania", {"type": "propaganda", "target": "country",
                                     "message": "blame_government", "magnitude": 1.0})
        for region, start in before.items():
            with self.subTest(region=region):
                self.assertLess(pop_avg(w, "approval", region), start)

    def test_a_distrusted_state_media_makes_it_land_harder(self):
        drops = {}
        for credibility in (.9, .1):
            w = world(credibility=credibility)
            start = pop_avg(w, "approval", "kessel")
            answer_month(w, "veleria", {"type": "propaganda", "target": "kessel",
                                        "message": "government_failing", "magnitude": .8})
            drops[credibility] = start - pop_avg(w, "approval", "kessel")
        self.assertGreater(drops[.1], drops[.9])

    def test_a_hard_region_takes_a_bigger_hit_than_a_calm_one(self):
        w = world()
        for p in w.k_pops():
            if p.region == "kessel":
                p.grievance, p.hunger, p.income, p.unemployment = .8, .4, .6, .3
            elif p.region == "lissen":
                p.grievance, p.hunger, p.income, p.unemployment = .05, 0.0, 1.0, .03
        k_before = pop_avg(w, "approval", "kessel")
        l_before = pop_avg(w, "approval", "lissen")
        answer_month(w, "veleria", {"type": "propaganda", "target": "country",
                                    "message": "government_failing", "magnitude": 1.0})
        k_drop = k_before - pop_avg(w, "approval", "kessel")
        l_drop = l_before - pop_avg(w, "approval", "lissen")
        self.assertGreater(k_drop, l_drop)

    def test_stir_minority_falls_harder_on_the_minorities(self):
        w = world()
        before = {(ident): pop_avg(w, "approval", "highlands", ident) for ident in ("karamanian", "vell", "imperial")}
        answer_month(w, "veleria", {"type": "propaganda", "target": "highlands",
                                    "message": "stir_minority", "magnitude": 1.0})
        drops = {ident: before[ident] - pop_avg(w, "approval", "highlands", ident) for ident in before}
        self.assertGreater(drops["vell"], drops["karamanian"])
        self.assertGreater(drops["imperial"], drops["karamanian"])

    def test_unrest_rises_in_an_engine_month(self):
        # Grievance is what society.update turns into unrest (society.py: p.unrest = grievance * (1 - fear)),
        # so a full month with the campaign must show more unrest than the same month without it.
        campaign = world(seed=11)
        control = world(seed=11)
        answer_month(campaign, "veleria", {"type": "propaganda", "target": "country",
                                           "message": "government_failing", "magnitude": 1.0})
        engine.step(campaign)
        engine.step(control)
        self.assertGreater(pop_avg(campaign, "unrest"), pop_avg(control, "unrest"))
        self.assertLess(pop_avg(campaign, "approval"), pop_avg(control, "approval"))


class TheCampaignIsRecorded(unittest.TestCase):
    def test_one_foreign_record_with_its_source_and_its_effects(self):
        w = world(month=3, credibility=.4)
        # Engine 30 (T170): a campaign can now be caught, which is not this test's subject; the draw is held high.
        with mock.patch("karamaniya.foreign.rng_for") as seeded:
            seeded.return_value.random.return_value = .99
            answer_month(w, "dorsania", {"type": "propaganda", "target": "dorran",
                                         "message": "blame_government", "magnitude": .7})
        records = w.media.get("campaigns") or []
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["month"], 3)
        self.assertEqual(record["source"], "dorsania")
        self.assertEqual(record["kinds"], ["propaganda"])
        self.assertEqual(record["claims"], [])
        self.assertEqual(record["intensity"], .7)
        self.assertEqual(record["target"], "dorran")
        self.assertEqual(record["message"], "blame_government")
        self.assertTrue(record["executed_by"])
        self.assertFalse(record["defied"])
        self.assertFalse(record["exposed"])
        self.assertLess(record["effects"]["approval"], 0)
        self.assertGreater(record["effects"]["grievance"], 0)
        self.assertAlmostEqual(record["effects"]["credibility"], .4)
        self.assertFalse(record["effects"]["jammed"])

    def test_the_act_does_not_write_the_state_medias_fields(self):
        w = world(credibility=.55)
        w.media["line"] = {"kinds": ["praise_government"]}
        w.media["boost"] = .04
        snapshot = {"credibility": w.media["credibility"], "line": dict(w.media["line"]),
                    "boost": w.media["boost"]}
        answer_month(w, "veleria", {"type": "propaganda", "target": "country",
                                    "message": "government_failing", "magnitude": 1.0})
        self.assertEqual(w.media["credibility"], snapshot["credibility"])
        self.assertEqual(w.media["line"], snapshot["line"])
        self.assertEqual(w.media["boost"], snapshot["boost"])

    def test_a_replayed_month_does_not_apply_twice(self):
        w = world()
        out, _ = read("veleria", {"type": "propaganda", "target": "kessel",
                                  "message": "government_failing", "magnitude": 1.0})
        positions = foreign.positions(w)
        foreign._apply_cabinet_decisions(w, positions, {"veleria": out})
        one = pop_avg(w, "approval", "kessel")
        foreign._apply_cabinet_decisions(w, positions, {"veleria": out})
        self.assertEqual(pop_avg(w, "approval", "kessel"), one)
        self.assertEqual(len(w.media["campaigns"]), 1)


class JammingIsASettingWithItsCosts(unittest.TestCase):
    def test_the_setting_is_open_by_default_and_held_by_the_interior(self):
        self.assertEqual(Policy().foreign_broadcasts, "open")
        self.assertEqual(politics.ENUMS["foreign_broadcasts"], ("open", "jammed"))
        self.assertEqual(politics.LEVER_OFFICE["foreign_broadcasts"], "interior")
        self.assertEqual(politics.parse_lever("foreign_broadcasts", "jammed"), "jammed")
        self.assertIsNone(politics.parse_lever("foreign_broadcasts", "silent"))

    def test_a_set_policy_motion_sets_it(self):
        w = world()
        mo = {"type": "set_policy", "subject": "foreign_broadcasts", "value": "jammed",
              "text": "Jam foreign broadcasts."}
        self.assertIsNone(politics.validate_motion_detail(w, mo))
        politics.apply_motion(w, mo)
        self.assertEqual(w.policy.foreign_broadcasts, "jammed")
        self.assertEqual(w.const.directives["foreign_broadcasts"], "jammed")

    def test_jamming_lowers_the_democracy_index_while_it_stands(self):
        w = world()
        open_index = democracy_index(w)
        w.policy.foreign_broadcasts = "jammed"
        self.assertLess(democracy_index(w), open_index)
        w.policy.foreign_broadcasts = "open"
        self.assertEqual(democracy_index(w), open_index)

    def test_jamming_cuts_the_union_effect(self):
        drops = {}
        for setting in ("open", "jammed"):
            w = world()
            w.policy.foreign_broadcasts = setting
            start = pop_avg(w, "approval", "kessel")
            answer_month(w, "veleria", {"type": "propaganda", "target": "kessel",
                                        "message": "government_failing", "magnitude": 1.0})
            drops[setting] = start - pop_avg(w, "approval", "kessel")
        self.assertGreater(drops["open"], drops["jammed"])
        self.assertGreater(drops["jammed"], 0)

    def test_jamming_costs_credibility_each_month_once(self):
        w = world(month=2, credibility=.6)
        w.policy.foreign_broadcasts = "jammed"
        foreign.broadcast_month(w)
        first = w.media["credibility"]
        self.assertLess(first, .6)
        foreign.broadcast_month(w)
        self.assertEqual(w.media["credibility"], first, "the month's cost is applied once")
        w.month = 3
        foreign.broadcast_month(w)
        self.assertLess(w.media["credibility"], first)

    def test_an_open_setting_costs_nothing(self):
        w = world(credibility=.6)
        foreign.broadcast_month(w)
        self.assertEqual(w.media["credibility"], .6)

    def test_the_setting_survives_a_checkpoint(self):
        w = world()
        w.policy.foreign_broadcasts = "jammed"
        loaded = World.from_dict(w.to_dict())
        self.assertEqual(loaded.policy.foreign_broadcasts, "jammed")

    def test_the_delegates_are_told_the_setting_and_its_costs(self):
        text = prompts.RULES
        self.assertIn("foreign_broadcasts", text)
        self.assertIn("open", text)
        self.assertIn("jammed", text)
        self.assertIn("trust in the state media", text)
        self.assertIn("democratic", text)
        jammed = world()
        jammed.policy.foreign_broadcasts = "jammed"
        self.assertIn("foreign_broadcasts jammed", briefing.settings_block(jammed))


class TheCabinetIsToldTheActsShape(unittest.TestCase):
    def test_the_cabinet_prompt_states_the_acts_limits(self):
        for actor in ACTORS:
            with self.subTest(actor=actor):
                text = foreign.cabinet_system_prompt(actor, "hawk")
                self.assertIn("propaganda", text)
                self.assertIn("target", text)
                for message in MESSAGES:
                    self.assertIn(message, text)
                self.assertIn("0 to 1", text)

    def test_the_catalog_entry_describes_it_without_judging_it(self):
        for actor in ACTORS:
            entry = next(a for a in foreign.action_catalog(actor) if a["type"] == "propaganda")
            text = " ".join(str(v) for v in entry.values()).lower()
            self.assertIn("target", text)
            self.assertIn("message", text)
            for word in ("lie", "lying", "good", "bad", "risky", "expected"):
                self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
