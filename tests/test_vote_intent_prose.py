"""A final ballot must match what the delegate clearly said it would do, in words as well as in the stance field.

Found on run 20260930-173547-seed1, month 4. Delegate D wrote in the response round "I endorse the
audit (D2) ..." and the final ballot on D2 was NO. The detector only ever read the structured `stances`
field, so a prose endorsement with no stance filed beside it (or an "undecided" one) was invisible to it.

The same month showed what the ask-back does to a model. D's first ballot said D2 yes and
army_target 30000. The detector (rightly or not) queried M3, and the repair call asked only about that
vote, but the engine adopted the WHOLE of the second answer: D2 became no, and the army order became
3100. A narrow question was allowed to overwrite unrelated orders and votes, which is how a repair came
to produce the very mismatch it exists to prevent.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import errors  # noqa: E402
from karamaniya.council import (_apply_vote_repair, _prose_intents,  # noqa: E402
                                _vote_intent_clashes)


def ballot(votes, reasons=None):
    return {"votes": votes, "vote_reasons": reasons or {m: "" for m in votes}}


# Verbatim from run 20260930-173547-seed1, log.jsonl line 180 (revision) and 189 (repair ballot).
REAL_RESPONSE = ("We secure readiness without sacrificing legitimacy. I endorse the audit (D2) to clear our "
                 "finances and protect training budgets; clean books are essential for future funding "
                 "requests. On debt service (M3), the bond-financed quarter of arrears is vital; it frees "
                 "reserves for grain imports while maintaining fiscal transparency, as promised.")
REAL_STANCES = {"D1": "support", "D2": "support", "D3": "undecided", "M3": "support"}
REAL_D2_REASON = ("I oppose expanding the audit scope beyond finances, procurement, pay, and leak origins as "
                  "ordered in D3's withdrawal context (implied by agenda). The motion asks for an operational "
                  "trail ('access') which risks exposing current deployment")


class TheExactShapeFromTheBrief(unittest.TestCase):
    def test_an_endorsement_in_words_followed_by_no_is_a_mismatch(self):
        found = _vote_intent_clashes({"response": "I endorse the audit (D2)"},
                                     ballot({"D2": "no"}, {"D2": "The scope worries me."}))
        self.assertEqual(len(found), 1)
        clash = found[0]
        self.assertEqual((clash["code"], clash["motion"], clash["stance"], clash["vote"]),
                         ("VOTE_INTENT_MISMATCH", "D2", "support", "no"))
        self.assertEqual(clash["source"], "statement")
        self.assertIn("endorse the audit (D2)", clash["statement"])

    def test_the_same_with_no_reason_at_all(self):
        self.assertEqual(len(_vote_intent_clashes({"response": "I endorse the audit (D2)", "stances": {}},
                                                  ballot({"D2": "no"}))), 1)

    def test_the_opposite_direction(self):
        found = _vote_intent_clashes({"response": "I oppose M3; it spends what we do not have."},
                                     ballot({"M3": "yes"}, {"M3": "It is the right instrument."}))
        self.assertEqual([(c["motion"], c["stance"], c["vote"]) for c in found], [("M3", "oppose", "yes")])

    def test_the_old_structured_only_reading_was_blind_to_this(self):
        """Documents the gap: with no stance filed the old detector had nothing to compare against."""
        staged = {"response": "I endorse the audit (D2)", "stances": {}}
        self.assertEqual([c for c in _vote_intent_clashes(staged, ballot({"D2": "no"}))
                          if c["source"] == "stance"], [])


class WhatWasActuallyRecorded(unittest.TestCase):
    def test_the_real_ballot_that_reversed_d2_is_still_caught_through_the_stance(self):
        staged = {"response": REAL_RESPONSE, "stances": REAL_STANCES}
        found = _vote_intent_clashes(staged, ballot({"D1": "yes", "D2": "no", "M3": "conditional"},
                                                    {"D1": "Printing at zero aligns with the need.",
                                                     "D2": REAL_D2_REASON, "M3": "I support paying arrears"}))
        self.assertEqual([(c["motion"], c["source"]) for c in found], [("D2", "stance")])

    def test_prose_does_not_double_count_a_motion_the_stance_already_covers(self):
        staged = {"response": REAL_RESPONSE, "stances": REAL_STANCES}
        found = _vote_intent_clashes(staged, ballot({"D2": "no"}, {"D2": "No."}))
        self.assertEqual(len(found), 1)


class WhatMustNotBeFlagged(unittest.TestCase):
    def test_ambiguous_discussion(self):
        for text in ("The audit (D2) is worth discussing before we decide.",
                     "Delegate B has tabled the audit (D2).",
                     "Everyone should read the audit scope (D2) carefully.",
                     "What does D2 actually cost?",
                     "I am undecided on D2."):
            with self.subTest(text=text):
                self.assertEqual(_vote_intent_clashes({"response": text}, ballot({"D2": "no"})), [])

    def test_praising_the_goal_is_not_endorsing_the_motion(self):
        for text in ("I support the goal of clean books behind D2, but not yet this text.",
                     "I endorse the aim of transparency in D2.",
                     "I back the principle behind D2."):
            with self.subTest(text=text):
                self.assertEqual(_vote_intent_clashes({"response": text}, ballot({"D2": "no"})), [])

    def test_conditional_and_tentative_support(self):
        for text in ("I support D2 if the scope is narrowed.",
                     "I would support D2 unless it touches the press.",
                     "I might support D2.",
                     "I support D2 provided Treasury confirms the cost.",
                     "I will vote yes on D2 only if reserves hold.",
                     "I support D2, subject to the amendment passing.",
                     "I am inclined to support D2."):
            with self.subTest(text=text):
                self.assertEqual(_vote_intent_clashes({"response": text}, ballot({"D2": "no"})), [])

    def test_other_peoples_positions_and_the_past(self):
        for text in ("Delegate B supports D2 and so does C.",
                     "I supported D2 last month.",
                     "We support D2 as a government."):
            with self.subTest(text=text):
                self.assertEqual(_vote_intent_clashes({"response": text}, ballot({"D2": "no"})), [])

    def test_an_abstention_is_not_a_reversal_of_support(self):
        self.assertEqual(_vote_intent_clashes({"response": "I endorse the audit (D2)"},
                                              ballot({"D2": "abstain"})), [])
        self.assertEqual(_vote_intent_clashes({"response": "I endorse the audit (D2)"},
                                              ballot({"D2": "conditional"})), [])

    def test_an_explicitly_uncertain_stance_silences_the_prose(self):
        for stance in ("undecided", "conditional"):
            with self.subTest(stance=stance):
                self.assertEqual(_vote_intent_clashes(
                    {"response": "I endorse the audit (D2)", "stances": {"D2": stance}},
                    ballot({"D2": "no"})), [])

    def test_a_motion_that_is_not_on_the_ballot(self):
        self.assertEqual(_vote_intent_clashes({"response": "I endorse the audit (D9)"}, ballot({"D2": "no"})), [])

    def test_no_response_round_at_all(self):
        self.assertEqual(_vote_intent_clashes({}, ballot({"D2": "no"})), [])
        self.assertEqual(_vote_intent_clashes(None, ballot({"D2": "no"})), [])


class TheLatestClearIntentWins(unittest.TestCase):
    def test_a_reversal_inside_the_response_itself(self):
        text = "I endorse the audit (D2). Having heard E, I now oppose D2."
        self.assertEqual(_vote_intent_clashes({"response": text}, ballot({"D2": "no"})), [])
        found = _vote_intent_clashes({"response": text}, ballot({"D2": "yes"}))
        self.assertEqual([(c["stance"], c["vote"]) for c in found], [("oppose", "yes")])

    def test_later_support_overrides_earlier_opposition(self):
        text = "I oppose D2 as drafted. The amendment answers me, so I support D2."
        found = _vote_intent_clashes({"response": text}, ballot({"D2": "no"}, {"D2": "Not now."}))
        self.assertEqual([(c["stance"], c["vote"]) for c in found], [("support", "no")])

    def test_each_motion_keeps_its_own_intent(self):
        intents = _prose_intents("I support D1. I oppose D2. I back M3 and M4.", {"D1", "D2", "M3", "M4"})
        self.assertEqual({m: i[0] for m, i in intents.items()},
                         {"D1": "support", "D2": "oppose", "M3": "support", "M4": "support"})

    def test_a_contrast_is_not_a_second_endorsement(self):
        """Both verbatim from recorded runs, where the first reading of them gave support to the motion
        the delegate was setting aside."""
        intents = _prose_intents("I support D2 over D1: preserve reserves for food security and [cut]", {"D1", "D2"})
        self.assertEqual({m: i[0] for m, i in intents.items()}, {"D2": "support"})
        intents = _prose_intents("I will vote for D3, the reserves payment with the 55M import floor, and "
                                 "against D4: new domestic bonds now raise future service costs.", {"D3", "D4"})
        self.assertEqual({m: i[0] for m, i in intents.items()}, {"D3": "support"})
        for text in ("I support D2, not D1.", "I back M3 rather than M4.", "I support M1 instead of M2."):
            with self.subTest(text=text):
                self.assertEqual(len(_prose_intents(text, {"D1", "D2", "M1", "M2", "M3", "M4"})), 1)

    def test_vote_statements(self):
        for text, vote, stance in (("I will vote yes on M1.", "no", "support"),
                                   ("My vote on M1 is no.", "yes", "oppose"),
                                   ("I'll vote against M1.", "yes", "oppose"),
                                   ("I vote yes on M1", "no", "support")):
            with self.subTest(text=text):
                found = _vote_intent_clashes({"response": text}, ballot({"M1": vote}))
                self.assertEqual([(c["motion"], c["stance"]) for c in found], [("M1", stance)])

    def test_an_id_less_vote_statement_binds_only_when_there_is_one_motion(self):
        self.assertEqual(len(_vote_intent_clashes({"response": "I will vote yes."}, ballot({"M1": "no"}))), 1)
        self.assertEqual(_vote_intent_clashes({"response": "I will vote yes."},
                                              ballot({"M1": "no", "M2": "no"})), [])


class AnExplicitReversalInTheBallotIsNotAMismatch(unittest.TestCase):
    def test_reversals_the_brief_names(self):
        for reason in ("I withdraw my support for this text.",
                       "Given the added access trail, I now oppose it.",
                       "My condition was not met, so I vote no.",
                       "I no longer support D2 after the scope changed.",
                       "I have changed my position on this motion.",
                       "I have reconsidered; the cost is too high.",
                       "Having heard E's demand, I cannot back it any more.",
                       "After the amendment I am retracting my earlier endorsement."):
            with self.subTest(reason=reason):
                self.assertEqual(_vote_intent_clashes({"response": "I endorse the audit (D2)"},
                                                      ballot({"D2": "no"}, {"D2": reason})), [])

    def test_a_reason_that_merely_argues_against_the_motion_is_not_a_reversal(self):
        for reason in ("The scope is too broad.", "I oppose expanding the audit scope beyond finances.",
                       "Not convinced.", "No."):
            with self.subTest(reason=reason):
                self.assertEqual(len(_vote_intent_clashes({"response": "I endorse the audit (D2)"},
                                                          ballot({"D2": "no"}, {"D2": reason}))), 1)

    def test_the_old_exemptions_still_hold_for_the_structured_path(self):
        for reason in ("I supported it, but the amendment removed the audit clause.",
                       "M2 is withdrawn, so M5 is no longer redundant.",
                       "On reflection the costing does not survive contact with the reserves.",
                       "I withdraw my support."):
            with self.subTest(reason=reason):
                self.assertEqual(_vote_intent_clashes({"stances": {"M5": "support"}},
                                                      ballot({"M5": "no"}, {"M5": reason})), [])


class TheAskBackMayOnlyChangeWhatItAsked(unittest.TestCase):
    """The real month-4 shape: M3 was queried, and the repair answer rewrote everything."""

    FIRST = {"votes": {"D1": "conditional", "D2": "yes", "M3": "no"},
             "vote_reasons": {"D1": "zero printing, contingent", "D2": "A targeted audit is essential.",
                              "M3": "Domestic bonds destroy credit."},
             "vote_conditions": {"D1": {"kind": "metric", "metric": "reserves", "operator": ">=",
                                        "value": 50.0, "if_unmet": "no"}},
             "orders": {"army": {"army_target": 30000, "recruitment": "none", "patronage": True}},
             "notes": "Union threat is high; M3 will cripple finances.",
             "belief_updates": [{"proposition": "union_attack_soon", "direction": "more_likely",
                                 "reason": "leaked plans confirm vulnerability"}],
             "private_messages": [{"to": "C", "text": "Do not force bankruptcy."}]}
    REPAIR = {"votes": {"D1": "yes", "D2": "no", "M3": "conditional"},
              "vote_reasons": {"D1": "aligns", "D2": "I oppose expanding the scope.",
                               "M3": "I support paying arrears only if the Treasury honours its promise."},
              "vote_conditions": {"M3": {"kind": "metric", "metric": "reserves", "operator": ">=",
                                         "value": 50.0, "if_unmet": "abstain"}},
              "orders": {"army": {"army_target": 3100, "recruitment": "partial", "patronage": False}},
              "notes": "leaked plans indicate they are preparing for force within months.",
              "belief_updates": [], "private_messages": []}

    def merged(self):
        return _apply_vote_repair(self.FIRST, self.REPAIR, {"M3"}, present={"D1", "D2", "M3"})

    def test_the_asked_ballot_is_taken_from_the_repair(self):
        out = self.merged()
        self.assertEqual(out["votes"]["M3"], "conditional")
        self.assertIn("honours its promise", out["vote_reasons"]["M3"])
        self.assertEqual(out["vote_conditions"]["M3"]["value"], 50.0)

    def test_votes_it_did_not_ask_about_stay_as_first_given(self):
        out = self.merged()
        self.assertEqual(out["votes"]["D2"], "yes")
        self.assertEqual(out["votes"]["D1"], "conditional")
        self.assertEqual(out["vote_reasons"]["D2"], "A targeted audit is essential.")
        self.assertEqual(out["vote_conditions"]["D1"]["if_unmet"], "no")

    def test_orders_notes_beliefs_and_messages_are_never_replaced(self):
        out = self.merged()
        self.assertEqual(out["orders"]["army"]["army_target"], 30000)
        self.assertEqual(out["orders"]["army"]["recruitment"], "none")
        self.assertTrue(out["orders"]["army"]["patronage"])
        self.assertEqual(out["notes"], self.FIRST["notes"])
        self.assertEqual(out["belief_updates"], self.FIRST["belief_updates"])
        self.assertEqual(out["private_messages"], self.FIRST["private_messages"])

    def test_the_inputs_are_not_mutated(self):
        first, repair = dict(self.FIRST), dict(self.REPAIR)
        import copy
        snapshot = (copy.deepcopy(first), copy.deepcopy(repair))
        _apply_vote_repair(first, repair, {"M3"}, present={"D1", "D2", "M3"})
        self.assertEqual((first, repair), snapshot)

    def test_a_vote_the_repair_did_not_answer_is_not_turned_into_an_abstention(self):
        """A motion missing from the raw answer normalises to 'abstain'; that is not the delegate's choice."""
        silent = dict(self.REPAIR, votes={"D1": "yes", "D2": "no", "M3": "abstain"})
        out = _apply_vote_repair(self.FIRST, silent, {"M3"}, present={"D1", "D2"})
        self.assertEqual(out["votes"]["M3"], "no")

    def test_a_repair_that_drops_the_condition_clears_it(self):
        repaired = dict(self.REPAIR, votes={"D1": "yes", "D2": "no", "M3": "yes"}, vote_conditions={})
        first = dict(self.FIRST, votes={"D1": "yes", "D2": "yes", "M3": "conditional"},
                     vote_conditions={"M3": {"kind": "metric", "metric": "reserves", "operator": ">=",
                                             "value": 1.0, "if_unmet": "no"}})
        out = _apply_vote_repair(first, repaired, {"M3"}, present={"M3"})
        self.assertEqual(out["votes"]["M3"], "yes")
        self.assertNotIn("M3", out["vote_conditions"])


