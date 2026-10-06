"""State freshness: a remembered fact is dated, and never mistaken for the state of the world now.

The recorded case: in Month 7 the Army holder ordered 32,000 against a 31,000 directive; in Month 8 he
ordered 31,000. The Interior holder's notes still read "B still defiant - army at 32K (directive 31K)",
because the state showed the army's actual strength (about 32,000), which moves toward its target only
gradually, and the directive as "3.1e+04"."""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import decision_context, freshness, memory, politics  # noqa: E402
from karamaniya.council import Council  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

OFFICES = {"head": "A", "treasury": "D", "interior": "E", "army": "B", "navy": "C"}
NOTE = "Month 8: B still defiant—army at 32K (directive 31K), patronage ON. Must consider vacating B's office."


def world(month=0):
    w = new_world(3, 6, member_ids=list("ABCDE"))
    w.const.offices.update(OFFICES)
    w.month = month
    return w


def row(w, month):
    """A finished month, as the engine keeps it."""
    return {"month": month, "offices": dict(w.const.offices), "army": w.mil.army.size, "events": list(w.events),
            "hard_state": {"directives": dict(w.const.directives), "war": w.dip.war, "blockade": w.dip.blockade}}


def resolve_month(w, motions, votes, orders, notes=None, statements=None):
    """One month's resolution as the council runs it, then the memory step that follows it."""
    council = Council.__new__(Council)
    council.w, council.pending_dms, council.observer, council._lock, council.spend = w, [], None, threading.Lock(), 0.0
    decisions = {mid: {"votes": dict(votes.get(mid, {})), "vote_reasons": {}, "vote_conditions": {}, "resign": False,
                       "coup": None, "coup_stance": "resist", "orders": orders.get(mid, {}), "operations": {},
                       "private_messages": [], "notes": (notes or {}).get(mid, ""), "belief_updates": [],
                       "decision_factors": []} for mid in "ABCDE"}
    record = council._resolve_v2(decisions, motions, motions, statements or [], list("ABCDE"), [], {}, {}, [], False)
    memory.record_month(w, record)
    w.history.append(row(w, w.month))
    w.month += 1
    return record


def yes(*motion_ids):
    return {mid: {m: "yes" for m in motion_ids} for mid in "ABCDE"}


def army_target_motion():
    return {"id": "M1", "proposer": "C", "type": "set_policy", "subject": "army_target", "value": "31000",
            "text": "", "summary": "directive army_target = 31000"}


def the_recorded_history():
    """Months 1-8: the directive in Month 3, B's violation in Month 7, his order back in line in Month 8."""
    w = world()
    for month in range(2):
        resolve_month(w, [], {}, {})
    resolve_month(w, [army_target_motion()], yes("M1"), {})               # Month 3: directive 31,000
    for _ in range(3):
        resolve_month(w, [], {}, {"B": {"army": {"army_target": 31000.0}}})
    w.mil.army.size = 32000.0
    resolve_month(w, [], {}, {"B": {"army": {"army_target": 32000.0}}})   # Month 7: 32,000 against it
    resolve_month(w, [], {}, {"B": {"army": {"army_target": 31000.0}}},   # Month 8: back to 31,000
                  notes={"E": NOTE})
    w.mil.army.size = 31750.0                                             # the army is still above its target
    return w


class Numbers(unittest.TestCase):
    def test_thousands_are_written_in_full(self):
        self.assertEqual(politics.fmt_value(31000.0), "31,000")
        self.assertEqual(politics.fmt_value(31750.0), "31,750")
        self.assertEqual((politics.fmt_value(0.22), politics.fmt_value(0.045), politics.fmt_value(True),
                          politics.fmt_value("max")), ("0.22", "0.045", "on", "max"))

    def test_the_defiance_event_is_readable_and_structured(self):
        w = world()
        politics.apply_motion(w, army_target_motion())
        politics.apply_orders(w, "B", {"army": {"army_target": 32000.0}})
        event = [e for e in w.events if e["kind"] == "defiance"][0]
        self.assertIn("directive 31,000, order 32,000", event["text"])
        self.assertEqual((event["lever"], event["directive"], event["order"]), ("army_target", 31000.0, 32000.0))


