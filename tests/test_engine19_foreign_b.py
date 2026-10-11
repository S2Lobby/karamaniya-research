"""World engine 19, the Union's rules, the director and the cabinets' estimates (audit slice of docs/AUDIT_ENGINE18.md).

Each class pins one finding of the engine 18 audit. The findings were reproduced by the auditors' proof scripts; the
tests here assert the behaviour the fix makes true, and each one fails on engine 18. No delegate is told what to decide:
these are the rules of the neighbours and the Union, and what the cabinets are shown of Karamaniya's army.
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import director, fine_print, foreign, foreign_force, operations, resolve  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

DEADLINE = 5
DEMAND = {"issued": 3, "deadline": DEADLINE, "terms": "Withdraw Karamaniyan forces from the regions on the border.",
          "terms_id": "demilitarize_border", "by": "veleria"}


def world(month: int = 2, seed: int = 5):
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    w.month = month
    w.events = []
    return w


def demanded(month: int = DEADLINE):
    """A world with Veleria's demand standing, the Union cohesive, and no cabinet answering this month."""
    w = world(month)
    w.dip.ultimatum = dict(DEMAND)
    w.foreign["union"]["cohesion"] = 0.85
    w.foreign["union"]["military_coordination"] = 0.80
    return w


class ExpiredDemandOnTheUnionsRules(unittest.TestCase):
    """Audit FO9 + MO2: an expired demand on the Union's rules path lapses. Before the fix the rules enforced it again
    every month (the rally rose .18 a month), and a blockade or a war returned before the lapse test, so the demand stood
    and blocked any new one."""

    def test_an_enforced_demand_is_spent_so_the_rules_do_not_enforce_it_again(self):
        w = demanded()
        director._deadline_policy(w)
        self.assertEqual(w.dip.ultimatum, {})
        rally, embargo = w.dip.rally, w.dip.grain_embargo
        for month in (DEADLINE + 1, DEADLINE + 2, DEADLINE + 3):
            w.month = month
            director._deadline_policy(w)
        self.assertEqual((w.dip.rally, w.dip.grain_embargo), (rally, embargo))

    def test_a_blockade_already_in_force_does_not_hold_an_expired_demand_open(self):
        w = demanded()
        w.dip.blockade = True
        director._deadline_policy(w)
        self.assertEqual(w.dip.ultimatum, {})
        self.assertTrue(w.dip.blockade, "a blockade already imposed may continue")
        self.assertIsNone(foreign_force.check(w, "veleria", {"type": "ultimatum", "terms": "status_talks",
                                                              "deadline_months": 2}))

    def test_a_war_in_force_lets_an_expired_demand_lapse(self):
        w = demanded()
        w.dip.war, w.dip.aggressor, w.dip.war_start = True, "union", 1
        director._deadline_policy(w)
        self.assertEqual(w.dip.ultimatum, {})
        self.assertTrue(w.dip.war)

    def test_a_cabinet_that_acts_the_month_after_the_deadline_lapses_it_under_a_blockade(self):
        w = demanded(DEADLINE + 1)
        w.dip.blockade = True
        w.foreign.setdefault("cabinet_month", {})["veleria"] = w.month
        before = w.foreign["actors"]["veleria"]["reputation"]["military_aggressiveness"]
        director._deadline_policy(w)
        self.assertEqual(w.dip.ultimatum, {})
        self.assertLess(w.foreign["actors"]["veleria"]["reputation"]["military_aggressiveness"], before)
        self.assertIn("ultimatum_lapsed", [e["kind"] for e in w.events])

    def test_a_demand_stands_until_its_deadline_whatever_is_in_force(self):
        w = demanded(DEADLINE - 1)
        w.dip.blockade = True
        director._deadline_policy(w)
        self.assertEqual(w.dip.ultimatum["deadline"], DEADLINE)

    def test_a_cabinet_that_imposes_a_blockade_this_month_has_acted_on_its_demand(self):
        w = demanded(DEADLINE + 1)
        w.foreign.setdefault("cabinet_month", {})["veleria"] = w.month
        foreign_force.apply(w, "veleria", {"type": "naval_blockade", "magnitude": .5})
        director._deadline_policy(w)
        self.assertTrue(w.dip.ultimatum)
        self.assertFalse(any(e["kind"] == "ultimatum_lapsed" for e in w.events))


