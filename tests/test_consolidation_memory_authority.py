"""Three integrity faults, all three found live in run 20260930-090535-seed1.

They are causally linked, which is why they are pinned together. Two delegates each withdrew their
own farm_support motion to fall in behind the other's, so both left the agenda and the council
voted on no farm policy at all. A third delegate then wrote in its notes that the council had
agreed farm_support=0.05 — a memory the record does not bear out, and one nothing was going to
correct before it became a fact it reasoned from next month. Underneath both, an office order for a
setting that office does not hold was dropped without a word.
"""
import copy
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import freshness, memory, politics  # noqa: E402
from karamaniya.deliberation import resolve_mutual_withdrawals  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


# The two motions exactly as the run recorded them: A withdrew M4 to fall in behind M1, and E
# withdrew M1 to fall in behind M4.
REAL_PAIR = [
    {"id": "M4", "proposer": "A", "type": "set_policy", "subject": "farm_support", "value": "0.05",
     "text": "directive farm_support = 0.05", "summary": "directive farm_support = 0.05",
     "withdrawn": True, "withdrawn_by": "A", "replaced_by": "M1", "cosponsors": [], "passed": False},
    {"id": "M1", "proposer": "E", "type": "set_policy", "subject": "farm_support", "value": "0.04",
     "text": "directive farm_support = 0.04", "summary": "directive farm_support = 0.04",
     "withdrawn": True, "withdrawn_by": "E", "replaced_by": "M4", "cosponsors": [], "passed": False},
]
# B's notes for that month, verbatim.
REAL_NOTE = ("As of Month 1: Council agreed on farm_support=0.05 and arrears settlement via reserves "
             "(quarter). E confirmed no printing.")


class WithdrawalsAreTerminal(unittest.TestCase):
    def test_a_mutual_withdrawal_cycle_is_audited_without_reviving_a_motion(self):
        motions = copy.deepcopy(REAL_PAIR)
        self.assertEqual([m["id"] for m in motions if not m.get("withdrawn")], [],
                         "both motions have been withdrawn")
        collisions = resolve_mutual_withdrawals(motions)
        self.assertEqual([m["id"] for m in motions if not m.get("withdrawn")], [])
        self.assertEqual(len(collisions), 1)
        record = collisions[0]
        self.assertEqual(record["code"], "MUTUAL_WITHDRAWAL_COLLISION")
        self.assertEqual(record["proposers"], {"M4": "A", "M1": "E"})
        self.assertTrue(record["same_family"], "both motions were about farm support")
        self.assertIsNone(record["kept"])
        self.assertEqual(set(record["dropped"]), {"M4", "M1"})

    def test_a_cycle_does_not_clear_terminal_withdrawal_metadata(self):
        a = {"id": "M1", "proposer": "A", "type": "set_policy", "subject": "rail", "value": "x",
             "text": "t", "summary": "s", "withdrawn": True, "replaced_by": "M2", "cosponsors": []}
        b = {"id": "M2", "proposer": "B", "type": "set_policy", "subject": "rail", "value": "x",
             "text": "t", "summary": "s", "withdrawn": True, "replaced_by": "M1", "cosponsors": ["C"]}
        # M2 has a co-sponsor, so it is the one more of the council stood behind.
        resolve_mutual_withdrawals([a, b])
        self.assertEqual([m["id"] for m in (a, b) if not m.get("withdrawn")], [])

    def test_a_one_way_withdrawal_is_left_alone(self):
        a = {"id": "M1", "proposer": "A", "type": "set_policy", "subject": "rail", "value": "x",
             "text": "t", "summary": "s", "withdrawn": True, "replaced_by": "M2", "cosponsors": []}
        b = {"id": "M2", "proposer": "B", "type": "set_policy", "subject": "rail", "value": "x",
             "text": "t", "summary": "s", "cosponsors": []}
        self.assertEqual(resolve_mutual_withdrawals([a, b]), [])
        self.assertTrue(a.get("withdrawn"), "a delegate withdrawing to back another was undone")
        self.assertNotIn("restored_from_collision", b)

    def test_a_three_way_cycle_is_audited_without_reopening_a_motion(self):
        motions = [{"id": f"M{i}", "proposer": p, "type": "set_policy", "subject": "rail", "value": "x",
                    "text": "t", "summary": "s", "cosponsors": []}
                   for i, p in ((1, "A"), (2, "B"), (3, "C"))]
        for mo, target in zip(motions, ("M2", "M3", "M1")):
            mo.update(withdrawn=True, replaced_by=target)
        collisions = resolve_mutual_withdrawals(motions)
        self.assertEqual(len(collisions), 1, "a three-way cycle was seen as three separate pairs")
        self.assertEqual(len([m for m in motions if not m.get("withdrawn")]), 0)
        self.assertEqual(collisions[0]["dropped"], ["M1", "M2", "M3"])

    def test_the_audit_says_all_motions_remain_withdrawn(self):
        motions = copy.deepcopy(REAL_PAIR)
        collisions = resolve_mutual_withdrawals(motions)
        self.assertIn("remain withdrawn", collisions[0]["note"])
        self.assertTrue(all(m["withdrawn"] for m in motions))


