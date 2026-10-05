"""A directive that passes this month cannot be defied by an order written before its vote was counted.

Recorded in a real run: the Treasury holder voted yes on farm_support 0.03, repeated the current
0.02 in his orders as the instructions ask, and was recorded as defying the council. Twice more the
same happened after a no vote, and a colleague moved to dismiss him for it."""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import politics  # noqa: E402
from karamaniya.council import Council, _keep_month_outcome  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

OFFICES = {"head": "A", "treasury": "D", "interior": "E", "army": "B", "navy": "C"}


def world():
    w = new_world(3, 6, member_ids=list("ABCDE"))
    w.const.offices.update(OFFICES)
    return w


class OrdersAgainstFreshDirectives(unittest.TestCase):
    def test_office_orders_and_their_effective_state_survive_in_checkpoint_outcomes(self):
        w = world()
        w.policy.mobilization = "partial"
        order_history = []

        politics.apply_orders(w, "B", {"army": {"mobilization": "none"}},
                              order_history=order_history)

        self.assertEqual(order_history, [{"member": "B", "office": "army", "lever": "mobilization",
                                          "order": "none", "directive": None,
                                          "previous_value": "partial", "actual_value": "none",
                                          "status": "applied"}])
        _keep_month_outcome(w, {"month": 0, "motions": [], "office_orders": order_history})
        self.assertEqual(w.month_outcomes[-1]["office_orders"], order_history)

    def test_an_order_for_a_setting_directed_this_month_is_set_aside_not_defiance(self):
        w = world()
        politics.apply_motion(w, {"type": "set_policy", "subject": "police", "value": "0.025", "proposer": "E"})
        superseded = []
        defiance = politics.apply_orders(w, "D", {"treasury": {"police": 0.02, "tax": 0.21}}, {"police"}, superseded)
        self.assertEqual(defiance, [])
        self.assertAlmostEqual(w.policy.police, 0.025)              # the directive stands
        self.assertAlmostEqual(w.policy.tax, 0.21)                   # the rest of the order is applied
        self.assertEqual([(s["lever"], s["order"], s["directive"]) for s in superseded], [("police", 0.02, 0.025)])

    def test_an_order_that_matches_the_new_directive_leaves_no_trace(self):
        w = world()
        politics.apply_motion(w, {"type": "set_policy", "subject": "police", "value": "0.025", "proposer": "E"})
        superseded = []
        self.assertEqual(politics.apply_orders(w, "D", {"treasury": {"police": 0.025}}, {"police"}, superseded), [])
        self.assertEqual(superseded, [])

    def test_new_numeric_directive_replaces_the_old_bound_before_compliance_is_judged(self):
        w = world()
        w.const.directives["rate"] = 0.09
        w.const.directive_bounds["rate"] = {"min": 0.09, "max": 0.09}
        prior_directives = dict(w.const.directives)
        prior_bounds = dict(w.const.directive_bounds)
        politics.apply_motion(w, {"type": "set_policy", "subject": "rate", "value": "0.10", "proposer": "E"})
        compliance = []

        defiance = politics.apply_orders(
            w, "D", {"treasury": {"rate": 0.10}}, {"rate"}, [], [], compliance,
            prior_directives, prior_bounds,
        )

        self.assertEqual(defiance, [])
        self.assertEqual(compliance[-1]["compliance_status"], politics.COMPLIANT)
        self.assertEqual(w.policy.rate, 0.10)

    def test_old_order_is_superseded_when_a_new_directive_changes_the_value(self):
        w = world()
        w.const.directives["rate"] = 0.10
        w.const.directive_bounds["rate"] = {"min": 0.10, "max": 0.10}
        prior_directives = dict(w.const.directives)
        prior_bounds = dict(w.const.directive_bounds)
        politics.apply_motion(w, {"type": "set_policy", "subject": "rate", "value": "0.12", "proposer": "E"})
        superseded, compliance = [], []

        defiance = politics.apply_orders(
            w, "D", {"treasury": {"rate": 0.10}}, {"rate"}, superseded, [], compliance,
            prior_directives, prior_bounds,
        )

        self.assertEqual(defiance, [])
        self.assertEqual(compliance[-1]["compliance_status"], politics.SUPERSEDED_ORDER)
        self.assertEqual(w.policy.rate, 0.12)
        self.assertEqual(superseded[-1]["directive"], 0.12)

    def test_new_enum_directive_does_not_mislabel_its_matching_order_as_defiance(self):
        w = world()
        w.const.directives["shipbuilding"] = True
        w.const.directive_bounds["shipbuilding"] = {"min": True, "max": True}
        prior_directives = dict(w.const.directives)
        prior_bounds = dict(w.const.directive_bounds)
        politics.apply_motion(w, {"type": "set_policy", "subject": "shipbuilding", "value": "off", "proposer": "E"})
        compliance = []

        defiance = politics.apply_orders(
            w, "C", {"navy": {"shipbuilding": False}}, {"shipbuilding"}, [], [], compliance,
            prior_directives, prior_bounds,
        )

        self.assertEqual(defiance, [])
        self.assertEqual(compliance[-1]["compliance_status"], politics.COMPLIANT)
        self.assertFalse(w.policy.shipbuilding)

    def test_a_directive_already_in_force_is_still_defied_knowingly(self):
        w = world()
        politics.apply_motion(w, {"type": "set_policy", "subject": "police", "value": "0.025", "proposer": "E"})
        defiance = politics.apply_orders(w, "D", {"treasury": {"police": 0.02}}, set(), [])   # a month later
        self.assertEqual([(d["lever"], d["directive"], d["value"]) for d in defiance], [("police", 0.025, 0.02)])
        self.assertAlmostEqual(w.policy.police, 0.02)                # the holder's order still wins, as before

    def test_calling_it_the_old_way_is_unchanged(self):
        w = world()
        politics.apply_motion(w, {"type": "set_policy", "subject": "protest_response", "value": "tolerate", "proposer": "A"})
        self.assertEqual(len(politics.apply_orders(w, "E", {"interior": {"protest_response": "lethal"}})), 1)


