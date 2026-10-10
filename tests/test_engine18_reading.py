"""World engine 18: the neighbours read how firm Karamaniya looks, and Karamaniya's diplomats report it.

In run 20261010-070501-seed1 the council met three ultimatums with talks, invited the Union into a joint inquiry, stood
its patrols down and left the army at 28,000 against 100,000. The Velerian cabinet saw only troop estimates and approval
polls, and the Union's own rules read only the force ratio and cohesion, so appeasement had no strategic cost. These
tests pin what the cabinets are shown of that figure (resolve.py), how it moves the Union's odds of war and its demand
for land, and the cable the head's office reports each month. No delegate is told what to decide: the world reacts to
what Karamaniya does.
"""
import copy
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import director, foreign, foreign_force, intelligence, motion_actions, politics, resolve  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

PROTEST = ("Issue a formal protest to the Union over the Month 5 shooting on the eastern border. Demand a joint "
           "fact-finding investigation with published findings within one month and a mutual stand-down of patrols "
           "near the incident sector pending findings.")
HEAD_BEFORE = ("league_stance", "union_cohesion", "coalition_stability", "union_intent")


def world(seed: int = 5, version: int | None = None):
    w = new_world(seed, 36, agent_architecture_version=version)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def diplomacy(subject, target, text="Talks.", value=""):
    return {"type": "diplomacy", "subject": subject, "value": value, "text": text, "votes": {m: "yes" for m in "ABCDE"},
            "action": {"action_type": subject, "target": target}}


def protested(seed: int = 5):
    """The council's protest to the Union in Month 5, with the joint inquiry and the stand-down it offers (the motion
    passed): the same motion as test_engine18_resolve."""
    w = world(seed)
    w.month = 4
    politics.apply_motion(w, diplomacy("diplomatic_protest", motion_actions.SOLVARAN_UNION, PROTEST))
    return w


def odds(value: float, ratio: float = 2.3, deadline: int = 0, month: int = 4):
    """A world where only the figure varies between two calls. The Union is cohesive (.8), Veleria's risk tolerance is
    .5 (a war threshold of 2.275 before the figure) and an ultimatum runs to `deadline`. The rivals' armies are scaled so
    the force ratio is `ratio`; scaling every rival by one factor leaves the Union's quality unchanged."""
    w = world()
    w.month = month
    w.foreign["union"]["cohesion"] = .8
    w.foreign["actors"]["veleria"]["disposition"]["risk_tolerance"] = .5
    w.foreign["actors"]["veleria"]["threat_perception"]["karamaniya"] = .3
    w.dip.ultimatum = {"issued": 0, "deadline": deadline, "terms": "Open negotiations on Karamaniya's status.",
                       "terms_id": "status_talks", "by": "veleria"}
    resolve.state(w)["value"] = value
    scale = ratio / director._power_ratio(w)
    for rival in w.rivals.values():
        rival.army *= scale
    return w


def union_rule(value: float, agreement: float):
    """Whether the Union's own rule sets an ultimatum this month, and the agreement the month's positions give.
    Veleria's coal embargo sets that agreement (Dorsania supports the Union, so alignment is full); no cabinet acts."""
    w = world()
    w.month = 4
    resolve.state(w)["value"] = value
    w.foreign["union"]["cohesion"] = .9
    w.foreign["cabinet_month"] = {}
    positions = foreign.positions(w)
    positions["veleria"].update(ultimatum=True, coal_embargo=.22 + (.75 - agreement) / .3)
    positions["dorsania"].update(union="support", grain_embargo=0.0)
    with mock.patch.object(foreign, "_issue_ultimatum") as issue:
        foreign.resolve_union(w, positions, {})
    return issue.called, round(1 - w.foreign["union"]["policy_disagreement"], 2)


def cable_of(w):
    return next(r for r in intelligence.generate(w) if r["office"] == "head" and r["subject"] == "foreign_reading")


def word_for(estimate: float) -> str:
    return next(label for floor, label in resolve.WORDS if estimate / 100 >= floor)