class TheUnionsRuleDemandForStatus(unittest.TestCase):
    """Audit FO5: a status demand the Union's own rule sets names its terms and its neighbour, as a cabinet's does. Before
    the fix it had neither, so talks could not lift it and no cabinet was shown it."""

    def test_the_rule_states_its_terms_and_its_neighbour(self):
        w = world(4)
        foreign._issue_ultimatum(w)
        self.assertEqual((w.dip.ultimatum["terms_id"], w.dip.ultimatum["by"]), ("status_talks", "veleria"))

    def test_talks_lift_the_rules_demand(self):
        w = world(4)
        foreign._issue_ultimatum(w)
        director._union_reply(w, "status_talks")
        self.assertEqual(w.dip.ultimatum, {})
        self.assertIn("lifts its deadline", w.dip.inbox[-1]["text"])

    def test_talks_lift_it_as_they_lift_a_cabinets_status_demand(self):
        cabinet, rule = world(4), world(4)
        foreign_force.apply(cabinet, "veleria", {"type": "ultimatum", "terms": "status_talks", "deadline_months": 3})
        foreign._issue_ultimatum(rule)
        for w in (cabinet, rule):
            director._union_reply(w, "status_talks")
        self.assertEqual((bool(cabinet.dip.ultimatum), bool(rule.dip.ultimatum)), (False, False))

    def test_the_cabinet_is_shown_the_rules_demand(self):
        w = world(4)
        foreign._issue_ultimatum(w)
        shown = foreign_force.cabinet_view(w, "veleria")["confrontation"]["ultimatum"]
        self.assertIsNotNone(shown)
        self.assertEqual((shown["by"], shown["deadline_month"]), ("veleria", w.dip.ultimatum["deadline"] + 1))


def rule_world(month: int = 4, figure: float = .2, balanced: bool = False):
    """A world with no cabinet answering, the Union cohesive, and Karamaniya's figure set. The default Union army is 3.39
    soldiers per Karamanian soldier; `balanced` gives the Union 2.1, below the three-to-one trigger."""
    w = world(month)
    w.foreign["union"]["cohesion"] = 0.8
    w.foreign["union"]["military_coordination"] = 0.8
    resolve.state(w)["value"] = figure
    if balanced:
        w.rivals["veleria"].army, w.rivals["dorsania"].army = 40000.0, 20000.0
    return w


def rule_turn(w) -> None:
    foreign.resolve_union(w, foreign.positions(w), {})


class TheUnionsRuleDemandsWithoutCabinets(unittest.TestCase):
    """Audit FO6: with the foreign cabinets off, the Union's rule never set a demand, because its flag needed a pressure the
    rule-played world never reaches. In a month no cabinet answered, the rule now also demands when Karamaniya looks
    wavering (resolve below .45) or the Union has more than three soldiers per Karamanian soldier, as the baselines'
    stand-in neighbour does (backends/scripted._velerian_demand), from Month 3; a demand the rule set is followed by no
    other for six months."""

    def test_a_yielding_karamaniya_is_demanded_of_when_no_cabinet_answers(self):
        w = rule_world(figure=.2, balanced=True)
        rule_turn(w)
        self.assertEqual(w.dip.ultimatum.get("by"), "veleria")

    def test_a_union_outnumbering_karamaniya_three_to_one_is_demanded_of_too(self):
        w = rule_world(figure=.6)
        rule_turn(w)
        self.assertEqual(w.dip.ultimatum.get("by"), "veleria")

    def test_a_firm_karamaniya_facing_a_balanced_union_is_not_demanded_of(self):
        w = rule_world(figure=.6, balanced=True)
        rule_turn(w)
        self.assertEqual(w.dip.ultimatum, {})

    def test_a_month_a_cabinet_answers_is_left_to_the_cabinet(self):
        w = rule_world(figure=.2, balanced=True)
        foreign.resolve_union(w, foreign.positions(w), {"veleria": {"actions": []}})
        self.assertEqual(w.foreign["cabinet_month"]["veleria"], w.month)
        self.assertEqual(w.dip.ultimatum, {})

    def test_the_rule_waits_six_months_after_its_last_demand_and_records_the_month(self):
        w = rule_world(month=4, figure=.2, balanced=True)
        rule_turn(w)
        self.assertTrue(w.dip.ultimatum)
        self.assertEqual(w.foreign.get("rule_demand_month"), 4)
        w.dip.ultimatum = {}
        w.month = 6
        rule_turn(w)
        self.assertEqual(w.dip.ultimatum, {}, "no second demand inside the six-month cooldown")
        w.month = 10
        rule_turn(w)
        self.assertTrue(w.dip.ultimatum, "a demand again once the cooldown has passed")


