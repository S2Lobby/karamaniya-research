"""World engine 19: the politics slice of the engine-18 audit (docs/AUDIT_ENGINE18.md).

Each test names the audit ID it covers: the election outlook the delegates read (PO1, TO5), the rigged count (PO5,
PO6), the referendum for legacy worlds (PO7), the integrity audit (PO2, PO8, PO10), the Charter amendment guard (PO3),
the agendas' red lines (PO4), the opposition after a resume (PO9) and the grain deal's last month (TO11).
"""
import copy
import os
import random
import sys
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import agendas, decision_context, foreign, integrity, opposition, politics  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

# Audit PO1 + TO5: the line now says what the vote it previews includes.
OUTLOOK = "If the election were held now, with the campaign and settings in force:"


def at_the_vote(seed: int = 5):
    """A world in the Charter's election month, before the vote is taken."""
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    w.month = w.const.election_month
    return w


def rounded(shares: dict) -> dict:
    return {k: round(v, 3) for k, v in shares.items()}


class TheOutlookIsTheVote(unittest.TestCase):
    """PO1 + TO5: 'If the election were held now' is the vote the engine takes, under the settings in force."""

    SETTINGS = {
        "rigged count": lambda w: setattr(w.policy, "election_conduct", "rigged"),
        "Union propaganda at its maximum": lambda w: setattr(w.dip, "propaganda", 1.0),
        "censored press": lambda w: setattr(w.const, "press", "censored"),
    }

    def test_the_outlook_is_the_vote_under_the_settings_in_force(self):
        for label, set_up in self.SETTINGS.items():
            with self.subTest(setting=label):
                w = at_the_vote()
                set_up(w)
                outlook = politics.election_outlook(w)
                vote = copy.deepcopy(w)
                politics._election(vote, random.Random(0))
                record = vote.const.elections[-1]
                self.assertEqual(rounded(outlook["shares"]), record["shares"])
                self.assertEqual(outlook["verdict"], politics.charter_verdict(record["shares"]))

    def test_a_rigged_count_is_previewed_as_the_government_keeping_power(self):
        w = at_the_vote()
        w.policy.election_conduct = "rigged"
        line = next(x for x in decision_context.canonical_hard_state_v2(w, "session", []).splitlines()
                    if x.startswith("If the election were held now"))
        self.assertTrue(line.startswith(OUTLOOK), line)
        self.assertIn("the government would keep power", line)


class TheRiggedCountNeverOverdrawsTheOtherLists(unittest.TestCase):
    """PO5: a rigged count gives the Council List at most what the other lists hold, and takes it from them pro rata."""

    def test_a_normal_rigged_count_adds_twelve_points_to_the_council_list(self):
        fair, rigged = at_the_vote(), at_the_vote()
        rigged.policy.election_conduct = "rigged"
        politics._election(fair, random.Random(0))
        politics._election(rigged, random.Random(0))
        gain = rigged.const.elections[-1]["shares"]["Council List"] - fair.const.elections[-1]["shares"]["Council List"]
        self.assertAlmostEqual(gain, 0.12, places=2)

    def test_no_share_goes_negative_when_the_council_list_already_holds_most_of_the_vote(self):
        w = at_the_vote()
        for p in w.pops:
            p.indep, p.approval = 0.98, 0.92
        w.policy.election_conduct = "rigged"
        politics._election(w, random.Random(0))
        shares = w.const.elections[-1]["shares"]
        self.assertGreaterEqual(min(shares.values()), 0.0, shares)
        self.assertAlmostEqual(sum(shares.values()), 1.0, places=2)


class TheRiggedCountLeavesTheOfficersAlone(unittest.TestCase):
    """PO6: whether the count was rigged does not move the officers' coup check of the same month."""

    def test_the_officers_coup_is_the_same_with_a_fair_count_or_a_rigged_one(self):
        template = at_the_vote(1)
        template.mil.army.loyalty = 0.2
        template.mil.army.arrears = 4.0
        for p in template.pops:
            p.approval = 0.6                  # keeps the revolution check from drawing at all
        differ = []
        for seed in range(1, 61):
            coup = {}
            for conduct in ("fair", "rigged"):
                w = copy.deepcopy(template)
                w.seed = seed
                w.policy.election_conduct = conduct
                politics.monthly_checks(w)
                coup[conduct] = bool(w.outcome) and w.outcome.get("type") == "officers_coup"
            if coup["fair"] != coup["rigged"]:
                differ.append(seed)
        self.assertEqual(differ, [])