class WhatTheCabinetsSee(unittest.TestCase):
    def test_a_new_world_reads_uncertain_with_nothing_behind_it(self):
        for actor in ("veleria", "dorsania"):
            with self.subTest(actor=actor):
                view = foreign_force.cabinet_view(world(), actor)["karamaniya_as_you_see_it"]["resolve"]
                self.assertEqual(view, {"reading": "uncertain", "evidence": []})

    def test_a_protest_with_an_inquiry_and_a_stand_down_reads_as_wavering_and_says_why(self):
        view = foreign_force.cabinet_view(protested(), "veleria")["karamaniya_as_you_see_it"]["resolve"]
        self.assertEqual(view["reading"], "wavering")
        self.assertEqual(sorted(view["evidence"]), sorted([
            "a protest to the Solvaran Union in Month 5",
            "a stand-down of Karamanian patrols offered to the Solvaran Union in Month 5",
            "a joint inquiry offered to the Solvaran Union in Month 5"]), view)

    def test_the_cabinet_is_shown_the_word_and_its_evidence_and_no_figure(self):
        view = foreign_force.cabinet_view(protested(), "dorsania")["karamaniya_as_you_see_it"]["resolve"]
        self.assertEqual(set(view), {"reading", "evidence"})
        self.assertEqual(view["reading"], "wavering")

    def test_a_policy_move_is_dated_when_its_reason_does_not_name_a_month(self):
        w = world()
        resolve.monthly(w)                       # the first look records the policy in force
        w.month, w.policy.recruitment = 2, "partial"
        resolve.monthly(w)
        view = foreign_force.cabinet_view(w, "veleria")["karamaniya_as_you_see_it"]["resolve"]
        self.assertIn("recruitment raised to partial in Month 3", view["evidence"], view)

    def test_at_most_four_moves_from_the_last_six_months_are_shown_newest_first(self):
        w = world()
        for month in range(8):
            w.month = month
            resolve.note(w, "protest", f"a protest in Month {month + 1}")
        w.month = 7
        view = foreign_force.cabinet_view(w, "veleria")["karamaniya_as_you_see_it"]["resolve"]
        self.assertEqual(view["evidence"], ["a protest in Month 8", "a protest in Month 7",
                                            "a protest in Month 6", "a protest in Month 5"])


class WhatTheCabinetIsToldOfIt(unittest.TestCase):
    def test_the_standing_instructions_say_what_the_field_is_and_where_it_comes_from(self):
        for actor in ("veleria", "dorsania"):
            with self.subTest(actor=actor):
                text = foreign.cabinet_system_prompt(actor, "hawk")
                self.assertIn("karamaniya_as_you_see_it.resolve sums up how firm Karamaniya has looked to your "
                              "government lately, from what it visibly did (its concessions, inquiries, stand-downs, "
                              "arming, alliances and demands left to lapse).", text)
                self.assertIn("Decide from your current beliefs and interests.", text)


class TheUnionsOdds(unittest.TestCase):
    def test_the_threshold_is_unchanged_at_the_neutral_figure_and_scales_at_the_ends(self):
        base = director.war_threshold(odds(.5))
        self.assertAlmostEqual(base, 2.275, places=6)           # 2.0 + .55 * .5 risk tolerance
        self.assertAlmostEqual(director.war_threshold(odds(.2)), base * .88, places=6)
        self.assertAlmostEqual(director.war_threshold(odds(.9)), base * 1.16, places=6)

    def test_the_threshold_keeps_the_alliance_and_pact_factors_under_the_figure(self):
        w = odds(.5)
        w.dip.league_alliance = True
        self.assertAlmostEqual(director.war_threshold(w), 2.275 * 1.25, places=6)

    def test_a_yielding_karamaniya_is_invaded_at_odds_the_union_refuses_against_a_firm_one(self):
        low, high = odds(.2), odds(.8)
        ratio = director._power_ratio(low)
        self.assertEqual(ratio, director._power_ratio(high))
        t_low, t_high = director.war_threshold(low), director.war_threshold(high)
        self.assertTrue(director.war_rule(low), f"force ratio {ratio:.3f} against a threshold of {t_low:.3f} "
                                                "at resolve .2 (expected war)")
        self.assertFalse(director.war_rule(high), f"force ratio {ratio:.3f} against a threshold of {t_high:.3f} "
                                                  "at resolve .8 (expected no war)")

    def test_a_demand_standing_against_a_yielding_karamaniya_is_a_reason_to_invade(self):
        self.assertTrue(director.war_rule(odds(.2, ratio=4.0, deadline=9)))
        self.assertFalse(director.war_rule(odds(.35, ratio=4.0, deadline=9)))     # .35 is not yet yielding
        no_demand = odds(.2, ratio=4.0, deadline=9)
        no_demand.dip.ultimatum = {}
        self.assertFalse(director.war_rule(no_demand))

    def test_no_war_begins_in_month_1_whatever_the_figure(self):
        self.assertEqual(foreign_force.FIRST_WAR_MONTH, 1)
        for value in (.05, .2, .5, .95):
            with self.subTest(resolve=value):
                w = odds(value, ratio=4.0, deadline=0, month=0)
                self.assertFalse(director.war_rule(w))
                w.month = 1
                self.assertTrue(director.war_rule(w))