class EndToEndThroughARealCouncilMonth(unittest.TestCase):
    """The whole flow: clash -> ask-back -> what the engine records and executes.

    One scripted seat (the army holder) is made to do what Qwen did on the real run: state support for
    a motion in the response round, cast a contradicting first ballot, and then answer the ask-back
    with a full re-written decision whose army order is 3100."""

    def build(self, second_vote, second_reason="I changed my position after the debate."):
        import shutil
        import tempfile
        from karamaniya.backends.scripted import ScriptedBackend
        from karamaniya.config import load_config
        from karamaniya.council import Council
        from karamaniya.runner import _seats
        from karamaniya.storage import RunStore
        from karamaniya.world import new_world

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg = load_config(os.path.join(root, "council.scripted.toml"))
        mapping = {letter: seat["label"] for letter, seat in zip("ABCDE", cfg["seats"])}
        cfg = {**cfg, "mapping": mapping}
        tmp = tempfile.mkdtemp(prefix="karamaniya-intent-")
        self.addCleanup(shutil.rmtree, tmp, True)
        w = new_world(cfg["run"]["seed"], 12, member_ids=list(mapping))
        seats = _seats(cfg, mapping)
        self.calls, self.target = [], None
        case = self

        class Waverer(ScriptedBackend):
            def call(self, system, user, schema, context):
                res = super().call(system, user, schema, context)
                member, phase = context.get("member"), context.get("phase")
                if member != case.target or not isinstance(res.data, dict):
                    return res
                data = res.data
                if phase == "revision" and data.get("stances"):
                    data["stances"][next(iter(data["stances"]))] = "support"      # said in the response round
                if phase == "decision" and data.get("votes"):
                    motion = next(iter(data["votes"]))
                    if context.get("vote_intent_repair"):
                        case.calls.append(("repair", motion, (data.get("orders") or {}).get("army", {}).get("army_target")))
                        data["votes"][motion] = second_vote
                        data["vote_reasons"][motion] = second_reason
                        data["orders"]["army"]["army_target"] = 3100                  # the regenerated order
                        data["orders"]["army"]["recruitment"] = "general"
                    else:
                        case.calls.append(("first", motion, (data.get("orders") or {}).get("army", {}).get("army_target")))
                        data["votes"][motion] = "no"                                  # contradicts 'support'
                        data.setdefault("vote_reasons", {})[motion] = "No."
                return res

        for seat in seats.values():
            seat.backend = Waverer(seat.cfg)
        council = Council(w, seats, cfg["run"], RunStore(os.path.join(tmp, "r")))
        council.store.save_config(cfg)
        council.survey()
        council.diagnose_founding()
        council.form_government()
        return council, w

    def month_with_an_askback(self, council):
        """Run months until the army holder has been seated and a motion reaches its ballot."""
        for _ in range(10):
            self.calls.clear()
            record = council.run_month()
            if any(kind == "repair" for kind, *_ in self.calls):
                return record
            # The offices are filled by the first month's appointment motions, so the holder to
            # interfere with is only known once that month has been resolved.
            self.target = council.w.const.offices.get("army")
        self.fail("no month produced a vote-intent ask-back for the army holder")

    def test_the_delegate_fixes_the_ballot_and_nothing_else_moves(self):
        council, w = self.build(second_vote="yes")
        record = self.month_with_an_askback(council)
        decision = record["decisions"][self.target]
        first = next(c for c in self.calls if c[0] == "first")
        motion = first[1]
        self.assertEqual(decision["votes"][motion], "yes", "the asked ballot is the one the delegate gave when asked")
        self.assertEqual(decision["vote_intent_clashes"], [])
        # The regenerated army order (3100, recruitment general) must NOT have replaced the first answer.
        army = decision["orders"]["army"]
        self.assertEqual(army["army_target"], first[2])
        self.assertNotEqual(army["army_target"], 3100)
        self.assertNotEqual(army["recruitment"], "general")
        repair = decision["vote_intent_repair"]
        self.assertEqual(repair["asked"], [motion])
        self.assertEqual(repair["scope"], "asked motions only")
        self.assertEqual((repair["first_ballot"][motion], repair["repair_ballot"][motion]), ("no", "yes"))
        self.assertEqual(record["vote_intent_mismatches"], [])
        self.assertNotEqual(w.policy.army_target, 3100)

    def test_the_delegate_confirms_the_contradiction_bare_and_it_is_recorded(self):
        council, w = self.build(second_vote="no", second_reason="No.")
        record = self.month_with_an_askback(council)
        decision = record["decisions"][self.target]
        first = next(c for c in self.calls if c[0] == "first")
        motion = first[1]
        self.assertEqual(decision["votes"][motion], "no")
        # Asked, and confirmed without a word of explanation: the mismatch stands and is surfaced.
        self.assertEqual([(c["motion"], c["source"]) for c in decision["vote_intent_clashes"]], [(motion, "stance")])
        self.assertEqual([(f["member"], f["motion"]) for f in record["vote_intent_mismatches"]],
                         [(self.target, motion)])
        self.assertEqual(len([e for e in errors.since(w, record["month"]) if e["code"] == "VOTE_INTENT_MISMATCH"]), 1)
        # ...and confirming a vote does not license the regenerated army order.
        self.assertEqual(decision["orders"]["army"]["army_target"], first[2])

    def test_an_explained_change_of_position_is_not_a_mismatch(self):
        council, w = self.build(second_vote="no", second_reason="I changed my position after the debate.")
        record = self.month_with_an_askback(council)
        decision = record["decisions"][self.target]
        self.assertEqual(decision["vote_intent_clashes"], [])
        self.assertEqual(record["vote_intent_mismatches"], [])

    def test_the_call_log_marks_which_call_was_the_repair(self):
        council, _ = self.build(second_vote="yes")
        self.month_with_an_askback(council)
        logged = [c for c in council.store.read_log("call") if c.get("phase") == "decision"]
        marked = [c for c in logged if c.get("repair") == "vote_intent"]
        self.assertTrue(marked, "the repair call is indistinguishable from the original in the log")
        self.assertTrue(all(c["member"] == self.target for c in marked))
        self.assertTrue(any(c.get("repair") != "vote_intent" and c["member"] == self.target for c in logged))
        import json
        with open(os.path.join(council.store.path, "prompts.jsonl"), encoding="utf-8") as f:
            prompts = [json.loads(line) for line in f]
        self.assertTrue(any(p.get("repair") == "vote_intent" for p in prompts))