class TheArmysAttackPosture(unittest.TestCase):
    """Audit FO7: Karamaniya's own attack posture began a war in Month 1 and began it again each month, undoing a ceasefire
    for as long as the posture stood. No war begins in Month 1; a war the posture began ends with it, and the council must
    order the attack again to resume it."""

    def test_an_attack_ordered_in_month_1_begins_its_war_in_month_2(self):
        w = world(month=0)
        w.policy.posture = "attack"
        director._karamanian_aggression(w)
        self.assertFalse(w.dip.war)
        w.month = 1
        director._karamanian_aggression(w)
        self.assertTrue(w.dip.war)
        self.assertEqual((w.dip.aggressor, w.dip.war_start), ("karamaniya", 1))

    def test_a_ceasefire_resets_the_posture_and_the_war_does_not_restart(self):
        w = world(month=1)
        w.policy.posture = "attack"
        director._karamanian_aggression(w)
        self.assertTrue(w.dip.war)
        director._end_war(w, "ceasefire agreed")
        self.assertEqual(w.policy.posture, "defend")
        self.assertIn("posture", [e["kind"] for e in w.events])
        w.month = 2
        director._karamanian_aggression(w)
        self.assertFalse(w.dip.war, "a ceasefire is not undone by the posture the council no longer holds")
        self.assertTrue(w.dip.ceasefire)

    def test_an_armistice_resets_the_posture_too(self):
        w = world(month=3)
        w.policy.posture = "attack"
        director._karamanian_aggression(w)
        director._end_war(w, "armistice")
        self.assertEqual(w.policy.posture, "defend")

    def test_once_the_council_orders_the_attack_again_the_war_resumes(self):
        w = world(month=1)
        w.policy.posture = "attack"
        director._karamanian_aggression(w)
        director._end_war(w, "ceasefire agreed")
        w.month = 4
        w.policy.posture = "attack"
        director._karamanian_aggression(w)
        self.assertTrue(w.dip.war)
        self.assertEqual(w.dip.war_start, 4)


def output_ratio(w, actor: str) -> float:
    rival = w.rivals[actor]
    return rival.gdp_real / rival.gdp_real0


def implied(actor: str, level: float) -> float:
    return 1 - foreign.EMBARGO_COST[actor] * level


def standing_embargo(w, actor: str, commodity: str, level: float) -> None:
    """An embargo at `level`, charged the way the engine charges one, so the output and the level agree before the act."""
    if commodity == "grain":
        w.dip.grain_embargo = level
    else:
        w.dip.coal_embargo = level
    foreign._embargo_output(w, actor, 0.0, level, "setup", approval=0.0)


