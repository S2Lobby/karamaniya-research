"""Outstanding integrity + action-vocabulary patch, part 2 of 2."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import politics  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def world():
    return new_world(11)


def arrears_world():
    w = world()
    w.econ.arrears = 100e6
    w.econ.arrears_by = {"army": 10e6, "police": 10e6, "foreign_debt": 10e6,
                         "civil_service": 20e6, "contractors": 50e6}
    return w


def grain_world():
    w = world()
    actors = w.foreign.setdefault("actors", {})
    actors.setdefault("dorsania", {}).setdefault("diplomacy", {}).setdefault(
        "commitments", []).append({"partner": "karamaniya", "until": 99, "kind": "grain_deal"})
    return w


class ExistingDealSemanticsContinued(unittest.TestCase):
    def test_an_expansion_after_a_storm_is_not_a_new_agreement(self):
        self.assertIsNone(politics.validate_motion_detail(grain_world(), {
            "type": "diplomacy", "subject": "grain_deal", "value": "",
            "text": "expand grain deliveries after the storm",
            "action": {"action_type": "grain_deal", "target": "DORSANIA",
                       "deal_action": "EXPAND_VOLUME"}}))

    def test_extending_what_does_not_exist_is_refused(self):
        detail = politics.validate_motion_detail(world(), {
            "type": "diplomacy", "subject": "grain_deal", "value": "",
            "text": "extend the grain deal with Dorsania",
            "action": {"action_type": "grain_deal", "target": "DORSANIA",
                       "deal_action": "EXTEND_EXISTING_DEAL"}})
        self.assertIsNotNone(detail)
        self.assertEqual(detail["reason_code"], "NO_EXISTING_DEAL")


class DeferMotion(unittest.TestCase):
    def test_defer_highlands_until_month_6_is_procedural(self):
        w = world()
        mo = {"id": "D1", "type": "defer_motion", "subject": "M3", "value": "Month 6",
              "text": "defer Highlands until Month 6", "proposer": "A"}
        self.assertIsNone(politics.validate_motion_detail(w, mo))
        result = politics.apply_motion(w, dict(mo))
        self.assertIn("no policy state changed", result)
        self.assertEqual(w.agenda["deferrals"][-1]["target"], "M3")
        self.assertEqual(w.agenda["deferrals"][-1]["until"], 5)
        self.assertNotIn("highlands_status", w.const.directives)

    def test_a_deferral_with_no_target_is_rejected(self):
        detail = politics.validate_motion_detail(world(), {
            "type": "defer_motion", "subject": "", "value": "", "text": "defer stuff"})
        self.assertIsNotNone(detail)
        self.assertEqual(detail["reason_code"], "NO_DEFERRAL_TARGET")


class TargetedArrearsSettlement(unittest.TestCase):
    def test_storm_related_arrears_are_accepted_and_targeted(self):
        w = arrears_world()
        mo = {"type": "settle_arrears", "subject": "reserves",
              "value": "all_of_current_arrears_that_are_storm_related",
              "text": "pay storm-related arrears only"}
        self.assertIsNone(politics.validate_motion_detail(w, mo))
        scope, categories, unknown = politics._arrears_scope(mo, mo["value"])
        self.assertEqual(categories, ["contractors"])
        self.assertEqual(unknown, set())
        before = dict(w.econ.arrears_by)
        politics.apply_motion(w, {**mo, "proposer": "A"})
        self.assertLess(w.econ.arrears_by["contractors"], before["contractors"])
        self.assertAlmostEqual(w.econ.arrears_by["civil_service"], before["civil_service"])
        self.assertAlmostEqual(w.econ.arrears_by["army"], before["army"])

    def test_a_genuinely_unknown_category_is_still_rejected(self):
        detail = politics.validate_motion_detail(arrears_world(), {
            "type": "settle_arrears", "subject": "reserves",
            "value": "all_of_current_arrears_that_are_moon_related",
            "text": "pay moon arrears"})
        self.assertIsNotNone(detail)
        self.assertEqual(detail["reason_code"], "UNKNOWN_ARREARS_CATEGORY")

    def test_plain_gibberish_is_still_a_bad_value(self):
        detail = politics.validate_motion_detail(arrears_world(), {
            "type": "settle_arrears", "subject": "reserves",
            "value": "blorble", "text": "pay blorble"})
        self.assertIsNotNone(detail)
        self.assertEqual(detail["reason_code"], "BAD_VALUE")


class NamedIntegrityRecords(unittest.TestCase):
    def test_kessel_audit_when_no_kessel_audit_ran_is_a_fact_reference_error(self):
        from karamaniya import memory as _memory
        findings = _memory.fact_reference_errors(
            world(), "A", "The Kessel audit found corruption in procurement.")
        self.assertTrue(findings)
        self.assertEqual(findings[0]["code"], "FACT_REFERENCE_ERROR")
        self.assertEqual(findings[0]["referred_to"], "kessel")

    def test_audit_and_kessel_in_separate_clauses_do_not_create_a_false_reference(self):
        from karamaniya import memory as _memory
        findings = _memory.fact_reference_errors(world(), "C",
            "I voted yes on D1 audit, D2 raised officer pay, D3 voluntary recruitment, and M1 Kessel cultural status.")
        self.assertEqual(findings, [])

    def test_a_stale_treasury_order_is_a_named_mismatch_but_policy_still_moves(self):
        w = world()
        w.const.directives["police"] = 0.020
        w.const.offices["treasury"] = "A"
        compliance = []
        defiance = politics.apply_orders(w, "A", {"treasury": {"police": "0.018"}},
                                         fresh=set(), superseded=[], unauthorized=[],
                                         compliance=compliance)
        self.assertEqual(len(defiance), 1)
        clash = compliance[-1]
        self.assertEqual(clash["code"], "DIRECTIVE_ORDER_MISMATCH")
        self.assertAlmostEqual(clash["directive_value"], 0.020)
        self.assertAlmostEqual(clash["office_order_value"], 0.018)
        self.assertAlmostEqual(clash["actual_executed_value"], 0.018)
        self.assertEqual(clash["compliance_status"], "EXPLICIT_VIOLATION")

    def test_an_order_repeating_a_fresh_directive_is_superseded_not_defiance(self):
        w = world()
        w.const.directives["police"] = 0.020
        w.const.offices["treasury"] = "A"
        compliance, superseded = [], []
        defiance = politics.apply_orders(w, "A", {"treasury": {"police": "0.018"}},
                                         fresh={"police"}, superseded=superseded,
                                         unauthorized=[], compliance=compliance)
        self.assertEqual(defiance, [])
        self.assertEqual(len(superseded), 1)
        self.assertEqual(compliance[-1]["compliance_status"], "SUPERSEDED_ORDER")
        self.assertEqual(compliance[-1]["code"], "DIRECTIVE_ORDER_MISMATCH")

    def test_the_acceptance_month_council_police_0020_plus_stale_order(self):
        # The spec's exact month: council passes police=0.020, Treasury's order still says
        # 0.018. The directive stands (policy REMAINS 0.020), the order is set aside, and the
        # mismatch is recorded as SUPERSEDED_ORDER — not defiance, not a silent overwrite.
        import threading
        from karamaniya.council import Council as _Council
        w = new_world(3, 6, member_ids=list("ABCDE"))
        w.const.offices.update({"head": "A", "treasury": "D", "interior": "E",
                                "army": "B", "navy": "C"})
        motion = {"id": "M1", "proposer": "E", "type": "set_policy", "subject": "police",
                  "value": "0.020", "text": "", "summary": "directive police = 0.020"}
        council = _Council.__new__(_Council)
        council.w, council.pending_dms, council.observer, council._lock, council.spend = (
            w, [], None, threading.Lock(), 0.0)
        def _decision(votes, orders):
            return {"votes": votes, "vote_reasons": {}, "vote_conditions": {}, "resign": False,
                    "coup": None, "coup_stance": "resist", "orders": orders, "operations": {},
                    "private_messages": [], "notes": "", "belief_updates": [],
                    "decision_factors": []}
        decisions = {mid: _decision({"M1": "yes"},
                                    {"treasury": {"police": 0.018}} if mid == "D" else {})
                     for mid in "ABCDE"}
        record = council._resolve_v2(decisions, [motion], [motion], [], list("ABCDE"),
                                     [], {}, {}, [], False)
        self.assertAlmostEqual(w.policy.police, 0.020)
        self.assertAlmostEqual(w.const.directives["police"], 0.020)
        self.assertEqual(record["defiance"], [])
        self.assertEqual(len(record["superseded_orders"]), 1)
        clash = record["compliance"][-1]
        self.assertEqual(clash["code"], "DIRECTIVE_ORDER_MISMATCH")
        self.assertAlmostEqual(clash["directive_value"], 0.020)
        self.assertAlmostEqual(clash["office_order_value"], 0.018)
        self.assertAlmostEqual(clash["actual_executed_value"], 0.020)
        self.assertEqual(clash["compliance_status"], "SUPERSEDED_ORDER")


if __name__ == "__main__":
    unittest.main()
