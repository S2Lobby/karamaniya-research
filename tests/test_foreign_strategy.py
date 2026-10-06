"""Red lines, leadership confidence and domestic constituencies of the foreign actors."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import briefing, foreign  # noqa: E402
from karamaniya.world import World, new_world  # noqa: E402


class ForeignStrategy(unittest.TestCase):
    def world(self, seed=31):
        return new_world(seed, months=36, human_factor=False,
                         founding_scenario="serene", founding_severity="mild")

    def prepared(self, seed=31):
        w = self.world(seed)
        foreign.prepare(w)
        return w


class RedLines(ForeignStrategy):
    def test_each_actor_keeps_a_small_set_of_machine_evaluable_lines(self):
        w = self.prepared()
        for actor_id, actor in w.foreign["actors"].items():
            with self.subTest(actor=actor_id):
                lines = actor["red_lines"]
                self.assertTrue(2 <= len(lines) <= 3, lines)
                for line in lines:
                    self.assertEqual(set(line), {"id", "condition", "threshold", "severity",
                                                 "crossed_month", "response"})
                    self.assertIn(line["condition"], foreign.RED_LINE_CONDITIONS)
                    self.assertGreater(line["threshold"], 0)
                    self.assertLessEqual(line["threshold"], 1)
                    self.assertGreater(line["severity"], 0)
                    self.assertEqual(line["crossed_month"], -1)
                    self.assertFalse(line["response"])
                readings = foreign.red_line_measurements(w, actor_id)
                self.assertEqual(set(readings), {line["condition"] for line in lines})
                for value in readings.values():
                    self.assertIsInstance(value, float)
                    self.assertTrue(0 <= value <= 1)

    def test_a_crossed_line_hardens_the_actor_once_and_is_not_retriggered(self):
        w = self.prepared()
        veleria = w.foreign["actors"]["veleria"]
        before = dict(veleria["relations"]["karamaniya"])
        w.month += 1
        w.dip.league_alliance = True          # Karamaniya accepts the League's military alliance
        foreign.evaluate_red_lines(w)
        crossed = [line for line in veleria["red_lines"] if line["crossed_month"] == w.month]
        self.assertEqual([line["id"] for line in crossed], ["league_military_ties"])
        self.assertTrue(crossed[0]["response"])
        self.assertGreater(veleria["relations"]["karamaniya"]["hostility"], before["hostility"])
        self.assertGreater(veleria["relations"]["karamaniya"]["threat_perception"],
                           before["threat_perception"])
        self.assertTrue(any(entry["kind"] == "red_line" for entry in veleria["memory"]))

        hardened = veleria["relations"]["karamaniya"]["hostility"]
        for _ in range(3):
            w.month += 1
            foreign.evaluate_red_lines(w)
        self.assertEqual(crossed[0]["crossed_month"], w.month - 3, "a standing breach re-fired")
        self.assertEqual(veleria["relations"]["karamaniya"]["hostility"], hardened)

    def test_an_uncrossed_line_changes_nothing(self):
        first, second = self.prepared(), self.prepared()
        self.assertEqual(first.foreign, second.foreign)
        for actor in first.foreign["actors"].values():
            self.assertTrue(all(line["crossed_month"] == -1 for line in actor["red_lines"]))
        before = {aid: dict(actor["relations"]["karamaniya"])
                  for aid, actor in first.foreign["actors"].items()}
        foreign.evaluate_red_lines(first)
        for actor_id, actor in first.foreign["actors"].items():
            self.assertEqual(actor["relations"]["karamaniya"], before[actor_id])
            self.assertTrue(all(line["crossed_month"] == -1 for line in actor["red_lines"]))

    def test_a_crossing_reaches_the_actors_existing_assessment(self):
        calm, crossed = self.prepared(), self.prepared()
        crossed.dip.league_alliance = True
        for w in (calm, crossed):
            w.month += 1
            foreign.prepare(w)
        self.assertGreater(foreign.positions(crossed)["veleria"]["pressure"],
                           foreign.positions(calm)["veleria"]["pressure"])
        self.assertGreater(crossed.foreign["actors"]["veleria"]["relations"]["karamaniya"]["hostility"],
                           calm.foreign["actors"]["veleria"]["relations"]["karamaniya"]["hostility"])

    def test_the_response_to_a_crossing_follows_disposition(self):
        w = self.prepared()
        aggressive = foreign._red_line_response(w.foreign["actors"]["veleria"]["disposition"])
        patient = foreign._red_line_response(w.foreign["actors"]["dorsania"]["disposition"])
        self.assertEqual((aggressive, patient), ("escalate", "protest"))
        self.assertGreater(foreign.RED_LINE_RESPONSES[aggressive][0],
                           foreign.RED_LINE_RESPONSES[patient][0])
        # The same crossing seen through Dorsania's patience is recorded as a protest.
        w.dip.blockade = True
        w.dip.blockade_eff = .9
        foreign.evaluate_red_lines(w)
        line = next(x for x in w.foreign["actors"]["dorsania"]["red_lines"]
                    if x["id"] == "sea_lanes_closed")
        self.assertEqual(line["crossed_month"], w.month)
        self.assertEqual(line["response"], "protest")

    def test_a_crossed_line_never_starts_a_war_or_an_attack(self):
        w = self.prepared()
        w.dip.war = True
        w.dip.aggressor = "karamaniya"
        armies = {actor_id: rival.army for actor_id, rival in w.rivals.items()}
        foreign.evaluate_red_lines(w)
        self.assertTrue(w.dip.war, "the line cancelled Karamaniya's own war")
        self.assertEqual({actor_id: rival.army for actor_id, rival in w.rivals.items()}, armies)
        self.assertFalse(w.dip.blockade)
        self.assertFalse(w.dip.ultimatum)


class Leadership(ForeignStrategy):
    def test_confidence_falls_under_domestic_stress_and_failed_pressure(self):
        w = self.prepared()
        veleria = w.foreign["actors"]["veleria"]
        opening = veleria["leadership"]["confidence"]
        veleria["domestic"].update(approval=.25, war_weariness=.6, fiscal_stress=.9)
        veleria["beliefs"]["economic_pressure_effectiveness"]["value"] = .25
        w.rivals["veleria"].printing = .5
        w.dip.coal_embargo = .4
        foreign.prepare(w)
        self.assertLess(veleria["leadership"]["confidence"], opening)
        self.assertGreater(veleria["leadership"]["domestic_pressure"], .5)
        self.assertLessEqual(veleria["leadership"]["domestic_pressure"], 1.0)

    def test_confidence_recovers_slowly_when_conditions_and_results_improve(self):
        w = self.prepared()
        veleria = w.foreign["actors"]["veleria"]
        opening = veleria["leadership"]["confidence"]
        veleria["domestic"].update(approval=.25, war_weariness=.6, fiscal_stress=.9)
        veleria["beliefs"]["economic_pressure_effectiveness"]["value"] = .25
        w.rivals["veleria"].printing = .5
        w.dip.coal_embargo = .4
        for _ in range(4):
            w.month += 1
            foreign.prepare(w)
        low = veleria["leadership"]["confidence"]
        self.assertLess(low, opening * .8, "a bad stretch barely moved confidence")

        # The bad stretch ends: no printing, no embargo, a calmer public, pressure that works.
        w.rivals["veleria"].printing = 0.0
        w.dip.coal_embargo = 0.0
        veleria["beliefs"]["economic_pressure_effectiveness"]["value"] = .6
        veleria["economy"]["inflation"] = .02
        veleria["domestic"].update(approval=.70, war_weariness=0.0, fiscal_stress=.08)
        for _ in range(2):
            w.month += 1
            foreign.prepare(w)
        recovered = veleria["leadership"]["confidence"]
        self.assertGreater(recovered, low, "confidence did not recover at all")
        self.assertLess(recovered, opening, "confidence recovered faster than it fell")
        self.assertLess(veleria["leadership"]["domestic_pressure"], .5)
        before = veleria["leadership"]["months_in_office"]
        w.month += 1
        foreign.prepare(w)
        self.assertEqual(veleria["leadership"]["months_in_office"], before + 1)

    def test_tenure_follows_the_calendar_not_the_number_of_prepare_calls(self):
        w = self.prepared()
        veleria = w.foreign["actors"]["veleria"]
        foreign.prepare(w)                          # the same month resolved a second time
        self.assertEqual(veleria["leadership"]["months_in_office"],
                         foreign._tenure_opening("veleria", w.seed) + w.month)
        w.month += 3
        foreign.prepare(w)
        self.assertEqual(veleria["leadership"]["months_in_office"],
                         foreign._tenure_opening("veleria", w.seed) + w.month)


class Constituencies(ForeignStrategy):
    def test_groups_carry_a_bounded_preference_and_weights_that_sum(self):
        w = self.prepared()
        for actor_id, actor in w.foreign["actors"].items():
            with self.subTest(actor=actor_id):
                groups = actor["constituencies"]
                weighted = [g for g in groups.values() if g["weight"] > 0]
                self.assertTrue(2 <= len(weighted) <= 3, groups)
                self.assertAlmostEqual(sum(g["weight"] for g in groups.values()), 1.0, places=6)
                for group in groups.values():
                    self.assertTrue(-1 <= group["preference"] <= 1)
                    self.assertTrue(0 <= group["support"] <= 1)

    def test_posture_follows_the_instruments_the_engine_moves(self):
        w = self.prepared()
        self.assertEqual(foreign.posture_toward_karamaniya(w, "veleria"), 0.0)
        w.dip.coal_embargo = .40
        self.assertGreater(foreign.posture_toward_karamaniya(w, "veleria"), .5)
        w.dip.coal_embargo = 0.0
        w.dip.nonaggression = True
        self.assertLess(foreign.posture_toward_karamaniya(w, "veleria"), 0.0)
        w.dip.nonaggression = False
        w.counters["dorsania_trade"] = 1.0
        w.counters["dorsania_trade_until"] = w.month + 6
        self.assertLess(foreign.posture_toward_karamaniya(w, "dorsania"), 0.0)

    def test_a_group_whose_preference_is_ignored_shows_up_as_pressure(self):
        w = self.prepared()
        veleria = w.foreign["actors"]["veleria"]
        calm = dict(veleria["political_pressures"])
        self.assertGreater(calm["nationalists_grievance"], 0.0)
        self.assertGreater(calm["commercial_sector_grievance"], 0.0)
        self.assertNotIn("workers_grievance", calm, "a group with no posture carries no grievance")

        w.dip.coal_embargo = .40                    # the government now does what nationalists want
        foreign.prepare(w)
        firm = veleria["political_pressures"]
        self.assertLess(firm["nationalists_grievance"], calm["nationalists_grievance"])
        self.assertGreater(firm["commercial_sector_grievance"], calm["commercial_sector_grievance"])

    def test_a_group_that_gets_exactly_its_policy_carries_no_grievance(self):
        w = self.prepared()
        dorsania = w.foreign["actors"]["dorsania"]
        w.dip.grain_embargo = .225                  # exactly the posture the Dorsanian army wants
        foreign.prepare(w)
        self.assertAlmostEqual(dorsania["political_pressures"]["army_grievance"], 0.0, places=3)
        self.assertGreater(dorsania["political_pressures"]["grain_exporters_grievance"], 0.0)

    def test_grievance_reaches_the_measure_of_domestic_pressure(self):
        w = self.prepared()
        veleria = w.foreign["actors"]["veleria"]
        ignored = veleria["leadership"]["domestic_pressure"]
        # A government whose groups no longer argue about the posture hears less of it.
        for group in veleria["constituencies"].values():
            group["preference"], group["weight"] = 0.0, 0.0
        foreign.prepare(w)
        self.assertLess(veleria["leadership"]["domestic_pressure"], ignored)


class CautiousLeadership(ForeignStrategy):
    def test_a_low_confidence_leadership_pulls_the_same_decisions_punch(self):
        bold, cautious = self.world(), self.world()
        foreign.prepare(bold)
        foreign.prepare(cautious)
        for w in (bold, cautious):
            actor = w.foreign["actors"]["veleria"]
            actor["political_pressures"]["nationalist_demand"] = .9
            actor["beliefs"]["karamaniya_permanent_separation"].update(value=.9, confidence=.9)
            actor["beliefs"]["karamaniya_offensive_intent"].update(value=.8, confidence=.9)
        bold.foreign["actors"]["veleria"]["leadership"]["confidence"] = .95
        cautious.foreign["actors"]["veleria"]["leadership"]["confidence"] = .05
        decided = foreign.positions(bold)["veleria"]
        hedged = foreign.positions(cautious)["veleria"]
        self.assertGreater(decided["coal_embargo"], hedged["coal_embargo"])
        self.assertGreater(decided["pressure"], hedged["pressure"])
        self.assertGreater(decided["military_build"], hedged["military_build"])


class Determinism(ForeignStrategy):
    def test_the_same_seed_replays_the_same_strategy_state(self):
        a, b = self.prepared(), self.prepared()
        self.assertEqual(a.foreign, b.foreign)
        for actor_id in ("veleria", "dorsania"):
            self.assertEqual(a.foreign["actors"][actor_id]["red_lines"],
                             b.foreign["actors"][actor_id]["red_lines"])
            self.assertEqual(a.foreign["actors"][actor_id]["leadership"],
                             b.foreign["actors"][actor_id]["leadership"])

    def test_different_seeds_draw_different_leaderships(self):
        first, second = self.prepared(31), self.prepared(32)
        self.assertNotEqual(first.foreign["actors"]["veleria"]["leadership"],
                            second.foreign["actors"]["veleria"]["leadership"])


class OldCheckpoints(ForeignStrategy):
    def _old_style(self):
        w = self.prepared()
        old = w.to_dict()
        for actor in old["foreign"]["actors"].values():
            actor.pop("red_lines")
            actor.pop("leadership")
            actor["constituencies"] = {name: group["support"]
                                       for name, group in actor["constituencies"].items()}
            actor["constituencies"]["merchant_guilds"] = .5
        return w, old

    def test_a_checkpoint_without_the_new_keys_still_loads_and_is_upgraded(self):
        w, old = self._old_style()
        restored = World.from_dict(old)
        foreign.prepare(restored)
        for actor_id, actor in restored.foreign["actors"].items():
            self.assertEqual(len(actor["red_lines"]), len(foreign.RED_LINES[actor_id]))
            self.assertTrue(all(line["crossed_month"] == -1 for line in actor["red_lines"]))
            self.assertIn("confidence", actor["leadership"])
            self.assertIsInstance(actor["constituencies"]["merchant_guilds"], dict)
            self.assertAlmostEqual(actor["constituencies"]["merchant_guilds"]["support"], .5)
            self.assertTrue(any(key.endswith("_grievance") for key in actor["political_pressures"]))
        self.assertEqual(restored.foreign["actors"]["dorsania"]["relations"]["karamaniya"],
                         w.foreign["actors"]["dorsania"]["relations"]["karamaniya"])

    def test_an_old_checkpoint_that_meets_no_condition_crosses_nothing(self):
        _, old = self._old_style()
        restored = World.from_dict(old)
        foreign.prepare(restored)
        for actor_id, actor in restored.foreign["actors"].items():
            with self.subTest(actor=actor_id):
                self.assertTrue(all(foreign.red_line_measurements(restored, actor_id)[line["condition"]]
                                    < line["threshold"] for line in actor["red_lines"]))
                self.assertTrue(all(line["crossed_month"] == -1 for line in actor["red_lines"]))

    def test_two_old_checkpoints_upgrade_identically(self):
        _, old = self._old_style()
        first = World.from_dict(old)
        second = World.from_dict(old)
        foreign.prepare(first)
        foreign.prepare(second)
        self.assertEqual(first.foreign, second.foreign)


class NoInformationLeaks(ForeignStrategy):
    def test_the_cabinet_context_does_not_expose_the_model_blocks(self):
        w = self.prepared()
        for actor_id in ("veleria", "dorsania"):
            with self.subTest(actor=actor_id):
                context = foreign.cabinet_context(w, actor_id)
                self.assertNotIn("red_lines", context)
                self.assertNotIn("leadership", context)
                self.assertNotIn("constituencies", context)
                self.assertNotIn("weight", repr(context))
                self.assertIn("pressures", context)
        public = briefing.public(w)
        self.assertNotIn("red_line", public)
        self.assertNotIn("grievance", public)


if __name__ == "__main__":
    unittest.main()
