"""A refused act names the acts its target does accept (engine 24, E7).

The census of every recorded run found 21 refusals of an act that its target does not receive: trade talks or status
talks sent to Veleria, Dorsania or the Maritime League, and a grain deal sent as a trade deal. The refusal said which
actors the act can go to, but not which acts the refused target accepts, so a delegate had nothing to put in its place.
The repair request named acts for each target too, but read them from the default receiver of each act
(DIPLOMATIC_ACTIONS) instead of the table the check uses (DIPLOMATIC_TARGETS): for Veleria it named only cede_region,
and for Dorsania only grain_deal.

The refusal goes back to the delegate, in the repair request and in the month's rejected-motions note, so these words
are model-facing. The table itself is not changed here: which acts a target accepts is a design decision.

Engine 27 (wave 3, D) widened six pairs, among them trade_talks to Veleria and status_talks to Veleria; those examples
now pass. The specific assertions below use pairs the proposal keeps refused (a trade deal to Veleria, a grain deal to
Veleria, a federation to Dorsania), so the engine-24 wording stays pinned.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import motion_actions as ma  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def world():
    return new_world(11)


def accepted_by_table(actor: str) -> list:
    """Every act the table lets this actor receive, in DIPLOMATIC_ACTIONS order."""
    return [act for act in ma.DIPLOMATIC_ACTIONS
            if actor in ma.DIPLOMATIC_TARGETS.get(act, {ma.DIPLOMATIC_ACTIONS[act]})]


def refused_pairs():
    for act in ma.DIPLOMATIC_ACTIONS:
        allowed = ma.DIPLOMATIC_TARGETS.get(act, {ma.DIPLOMATIC_ACTIONS[act]})
        for actor in ma.ACTORS:
            if actor not in allowed:
                yield act, actor


def diplomatic_motion(act: str, actor: str) -> dict:
    return {"type": "diplomacy", "subject": ma.ACTION_TO_SUBJECT.get(act, act), "value": "", "text": "",
            "action": {"action_type": act, "target": actor}}


def not_valid_reason(clash: dict) -> dict:
    return next(r for r in clash["reasons"] if r["code"] == "ACTION_NOT_VALID_FOR_TARGET")


class TheRefusalNamesWhatTheTargetAccepts(unittest.TestCase):
    def test_trade_deal_to_veleria_says_what_veleria_accepts(self):
        w = world()
        clash = ma.conflict(w, diplomatic_motion("trade_deal", ma.VELERIA))
        self.assertEqual(not_valid_reason(clash)["detail"],
                         "a trade_deal can be addressed to Dorsania, Maritime League, not the Veleria. Veleria accepts: "
                         "diplomatic_protest, trade_talks, status_talks, non_aggression_pact, renounce, cede_region, "
                         "ultimatum_reply")

    def test_the_execution_gate_gives_the_same_words(self):
        w = world()
        motion = diplomatic_motion("trade_deal", ma.VELERIA)
        gate = ma.validate_diplomatic_action(w, motion)
        self.assertEqual(gate["code"], "ACTION_NOT_VALID_FOR_TARGET")
        self.assertEqual(gate["detail"], not_valid_reason(ma.conflict(w, motion))["detail"])

    def test_every_refused_pair_names_exactly_the_acts_the_table_accepts(self):
        w = world()
        for act, actor in refused_pairs():
            with self.subTest(act=act, actor=actor):
                detail = not_valid_reason(ma.conflict(w, diplomatic_motion(act, actor)))["detail"]
                self.assertIn(". " + ma.ACTOR_NAMES[actor] + " accepts: ", detail)
                listed = detail.split(" accepts: ", 1)[1]
                self.assertEqual(listed.split(", "), accepted_by_table(actor))

    def test_the_gate_and_the_check_agree_on_every_refused_pair(self):
        w = world()
        for act, actor in refused_pairs():
            with self.subTest(act=act, actor=actor):
                motion = diplomatic_motion(act, actor)
                gate = ma.validate_diplomatic_action(w, motion)
                self.assertEqual(gate["code"], "ACTION_NOT_VALID_FOR_TARGET")
                self.assertEqual(gate["detail"], not_valid_reason(ma.conflict(w, motion))["detail"])


class TheRepairRequestNamesTheTablesActs(unittest.TestCase):
    def test_each_refused_target_is_told_every_act_the_table_gives_it(self):
        w = world()
        for act, actor in refused_pairs():
            with self.subTest(act=act, actor=actor):
                repair = ma.repair_request(w, ma.conflict(w, diplomatic_motion(act, actor)))
                expected = (f"Acts the engine can address to the {ma.ACTOR_NAMES[actor]}: "
                            f"{', '.join(accepted_by_table(actor))}.")
                self.assertIn(expected, repair)

    def test_dorsania_is_not_told_only_grain_deal(self):
        w = world()
        repair = ma.repair_request(w, ma.conflict(w, diplomatic_motion("federation", ma.DORSANIA)))
        self.assertIn("Acts the engine can address to the Dorsania: diplomatic_protest, trade_talks, status_talks, "
                      "non_aggression_pact, trade_deal, grain_deal, renounce, cede_region, ultimatum_reply.", repair)

    def test_veleria_is_not_told_only_cede_region(self):
        w = world()
        repair = ma.repair_request(w, ma.conflict(w, diplomatic_motion("grain_deal", ma.VELERIA)))
        self.assertIn("Acts the engine can address to the Veleria: diplomatic_protest, trade_talks, status_talks, "
                      "non_aggression_pact, renounce, cede_region, ultimatum_reply.", repair)


class TheAcceptedPairsAreStillNotRefused(unittest.TestCase):
    def test_every_pair_the_table_accepts_passes_the_check(self):
        w = world()
        for act, actors in ma.DIPLOMATIC_TARGETS.items():
            for actor in actors:
                with self.subTest(act=act, actor=actor):
                    self.assertIsNone(ma.conflict(w, diplomatic_motion(act, actor)))


if __name__ == "__main__":
    unittest.main()
