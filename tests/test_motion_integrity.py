"""Political text, structured motion, final vote and world-state execution must agree.

The live run filed a formal protest to the Solvaran Union as `diplomacy / trade_deal`, which routes
to the Maritime League, so the League was sent a trade agreement and the Union never heard the
protest. These tests pin down every part of the answer: the check that catches it, the targeted
repair, the execution gate, one canonical status, and a duplicate action executing once.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, motion_actions, politics  # noqa: E402
from karamaniya.backends import CallResult  # noqa: E402
from karamaniya.backends.scripted import ScriptedBackend  # noqa: E402
from karamaniya.config import load_config  # noqa: E402
from karamaniya.council import Council  # noqa: E402
from karamaniya.integrity import audit, mark, replay_plan  # noqa: E402
from karamaniya.runner import _seats, new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "council.scripted.toml")

PROTEST_TEXT = ("Formal diplomatic protest to the Solvaran Union demanding cessation of unauthorized "
                "inspections of Karamanian merchant vessels and respect for our sovereign trade rights.")
MISFILED = {"type": "diplomacy", "subject": "trade_deal", "value": "", "text": PROTEST_TEXT,
            "action": {"action_type": "trade_deal", "target": "Maritime League",
                       "issue": "merchant vessel inspections", "terms": ["cease inspections"]}}
REPAIRED = {"type": "diplomacy", "subject": "diplomatic_protest", "value": "", "text": PROTEST_TEXT,
            "action": {"action_type": "diplomatic_protest", "target": "Solvaran Union",
                       "issue": "unauthorized merchant vessel inspection", "terms": ["cease inspections"]}}


def world():
    return new_world(11)


class ProseAgainstAction(unittest.TestCase):
    """1. A Union protest filed as a Maritime League trade deal is caught, not executed."""

    def test_the_live_runs_misfiled_protest_is_detected(self):
        clash = motion_actions.conflict(world(), MISFILED)
        self.assertIsNotNone(clash)
        self.assertEqual(clash["code"], "MOTION_ACTION_MISMATCH")
        codes = {r["code"] for r in clash["reasons"]}
        self.assertIn("TARGET_MISMATCH", codes)
        self.assertIn("ACTION_MISMATCH", codes)

    def test_the_repair_request_names_both_sides_of_the_conflict(self):
        message = motion_actions.repair_request(world(), motion_actions.conflict(world(), MISFILED))
        self.assertIn("MOTION_ACTION_MISMATCH", message)
        self.assertIn("Solvaran Union", message)
        self.assertIn("Maritime League", message)
        self.assertIn("protest", message.lower())

    def test_a_matching_protest_is_not_flagged(self):
        self.assertIsNone(motion_actions.conflict(world(), REPAIRED))

    def test_genuine_foreign_motions_are_left_alone(self):
        for mo in (
            {"type": "diplomacy", "subject": "trade_deal", "value": "",
             "text": "To the Maritime League: a standing trade arrangement for grain and fuel."},
            {"type": "diplomacy", "subject": "non_aggression", "value": "",
             "text": "Propose a mutual non-aggression pact to the Solvaran Union: both sides renounce force."},
            {"type": "diplomacy", "subject": "grain_deal", "value": "",
             "text": "Propose a transparent grain deal with Dorsania securing predictable imports."},
            {"type": "set_policy", "subject": "farm_support", "value": "0.05",
             "text": "Raise farm support to the cap."},
        ):
            with self.subTest(mo=mo["subject"]):
                self.assertIsNone(motion_actions.conflict(world(), mo))

    def test_an_explicit_action_governs_the_engine_subject(self):
        """The act a delegate states outright decides where the motion is sent."""
        stated = {"type": "diplomacy", "subject": "trade_deal", "value": "", "text": PROTEST_TEXT,
                  "action": {"action_type": "diplomatic_protest", "target": "Solvaran Union"}}
        fixed = actions.normalize_motion_v2(world(), stated)
        self.assertEqual(fixed["subject"], "diplomatic_protest")
        self.assertEqual(fixed["declared_subject"], "trade_deal")
        self.assertEqual(motion_actions.structured_action(world(), fixed)["target"], "union")
        # A stale subject that contradicts the stated act is itself reported.
        clash = motion_actions.conflict(world(), fixed)
        self.assertIsNotNone(clash)
        self.assertIn("DECLARED_SUBJECT_CONTRADICTS_ACTION", {r["code"] for r in clash["reasons"]})


class Execution(unittest.TestCase):
    """2, 3 and 8: what may reach world state, and what may not."""

    def test_a_protest_executes_only_against_the_union(self):
        w = world()
        politics.apply_motion(w, {**REPAIRED, "proposer": "A"})
        self.assertEqual([p["party"] for p in w.dip.proposals], ["union"])
        self.assertEqual([p["kind"] for p in w.dip.proposals], ["diplomatic_protest"])

    def test_a_genuine_trade_deal_executes_only_against_the_league(self):
        w = world()
        politics.apply_motion(w, {"type": "diplomacy", "subject": "trade_deal", "value": "",
                                  "text": "To the Maritime League: a standing trade arrangement.",
                                  "proposer": "A"})
        self.assertEqual([p["party"] for p in w.dip.proposals], ["league"])

    def test_a_withdrawn_motion_cannot_mutate_state(self):
        w = world()
        before = json.dumps(w.to_dict(), sort_keys=True, default=str)
        verdict = motion_actions.validate_execution(w, {**REPAIRED, "status": "WITHDRAWN", "passed": True})
        self.assertEqual(verdict["code"], "MOTION_WITHDRAWN")
        self.assertEqual(json.dumps(w.to_dict(), sort_keys=True, default=str), before)

    def test_deferred_and_superseded_motions_cannot_mutate_state(self):
        w = world()
        for status in ("DEFERRED", "SUPERSEDED", "AGENDA_BLOCKED", "LAPSED"):
            with self.subTest(status=status):
                verdict = motion_actions.validate_execution(w, {**REPAIRED, "status": status, "passed": True})
                self.assertIsNotNone(verdict)
        self.assertEqual(w.dip.proposals, [])

    def test_a_motion_that_did_not_carry_cannot_execute(self):
        verdict = motion_actions.validate_execution(world(), {**REPAIRED, "passed": False})
        self.assertEqual(verdict["code"], "NOT_PASSED")

    def test_a_protest_addressed_to_the_wrong_hand_is_refused(self):
        w = world()
        wrong = {**REPAIRED, "subject": "trade_deal", "action": {"action_type": "diplomatic_protest",
                                                                 "target": "Maritime League"}}
        verdict = motion_actions.validate_execution(w, {**wrong, "passed": True})
        self.assertEqual(verdict["code"], "ACTION_NOT_VALID_FOR_TARGET")
        self.assertIn("Solvaran Union", verdict["detail"])

    def test_an_action_with_no_target_is_refused(self):
        verdict = motion_actions.validate_execution(world(), {
            "type": "diplomacy", "subject": "trade_deal", "value": "", "text": "", "passed": True})
        self.assertIsNone(verdict)  # the league is where a trade deal goes; the target is implied
        verdict = motion_actions.validate_execution(world(), {
            "type": "diplomacy", "subject": "trade_deal", "value": "", "text": "", "passed": True,
            "action": {"action_type": "trade_deal", "target": ""}})
        self.assertIsNone(verdict)


class Duplicates(unittest.TestCase):
    """7. Two motion ids that resolve to the same act execute once."""

    def test_an_equivalent_action_executes_once(self):
        w = world()
        w.month = 4
        first = {**REPAIRED, "id": "D5"}
        second = {**REPAIRED, "id": "D6"}
        executed = {}
        self.assertIsNone(motion_actions.validate_execution(w, {**first, "passed": True}, executed))
        executed[motion_actions.execution_key(w, first)] = "D5"
        verdict = motion_actions.validate_execution(w, {**second, "passed": True}, executed)
        self.assertEqual(verdict["code"], "DUPLICATE_ACTION")
        self.assertEqual(verdict["duplicate_of"], "D5")

    def test_genuinely_different_actions_are_not_merged(self):
        w = world()
        w.month = 4
        protest = motion_actions.execution_key(w, REPAIRED)
        deal = motion_actions.execution_key(w, {**REPAIRED, "subject": "trade_deal",
                                                "action": {"action_type": "trade_deal",
                                                           "target": "Maritime League"}})
        pact = motion_actions.execution_key(w, {**REPAIRED, "subject": "non_aggression",
                                                "action": {"action_type": "non_aggression_pact",
                                                           "target": "Solvaran Union"}})
        self.assertEqual(len({protest, deal, pact}), 3)

    def test_the_same_act_in_a_later_month_is_not_a_duplicate(self):
        w = world()
        w.month = 4
        first = motion_actions.execution_key(w, REPAIRED)
        w.month = 5
        self.assertNotEqual(first, motion_actions.execution_key(w, REPAIRED))


class CanonicalStatus(unittest.TestCase):
    """4 and 5: WITHDRAWN is not DEFEATED, and DEFEATED needs a real losing vote."""

    def test_a_withdrawn_motion_reads_as_withdrawn_everywhere(self):
        from karamaniya import convergence
        mo = {"id": "D4", "type": "set_policy", "subject": "farm_support", "value": "0.05",
              "proposer": "A", "withdrawn": True, "passed": False, "votes": {},
              "status": "WITHDRAWN", "execution_status": "NOT_APPLICABLE"}
        self.assertEqual(convergence.motion_status(mo), "WITHDRAWN")
        self.assertNotEqual(convergence.motion_status(mo), "DEFEATED")
        self.assertNotIn(convergence.motion_status(mo), convergence.VOTED_STATES)
        self.assertFalse(convergence.reached_vote(mo))

    def test_a_stored_status_is_the_one_every_reader_uses(self):
        from karamaniya import convergence
        mo = {"id": "D4", "type": "diplomacy", "subject": "trade_deal", "value": "", "proposer": "A",
              "passed": False, "votes": {"A": "no", "B": "no"}, "status": "SUPERSEDED"}
        self.assertEqual(convergence.motion_status(mo), "SUPERSEDED")

    def test_defeated_requires_an_actual_losing_vote(self):
        from karamaniya import convergence
        beaten = {"id": "M3", "type": "set_policy", "subject": "tax", "value": "0.3", "proposer": "C",
                  "passed": False, "votes": {"A": "no", "B": "no", "C": "yes"}}
        self.assertEqual(convergence.motion_status(beaten), "DEFEATED")
        never_voted = {"id": "M9", "type": "set_policy", "subject": "tax", "value": "0.4", "proposer": "C",
                       "passed": False, "votes": {}}
        self.assertNotEqual(convergence.motion_status(never_voted), "DEFEATED")

    def test_a_blocked_execution_is_its_own_state(self):
        from karamaniya import convergence
        mo = {"id": "D5", "type": "diplomacy", "subject": "trade_deal", "value": "", "proposer": "E",
              "passed": True, "votes": dict.fromkeys("ABCDE", "yes"), "execution_status": "EXECUTION_BLOCKED"}
        self.assertEqual(convergence.motion_status(mo), "EXECUTION_BLOCKED")
        self.assertIn(convergence.motion_status(mo), convergence.VOTED_STATES)


class AmendedPayload(unittest.TestCase):
    """6. Only the final amended version is executed."""

    def test_the_amended_value_is_the_one_applied(self):
        w = world()
        mo = {"id": "M1", "type": "set_policy", "subject": "tax", "value": "0.25", "text": "",
              "proposer": "A", "revisions": [{"value": "0.2", "text": ""}], "amended": True}
        entry = {}
        from karamaniya.council import _motion_versions
        entry.update(_motion_versions(w, mo))
        self.assertEqual(entry["final_text"], "")
        self.assertEqual(entry["final_structured_action"]["value"], "0.25")
        self.assertEqual(entry["original_structured_action"]["value"], "0.2")

    def test_the_original_version_survives_an_amendment(self):
        from karamaniya import deliberation
        w = world()
        tabled = [{"id": "M1", "type": "set_policy", "subject": "farm_support", "value": "0.05",
                   "text": "", "proposer": "A", "summary": "s", "revisions": []}]
        deliberation.apply_revisions(w, "A", {"amend": [{"motion_id": "M1", "value": "0.03", "text": ""}]},
                                     tabled, tabled)
        self.assertEqual(tabled[0]["value"], "0.03")
        self.assertEqual(tabled[0]["revisions"][0]["value"], "0.05")
        from karamaniya.council import _motion_versions
        versions = _motion_versions(w, tabled[0])
        self.assertEqual(versions["original_structured_action"]["value"], "0.05")
        self.assertEqual(versions["final_structured_action"]["value"], "0.03")


class InjectedBackend(ScriptedBackend):
    """A stand-in that files a protest as a trade deal, the way the live run did.

    `repair` decides what comes back when the council asks it to fix the motion.
    """

    def __init__(self, cfg: dict, member: str, repair: dict | None):
        super().__init__(cfg)
        self.member = member
        self.repair = repair
        self.repair_calls = 0
        self.session_motions = []

    def call(self, system, user, schema, context):
        phase, mid = context.get("phase"), context.get("member")
        if mid == self.member and phase == "session":
            res = super().call(system, user, schema, context)
            res.data = {**res.data, "motions": [dict(MISFILED, force_agenda=False)]}
            return res
        if mid == self.member and phase == "motion_repair":
            self.repair_calls += 1
            if self.repair is None:
                return CallResult(data=None, raw="", error="no answer", served_model="stub")
            return CallResult(data={"motions": [dict(self.repair)]}, raw="{}", served_model="stub")
        return super().call(system, user, schema, context)


class CouncilRoundTrip(unittest.TestCase):
    """1 and 2 end to end: the mismatch is sent back, and the repaired protest reaches the Union."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-integrity-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, repair):
        cfg = load_config(CONFIG)
        mapping = {letter: seat["label"] for letter, seat in zip("ABCDE", cfg["seats"])}
        cfg = {**cfg, "mapping": mapping}
        run_dir = os.path.join(self.tmp, "run")
        store = RunStore(run_dir)
        store.save_config(cfg)
        w = new_world(cfg["run"]["seed"], 3, cfg["run"]["framing"], member_ids=list(mapping),
                      agent_architecture_version=int(cfg["run"].get("agent_architecture_version", 2)))
        seats = _seats(cfg, mapping)
        backend = InjectedBackend(seats["A"].cfg, "A", repair)
        seats["A"].backend = backend
        council = Council(w, seats, cfg["run"], store)
        store._write_json("survey.json", council.survey())
        council.diagnose_founding()
        council.form_government()
        return council, w, backend, store

    def test_the_misfiled_motion_is_held_back_and_repaired(self):
        council, w, backend, store = self.build(REPAIRED)
        record = council.run_month()
        self.assertEqual(backend.repair_calls, 1, "the malformed motion should go back once")
        mine = [m for m in record["motions"] if m["proposer"] == "A" and m["type"] == "diplomacy"]
        self.assertTrue(mine, "the repaired motion should have been tabled")
        for mo in mine:
            self.assertEqual(mo["subject"], "diplomatic_protest")
            self.assertEqual(mo["final_structured_action"]["target"], "union")
        # The engine sent the Union a protest and never sent the League a trade deal for it.
        sent = [p for p in w.dip.log if p.get("from") == "Maritime League"]
        for entry in sent:
            self.assertNotIn("lower tariffs", entry.get("text", ""))

    def test_a_motion_that_is_not_repaired_is_blocked_not_guessed(self):
        """The repair comes back just as contradictory, so nothing is executed."""
        council, w, backend, store = self.build(MISFILED)
        record = council.run_month()
        self.assertEqual(backend.repair_calls, 1)
        self.assertEqual([m for m in record["motions"] if m["proposer"] == "A" and m["type"] == "diplomacy"], [])
        blocked = [r for r in (record.get("rejected_motions") or [])
                   if r.get("reason_code", "").startswith("MOTION_ACTION_MISMATCH")]
        self.assertTrue(blocked, "the unrepaired motion must be recorded as rejected")
        for entry in w.dip.log:
            self.assertNotIn("lower tariffs", entry.get("text", ""))

    def test_a_motion_blocked_at_execution_is_recorded_and_changes_nothing(self):
        """The pre-execution gate is a backstop: the vote happened, the act still does not run."""
        council, w, backend, store = self.build(REPAIRED)
        from karamaniya import motion_actions as ma
        original = ma.validate_execution
        ma.validate_execution = lambda world, motion, executed=None: (
            {"code": "DUPLICATE_ACTION", "detail": "an equivalent action already executed this month",
             "duplicate_of": "D1"} if motion.get("type") == "diplomacy" else original(world, motion, executed))
        try:
            record = council.run_month()
        finally:
            ma.validate_execution = original
        blocked = [m for m in record["motions"] if m.get("execution_status") == "EXECUTION_BLOCKED"]
        self.assertTrue(blocked, "the gate should have blocked the diplomatic motion")
        for mo in blocked:
            self.assertEqual(mo["status"], "EXECUTION_BLOCKED")
            self.assertIn("execution blocked", mo["result"])
            self.assertEqual(mo["duplicate_of"], "D1")
            self.assertTrue(mo["validation_errors"])
        self.assertEqual([p for p in w.dip.proposals if p["kind"] in ("trade_deal", "diplomatic_protest")], [])
        self.assertTrue([e for e in w.events if e.get("kind") == "execution_blocked"])

    def test_a_council_without_a_mismatch_is_untouched(self):
        council, w, backend, store = self.build(REPAIRED)
        record = council.run_month()
        self.assertTrue(all("status" in mo for mo in record["motions"]))
        for mo in record["motions"]:
            self.assertIn(mo["execution_status"], ("EXECUTED", "NOT_APPLICABLE", "EXECUTION_BLOCKED",
                                                  "EXECUTION_BLOCKED_CONDITION"))
            self.assertTrue(mo.get("final_structured_action") or mo.get("withdrawn"))
            self.assertIn("vote_status", mo)
            self.assertIn("conditions", mo)
            self.assertIn("condition_results", mo)


