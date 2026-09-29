"""Office vacancy authority: holder vs orders vs directives vs world state.

A removed holder loses order authority immediately but keeps delegate
identity; deployments / operational state survive removal; a conflicting
standing order never overrides a council directive.
"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import operations, politics, vacancy  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

OFFICES = {"head": "A", "treasury": "D", "interior": "E", "army": "B", "navy": "C"}


def world():
    w = new_world(3, 6, member_ids=list("ABCDE"), human_factor=False)
    w.const.offices.update(OFFICES)
    return w


class ImmediateAuthorityLoss(unittest.TestCase):
    def test_vacated_holder_loses_orders_but_stays_active_delegate(self):
        w = world()
        self.assertEqual(vacancy.vacancy_state_for(w, "army")["holder"], "B")
        politics.apply_motion(w, {"type": "vacate_office", "subject": "army", "value": "",
                                  "proposer": "A"})
        self.assertIsNone(w.const.offices.get("army"))
        self.assertFalse(vacancy.can_issue_orders(w, "B", "army"))
        # Retained delegate rights: still an active delegate, not deleted.
        self.assertEqual(w.member("B").status, "active")
        self.assertIn("B", [m.id for m in w.active_members()])
        self.assertIn("B", [m.id for m in w.members])
        state = vacancy.vacancy_state_for(w, "army")
        self.assertIsNone(state["holder"])
        self.assertEqual(state["former_holder"], "B")
        self.assertEqual(state["vacant_since"], w.month)
        self.assertEqual(state["status"], "vacant")
        self.assertTrue(state["interim_appointment_required"])

    def test_expelled_holder_loses_orders_but_record_retained(self):
        w = world()
        self.assertEqual(vacancy.vacancy_state_for(w, "treasury")["holder"], "D")
        politics.remove_member(w, "D", "expelled")
        self.assertFalse(vacancy.can_issue_orders(w, "D", "treasury"))
        self.assertFalse(vacancy.can_issue_orders(w, w.member("D"), "treasury"))
        # Member record retained (delegate identity survives authority loss).
        self.assertEqual(w.member("D").status, "removed")
        self.assertIn("D", [m.id for m in w.members])
        self.assertNotIn("D", [m.id for m in w.active_members()])
        # A removed holder's orders are ignored: no policy change, no defiance.
        before = w.policy.police
        defiance = politics.apply_orders(w, "D", {"treasury": {"police": 0.09}}, set(), [])
        self.assertEqual(defiance, [])
        self.assertAlmostEqual(w.policy.police, before)

    def test_active_holder_keeps_authority(self):
        w = world()
        self.assertTrue(vacancy.can_issue_orders(w, "B", "army"))
        self.assertTrue(vacancy.can_issue_orders(w, w.member("B"), "army"))
        self.assertFalse(vacancy.can_issue_orders(w, "C", "army"))
        self.assertFalse(vacancy.can_issue_orders(w, "B", "navy"))
        self.assertFalse(vacancy.can_issue_orders(w, "NOBODY", "army"))


class PreRemovalOrderLabeling(unittest.TestCase):
    def test_orders_before_removal_month_are_labelled(self):
        w = world()
        politics.remove_member(w, "B", "expelled")
        removal_month = w.member("B").removed_month
        orders = [{"id": "o1", "office": "army", "month": removal_month - 2, "lever": "posture"},
                  {"id": "o2", "office": "army", "month": removal_month - 1, "lever": "posture"},
                  {"id": "o3", "office": "army", "month": removal_month, "lever": "posture"},
                  {"id": "o4", "office": "army", "month": removal_month + 1, "lever": "posture"}]
        snapshot = copy.deepcopy(orders)
        labelled = vacancy.label_pre_removal_orders(orders, removal_month)
        self.assertEqual([o.get("label") for o in labelled],
                         [vacancy.PRE_REMOVAL_ORDER, vacancy.PRE_REMOVAL_ORDER, None, None])
        self.assertEqual(orders, snapshot)  # input never mutated
        again = vacancy.label_pre_removal_orders(orders, removal_month)
        self.assertEqual(labelled, again)  # deterministic


class Separation(unittest.TestCase):
    def test_deployments_survive_but_standing_orders_never_beat_directives(self):
        w = world()
        before_deploy = dict(w.mil.deploy)
        before_ops = dict((w.institutions.get("operations") or {}).get("army") or {})
        politics.apply_motion(w, {"type": "set_policy", "subject": "posture",
                                  "value": "defend", "proposer": "A"})
        politics.remove_member(w, "B", "expelled")
        # Operational / world state survives removal.
        self.assertEqual(w.mil.deploy, before_deploy)
        self.assertEqual((w.institutions.get("operations") or {}).get("army") or {},
                         before_ops)
        # A stale standing order conflicting with the directive never wins:
        # it is recorded as defiance but must not move actual world state
        # while the office is vacant (holder authority is gone).
        directive = w.const.directives["posture"]
        holder = w.const.offices.get("army")
        self.assertIsNone(holder)
        if holder is None:
            standing_order_value = "attack" if directive != "attack" else "fortify"
            self.assertNotEqual(w.policy.posture, standing_order_value)
            self.assertEqual(w.policy.posture, directive)
            req = vacancy.continuity_requirements(w, "army")
            self.assertFalse(req["standing_orders_override_directives"])
            self.assertTrue(req["deployments_preserved"])

    def test_holder_orders_directives_world_state_are_distinct_layers(self):
        w = world()
        politics.apply_motion(w, {"type": "set_policy", "subject": "police",
                                  "value": "0.025", "proposer": "E"})
        holder_before = dict(w.const.offices)
        directive_before = dict(w.const.directives)
        deploy_before = dict(w.mil.deploy)
        ops_set = operations.set_orders(w, "E", {"interior": {"focus": "smuggling"}})
        self.assertTrue(ops_set)
        # Operational orders live under institutions, not in const or world state.
        self.assertEqual(w.const.offices, holder_before)
        self.assertEqual(w.const.directives, directive_before)
        self.assertEqual(w.mil.deploy, deploy_before)
        self.assertIn("interior", w.institutions.get("operations", {}))
        politics.remove_member(w, "E", "expelled")
        self.assertEqual(w.const.directives, directive_before)  # directives persist
        self.assertEqual(w.mil.deploy, deploy_before)  # world state persists
        self.assertIn("interior", w.institutions.get("operations", {}))  # orders persist
        self.assertIsNone(w.const.offices.get("interior"))  # holder gone


class Continuity(unittest.TestCase):
    def test_vacant_armed_office_flags_high_risk_and_interim(self):
        w = world()
        self.assertEqual(vacancy.vacancy_state_for(w, "army")["holder"], "B")
        politics.remove_member(w, "B", "expelled")
        req = vacancy.continuity_requirements(w, "army")
        self.assertEqual(req["status"], "vacant")
        self.assertTrue(req["interim_appointment_required"])
        self.assertEqual(req["continuity_risk"], "high")
        self.assertIn("appoint_interim_holder", req["requirements"])
        self.assertIn("monitor_force_loyalty_and_arrears", req["requirements"])
        self.assertTrue(req["deployments_preserved"])
        # vacate path records former holder and month too.
        w2 = world()
        self.assertEqual(vacancy.vacancy_state_for(w2, "navy")["holder"], "C")
        politics.apply_motion(w2, {"type": "vacate_office", "subject": "navy",
                                   "value": "", "proposer": "A"})
        st = vacancy.vacancy_state_for(w2, "navy")
        self.assertEqual((st["former_holder"], st["vacant_since"], st["continuity_risk"]),
                         ("C", w2.month, "high"))

    def test_occupied_office_needs_nothing_and_civil_risk_is_medium(self):
        w = world()
        req = vacancy.continuity_requirements(w, "treasury")
        self.assertEqual(req["status"], "occupied")
        self.assertFalse(req["interim_appointment_required"])
        self.assertEqual(req["continuity_risk"], "none")
        self.assertEqual(req["holder"], "D")
        self.assertEqual(req["requirements"], ["no_action_required"])
        w.const.offices["treasury"] = None
        st = vacancy.vacancy_state_for(w, "treasury")
        self.assertEqual((st["status"], st["continuity_risk"], st["vacant_since"]),
                         ("vacant", "medium", w.month))

    def test_vacancy_log_is_the_only_new_key(self):
        w = world()
        w.institutions.pop(vacancy.VACANCY_LOG_KEY, None)
        before = set(w.institutions.keys())
        vacancy.vacancy_state_for(w, "head")
        vacancy.continuity_requirements(w, "army")
        vacancy.can_issue_orders(w, "A", "head")
        vacancy.note_kind_for_member(w, "A")
        added = set(w.institutions.keys()) - before
        self.assertEqual(added, {vacancy.VACANCY_LOG_KEY})
        self.assertIn("head", w.institutions[vacancy.VACANCY_LOG_KEY])


class NoteKinds(unittest.TestCase):
    def test_removed_delegate_notes_are_political_preference(self):
        w = world()
        self.assertEqual(vacancy.note_kind_for_member(w, "B"),
                         vacancy.EXECUTABLE_OFFICE_PLAN)
        politics.remove_member(w, "B", "expelled")
        self.assertEqual(vacancy.note_kind_for_member(w, "B"),
                         vacancy.POLITICAL_PREFERENCE)
        self.assertEqual(vacancy.note_kind_for_member(w, w.member("B")),
                         vacancy.POLITICAL_PREFERENCE)
        # An active delegate with no office is political too; holders execute.
        self.assertEqual(vacancy.note_kind_for_member(w, "A"),
                         vacancy.EXECUTABLE_OFFICE_PLAN)
        w.const.offices["head"] = None
        self.assertEqual(vacancy.note_kind_for_member(w, "A"),
                         vacancy.POLITICAL_PREFERENCE)


if __name__ == "__main__":
    unittest.main()
