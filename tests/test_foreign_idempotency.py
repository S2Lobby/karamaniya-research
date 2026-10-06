"""A foreign action's effects are applied once, no matter how many times a month is resolved."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import errors, foreign  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def world_with_cabinet(seed=1):
    w = new_world(seed, 12)
    foreign.prepare(w)
    return w


class ActionIdentity(unittest.TestCase):
    def test_the_same_act_gets_the_same_id_and_a_different_slot_does_not(self):
        a = foreign.action_id("veleria", 3, "propaganda", 0)
        self.assertEqual(a, foreign.action_id("veleria", 3, "propaganda", 0))
        self.assertNotEqual(a, foreign.action_id("veleria", 3, "propaganda", 1))
        self.assertNotEqual(a, foreign.action_id("veleria", 4, "propaganda", 0))
        self.assertNotEqual(a, foreign.action_id("dorsania", 3, "propaganda", 0))
        self.assertNotEqual(a, foreign.action_id("veleria", 3, "grain_embargo", 0))

    def test_identity_survives_a_save_and_load_round_trip(self):
        from karamaniya.world import World
        w = world_with_cabinet()
        again = World.from_dict(w.to_dict())
        self.assertEqual(foreign.action_id("veleria", w.month, "propaganda", 0),
                         foreign.action_id("veleria", again.month, "propaganda", 0))


class ApplyingOnce(unittest.TestCase):
    def _decide(self):
        return {"veleria": {"strategy": "press the advantage",
                            "actions": [{"type": "propaganda", "magnitude": 0.8},
                                        {"type": "military_exercise", "troops": 1000, "magnitude": 0.5}],
                            "decision_factors": ["test"]}}

    def test_effects_are_recorded_with_their_real_delta(self):
        w = world_with_cabinet()
        positions = foreign.positions(w)
        foreign._apply_cabinet_decisions(w, positions, self._decide())
        ledger = foreign.applied_effects(w)
        self.assertEqual(len(ledger), 2)
        prop = next(e for e in ledger if e["action"] == "propaganda")
        self.assertEqual(prop["actor"], "veleria")
        self.assertEqual(prop["status"], "APPLIED")
        self.assertEqual(prop["executed_month"], w.month)
        self.assertIn("propaganda", prop["effects_applied"])
        self.assertGreater(prop["effects_applied"]["propaganda"], 0)

    def test_reapplying_the_same_month_does_not_double_the_effect(self):
        w = world_with_cabinet()
        positions = foreign.positions(w)
        foreign._apply_cabinet_decisions(w, positions, self._decide())
        after_first = w.dip.propaganda
        self.assertGreater(after_first, 0)

        # Resolve the same month a second time, as a replay or a retried call would.
        foreign._apply_cabinet_decisions(w, positions, self._decide())
        self.assertEqual(w.dip.propaganda, after_first, "propaganda was applied twice")
        self.assertEqual(len(foreign.applied_effects(w)), 2, "duplicate entries entered the ledger")
        self.assertEqual(errors.summary(w)["by_code"].get("FOREIGN_ACTION_DUPLICATE"), 2)

    def test_a_duplicate_is_recorded_rather_than_silently_dropped(self):
        w = world_with_cabinet()
        positions = foreign.positions(w)
        foreign._apply_cabinet_decisions(w, positions, self._decide())
        w.audit_errors = []
        foreign._apply_cabinet_decisions(w, positions, self._decide())
        codes = [e["code"] for e in w.audit_errors]
        self.assertEqual(codes.count("FOREIGN_ACTION_DUPLICATE"), 2)

    def test_a_genuinely_different_action_in_the_same_month_still_applies(self):
        w = world_with_cabinet()
        positions = foreign.positions(w)
        foreign._apply_cabinet_decisions(w, positions, self._decide())
        first = w.dip.propaganda
        # A different act in the same month must not be mistaken for a duplicate.
        foreign._apply_cabinet_decisions(w, positions, {"veleria": {
            "actions": [{"type": "offer_talks", "magnitude": 0.5}], "decision_factors": ["test"]}})
        types = {e["action"] for e in foreign.applied_effects(w)}
        self.assertIn("offer_talks", types)
        self.assertEqual(w.dip.propaganda, first)

    def test_the_next_month_applies_fresh_actions(self):
        w = world_with_cabinet()
        positions = foreign.positions(w)
        foreign._apply_cabinet_decisions(w, positions, self._decide())
        first = w.dip.propaganda
        w.month += 1
        foreign._apply_cabinet_decisions(w, positions, self._decide())
        self.assertGreater(w.dip.propaganda, first, "a new month's action was treated as a duplicate")

    def test_an_invalid_action_is_recorded_and_not_applied(self):
        w = world_with_cabinet()
        positions = foreign.positions(w)
        before = w.dip.propaganda
        foreign._apply_cabinet_decisions(w, positions, {"veleria": {
            "actions": [{"type": "declare_war_unilaterally", "magnitude": 1.0}], "decision_factors": []}})
        self.assertEqual(w.dip.propaganda, before)
        self.assertEqual(errors.summary(w)["by_code"].get("FOREIGN_ACTION_INVALID"), 1)
        self.assertEqual(foreign.applied_effects(w), [])

    def test_ledger_is_bounded(self):
        w = world_with_cabinet()
        positions = foreign.positions(w)
        for month in range(foreign.LEDGER_CAP + 40):
            w.month = month
            foreign._apply_cabinet_decisions(w, positions, self._decide())
        self.assertLessEqual(len(foreign.applied_effects(w)), foreign.LEDGER_CAP)

    def test_ledger_survives_save_and_load(self):
        from karamaniya.world import World
        w = world_with_cabinet()
        positions = foreign.positions(w)
        foreign._apply_cabinet_decisions(w, positions, self._decide())
        again = World.from_dict(w.to_dict())
        self.assertEqual(len(foreign.applied_effects(again)), 2)
        # And the duplicate guard still holds on the reloaded world.
        again_positions = foreign.positions(again)
        before = again.dip.propaganda
        foreign._apply_cabinet_decisions(again, again_positions, self._decide())
        self.assertEqual(again.dip.propaganda, before)


if __name__ == "__main__":
    unittest.main()