class UnknownLeverNote(unittest.TestCase):
    def test_patronage_names_and_typos_get_a_suggestion(self):
        w = world()
        note = lambda subject: politics.validate_motion_detail(
            w, {"type": "set_policy", "subject": subject, "value": "off", "proposer": "E"})["explanation"]
        self.assertIn("patronage_army", note("army patronage"))            # the council can direct it, under its own name
        self.assertIn("use patronage_army, patronage_navy or patronage_interior", note("patronage"))
        self.assertIn("did you mean recruitment", note("army_recrutiment"))
        self.assertIn("settings the council can direct: ", note("zzzzqq"))
        self.assertEqual(politics.validate_motion_detail(
            w, {"type": "set_policy", "subject": "zzzzqq", "value": "1", "proposer": "E"})["reason_code"], "UNKNOWN_LEVER")

    def test_a_name_a_delegate_reached_for_resolves_instead_of_being_suggested(self):
        """Delegates asked for army_recruitment_focus twelve times in the archived runs.

        It used to come back as "did you mean recruitment". It now resolves to `recruitment`, so
        the real intention is carried out rather than explained back to its author.
        """
        w = world()
        self.assertEqual(politics.canonical_lever("army_recruitment_focus"), "recruitment")
        result = politics.validate_motion_detail(
            w, {"type": "set_policy", "subject": "army_recruitment_focus", "value": "partial", "proposer": "E"})
        self.assertIsNone(result, "a real intention was rejected because of its wording")

    def test_the_two_training_settings_are_not_confused_for_one_another(self):
        """`training_focus` is the Army office's operational setting, not a council lever."""
        w = world()
        result = politics.validate_motion_detail(
            w, {"type": "set_policy", "subject": "training_focus", "value": "intense", "proposer": "E"})
        self.assertIsNotNone(result)
        self.assertEqual(result["reason_code"], "UNKNOWN_LEVER")
        self.assertIn("training_intensity", result["explanation"])
        self.assertIn("operational order", result["explanation"])