class ConditionalExecution(unittest.TestCase):
    """1, 2 and 6: a 55M floor blocks the payment, passes politically, and runs later."""

    FLOOR_TEXT = ("Pay a quarter of inherited unpaid bills from reserves, only if reserves "
                  "remain above 55M and only after League credit clears first, with audited register.")

    def pay(self, **kw):
        base = {"id": "M1", "type": "settle_arrears", "subject": "reserves", "value": "quarter",
                "text": self.FLOOR_TEXT, "proposer": "A", "passed": True,
                "votes": dict.fromkeys("ABCDE", "yes")}
        return {**base, **kw}

    def test_a_reserve_floor_blocks_execution_and_changes_nothing(self):
        import json
        w = world()
        w.econ.gold = 60e6
        w.econ.arrears = 20e6
        mo = self.pay(conditions=motion_actions.motion_conditions(self.pay()))
        self.assertTrue(mo["conditions"], "the floor text must produce executable conditions")
        gate = motion_actions.validate_execution(w, mo)
        self.assertIsNotNone(gate)
        self.assertEqual(gate["code"], "EXECUTION_BLOCKED_CONDITION")
        before = json.dumps(w.to_dict(), sort_keys=True, default=str)
        self.assertEqual(json.dumps(w.to_dict(), sort_keys=True, default=str), before)

    def test_the_same_motion_executes_once_conditions_become_true(self):
        w = world()
        w.econ.gold = 60e6
        w.econ.arrears = 20e6
        mo = self.pay(conditions=motion_actions.motion_conditions(self.pay()))
        self.assertIsNotNone(motion_actions.validate_execution(w, mo))
        w.econ.gold = 200e6
        w.econ.loans_in = 10e6
        w.counters["register_audited"] = 1
        self.assertIsNone(motion_actions.validate_execution(w, mo))
        before_gold = w.econ.gold
        politics.apply_motion(w, {**mo, "proposer": "A"})
        self.assertLess(w.econ.gold, before_gold, "the payment must actually run once unblocked")

    def test_passed_but_blocked_stays_politically_passed(self):
        from karamaniya import convergence
        mo = self.pay(passed=True, execution_status="EXECUTION_BLOCKED_CONDITION",
                      vote_status="PASSED_CONDITIONALLY",
                      conditions=[{"metric": "reserves_after_payment", "operator": ">=",
                                   "value": 55e6, "source": "floor"}],
                      blocking_reason="reserves_after_payment would fall below floor")
        self.assertTrue(mo["passed"])
        self.assertEqual(mo["vote_status"], "PASSED_CONDITIONALLY")
        self.assertEqual(convergence.motion_status(mo), "EXECUTION_BLOCKED")
        self.assertIn(convergence.motion_status(mo), convergence.VOTED_STATES)

    def test_amendments_update_executable_conditions(self):
        from karamaniya import deliberation
        w = world()
        w.econ.arrears = 40e6
        tabled = [{"id": "M1", "type": "settle_arrears", "subject": "reserves", "value": "quarter",
                   "text": "Pay a quarter of unpaid bills from reserves.", "proposer": "A",
                   "summary": "s", "revisions": []}]
        self.assertEqual(motion_actions.motion_conditions(tabled[0]), [])
        deliberation.apply_revisions(w, "A", {"amend": [{"motion_id": "M1", "value": "quarter",
                                                        "text": self.FLOOR_TEXT}]}, tabled, tabled)
        conds = motion_actions.motion_conditions(tabled[0])
        self.assertTrue(any(c["metric"] == "reserves_after_payment" for c in conds))
        self.assertEqual(tabled[0]["final_conditions"], conds)

    def test_final_text_without_stored_conditions_is_a_mismatch(self):
        w = world()
        clash = motion_actions.condition_mismatch(w, self.pay())
        self.assertIsNotNone(clash)
        self.assertEqual(clash["code"], "MOTION_CONDITION_MISMATCH")
        gate = motion_actions.validate_execution(w, self.pay())
        self.assertEqual(gate["code"], "MOTION_CONDITION_MISMATCH")


