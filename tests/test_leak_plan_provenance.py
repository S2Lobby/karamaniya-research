"""A memory may draw an inference from a leak. It may not attribute the leaked document to someone else.

Found on run 20260930-173547-seed1, month 4. Delegate D's notes, handed back to it next month as what it
knows, said:

    "Union intent to annex remains high (65%); leaked plans indicate they are preparing for force
     within months."

What D actually had (from its own prompt): one live issue, "A newspaper obtains real military
deployment plans ... genuine ARMY deployment plans" — Karamaniya's own — and, separately, an
intelligence estimate that Union deployments were 24-48% likely to be preparation for force. No
foreign plan was ever leaked: the simulation has exactly one plan-leak event and it is the state's own.
So the sentence is not a belief marked as an estimate ("I worry the Union may exploit our leaked
plans" is exactly that, and is fine). It is a factual claim that hangs a finding on the wrong document:
evidence about the Union attributed to plans that are not the Union's.

Every existing memory check was about audits, so none of them could see it. The two tags below are the
provenance the brief names: OWN_DEPLOYMENT_PLAN for what the record shows leaked, and
FOREIGN_DEPLOYMENT_PLAN for what a record would have to show before a delegate could say "the Union's
plans".
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import dilemmas, memory  # noqa: E402
from karamaniya.council import Council  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

# Verbatim from run 20260930-173547-seed1, log.jsonl line 189 (decisions[D].notes).
D_NOTE = ("As of Month 5, army loyalty is medium (35-59%). Printing stopped helps credibility but hurts "
          "short-term liquidity; must watch exports. Union intent to annex remains high (65%); leaked plans "
          "indicate they are preparing for force within months.")
D_CLAIM = "leaked plans indicate they are preparing for force within months."

OWN_LEAK = {"id": "I5-leaked_plan", "kind": "leaked_plan", "month": 4, "status": "resolved",
            "title": "A newspaper obtains real military deployment plans",
            "text": "An independent newspaper says it holds genuine army deployment plans and intends to publish.",
            "office_notes": {"army": "Staff confirm the documents are genuine and current."}}
# No such event exists in the engine today. It is what the record would have to contain for a delegate to
# be entitled to speak of a foreign actor's leaked plans.
FOREIGN_LEAK = {"id": "I9-captured_plan", "kind": "captured_plan", "month": 6, "status": "active",
                "plan_owner": memory.FOREIGN_DEPLOYMENT_PLAN, "title": "Union deployment orders captured",
                "text": "A courier carrying Union deployment orders was taken."}


def world(*issues, history=False):
    w = new_world(3, 12, member_ids=list("ABCDE"))
    w.const.offices.update({"head": "B", "treasury": "C", "interior": "E", "army": "D", "navy": "A"})
    state = dilemmas.state(w)
    for issue in issues:
        state["history" if history else "active"].append(dict(issue))
    w.month = 5
    return w


class WhoseDeploymentPlansLeaked(unittest.TestCase):
    def test_the_recorded_leak_is_the_states_own(self):
        self.assertEqual(memory.deployment_plan_provenance(world(OWN_LEAK)), {memory.OWN_DEPLOYMENT_PLAN})

    def test_a_resolved_leak_is_still_a_leak_that_happened(self):
        self.assertEqual(memory.deployment_plan_provenance(world(OWN_LEAK, history=True)),
                         {memory.OWN_DEPLOYMENT_PLAN})

    def test_no_leak_no_provenance(self):
        self.assertEqual(memory.deployment_plan_provenance(world()), set())
        self.assertEqual(memory.deployment_plan_provenance(new_world(3, 12, member_ids=list("ABCDE"))), set())

    def test_a_foreign_plan_needs_a_record_that_says_so(self):
        self.assertEqual(memory.deployment_plan_provenance(world(FOREIGN_LEAK)), {memory.FOREIGN_DEPLOYMENT_PLAN})
        self.assertEqual(memory.deployment_plan_provenance(world(OWN_LEAK, FOREIGN_LEAK)),
                         {memory.OWN_DEPLOYMENT_PLAN, memory.FOREIGN_DEPLOYMENT_PLAN})

    def test_the_tags_are_the_names_the_brief_uses(self):
        self.assertEqual((memory.OWN_DEPLOYMENT_PLAN, memory.FOREIGN_DEPLOYMENT_PLAN),
                         ("OWN_DEPLOYMENT_PLAN", "FOREIGN_DEPLOYMENT_PLAN"))


class TheRecordedSentence(unittest.TestCase):
    def test_it_is_a_reference_error_against_the_record(self):
        found = memory.fact_reference_errors(world(OWN_LEAK), "D", D_NOTE)
        self.assertEqual(len(found), 1, "only the one sentence is at fault")
        finding = found[0]
        self.assertEqual(finding["code"], "FACT_REFERENCE_ERROR")
        self.assertEqual(finding["member"], "D")
        self.assertEqual(finding["referred_to"], "FOREIGN_DEPLOYMENT_PLAN")
        self.assertEqual(finding["canonical"], ["OWN_DEPLOYMENT_PLAN"])
        self.assertEqual(finding["claim"], D_CLAIM)
        self.assertIn("kept as written", finding["note"])

    def test_the_rest_of_the_note_is_not_touched(self):
        """Loyalty, liquidity and a 65% annexation estimate are not claims about a leak."""
        for sentence in D_NOTE.split("; ")[:2]:
            self.assertEqual(memory.fact_reference_errors(world(OWN_LEAK), "D", sentence), [])

    def test_a_note_with_no_such_claim_is_clean(self):
        self.assertEqual(memory.fact_reference_errors(
            world(OWN_LEAK), "D", "Army loyalty is medium. Printing stopped helps credibility."), [])

    def test_the_finding_is_reported_not_rewritten(self):
        w = world(OWN_LEAK)
        before = D_NOTE
        memory.fact_reference_errors(w, "D", D_NOTE)
        self.assertEqual(D_NOTE, before)


class AnInferenceIsNotAnAttribution(unittest.TestCase):
    """Delegates may draw inferences. What they may not do is state the wrong document as the source."""

    def test_the_briefs_valid_belief(self):
        for text in ("Because our deployment plans leaked, I worry the Union may exploit them.",
                     "Our leaked deployment plans could tell the Union where we are thin.",
                     "The leaked plans confirm our vulnerability.",
                     "With the army's plans published, the Union may strike where we are weakest.",
                     "I fear the leaked plans suggest they are preparing for force.",
                     "I believe the leaked plans indicate they are preparing for force.",
                     "If the leaked plans show they are preparing for force, we must mobilise.",
                     "The plans that leaked are ours; what the Union does with them is a risk."):
            with self.subTest(text=text):
                self.assertEqual(memory.fact_reference_errors(world(OWN_LEAK), "D", text), [])

    def test_the_briefs_unsupported_claim(self):
        for text in ("The leaked Union plans show they will attack.",
                     "The leaked plans prove the Union is massing troops on the border.",
                     "Leaked plans reveal they intend to invade within months.",
                     "The published deployment plans confirm Veleria is preparing an offensive.",
                     "Plans leaked to the press show they will strike in the spring."):
            with self.subTest(text=text):
                found = memory.fact_reference_errors(world(OWN_LEAK), "D", text)
                self.assertEqual([f["code"] for f in found], ["FACT_REFERENCE_ERROR"])
                self.assertEqual(found[0]["referred_to"], "FOREIGN_DEPLOYMENT_PLAN")

    def test_a_delegate_may_say_so_when_the_record_supports_it(self):
        """The same sentence is fine in a world whose record contains a foreign plan."""
        for text in ("The leaked Union plans show they will attack.", D_CLAIM):
            with self.subTest(text=text):
                self.assertEqual(memory.fact_reference_errors(world(OWN_LEAK, FOREIGN_LEAK), "D", text), [])


class NoLeakAtAll(unittest.TestCase):
    """With no deployment-plan leak in the record the claim has nothing to be wrongly attributed to: it
    is a memory of an event that did not happen, which is UNSUPPORTED_MEMORY_FACT, not a wrong reference."""

    def test_the_claim_is_unsupported(self):
        w = world()
        self.assertEqual(memory.fact_reference_errors(w, "D", D_CLAIM), [])
        found = memory.unsupported_facts(w, "D", D_NOTE)
        self.assertEqual([f["code"] for f in found], ["UNSUPPORTED_MEMORY_FACT"])
        self.assertEqual(found[0]["claim"], D_CLAIM)
        self.assertIn("no deployment-plan leak", found[0]["note"])

    def test_a_recorded_own_leak_is_not_an_unsupported_fact(self):
        self.assertEqual(memory.unsupported_facts(world(OWN_LEAK), "D", D_NOTE), [])

    def test_the_audit_checks_are_untouched(self):
        w = world()
        w.const.offices["army"] = "D"
        found = memory.unsupported_facts(w, "D", "The army audit was clean and closed the matter.")
        self.assertEqual([(f["code"], f["office"]) for f in found], [("UNSUPPORTED_MEMORY_FACT", "army")])


class InTheMonthRecord(unittest.TestCase):
    def resolve(self, w, notes):
        council = Council.__new__(Council)
        council.w, council.pending_dms, council.observer, council._lock, council.spend = \
            w, [], None, threading.Lock(), 0.0
        decisions = {mid: {"votes": {}, "vote_reasons": {}, "vote_conditions": {}, "resign": False, "coup": None,
                           "coup_stance": "resist", "orders": {}, "operations": {}, "private_messages": [],
                           "notes": notes.get(mid, ""), "belief_updates": [], "decision_factors": []}
                     for mid in "ABCDE"}
        return council._resolve_v2(decisions, [], [], [], list("ABCDE"), [], {}, {}, [], False)

    def test_the_finding_is_recorded_and_the_note_is_kept_verbatim(self):
        w = world(OWN_LEAK)
        record = self.resolve(w, {"D": D_NOTE})
        self.assertEqual([(f["code"], f["member"], f["referred_to"]) for f in record["memory_mismatches"]],
                         [("FACT_REFERENCE_ERROR", "D", "FOREIGN_DEPLOYMENT_PLAN")])
        self.assertEqual(record["decisions"]["D"]["notes"], D_NOTE)
        self.assertEqual(w.member("D").notebook, D_NOTE)

    def test_a_valid_inference_leaves_no_finding(self):
        record = self.resolve(world(OWN_LEAK), {"D": "Because our deployment plans leaked, I worry the Union may exploit them."})
        self.assertEqual(record["memory_mismatches"], [])

    def test_a_public_statement_is_held_to_the_same_reading(self):
        found = memory.fact_reference_errors(world(OWN_LEAK), "D", "Colleagues: the leaked plans show they will attack.")
        self.assertEqual([f["code"] for f in found], ["FACT_REFERENCE_ERROR"])


if __name__ == "__main__":
    unittest.main()
