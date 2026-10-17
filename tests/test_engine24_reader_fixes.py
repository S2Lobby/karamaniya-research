"""Engine 24, reader fixes (brief section 9.F): answers the engine refused where the meaning is plain.

Private messages (F2):
- a message that names its recipient under "recipient" (run 20261011-211521-seed1, Month 9, seat C, Qwen3.8 Flash);
- a refused message in an opening is reported once, not twice (the same run; the session reader read it twice).

Cabinet answers (F4):
- an act named under "action" instead of "type" (runs 20261008-130316-seed1 and 20261011-211521-seed1);
- a null troops read as absent, as the reader already reads its other optional fields (runs 20261010-002051-seed1,
  20261010-070501-seed1 and 20261011-094417-seed1: 31 acts with a valid magnitude). A null magnitude is read as 0.5 and
  the cabinet is told so (backlog T142; test_engine24_cabinet_limits.py).

The classes at the end pin what stays refused, and the two "terms" shapes that main already reads. Nothing here calls
a model.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import actions, foreign, foreign_force  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def world(month: int = 0):
    w = new_world(5, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    w.month = month
    return w


def cabinet_answer(**fields):
    """A cabinet's raw answer with every field the reader looks at, and the given fields over it."""
    base = {"public_statement": "", "strategic_assessment": "", "strategy": "", "union_position": None,
            "diplomatic_messages": [], "belief_updates": [], "decision_factors": [], "actions": []}
    return {**base, **fields}


def read(actor, *acts):
    return foreign.normalize_cabinet_output(actor, cabinet_answer(actions=list(acts)))


def answer_month(w, actor, *acts):
    """The month's resolution of one cabinet's answer: read it, then apply it as the engine does."""
    out, _ = read(actor, *acts)
    foreign._apply_cabinet_decisions(w, foreign.positions(w), {actor: out})


def refused_next_month(w, actor="veleria"):
    return foreign_force.cabinet_view(w, actor)["your_acts_refused_last_month"]


def dms(w, mid, *items):
    problems = []
    out = actions._dms(w, mid, list(items), 3, problems)
    return out, problems


class RecipientNamedUnderRecipient(unittest.TestCase):
    """Run 20261011-211521-seed1, Month 9, seat C: three messages named their recipient under "recipient", and each was
    refused as "bad private message recipient 'None'"."""

    def test_a_message_naming_its_recipient_under_recipient_is_kept(self):
        out, problems = dms(world(), "C", {"recipient": "D", "kind": "message", "text": "Your pay promise stands."})
        self.assertEqual(out, [{"from": "C", "to": "D", "text": "Your pay promise stands."}])
        self.assertEqual(problems, [])

    def test_to_wins_when_both_keys_name_a_recipient(self):
        out, _ = dms(world(), "C", {"to": "B", "recipient": "D", "text": "Hold the line."})
        self.assertEqual([m["to"] for m in out], ["B"])

    def test_a_recipient_under_recipient_that_is_the_sender_is_refused_as_self(self):
        out, problems = dms(world(), "C", {"recipient": "C", "text": "A note to myself."})
        self.assertEqual(out, [])
        self.assertEqual(problems, ["private message cannot be sent to self ('C')"])

    def test_a_recipient_under_recipient_that_is_no_member_is_refused(self):
        out, problems = dms(world(), "C", {"recipient": "Z", "text": "Hello."})
        self.assertEqual(out, [])
        self.assertEqual(problems, ["bad private message recipient 'Z'"])

    def test_a_message_with_no_recipient_key_is_refused_as_before(self):
        out, problems = dms(world(), "C", {"text": "Hello."})
        self.assertEqual(out, [])
        self.assertEqual(problems, ["bad private message recipient 'None'"])

    def test_an_unrecognised_key_is_not_read_as_the_recipient(self):
        # Run 20261011-211521-seed1, Month 16 (nemotron): the recipient sat under a key of ", ". That is a guess about a
        # corrupted key, so the message stays refused.
        out, problems = dms(world(), "A", {", ": "C", "text": "Request an update.", "kind": "request"})
        self.assertEqual(out, [])
        self.assertEqual(problems, ["bad private message recipient 'None'"])

    def test_the_kind_given_for_a_message_under_recipient_is_kept(self):
        problems = []
        out = actions._v2_dms(world(), "C", [{"recipient": "D", "kind": "bargain", "text": "Your pay promise stands."}],
                              3, problems)
        self.assertEqual([m["kind"] for m in out], ["bargain"])
        self.assertEqual(problems, [])


