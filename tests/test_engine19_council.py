"""Engine 19, the council's month: repairs and deferrals, conditional votes, resignations, leaks and formation.

Each test class is one finding of docs/AUDIT_ENGINE18.md, named by its ID. The seats are the engine's own
scripted stand-ins (karamaniya/backends/scripted.py), so nothing here calls a model.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import foreign, intelligence, motion_actions as ma, standing  # noqa: E402
from karamaniya.backends import CallResult  # noqa: E402
from karamaniya.backends.scripted import ScriptedBackend  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.council import Council, _rejected_last_month  # noqa: E402
from karamaniya.runner import _seats  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTED = os.path.join(ROOT, "council.scripted.toml")

# A motion whose words ("from 10% to 12%") and value (0.20) describe different acts: it is held back.
CONFLICTED = {"type": "set_policy", "subject": "tax", "value": "0.20",
              "text": "Raise the tax rate from 10% to 12% on high incomes."}


def seat_backend(on_answer):
    """A scripted seat. Each answer goes through on_answer(context, res) before the engine reads it."""
    class Seat(ScriptedBackend):
        def call(self, system, user, schema, context):
            res = super().call(system, user, schema, context)
            on_answer(context, res)
            return res
    return Seat


def scripted_council(tmp, backend_cls, months=4, seed=1):
    """A Council with scripted seats and formation done, ready for run_month()."""
    cfg = load_config(SCRIPTED)
    cfg = {**cfg, "run": {**cfg["run"], "tokens": {}, "foreign_cabinets": False, "seed": seed}}
    cfg = normalize_config({"run": cfg["run"], "seat": cfg["seats"]})
    mapping = {letter: seat["label"] for letter, seat in zip("ABCDE", cfg["seats"])}
    cfg["mapping"] = mapping
    w = new_world(cfg["run"]["seed"], months, member_ids=list(mapping),
                  founding_scenario=cfg["run"].get("founding_scenario", "random"),
                  founding_severity=cfg["run"].get("founding_severity", "default"))
    seats = _seats(cfg, mapping)
    for seat in seats.values():
        seat.backend = backend_cls(seat.cfg)
    os.makedirs(tmp, exist_ok=True)
    council = Council(w, seats, cfg["run"], RunStore(os.path.join(tmp, "r")))
    council.store.save_config(cfg)
    (council.store.path / "system_prompt.txt").write_text(council.system, encoding="utf-8")
    council.survey()
    council.diagnose_founding()
    council.form_government()
    return council, w


class RepairAnswerMalformed(unittest.TestCase):
    """Audit CO2 (high): a malformed motion-repair answer ended the run at council.py:1913 and :1958."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="engine19-council-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def repair_seat(motions_value):
        """Delegate A's conflicting motion goes back for repair, and its repair answer carries motions_value."""
        def on_answer(context, res):
            phase, mid = context.get("phase"), context.get("member")
            if phase == "motion_repair":
                res.data = {"motions": motions_value}
                return
            w = context.get("world")
            if w is None or w.month != 1 or not isinstance(res.data, dict):
                return
            if phase == "session":
                res.data["agenda_priorities"] = []
                res.data["motions"] = [dict(CONFLICTED)] if mid == "A" else []
            if phase == "decision":
                motions = context.get("motions") or []
                res.data["votes"] = {m["id"]: "yes" for m in motions}
                res.data["vote_reasons"] = {m["id"]: "yes" for m in motions}
                res.data["vote_conditions"] = []
        return seat_backend(on_answer)

    def test_a_repair_answer_whose_motions_is_not_a_list_refuses_the_motion(self):
        for case, motions_value in enumerate((3.5, ["a stray string", 2])):
            with self.subTest(motions=motions_value):
                council, _ = scripted_council(os.path.join(self.tmp, f"case{case}"),
                                              self.repair_seat(motions_value))
                council.run_month()
                record = council.run_month()
                refused = [r for r in record["rejected_motions"] if r.get("member") == "A"]
                self.assertEqual([r["reason_code"] for r in refused], ["MOTION_ACTION_MISMATCH_UNREPAIRED"])
                self.assertEqual(record["motions"], [], "a motion that was not repaired must not reach the vote")

    def test_a_structured_action_repair_answer_that_is_not_a_list_is_no_repair(self):
        council, _ = scripted_council(os.path.join(self.tmp, "structured"), self.repair_seat(3.5))
        motion = {"type": "diplomacy", "subject": "trade_deal", "value": "", "text": "Trade deal.", "proposer": "A"}
        repaired, problems = council._repair_structured_action(
            "A", motion, {"reason_code": "NO_STRUCTURED_ACTION", "explanation": "no action"}, [])
        self.assertIsNone(repaired)
        self.assertEqual(problems, ["the model returned no corrected motion"])