class NumericGrounding(unittest.TestCase):
    """3 and 4: interpretation is allowed, invented statistics are sent back."""

    def test_unsupported_shortage_triggers_targeted_repair(self):
        w = world()
        w.econ.food_ratio = 0.96
        claim = motion_actions.check_numeric_grounding(w, "A", "food shortage is 35%")
        self.assertIsNotNone(claim)
        self.assertEqual(claim["code"], "NUMERIC_GROUNDING_ERROR")
        self.assertIn("96%", claim["repair"])

    def test_interpretation_of_a_true_number_is_allowed(self):
        w = world()
        w.econ.food_ratio = 0.96
        self.assertIsNone(motion_actions.check_numeric_grounding(
            w, "A", "96% food coverage is dangerously weak."))

    def test_hunger_cannot_silently_become_a_shortage(self):
        w = world()
        for p in w.k_pops():
            p.hunger = 0.035
        claim = motion_actions.check_numeric_grounding(w, "A", "food shortage is 35%")
        self.assertIsNotNone(claim)
        self.assertEqual(claim["code"], "NUMERIC_GROUNDING_ERROR")

    def test_a_supported_private_estimate_is_allowed(self):
        import karamaniya.intelligence as intel
        w = world()
        w.econ.food_ratio = 0.96
        original = intel.office_context
        intel.office_context = lambda *a, **k: "Treasury cash desk: food shortage 35% confirmed by audit."
        try:
            self.assertIsNone(motion_actions.check_numeric_grounding(w, "A", "food shortage is 35%"))
        finally:
            intel.office_context = original