class SessionReportsEachRefusalOnce(unittest.TestCase):
    """The opening's reader used to read each message twice, and report each refusal twice (run 20261011-211521-seed1
    Month 9 and Month 16; census: 12 recipient entries for 6 messages)."""

    def test_a_refused_message_in_an_opening_is_reported_once(self):
        out, problems = actions.normalize_session_v2(world(), "A", {"private_messages": [
            {"to": "E", "text": "", "kind": "message"}]}, 3)
        self.assertEqual(out["private_messages"], [])
        self.assertEqual([p for p in problems if "private message" in p], ["private message to E has an empty body"])

    def test_a_self_addressed_message_in_an_opening_is_reported_once(self):
        out, problems = actions.normalize_session_v2(world(), "A", {"private_messages": [
            {"to": "A", "text": "A note to myself.", "kind": "message"}]}, 3)
        self.assertEqual([p for p in problems if "private message" in p],
                         ["private message cannot be sent to self ('A')"])

    def test_a_message_under_recipient_in_an_opening_is_kept_and_reported_once(self):
        out, problems = actions.normalize_session_v2(world(), "C", {"private_messages": [
            {"recipient": "D", "kind": "message", "text": "Your pay promise stands."}]}, 3)
        self.assertEqual([(m["to"], m["text"]) for m in out["private_messages"]], [("D", "Your pay promise stands.")])
        self.assertEqual([p for p in problems if "private message" in p], [])

    def test_a_legacy_session_reports_a_refused_message_once(self):
        _, problems = actions.normalize_session(world(), "A", {"private_messages": [{"to": "E", "text": ""}]}, 3)
        self.assertEqual([p for p in problems if "private message" in p], ["private message to E has an empty body"])

    def test_a_private_messages_field_that_is_not_a_list_is_reported_once(self):
        _, problems = actions.normalize_session_v2(world(), "A", {"private_messages": "none"}, 3)
        self.assertEqual([p for p in problems if "not a list" in p], ["private_messages is not a list"])


class ActNamedUnderActionKey(unittest.TestCase):
    """Runs 20261008-130316-seed1 (Dorsania, Months 4 and 5) and 20261011-211521-seed1 (Dorsania Month 2, Veleria Month
    7): twelve acts that were valid types were written under "action", and each was refused as "unsupported cabinet
    action"."""

    def test_an_act_named_under_action_is_read_as_its_type(self):
        out, problems = read("dorsania", {"action": "intelligence_collection", "magnitude": .6})
        self.assertEqual(out["actions"], [{"type": "intelligence_collection", "magnitude": .6}])
        self.assertIn("type 'intelligence_collection' was read from the key 'action'", problems)

    def test_the_reading_is_not_sent_to_the_cabinet_and_the_act_is_carried_out(self):
        w = world(month=2)
        answer_month(w, "dorsania", {"action": "intelligence_collection", "magnitude": .6})
        w.month += 1
        self.assertEqual(refused_next_month(w, "dorsania"), [])
        self.assertIn("intelligence_collection", [a["type"] for a in w.foreign["actors"]["dorsania"]["diplomacy"]
                                                  ["last_actions"]])

    def test_the_type_wins_when_both_keys_are_given(self):
        out, problems = read("dorsania", {"type": "offer_talks", "action": "intelligence_collection", "magnitude": .4})
        self.assertEqual(out["actions"], [{"type": "offer_talks", "magnitude": .4}])
        self.assertEqual(problems, [])

    def test_an_unknown_act_under_action_is_still_refused(self):
        out, problems = read("dorsania", {"action": "launch_missiles", "magnitude": .4})
        self.assertEqual(out["actions"], [])
        self.assertEqual(problems, ["unsupported cabinet action"])

    def test_another_cabinets_act_under_action_is_still_refused(self):
        # grain_embargo is Dorsania's own act; Veleria's reader reads only Veleria's catalog.
        out, problems = read("veleria", {"action": "grain_embargo", "magnitude": .4})
        self.assertEqual(out["actions"], [])
        self.assertEqual(problems, ["unsupported cabinet action"])


