"""A shared starting situation can grow distinct political relationships through choices."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, human, prompts  # noqa: E402
from karamaniya.engine import nation_detail  # noqa: E402
from karamaniya.world import World, new_world  # noqa: E402


class HumanFactor(unittest.TestCase):
    def test_equal_start_and_choice_driven_relationships_survive_resume(self):
        w = new_world(7)
        self.assertEqual({m.clout for m in w.members}, {0.5})
        self.assertTrue(all(not m.alignment for m in w.members))
        record = {"motions": [{"proposer": "A", "type": "assign_office", "value": "B", "passed": True,
                               "votes": {"A": "yes", "B": "yes", "C": "no", "D": "abstain", "E": "abstain"}}],
                  "defiance": [], "coups": []}
        human.update(w, record)
        self.assertGreater(w.member("A").alignment["B"], 0)
        self.assertLess(w.member("A").alignment["C"], 0)
        self.assertGreater(w.member("B").clout, w.member("C").clout)
        restored = World.from_dict(w.to_dict())
        self.assertEqual(human.snapshot(restored), human.snapshot(w))
        self.assertIn("Observed working relationships", human.context(restored, "A"))

    def test_each_delegate_receives_the_same_standing_rules(self):
        w = new_world(3)
        self.assertIn("Delegates have different private dispositions", prompts.system_prompt("simulation"))
        self.assertIn("Your influence in the council", human.context(w, "A"))
        self.assertIn("Your influence in the council", human.context(w, "B"))

    def test_self_declared_principles_are_opt_in_and_persist(self):
        w = new_world(3)
        opening = prompts.survey_schema(w.human_factor)
        self.assertIn("principles", opening["required"])
        self.assertIn("independently", prompts.survey_prompt(opening))
        schema = actions.session_schema(w, "A")
        self.assertIn("principles", schema["required"])
        out, problems = actions.normalize_session(w, "A", {"principles": "Open elections and civil rights"}, 0)
        self.assertEqual(problems, [])
        self.assertEqual(out["principles"], "Open elections and civil rights")
        prompt = prompts.session_prompt(w, "A", "brief", "", [], [], [], ["A"], schema, 0)
        self.assertIn("No ideology is assigned to you", prompt)
        w.member("A").ideology = out["principles"]
        w.member("A").ideology_history.append({"month": 0, "text": out["principles"]})
        restored = World.from_dict(w.to_dict())
        self.assertEqual(human.snapshot(restored)["A"]["ideology_history"],
                         [{"month": 0, "text": "Open elections and civil rights"}])

    def test_legacy_prompts_match_the_missing_message_field_at_zero_allowance(self):
        w = new_world(1, member_ids=list("ABCDE"))
        session = prompts.session_prompt(
            w, "A", "brief", "", [], [], [], list("ABCDE"), actions.session_schema(w, "A"), 0)
        decision = prompts.decision_prompt(
            w, "A", "brief", "", [], [], [], actions.decision_schema(w, "A", []), 0)

        for phase, text in (("session", session), ("decision", decision)):
            with self.subTest(phase=phase):
                self.assertNotIn("up to 0 private", text)
                self.assertIn("no private messages left this month", text)
                self.assertIn("field is not in the schema", text)

    def test_old_runs_keep_their_original_prompt(self):
        w = new_world(3, human_factor=False)
        self.assertFalse(w.human_factor)
        self.assertNotIn("PERSONAL STAKES", prompts.system_prompt("simulation", w.human_factor))
        self.assertNotIn("principles", actions.session_schema(w, "A")["properties"])

    def test_country_totals_are_consistent_with_the_world(self):
        w = new_world(1)
        data = nation_detail(w)
        self.assertEqual(data["karamaniya"]["population"], round(w.population(), -3))
        self.assertEqual(data["veleria"]["army"], round(w.rivals["veleria"].army, -2))
        self.assertAlmostEqual(data["dorsania"]["output_per_person"],
                               w.rivals["dorsania"].gdp_real * 12 / w.rivals["dorsania"].population,
                               delta=5)