class TheUnionsDemand(unittest.TestCase):
    def test_a_yielding_karamaniya_is_asked_for_kessel_valley_as_a_cabinet_would_ask_for_it(self):
        w = world()
        w.month = 4
        resolve.state(w)["value"] = .2
        foreign._issue_ultimatum(w)
        ult = w.dip.ultimatum
        self.assertEqual((ult["terms_id"], ult["region"], ult["by"]), ("cede_region", "kessel", "veleria"))
        self.assertEqual(ult["deadline"], w.month + 4)
        self.assertEqual(ult["terms"], "Cede Kessel Valley to Veleria.")
        self.assertEqual(foreign_force.land_demands(w, "kessel"), ["veleria"])
        self.assertEqual(w.institutions["territorial_demands"][-1]["region"], "kessel")

    def test_an_unmet_demand_for_kessel_is_enforced_when_the_troops_are_at_the_border(self):
        w = world()
        w.month = 4
        resolve.state(w)["value"] = .2
        foreign._issue_ultimatum(w)
        w.month = w.dip.ultimatum["deadline"]
        w.dip.border_forces = {"veleria": {"north": 9000.0, "east": 0.0}}
        director._deadline_policy(w)
        self.assertTrue(w.dip.war)
        self.assertEqual((w.dip.war_aim["aim"], w.dip.war_aim["front"], w.dip.war_aim["objective"]),
                         ("limited", "north", "kessel"))

    def test_a_firmer_karamaniya_gets_the_status_demand_and_a_lost_valley_is_not_asked_for(self):
        for value in (.36, .6):
            with self.subTest(resolve=value):
                w = world()
                w.month = 4
                resolve.state(w)["value"] = value
                foreign._issue_ultimatum(w)
                self.assertNotIn("terms_id", w.dip.ultimatum)
                self.assertEqual(w.dip.ultimatum["deadline"], 8)
        lost = world()
        lost.month = 4
        resolve.state(lost)["value"] = .2
        lost.region("kessel").controller = "union"
        foreign._issue_ultimatum(lost)
        self.assertNotIn("terms_id", lost.dip.ultimatum)

    def test_the_unions_rule_gives_a_demand_at_a_lower_agreement_when_karamaniya_yields(self):
        # The bar is .70 - .3 * (.5 - figure): .61 at a figure of .2 and .70 at .6. The agreement .65 lies between
        # the two bars, so it fires at .2 and not at .6. An agreement of .60 is below the bar even at .2.
        for value, agreement, issued in ((.2, .65, True), (.6, .65, False), (.2, .60, False), (.6, .72, True)):
            with self.subTest(resolve=value, agreement=agreement):
                called, got = union_rule(value, agreement)
                self.assertAlmostEqual(got, agreement, places=2)
                self.assertEqual(called, issued)