class TheExporterOutputFollowsTheEmbargoLevel(unittest.TestCase):
    """Audit FO8: an exporter's output follows an embargo's level on every path that moves the level. Before the fix the
    expired-demand enforcement, a protest, a grain deal and the Union's trade talks and protest moved the level but not
    the output, so the trade an easing gives back was never given back, and a tightening was never paid for."""

    def test_the_rules_enforcement_of_an_expired_demand_charges_the_output_its_level_implies(self):
        w = demanded()
        director._deadline_policy(w)
        self.assertAlmostEqual(w.dip.grain_embargo, .75)
        self.assertAlmostEqual(output_ratio(w, "dorsania"), implied("dorsania", .75), places=9)

    def test_a_grain_deal_gives_back_the_output_its_level_eases_by(self):
        w = world(4)
        standing_embargo(w, "dorsania", "grain", .5)
        foreign.dorsania_reply(w, "grain_deal")
        self.assertAlmostEqual(w.dip.grain_embargo, .38)
        self.assertAlmostEqual(output_ratio(w, "dorsania"), implied("dorsania", .38), places=9)

    def test_a_dorsanian_protest_gives_back_the_output_its_level_eases_by(self):
        w = world(4)
        standing_embargo(w, "dorsania", "grain", .5)
        w.foreign["actors"]["dorsania"]["relations"]["karamaniya"]["trust"] = .6
        director._protest_reply(w, "dorsania")
        self.assertAlmostEqual(w.dip.grain_embargo, .4)
        self.assertAlmostEqual(output_ratio(w, "dorsania"), implied("dorsania", .4), places=9)

    def test_the_unions_trade_talks_and_protest_give_back_the_output_their_level_eases_by(self):
        for kind, eased in (("trade_talks", .3), ("diplomatic_protest", .4)):
            with self.subTest(reply=kind):
                w = world(4)
                standing_embargo(w, "dorsania", "grain", .5)
                director._union_reply(w, kind)
                self.assertAlmostEqual(w.dip.grain_embargo, eased)
                self.assertAlmostEqual(output_ratio(w, "dorsania"), implied("dorsania", eased), places=9)

    def test_a_veleria_protest_gives_back_the_output_its_coal_embargo_eases_by(self):
        w = world(4)
        standing_embargo(w, "veleria", "coal", .5)
        director._protest_reply(w, "veleria")
        self.assertAlmostEqual(w.dip.coal_embargo, .4)
        self.assertAlmostEqual(output_ratio(w, "veleria"), implied("veleria", .4), places=9)


def coal_turn(w, pressure: float, target: float = 0.0) -> None:
    """One month of the Union's positions with Veleria's pressure and coal target set, and no cabinet answering."""
    positions = foreign.positions(w)
    positions["veleria"]["pressure"] = pressure
    positions["veleria"]["coal_embargo"] = target
    foreign.resolve_union(w, positions, {})


