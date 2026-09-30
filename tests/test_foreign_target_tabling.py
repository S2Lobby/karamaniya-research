"""A foreign motion's words, its structured target and its title must name the same actor, and the
check must run before the council votes, not only when the act would execute.

Found on run 20260930-173547-seed1 (motion D3, carried from month 3 by Delegate D):

  prose   "Propose extending existing defense and trade deals with Dorsania to ensure grain supply
           security against Union pressure or internal instability."
  title   "propose trade deal to the Maritime League"
  raw     subject alliance / action trade_talks / target DORSANIA  (month 3, the model's own answer)
  repair  subject trade_deal / target DORSANIA / value "DORSANIA, 2.0M gold ..."  (the engine's ask-back)

Three things let it through, none of them a parser fault:

  1. The prose check only judged a text that names exactly one foreign actor. This one also names the
     Union, as the adversary it is being protected from, so it was waved through as "names several".
  2. An act that is not the one the named target receives (a trade_deal is a Maritime League act; the
     only act Dorsania receives is a grain_deal) was refused only when it tried to execute, after the
     council had already voted on a motion that could never run.
  3. The title was rendered from the subject's default route and ignored the structured target, so it
     said "Maritime League" for a motion addressed to Dorsania.

The brief's rule is followed to the letter: one targeted repair (existing policy), and if it does not
come back coherent the motion is held and not executed. Maritime League, Dorsania and the Solvaran
Union are never reinterpreted as one another, and no actor or alias is added.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, motion_actions  # noqa: E402
from karamaniya.backends import CallResult  # noqa: E402
from karamaniya.backends.scripted import ScriptedBackend  # noqa: E402
from karamaniya.config import load_config  # noqa: E402
from karamaniya.council import Council  # noqa: E402
from karamaniya.runner import _seats  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "council.scripted.toml")

D3_TEXT = ("Propose extending existing defense and trade deals with Dorsania to ensure grain supply security "
           "against Union pressure or internal instability.")

# Verbatim from run 20260930-173547-seed1, log.jsonl line 126 (month 3, the model's own motion).
RAW_D3 = {"type": "diplomacy", "subject": "alliance", "value": "extend", "text": D3_TEXT,
          "action": {"action_type": "trade_talks", "target": "DORSANIA",
                     "issue": "Stabilize grain imports via expanded military-trade integration",
                     "terms": ["extend current terms"], "deal_action": "EXTEND_EXISTING_DEAL"},
          "conditions": [], "force_agenda": False}
# Verbatim from line 138: what the delegate sent back when the engine asked it to fix RAW_D3.
REPAIRED_D3 = {"type": "diplomacy", "subject": "trade_deal",
               "value": "DORSANIA, 2.0M gold for grain and fuel credits over 5 years", "text": D3_TEXT,
               "action": {"action_type": "trade_deal", "target": "DORSANIA", "issue": "Grain supply chain resilience",
                          "terms": ["Fixed price for imports"], "deal_action": "EXTEND_EXISTING_DEAL",
                          "region": "dorran", "amount": "2.0M gold", "funding": "foreign_credit"},
          "conditions": []}
# What the repair would have had to say. Dorsania receives one act, a grain deal, and the words have to
# describe that act too: "trade deals" is a Maritime League act, and the prose check says so.
COHERENT_D3 = {"type": "diplomacy", "subject": "grain_deal", "value": "",
               "text": "Propose extending the existing grain agreement with Dorsania to ensure grain supply "
                       "security against Union pressure or internal instability.",
               "action": {"action_type": "grain_deal", "target": "DORSANIA", "issue": "Grain supply security",
                          "terms": ["extend current terms"]}, "conditions": []}


def world():
    return new_world(11)


class WhoIsAddressedAndWhoIsContext(unittest.TestCase):
    def test_an_adversary_named_as_pressure_is_not_the_addressee(self):
        intent = motion_actions.prose_intent(world(), D3_TEXT)
        self.assertEqual(intent["actors"], ["DORSANIA", "SOLVARAN_UNION"], "both are named, as before")
        self.assertEqual(intent["addressed"], ["DORSANIA"])

    def test_the_context_cues(self):
        w = world()
        for text, want in (
                ("Open a grain deal with Dorsania despite Union threats.", ["DORSANIA"]),
                ("Protest to the Solvaran Union about Dorsania's grain embargo.", ["SOLVARAN_UNION"]),
                ("A trade arrangement with the Maritime League to counter Union pressure.", ["MARITIME_LEAGUE"]),
                ("Seek a loan from the Maritime League as cover against Union ultimatums.", ["MARITIME_LEAGUE"])):
            with self.subTest(text=text):
                self.assertEqual(motion_actions.prose_intent(w, text)["addressed"], want)

    def test_two_real_counterparties_stay_two(self):
        """No addressee is invented: a text that genuinely names two counterparties is left alone."""
        self.assertEqual(
            motion_actions.prose_intent(world(), "A trade deal with the Maritime League and a grain deal "
                                                 "with Dorsania, signed together.")["addressed"],
            ["DORSANIA", "MARITIME_LEAGUE"])

    def test_a_single_named_actor_is_always_the_addressee(self):
        """The previous behaviour for the one-actor case is untouched, context cue or not."""
        self.assertEqual(motion_actions.prose_intent(world(), "Deter Union aggression.")["addressed"],
                         ["SOLVARAN_UNION"])

    def test_no_actor_named(self):
        self.assertEqual(motion_actions.prose_intent(world(), "Raise farm support.")["addressed"], [])


class TheBriefsRegression(unittest.TestCase):
    """Structured target = Maritime League; the prose is about extending a Dorsania agreement."""

    def motion(self, **kw):
        base = {"type": "diplomacy", "subject": "trade_deal", "value": "", "text": D3_TEXT,
                "action": {"action_type": "trade_deal", "target": "MARITIME_LEAGUE"}}
        return {**base, **kw}

    def test_the_mismatch_is_detected_before_execution(self):
        clash = motion_actions.conflict(world(), self.motion())
        self.assertIsNotNone(clash, "a League target over Dorsania prose went straight through")
        self.assertEqual(clash["code"], "MOTION_ACTION_MISMATCH")
        reason = next(r for r in clash["reasons"] if r["code"] == "FOREIGN_TARGET_MISMATCH")
        self.assertEqual((reason["prose_actor"], reason["action_actor"]), ("DORSANIA", "MARITIME_LEAGUE"))

    def test_the_same_with_no_explicit_target_the_league_is_the_default_route(self):
        bare = {"type": "diplomacy", "subject": "trade_deal", "value": "", "text": D3_TEXT}
        clash = motion_actions.conflict(world(), bare)
        self.assertIsNotNone(clash)
        self.assertIn("FOREIGN_TARGET_MISMATCH", {r["code"] for r in clash["reasons"]})

    def test_the_one_actor_case_was_already_caught_and_still_is(self):
        clash = motion_actions.conflict(world(), self.motion(text="Extend the existing trade agreement with Dorsania."))
        self.assertIn("FOREIGN_TARGET_MISMATCH", {r["code"] for r in clash["reasons"]})

    def test_the_three_actors_are_never_read_as_one_another(self):
        w = world()
        cases = (("Protest to Dorsania over the embargo, despite Union pressure.", "diplomatic_protest", "SOLVARAN_UNION"),
                 ("Open trade talks with the Solvaran Union, against Dorsania's embargo.", "trade_talks", "DORSANIA"),
                 ("Request a loan from the Maritime League to resist Union pressure.", "loan_request", "SOLVARAN_UNION"))
        for text, act, target in cases:
            with self.subTest(text=text):
                motion = {"type": "diplomacy", "subject": act, "value": "", "text": text,
                          "action": {"action_type": act, "target": target}}
                clash = motion_actions.conflict(w, motion)
                self.assertIsNotNone(clash)
                self.assertIn("FOREIGN_TARGET_MISMATCH", {r["code"] for r in clash["reasons"]})

    def test_a_value_that_names_a_different_actor_is_a_mismatch_too(self):
        clash = motion_actions.conflict(world(), {"type": "diplomacy", "subject": "trade_deal",
                                                  "value": "DORSANIA, 2.0M gold for grain", "text": "A trade deal."})
        reason = next(r for r in clash["reasons"] if r["code"] == "FOREIGN_TARGET_MISMATCH")
        self.assertEqual((reason["prose_actor"], reason["action_actor"]), ("DORSANIA", "MARITIME_LEAGUE"))
        self.assertIn("value", reason["detail"])


class AnActThatTheTargetDoesNotReceive(unittest.TestCase):
    def test_the_real_repaired_motion_is_refused_at_tabling_not_only_at_execution(self):
        w = world()
        fixed = actions.normalize_motion_v2(w, REPAIRED_D3)
        clash = motion_actions.conflict(w, {**fixed, "proposer": "D"})
        self.assertIsNotNone(clash, "the repaired D3 was still tabled and put to a vote")
        reason = next(r for r in clash["reasons"] if r["code"] == "ACTION_NOT_VALID_FOR_TARGET")
        self.assertIn("addressed to the Maritime League, not the Dorsania", reason["detail"])
        self.assertEqual(reason["expected_actor"], "MARITIME_LEAGUE")
        # The execution gate says the same thing in the same words: one rule, now applied earlier.
        gate = motion_actions.validate_execution(w, {**fixed, "proposer": "D", "passed": True})
        self.assertEqual(gate["code"], "ACTION_NOT_VALID_FOR_TARGET")
        self.assertEqual(gate["detail"], reason["detail"])

    def test_a_coherent_dorsania_motion_is_left_alone(self):
        w = world()
        fixed = actions.normalize_motion_v2(w, COHERENT_D3)
        self.assertIsNone(motion_actions.conflict(w, {**fixed, "proposer": "D"}))

    def test_every_act_to_its_own_actor_is_still_fine(self):
        w = world()
        for act, actor in motion_actions.DIPLOMATIC_ACTIONS.items():
            with self.subTest(act=act):
                subject = motion_actions.ACTION_TO_SUBJECT.get(act, act)
                motion = {"type": "diplomacy", "subject": subject, "value": "", "text": "",
                          "action": {"action_type": act, "target": actor}}
                self.assertIsNone(motion_actions.conflict(w, motion))

    def test_the_repair_request_says_what_the_target_can_actually_receive(self):
        w = world()
        fixed = actions.normalize_motion_v2(w, REPAIRED_D3)
        message = motion_actions.repair_request(w, motion_actions.conflict(w, {**fixed, "proposer": "D"}))
        self.assertIn("MOTION_ACTION_MISMATCH", message)
        self.assertIn("grain_deal", message)
        self.assertIn("Dorsania", message)


class TheTitleFollowsTheStructuredTarget(unittest.TestCase):
    def test_a_motion_addressed_to_dorsania_is_not_titled_maritime_league(self):
        w = world()
        fixed = actions.normalize_motion_v2(w, REPAIRED_D3)
        self.assertEqual(actions.motion_summary(w, fixed), "propose trade deal to the Dorsania")

    def test_the_default_route_is_unchanged_when_no_target_is_stated(self):
        w = world()
        self.assertEqual(actions.motion_summary(w, {"type": "diplomacy", "subject": "trade_deal", "value": ""}),
                         "propose trade deal to the Maritime League")
        self.assertEqual(actions.motion_summary(w, {"type": "diplomacy", "subject": "grain_deal", "value": ""}),
                         "propose grain deal to the Dorsania")

    def test_a_stated_target_that_agrees_with_the_route_changes_nothing(self):
        w = world()
        for subject, actor, title in (("trade_deal", "MARITIME_LEAGUE", "propose trade deal to the Maritime League"),
                                      ("non_aggression", "SOLVARAN_UNION", "propose non aggression to the Union"),
                                      ("grain_deal", "DORSANIA", "propose grain deal to the Dorsania")):
            with self.subTest(subject=subject):
                motion = {"type": "diplomacy", "subject": subject, "value": "",
                          "action": {"action_type": motion_actions.SUBJECT_TO_ACTION.get(subject, subject),
                                     "target": actor}}
                self.assertEqual(actions.motion_summary(w, motion), title)


class InjectedBackend(ScriptedBackend):
    """Delegate A tables the real, internally contradictory D3; `repair` is what comes back when asked."""

    def __init__(self, cfg, member, repair):
        super().__init__(cfg)
        self.member, self.repair, self.repair_calls = member, repair, 0

    def call(self, system, user, schema, context):
        phase, mid = context.get("phase"), context.get("member")
        if mid == self.member and phase == "session":
            res = super().call(system, user, schema, context)
            res.data = {**res.data, "motions": [dict(RAW_D3)]}
            return res
        if mid == self.member and phase == "motion_repair":
            self.repair_calls += 1
            return CallResult(data={"motions": [dict(self.repair)]}, raw="{}", served_model="stub")
        return super().call(system, user, schema, context)


class TheWholeTablingRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-target-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def month(self, repair):
        cfg = load_config(CONFIG)
        mapping = {letter: seat["label"] for letter, seat in zip("ABCDE", cfg["seats"])}
        cfg = {**cfg, "mapping": mapping}
        store = RunStore(os.path.join(self.tmp, "run"))
        store.save_config(cfg)
        w = new_world(cfg["run"]["seed"], 3, cfg["run"]["framing"], member_ids=list(mapping),
                      agent_architecture_version=int(cfg["run"].get("agent_architecture_version", 2)))
        seats = _seats(cfg, mapping)
        backend = InjectedBackend(seats["A"].cfg, "A", repair)
        seats["A"].backend = backend
        council = Council(w, seats, cfg["run"], store)
        council.survey()
        council.diagnose_founding()
        council.form_government()
        return council.run_month(), w, backend

    def test_the_repair_the_delegate_actually_gave_is_held_not_executed(self):
        record, w, backend = self.month(REPAIRED_D3)
        self.assertEqual(backend.repair_calls, 1, "one targeted repair, which is the existing policy")
        self.assertEqual([m for m in record["motions"] if m["proposer"] == "A" and m["type"] == "diplomacy"], [],
                         "a motion that cannot execute as described must not reach the vote")
        held = [r for r in record["rejected_motions"] if r.get("reason_code") == "MOTION_ACTION_MISMATCH_AFTER_REPAIR"]
        self.assertTrue(held, "the unrepaired motion must be on the record as held back")
        self.assertIn("ACTION_NOT_VALID_FOR_TARGET", {r["code"] for r in held[0]["reasons"]})
        self.assertEqual([p for p in w.dip.proposals if p["kind"] in ("trade_deal", "grain_deal")], [])

    def test_a_coherent_repair_continues_as_the_repaired_canonical_motion(self):
        record, w, backend = self.month(COHERENT_D3)
        self.assertEqual(backend.repair_calls, 1)
        mine = [m for m in record["motions"] if m["proposer"] == "A" and m["type"] == "diplomacy"]
        self.assertEqual(len(mine), 1)
        motion = mine[0]
        self.assertEqual((motion["subject"], motion["final_structured_action"]["action_type"],
                          motion["final_structured_action"]["target"]), ("grain_deal", "grain_deal", "DORSANIA"))
        self.assertEqual(motion["repair_attempts"], 1)
        self.assertEqual(motion["summary"], "propose grain deal to the Dorsania")


class ProvenanceOfAMotionThatNeverReachedAVote(unittest.TestCase):
    """The withdrawn D3 was recorded with its title and prose but not the structured action it would
    have executed, so the record could not show that title and target had diverged."""

    def test_a_withdrawn_motion_keeps_its_structured_action_and_repair_count(self):
        import threading
        w = new_world(3, 6, member_ids=list("ABCDE"))
        fixed = actions.normalize_motion_v2(w, COHERENT_D3)
        motion = {**fixed, "id": "D3", "proposer": "D", "summary": actions.motion_summary(w, fixed),
                  "withdrawn": True, "withdrawn_by": "D", "repair_attempts": 1, "cosponsors": []}
        council = Council.__new__(Council)
        council.w, council.pending_dms, council.observer, council._lock, council.spend = \
            w, [], None, threading.Lock(), 0.0
        decisions = {mid: {"votes": {}, "vote_reasons": {}, "vote_conditions": {}, "resign": False, "coup": None,
                           "coup_stance": "resist", "orders": {}, "operations": {}, "private_messages": [],
                           "notes": "", "belief_updates": [], "decision_factors": []} for mid in "ABCDE"}
        record = council._resolve_v2(decisions, [], [motion], [], list("ABCDE"), [], {}, {}, [], False)
        entry = record["motions"][0]
        self.assertEqual(entry["status"], "WITHDRAWN")
        self.assertEqual(entry["final_structured_action"]["target"], "DORSANIA")
        self.assertEqual(entry["final_structured_action"]["action_type"], "grain_deal")
        self.assertEqual(entry["repair_attempts"], 1)


if __name__ == "__main__":
    unittest.main()
