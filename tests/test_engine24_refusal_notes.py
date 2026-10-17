"""Engine 24, refusal notes (backlog T138 and T140).

T138: a delegate whose private message or public communication the engine refused was never told. The refusal was
recorded in the month's problems as a string, and the next month's note (council._rejected_last_month) named only
its refused motions. Run 20261011-211521-seed1 refused messages with no recipient (the census: "bad private message
recipient 'None'"), messages sent to the sender, messages with an empty body, and communications of an unknown kind
("demand", ""). Those are the refusals the sender now sees, with the reason, the next month. Engine 27 made "demand"
a known communication kind, so these tests use the still-unknown "summons" as their example.

T140: the note cut each refusal's explanation at 300 characters. In run 20261008-130316-seed1 (Month 6, Delegate C)
and in run tinytest-mild-sim-r0-s1001 (Month 2, Delegate A) the list of the levers the council can direct was cut
inside the list (for example "... navy_mission, offic"). The note now carries each explanation whole, and every
refusal of a delegate. Months are numbered as the census numbers them: the record's month plus one.
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import actions  # noqa: E402
from karamaniya.backends.scripted import ScriptedBackend  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.council import Council, _rejected_last_month  # noqa: E402
from karamaniya.runner import _seats  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

SCRIPTED = os.path.join(ROOT, "council.scripted.toml")


def world():
    return new_world(1, 12, member_ids=list("ABCDE"))


def refusing_council(test, answers: dict, months: int = 4):
    """A scripted run in which Delegate A's answers in Month 2 (world month 1) carry the given fields.

    `answers` maps a phase ("session", "revision" or "decision") to the fields written over the scripted answer.
    """
    class Refusing(ScriptedBackend):
        def call(self, system, user, schema, context):
            res = super().call(system, user, schema, context)
            w, mid, phase = context.get("world"), context.get("member"), context.get("phase")
            if w is not None and w.month == 1 and mid == "A" and phase in answers and isinstance(res.data, dict):
                res.data.update(answers[phase])
            return res

    tmp = tempfile.mkdtemp(prefix="engine24-refusal-")
    test.addCleanup(shutil.rmtree, tmp, True)
    cfg = load_config(SCRIPTED)
    run = {"tokens": {}, "foreign_cabinets": False, "months": months, "seed": 1}
    cfg = {**cfg, "run": {**cfg["run"], **run}}
    cfg = normalize_config({"run": cfg["run"], "seat": cfg["seats"]})
    mapping = {letter: seat["label"] for letter, seat in zip("ABCDE", cfg["seats"])}
    cfg["mapping"] = mapping
    w = new_world(cfg["run"]["seed"], months, member_ids=list(mapping),
                  founding_scenario=cfg["run"].get("founding_scenario", "random"),
                  founding_severity=cfg["run"].get("founding_severity", "default"))
    seats = _seats(cfg, mapping)
    for seat in seats.values():
        seat.backend = Refusing(seat.cfg)
    council = Council(w, seats, cfg["run"], RunStore(os.path.join(tmp, "r")))
    council.store.save_config(cfg)
    (council.store.path / "system_prompt.txt").write_text(council.system, encoding="utf-8")
    council.survey()
    council.diagnose_founding()
    council.form_government()
    return council


# The refusals A's Month-2 answers carry: a message to itself, a message with no recipient, a message with an empty
# body, and a communication of the unknown kind "summons" (the census names both kinds of refusal).
SESSION_REFUSALS = {"private_messages": [{"to": "A", "text": "A note to myself.", "kind": "message"},
                                         {"text": "A message with no recipient.", "kind": "message"},
                                         {"to": "C", "text": "   ", "kind": "message"}],
                    "communications": [{"kind": "summons", "target": "public", "about": "the ceiling"}]}


class RefusedMessagesAreTold(unittest.TestCase):
    """T138: the refused private messages and communications are in the sender's next-month note, with the reason."""

    def test_a_refused_private_message_is_listed_in_the_senders_next_month_note(self):
        council = refusing_council(self, {"session": SESSION_REFUSALS})
        council.run_month()
        council.run_month()
        sections = _rejected_last_month(council.last_record, "A")
        self.assertEqual([s.key for s in sections], ["rejected_last_month"])
        text = sections[0].text
        self.assertIn("private message to A: a private message cannot be sent to yourself", text)
        self.assertIn("private message to None: bad private message recipient 'None'", text)
        self.assertIn("private message to C: a private message needs non-empty text", text)

    def test_a_refused_communication_is_listed_in_the_senders_next_month_note(self):
        council = refusing_council(self, {"session": SESSION_REFUSALS})
        council.run_month()
        council.run_month()
        text = _rejected_last_month(council.last_record, "A")[0].text
        self.assertIn("communication to public: unknown communication kind 'summons'", text)

    def test_a_message_refused_in_the_decision_round_is_listed_the_next_month(self):
        council = refusing_council(self, {"decision": {"private_messages": [{"to": "A", "text": "Myself again.",
                                                                              "kind": "message"}]}})
        council.run_month()
        council.run_month()
        text = _rejected_last_month(council.last_record, "A")[0].text
        self.assertIn("private message to A: a private message cannot be sent to yourself", text)

    def test_a_refusal_is_listed_for_its_sender_only(self):
        council = refusing_council(self, {"session": SESSION_REFUSALS})
        council.run_month()
        council.run_month()
        texts = [s.text for s in _rejected_last_month(council.last_record, "B")]
        self.assertFalse(any("cannot be sent to yourself" in t or "unknown communication kind 'summons'" in t
                             for t in texts))

    def test_the_motion_lines_keep_their_header_when_messages_are_listed_too(self):
        section = _rejected_last_month({"rejected_motions": [
            {"member": "A", "motion": {"type": "set_policy", "subject": "tax", "value": "0.5"},
             "reason_code": "UNKNOWN_LEVER", "explanation": "unknown policy lever 'tax'"}],
            "rejected_messages": [{"member": "A", "phase": "session", "channel": "communication", "to": "public",
                                   "kind": "summons", "reason": "unknown communication kind 'summons'"}]}, "A")
        text = section[0].text
        self.assertTrue(text.startswith("YOUR MOTIONS NOT TABLED LAST MONTH (the reason each was refused):\n"))
        self.assertIn("- set_policy tax 0.5: UNKNOWN_LEVER - unknown policy lever 'tax'", text)
        self.assertIn("YOUR PRIVATE MESSAGES AND COMMUNICATIONS NOT SENT LAST MONTH", text)
        self.assertIn("- communication to public: unknown communication kind 'summons'", text)