class TheVelerianCoalEmbargo(unittest.TestCase):
    """Audit FO11 + FO19: Veleria's coal embargo only ratcheted up (nothing could ease it), and its trade_concession moved
    nothing the engine read. Now a month of Velerian pressure below .3 eases the coal embargo a step, and the concession
    eases it by the step Dorsania's concession eases grain. The ledger records only what changed."""

    def test_below_pressure_point_three_the_coal_embargo_eases_a_step_a_month(self):
        w = world(month=1)
        standing_embargo(w, "veleria", "coal", .30)
        coal_turn(w, pressure=.2)
        self.assertAlmostEqual(w.dip.coal_embargo, .25, places=9)
        self.assertAlmostEqual(output_ratio(w, "veleria"), implied("veleria", .25), places=9)

    def test_at_or_above_point_three_the_step_does_not_happen(self):
        w = world(month=1)
        standing_embargo(w, "veleria", "coal", .30)
        coal_turn(w, pressure=.35)
        self.assertAlmostEqual(w.dip.coal_embargo, .30, places=9)

    def test_the_pressure_step_stops_at_zero_and_the_coal_embargo_can_be_lifted(self):
        w = world(month=1)
        standing_embargo(w, "veleria", "coal", .80)
        for month in range(1, 1 + 20):
            w.month = month
            coal_turn(w, pressure=.2)
        self.assertEqual(w.dip.coal_embargo, 0.0)
        self.assertAlmostEqual(output_ratio(w, "veleria"), 1.0, places=9)

    def test_a_veleria_trade_concession_eases_the_coal_embargo_by_the_step_dorsanias_eases_grain(self):
        veleria, dorsania = world(month=4), world(month=4)
        standing_embargo(veleria, "veleria", "coal", .30)
        standing_embargo(dorsania, "dorsania", "grain", .30)
        for w, actor in ((veleria, "veleria"), (dorsania, "dorsania")):
            positions = foreign.positions(w)
            positions["veleria"]["pressure"] = .35      # above the pressure step (FO11), so only the concession moves coal
            foreign._apply_cabinet_decisions(w, positions, {actor: {"actions": [{"type": "trade_concession",
                                                                                 "magnitude": .8}]}})
            foreign.resolve_union(w, positions, {})
        self.assertAlmostEqual(veleria.dip.coal_embargo, .196, places=6)
        self.assertAlmostEqual(dorsania.dip.grain_embargo, .196, places=6)
        self.assertAlmostEqual(output_ratio(veleria, "veleria"), implied("veleria", .196), places=9)

    def test_the_ledger_records_the_coal_easing_that_happened_and_no_grain_effect(self):
        w = world(month=4)
        standing_embargo(w, "veleria", "coal", .30)
        positions = foreign.positions(w)
        foreign._apply_cabinet_decisions(w, positions, {"veleria": {"actions": [{"type": "trade_concession",
                                                                                  "magnitude": .8}]}})
        effects = [e["effects_applied"] for e in foreign.applied_effects(w) if e["action"] == "trade_concession"]
        self.assertEqual(len(effects), 1)
        self.assertAlmostEqual(effects[0]["coal_embargo"], -.104, places=6)
        self.assertNotIn("position.grain_embargo", effects[0])

    def test_a_concession_with_no_coal_embargo_records_no_coal_effect(self):
        w = world(month=4)
        positions = foreign.positions(w)
        foreign._apply_cabinet_decisions(w, positions, {"veleria": {"actions": [{"type": "trade_concession",
                                                                                  "magnitude": .8}]}})
        effects = [e["effects_applied"] for e in foreign.applied_effects(w) if e["action"] == "trade_concession"]
        self.assertEqual(w.dip.coal_embargo, 0.0)
        self.assertNotIn("coal_embargo", effects[0])
        self.assertNotIn("position.grain_embargo", effects[0])

    def test_a_dorsanian_concession_records_the_grain_it_eases_and_nothing_at_zero(self):
        eased, idle = world(month=4), world(month=4)
        standing_embargo(eased, "dorsania", "grain", .30)
        for w in (eased, idle):
            positions = foreign.positions(w)
            foreign._apply_cabinet_decisions(w, positions, {"dorsania": {"actions": [{"type": "trade_concession",
                                                                                      "magnitude": .8}]}})
        recorded = [e["effects_applied"] for e in foreign.applied_effects(eased) if e["action"] == "trade_concession"]
        self.assertAlmostEqual(recorded[0]["grain_embargo"], -.104, places=6)
        self.assertNotIn("position.grain_embargo", recorded[0])
        idle_effects = [e["effects_applied"] for e in foreign.applied_effects(idle) if e["action"] == "trade_concession"]
        self.assertNotIn("grain_embargo", idle_effects[0])
        self.assertNotIn("position.grain_embargo", idle_effects[0])


def army_bands(w, months: int):
    """The Velerian cabinet's estimate of Karamaniya's army, for each of `months` months (the stream is per month)."""
    bands = []
    for month in range(months):
        w.month = month
        foreign._signal_intelligence(w)
        bands.append(w.foreign["actors"]["veleria"]["intelligence"][-1]["visible_karamaniyan_force_estimate"])
    return bands


class _CountingStream:
    """Wraps a seeded stream and counts its draws, to pin how many values the intelligence stream gives out."""

    def __init__(self, stream):
        self.stream, self.calls = stream, 0

    def uniform(self, a, b):
        self.calls += 1
        return self.stream.uniform(a, b)

    def random(self):
        self.calls += 1
        return self.stream.random()

    def randrange(self, *args):
        self.calls += 1
        return self.stream.randrange(*args)