class TheReferendumFormulaIsForAgentArchitectureTwo(unittest.TestCase):
    """PO7: a world before agent architecture 2 keeps the engine-16 result: the support as it stands, a rigged count
    as it always was, and a flat rally on a win."""

    def legacy(self):
        w = new_world(5, 36, human_factor=False, agent_architecture_version=1)
        w.foreign = foreign.initial_state(w.seed)
        w.month = 6
        w.const.referendum_month = 6
        w.const.elections = []
        return w

    @staticmethod
    def support(w) -> float:
        pops = w.k_pops()
        return sum(p.indep * p.size for p in pops) / sum(p.size for p in pops)

    def test_a_legacy_referendum_is_the_support_and_a_flat_rally(self):
        w = self.legacy()
        support, rally0 = self.support(w), w.dip.rally
        politics._referendum(w, random.Random(0))
        self.assertEqual(w.const.elections[-1], {"month": 6, "referendum": round(support, 3)})
        self.assertAlmostEqual(w.dip.rally - rally0, 0.2, places=6)
        self.assertEqual(w.dip.propaganda, 0.0)

    def test_a_legacy_rigged_count_adds_the_old_eight_points(self):
        w = self.legacy()
        w.policy.election_conduct = "rigged"
        support = self.support(w)
        politics._referendum(w, random.Random(0))
        self.assertEqual(w.const.elections[-1]["referendum"], round(min(0.99, support + 0.08), 3))


class RecordedRun:
    """Only what integrity reads from a run store: its name, its month log and its checkpoint."""

    def __init__(self, records=(), world=None):
        self.path = Path("engine19-run")
        self._records = list(records)
        self._world = world

    def read_log(self, name):
        return self._records if name == "month" else []

    def read_json(self, name):
        raise FileNotFoundError(name)

    def load_checkpoint(self):
        return [self._world]


def misfiled(**changes) -> dict:
    """A passed diplomacy motion whose text asks for trade talks with the Maritime League and whose action goes to the
    Union: the wrong act of the engine-18 audit."""
    mo = {"id": "M7", "proposer": "A", "type": "diplomacy", "subject": "trade_talks", "value": "",
          "text": "Propose trade talks with the Maritime League to restore shipping.",
          "action": {"action_type": "trade_talks", "target": "union"},
          "passed": True, "withdrawn": False, "void": False, "votes": {"A": "yes", "B": "yes", "C": "yes"},
          "tally": "(3 yes, 0 no, 0 abstain)", "result": "proposal sent to the Solvaran Union: trade talks",
          "execution_status": "EXECUTED", "execution_month": 4}
    mo.update(changes)
    return mo


def audited_world() -> dict:
    w = new_world(5, 36)
    w.foreign = foreign.initial_state(w.seed)
    return w.to_dict()


class TheIntegrityAuditCountsOnlyWhatExecuted(unittest.TestCase):
    """PO2: a passed motion that the execution gate blocked changed nothing, so it is not counted as executed."""

    def test_a_motion_the_gate_blocked_is_not_counted_as_executed(self):
        blocked = misfiled(execution_status="EXECUTION_BLOCKED",
                           result="passed, execution blocked: the action has no valid target")
        report = integrity.audit(RecordedRun([{"month": 4, "motions": [blocked]}]), audited_world())
        self.assertEqual(report["executed_wrongly"], [])
        self.assertEqual(report["findings"][0]["touched_state"], [])
        self.assertEqual(report["classification"], "CORRECTED_NON_BEHAVIORAL")

    def test_a_motion_that_executed_still_counts(self):
        report = integrity.audit(RecordedRun([{"month": 4, "motions": [misfiled()]}]), audited_world())
        self.assertEqual(report["classification"], "CORRECTED_BEHAVIORAL")

    def test_a_record_with_no_execution_status_counts_as_executed(self):
        legacy = misfiled()
        del legacy["execution_status"], legacy["execution_month"]
        report = integrity.audit(RecordedRun([{"month": 4, "motions": [legacy]}]), audited_world())
        self.assertEqual(report["classification"], "CORRECTED_BEHAVIORAL")


class TheReplayPointIsTheLastCleanMonth(unittest.TestCase):
    """PO10: with the wrong motion in Month 1 (month 0), no month is clean, so the replay point is -1, not Month 1."""

    def test_a_wrong_motion_in_month_zero_leaves_no_clean_month(self):
        world = audited_world()
        store = RecordedRun([{"month": 0, "motions": [misfiled(execution_month=0)]}], world)
        report = integrity.audit(store, world)
        self.assertEqual(integrity._last_clean_month(report, world.get("history", [])), -1)
        record = integrity.mark(store, world)
        self.assertEqual(record["last_clean_month"], -1)
        self.assertEqual(record["replay"]["to_month"], -1)
        self.assertNotIn("to month 0", record["replay"]["how"])

    def test_a_wrong_motion_in_month_four_leaves_month_three_clean(self):
        world = audited_world()
        store = RecordedRun([{"month": 4, "motions": [misfiled(execution_month=4)]}], world)
        self.assertEqual(integrity.mark(store, world)["last_clean_month"], 3)


class TheReplayRecordsTheMonthAsked(unittest.TestCase):
    """PO8: record_replay writes the replay point it was asked for."""

    def test_the_month_asked_for_is_the_month_recorded(self):
        for month in (5, 20):
            with self.subTest(up_to_month=month):
                store = RecordedRun([], new_world(5, 36))
                record = integrity.record_replay(store, up_to_month=month, write=False)
                self.assertEqual(record["replay"]["to_month"], month)
                self.assertEqual(record["last_clean_month"], month)