class ReaderKeepsEachRefusal(unittest.TestCase):
    """T138 at the reader: each refused message and communication is kept with its reason, and the problems that were
    recorded before are recorded as before."""

    def test_the_session_reader_keeps_each_refused_message_with_its_reason(self):
        out, problems = actions.normalize_session_v2(world(), "A", {"private_messages": [
            {"to": "A", "text": "to myself", "kind": "message"},
            {"text": "no recipient", "kind": "message"},
            {"to": "B", "text": "   ", "kind": "message"},
            {"to": "C", "text": "fine", "kind": "message"}]}, 3)
        self.assertEqual([m["to"] for m in out["private_messages"]], ["C"])
        refused = out["refused_messages"]
        self.assertEqual([r["to"] for r in refused], ["A", "None", "B"])
        self.assertEqual(refused[0]["reason"],
                         "a private message cannot be sent to yourself; the recipient must be one of B, C, D, E")
        self.assertEqual(refused[1]["reason"],
                         "bad private message recipient 'None'; the recipient must be one of B, C, D, E")
        self.assertEqual(refused[2]["reason"], "a private message needs non-empty text")
        self.assertEqual(problems, ["private message cannot be sent to self ('A')",
                                    "bad private message recipient 'None'",
                                    "private message to B has an empty body"])

    def test_the_session_reader_keeps_a_communication_of_an_unknown_kind(self):
        out, problems = actions.normalize_session_v2(world(), "A", {"communications": [
            {"kind": "summons", "target": "public", "about": "x"},
            {"kind": "endorse", "target": "dorsania", "about": "y"}]}, 3)
        self.assertEqual([c["kind"] for c in out["communications"]], ["endorse"])
        self.assertEqual([(r["channel"], r["to"], r["reason"]) for r in out["refused_messages"]],
                         [("communication", "public", "unknown communication kind 'summons'")])
        self.assertIn("unknown communication kind 'summons'", problems)

    def test_a_third_communication_is_refused_with_the_limit_as_its_reason(self):
        item = {"kind": "endorse", "target": "public", "about": "x"}
        out, _ = actions.normalize_session_v2(world(), "A", {"communications": [item, item, item]}, 3)
        self.assertEqual(len(out["communications"]), 2)
        self.assertEqual([r["reason"] for r in out["refused_messages"]],
                         ["only two public communications are read a month; this one came after them"])

    def test_the_second_communication_of_a_response_round_is_refused_with_the_limit_as_its_reason(self):
        item = {"kind": "endorse", "target": "public", "about": "x"}
        out, _ = actions.normalize_revision(world(), "A", {"communications": [item, item]}, [], 3)
        self.assertEqual(len(out["communications"]), 1)
        self.assertEqual([r["reason"] for r in out["refused_messages"]],
                         ["only one public communication is read in the response round; this one came after it"])

    def test_a_third_communication_of_a_response_round_gives_the_response_round_reason(self):
        # The reader's cap of two is applied first; the response round's limit of one must still be the reason given.
        item = {"kind": "endorse", "target": "public", "about": "x"}
        out, _ = actions.normalize_revision(world(), "A", {"communications": [item, item, item]}, [], 3)
        self.assertEqual(len(out["communications"]), 1)
        self.assertEqual([r["reason"] for r in out["refused_messages"]],
                         ["only one public communication is read in the response round; this one came after it"] * 2)

    def test_messages_past_the_quota_are_each_refused_and_one_problem_is_recorded(self):
        messages = [{"to": "B", "text": f"message {i}", "kind": "message"} for i in range(4)]
        out, problems = actions.normalize_session_v2(world(), "A", {"private_messages": messages}, 3)
        self.assertEqual(len(out["private_messages"]), 3)
        self.assertEqual([r["reason"] for r in out["refused_messages"]],
                         ["too many private messages: 3 was the most left to send this month"])
        self.assertEqual(problems.count("too many private messages"), 1)