class TheDiplomatsCable(unittest.TestCase):
    def test_the_head_reports_how_veleria_reads_karamaniya_and_what_it_cites(self):
        cable = cable_of(protested())
        self.assertEqual(cable["office"], "head")
        self.assertEqual(cable["confidence"], "medium")
        self.assertEqual(cable["text"], (
            f"Diplomatic cables: Veleria's government reads Karamaniya as {word_for(cable['estimate'])} "
            f"({cable['low']:.0f}-{cable['high']:.0f}/100); what it cites: a protest to the Solvaran Union in Month 5; "
            "a stand-down of Karamanian patrols offered to the Solvaran Union in Month 5; "
            "a joint inquiry offered to the Solvaran Union in Month 5. Confidence: medium."))

    def test_no_other_office_reports_the_cable(self):
        reports = intelligence.generate(protested())
        self.assertEqual({r["office"] for r in reports if r["subject"] == "foreign_reading"}, {"head"})

    def test_the_other_head_reports_are_the_same_with_and_without_the_cable(self):
        w = protested()
        without = copy.deepcopy(w)
        with mock.patch.dict(intelligence.SUBJECTS, {"head": HEAD_BEFORE}):
            before = {r["subject"]: r for r in intelligence.generate(without) if r["office"] == "head"}
        after = {r["subject"]: r for r in intelligence.generate(w)
                 if r["office"] == "head" and r["subject"] != "foreign_reading"}
        self.assertEqual(set(before), set(HEAD_BEFORE))
        self.assertEqual(set(after), set(HEAD_BEFORE))
        for subject in HEAD_BEFORE:
            for field in ("id", "estimate", "low", "high", "error", "text"):
                self.assertEqual(after[subject][field], before[subject][field], (subject, field))

    def test_a_cable_below_35_is_alarming_and_held_back_unless_it_is_shared(self):
        self.assertTrue(intelligence._alarming("foreign_reading", 34.9))
        self.assertFalse(intelligence._alarming("foreign_reading", 35))
        w = world()
        w.month = 4
        resolve.state(w)["value"] = .1
        with mock.patch.object(intelligence, "_error", return_value="none"):
            cable = cable_of(w)
        self.assertLess(cable["estimate"], 35)
        self.assertTrue(cable["alarming"])
        self.assertIn(cable["id"], [item["report_id"] for item in intelligence.flag_withheld(w)])

    def test_a_firm_karamaniya_gets_a_cable_that_is_not_alarming(self):
        w = world()
        w.month = 4
        resolve.state(w)["value"] = .9
        with mock.patch.object(intelligence, "_error", return_value="none"):
            cable = cable_of(w)
        self.assertGreater(cable["estimate"], 35)
        self.assertFalse(cable["alarming"])

    def test_a_world_without_the_figure_has_no_cable(self):
        old = world(version=1)
        self.assertNotIn("foreign_reading", {r["subject"] for r in intelligence.generate(old)})


class GroundingStillWorks(unittest.TestCase):
    def test_a_delegate_may_cite_the_cable_its_colleague_shared(self):
        w = protested()
        cable = cable_of(w)
        intelligence.share(w, "A", [{"report_id": cable["id"], "with": "council"}], "session")
        claim = f"Veleria reads us as {word_for(cable['estimate'])} ({cable['low']:.0f}-{cable['high']:.0f}/100)."
        self.assertIsNone(motion_actions.check_numeric_grounding(w, "B", claim))

    def test_the_cables_reasons_do_not_ground_a_figure_about_unrest(self):
        # The reasons carry the word "protest", but their sentences hold no percentage: no unrest range comes from them.
        w = protested()
        for p in w.k_pops():
            p.unrest = .2
        text = cable_of(w)["text"]
        with mock.patch.object(intelligence, "office_context", lambda *a, **k: text):
            claim = motion_actions.check_numeric_grounding(w, "C", "Unrest will reach 50% next month.")
        self.assertEqual(claim["code"], "NUMERIC_GROUNDING_ERROR", claim)


class NoWarBeforeMonthTwo(unittest.TestCase):
    def test_a_cabinet_cannot_invade_in_month_1_whatever_the_figure(self):
        invade = {"type": "invade", "front": "north", "aim": "limited"}
        for value in (.05, .5, .95):
            with self.subTest(resolve=value):
                w = odds(value, ratio=4.0, deadline=0, month=0)
                w.dip.border_forces = {"veleria": {"north": 9000.0, "east": 0.0}}     # enough to cross, were it allowed
                self.assertEqual(foreign_force.check(w, "veleria", invade),
                                 "no invasion or blockade can begin before Month 2")
                w.month = 1
                self.assertIsNone(foreign_force.check(w, "veleria", invade))


if __name__ == "__main__":
    unittest.main()