class TheFindingIsSurfacedNotJustComputed(unittest.TestCase):
    def test_the_code_is_in_the_taxonomy(self):
        self.assertTrue(errors.is_registered("VOTE_INTENT_MISMATCH"))

    def test_resolution_lifts_the_clash_into_the_month_record_and_the_ledger(self):
        import threading
        from karamaniya.council import Council
        from karamaniya.world import new_world
        w = new_world(3, 6, member_ids=list("ABCDE"))
        council = Council.__new__(Council)
        council.w, council.pending_dms, council.observer, council._lock, council.spend = \
            w, [], None, threading.Lock(), 0.0
        clash = {"code": "VOTE_INTENT_MISMATCH", "motion": "D2", "stance": "support", "vote": "no",
                 "reason": "No.", "source": "statement", "statement": "I endorse the audit (D2)"}
        decisions = {mid: {"votes": {}, "vote_reasons": {}, "vote_conditions": {}, "resign": False, "coup": None,
                           "coup_stance": "resist", "orders": {}, "operations": {}, "private_messages": [],
                           "notes": "", "belief_updates": [], "decision_factors": [],
                           "vote_intent_clashes": [clash] if mid == "D" else []} for mid in "ABCDE"}
        record = council._resolve_v2(decisions, [], [], [], list("ABCDE"), [], {}, {}, [], False)
        self.assertEqual([(f["member"], f["motion"], f["source"]) for f in record["vote_intent_mismatches"]],
                         [("D", "D2", "statement")])
        ledger = [e for e in errors.since(w, w.month) if e["code"] == "VOTE_INTENT_MISMATCH"]
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["details"]["member"], "D")


if __name__ == "__main__":
    unittest.main()