class TheCharterElectionDateIsGuardedAtMonth36(unittest.TestCase):
    """PO3: a second clause fixing the Charter's election date is refused as a duplicate; the date is Month 36."""

    STORED = ("The Constituent Assembly election is held in Month 36 and may not be postponed or cancelled by the "
              "government.")
    PROPOSED = ("Constituent Assembly elections are to be held in Month 36 as the Charter sets; the date is fixed and "
                "may not be moved.")

    def test_a_second_clause_fixing_the_month_36_date_is_a_duplicate(self):
        w = new_world(5, 36)
        w.const.amendments = [{"month": 0, "by": "A", "text": self.STORED}]
        self.assertEqual(politics.amendment_overlap(w, self.PROPOSED), self.STORED[:120])

    def test_a_month_36_clause_that_adds_observers_is_a_strengthening(self):
        w = new_world(5, 36)
        w.const.amendments = [{"month": 0, "by": "A", "text": self.STORED}]
        strengthening = self.PROPOSED + " Observers and the polling access must be guaranteed."
        self.assertIsNone(politics.amendment_overlap(w, strengthening))


class TheGrainArrangementRunsToItsLastMonth(unittest.TestCase):
    """TO11: an agreement is in force through its last month (until), as the economy counts it, so the state the
    delegates read agrees with the economy."""

    def test_an_agreement_is_in_force_in_its_last_month(self):
        w = new_world(5, 36)
        w.foreign = foreign.initial_state(w.seed)
        # The inherited arrangement as founding.py records it: Month 1 through Month 6 (until = 5).
        w.foreign["actors"]["dorsania"]["diplomacy"]["commitments"].append(
            {"type": "grain agreement", "month": 0, "until": 5, "partner": "karamaniya", "temporary": True})
        w.month = 5
        self.assertEqual(len(politics.active_deals(w, "dorsania")), 1)
        w.month = 6
        self.assertEqual(politics.active_deals(w, "dorsania"), [])


class ARedLineIsCrossedOnlyByTheActItNames(unittest.TestCase):
    """PO4: a red line is crossed by the act it describes. Lifting a measure, or setting the rule already in force, is
    not a crossing; order first's line is pay, so a cut to the military budget does not cross it."""

    def test_imposing_an_emergency_measure_crosses_the_constitution_line_and_lifting_one_does_not(self):
        w = new_world(5, 36)
        on = {"type": "emergency_measure", "subject": "curfew", "value": "on"}
        off = {"type": "emergency_measure", "subject": "curfew", "value": "off"}
        self.assertTrue(agendas.crosses(w, on, "constitution"))
        self.assertFalse(agendas.crosses(w, off, "constitution"))

    def test_setting_the_decision_rule_already_in_force_is_no_crossing(self):
        w = new_world(5, 36)
        w.const.decision_rule = "two_thirds"
        same = {"type": "constitution", "subject": "decision_rule", "value": "two_thirds"}
        self.assertFalse(agendas.crosses(w, same, "order_first"))
        w.const.decision_rule = "majority"
        change = {"type": "constitution", "subject": "decision_rule", "value": "two_thirds"}
        self.assertTrue(agendas.crosses(w, change, "order_first"))

    def test_order_first_counts_cuts_to_pay_not_to_the_military_budget(self):
        w = new_world(5, 36)
        w.policy.military, w.policy.police, w.policy.officer_pay = 0.03, 0.02, "standard"
        cut_budget = {"type": "set_policy", "subject": "military", "value": "0.02"}
        self.assertFalse(agendas.crosses(w, cut_budget, "order_first"))
        self.assertTrue(agendas.crosses(w, cut_budget, "defence"))
        freeze_pay = {"type": "set_policy", "subject": "officer_pay", "value": "freeze"}
        self.assertTrue(agendas.crosses(w, freeze_pay, "order_first"))
        cut_police = {"type": "set_policy", "subject": "police", "value": "0.01"}
        self.assertTrue(agendas.crosses(w, cut_police, "order_first"))


class TheResumedWorldsFirstLookReportsNoStaleActs(unittest.TestCase):
    """PO9, decided against the audit's fix. A world resumed without an opposition record keeps its first look as the
    baseline. Measuring that look from the fresh-run settings (_start) reported settings set long before the resume as
    this month's acts (an army build-up, emergency powers declared, an election moved), and each one moved the public."""

    def test_settings_set_before_the_resume_are_not_reported_as_this_months_acts(self):
        w = new_world(5, 36)
        w.foreign = foreign.initial_state(w.seed)
        w.institutions.pop(opposition.KEY, None)     # as a checkpoint from before engine 18 has it
        w.month = 9
        w.policy.military = 0.09                     # all three set long before the resume
        w.const.emergency = True
        w.const.election_month = 39
        opposition.monthly(w)
        said = [s["text"] for s in w.institutions[opposition.KEY]["said"] if s["month"] == 9]
        self.assertEqual(said, [])
        self.assertEqual(opposition.momentum(w, "Union Party"), 0.0)


if __name__ == "__main__":
    unittest.main()
