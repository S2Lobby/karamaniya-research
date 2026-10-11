"""World engine 17: a neighbour can demand a border region, and the council can give it up or refuse (territory.py).

In run 20261010-070501-seed1 Veleria's cabinet, played by a model, issued three ultimatums: "status_talks" in Months 3
and 6 and "protect_imperial_citizens" in Month 8. It never demanded land, although its aims said "if nothing more can
be had, Kessel Valley": no term it could set was land, so the limited war a cabinet could start for the valley had no
demand behind it. These tests cover the demand, the council's answer (a cession), and the refusal the rules enforce.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import agents, director, foreign, foreign_force  # noqa: E402
from karamaniya import ministries, motion_actions, politics, public_mood, standing  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def world(seed: int = 3):
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    # An audience comes with the office a delegate holds (agents.audiences_for, refreshed each month in a run).
    for m in w.members:
        m.agent_state["constituencies"] = agents.audiences_for(w, m.id)
    return w


def act(w, actor, **action):
    action.setdefault("magnitude", .5)
    error = foreign_force.check(w, actor, action)
    if error is None:
        foreign_force.apply(w, actor, action)
    return error


def demand(w, region="kessel", by="veleria", months=2):
    """A neighbour demands a region in Month 1 (index 0); the demand's deadline is `months` later."""
    return act(w, by, type="ultimatum", terms="cede_region", region=region, deadline_months=months)


def cession_motion(region="Kessel Valley", target="VELERIA"):
    return {"id": "M1", "type": "diplomacy", "subject": "cede_region", "value": region,
            "text": f"Cede {region} to {target.title()}.", "action": {"target": target}, "proposer": "A"}


def council_cedes(w, motion):
    """The motion passes and is queued as a proposal, and the neighbour that demanded the region answers it."""
    politics.apply_motion(w, dict(motion, passed=True))
    director._answer_proposals(w)


class TheDemand(unittest.TestCase):
    def test_veleria_may_demand_kessel_and_dorran(self):
        w = world()
        for region in ("kessel", "dorran"):
            with self.subTest(region=region):
                self.assertIsNone(foreign_force.check(w, "veleria", {"type": "ultimatum", "terms": "cede_region",
                                                                     "region": region, "deadline_months": 3}))

    def test_it_refuses_land_off_its_fronts_and_the_capital(self):
        w = world()
        for region in ("aster", "highlands"):
            with self.subTest(region=region):
                error = foreign_force.check(w, "veleria", {"type": "ultimatum", "terms": "cede_region",
                                                           "region": region, "deadline_months": 3})
                self.assertIn("Veleria may demand only Kessel Valley or Dorran March", error)

    def test_dorsania_may_demand_only_dorran(self):
        w = world()
        self.assertIsNone(foreign_force.check(w, "dorsania", {"type": "ultimatum", "terms": "cede_region",
                                                              "region": "dorran", "deadline_months": 3}))
        error = foreign_force.check(w, "dorsania", {"type": "ultimatum", "terms": "cede_region",
                                                    "region": "kessel", "deadline_months": 3})
        self.assertIn("Dorsania may demand only Dorran March", error)

    def test_land_karamaniya_no_longer_holds_cannot_be_demanded(self):
        w = world()
        w.region("kessel").controller = "union"
        error = foreign_force.check(w, "veleria", {"type": "ultimatum", "terms": "cede_region", "region": "kessel",
                                                   "deadline_months": 3})
        self.assertIn("no longer holds Kessel Valley", error)

    def test_the_demand_is_stored_with_its_region_and_says_what_and_when(self):
        w = world()
        self.assertIsNone(demand(w, "kessel", "veleria", 2))
        ult = w.dip.ultimatum
        self.assertEqual((ult["region"], ult["by"], ult["deadline"]), ("kessel", "veleria", 2))
        self.assertIn("Cede Kessel Valley to Veleria", ult["terms"])
        self.assertIn("Veleria demands: Cede Kessel Valley to Veleria. It expects an answer by Month 3.",
                      [m["text"] for m in w.dip.inbox])
        self.assertTrue(any(e["kind"] == "ultimatum" and e["text"].endswith("by Month 3.") for e in w.events))

    def test_a_demand_for_land_rallies_harder_than_the_others(self):
        land, other = world(), world()
        demand(land, "kessel", "veleria", 2)
        act(other, "veleria", type="ultimatum", terms="status_talks", deadline_months=2)
        self.assertAlmostEqual(land.dip.rally, .25)
        self.assertAlmostEqual(other.dip.rally, .16)

    def test_the_cabinet_reply_and_the_engine_accept_it_with_its_region(self):
        w = world()
        out, problems = foreign.normalize_cabinet_output("veleria", {"actions": [
            {"type": "ultimatum", "terms": "cede_region", "region": "kessel", "deadline_months": 2}]})
        self.assertEqual(problems, [])
        self.assertEqual(out["actions"], [{"type": "ultimatum", "magnitude": .5, "terms": "cede_region",
                                           "region": "kessel", "deadline_months": 2}])
        self.assertIsNone(foreign.validate_action("veleria", dict(out["actions"][0]), {}, w))


