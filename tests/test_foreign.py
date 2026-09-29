"""Strategic foreign actors, asymmetric information and cost-aware diplomacy."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import briefing, director, economy, foreign  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
