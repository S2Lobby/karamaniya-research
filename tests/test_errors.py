"""The structured error ledger: every rejection is data, and every code is registered."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import director, engine, errors  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def run(w, months, each=None):
    original = director.act
    director.act = lambda world, *_a, **_k: setattr(world.dip, "inbox", [])
    try:
        for _ in range(months):
            if w.ended():
                break
            engine.begin_month(w)
            if each:
                each(w)
            engine.step(w)
    finally:
        director.act = original
    return w


class Taxonomy(unittest.TestCase):
    def test_every_code_the_brief_names_is_registered(self):
        # The mission brief names these explicitly as required distinct outcomes.
        required = ["UNKNOWN_ACTION", "INVALID_RECIPIENT", "MOTION_SEMANTIC_MISMATCH",
                    "NUMERIC_GROUNDING_ERROR", "UNAUTHORIZED_OFFICE_ACTION", "STALE_AUTHORITY",
                    "CONDITION_UNRESOLVED", "FOREIGN_ACTION_DUPLICATE", "MEMORY_PHASE_MISMATCH"]
        for code in required:
            with self.subTest(code=code):
                self.assertTrue(errors.is_registered(code), f"{code} missing from the taxonomy")

    def test_descriptions_are_complete(self):
        for entry in errors.taxonomy():
            with self.subTest(code=entry["code"]):
                self.assertTrue(entry["description"].strip())
                self.assertIn(entry["severity"], ("info", "warning", "error"))
                self.assertTrue(entry["category"].strip())

    def test_taxonomy_is_sorted_and_unique(self):
        codes = [e["code"] for e in errors.taxonomy()]
        self.assertEqual(codes, sorted(codes))
        self.assertEqual(len(codes), len(set(codes)))


class Recording(unittest.TestCase):
    def test_record_adds_one_entry_and_summarises_it(self):
        w = new_world(1, 3)
        before = errors.summary(w)["total"]
        entry = errors.record(w, "UNKNOWN_LEVER", "no such lever", member="B")
        self.assertEqual(errors.summary(w)["total"], before + 1)
        self.assertEqual(entry["code"], "UNKNOWN_LEVER")
        self.assertEqual(entry["severity"], "info")
        self.assertEqual(entry["month"], 0)
        self.assertEqual(entry["details"]["member"], "B")
        self.assertEqual(errors.summary(w)["by_code"]["UNKNOWN_LEVER"], 1)

    def test_unregistered_code_is_self_policing(self):
        w = new_world(1, 3)
        entry = errors.record(w, "TOTALLY_NEW_FAILURE", "invented on the spot")
        self.assertFalse(entry["registered"])
        self.assertEqual(entry["code"], "UNREGISTERED_ERROR_CODE")
        self.assertEqual(entry["originally_attempted"], "TOTALLY_NEW_FAILURE")
        self.assertEqual(errors.summary(w)["unregistered"], 1)

    def test_recording_does_not_mutate_canonical_state(self):
        w = new_world(1, 3)
        before = w.to_dict()
        errors.record(w, "UNKNOWN_ACTION", "probe")
        after = w.to_dict()
        # Only the ledger and the event timeline may change; no state variable may move.
        for key in ("audit_errors", "events"):
            before.pop(key, None)
            after.pop(key, None)
        self.assertEqual(copy.deepcopy(before), copy.deepcopy(after))

    def test_event_is_emitted_but_not_public(self):
        w = new_world(1, 3)
        errors.record(w, "STALE_AUTHORITY", "order after removal")
        events = [e for e in w.events if e.get("kind") == "engine_error"]
        self.assertEqual(len(events), 1)
        self.assertFalse(events[0]["public"])

    def test_log_is_bounded(self):
        w = new_world(1, 3)
        for i in range(errors.MAX_RECORDED + 25):
            errors.record(w, "UNKNOWN_ACTION", f"burst {i}")
        log = w.audit_errors
        self.assertEqual(len(log), errors.MAX_RECORDED)
        # The newest entries survive, the oldest are dropped.
        self.assertEqual(log[-1]["message"], f"burst {errors.MAX_RECORDED + 24}")

    def test_since_filters_by_month(self):
        w = new_world(1, 3)
        errors.record(w, "UNKNOWN_ACTION", "in month 0")
        w.month = 2
        errors.record(w, "UNKNOWN_ACTION", "in month 2")
        self.assertEqual(len(errors.since(w, 0)), 1)
        self.assertEqual(len(errors.since(w, 2)), 1)
        self.assertEqual(len(errors.since(w)), 2)


class Wiring(unittest.TestCase):
    def test_a_rejected_motion_reaches_the_ledger(self):
        from karamaniya import politics
        w = new_world(1, 3)
        w.const.offices["army"] = "A"
        result = politics._reject("UNKNOWN_LEVER", "no such lever", lever="warp_drive")
        self.assertEqual(result["reason_code"], "UNKNOWN_LEVER")
        # The council path records exactly this shape; recording it must not raise.
        errors.record(w, result["reason_code"], result["explanation"], **result["related_state"])
        self.assertEqual(errors.summary(w)["by_code"]["UNKNOWN_LEVER"], 1)

    def test_a_long_run_records_only_registered_codes(self):
        """The end-to-end guarantee: the taxonomy covers what the engine actually emits."""
        w = run(new_world(7, 36), 18, each=lambda x: setattr(x.const, "elected", True))
        s = errors.summary(w)
        self.assertEqual(s["unregistered"], 0,
                         f"unregistered codes reached the log: {s['by_code']}")
        for code, count in s["by_code"].items():
            with self.subTest(code=code):
                self.assertTrue(errors.is_registered(code))
                self.assertGreater(count, 0)

    def test_ledger_survives_a_save_and_load_round_trip(self):
        from karamaniya.world import World
        w = new_world(1, 3)
        errors.record(w, "CONDITION_UNRESOLVED", "still false")
        again = World.from_dict(w.to_dict())
        self.assertEqual(len(again.audit_errors), 1)
        self.assertEqual(again.audit_errors[0]["code"], "CONDITION_UNRESOLVED")

    def test_a_pre_taxonomy_checkpoint_still_records(self):
        """Old saves have no ledger field; recording must create it rather than crash."""
        from karamaniya.world import World
        w = new_world(1, 3)
        data = w.to_dict()
        del data["audit_errors"]
        old = World.from_dict(data)
        errors.record(old, "UNKNOWN_ACTION", "on an upgraded world")
        self.assertEqual(errors.summary(old)["total"], 1)


if __name__ == "__main__":
    unittest.main()