class ThreeDifferentThings(unittest.TestCase):
    def test_directive_order_and_actual_are_stated_apart(self):
        w = world(8)
        w.const.directives["army_target"] = 31000.0
        w.history = [row(w, m) for m in range(8)]                       # in force since before this month
        w.policy.army_target, w.mil.army.size = 31000.0, 31750.0
        text = freshness.directive_text(w)
        self.assertIn("council directive 31,000", text)
        self.assertIn("CURRENT: Delegate B's order is 31,000, in line with it", text)
        self.assertIn("ACTUAL: army strength is about 31,800", text)
        self.assertIn("not anyone's order", text)
        self.assertIn("three different things", text)

    def test_an_order_against_the_directive_is_said_to_be_against_it(self):
        w = world(8)
        w.const.directives["army_target"] = 31000.0
        w.history = [row(w, m) for m in range(8)]
        w.policy.army_target = 32000.0
        self.assertIn("CURRENT: Delegate B's order is 32,000, AGAINST it", freshness.directive_text(w))

    def test_the_state_block_carries_the_status_and_labels_the_forces_line(self):
        w = the_recorded_history()
        block = decision_context.canonical_hard_state_v2(w, "session", [])
        self.assertIn("DIRECTIVE STATUS (as of Month 8)", block)
        self.assertIn("army about 32,000 (actual strength, not the Army holder's target order, which is 31,000)", block)
        self.assertNotIn("e+04", block)


class PastAndCurrent(unittest.TestCase):
    def test_the_violation_is_kept_as_past_and_the_present_is_stated_beside_it(self):
        w = the_recorded_history()
        text = freshness.directive_text(w)
        self.assertIn("PAST: Month 7: Delegate B ordered 32,000 against the 31,000 directive; had brought it back into "
                      "line by Month 8; that violation stays on the record", text)
        self.assertIn("CURRENT: Delegate B's order is 31,000, in line with it", text)
        self.assertIn("ACTUAL: army strength is about 31,800", text)

    def test_history_is_never_overwritten_by_compliance(self):
        w = the_recorded_history()
        (entry,) = freshness.log(w)
        self.assertEqual((entry["month"], entry["order"], entry["directive"], entry["restored_month"], entry["ended"]),
                         (6, 32000.0, 31000.0, 7, "complied"))

    def test_an_open_violation_is_not_called_corrected(self):
        w = world()
        for _ in range(2):
            resolve_month(w, [], {}, {})
        resolve_month(w, [army_target_motion()], yes("M1"), {})
        resolve_month(w, [], {}, {"B": {"army": {"army_target": 32000.0}}})
        self.assertIn("PAST, not corrected as of Month 4: Month 4: Delegate B ordered 32,000 against the 31,000 directive",
                      freshness.directive_text(w))
        self.assertEqual(freshness.log(w)[0]["restored_month"], None)

    def test_a_violation_ends_when_the_directive_is_lifted_or_the_office_changes_hands(self):
        w = world()
        resolve_month(w, [army_target_motion()], yes("M1"), {})
        resolve_month(w, [], {}, {"B": {"army": {"army_target": 32000.0}}})
        w.const.offices["army"] = "C"
        record = resolve_month(w, [], {}, {})
        self.assertEqual([(r["member"], r["ended"]) for r in record["compliance_restored"]], [("B", "office changed hands")])


class MemoryStaysRelevant(unittest.TestCase):
    def test_every_delegate_remembers_the_violation_dated_and_it_does_not_fade(self):
        w = the_recorded_history()
        for mid in "ACDE":
            items = [x for x in w.member(mid).agent_state["memory"] if x["kind"] == "defiance"]
            self.assertEqual(len(items), 1, mid)
            self.assertEqual((items[0]["month"], items[0]["observed_month"], items[0]["claim"], items[0]["source"],
                              items[0]["protected"]), (6, 6, "PAST_EVENT", "council record", True))
            self.assertIn("Delegate B ordered army_target 32,000 against the council's 31,000 directive", items[0]["text"])
        own = [x for x in w.member("B").agent_state["memory"] if x["kind"] == "defiance"][0]
        self.assertTrue(own["text"].startswith("You ordered army_target 32,000"))
        for _ in range(12):
            memory.decay(w)
            w.month += 1
        self.assertTrue([x for x in w.member("E").agent_state["memory"] if x["kind"] == "defiance"])

    def test_compliance_is_remembered_and_says_the_violation_remains_on_the_record(self):
        w = the_recorded_history()
        (item,) = [x for x in w.member("E").agent_state["memory"] if x["kind"] == "compliance_restored"]
        self.assertEqual(item["month"], 7)
        self.assertIn("Delegate B is now ordering army_target 31,000, in line with the 31,000 directive", item["text"])
        self.assertIn("the Month 7 violation remains on the record", item["text"])

    def test_memory_lines_are_dated_and_say_what_kind_of_claim_they_are(self):
        w = the_recorded_history()
        w.month += 1
        memory.add(w, "E", "intel_shared", "Treasury put reserves near 71M.")
        w.month += 1
        text = memory.context(w, "E", {"army_target", "defiance"})
        self.assertIn("each was true as of its month and may have changed since", text)
        self.assertIn("Month 7 (council record): Delegate B ordered army_target 32,000", text)
        items = {x["kind"]: x for x in w.member("E").agent_state["memory"]}
        self.assertEqual(items["intel_shared"]["claim"], "PRIVATE_ESTIMATE")
        self.assertEqual(items["intel_shared"]["source"], "a colleague's report")