class TheCouncilsAnswer(unittest.TestCase):
    def test_a_cession_with_no_demand_behind_it_is_refused_plainly(self):
        rejection = politics.validate_motion_detail(world(), cession_motion("Lissen Coast"))
        self.assertEqual(rejection["reason_code"], "NOT_DEMANDED")
        self.assertEqual(rejection["explanation"],
                         "a region can only be ceded to a neighbour that has demanded it; no one has demanded Lissen Coast")

    def test_with_veleria_demanding_kessel_the_motion_is_valid_to_veleria_only(self):
        w = world()
        demand(w, "kessel", "veleria", 2)
        self.assertIsNone(politics.validate_motion_detail(w, cession_motion("Kessel Valley", "VELERIA")))
        to_dorsania = politics.validate_motion_detail(w, cession_motion("Kessel Valley", "DORSANIA"))
        self.assertEqual(to_dorsania["explanation"],
                         "a region can only be ceded to a neighbour that has demanded it; "
                         "Kessel Valley has been demanded by Veleria, not Dorsania")
        other_region = politics.validate_motion_detail(w, cession_motion("Dorran March", "VELERIA"))
        self.assertEqual(other_region["explanation"], "a region can only be ceded to a neighbour that has demanded it; "
                                                      "no one has demanded Dorran March")

    def test_the_union_is_not_a_neighbour_that_can_be_given_land(self):
        w = world()
        demand(w, "kessel", "veleria", 2)
        rejection = politics.validate_motion_detail(w, cession_motion("Kessel Valley", "UNION"))
        self.assertEqual(rejection["reason_code"], "ACTION_NOT_VALID_FOR_TARGET")

    def test_the_council_gives_up_the_region_when_the_motion_passes(self):
        w = world()
        demand(w, "kessel", "veleria", 2)
        total = sum(p.size for p in w.pops)
        expected_flight = sum(p.size * (.02 if p.ident == "imperial" else .25) for p in w.pops if p.region == "kessel")
        council_cedes(w, cession_motion())
        self.assertEqual(w.region("kessel").controller, "union")
        self.assertNotIn("kessel", [r.id for r in w.k_regions()])
        self.assertTrue(all(p.region != "kessel" for p in w.k_pops()))
        self.assertAlmostEqual(w.counters["refugees"], expected_flight, delta=expected_flight * 1e-6)
        self.assertAlmostEqual(sum(p.size for p in w.pops), total, delta=total * 1e-9)
        self.assertTrue(any(e["kind"] == "cession" and e["text"] == "Karamaniya has ceded Kessel Valley to Veleria."
                            for e in w.events))

    def test_the_cession_is_recorded_and_clears_the_demand_and_veleria_accepts_it(self):
        w = world()
        demand(w, "kessel", "veleria", 2)
        council_cedes(w, cession_motion())
        self.assertEqual(w.dip.ultimatum, {})
        self.assertEqual(w.institutions["ceded"], {"kessel": {"to": "veleria", "month": 0}})
        self.assertIn("Veleria accepts Kessel Valley, which Karamaniya has handed over.",
                      [m["text"] for m in w.dip.inbox])

    def test_the_army_resents_it_the_public_turns_and_the_receiving_power_warms(self):
        w = world()
        demand(w, "kessel", "veleria", 2)
        relations = w.foreign["actors"]["veleria"]["relations"]["karamaniya"]
        hostility, trust = relations["hostility"], relations["trust"]
        council_cedes(w, cession_motion())
        self.assertAlmostEqual(ministries.grievance(w, "army"), .15, places=4)
        self.assertAlmostEqual(ministries.grievance(w, "interior"), .05, places=4)
        approval = [r for r in public_mood.active(w, "territory") if r["kind"] == "approval"]
        self.assertEqual([(r["where"], r["value"]) for r in approval], [("ident:karamanian", -.02)])
        self.assertAlmostEqual(relations["hostility"], round(hostility - .1, 3), places=3)
        self.assertAlmostEqual(relations["trust"], round(trust + .05, 3), places=3)

    def test_before_the_vote_the_army_sees_its_officers_sour_sharply(self):
        w = world()
        motion = cession_motion()
        exposure = standing.vote_exposure(w, "D", motion)
        self.assertLess(exposure["yes"]["senior officers"], -.035)
        text = standing.exposure_text(w, "D", [dict(motion, summary="cede Kessel Valley")])
        self.assertIn("senior officers (sharply)", text)

    def test_dorsania_is_given_dorran_when_it_demanded_it(self):
        w = world()
        self.assertIsNone(act(w, "dorsania", type="ultimatum", terms="cede_region", region="dorran", deadline_months=2))
        motion = cession_motion("Dorran March", "DORSANIA")
        self.assertIsNone(politics.validate_motion_detail(w, motion))
        council_cedes(w, motion)
        self.assertEqual(w.institutions["ceded"], {"dorran": {"to": "dorsania", "month": 0}})
        self.assertEqual(w.region("dorran").controller, "union")
        self.assertEqual(w.dip.ultimatum, {})