class RefusalExplanationsAreWhole(unittest.TestCase):
    """T140: a refusal's explanation reaches the note whole, and no refusal of a delegate is left out of it."""

    LONG = ("unknown policy lever 'highlands_status'; settings the council can direct: " + ", ".join(
        f"lever_{n:02d}" for n in range(60)) + ". END-OF-EXPLANATION")

    def test_a_long_refusal_explanation_reaches_the_note_whole(self):
        self.assertGreater(len(self.LONG), 300)
        text = _rejected_last_month({"rejected_motions": [
            {"member": "A", "motion": {"type": "set_policy", "subject": "highlands_status", "value": "cultural"},
             "reason_code": "UNKNOWN_LEVER", "explanation": self.LONG}]}, "A")[0].text
        self.assertIn(self.LONG, text)
        self.assertNotIn("[cut]", text)

    def test_an_unknown_lever_lists_every_setting_in_the_note(self):
        # The engine's own explanation for a lever with no close match lists the settings the council can direct, about
        # 580 characters. The cut at 300 ended the note inside that list ("... navy_mission, o") in run 20261008-130316-seed1
        # (Month 6) and in tinytest-mild-sim-r0-s1001 (Month 2).
        from karamaniya import politics
        w = new_world(1, 12, member_ids=list("ABCDE"))
        motion = {"type": "set_policy", "subject": "zq_nonexistent_lever", "value": "high", "text": "Raise it."}
        detail = politics.validate_motion_detail(w, dict(motion))
        self.assertGreater(len(detail["explanation"]), 300)
        text = _rejected_last_month({"rejected_motions": [{"member": "A", "motion": motion, **detail}]}, "A")[0].text
        self.assertIn(", ".join(sorted(politics.LEVER_OFFICE)), text)

    def test_every_refusal_of_a_delegate_is_listed(self):
        refusals = [{"member": "A", "motion": {"type": "program", "subject": f"s{i}", "value": ""},
                     "reason_code": "EMPTY_MOTION_TEXT", "explanation": f"refusal number {i}"} for i in range(6)]
        text = _rejected_last_month({"rejected_motions": refusals}, "A")[0].text
        for i in range(6):
            self.assertIn(f"refusal number {i}", text)


if __name__ == "__main__":
    unittest.main()
