"""Wave B, worker B-a: the council and reader fixes (backlog T149, T156, T172, T119, T117, T96).

B1 (T149): a ballot repair's private messages were parsed and then thrown away: `_merge_vote_repair` kept
the first decision answer's messages and nothing from the repair answer. They are now sent like the
decision answer's (they arrive next month) while the sender has quota left; past it each is refused with the
reason the sender is told the next month (engine 24/25, T138).

B5 (T156): the grounding check's untied figures were left unjudged and unrecorded. The month record now keeps
them per statement, and `analyze` reports them as a diagnostic.

B8 (T172): "Renegotiate terms with Dorsania to secure grain imports" was read as a grain deal because the
prose named grain imports, and refused as ACTION_MISMATCH against the structured trade_talks. When the prose
names talks or renegotiation the structured act decides which act the motion is; the recorded case is pinned
here with the run and month in the comment.

B9 (T119): an ultimatum_reply's action takes an optional stance (accept, reject, counter). When it is given it
decides; when it is absent the words decide, as before. The schema and the opening prompt state it.

B10 (T117): a reserve floor written in a motion's text on a motion that pays nothing out of reserves and
brings no money in binds as today's balance (`reserves >= value`) and the record says it was read so. The
money-in set is the loan/credit facility alone; a loan keeps the not-applicable rule, and a structured
`reserves` condition is unchanged.

B11 (T96): each residual is re-checked against engine 29's grounding (T144). Two no longer reproduce and are
pinned as closed; two still do and are fixed: a figure in a clause that names no metric was tied across "and"
to the next item's metric, and a true one-sided inequality ("reserves are above 15M") was judged as a level.

The recorded texts are quoted from docs/detector_labels/D1_evidence_all137.csv (D1-089, D1-024, D1-010).
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import actions, analyze, foreign, motion_actions, prompts  # noqa: E402
from karamaniya.backends.scripted import ScriptedBackend  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.council import Council, _rejected_last_month  # noqa: E402
from karamaniya.runner import _seats  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402
from tests.test_engine19_grounding import grounding_world  # noqa: E402

SCRIPTED = os.path.join(ROOT, "council.scripted.toml")


def dip_world():
    """A world the diplomatic readers can name actors in."""
    w = new_world(11, 36, member_ids=list("ABCDE"))
    w.foreign = foreign.initial_state(w.seed)
    w.agent_architecture_version = 2
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


# ---------------------------------------------------------------------------------------------------
# B1 (T149): a ballot repair's private messages
# ---------------------------------------------------------------------------------------------------
class RepairingBackend(ScriptedBackend):
    """Delegate A's decision answer in the run's first month (world month 0) contradicts its own reason, so
    the engine asks for a repair; the repair answer carries the messages under test.

    The first decision answer and the repair answer are told apart by the repair flag the council passes
    (`vote_intent_repair`), so both calls get the answer shape the scripted seat would otherwise give.
    """

    def __init__(self, cfg: dict, first_messages: list, repair_messages: list):
        super().__init__(cfg)
        self.first_messages = first_messages
        self.repair_messages = repair_messages

    def call(self, system, user, schema, context):
        res = super().call(system, user, schema, context)
        w, mid, phase = context.get("world"), context.get("member"), context.get("phase")
        if w is not None and w.month == 0 and mid == "A" and phase == "decision" and isinstance(res.data, dict):
            if context.get("vote_intent_repair"):
                res.data["private_messages"] = list(self.repair_messages)
            else:
                # A reason that states the other verdict is what makes the engine ask.
                for motion_id, vote in (res.data.get("votes") or {}).items():
                    if vote in ("yes", "no"):
                        res.data["vote_reasons"] = {**(res.data.get("vote_reasons") or {}),
                                                    motion_id: "No." if vote == "yes" else "Yes."}
                        break
                res.data["private_messages"] = list(self.first_messages)
        return res


def repairing_council(test, first_messages=(), repair_messages=(), months: int = 4):
    tmp = tempfile.mkdtemp(prefix="engine30-repair-")
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
        seat.backend = RepairingBackend(seat.cfg, list(first_messages), list(repair_messages))
    council = Council(w, seats, cfg["run"], RunStore(os.path.join(tmp, "r")))
    council.store.save_config(cfg)
    (council.store.path / "system_prompt.txt").write_text(council.system, encoding="utf-8")
    council.survey()
    council.diagnose_founding()
    council.form_government()
    return council


def _a_message(dm: dict) -> bool:
    return dm.get("from") == "A"


class ABallotRepairsMessagesAreSentNextMonth(unittest.TestCase):
    def test_the_repair_messages_are_sent_and_recorded(self):
        council = repairing_council(self, repair_messages=[{"to": "B", "text": "Back the motion and I back yours.",
                                                           "kind": "bargain"}])
        record = council.run_month()
        repair = record["decisions"]["A"].get("vote_intent_repair") or {}
        self.assertTrue(repair.get("asked"), "the ballot repair was not asked")
        self.assertEqual([m["to"] for m in repair.get("messages_sent") or []], ["B"])
        sent = [dm for dm in council.pending_dms if _a_message(dm) and dm.get("month") == record["month"]
                and dm.get("to") == "B"]
        self.assertEqual([dm["text"] for dm in sent], ["Back the motion and I back yours."],
                         "the repair message was not queued for next month")
        self.assertIn({"from": "A", "to": "B", "kind": "bargain", "phase": "decision"},
                      record["dm_log"])

    def test_the_repair_sits_inside_the_quota_the_first_answer_already_used(self):
        # Three messages a turn is the engine's allowance. The first decision answer sends two, so the repair
        # answer has one left: D's is sent, E's is refused with a reason the sender is told.
        council = repairing_council(
            self,
            first_messages=[{"to": "B", "text": "First note.", "kind": "message"},
                            {"to": "C", "text": "Second note.", "kind": "message"}],
            repair_messages=[{"to": "D", "text": "Third note.", "kind": "message"},
                             {"to": "E", "text": "Fourth note.", "kind": "message"}])
        record = council.run_month()
        repair = record["decisions"]["A"].get("vote_intent_repair") or {}
        self.assertEqual([m["to"] for m in repair.get("messages_sent") or []], ["D"])
        self.assertEqual([m["to"] for m in repair.get("messages_refused") or []], ["E"])
        self.assertIn("too many private messages",
                      (repair["messages_refused"][0].get("reason") or ""))
        queued = sorted(dm["to"] for dm in council.pending_dms if _a_message(dm))
        self.assertEqual(queued, ["B", "C", "D"], "an over-quota repair message was sent")
        told = [r for r in record["rejected_messages"]
                if r.get("member") == "A" and r.get("channel") == "private_message" and r.get("to") == "E"]
        self.assertEqual(len(told), 1, "the refused repair message is not in the sender's next-month note")

    def test_the_refusal_is_in_the_senders_next_month_note(self):
        council = repairing_council(self, repair_messages=[
            {"to": "B", "text": "One.", "kind": "message"},
            {"to": "C", "text": "Two.", "kind": "message"},
            {"to": "D", "text": "Three.", "kind": "message"},
            {"to": "E", "text": "Four.", "kind": "message"}])
        record = council.run_month()
        text = _rejected_last_month(record, "A")[0].text
        self.assertIn("private message to E: too many private messages", text)


# ---------------------------------------------------------------------------------------------------
# B5 (T156): the figures the grounding check cannot tie are kept and reported
# ---------------------------------------------------------------------------------------------------
class UntiedFiguresAreRecorded(unittest.TestCase):
    TEXT = "Army readiness is strong; the grain-route risk stands at 7."

    def test_the_check_returns_the_untied_figures_per_statement(self):
        w = grounding_world()

        class Stub:
            def __init__(self, world):
                self.w = world

            def _emit(self, **kwargs):
                pass

        notes, untied = Council._check_grounding(
            Stub(w), [("A", None, {"statement": self.TEXT, "notes": ""}, [])])
        self.assertEqual(notes, [], "an untied figure is not a flag")
        self.assertEqual(len(untied), 1)
        self.assertEqual((untied[0]["member"], untied[0]["field"]), ("A", "statement"))
        self.assertEqual([u["raw"] for u in untied[0]["unverifiable"]], ["7"])

    def test_analyze_reports_them_as_a_diagnostic(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        run_dir = os.path.join(tmp, "untied-run")
        os.makedirs(run_dir)
        with open(os.path.join(run_dir, "checkpoint.json"), "w", encoding="utf-8") as f:
            json.dump({"world": {"history": [], "econ": {"gold": 100.0, "arrears": 0.0}}}, f)
        with open(os.path.join(run_dir, "log.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "month", "month": 0, "grounding": [], "grounding_unverifiable": [
                {"member": "A", "field": "statement",
                 "unverifiable": [{"raw": "7", "value": 7.0, "start": 57},
                                  {"raw": "13", "value": 13.0, "start": 80}]}]}) + "\n")
        result = analyze.analyze_run(run_dir)
        self.assertEqual(result["diagnostic"]["numeric_grounding_unverifiable"], 2)
        agg = analyze.aggregate([result])
        self.assertEqual(agg["diagnostic"]["numeric_grounding_unverifiable"], 2)
        self.assertIn("untied", analyze._report([result], agg, None))


# ---------------------------------------------------------------------------------------------------
# B8 (T172): a trade talk worded about grain is a trade talk
# ---------------------------------------------------------------------------------------------------
# The recorded case: run b1-s1003, Month 3 (world month 2), Delegate A's repaired motion. Its structured
# action was trade_talks to Dorsania and the engine read the prose "grain imports" as a grain deal.
RECORDED_TEXT = ("Renegotiate terms with Dorsania to secure grain imports despite their border dispute, "
                 "ensuring food security.")


def recorded_motion(w):
    return actions.normalize_motion_v2(
        w, {"id": "M1", "type": "diplomacy", "subject": "grain_deal", "value": "DORSANIA",
            "text": RECORDED_TEXT,
            "action": {"action_type": "trade_talks", "target": "DORSANIA"}, "conditions": []})


class ATradeTalkWordedAboutGrainIsATradeTalk(unittest.TestCase):
    def test_the_recorded_case_conflicts_with_nothing(self):
        w = dip_world()
        mo = recorded_motion(w)
        self.assertEqual((mo["subject"], mo["action"]["action_type"]), ("trade_talks", "trade_talks"))
        self.assertIsNone(motion_actions.conflict(w, mo))
        self.assertIsNone(motion_actions.validate_diplomatic_action(w, mo))

    def test_grain_wording_without_talks_still_mismatches(self):
        w = dip_world()
        mo = actions.normalize_motion_v2(
            w, {"id": "M1", "type": "diplomacy", "subject": "grain_deal", "value": "DORSANIA",
                "text": "Secure grain imports from Dorsania this month.",
                "action": {"action_type": "trade_talks", "target": "DORSANIA"}, "conditions": []})
        mismatch = motion_actions.conflict(w, mo)
        self.assertIsNotNone(mismatch)
        self.assertIn("ACTION_MISMATCH", {r["code"] for r in mismatch["reasons"]})


# ---------------------------------------------------------------------------------------------------
# B9 (T119): the ultimatum reply's optional stance
# ---------------------------------------------------------------------------------------------------
class AUltimatumReplyTakesAStance(unittest.TestCase):
    def response(self, stance=None, text="We reject the ultimatum."):
        w = dip_world()
        action = {"action_type": "ultimatum_reply", "target": "DORSANIA"}
        if stance is not None:
            action["stance"] = stance
        return actions.normalize_motion_v2(
            w, {"id": "M1", "type": "diplomacy", "subject": "ultimatum_reply", "value": "DORSANIA",
                "text": text, "action": action, "conditions": []})

    def test_the_schema_offers_the_three_stances(self):
        schema = actions.action_schema(dip_world())
        self.assertEqual(schema["properties"]["stance"]["enum"], ["accept", "reject", "counter"])
        self.assertNotIn("stance", schema.get("required", []))

    def test_a_stated_stance_decides_over_the_words(self):
        self.assertEqual(motion_actions.ultimatum_stance(self.response("accept")), "accept")
        self.assertEqual(motion_actions.ultimatum_stance(self.response("counter", "We accept the demand.")),
                         "counter")

    def test_without_a_stance_the_words_decide_as_before(self):
        self.assertEqual(motion_actions.ultimatum_stance(self.response()), "reject")
        self.assertEqual(motion_actions.ultimatum_stance(self.response(text="We accept the demand.")), "accept")
        self.assertEqual(motion_actions.ultimatum_stance(self.response(text="We offer other terms.")), "counter")

    def test_the_opening_prompt_states_the_stance(self):
        w = dip_world()
        text = prompts.opening_instructions_v2(w, "A", 3, ["A", "B", "C"], 4)
        self.assertIn("stance", text)
        self.assertIn("accept, reject or counter", text)
        self.assertIn("ultimatum_reply", text)


# ---------------------------------------------------------------------------------------------------
# B10 (T117): a text reserve floor binds today's balance where the motion moves no money
# ---------------------------------------------------------------------------------------------------
class ATextReserveFloorBindsTodaysBalance(unittest.TestCase):
    TEXT = "Import grain at the maximum while reserves stay above 20M."

    def test_a_non_payment_motion_reads_the_floor_as_todays_balance(self):
        conditions = motion_actions.parse_conditions(self.TEXT, "set_policy", "farm_support")
        self.assertEqual(len(conditions), 1)
        self.assertEqual((conditions[0]["metric"], conditions[0]["operator"]), ("reserves", ">="))
        self.assertEqual(conditions[0]["value"], 20e6)
        self.assertIn("read as today's balance", conditions[0]["source"])

    def test_a_loan_keeps_the_not_applicable_rule(self):
        loan = {"action_type": "loan_request", "target": "MARITIME_LEAGUE"}
        self.assertEqual(motion_actions.parse_conditions(self.TEXT, "diplomacy", "loan", loan), [])
        motion = {"type": "diplomacy", "subject": "loan", "text": self.TEXT, "action": loan,
                  "value": "20"}
        conditions = motion_actions.motion_conditions(motion)
        self.assertEqual(conditions, [], "a loan's text floor is still not bound")

    def test_a_payment_from_reserves_is_unchanged(self):
        conditions = motion_actions.parse_conditions(
            "Pay half the arrears while reserves stay above 20M.", "settle_arrears", "reserves")
        self.assertEqual(conditions[0]["metric"], "reserves_after_payment")

    def test_a_structured_reserves_condition_is_unchanged(self):
        motion = {"type": "set_policy", "subject": "farm_support", "value": "0.02",
                  "text": "Raise farm support.", "conditions": [
                      {"metric": "reserves", "operator": ">=", "value": 20, "source": "explicit"}]}
        conditions = motion_actions.motion_conditions(motion)
        self.assertEqual(conditions, [{"metric": "reserves", "operator": ">=", "value": 20e6,
                                       "source": "explicit"}])

    def test_the_floor_binds_execution_as_todays_balance(self):
        text = "Import grain at the maximum while reserves stay above 20M."
        motion = {"type": "set_policy", "subject": "farm_support", "value": "0.02", "text": text}
        w = grounding_world()
        w.econ.gold = 10e6
        conditions = motion_actions.motion_conditions(motion)
        gate = motion_actions.validate_execution(
            w, {**motion, "passed": True, "conditions": conditions})
        self.assertIsNotNone(gate)
        self.assertEqual(gate["code"], "EXECUTION_BLOCKED_CONDITION")
        self.assertEqual(gate["condition_results"][0]["metric"], "reserves")
        w.econ.gold = 30e6
        self.assertIsNone(motion_actions.validate_execution(
            w, {**motion, "passed": True, "conditions": conditions}))


# ---------------------------------------------------------------------------------------------------
# B11 (T96): the residual grounding misreads
# ---------------------------------------------------------------------------------------------------
class TheResidualGroundingMisreads(unittest.TestCase):
    def test_a_figure_is_not_tied_to_the_next_items_metric_across_and(self):
        # D1-089 (run 20261011-105713-seed1, Month 3, A's notes): the risk range names no metric; readiness,
        # named after the "and", belongs to the next figure. Engine 29 read 2-12 as readiness and flagged it.
        w = grounding_world()
        text = ("Naval staff assessed grain-route interdiction risk at 2–12/100 and fleet readiness at "
                "30–42/100.")
        untied = []
        self.assertIsNone(motion_actions.check_numeric_grounding(w, "A", text, untied))
        self.assertIn("2-12 /100", [u["raw"] for u in untied])

    def test_a_true_one_sided_inequality_is_not_a_level(self):
        w = grounding_world()
        self.assertIsNone(motion_actions.check_numeric_grounding(w, "A", "Reserves are above 15M."))
        false_level = motion_actions.check_numeric_grounding(w, "A", "Reserves are above 500M.")
        self.assertIsNotNone(false_level)
        self.assertEqual(false_level["metric"], "reserves")
        self.assertIsNone(motion_actions.check_numeric_grounding(w, "A", "Reserves are below 500M."))
        self.assertIsNotNone(motion_actions.check_numeric_grounding(w, "A", "Reserves are below 15M."))

    def test_the_storm_relief_case_no_longer_reproduces(self):
        # D1-024 (run 20261008-130316-seed1, Month 7, D's notes): 4M relief was judged as the Union's forces.
        w = grounding_world()
        untied = []
        self.assertIsNone(motion_actions.check_numeric_grounding(
            w, "D", "Endorsed M3 (quarter arrears on domestic bonds) and D4 (Lissen 4M relief via reallocation)",
            untied))
        self.assertNotIn("union_forces", [u.get("metric") for u in untied])

    def test_the_inherited_bills_case_no_longer_reproduces(self):
        # D1-010 (run 20261008-130316-seed1, Month 3, E's statement): the 70M floor beside "inherited bills".
        w = grounding_world()
        self.assertIsNone(motion_actions.check_numeric_grounding(
            w, "E", "Third, I back settling a quarter of inherited bills only once forces' pay is confirmed and "
                    "reserves stay above 70M"))


if __name__ == "__main__":
    unittest.main()
