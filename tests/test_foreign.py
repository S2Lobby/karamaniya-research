"""Strategic foreign actors, asymmetric information and cost-aware diplomacy."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import briefing, director, economy, foreign, politics  # noqa: E402
from karamaniya.world import World, new_world  # noqa: E402


class ForeignActors(unittest.TestCase):
    def world(self, seed=31):
        return new_world(seed, months=36, human_factor=False,
                         founding_scenario="serene", founding_severity="mild")

    def test_foreign_state_survives_json_round_trip_and_seed_replays(self):
        a, b = self.world(), self.world()
        self.assertEqual(a.foreign, b.foreign)
        restored = World.from_dict(a.to_dict())
        self.assertEqual(restored.foreign, a.foreign)
        self.assertEqual(restored.dip.private_inbox, [])

    def test_dorsania_can_break_union_agreement_and_prevent_union_formation(self):
        w = self.world()
        positions = foreign.positions(w)
        positions["veleria"].update(union="found", coal_embargo=.3)
        positions["dorsania"].update(union="oppose", grain_embargo=-.08,
                                      independent_trade=True)
        foreign.resolve_union(w, positions)
        self.assertFalse(w.dip.union_formed)
        self.assertLess(w.foreign["union"]["military_coordination"], .62)
        self.assertTrue(any(x["kind"] == "union_dissent" for x in w.foreign["decision_log"]))
        self.assertEqual(w.dip.grain_embargo, 0.0)

    def test_vellerian_pressure_rises_with_separation_and_threat_evidence(self):
        calm = self.world()
        pressured = World.from_dict(calm.to_dict())
        foreign.prepare(calm)
        foreign.prepare(pressured)
        actor = pressured.foreign["actors"]["veleria"]
        actor["beliefs"]["karamaniya_permanent_separation"].update(value=.90, confidence=.9)
        actor["beliefs"]["karamaniya_offensive_intent"].update(value=.75, confidence=.9)
        actor["political_pressures"]["nationalist_demand"] = .85
        actor["political_pressures"]["industrial_disruption"] = .30
        calm_position = foreign.positions(calm)["veleria"]
        threat_position = foreign.positions(pressured)["veleria"]
        self.assertEqual(calm_position["coal_embargo"], 0.0)
        self.assertGreater(threat_position["coal_embargo"], 0.0)
        self.assertGreater(threat_position["military_build"], 0.0)
        before = pressured.rivals["veleria"].gdp_real
        foreign.resolve_union(pressured, {"veleria": threat_position,
                                          "dorsania": foreign.positions(pressured)["dorsania"]})
        self.assertLess(pressured.rivals["veleria"].gdp_real, before)

    def test_bilateral_grain_deal_improves_trade_and_routes_private_dispatch(self):
        w = self.world()
        baseline = World.from_dict(w.to_dict())
        baseline_trade = economy.trade_and_food(baseline, economy.produce(baseline))
        foreign.prepare(w)
        foreign.dorsania_reply(w, "grain_deal", text="buy grain")
        result = economy.trade_and_food(w, economy.produce(w))
        self.assertGreater(result["food_dors"], baseline_trade["food_dors"] + .10e6)
        self.assertTrue(w.dip.private_inbox)
        self.assertEqual(w.dip.private_inbox[-1]["office"], "treasury")
        self.assertFalse(w.dip.inbox)
        w.const.offices["treasury"] = "A"
        w.const.offices["head"] = "B"
        treasury_annex = briefing.annex(w, "A")
        head_annex = briefing.annex(w, "B")
        self.assertIn("accepts a", treasury_annex)
        self.assertNotIn("accepts a", head_annex)
        self.assertNotIn("accepts a", briefing.public(w))

    def test_bilateral_trade_and_economic_bonus_share_the_inclusive_expiry_month(self):
        with_trade = self.world()
        with_trade.region("dorran").controller = "karamaniya"
        with_trade.counters["dorsania_trade"] = 1.0
        with_trade.counters["dorsania_trade_until"] = with_trade.month
        without_trade = World.from_dict(with_trade.to_dict())
        without_trade.counters["dorsania_trade"] = 0.0

        self.assertTrue(foreign._bilateral_trade_open(with_trade))
        food_with_trade = economy.trade_and_food(with_trade, economy.produce(with_trade))["food_dors"]
        food_without_trade = economy.trade_and_food(without_trade, economy.produce(without_trade))["food_dors"]
        self.assertAlmostEqual(food_with_trade - food_without_trade,
                               .14e6 * with_trade.econ.food_import_capacity)

        with_trade.month += 1
        self.assertFalse(foreign._bilateral_trade_open(with_trade))

    def test_grain_agreement_duration_is_exact_and_renewal_extends_the_end_date(self):
        w = self.world()
        foreign.prepare(w)
        pressure = w.foreign["actors"]["dorsania"]["political_pressures"]["exporter_opposition"]
        duration = 6 if pressure < .55 else 9

        foreign.dorsania_reply(w, "grain_deal")
        original_until = int(w.counters["dorsania_trade_until"])
        self.assertEqual(original_until, w.month + duration - 1)
        w.month = original_until
        self.assertTrue(foreign._bilateral_trade_open(w))

        foreign.dorsania_reply(w, "grain_deal")
        renewed_until = int(w.counters["dorsania_trade_until"])
        self.assertEqual(renewed_until, original_until + duration)
        w.month = renewed_until + 1
        self.assertFalse(foreign._bilateral_trade_open(w))

    def test_market_embargo_effect_includes_enforcement_and_leakage(self):
        w = self.world()
        w.dip.grain_embargo = .8
        foreign.sync_embargoes(w)
        obj = w.foreign["embargoes"]["dorsania:grain"]
        expected = obj["severity"] * obj["enforcement"] * (1 - obj["leakage"])
        self.assertAlmostEqual(foreign.effective_embargo(w, "dorsania", "grain"), expected)
        self.assertLess(expected, w.dip.grain_embargo)

    def test_foreign_intelligence_is_noisy_and_context_omits_private_material(self):
        w = self.world()
        contexts = foreign.prepare(w)
        for actor_id in ("veleria", "dorsania"):
            info = w.foreign["actors"][actor_id]["intelligence"][-1]
            low, high = info["visible_karamaniyan_force_estimate"]
            self.assertGreater(high, low)
            self.assertNotEqual(low, w.mil.army.size)
            self.assertNotEqual(high, w.mil.army.size)
            self.assertNotIn("private_inbox", contexts[actor_id])
            self.assertNotIn("hidden_policies", contexts[actor_id])
            self.assertNotIn("private_prompt", contexts[actor_id])
        govt = w.foreign["government_intelligence"][-1]["actors"]["veleria"]
        self.assertGreater(govt["force_estimate"][1], govt["force_estimate"][0])
        self.assertNotEqual(govt["force_estimate"][0], w.rivals["veleria"].army)
        public = briefing.public(w)
        self.assertNotIn("karamaniya_permanent_separation", public)
        self.assertNotIn("economic_pressure_effectiveness", public)

    def test_cabinet_output_is_bounded_and_reserve_request_is_validated(self):
        w = self.world()
        normalized, problems = foreign.normalize_cabinet_output("veleria", {
            "actions": [{"type": "military_exercise", "magnitude": 1, "troops": 999999}],
            "belief_updates": [{"belief": "karamaniya_offensive_intent", "value": .9, "confidence": .8},
                               {"belief": "secret", "value": 1, "confidence": 1}],
        })
        self.assertEqual(len(normalized["belief_updates"]), 1)
        self.assertTrue(problems)
        error = foreign.validate_action("veleria", normalized["actions"][0], {"mobilized_reserve": 1})
        self.assertIn("exceeds", error)

    def test_league_caps_credit_by_exposure_and_sets_repayment_conditions(self):
        w = self.world()
        director._league_reply(w, "loan", 100)
        self.assertGreater(w.dip.league_loan_pending, 0)
        loan = w.foreign["league"]["loan"]
        self.assertEqual(loan["conditions"]["debt_service"], "pay")
        self.assertGreater(loan["interest"], .045)
        w2 = self.world(32)
        w2.foreign["league"]["financial_exposure"] = 1
        director._league_reply(w2, "loan", 100)
        self.assertEqual(w2.dip.league_loan_pending, 0)
        self.assertIn("declines", w2.dip.private_inbox[-1]["text"])

    def test_frozen_undisbursed_loan_releases_reserved_exposure(self):
        w = self.world()
        w.set_league_trust(.55)
        w.econ.deficit = .20 * w.econ.gdp_nominal
        w.policy.debt_service = "pay"

        director._league_reply(w, "loan", 100)
        self.assertGreater(w.dip.league_loan_pending, 0)
        self.assertEqual(w.foreign["league"]["loan"]["principal"], 0)
        self.assertGreater(w.foreign["league"]["financial_exposure"], 0)

        foreign.league_month(w)

        self.assertEqual(w.dip.league_loan_pending, 0)
        self.assertEqual(w.foreign["league"]["loan"]["principal"], 0)
        self.assertEqual(w.foreign["league"]["financial_exposure"], 0)

    def test_league_trust_actions_survive_monthly_smoothing(self):
        cases = (
            ("protest", .02, lambda w: director._protest_reply(w, "league")),
            ("renounce", -.2, lambda w: (setattr(w.dip, "league_alliance", True),
                                          director._renounce(w, "league"))),
            ("aggression", -.3, lambda w: (setattr(w.policy, "posture", "attack"),
                                            director._karamanian_aggression(w))),
        )
        for name, adjustment, apply_action in cases:
            with self.subTest(action=name):
                w = self.world()
                w.set_league_trust(.65)
                baseline = World.from_dict(w.to_dict())

                apply_action(w)

                self.assertAlmostEqual(w.dip.league_trust,
                                       w.foreign["league"]["trust_in_karamaniya"])
                foreign.league_month(w)
                foreign.league_month(baseline)
                self.assertAlmostEqual(w.dip.league_trust - baseline.dip.league_trust,
                                       round(.88 * adjustment, 3), places=3)
                self.assertEqual(w.dip.league_trust,
                                 w.foreign["league"]["trust_in_karamaniya"])

    def test_internment_clamps_league_trust_and_monthly_recovery_remains_smooth(self):
        w = self.world()
        w.set_league_trust(.1)

        politics.apply_motion(w, {"type": "constitution", "subject": "minority",
                                  "value": "interned", "text": "intern the minority",
                                  "proposer": "A"})

        self.assertEqual(w.dip.league_trust, 0.0)
        self.assertEqual(w.foreign["league"]["trust_in_karamaniya"], 0.0)

        foreign.league_month(w)

        self.assertAlmostEqual(w.dip.league_trust, .039)
        self.assertEqual(w.dip.league_trust, w.foreign["league"]["trust_in_karamaniya"])

    def test_terminal_union_outcomes_stop_external_preparation_and_aggression(self):
        for kind in ("join_union", "federation"):
            with self.subTest(proposal=kind):
                w = self.world()
                w.policy.posture = "attack"
                if kind == "federation":
                    w.dip.union_weariness = .5  # The Union accepts when it is weary.
                w.dip.proposals.append({"kind": kind, "party": "union"})
                intelligence_before = {
                    actor_id: len(actor["intelligence"])
                    for actor_id, actor in w.foreign["actors"].items()
                }
                league_history_before = len(w.foreign["league"]["history"])
                gdp_before = {actor_id: rival.gdp_real for actor_id, rival in w.rivals.items()}

                director.act(w)

                self.assertTrue(w.ended())
                self.assertFalse(w.dip.war)
                self.assertEqual(
                    {actor_id: len(actor["intelligence"])
                     for actor_id, actor in w.foreign["actors"].items()},
                    intelligence_before,
                )
                self.assertEqual(len(w.foreign["league"]["history"]), league_history_before)
                self.assertEqual({actor_id: rival.gdp_real for actor_id, rival in w.rivals.items()},
                                 gdp_before)


if __name__ == "__main__":
    unittest.main()