PROTEST = ("Formal diplomatic protest to the Solvaran Union demanding cessation of unauthorized inspections of "
           "Karamanian merchant vessels.")
STATUS = "Open talks on Karamaniya's status with the Solvaran Union. No federation is agreed."
# Two motions held back in one month: both are filed as trade deals with the Maritime League.
MISFILED_PROTEST = {"type": "diplomacy", "subject": "trade_deal", "value": "", "text": PROTEST,
                    "action": {"action_type": "trade_deal", "target": "Maritime League"}}
MISFILED_TALKS = {"type": "diplomacy", "subject": "trade_deal", "value": "", "text": STATUS,
                  "action": {"action_type": "trade_deal", "target": "Maritime League"}}
# What the delegate sends back for the talks: the same words, filed as the status talks they are.
TALKS_REPAIR = {"type": "diplomacy", "subject": "status_talks", "value": "", "text": STATUS,
                "action": {"action_type": "status_talks", "target": "Solvaran Union"}}


class Reply:
    def __init__(self, data):
        self.data, self.error, self.raw, self.served_model = data, "", "{}", "stub"


def repair_round(reply, misfiled):
    """Delegate A's held-back motions go through _repair_motions once; `reply` is its one answer."""
    w = new_world(11, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.agent_architecture_version = 2
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    items = []
    for raw in misfiled:
        candidate = {**raw, "proposer": "A"}
        items.append({"member": "A", "motion": candidate, "conflict": ma.conflict(w, candidate)})
    council = Council.__new__(Council)
    council.w = w
    council._call = lambda *a, **k: reply
    council._call_summary = lambda *a, **k: {}
    council._emit = lambda **k: None
    tabled, rejected, calls = [], [], []
    council._repair_motions("A", items, tabled, set(), rejected, calls)
    return tabled, rejected


class RepairPairedById(unittest.TestCase):
    """Audit MO13 (medium): a repair reply was paired with the held-back motions by position."""

    def test_a_reply_answers_the_motion_whose_id_it_carries(self):
        tabled, rejected = repair_round(Reply({"motions": [{**TALKS_REPAIR, "id": "R2"}]}),
                                        [MISFILED_PROTEST, MISFILED_TALKS])
        self.assertEqual([(r["reason_code"], r["motion"]["text"]) for r in rejected],
                         [("MOTION_ACTION_MISMATCH_UNREPAIRED", PROTEST)])
        self.assertEqual([t["subject"] for t in tabled], ["status_talks"])
        self.assertEqual(tabled[0]["text"], STATUS)
        self.assertNotIn("original_text", tabled[0], "the talks repair must not carry the protest's wording")

    def test_an_unlabelled_reply_answers_nothing_when_two_motions_were_held(self):
        tabled, rejected = repair_round(Reply({"motions": [TALKS_REPAIR]}), [MISFILED_PROTEST, MISFILED_TALKS])
        self.assertEqual(tabled, [])
        self.assertEqual([(r["reason_code"], r["motion"]["text"]) for r in rejected],
                         [("MOTION_ACTION_MISMATCH_UNREPAIRED", PROTEST),
                          ("MOTION_ACTION_MISMATCH_UNREPAIRED", STATUS)])

    def test_an_unlabelled_reply_answers_the_only_motion_held_back(self):
        tabled, rejected = repair_round(Reply({"motions": [TALKS_REPAIR]}), [MISFILED_TALKS])
        self.assertEqual(rejected, [])
        self.assertEqual([t["subject"] for t in tabled], ["status_talks"])


class RepairRefusalShown(unittest.TestCase):
    """Audit MO14 (medium): a refusal from the repair path was never shown to its author the next month."""

    def test_a_motion_refused_on_the_repair_path_is_shown_to_its_author_next_month(self):
        tabled, rejected = repair_round(Reply(None), [MISFILED_PROTEST])
        self.assertEqual(tabled, [])
        self.assertIsInstance(rejected[0]["motion"], dict)
        section = _rejected_last_month({"rejected_motions": rejected}, "A")
        self.assertEqual(len(section), 1)
        # Engine 29 (backlog T177): the reason in words; the code stays in the record.
        self.assertIn("diplomacy trade_deal: no corrected motion was returned", section[0].text)
        self.assertNotIn("MOTION_ACTION_MISMATCH_UNREPAIRED", section[0].text)
        self.assertEqual(rejected[0]["reason_code"], "MOTION_ACTION_MISMATCH_UNREPAIRED")

    def test_a_repair_that_still_contradicts_itself_keeps_its_motion_and_its_reasons(self):
        tabled, rejected = repair_round(Reply({"motions": [{**MISFILED_PROTEST, "id": "R1"}]}), [MISFILED_PROTEST])
        self.assertEqual(tabled, [])
        self.assertEqual(rejected[0]["reason_code"], "MOTION_ACTION_MISMATCH_AFTER_REPAIR")
        self.assertEqual(rejected[0]["motion"]["text"], PROTEST)
        self.assertTrue(rejected[0]["reasons"])


WELFARE = {"type": "set_policy", "subject": "welfare", "value": "0.02", "text": "Raise welfare support for households."}
# A repaired motion whose lever does not exist: intake refuses it, and the repair must not let it through.
UNKNOWN_LEVER = {"type": "set_policy", "subject": "tax_rate_plus", "value": "0.12",
                 "text": "Raise the tax rate from 10% to 12% on high incomes."}


class RepairedMotionIntake(unittest.TestCase):
    """Audit CO5 (medium): a motion sent back for repair skipped deliberation.check, so an invalid motion took a
    vote and an agenda slot, lapsed, and pushed a valid motion off the agenda."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="engine19-council-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def seat_that_repairs_into_an_unknown_lever():
        def on_answer(context, res):
            phase, mid, w = context.get("phase"), context.get("member"), context.get("world")
            if phase == "motion_repair" and mid == "A":
                res.data = {"motions": [dict(UNKNOWN_LEVER)]}
                return
            if w is None or w.month != 1 or not isinstance(res.data, dict):
                return
            if phase == "session":
                res.data["agenda_priorities"] = []
                res.data["motions"] = ([dict(CONFLICTED)] if mid == "A"
                                       else [dict(WELFARE)] if mid == "B" else [])
            if phase == "decision":
                motions = context.get("motions") or []
                res.data["votes"] = {m["id"]: "yes" for m in motions}
                res.data["vote_reasons"] = {m["id"]: "yes" for m in motions}
                res.data["vote_conditions"] = []
        return seat_backend(on_answer)

    def test_a_repaired_motion_meets_the_intake_checks_before_it_is_tabled(self):
        council, w = scripted_council(os.path.join(self.tmp, "repair"), self.seat_that_repairs_into_an_unknown_lever())
        w.tuning = {"agenda": {"major_motions": 1, "fiscal_extra": 0, "emergency_extra": 0}}
        for mid, capital in (("A", 0.9), ("B", 0.5), ("C", 0.1), ("D", 0.1), ("E", 0.1)):
            standing.ensure(w, mid)["capital"] = capital
        council.run_month()
        record = council.run_month()
        self.assertEqual([m["subject"] for m in record["motions"]], ["welfare"],
                         "the invalid repaired motion must not be put to a vote")
        self.assertEqual([(r["member"], r["reason_code"]) for r in record["rejected_motions"]],
                         [("A", "UNKNOWN_LEVER")])
        self.assertEqual(record["deferred_motions"], [], "the valid motion must not lose its slot to it")


FROM_C = {"type": "set_policy", "subject": "welfare", "value": "0.02", "text": "Raise welfare support for households."}
DEFERRAL = {"type": "defer_motion", "subject": "welfare", "value": "Month 5",
            "text": "Hold the welfare question back until Month 5 while food figures are checked."}


def deferral_seat():
    """Month index 1: A defers the welfare question until Month 5, B tables a military budget, C tables welfare.
    Two substantive slots, so C's welfare motion is deferred for lack of time, and everyone votes yes."""
    def on_answer(context, res):
        phase, mid, w = context.get("phase"), context.get("member"), context.get("world")
        if w is None or w.month != 1 or not isinstance(res.data, dict):
            return
        if phase == "session":
            res.data["agenda_priorities"] = []
            res.data["motions"] = {
                "A": [dict(DEFERRAL)],
                "B": [{"type": "set_policy", "subject": "military", "value": "0.05",
                       "text": "Raise the military budget modestly."}],
                "C": [dict(FROM_C)],
            }.get(mid, [])
        if phase == "decision":
            motions = context.get("motions") or []
            res.data["votes"] = {m["id"]: "yes" for m in motions}
            res.data["vote_reasons"] = {m["id"]: "yes: a measured step for the country" for m in motions}
            res.data["vote_conditions"] = []
    return seat_backend(on_answer)


class NamedDeferral(unittest.TestCase):
    """Audit CO3 (medium): a deferral 'until Month N' was never applied, because the link was read before the
    deferral was written. Audit CO4 (medium): once it works, the next agenda rebuild drops the held motion."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="engine19-council-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def council_after_the_deferral(tmp):
        council, w = scripted_council(tmp, deferral_seat(), months=8)
        w.tuning = {"agenda": {"major_motions": 2, "fiscal_extra": 0, "emergency_extra": 0}}
        for mid, capital in (("A", 0.9), ("B", 0.6), ("C", 0.1), ("D", 0.5), ("E", 0.5)):
            standing.ensure(w, mid)["capital"] = capital
        council.run_month()          # month index 0
        council.run_month()          # month index 1: the deferral is voted
        return council, w

    @staticmethod
    def held(w):
        return [e for e in w.agenda["deferred"] if e.get("subject") == "welfare" and e.get("type") == "set_policy"]

    def test_the_month_a_deferral_names_is_set_on_the_held_motion(self):
        council, w = self.council_after_the_deferral(os.path.join(self.tmp, "link"))
        self.assertEqual([e.get("defer_until") for e in self.held(w)], [4])

    def test_a_held_motion_stays_on_the_agenda_until_its_month_and_returns_then(self):
        council, w = self.council_after_the_deferral(os.path.join(self.tmp, "keep"))
        for entry in self.held(w):
            entry["defer_until"] = 4      # the link set by hand, so only the agenda rebuild is under test
        for month_index in (2, 3):
            record = council.run_month()
            self.assertEqual([m for m in record["motions"] if m.get("subject") == "welfare"], [],
                             f"welfare must stay held in index {month_index}")
            self.assertEqual([e.get("defer_until") for e in self.held(w)], [4])
        record = council.run_month()      # index 4, Month 5
        back = [m for m in record["motions"] if m.get("subject") == "welfare" and m.get("carried_over")]
        self.assertEqual(len(back), 1, "the held question returns in the month the deferral named")


FARM = {"type": "set_policy", "subject": "farm_support", "value": "0.03", "text": "Increase farm support."}
WELFARE_BY_B = {"type": "set_policy", "subject": "welfare", "value": "0.02",
                "text": "Raise welfare support for households."}


def conditional_seat():
    """Month index 1. A proposes farm support and resigns in the same decision, so the motion lapses (its proposer
    is no longer in government). B proposes welfare, and C votes on it conditionally: yes if the farm motion passes.
    Welfare's yes votes are B, C (if its condition is met) and E: two without C, three with it."""
    def on_answer(context, res):
        phase, mid, w = context.get("phase"), context.get("member"), context.get("world")
        if w is None or w.month != 1 or not isinstance(res.data, dict):
            return
        if phase == "session":
            res.data["agenda_priorities"] = []
            res.data["motions"] = {"A": [dict(FARM)], "B": [dict(WELFARE_BY_B)]}.get(mid, [])
        if phase == "decision":
            motions = context.get("motions") or []
            farm = next((m["id"] for m in motions if m.get("subject") == "farm_support"), None)
            welfare = next((m["id"] for m in motions if m.get("subject") == "welfare"), None)
            if farm is None or welfare is None:
                return
            welfare_vote = {"A": "no", "B": "yes", "C": "conditional", "D": "no", "E": "yes"}[mid]
            res.data["votes"] = {farm: "yes", welfare: welfare_vote}
            res.data["vote_reasons"] = {farm: "Farm support first.", welfare: "Welfare support, as agreed."}
            res.data["vote_conditions"] = ([{"motion_id": welfare, "kind": "motion", "metric": "none",
                                             "operator": "none", "value": 0, "other_motion": farm,
                                             "other_outcome": "passes", "if_unmet": "no"}] if mid == "C" else [])
            res.data["resign"] = mid == "A"
    return seat_backend(on_answer)


class ConditionalOnALapsedMotion(unittest.TestCase):
    """Audit CO6 (medium): a conditional vote 'yes if X passes' counted as met when X won its vote and then lapsed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="engine19-council-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_condition_on_a_motion_that_lapsed_is_not_met(self):
        council, w = scripted_council(os.path.join(self.tmp, "lapsed"), conditional_seat())
        w.tuning = {"agenda": {"major_motions": 2, "fiscal_extra": 0, "emergency_extra": 0}}
        council.run_month()
        record = council.run_month()
        by_subject = {m["subject"]: m for m in record["motions"]}
        self.assertTrue(by_subject["farm_support"]["result"].startswith("lapsed"))
        welfare = by_subject["welfare"]
        self.assertEqual(welfare["conditional_votes"]["C"]["counted_as"], "no")
        self.assertFalse(welfare["passed"], "two yes votes of five; the lapsed motion does not make C's vote yes")


class ResignationKeepsTheVote(unittest.TestCase):
    """Audit CO8 (medium): a delegate who voted yes and resigned in the same decision lost the vote."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="engine19-council-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_yes_vote_cast_in_the_decision_counts_although_the_delegate_resigns(self):
        def on_answer(context, res):
            phase, mid, w = context.get("phase"), context.get("member"), context.get("world")
            if w is None or w.month != 1 or not isinstance(res.data, dict):
                return
            if phase == "session":
                res.data["agenda_priorities"] = []
                res.data["motions"] = [dict(WELFARE_BY_B)] if mid == "B" else []
            if phase == "decision":
                motions = context.get("motions") or []
                vote = {"A": "yes", "B": "yes", "C": "yes", "D": "no", "E": "no"}[mid]
                res.data["votes"] = {m["id"]: vote for m in motions}
                res.data["vote_reasons"] = {m["id"]: vote for m in motions}
                res.data["vote_conditions"] = []
                res.data["resign"] = mid == "A"
        council, w = scripted_council(os.path.join(self.tmp, "resign"), seat_backend(on_answer))
        w.tuning = {"agenda": {"fiscal_extra": 0, "emergency_extra": 0}}
        council.run_month()
        record = council.run_month()
        self.assertEqual(record["resigned"], ["A"])
        motion = record["motions"][0]
        self.assertEqual(motion["submitted_votes"]["A"], "yes")
        self.assertEqual(motion["votes"].get("A"), "yes", "A voted while it was in government, so the vote counts")
        self.assertEqual(motion["tally"], "(3 yes, 2 no, 0 abstain)")
        self.assertTrue(motion["passed"], "three of five voted yes")


class DecisionTally(unittest.TestCase):
    """The count a decision is decided by. Over the live roster it must be politics.passes, for every rule."""

    def test_over_the_live_roster_it_is_politics_passes_under_every_rule(self):
        from itertools import product
        from karamaniya import deliberation, politics
        w = new_world(3, 6, member_ids=list("ABCDE"))
        for rule, head in product(("majority", "two_thirds", "unanimity", "head_decides"), (None, "A", "C")):
            w.const.decision_rule = rule
            w.const.offices["head"] = head
            for choice in product(("yes", "no", "abstain"), repeat=5):
                votes = dict(zip("ABCDE", choice))
                with self.subTest(rule=rule, head=head, votes=choice):
                    self.assertEqual(deliberation.decision_passes(w, votes, list("ABCDE"), head),
                                     politics.passes(w, votes))


class WithheldReportsCanLeak(unittest.TestCase):
    """Audit IN-M2 (medium): the leak check ran before the month's withheld reports were flagged, so a withheld
    report could never leak (72 flagged and none leaked in a 36-month run)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="engine19-council-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_withheld_reports_are_flagged_before_the_leak_check_runs(self):
        council, _ = scripted_council(os.path.join(self.tmp, "order"), seat_backend(lambda context, res: None))
        order = []
        flag, leak_check = intelligence.flag_withheld, intelligence.leaks

        def flagged(w):
            order.append("flag")
            return flag(w)

        def checked(*args, **kwargs):
            order.append("leaks")
            return leak_check(*args, **kwargs)

        with mock.patch.object(intelligence, "flag_withheld", flagged), \
                mock.patch.object(intelligence, "leaks", checked):
            council.run_month()
        self.assertEqual(order[:2], ["flag", "leaks"])


class AuditLogsApproval(unittest.TestCase):
    """Audit CO12 (low): the execution audit logged approval as null for every executed motion, because it read the
    approval from a world snapshot that has no such key."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="engine19-council-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_an_executed_motion_logs_the_approval_it_was_passed_under(self):
        council, _ = scripted_council(os.path.join(self.tmp, "audit"), seat_backend(lambda context, res: None))
        executed = []
        for _ in range(6):
            record = council.run_month()
            executed += [m for m in record["motions"] if m.get("execution_status") == "EXECUTED"]
        self.assertTrue(executed, "the scripted seats pass motions, so there is an audit to read")
        for motion in executed:
            with self.subTest(motion=motion["id"]):
                self.assertIsInstance(motion["world_state_before"]["approval"], float)
                self.assertIsInstance(motion["world_state_after"]["approval"], float)


def declining_repair_seat():
    """Delegate A proposes a slate with holes. Its one repair comes back empty: declined, with no data."""
    class Seat(ScriptedBackend):
        def call(self, system, user, schema, context):
            if context.get("phase") == "formation_proposal" and context.get("member") == "A":
                if context.get("repair"):
                    return CallResult(data=None, raw="(declined)", served_model="scripted", refusal=True)
                return CallResult(data={"statement": "I propose B for head and myself for treasury.",
                                        "nominations": [],
                                        "slate": {"head": "B", "treasury": "A", "interior": "", "army": "", "navy": ""}},
                                  raw="(first)", served_model="scripted")
            return super().call(system, user, schema, context)
    return Seat


class FormationRepairUnanswered(unittest.TestCase):
    """Audit CO13 (low): a government-formation repair that returned nothing was logged as 'repaired', and its
    proposal went on as if it had been corrected."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="engine19-council-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_repair_that_returns_nothing_leaves_the_proposal_unreadable_and_excluded(self):
        _, w = scripted_council(os.path.join(self.tmp, "formation"), declining_repair_seat())
        formation = w.founding["formation"]
        proposal = formation["proposals"]["A"]
        self.assertEqual(proposal["status"], "unreadable")
        self.assertTrue(proposal["repair"]["attempted"], "the attempt stays in the record")
        self.assertTrue(proposal["repair"]["refused"])
        self.assertEqual([m for m in formation["motions"] if m["proposer"] == "A"], [])


if __name__ == "__main__":
    unittest.main()