class NotesAreDatedAndChecked(unittest.TestCase):
    def test_notes_are_kept_verbatim_with_the_month_they_were_written(self):
        w = the_recorded_history()
        self.assertEqual(w.member("E").notebook, NOTE)                       # never rewritten
        self.assertEqual(w.member("E").agent_state["notes_month"], 7)
        notes, since = freshness.notes_parts(w, "E")
        self.assertIn("written during Month 8, before that month's votes and orders were resolved", notes)
        self.assertIn("authoritative on what is true now", notes)
        self.assertTrue(notes.endswith(NOTE))
        self.assertEqual(w.member("E").notebook, NOTE)

    def test_what_changed_since_the_notes_were_written_is_listed(self):
        w = the_recorded_history()
        _, since = freshness.notes_parts(w, "E")
        self.assertIn("SINCE YOUR NOTES", since)
        self.assertIn("Month 8: Delegate B's order on army_target is 31,000, in line with the directive; the Month 7 "
                      "violation stays on the record.", since)
        self.assertIn("actual army strength is about 31,800 (about 32,000 when you wrote)", since)
        self.assertNotIn("Month 7: Delegate B ordered", since)               # E already knew that when writing

    def test_the_prompt_carries_the_notes_the_since_list_and_the_status_together(self):
        w = the_recorded_history()
        prompt, _ = decision_context.build(w, "E", "session", public_brief="BRIEF", motions=[], instructions="Speak.")
        for part in (NOTE, "SINCE YOUR NOTES", "DIRECTIVE STATUS", "written during Month 8"):
            self.assertIn(part, prompt)
        self.assertLess(prompt.index("written during Month 8"), prompt.index("SINCE YOUR NOTES"))

    def test_notes_with_nothing_changed_add_no_since_list(self):
        w = world(3)
        w.member("E").notebook = "Month 3: nothing special."
        w.member("E").agent_state["notes_month"] = 2
        w.history = [row(w, m) for m in range(3)]
        self.assertEqual(freshness.notes_parts(w, "E")[1], "")

    def test_the_instructions_teach_dated_hedged_notes(self):
        from karamaniya import prompts
        text = prompts.decision_instructions_v2(world(), "E", [], 2, False, False)
        for phrase in ("NOTES AGE", "'as of Month N'", "'has since changed'", "still, currently or remains",
                       "three different things", "stays part of a member's record after they comply"):
            self.assertIn(phrase, text)


class StaleClaims(unittest.TestCase):
    def test_a_claim_that_a_complying_member_is_still_defiant_is_flagged_not_rewritten(self):
        w = the_recorded_history()
        (claim,) = freshness.stale_claims(w, NOTE)
        self.assertEqual(claim["member"], "B")
        self.assertIn("B still defiant", claim["claim"])
        self.assertIn("order on army_target is 31,000 as of Month 8", claim["latest"])
        self.assertEqual(w.member("E").notebook, NOTE)

    def test_past_tense_and_record_statements_are_not_flagged(self):
        w = the_recorded_history()
        for text in ("In Month 7 B defied the 31K directive and ordered 32K.",
                     "B is now complying with the 31K target, but his Month 7 violation remains part of his accountability record.",
                     "B's Month 7 defiance remains on his record."):
            self.assertEqual(freshness.stale_claims(w, text), [], text)

    def test_a_claim_is_fresh_while_the_violation_is_open(self):
        w = world()
        for _ in range(2):
            resolve_month(w, [], {}, {})
        resolve_month(w, [army_target_motion()], yes("M1"), {})
        resolve_month(w, [], {}, {"B": {"army": {"army_target": 32000.0}}})
        self.assertEqual(freshness.stale_claims(w, NOTE), [])

    def test_the_check_runs_against_the_state_the_words_were_written_in(self):
        # Written in Month 8, before B's Month 8 order was known: fresh. Written in Month 9: stale.
        w = world()
        for _ in range(2):
            resolve_month(w, [], {}, {})
        resolve_month(w, [army_target_motion()], yes("M1"), {})
        for _ in range(3):
            resolve_month(w, [], {}, {"B": {"army": {"army_target": 31000.0}}})
        resolve_month(w, [], {}, {"B": {"army": {"army_target": 32000.0}}})                 # Month 7
        record = resolve_month(w, [], {}, {"B": {"army": {"army_target": 31000.0}}}, notes={"E": NOTE})   # Month 8
        self.assertEqual(record["stale_claims"], [])                                        # B was open when E wrote it
        record = resolve_month(w, [], {}, {}, notes={"E": NOTE})                            # Month 9: same words
        self.assertEqual([(c["member"], c["field"]) for c in record["stale_claims"]], [("B", "notes")])