class ProseAndNegation(unittest.TestCase):
    def test_we_will_never_cede_kessel_valley_does_not_read_as_the_act(self):
        w = world()
        for text in ("We will never cede Kessel Valley.", "No cession of Kessel Valley.",
                     "We will not give up Dorran March."):
            with self.subTest(text=text):
                self.assertNotIn("cede_region", motion_actions.prose_intent(w, text)["actions"])

    def test_a_motion_that_cedes_a_region_reads_as_the_act(self):
        self.assertEqual(motion_actions.prose_intent(world(), "Cede Kessel Valley to Veleria.")["actions"],
                         ["cede_region"])


class TheRulesEnforceTheDemand(unittest.TestCase):
    def test_with_the_troops_ready_the_expired_demand_starts_a_limited_war_for_the_region(self):
        w = world()
        demand(w, "kessel", "veleria", 2)
        w.month = 2
        w.dip.border_forces["veleria"]["north"] = 15000
        director._deadline_policy(w)
        self.assertTrue(w.dip.war)
        self.assertEqual((w.dip.war_aim["by"], w.dip.war_aim["aim"], w.dip.war_aim["objective"]),
                         ("veleria", "limited", "kessel"))
        self.assertEqual(w.dip.ultimatum, {})
        self.assertTrue(any(e["kind"] == "ultimatum_enforced" and "cede Kessel Valley" in e["text"] for e in w.events))

    def test_with_too_few_troops_the_embargo_path_runs_and_no_war_starts(self):
        w = world()
        demand(w, "kessel", "veleria", 2)
        w.month = 2
        w.dip.border_forces["veleria"]["north"] = 1000
        director._deadline_policy(w)
        self.assertFalse(w.dip.war)
        self.assertGreaterEqual(w.dip.grain_embargo, .75)

    def test_no_war_begins_in_month_one_however_ready_the_troops(self):
        w = world()
        w.mil.navy.size = 20     # keeps the embargo path from also setting a blockade, which would hide the war
        w.dip.ultimatum = {"issued": 0, "deadline": 0, "terms": "Cede Kessel Valley to Veleria.",
                           "terms_id": "cede_region", "by": "veleria", "region": "kessel"}
        w.dip.border_forces["veleria"]["north"] = 15000
        w.month = 0
        director._deadline_policy(w)
        self.assertFalse(w.dip.war)
        w.month = 1
        director._deadline_policy(w)
        self.assertTrue(w.dip.war)