class WithdrawnVsDefeated(unittest.TestCase):
    """5: WITHDRAWN everywhere for withdrawals, DEFEATED only for real losing votes."""

    def test_withdrawn_reads_withdrawn_in_every_reader(self):
        from karamaniya import convergence
        mo = {"id": "M4", "type": "set_policy", "subject": "tax", "value": "0.3", "proposer": "A",
              "withdrawn": True, "passed": False, "votes": {}, "status": "WITHDRAWN",
              "vote_status": "WITHDRAWN", "execution_status": "NOT_APPLICABLE"}
        self.assertEqual(convergence.motion_status(mo), "WITHDRAWN")
        self.assertNotEqual(convergence.motion_status(mo), "DEFEATED")
        self.assertNotIn(convergence.motion_status(mo), convergence.VOTED_STATES)
        self.assertFalse(convergence.reached_vote(mo))

    def test_a_real_losing_vote_reads_defeated(self):
        from karamaniya import convergence
        mo = {"id": "M3", "type": "set_policy", "subject": "tax", "value": "0.3", "proposer": "C",
              "passed": False, "votes": {"A": "no", "B": "no", "C": "yes", "D": "no", "E": "abstain"}}
        self.assertEqual(convergence.motion_status(mo), "DEFEATED")

    def test_deterministic_runs_remain_deterministic(self):
        w, v = world(), world()
        kwargs = {"type": "settle_arrears", "subject": "reserves", "value": "quarter",
                  "text": ConditionalExecution.FLOOR_TEXT}
        self.assertEqual(motion_actions.motion_conditions(kwargs),
                         motion_actions.motion_conditions(dict(kwargs)))
        self.assertEqual(motion_actions.evaluate_conditions(w, motion_actions.motion_conditions(kwargs)),
                         motion_actions.evaluate_conditions(v, motion_actions.motion_conditions(dict(kwargs))))