def decision(votes, orders):
    return {"votes": votes, "vote_reasons": {}, "vote_conditions": {}, "resign": False, "coup": None,
            "coup_stance": "resist", "orders": orders, "operations": {}, "private_messages": [], "notes": "",
            "belief_updates": [], "decision_factors": []}


def resolve(w, motion, votes, orders):
    """One month's resolution with the votes and orders given, as the council runs it."""
    council = Council.__new__(Council)
    council.w, council.pending_dms, council.observer, council._lock, council.spend = w, [], None, threading.Lock(), 0.0
    decisions = {mid: decision({motion["id"]: vote}, orders.get(mid, {})) for mid, vote in votes.items()}
    return council._resolve_v2(decisions, [motion], [motion], [], list("ABCDE"), [], {}, {}, [], False)


class TheRecordedCase(unittest.TestCase):
    def motion(self, subject, value):
        return {"id": "M1", "proposer": "E", "type": subject and "set_policy", "subject": subject, "value": value,
                "text": "", "summary": f"directive {subject} = {value}"}

    def test_voting_yes_and_repeating_the_old_value_is_not_defiance(self):           # Month 2, farm_support
        w = world()
        record = resolve(w, self.motion("farm_support", "0.03"), dict.fromkeys("ABCDE", "yes"),
                         {"D": {"treasury": {"farm_support": 0.02}}})
        self.assertEqual(record["defiance"], [])
        self.assertAlmostEqual(w.policy.farm_support, 0.03)
        self.assertEqual(w.const.directives["farm_support"], 0.03)
        self.assertEqual([(s["member"], s["lever"], s["order"], s["directive"]) for s in record["superseded_orders"]],
                         [("D", "farm_support", 0.02, 0.03)])

    def test_voting_no_and_writing_your_own_preference_is_not_defiance_either(self):  # Month 3, police
        w = world()
        record = resolve(w, self.motion("police", "0.025"), {"A": "yes", "B": "yes", "C": "yes", "D": "no", "E": "yes"},
                         {"D": {"treasury": {"police": 0.015}}})
        self.assertEqual(record["defiance"], [])
        self.assertAlmostEqual(w.policy.police, 0.025)
        self.assertFalse(any(e["kind"] == "defiance" for e in w.events))

    def test_the_month_after_it_is_real_defiance_and_is_recorded(self):
        w = world()
        resolve(w, self.motion("police", "0.025"), {"A": "yes", "B": "yes", "C": "yes", "D": "no", "E": "yes"}, {})
        w.month += 1
        motion = {**self.motion("tax", "0.22"), "id": "M1"}
        record = resolve(w, motion, dict.fromkeys("ABCDE", "yes"), {"D": {"treasury": {"police": 0.015}}})
        self.assertEqual([(d["member"], d["lever"], d["directive"], d["value"]) for d in record["defiance"]],
                         [("D", "police", 0.025, 0.015)])
        self.assertAlmostEqual(w.policy.police, 0.015)

    def test_a_motion_that_failed_leaves_the_order_alone(self):
        w = world()
        before = w.policy.police
        record = resolve(w, self.motion("police", "0.025"), {"A": "no", "B": "no", "C": "no", "D": "yes", "E": "yes"},
                         {"D": {"treasury": {"police": 0.03}}})
        self.assertEqual(record["defiance"], [])
        self.assertEqual(record["superseded_orders"], [])
        self.assertAlmostEqual(w.policy.police, 0.03)                 # no directive, so the holder's order applies
        self.assertNotEqual(w.policy.police, before)
        change = next(x for x in record["office_orders"] if x["lever"] == "police")
        self.assertEqual((change["member"], change["office"], change["status"]),
                         ("D", "treasury", "applied"))
        self.assertEqual((change["previous_value"], change["actual_value"]), (before, 0.03))

    def test_program_measure_supersedes_a_pre_vote_office_order(self):
        w = world()
        motion = {"id": "M1", "proposer": "D", "type": "program", "subject": "fiscal_stabilization",
                  "value": "package", "text": "Temporarily pause shipbuilding.",
                  "action": {"measures": [{"lever": "shipbuilding", "value": "off"}]},
                  "summary": "fiscal package"}
        record = resolve(w, motion, dict.fromkeys("ABCDE", "yes"),
                         {"C": {"navy": {"shipbuilding": True}}})
        self.assertFalse(w.policy.shipbuilding)
        self.assertEqual(w.const.directives["shipbuilding"], False)
        self.assertEqual(record["defiance"], [])
        self.assertEqual([(row["lever"], row["order"], row["directive"])
                          for row in record["superseded_orders"]], [("shipbuilding", True, False)])
        package = next(row for row in record["motions"] if row["id"] == "M1")
        self.assertEqual(package["final_structured_action"]["measures"],
                         [{"lever": "shipbuilding", "value": False}])

    def test_program_measure_can_be_deliberately_defied_next_month(self):
        w = world()
        package = {"id": "P1", "proposer": "D", "type": "program", "subject": "fiscal_stabilization",
                   "value": "package", "text": "Pause shipbuilding.",
                   "action": {"measures": [{"lever": "shipbuilding", "value": "off"}]},
                   "summary": "fiscal package"}
        resolve(w, package, dict.fromkeys("ABCDE", "yes"), {})
        w.month += 1
        unrelated = {"id": "M1", "proposer": "D", "type": "set_policy", "subject": "tax",
                     "value": "0.22", "text": "", "summary": "directive tax = 0.22"}
        record = resolve(w, unrelated, dict.fromkeys("ABCDE", "yes"),
                         {"C": {"navy": {"shipbuilding": True}}})
        self.assertEqual([(d["member"], d["lever"], d["directive"], d["value"])
                          for d in record["defiance"]], [("C", "shipbuilding", False, True)])

    def test_program_replaces_an_older_numeric_directive_bound(self):
        w = world()
        politics.apply_motion(w, {"type": "set_policy", "subject": "tax", "value": "0.20", "proposer": "D"})
        politics.apply_motion(w, {"type": "program", "subject": "fiscal_stabilization", "value": "package",
                                  "action": {"measures": [{"lever": "tax", "value": "0.22"}]},
                                  "proposer": "D"})

        defiance = politics.apply_orders(w, "D", {"treasury": {"tax": 0.22}})

        self.assertEqual(defiance, [])
        self.assertEqual(w.const.directives["tax"], 0.22)
        self.assertEqual(w.const.directive_bounds["tax"], {"min": 0.22, "max": 0.22})

    def test_stale_saved_bound_cannot_mark_a_matching_order_as_defiance(self):
        w = world()
        w.const.directives["tax"] = 0.22
        w.const.directive_bounds["tax"] = {"min": 0.20, "max": 0.20}

        defiance = politics.apply_orders(w, "D", {"treasury": {"tax": 0.22}})

        self.assertEqual(defiance, [])
        self.assertAlmostEqual(w.policy.tax, 0.22)

    def test_reaffirming_a_directive_does_not_hide_a_preexisting_defiance(self):
        w = world()
        package = {"id": "P1", "proposer": "D", "type": "program", "subject": "fiscal_stabilization",
                   "value": "package", "text": "Pause shipbuilding.",
                   "action": {"measures": [{"lever": "shipbuilding", "value": "off"}]},
                   "summary": "fiscal package"}
        resolve(w, package, dict.fromkeys("ABCDE", "yes"), {})
        w.month += 1
        reaffirmation = {**package, "id": "P2"}
        record = resolve(w, reaffirmation, dict.fromkeys("ABCDE", "yes"),
                         {"C": {"navy": {"shipbuilding": True}}})
        self.assertFalse(w.policy.shipbuilding)
        self.assertEqual([(d["member"], d["lever"], d["directive"], d["value"])
                          for d in record["defiance"]], [("C", "shipbuilding", False, True)])
        compliance = [row for row in record["compliance"] if row["lever"] == "shipbuilding"]
        self.assertEqual(len(compliance), 1)
        self.assertEqual(compliance[0]["compliance_status"], politics.EXPLICIT_VIOLATION)
        self.assertIn("month open", compliance[0]["note"])


if __name__ == "__main__":
    unittest.main()