class MemoriesMustMatchTheRecord(unittest.TestCase):
    def setUp(self):
        self.w = new_world(1, member_ids=list("ABCDE"))
        self.record = {"month": 0, "motions": copy.deepcopy(REAL_PAIR)}

    def test_the_real_note_is_caught(self):
        found = memory.validate_notes(self.w, "B", REAL_NOTE, self.record)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["code"], "MEMORY_FINAL_STATE_MISMATCH")
        self.assertEqual(found[0]["subject"], "farm_support")
        self.assertEqual(found[0]["motions"], ["M4", "M1"],
                         "both of the delegate's withdrawn motions should be named")
        self.assertIn("never voted on", found[0]["actual"])
        self.assertIn("agreed", found[0]["claim"])

    def test_a_position_a_condition_and_a_true_memory_are_not_claims(self):
        for note in (
            "We should agree on farm support before the recess.",
            "If the council approves farm support, the rural vote is ours.",
            "I propose to agree on farm support next month.",
            "The council rejected farm support; I will bring it back.",
            "Farm support failed, but the argument is not over.",
            "I could agree on farm support only if the Treasury finds the money.",
        ):
            with self.subTest(note=note):
                self.assertEqual(memory.validate_notes(self.w, "B", note, self.record), [])

    def test_a_measure_that_did_pass_may_be_remembered_as_passing(self):
        record = {"month": 0, "motions": [{"id": "M9", "type": "set_policy", "subject": "tax",
                                          "value": "0.22", "summary": "raise tax", "passed": True,
                                          "tally": "4-1"}]}
        self.assertEqual(memory.validate_notes(self.w, "B", "Council agreed to raise tax to 0.22.", record), [])

    def test_the_notes_are_never_rewritten(self):
        w = self.w
        member = w.member("B")
        member.notebook = REAL_NOTE
        member.agent_state = {"notes_month": 0}
        before = member.notebook
        w.month_outcomes = [self.record]
        freshness.notes_parts(w, "B")
        self.assertEqual(member.notebook, before,
                         "reading the notes back rewrote the delegate's own memory")

    def test_the_record_is_placed_beside_the_notes(self):
        w = self.w
        member = w.member("B")
        member.notebook = REAL_NOTE
        member.agent_state = {"notes_month": 0}
        w.month_outcomes = [dict(self.record, label="Month 1")]
        w.policy.farm_support = 0.02
        body, _ = freshness.notes_parts(w, "B")
        self.assertIn("WHAT ACTUALLY HAPPENED", body)
        self.assertIn("never voted on", body)
        self.assertIn(REAL_NOTE, body, "the delegate's own words were dropped instead of kept")
        # It sits in the notes section, not the since-list: the since-list is trimmed first under
        # budget pressure, and a correction that can be dropped is not a correction. It comes
        # before the delegate's own words, which stay verbatim and last.
        self.assertLess(body.index("WHAT ACTUALLY HAPPENED"), body.index(REAL_NOTE))
        self.assertTrue(body.endswith(REAL_NOTE))

    def test_a_checkpoint_from_before_this_change_still_resumes(self):
        """Runs saved earlier have no outcomes recorded, and must degrade to no correction rather
        than to a hollow heading with nothing under it."""
        w = self.w
        w.member("B").notebook = REAL_NOTE
        w.member("B").agent_state = {"notes_month": 0}
        w.month_outcomes = []
        body, _ = freshness.notes_parts(w, "B")
        self.assertNotIn("WHAT ACTUALLY HAPPENED", body)
        self.assertIn(REAL_NOTE, body, "the delegate's own notes went missing with it")

    def test_the_heading_never_promises_a_record_that_is_not_there(self):
        """A month in which no motion was tabled has nothing to recite. A heading telling the
        delegate to read a correction that was never written is worse than no heading."""
        w = self.w
        w.member("B").notebook = "Month 3: a quiet month."
        w.member("B").agent_state = {"notes_month": 0}
        w.month_outcomes = [{"month": 0, "motions": []}]
        body, _ = freshness.notes_parts(w, "B")
        self.assertIn("the list after it are authoritative", body)
        self.assertNotIn("the record below", body)
        # And when there is one, it says so and delivers it.
        w.month_outcomes = [self.record]
        body, _ = freshness.notes_parts(w, "B")
        self.assertIn("the record below are authoritative", body)
        self.assertIn("WHAT ACTUALLY HAPPENED", body)

    def test_the_outcome_is_kept_in_the_shape_the_check_needs(self):
        from karamaniya.council import _keep_month_outcome
        w = self.w
        w.month_outcomes = []
        _keep_month_outcome(w, self.record)
        self.assertEqual(len(w.month_outcomes), 1)
        kept = w.month_outcomes[0]
        self.assertEqual(kept["month"], 0)
        self.assertEqual([mo["id"] for mo in kept["motions"]], ["M4", "M1"])
        self.assertTrue(all(mo["withdrawn"] for mo in kept["motions"]))
        # Bounded: a long run must not carry its whole history in every checkpoint.
        for month in range(20):
            _keep_month_outcome(w, {"month": month, "motions": []})
        self.assertLessEqual(len(w.month_outcomes), 6)

    def test_the_three_states_stay_distinct_in_what_is_in_force(self):
        """"No motion passed" is not "nothing changed": an office can set a lever the council
        never directed, and the record has to say which of the three it is looking at."""
        w = self.w
        member = w.member("B")
        member.notebook = "As of Month 1: we discussed farm support."
        member.agent_state = {"notes_month": 0}
        w.month_outcomes = [dict(self.record, label="Month 1")]
        w.policy.farm_support = 0.03                        # an office set it; the council did not
        w.const.directives["tax"] = 0.22
        w.policy.tax = 0.19                                 # the office is not in line
        tail = freshness.notes_parts(w, "B")[0]
        self.assertIn("farm_support=0.03 (no council directive; the office set this)", tail)
        self.assertIn("the office is not in line", tail)