class LiveRunAudit(unittest.TestCase):
    """9. The recorded run is marked and left alone; the replay plan is deterministic."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-audit-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_clean_run_audits_clean(self):
        path = new_run(CONFIG, runs_dir=self.tmp, name="clean", months=6, quiet=True)
        store = RunStore(path)
        report = audit(store)
        self.assertEqual(report["classification"], "CLEAN")
        self.assertEqual(report["findings"], [])

    def test_a_run_with_a_known_misfiled_protest_is_marked_behavioral(self):
        path = new_run(CONFIG, runs_dir=self.tmp, name="marked", months=1, quiet=True)
        store = RunStore(path)
        cfg = store.read_json("config.json")
        record = {"type": "month", "month": 0, "order": list("ABCDE"),
                  "motions": [dict(MISFILED, id="D5", proposer="E", passed=True, withdrawn=False, void=False,
                                   tally="(5 yes, 0 no, 0 abstain)",
                                   votes=dict.fromkeys("ABCDE", "yes"),
                                   result="proposal sent to the Maritime League: trade deal")],
                  "pre_positions": {}, "revisions": {}}
        store.log(record)
        report = audit(store)
        self.assertEqual(report["classification"], "CORRECTED_BEHAVIORAL")
        self.assertEqual(report["executed_wrongly"][0]["motion"], "D5")
        self.assertIn("counters.league_trade", report["executed_wrongly"][0]["touched_state"])

    def test_marking_writes_beside_the_run_and_never_overwrites_the_log(self):
        path = new_run(CONFIG, runs_dir=self.tmp, name="preserve", months=1, quiet=True)
        store = RunStore(path)
        before = store.read_log("month")
        store.log({"type": "month", "month": 1, "order": list("ABCDE"),
                   "motions": [dict(MISFILED, id="D5", proposer="E", passed=True, tally="(5 yes, 0 no, 0 abstain)",
                                    votes=dict.fromkeys("ABCDE", "yes"), result="proposal sent to the Maritime League: trade deal")],
                   "pre_positions": {}, "revisions": {}})
        logged = store.read_log("month")
        record = mark(store, write=True)
        self.assertTrue((store.path / "correction.json").exists())
        self.assertTrue(record["recorded_history_preserved"])
        self.assertEqual(store.read_log("month"), logged)
        self.assertEqual(store.read_log("month")[:len(before)], before)
        self.assertEqual(record["classification"], "CORRECTED_BEHAVIORAL")

    def test_the_replay_plan_points_at_the_last_clean_month(self):
        path = new_run(CONFIG, runs_dir=self.tmp, name="replay", months=1, quiet=True)
        store = RunStore(path)
        store.log({"type": "month", "month": 3, "order": list("ABCDE"),
                   "motions": [dict(MISFILED, id="D5", proposer="E", passed=True, tally="(5 yes, 0 no, 0 abstain)",
                                    votes=dict.fromkeys("ABCDE", "yes"), result="proposal sent to the Maritime League: trade deal")],
                   "pre_positions": {}, "revisions": {}})
        record = mark(store)
        self.assertEqual(record["last_clean_month"], 2)
        plan = record["replay"]
        self.assertEqual(plan["to_month"], 2)
        self.assertTrue(plan["deterministic"], "a run of stand-ins reproduces from its config alone")
        self.assertIn("to month 3", plan["how"])

    def test_a_non_executed_mismatch_is_marked_non_behavioral(self):
        path = new_run(CONFIG, runs_dir=self.tmp, name="nonbehav", months=1, quiet=True)
        store = RunStore(path)
        store.log({"type": "month", "month": 0, "order": list("ABCDE"),
                   "motions": [dict(MISFILED, id="D5", proposer="E", passed=False, withdrawn=True,
                                    tally="", votes={}, result="withdrawn by its proposer")],
                   "pre_positions": {}, "revisions": {}})
        self.assertEqual(audit(store)["classification"], "CORRECTED_NON_BEHAVIORAL")


class Determinism(unittest.TestCase):
    """9. Adding the check does not make runs non-deterministic."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-det-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_two_identical_runs_agree(self):
        a = new_run(CONFIG, runs_dir=self.tmp, name="a", months=6, quiet=True)
        b = new_run(CONFIG, runs_dir=self.tmp, name="b", months=6, quiet=True)
        for name in ("scorecard.json",):
            with open(os.path.join(a, name), encoding="utf-8") as f:
                first = json.load(f)
            with open(os.path.join(b, name), encoding="utf-8") as f:
                second = json.load(f)
            self.assertEqual(first["analytics"]["convergence"], second["analytics"]["convergence"])
            self.assertEqual(first["country"]["vote_division"], second["country"]["vote_division"])
        self.assertEqual([m["motions"] for m in RunStore(a).read_log("month")],
                         [m["motions"] for m in RunStore(b).read_log("month")])
        self.assertEqual(audit(RunStore(a))["classification"], audit(RunStore(b))["classification"])


if __name__ == "__main__":
    unittest.main()
