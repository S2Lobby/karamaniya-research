"""A vote that contradicts the delegate's own last position, and a memory filed against a month
that had already been resolved.

Both are about the same thing: the record has to be internally consistent. A delegate that says it
supports a motion in the response round and then votes against it without a word leaves a hole where
the reason should be, and a delegate that files "outcomes pending" after the outcome is known hands
its future self a question the engine has already answered.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import audits, memory  # noqa: E402
from karamaniya.council import _vote_intent_clashes  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def decision(votes, reasons):
    return {"votes": votes, "vote_reasons": reasons}


class AVoteMustMatchTheStatedIntent(unittest.TestCase):
    def test_a_bare_reversal_is_caught_in_both_directions(self):
        staged = {"stances": {"M5": "support", "M3": "oppose"}}
        found = _vote_intent_clashes(staged, decision(
            {"M5": "no", "M3": "yes"},
            {"M5": "Not in the current fiscal position.", "M3": "It is the right instrument."}))
        self.assertEqual({c["motion"] for c in found}, {"M5", "M3"})
        self.assertTrue(all(c["code"] == "VOTE_INTENT_MISMATCH" for c in found))

    def test_a_delegate_that_says_why_is_left_alone(self):
        """Position changes after hearing the debate are the deliberation working, not a fault.
        What is caught is the reversal nobody explained."""
        for reason in ("I supported it, but the amendment removed the audit clause.",
                       "M2 is withdrawn, so M5 is no longer redundant.",
                       "I vote no on my own motion: the subject maps to Union diplomacy, not League talks.",
                       "On reflection the costing does not survive contact with the reserves.",
                       "I would support it if the audit clause returned; it has not.",
                       "Whereas I opposed it before, the amended text now covers my concern."):
            with self.subTest(reason=reason):
                self.assertEqual(_vote_intent_clashes({"stances": {"M5": "support"}},
                                                      decision({"M5": "no"}, {"M5": reason})), [])

    def test_agreeing_with_yourself_is_not_a_clash(self):
        for stance, vote in (("support", "yes"), ("oppose", "no")):
            with self.subTest(stance=stance):
                self.assertEqual(_vote_intent_clashes({"stances": {"M5": stance}},
                                                      decision({"M5": vote}, {"M5": "As stated."})), [])

    def test_a_stance_that_took_no_side_does_not_constrain_the_vote(self):
        for stance in ("undecided", "conditional"):
            with self.subTest(stance=stance):
                self.assertEqual(_vote_intent_clashes({"stances": {"M5": stance}},
                                                      decision({"M5": "no"}, {"M5": "No."})), [])

    def test_a_motion_the_delegate_never_gave_a_stance_on_is_not_a_clash(self):
        self.assertEqual(_vote_intent_clashes({"stances": {}},
                                              decision({"M5": "no"}, {"M5": "No."})), [])


class AMemoryMustMatchThePhase(unittest.TestCase):
    def setUp(self):
        self.w = new_world(1, member_ids=list("ABCDE"))

    def test_saying_the_month_is_unresolved_after_it_resolved(self):
        for note in ("Voted yes on M2 — confirm whether it passed.",
                     "M3 (League trade), M5 (50M loan); outcomes pending simulation.",
                     "The council has not decided on the loan.",
                     "Awaiting the vote count on M4."):
            with self.subTest(note=note):
                found = memory.validate_note_phase(self.w, "B", note)
                self.assertTrue(found, "a note filed against a resolved month read as unresolved")
                self.assertEqual(found[0]["code"], "MEMORY_PHASE_MISMATCH")

    def test_planning_the_next_move_is_not_a_phase_error(self):
        """"If M5 passes, I will ..." looks forward. A delegate planning its next move is not
        misreading the month it just lived through."""
        for note in ("Next month: publish the report if M5 passes.",
                     "If M3 passes, use the loan to clear arrears before the election.",
                     "Voted yes on all four motions. M1 carried 4-1.",
                     "I will table a revised motion if the audit reports irregularities."):
            with self.subTest(note=note):
                self.assertEqual(memory.validate_note_phase(self.w, "B", note), [])


class AMemoryMustRestOnSomething(unittest.TestCase):
    def setUp(self):
        self.w = new_world(1, member_ids=list("ABCDE"))
        self.w.const.offices["army"] = "B"

    def test_remembering_a_result_the_engine_never_produced(self):
        found = memory.unsupported_facts(self.w, "B", "The army audit was clean and closed the matter.")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["code"], "UNSUPPORTED_MEMORY_FACT")
        self.assertEqual(found[0]["office"], "army")

    def test_a_result_the_engine_did_produce_is_supported(self):
        audits.open_audit(self.w, "army", "A", "audit the army")
        self.w.month = 2
        audits.deliver(self.w)
        self.assertTrue(audits.report_for(self.w, "army") or audits.last_done(self.w, "army"),
                        "the audit produced no report, so this test proves nothing")
        self.assertEqual(memory.unsupported_facts(self.w, "B", "The army audit was clean."), [])

    def test_a_finding_of_wrongdoing_is_not_a_claim_that_it_was_clean(self):
        """The check exists for a delegate remembering an exoneration nobody issued. A delegate
        remembering that something WAS found is making the opposite claim."""
        for note in ("The army audit found serious irregularities.",
                     "The interior inquiry uncovered procurement fraud."):
            with self.subTest(note=note):
                self.assertEqual(memory.unsupported_facts(self.w, "B", note), [])

    def test_intentions_are_not_results(self):
        for note in ("I want an audit of the army this month.",
                     "The audit will examine army procurement next month.",
                     "I should request an interior inquiry."):
            with self.subTest(note=note):
                self.assertEqual(memory.unsupported_facts(self.w, "B", note), [])


if __name__ == "__main__":
    unittest.main()
