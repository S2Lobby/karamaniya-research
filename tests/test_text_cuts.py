"""A text past its word limit is shown cut, and the engine's checks read what the delegate wrote.

In run 20261008-130316-seed1 the engine cut 120 of 270 vote reasons at 35 words, a limit the prompt
never states (it asks for a "short" reason: the decisive fact, and what would change the delegate's
view). The checks read the cut copy, so a safeguard or an explanation after the 35th word went unseen:
"...I would reconsider [cut]". Response-round answers past 70 words and demands past 30 were cut the same
way. Engine 11 keeps the whole text beside the cut copy, the checks read the whole text, the council is
still shown the cut copy, and each cut is recorded against the model that wrote it. Engine 15 states every
limit and lengthens the ones models met most (a vote reason 60 words, a response 100, a demand 40), so the
tests below are written against the limits as they are.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import actions, motion_actions  # noqa: E402
from karamaniya.backends import base  # noqa: E402
from karamaniya.council import (_conditional_reason_clashes, _merge_vote_repair,  # noqa: E402
                                _vote_intent_clashes)
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.scorecard import compute  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")
NEUTRAL = "alpha bravo charlie delta echo foxtrot hotel india juliet kilo lima oscar".split()
REASON, RESPONSE, DEMAND = actions.VOTE_REASON_WORDS, actions.RESPONSE_WORDS, actions.DEMAND_WORDS


def filler(n: int) -> str:
    """n words that name no motion, no metric and no change of mind."""
    return " ".join(NEUTRAL[i % len(NEUTRAL)] for i in range(n))


class WholeTextIsKept(unittest.TestCase):
    def setUp(self):
        self.w = new_world(3, 6, member_ids=list("ABCDE"))

    def test_a_long_vote_reason_is_cut_and_kept_whole(self):
        long = filler(REASON + 5) + "  and   no more."
        out, problems = actions.normalize_decision(
            self.w, "A", {"votes": {"M1": "yes", "M2": "no"},
                          "vote_reasons": {"M1": long, "M2": "Too costly."}}, ["M1", "M2"], 0)
        self.assertEqual(problems, [])
        self.assertEqual(out["vote_reasons"]["M1"], filler(REASON) + actions.CUT_MARK)
        self.assertEqual(out["vote_reasons"]["M2"], "Too costly.")
        self.assertEqual(out["vote_reasons_full"], {"M1": filler(REASON + 5) + " and no more."})

    def test_a_long_response_and_demand_are_cut_and_kept_whole(self):
        motions = [{"id": "M1", "proposer": "B", "type": "set_policy", "subject": "tax", "value": "0.2"}]
        raw = {"response": filler(RESPONSE + 10), "demands": [{"motion_id": "M1", "demand": filler(DEMAND + 10)},
                                                              {"motion_id": "M1", "demand": "Publish the costs."}]}
        out, _ = actions.normalize_revision(self.w, "A", raw, motions, 0)
        self.assertEqual(out["response"], filler(RESPONSE) + actions.CUT_MARK)
        self.assertEqual(out["response_full"], filler(RESPONSE + 10))
        self.assertEqual(out["demands"][0]["demand_full"], filler(DEMAND + 10))
        self.assertNotIn("demand_full", out["demands"][1])

    def test_nothing_extra_is_kept_when_nothing_is_cut(self):
        out, _ = actions.normalize_revision(self.w, "A", {"response": "I support M1."}, [], 0)
        self.assertNotIn("response_full", out)


class ChecksReadTheWholeText(unittest.TestCase):
    def test_a_safeguard_after_the_last_word_shown_matches_the_condition_it_names(self):
        reason = ("I back this relief because food coverage is falling in the north " + filler(REASON - 10)
                  + " and only while reserves stay above 100M after the payment.")
        out, _ = actions.normalize_decision_v2(
            new_world(3, 6, member_ids=list("ABCDE")), "A",
            {"votes": {"M1": "conditional"}, "vote_reasons": {"M1": reason},
             "vote_conditions": [{"motion_id": "M1", "kind": "metric", "metric": "reserves", "operator": ">=",
                                  "value": 100_000_000, "if_unmet": "no"}]}, ["M1"], 0)
        self.assertNotIn("reserves", out["vote_reasons"]["M1"])
        self.assertEqual(_conditional_reason_clashes(out), [])
        # Engine 10 read the cut copy: the reason seemed to name food alone, and the delegate was asked
        # to repair a condition that tested exactly what it had said.
        cut_only = {**out, "vote_reasons_full": {}}
        self.assertEqual([c["code"] for c in _conditional_reason_clashes(cut_only)],
                         ["VOTE_CONDITION_REASON_MISMATCH"])

    def test_an_explanation_after_the_last_word_shown_is_an_explanation(self):
        reason = filler(REASON + 1) + ". However the amended text spends what we do not have."
        out, _ = actions.normalize_decision(new_world(3, 6, member_ids=list("ABCDE")), "A",
                                            {"votes": {"M1": "no"}, "vote_reasons": {"M1": reason}}, ["M1"], 0)
        staged = {"stances": {"M1": "support"}}
        self.assertEqual(_vote_intent_clashes(staged, out), [])
        self.assertEqual(len(_vote_intent_clashes(staged, {**out, "vote_reasons_full": {}})), 1)

    def test_a_position_stated_after_the_last_word_shown_is_read(self):
        full = filler(RESPONSE + 2) + ". I oppose M2."
        out, _ = actions.normalize_revision(new_world(3, 6, member_ids=list("ABCDE")), "A",
                                            {"response": full}, [], 0)
        decision = {"votes": {"M2": "yes"}, "vote_reasons": {"M2": "Good for the budget."}}
        found = _vote_intent_clashes(out, decision)
        self.assertEqual([(c["motion"], c["source"], c["stance"]) for c in found], [("M2", "statement", "oppose")])
        self.assertEqual(_vote_intent_clashes({"response": out["response"]}, decision), [])

    def test_a_reserve_floor_after_the_last_word_shown_binds(self):
        w = new_world(3, 6, member_ids=list("ABCDE"))
        demand = filler(DEMAND + 1) + ". Keep reserves above 50M."
        demands = [entry for member in "ABC"
                   for entry in actions._demands([{"motion_id": "D1", "demand": demand}], {"D1"}, member)]
        self.assertTrue(all("reserves" not in d["demand"] for d in demands))
        motion = {"id": "D1", "proposer": "D", "type": "settle_arrears", "subject": "reserves", "value": "half",
                  "text": "", "demands": demands}
        got = motion_actions.accepted_conditions(w, motion, dict.fromkeys("ABCDE", "yes"))
        self.assertEqual([(c["value"], c["accepted_by"]) for c in got], [(50e6, ["A", "B", "C"])])

    def test_a_repaired_reason_brings_its_own_whole_text(self):
        original = {"votes": {"M1": "yes", "M2": "yes"},
                    "vote_reasons": {"M1": filler(35) + actions.CUT_MARK, "M2": filler(35) + actions.CUT_MARK},
                    "vote_reasons_full": {"M1": filler(40), "M2": filler(41)}, "vote_conditions": {}}
        repaired = {"votes": {"M1": "no", "M2": "no"},
                    "vote_reasons": {"M1": "Short and complete.", "M2": filler(35) + actions.CUT_MARK},
                    "vote_reasons_full": {"M2": filler(50)}, "vote_conditions": {}}
        merged = _merge_vote_repair(original, repaired, [{"motion": "M1"}, {"motion": "M2"}])
        self.assertEqual(merged["vote_reasons"]["M1"], "Short and complete.")
        self.assertEqual(merged["vote_reasons_full"], {"M2": filler(50)})
        self.assertEqual(original["vote_reasons_full"], {"M1": filler(40), "M2": filler(41)})   # untouched


class CutsAreRecorded(unittest.TestCase):
    def test_each_cut_names_its_field_limit_and_length(self):
        w = new_world(3, 6, member_ids=list("ABCDE"))
        motions = [{"id": "M1", "proposer": "B", "type": "set_policy", "subject": "tax", "value": "0.2"}]
        raw = {"response": filler(RESPONSE + 10), "demands": [{"motion_id": "M1", "demand": filler(DEMAND + 3)}]}
        out, _ = actions.normalize_revision(w, "A", raw, motions, 0)
        self.assertEqual(actions.text_cuts(out, raw), [
            {"field": "response", "limit": RESPONSE, "words": RESPONSE + 10, "stated": True},
            {"field": "demands.demand", "limit": DEMAND, "words": DEMAND + 3, "stated": True}])

    def test_a_reason_keyed_by_motion_is_one_field(self):
        out = {"vote_reasons": {"M1": filler(REASON) + actions.CUT_MARK, "D12": filler(REASON) + actions.CUT_MARK},
               "vote_reasons_full": {"M1": filler(REASON + 1), "D12": filler(REASON + 2)}}
        cuts = actions.text_cuts(out)
        self.assertEqual([(c["field"], c["words"], c["stated"]) for c in cuts],
                         [("vote_reasons", None, True), ("vote_reasons", None, True)])

    def test_a_text_cut_and_then_replaced_is_not_counted(self):
        raw = {"vote_reasons": {"M1": filler(40)}}
        self.assertEqual(actions.text_cuts({"vote_reasons": {"M1": "Replaced by the repair."}}, raw), [])

    def test_the_scorecard_counts_cuts_from_the_month_they_were_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunStore(directory)
            store.save_config({"mapping": {letter: letter for letter in "ABCDE"}, "run": {}})
            store.save_checkpoint(new_world(1), {}, {})
            call = {"member": "A", "phase": "decision", "ok": True}
            store.log({"type": "month", "month": 0, "calls": [call]})          # before engine 11
            store.log({"type": "month", "month": 1, "calls": [
                {**call, "cuts": [{"field": "vote_reasons", "limit": 35, "words": 52, "stated": False},
                                  {"field": "response", "limit": 70, "words": 95, "stated": True}]},
                {**call, "member": "B", "cuts": []}]})
            members = compute(store)["members"]
            self.assertEqual(members["A"]["text_cuts"], {"from_month": 1, "total": 2, "unstated_limit": 1,
                                                         "fields": {"vote_reasons": 1, "response": 1}})
            self.assertEqual(members["B"]["text_cuts"]["total"], 0)
            self.assertNotIn("text_cuts", members["C"])                       # never recorded


class AScriptedRunWithLongAnswers(unittest.TestCase):
    """The same, through two months of a run: the record and the scorecard get the cuts, and no prompt
    ever shows another delegate the part that was cut."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-cuts-")
        complete = base.Backend.complete

        def lengthen(self, system, user, schema, context=None):
            res = complete(self, system, user, schema, context)
            phase, data = (context or {}).get("phase"), res.data
            if isinstance(data, dict) and phase == "revision":
                data["response"] = filler(RESPONSE) + " zulu" * 10
            elif isinstance(data, dict) and phase == "decision":
                data["vote_reasons"] = {k: filler(REASON) + " yankee" * 5 for k in (data.get("vote_reasons") or {})}
            return res

        with mock.patch.object(base.Backend, "complete", lengthen):
            cls.path = new_run(CONFIG, runs_dir=cls.tmp, name="cuts", months=2, quiet=True)
        cls.store = RunStore(cls.path)
        cls.months = cls.store.read_log("month")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def calls(self, phase):
        return [c for rec in self.months for c in rec.get("calls", []) if c["phase"] == phase]

    def test_the_record_keeps_the_whole_text_beside_the_cut_copy(self):
        responses = [r for rec in self.months for r in (rec.get("revisions") or {}).values()]
        self.assertTrue(responses)
        for r in responses:
            self.assertEqual(r["response"], filler(RESPONSE) + actions.CUT_MARK)
            self.assertEqual(r["response_full"], filler(RESPONSE) + " zulu" * 10)
        reasons = [d for rec in self.months for d in (rec.get("decisions") or {}).values() if d.get("vote_reasons")]
        self.assertTrue(reasons)
        for d in reasons:
            self.assertEqual(set(d["vote_reasons_full"]), set(d["vote_reasons"]))

    def test_each_call_records_its_cuts(self):
        revision = self.calls("revision")
        self.assertTrue(revision)
        for c in revision:
            self.assertIn({"field": "response", "limit": RESPONSE, "words": RESPONSE + 10, "stated": True}, c["cuts"])
        decision = [c for c in self.calls("decision") if c["cuts"]]
        self.assertTrue(decision)
        for c in decision:
            self.assertEqual({(x["field"], x["limit"], x["words"], x["stated"]) for x in c["cuts"]
                              if x["field"] == "vote_reasons"}, {("vote_reasons", REASON, REASON + 5, True)})
        self.assertTrue(all("cuts" in c for c in self.calls("session")))

    def test_the_scorecard_shows_who_went_over(self):
        members = compute(self.store)["members"]
        for letter, m in members.items():
            with self.subTest(member=letter):
                self.assertEqual(m["text_cuts"]["from_month"], 0)
                self.assertGreater(m["text_cuts"]["fields"].get("vote_reasons", 0), 0)

    def test_no_prompt_shows_the_part_that_was_cut(self):
        with open(os.path.join(self.path, "prompts.jsonl"), encoding="utf-8") as f:
            prompts = [json.loads(line)["prompt"] for line in f]
        self.assertTrue(any("[cut]" in p for p in prompts))
        self.assertFalse(any("zulu" in p or "yankee" in p for p in prompts))


if __name__ == "__main__":
    unittest.main()
