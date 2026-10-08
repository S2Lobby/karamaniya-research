"""Three engine faults found in Months 3-8 of run 20261008-130316-seed1, the first engine-6 run with
real models, each replayed against the recorded answer before the fix:

- the council sent the Union a non-aggression pact five times in eight months, though one pact is one
  standing agreement whoever it is addressed to;
- a rate motion's text raised the rate "from 6% to 7%", Month 1's figures, while it set 0.11 from 0.10,
  and nothing compared the two before the council voted;
- a storm was announced as damage already done, but the damage reached the state only after the council
  had answered it, so a 20M relief package voted on the news ran on 0.0% damage.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, dilemmas, motion_actions, politics  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

RATE_TEXT = ("Raise annual interest rate from 6% to 7% (a rise of 1 percentage point) immediately after this "
             "month to stem currency speculation without causing mass unemployment.")


class StandingTreaties(unittest.TestCase):
    def setUp(self):
        self.w = new_world(1, 36)

    def proposal(self, subject, text):
        mo = actions.normalize_motion_v2(self.w, {"type": "diplomacy", "subject": subject, "value": "", "text": text})
        return politics.validate_motion_detail(self.w, {**mo, "passed": False})

    def test_a_pact_in_force_is_not_proposed_again(self):
        self.assertIsNone(self.proposal("non_aggression", "Propose a non-aggression pact to the Solvaran Union."))
        self.w.dip.nonaggression = True
        for text in ("Propose a non-aggression pact to the Solvaran Union.",
                     "Propose a non-aggression pact to Veleria."):
            refused = self.proposal("non_aggression", text)
            self.assertEqual(refused["reason_code"], "ALREADY_IN_FORCE", text)

    def test_an_alliance_in_force_is_not_proposed_again(self):
        self.w.dip.league_alliance = True
        self.assertEqual(self.proposal("alliance", "Propose an alliance with the Maritime League.")["reason_code"],
                         "ALREADY_IN_FORCE")


class PolicyFigures(unittest.TestCase):
    def setUp(self):
        self.w = new_world(1, 36)
        self.motion = {"id": "M1", "type": "set_policy", "subject": "rate", "value": "0.11", "text": RATE_TEXT}

    def test_a_target_the_motion_does_not_set_is_sent_back(self):
        clash = motion_actions.conflict(self.w, self.motion)
        self.assertEqual(clash["reasons"][0]["code"], "POLICY_FIGURES_MISMATCH")
        ask = motion_actions.repair_request(self.w, clash)
        self.assertIn("the text moves rate 6% to 7%, but the motion sets rate to 0.11 (11%)", ask)

    def test_matching_or_absent_figures_pass(self):
        for text in ("Raise the rate from 10% to 11% to stem currency speculation.",
                     "Raise the rate one percentage point to stem currency speculation.",
                     "Raise the rate; unemployment is 7% and inflation 34%."):
            self.assertIsNone(motion_actions.conflict(self.w, {**self.motion, "text": text}), text)


class StormTiming(unittest.TestCase):
    def test_the_storm_damage_is_in_the_state_when_it_is_announced_and_lands_once(self):
        w = new_world(1, 36)
        w.month = 2
        w.tuning = {"dilemmas": {"base_rate": 1.0}}
        storm = {**dilemmas.CATALOGUE["storm"], "weight": lambda w: 1e6}
        with mock.patch.dict(dilemmas.CATALOGUE, {"storm": storm}):
            raised = dilemmas.generate(w)
        self.assertIn("storm", [i["kind"] for i in raised])
        self.assertAlmostEqual(w.region("lissen").damage, 0.03)
        self.assertAlmostEqual(w.region("aster").damage, 0.015)
        w.month = 3
        dilemmas.apply_ongoing(w)
        self.assertAlmostEqual(w.region("lissen").damage, 0.03)


if __name__ == "__main__":
    unittest.main()
