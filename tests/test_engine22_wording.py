"""Engine 22, wording: three records that said the wrong thing (run 20261011-105713-seed1, engine world 21).

1. Every unpaid bill was called "inherited", though most arrears were run up by the government's own deficits.
2. A broken promise was recorded as "acted against a recorded political commitment": it named neither the promise
   nor the vote, order or motion that broke it.
3. fact_reference_errors flagged references that were true: a motion on the table that month, a joint inquiry
   offered to a hostile power, an audit still under way, and a sentence that says no investigation is warranted.
   It must still flag an audit that never ran.

The tests drive the engine's own functions on a seeded world, with no model and no network.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import actions, agents, audits, commitments, memory, politics, prompts, resolve  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def world(seed: int = 11):
    w = new_world(seed, 36)
    w.agent_architecture_version = 2
    agents.ensure(w)
    return w


class UnpaidBillsAreNotCalledInherited(unittest.TestCase):
    """Arrears were 28M crowns after Month 1 and 102M by Month 5 in the run, most of it run up by this government's own
    deficits, yet the motion title, the payment record and the rules all called them "inherited"."""

    def test_the_motion_title_calls_the_bills_unpaid(self):
        title = actions.motion_summary(world(), {"type": "settle_arrears", "subject": "reserves", "value": "half"})
        self.assertEqual(title, "pay half of unpaid bills using reserves")

    def test_the_payment_record_calls_the_bills_unpaid(self):
        w = world()
        w.econ.arrears = 100e6
        w.econ.arrears_by = {"civil_service": 50e6, "contractors": 50e6}
        w.econ.gold = 214e6
        result = politics.apply_motion(w, {"type": "settle_arrears", "subject": "domestic_bonds", "value": "quarter",
                                           "text": "", "proposer": "B"})
        self.assertIn("unpaid bills", result)
        self.assertNotIn("inherited", result)

    def test_the_rule_the_delegates_read_calls_the_bills_unpaid(self):
        rule = next(line for line in prompts.RULES.splitlines() if line.startswith("- settle_arrears:"))
        self.assertNotIn("inherited", rule)
        self.assertIn("one-time payment of unpaid state bills;", rule)


def vote_record(*motions, decisions=None):
    return {"motions": list(motions), "decisions": decisions or {}, "defiance": [], "coups": []}


def motion_voted(mid, summary, votes, **extra):
    mo = {"id": mid, "proposer": "B", "type": "set_policy", "subject": "tax", "value": "0.2", "summary": summary,
          "passed": True, "void": False, "withdrawn": False, "votes": votes}
    mo.update(extra)
    return mo


def promise_events(w):
    return [e for e in w.events if e.get("kind") == "promise_broken"]


class BrokenPromisesNameThePromiseAndWhatBrokeIt(unittest.TestCase):
    """A broken promise was reported as "acted against a recorded political commitment", which says neither the
    promise nor the vote that broke it. The event now carries the promise as recorded and the evidence the check found."""

    def test_a_broken_pledge_names_the_promise_and_the_vote_that_broke_it(self):
        w = world()
        w.month = 2
        commitments.record(w, "A", "I will vote for the budget motion.", to="public")
        commitments.evaluate(w, vote_record(motion_voted("M1", "the budget motion", {"A": "no", "B": "yes"})))
        [event] = promise_events(w)
        self.assertIn("I will vote for the budget motion.", event["text"])
        self.assertIn("M1", event["text"])
        self.assertIn("the budget motion", event["text"])

    def test_the_promise_is_named_in_full_however_long_it_is(self):
        w = world()
        w.month = 2
        text = ("I will vote for the budget motion once the Treasury publishes every arrears ledger, the grain import "
                "bill and the monthly reserves figures, and not before.")
        commitments.record(w, "A", text, to="public")
        commitments.evaluate(w, vote_record(motion_voted("M1", "the budget motion", {"A": "no", "B": "yes"})))
        [event] = promise_events(w)
        self.assertIn(text, event["text"])

    def test_an_order_that_breaks_a_promise_is_named_with_its_office_and_value(self):
        w = world()
        w.month = 2
        text = "I will raise military spending."
        commitments.record(w, "C", text, to="public")
        commitments.evaluate(w, vote_record(decisions={"C": {"orders": {"treasury": {"military": "0.01"}}}}))
        [event] = promise_events(w)
        self.assertIn(text, event["text"])
        self.assertIn("treasury", event["text"])
        self.assertIn("0.01", event["text"])

    def test_an_action_that_breaks_a_principle_names_the_vote_that_did_it(self):
        w = world()
        w.month = 3
        promise = commitments.record(w, "C", "I will protect free speech and peaceful protest.", to="public")
        record = {"month": 3, "pre_resolution": {"election_month": -1},
                  "motions": [{"id": "M2", "proposer": "B", "type": "set_policy", "subject": "protest_response",
                               "value": "lethal", "summary": "lethal force against protests", "passed": True,
                               "void": False, "votes": {"C": "yes", "B": "yes"}}],
                  "decisions": {"C": {}}, "defiance": [], "coups": []}
        agents._consequences(w, record)
        [event] = [e for e in promise_events(w) if e.get("promise_id") == promise["id"]]
        self.assertIn("I will protect free speech and peaceful protest.", event["text"])
        self.assertIn("M2", event["text"])
        self.assertIn("lethal force against protests", event["text"])

    def test_an_order_that_breaks_a_principle_names_the_order(self):
        w = world()
        w.month = 3
        promise = commitments.record(w, "C", "I will protect free speech and peaceful protest.", to="public")
        record = {"month": 3, "pre_resolution": {"election_month": -1}, "motions": [],
                  "decisions": {"C": {"orders": {"interior": {"protest_response": "lethal"}}}},
                  "defiance": [], "coups": []}
        agents._consequences(w, record)
        [event] = [e for e in promise_events(w) if e.get("promise_id") == promise["id"]]
        self.assertIn("I will protect free speech and peaceful protest.", event["text"])
        self.assertIn("interior", event["text"])
        self.assertIn("lethal", event["text"])

    def test_the_public_flag_and_the_importance_of_the_event_are_kept(self):
        w = world()
        w.month = 2
        commitments.record(w, "A", "I will vote for the budget motion.", to="B")
        commitments.evaluate(w, vote_record(motion_voted("M1", "the budget motion", {"A": "no", "B": "yes"})))
        [event] = promise_events(w)
        self.assertFalse(event["public"])
        self.assertEqual(event["importance"], 2)


def audit_record(office: str, month: int) -> dict:
    """A finished audit as audits.deliver writes it (only the fields the reference check reads)."""
    return {"id": f"A{month}-{office}", "office": office, "target": None, "by": "E", "opened": month - 2,
            "month": month, "verdict": "clean", "text": f"Audit of the {office} (reported in Month {month + 1}).",
            "accurate": True, "truth": {"wrongdoing": False, "size": 0.0, "allegation_true": None}}


def audit_under_way(office: str, opened: int) -> dict:
    """An audit ordered and not yet reported, as audits.open_audit writes it."""
    return {"id": f"A{opened + 1}-{office}", "office": office, "target": None, "by": "E", "text": "",
            "opened": opened, "due": opened + 1, "supporters": []}


MOTION_ON_THE_TABLE = {"id": "M3", "type": "investigation", "subject": "army", "value": "open", "proposer": "E",
                       "passed": False, "summary": "audit the army"}


class FactReferenceErrorsOnlyClaimAPastAudit(unittest.TestCase):
    """memory.fact_reference_errors reads a reference to an audit as a claim about an audit that ran. A joint inquiry
    with a hostile power, a motion on the table, an audit under way and a negated sentence are not such a claim."""

    def test_a_reference_to_an_audit_that_never_ran_is_still_flagged(self):
        w = world()
        w.month = 9
        audits.state(w)["done"].append(audit_record("interior", 3))
        findings = memory.fact_reference_errors(w, "E", "The army audit found procurement fraud.")
        self.assertEqual([(f["code"], f["referred_to"]) for f in findings], [("FACT_REFERENCE_ERROR", "army")])

    def test_an_army_inquiry_that_never_ran_is_still_flagged_when_no_fine_print_offer_exists(self):
        w = world()
        w.month = 9
        audits.state(w)["done"].append(audit_record("interior", 3))
        findings = memory.fact_reference_errors(w, "E", "The army inquiry found procurement fraud.")
        self.assertEqual([f["referred_to"] for f in findings], ["army"])

    def test_a_negated_reference_does_not_shield_a_positive_claim_in_the_same_sentence(self):
        w = world()
        w.month = 9
        audits.state(w)["done"].append(audit_record("interior", 3))
        findings = memory.fact_reference_errors(w, "E", "No army audit ran, but the army audit found fraud.")
        self.assertEqual([f["referred_to"] for f in findings], ["army"])

    def test_a_sentence_that_says_no_audit_ran_claims_nothing(self):
        w = world()
        w.month = 9
        audits.state(w)["done"].append(audit_record("interior", 3))
        self.assertEqual(memory.fact_reference_errors(w, "E", "No army audit has run this year."), [])

    def test_a_sentence_that_says_no_investigation_is_warranted_claims_nothing(self):
        w = world()
        w.month = 9
        audits.state(w)["done"].append(audit_record("interior", 3))
        self.assertEqual(memory.fact_reference_errors(
            w, "E", "Previous army-target defiance remains part of C's record, but no new investigation is warranted "
                    "this month."), [])

    def test_an_audit_still_under_way_is_not_a_claim_about_a_past_audit(self):
        w = world()
        w.month = 6
        audits.state(w)["done"].append(audit_record("interior", 3))
        audits.state(w)["open"].append(audit_under_way("treasury", 5))
        self.assertEqual(memory.fact_reference_errors(w, "A", "The Treasury audit is due after Month 7;"), [])

    def test_a_motion_deferred_this_month_is_not_a_claim_about_a_past_audit(self):
        w = world()
        w.month = 4
        audits.state(w)["done"].append(audit_record("interior", 3))
        w.agenda["deferred"] = [{"id": "M4", "type": "investigation", "subject": "treasury", "value": "open",
                                 "proposer": "E", "summary": "audit the treasury", "deferred_month": 4}]
        self.assertEqual(memory.fact_reference_errors(
            w, "E", "E's Treasury audit pending; welcome it, publish everything."), [])

    def test_a_motion_on_the_table_this_month_is_not_a_claim_about_a_past_audit(self):
        w = world()
        w.month = 8
        audits.state(w)["done"].append(audit_record("interior", 3))
        text = ("against a procurement-slowing army audit during the ultimatum and the incomplete Charter amendment.")
        self.assertEqual(memory.fact_reference_errors(w, "A", text, motions=[MOTION_ON_THE_TABLE]), [])

    def test_a_finding_claimed_from_an_army_audit_that_only_failed_as_a_motion_is_still_flagged(self):
        w = world()
        w.month = 8
        audits.state(w)["done"].append(audit_record("interior", 3))
        findings = memory.fact_reference_errors(
            w, "A", "The army audit found procurement fraud.", motions=[MOTION_ON_THE_TABLE])
        self.assertEqual([f["referred_to"] for f in findings], ["army"])

    def test_a_motion_on_the_table_names_only_its_own_office(self):
        w = world()
        w.month = 8
        audits.state(w)["done"].append(audit_record("interior", 3))
        findings = memory.fact_reference_errors(w, "A", "The navy audit found fraud.", motions=[MOTION_ON_THE_TABLE])
        self.assertEqual([f["referred_to"] for f in findings], ["navy"])

    def test_a_joint_inquiry_on_the_fine_print_record_is_not_a_claim_about_an_audit(self):
        w = world()
        w.month = 6
        resolve.note(w, "joint_inquiry", "a joint inquiry offered to the Solvaran Union in Month 7")
        audits.state(w)["done"].append(audit_record("interior", 3))
        w.month = 8
        self.assertEqual(memory.fact_reference_errors(
            w, "C", "Army resentment from M7 inquiry and M4-5 pullbacks persists."), [])

    def test_a_joint_inquiry_on_the_record_does_not_excuse_an_inquiry_no_one_offered(self):
        w = world()
        w.month = 6
        resolve.note(w, "joint_inquiry", "a joint inquiry offered to the Solvaran Union in Month 7")
        audits.state(w)["done"].append(audit_record("interior", 3))
        w.month = 8
        findings = memory.fact_reference_errors(w, "C", "Army resentment from M4 inquiry persists.")
        self.assertEqual([f["referred_to"] for f in findings], ["army"])


if __name__ == "__main__":
    unittest.main()
