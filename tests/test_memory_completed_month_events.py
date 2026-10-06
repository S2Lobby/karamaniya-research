"""Completed-month memories use the engine's final event list and preserve its date."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import agents, audits, memory  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


class CompletedMonthEvents(unittest.TestCase):
    def test_late_leak_and_engine_events_are_remembered_once_with_the_completed_month(self):
        w = new_world(1, member_ids=list("ABCDE"), agent_architecture_version=2)
        agents.ensure(w)
        completed_month = 4
        w.month = completed_month

        leaked_text = "I support the grain corridor under civilian control."
        w.event("leak", "A private message was published.",
                **{"from": "B", "to": "C", "leaked_text": leaked_text,
                   "headline": "A private message was published"})
        region = w.k_regions()[0].id
        w.event("relief_underfunded", "The treasury funded only part of the promised relief.",
                region=region, member="D")

        # Audit delivery writes its own memory while the engine is still in this month.
        w.const.offices["army"] = "B"
        audit_text = "The army audit found no material irregularities."
        audits._consequences(w, {"office": "army", "target": "B", "by": "A"},
                             {"verdict": "clean", "text": audit_text})

        # This is the state seen by Council after engine.step: the clock has advanced and
        # last_events holds all events from the completed month.
        w.last_events = list(w.events)
        w.month = completed_month + 1
        record = {"month": completed_month, "motions": []}
        memory.record_month(w, record, events=w.last_events, completed_month=completed_month)
        memory.record_month(w, record, events=w.last_events, completed_month=completed_month)

        entries = w.member("A").agent_state["memory"]
        leak = [x for x in entries if x["kind"] == "leak"]
        relief = [x for x in entries if x["kind"] == "relief_underfunded"]
        audit = [x for x in entries if x["kind"] == "audit_report" and x["text"] == audit_text]
        self.assertEqual(len(leak), 1)
        self.assertIn(leaked_text, leak[0]["text"])
        self.assertEqual(leak[0]["month"], completed_month)
        self.assertEqual(leak[0]["provenance"]["layer"], "RAW_SOURCE")
        self.assertEqual(len(relief), 1)
        self.assertEqual(relief[0]["month"], completed_month)
        self.assertEqual(relief[0]["execution_status"], "PARTIALLY_EXECUTED")
        self.assertEqual(len(audit), 1, "post-engine event capture duplicated audits.deliver's direct memory")
        self.assertEqual(audit[0]["month"], completed_month)


if __name__ == "__main__":
    unittest.main()