class TheCabinetsEstimateOfTheArmy(unittest.TestCase):
    """Audit TO4 + FO15 + MI6: the cabinets' estimate of Karamaniya's army was two independent draws, biased about 10% high,
    containing the true army in under half of months, with ends that could reverse. An accepted inspection regime had no
    effect at all. Now one centre has symmetric noise and a band of ±width around it (the ends ordered), and while an
    inspection regime is in force the inspectors count the army, so the band is the army to the hundred."""

    def test_the_band_contains_the_army_most_months_without_bias_and_with_ordered_ends(self):
        army = 28000.0
        w = world(0)
        w.mil.army.size = army
        bands = army_bands(w, 300)
        covered = sum(lo <= army <= hi for lo, hi in bands)
        self.assertGreaterEqual(covered / len(bands), .8)
        self.assertFalse(any(lo > hi for lo, hi in bands))
        midpoints = [(lo + hi) / 2 / army for lo, hi in bands]
        self.assertAlmostEqual(sum(midpoints) / len(midpoints), 1.0, delta=.01)

    def test_while_an_inspection_regime_runs_the_band_is_the_army_to_the_hundred(self):
        army = 28345.0
        w = world(0)
        w.mil.army.size = army
        fine_print.reply(w, {"clauses": ["foreign_inspection"], "party": "union", "month": 0})
        for lo, hi in army_bands(w, 3):
            self.assertLessEqual(lo, army)
            self.assertGreaterEqual(hi, army)
            self.assertLessEqual(hi - lo, 100)
        w.month = 3
        foreign._signal_intelligence(w)
        lo, hi = w.foreign["actors"]["veleria"]["intelligence"][-1]["visible_karamaniyan_force_estimate"]
        self.assertGreater(hi - lo, 100, "once the regime lapses the estimate is noisy again")

    def test_the_estimate_takes_the_same_number_of_draws_so_the_draws_after_it_keep_their_values(self):
        w = world(0)
        real = foreign.rng_for
        streams = []

        def counted(seed, month, tag):
            stream = real(seed, month, tag)
            if tag == "foreign-intelligence":
                streams.append(_CountingStream(stream))
                return streams[-1]
            return stream

        with mock.patch.object(foreign, "rng_for", counted):
            foreign._signal_intelligence(w)
        self.assertEqual(streams[0].calls, 17)


class TheInspectionRegime(unittest.TestCase):
    """Audit MI6: fine_print.inspected is true for the months an accepted inspection regime runs, and asking creates no record."""

    def test_an_accepted_regime_runs_for_three_months_counting_the_month_it_is_accepted(self):
        w = world(4)
        fine_print.reply(w, {"clauses": ["foreign_inspection"], "party": "union", "month": 4})
        self.assertEqual(fine_print.state(w)["inspections"], [{"party": "union", "from": 4}])
        flags = {}
        for month in range(3, 8):
            w.month = month
            flags[month] = fine_print.inspected(w)
        self.assertEqual(flags, {3: False, 4: True, 5: True, 6: True, 7: False})

    def test_no_regime_means_not_inspected_and_asking_leaves_the_record_untouched(self):
        w = world(4)
        self.assertFalse(fine_print.inspected(w))
        self.assertNotIn(fine_print.KEY, w.institutions)


def head_world(tone: str):
    """A world in its fourth month with the head's diplomatic tone set (the head holds office: "A")."""
    w = world(4)
    if tone != "neutral":
        operations.set_orders(w, "A", {"head": {"diplomatic_tone": tone}})
    return w


def veleria_threat(w) -> float:
    return w.foreign["actors"]["veleria"]["threat_perception"]["karamaniya"]


class TheHeadsDiplomaticTone(unittest.TestCase):
    """Audit MI9: operations.apply moved Veleria's threat by the head's tone (conciliatory -.01, firm +.01), but
    foreign.positions rebuilds that threat from beliefs each month, so the move was erased before the month ended. The tone
    is now a term of the belief-based threat; the firm tone's rally still moves in operations.apply."""

    def test_the_tone_is_a_term_of_veleria_threat_each_month(self):
        neutral, conciliatory, firm = head_world("neutral"), head_world("conciliatory"), head_world("firm")
        for w in (neutral, conciliatory, firm):
            foreign.positions(w)
        self.assertAlmostEqual(veleria_threat(conciliatory), veleria_threat(neutral) - .01, delta=.001)
        self.assertAlmostEqual(veleria_threat(firm), veleria_threat(neutral) + .01, delta=.001)

    def test_operations_no_longer_writes_veleria_threat(self):
        for tone in ("conciliatory", "firm"):
            with self.subTest(tone=tone):
                w = head_world(tone)
                before = veleria_threat(w)
                operations.apply(w)
                self.assertEqual(veleria_threat(w), before)

    def test_the_firm_tone_still_rallies_the_country_in_operations(self):
        w = head_world("firm")
        rally = w.dip.rally
        operations.apply(w)
        self.assertAlmostEqual(w.dip.rally, rally + .01)


if __name__ == "__main__":
    unittest.main()