class NullTroopsAreAbsentNullMagnitudeIsHalf(unittest.TestCase):
    """Runs 20261010-002051-seed1, 20261010-070501-seed1 and 20261011-094417-seed1: acts with a null troops and a valid
    magnitude were refused, and none of them takes troops. A null magnitude is read as the default 0.5, and the cabinet is
    told so the next month (backlog T142; test_engine24_cabinet_limits.py)."""

    def test_a_null_troops_is_read_as_absent_for_an_act_that_takes_none(self):
        out, problems = read("veleria", {"type": "intelligence_collection", "magnitude": .4, "troops": None,
                                         "front": None, "aim": None, "region": None, "terms": None,
                                         "deadline_months": None})
        self.assertEqual(out["actions"], [{"type": "intelligence_collection", "magnitude": .4}])
        self.assertEqual(problems, [])

    def test_a_null_magnitude_is_read_as_one_half(self):
        out, problems = read("dorsania", {"type": "offer_talks", "magnitude": None})
        self.assertEqual(out["actions"], [{"type": "offer_talks", "magnitude": .5}])
        self.assertNotIn("action magnitude must be between 0 and 1", problems)

    def test_a_null_troops_on_a_force_act_is_left_to_the_world_to_refuse_with_its_reason(self):
        w = world(month=2)
        answer_month(w, "veleria", {"type": "deploy_to_border", "front": "north", "magnitude": .5, "troops": None})
        w.month += 1
        shown = refused_next_month(w)
        self.assertEqual(len(shown), 1, shown)
        self.assertTrue(shown[0]["reason"].startswith("name how many soldiers"), shown)

    def test_a_magnitude_outside_the_range_is_still_refused(self):
        out, problems = read("dorsania", {"type": "border_incident", "front": "east", "magnitude": 1.5})
        self.assertEqual(out["actions"], [])
        self.assertIn("action magnitude must be between 0 and 1", problems)

    def test_a_troops_that_is_not_a_number_is_still_refused(self):
        out, problems = read("dorsania", {"type": "deploy_to_border", "front": "east", "troops": "many",
                                          "magnitude": .5})
        self.assertEqual(out["actions"], [])
        self.assertIn("troops must be a nonnegative integer", problems)


class PinsWhatStaysRefusedOrAlreadyRead(unittest.TestCase):
    """Refusals kept on purpose (a sentence as a belief name, the fifth act), what engine 26 now reads (the cabinet's
    strategy object), and the two ultimatum shapes that run 20261011-105713-seed1 refused and main already reads."""

    def test_a_strategy_given_as_an_object_is_read(self):
        # Engine 26 (backlog T160): five recorded answers wrote the strategy as an object; its text is read.
        out, problems = foreign.normalize_cabinet_output("dorsania", cabinet_answer(
            strategy={"name": "Leverage before force", "horizon_months": 6}))
        self.assertEqual(out["strategy"], "Leverage before force")
        self.assertNotIn("strategy must be text", problems)

    def test_a_belief_named_by_a_sentence_is_still_refused(self):
        out, problems = foreign.normalize_cabinet_output("dorsania", cabinet_answer(belief_updates=[
            {"belief": "Karamaniya should see to its stability", "value": .75, "confidence": .6}]))
        self.assertEqual(out["belief_updates"], [])
        self.assertIn("invalid belief update", problems)

    def test_a_known_belief_name_is_read_as_before(self):
        out, problems = foreign.normalize_cabinet_output("dorsania", cabinet_answer(belief_updates=[
            {"belief": "karamaniya_offensive_intent", "value": .3, "confidence": .4}]))
        self.assertEqual(out["belief_updates"], [{"belief": "karamaniya_offensive_intent", "value": .3,
                                                  "confidence": .4}])
        self.assertEqual(problems, [])

    def test_the_fifth_act_is_not_read_and_the_cabinet_is_told_the_next_month(self):
        w = world(month=2)
        answer_month(w, "veleria", *([{"type": "offer_talks", "magnitude": .3}] * 4
                                     + [{"type": "propaganda", "magnitude": .3}]))
        w.month += 1
        shown = refused_next_month(w)
        self.assertEqual([s["action"] for s in shown], ["propaganda"], shown)
        self.assertIn("only the first 4", shown[0]["reason"])

    def test_a_list_of_terms_with_a_valid_first_term_issues_one_demand(self):
        out, problems = read("veleria", {"type": "ultimatum", "terms": ["status_talks", "protect_imperial_citizens"],
                                         "deadline_months": 2})
        self.assertEqual(out["actions"], [{"type": "ultimatum", "magnitude": .5, "terms": "status_talks",
                                           "deadline_months": 2}])

    def test_a_single_term_is_read_as_before(self):
        out, problems = read("veleria", {"type": "ultimatum", "terms": "status_talks", "deadline_months": 2})
        self.assertEqual(out["actions"][0]["terms"], "status_talks")
        self.assertEqual(problems, [])

    def test_a_communication_kind_demand_is_not_read_as_demand_resignation(self):
        # Run 20261011-105713-seed1, Months 8 and 9: Dorsania-directed demands for a pact and a withdrawal. No communication
        # kind means "demand", so the item stays refused.
        problems = []
        out = actions._comms([{"kind": "demand", "target": "dorsania", "about": "Withdraw your forces."}], problems)
        self.assertEqual(out, [])
        self.assertEqual(problems, ["unknown communication kind 'demand'"])


if __name__ == "__main__":
    unittest.main()