class RunsThatPredateTheRecord(unittest.TestCase):
    def test_the_record_is_read_back_from_the_public_events(self):
        w = world(8)
        w.const.directives["army_target"] = 31000.0
        w.policy.army_target = 31000.0
        w.history = [{"month": m, "offices": dict(OFFICES), "army": 31000.0, "hard_state": {"directives": {"army_target": 31000.0}},
                      "events": ([{"month": 6, "kind": "defiance", "member": "B", "public": True, "importance": 2,
                                   "text": "Delegate B (Army Command) acted against the council directive on army_target: "
                                           "directive 3.1e+04, order 3.2e+04."}] if m == 6 else [])} for m in range(8)]
        (entry,) = freshness.log(w)
        self.assertEqual((entry["month"], entry["member"], entry["lever"], entry["directive_text"], entry["order_text"]),
                         (6, "B", "army_target", "31,000", "32,000"))
        self.assertTrue(entry["backfilled"])
        self.assertEqual((entry["restored_month"], entry["ended"]), (7, "complied"))     # in line as of the last finished month
        self.assertIn("PAST: Month 7: Delegate B ordered 32,000 against the 31,000 directive", freshness.directive_text(w))

    def test_notes_saved_before_the_stamp_existed_are_taken_as_last_months(self):
        w = world(8)
        w.member("E").notebook = "old note"
        w.member("E").agent_state.pop("notes_month", None)
        self.assertEqual(freshness.notes_written_month(w, "E"), 7)


class BackfillIsHonest(unittest.TestCase):
    def legacy_world(self):
        w = world(8)
        w.const.directives.update({"army_target": 31000.0, "police": 0.02})
        w.policy.army_target, w.policy.police = 31000.0, 0.02

        def event(month, member, lever, directive, order):
            return {"month": month, "kind": "defiance", "member": member, "public": True, "importance": 2,
                    "text": f"Delegate {member} acted against the council directive on {lever}: directive {directive}, "
                            f"order {order}."}
        rows = []
        for m in range(8):
            directives = {"army_target": 31000.0} if m < 2 else {"army_target": 31000.0, "police": 0.02}
            rows.append({"month": m, "offices": dict(OFFICES), "army": 31000.0, "hard_state": {"directives": directives},
                         "events": ([event(2, "D", "police", "0.02", "0.015")] if m == 2 else []) +
                                   ([event(6, "B", "army_target", "3.1e+04", "3.2e+04")] if m == 6 else [])})
        w.history = rows
        return w

    def test_a_violation_of_a_directive_adopted_that_same_month_is_not_recorded(self):
        # The old engine recorded a holder's stale order as defiance of a directive passed in the same month.
        w = self.legacy_world()
        self.assertEqual([(e["member"], e["lever"]) for e in freshness.log(w)], [("B", "army_target")])

    def test_a_backfilled_end_date_is_only_as_of_the_last_finished_month_and_is_not_news(self):
        w = self.legacy_world()
        (entry,) = freshness.log(w)
        self.assertTrue(entry["approx"])
        w.member("E").notebook = "Month 8: B still defiant."
        w.member("E").agent_state["notes_month"] = 7
        self.assertNotIn("stays on the record", freshness.notes_parts(w, "E")[1])


class TheStatusBlockStaysShort(unittest.TestCase):
    def test_directives_with_nothing_to_say_share_one_line(self):
        w = world(8)
        w.const.directives.update({"tax": 0.22, "military": 0.045, "police": 0.025, "army_target": 31000.0})
        w.policy.tax, w.policy.military, w.policy.police, w.policy.army_target = 0.22, 0.045, 0.025, 31000.0
        w.history = [row(w, m) for m in range(8)]
        text = freshness.directive_text(w)
        self.assertIn("- In line, with nothing on the record: ", text)
        for item in ("tax 0.22 (Month 1)", "military 0.045 (Month 1)", "police 0.025 (Month 1)"):
            self.assertIn(item, text)
        self.assertEqual(sum(1 for line in text.splitlines() if line.startswith("- army_target")), 1)   # the three-way line stays
        self.assertEqual(len(text.splitlines()), 3)
        self.assertLess(len(text), 900)


if __name__ == "__main__":
    unittest.main()