class WhatTheCabinetsSee(unittest.TestCase):
    def test_the_demand_names_its_region_and_its_front_and_whether_it_was_ceded(self):
        w = world()
        demand(w, "kessel", "veleria", 2)
        view = foreign_force.ultimatum_compliance(w)
        self.assertEqual(view["region"], "Kessel Valley")
        self.assertFalse(view["observed"]["ceded"])
        self.assertEqual((view["observed"]["front"], view["observed"]["front_starts_at"]),
                         ("north", "Kessel Valley"))
        self.assertIn("karamanian_soldiers_on_the_north_front", view["observed"])

    def test_once_ceded_the_demand_is_shown_as_met_until_it_lapses(self):
        w = world()
        demand(w, "kessel", "veleria", 2)
        council_cedes(w, cession_motion())
        met = foreign_force.ultimatum_compliance(w)
        self.assertTrue(met["met"])
        self.assertTrue(met["observed"]["ceded"])
        w.month = 2 + foreign_force.LAPSE_MONTHS + 1
        self.assertIsNone(foreign_force.ultimatum_compliance(w))

    def test_the_cabinet_is_told_the_land_was_handed_over_under_threat(self):
        w = world()
        demand(w, "kessel", "veleria", 2)
        self.assertNotIn("ceded_under_threat", foreign_force.cabinet_view(w, "veleria")["confrontation"])
        council_cedes(w, cession_motion())
        self.assertEqual(foreign_force.cabinet_view(w, "veleria")["confrontation"]["ceded_under_threat"],
                         [{"region": "Kessel Valley", "to": "Veleria", "month": 1}])


class WhenTheDemandEnds(unittest.TestCase):
    def test_a_region_lost_in_war_ends_the_demand(self):
        w = world()
        demand(w, "kessel", "veleria", 2)
        w.region("kessel").controller = "union"
        director._deadline_policy(w)
        self.assertEqual(w.dip.ultimatum, {})

    def test_a_lapsed_demand_allows_a_cession_only_in_the_month_it_lapses(self):
        # Audit FO16: the demand is due in Month 3 (index 2) and lapses in Month 4 (index 3); after that it is no basis.
        w = world()
        demand(w, "kessel", "veleria", 2)
        w.dip.ultimatum = {}
        w.month = 3
        self.assertIsNone(politics.validate_motion_detail(w, cession_motion()))
        w.month = 4
        self.assertEqual(politics.validate_motion_detail(w, cession_motion())["reason_code"], "NOT_DEMANDED")

    def test_a_cession_of_a_region_no_longer_held_is_refused(self):
        w = world()
        demand(w, "kessel", "veleria", 2)
        w.region("kessel").controller = "union"
        rejection = politics.validate_motion_detail(w, cession_motion())
        self.assertIn("does not hold Kessel Valley", rejection["explanation"])


if __name__ == "__main__":
    unittest.main()