class OfficeAuthorityMustBeExplicit(unittest.TestCase):
    def setUp(self):
        self.w = new_world(1, member_ids=list("ABCDE"))
        self.w.const.offices.update({"treasury": "D", "interior": "C", "army": "B"})

    def test_every_lever_states_its_authority(self):
        for lever in politics.LEVER_OFFICE:
            self.assertTrue(politics.lever_authority(lever), f"{lever} has no stated authority")
            self.assertEqual(politics.lever_authority(lever),
                             politics.COUNCIL_DIRECTIVE_WITH_OFFICE_EXECUTION)

    def test_an_order_for_another_offices_setting_is_raised_not_dropped(self):
        """It used to be a bare `continue`: the order vanished and the record showed nothing, so a
        delegate could believe it had directed a setting it never touched."""
        raised = []
        politics.apply_orders(self.w, "C", {"interior": {"farm_support": 0.05}}, set(), [], raised)
        self.assertEqual(len(raised), 1)
        self.assertEqual(raised[0]["code"], "UNAUTHORIZED_OFFICE_ACTION")
        self.assertEqual(raised[0]["lever"], "farm_support")
        self.assertEqual(raised[0]["belongs_to"], "treasury")
        self.assertNotEqual(self.w.policy.farm_support, 0.05, "an unauthorized order changed the state")

    def test_a_setting_no_office_holds_is_raised_too(self):
        raised = []
        politics.apply_orders(self.w, "D", {"treasury": {"invented": 1}}, set(), [], raised)
        self.assertEqual([r["reason"] for r in raised], ["not a setting any office holds"])

    def test_the_office_that_holds_the_lever_is_unaffected(self):
        raised = []
        politics.apply_orders(self.w, "D", {"treasury": {"farm_support": 0.03}}, set(), [], raised)
        self.assertEqual(raised, [])
        self.assertEqual(self.w.policy.farm_support, 0.03)

    def test_acting_against_a_live_directive_is_still_defiance_not_unlawfulness(self):
        """The distinction the three-way split exists to keep: an office holder may set its own
        lever against the council's directive, and that is defiance to be recorded, not an order it
        had no authority to give."""
        self.w.const.directives["farm_support"] = 0.02
        raised = []
        defiance = politics.apply_orders(self.w, "D", {"treasury": {"farm_support": 0.05}}, set(), [], raised)
        self.assertEqual(raised, [], "a legitimate order by the responsible office was refused")
        self.assertEqual(len(defiance), 1)
        self.assertEqual(defiance[0]["lever"], "farm_support")


if __name__ == "__main__":
    unittest.main()
