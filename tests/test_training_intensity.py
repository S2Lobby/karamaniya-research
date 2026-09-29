"""The Army's training-intensity lever, and the name collision it was nearly shipped with.

Agents in the archived runs asked twelve times for a way to change how hard the army trains
(`army_training_focus`) and were rejected every time. Adding the lever was straightforward; adding
it *without* colliding with the Army office's existing operational `training_focus` — which decides
what the army trains FOR, not how hard — was the part that mattered.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import director, engine, military, operations, politics  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def run(w, months, each=None):
    original = director.act
    director.act = lambda world, *_a, **_k: setattr(world.dip, "inbox", [])
    try:
        for _ in range(months):
            if w.ended():
                break
            engine.begin_month(w)
            if each:
                each(w)
            engine.step(w)
    finally:
        director.act = original
    return w


def steady(w):
    w.const.elected = True
    w.const.election_month = 99


class NoNameCollisions(unittest.TestCase):
    """The guard that would have caught the bug this file exists for."""

    def test_no_council_lever_shares_a_name_with_an_operational_setting(self):
        operational = {name for settings in operations.OPERATIONS.values() for name in settings}
        clash = operational & set(politics.LEVER_OFFICE)
        self.assertEqual(clash, set(),
                         f"these names mean two different things: {sorted(clash)}")

    def test_the_two_training_settings_are_genuinely_distinct(self):
        self.assertIn("training_intensity", politics.LEVER_OFFICE)
        self.assertIn("training_focus", operations.OPERATIONS["army"])
        self.assertNotIn("training_focus", politics.LEVER_OFFICE)
        self.assertNotIn("training_intensity", operations.OPERATIONS["army"])

    def test_an_ambiguous_name_is_not_silently_redirected(self):
        """`training_focus` means the operational setting; it must not resolve to the lever."""
        self.assertEqual(politics.canonical_lever("training_focus"), "training_focus")
        self.assertNotIn(politics.canonical_lever("training_focus"), politics.LEVER_OFFICE)


class Aliases(unittest.TestCase):
    def test_the_name_agents_actually_used_resolves(self):
        self.assertEqual(politics.canonical_lever("army_training_focus"), "training_intensity")
        self.assertEqual(politics.canonical_lever("army training focus"), "training_intensity")

    def test_recruitment_phrasings_resolve_to_the_existing_lever(self):
        self.assertEqual(politics.canonical_lever("army_recruitment_focus"), "recruitment")
        self.assertEqual(politics.canonical_lever("conscription"), "recruitment")

    def test_every_alias_targets_a_real_lever(self):
        for name, target in politics.LEVER_ALIASES.items():
            with self.subTest(alias=name):
                self.assertIn(target, politics.LEVER_OFFICE)

    def test_an_alias_never_shadows_a_real_lever(self):
        """An alias must not redirect a name that is already a valid setting."""
        for name in politics.LEVER_ALIASES:
            with self.subTest(name=name):
                self.assertNotIn(name, politics.LEVER_OFFICE,
                                 f"{name} is both a lever and an alias")

    def test_an_unknown_name_is_left_alone(self):
        self.assertEqual(politics.canonical_lever("warp_drive"), "warp_drive")

    def test_the_hint_explains_the_distinction(self):
        hint = politics._unknown_lever("training_focus")
        self.assertIn("training_intensity", hint)
        self.assertIn("operational order", hint)


class TheLeverWorks(unittest.TestCase):
    def _train(self, mode):
        w = run(new_world(9, 18), 18,
                each=lambda x, m=mode: (steady(x), setattr(x.policy, "training_intensity", m)))
        return w.mil.army

    def test_the_three_settings_produce_different_training(self):
        neglect, standard, intense = (self._train(m).training
                                      for m in ("neglect", "standard", "intense"))
        self.assertLess(neglect, standard)
        self.assertLess(standard, intense)

    def test_training_reaches_quality_and_so_combat_power(self):
        def quality(force):
            return military.quality(force.equipment, force.training, force.morale)
        self.assertLess(quality(self._train("neglect")), quality(self._train("intense")))

    def test_intense_training_wears_on_morale(self):
        """It must be a tradeoff, not a free upgrade."""
        self.assertLess(self._train("intense").morale, self._train("standard").morale)

    def test_neglect_saves_money_and_intense_costs_more(self):
        cheap = military.TRAINING_INTENSITY["neglect"]["bill"]
        standard = military.TRAINING_INTENSITY["standard"]["bill"]
        dear = military.TRAINING_INTENSITY["intense"]["bill"]
        self.assertLess(cheap, standard)
        self.assertLess(standard, dear)

    def test_every_setting_is_registered_with_the_army_office(self):
        self.assertEqual(politics.LEVER_OFFICE["training_intensity"], "army")
        for mode in politics.ENUMS["training_intensity"]:
            with self.subTest(mode=mode):
                self.assertIn(mode, military.TRAINING_INTENSITY)

    def test_an_unknown_setting_falls_back_rather_than_crashing(self):
        w = new_world(9, 6)
        w.policy.training_intensity = "maximum"
        self.assertEqual(military.training_intensity(w), military.TRAINING_INTENSITY["standard"])


class AgentsCanFindIt(unittest.TestCase):
    def test_the_lever_is_listed_in_the_standing_instructions(self):
        from karamaniya import prompts
        text = getattr(prompts, "SETTINGS_TEXT", None) or getattr(prompts, "SETTINGS", None)
        if text is None:
            import inspect
            source = inspect.getsource(prompts)
            text = source
        self.assertIn("training_intensity", text,
                      "the lever exists but a delegate would never learn of it")

    def test_the_tradeoff_is_stated_where_a_voter_reads_it(self):
        from karamaniya import decision_context
        self.assertIn("training_intensity", decision_context.TRADEOFFS)

    def test_the_army_office_is_credited_for_changing_it(self):
        from karamaniya import standing
        owners = standing.DOMAINS.get("army", {}).get("levers", ())
        self.assertIn("training_intensity", owners)


class AVotingCouncilCanDirectIt(unittest.TestCase):
    def test_a_directive_on_training_intensity_is_accepted(self):
        w = new_world(9, 6)
        w.const.offices["army"] = "A"
        motion = {"type": "set_policy", "subject": "training_intensity", "value": "intense"}
        self.assertIsNone(politics.validate_motion_detail(w, motion))

    def test_the_aliased_name_also_produces_a_valid_motion(self):
        w = new_world(9, 6)
        w.const.offices["army"] = "A"
        motion = {"type": "set_policy", "subject": "army_training_focus", "value": "intense"}
        self.assertIsNone(politics.validate_motion_detail(w, motion))

    def test_an_invalid_setting_is_rejected_with_the_allowed_values(self):
        w = new_world(9, 6)
        w.const.offices["army"] = "A"
        motion = {"type": "set_policy", "subject": "training_intensity", "value": "maximum"}
        result = politics.validate_motion_detail(w, motion)
        self.assertIsNotNone(result)
        self.assertEqual(result["reason_code"], "BAD_VALUE")
        self.assertIn("intense", result["explanation"])


if __name__ == "__main__":
    unittest.main()
