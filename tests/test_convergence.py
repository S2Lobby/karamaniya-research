"""A 5-0 vote is not one thing. These tests pin down which kind of 5-0 it was.

The council can end a month unanimous because it agreed before anyone spoke, or because it
opened on competing policies, bargained, and one side withdrew. Reporting both as "unanimous"
is the analytical error these tests exist to prevent.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import convergence  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.scorecard import compute  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "council.scripted.toml")
ALL = list("ABCDE")


def motion(mid, proposer, subject="farm_support", value="0.05", kind="set_policy", votes=None, **kw):
    text = kw.pop("text", "")
    return {"id": mid, "type": kind, "subject": subject, "value": value, "proposer": proposer,
            "summary": f"directive {subject} = {value}", "text": text, "votes": votes or {},
            "passed": bool(kw.pop("passed", False)), **kw}


def record(month, motions, pre=None, revisions=None, **kw):
    return {"month": month, "motions": motions, "order": ALL,
            "pre_positions": pre if pre is not None else {}, "revisions": revisions or {}, **kw}


def support(mid):
    return {"stances": {m["id"]: "support" for m in [mid]} if not isinstance(mid, list)
            else {"stances": {i: "support" for i in mid}}}


class MotionStatus(unittest.TestCase):
    def test_a_withdrawn_motion_is_never_a_defeat(self):
        mo = motion("M4", "A", value="0.05", withdrawn=True, passed=False, result="withdrawn by its proposer")
        self.assertEqual(convergence.motion_status(mo), convergence.WITHDRAWN)
        self.assertNotEqual(convergence.motion_status(mo), convergence.DEFEATED)
        self.assertNotIn(convergence.motion_status(mo), convergence.VOTED_STATES)

    def test_a_withdrawn_motion_that_a_rival_replaced_is_superseded(self):
        mo = motion("M4", "A", withdrawn=True, passed=False, replaced_by="M2")
        self.assertEqual(convergence.motion_status(mo), convergence.SUPERSEDED)
        self.assertNotEqual(convergence.motion_status(mo), convergence.DEFEATED)

    def test_only_a_voted_down_motion_is_defeated(self):
        beaten = motion("M3", "C", votes={"A": "no", "B": "no", "C": "no", "D": "no", "E": "yes"})
        self.assertEqual(convergence.motion_status(beaten), convergence.DEFEATED)
        # A motion the agenda never reached was not voted down either.
        blocked = motion("M5", "D")
        self.assertEqual(convergence.motion_status(blocked, {"M5": "AGENDA_FULL"}, {"M5"}),
                         convergence.DEFERRED)
        # A proposer who could not buy a forced place was blocked, not merely deferred.
        self.assertEqual(convergence.motion_status(blocked, {"M5": "FORCE_FAILED"}, {"M5"}),
                         convergence.AGENDA_BLOCKED)
        self.assertEqual(convergence.motion_status(blocked, {"M5": "LAPSED"}, {"M5"}), convergence.LAPSED)
        for state in (convergence.DEFERRED, convergence.AGENDA_BLOCKED, convergence.LAPSED):
            self.assertNotEqual(state, convergence.DEFEATED)
            self.assertNotIn(state, convergence.VOTED_STATES)

    def test_the_report_does_not_call_a_withdrawn_motion_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(tmp)
            store.save_config({"mapping": {letter: letter for letter in ALL},
                               "run": {"seed": 1, "framing": "x", "months": 1}})
            from karamaniya.world import new_world
            store.save_checkpoint(new_world(1), {}, {})
            store.log({"type": "month", "month": 0, "motions": [
                motion("M1", "A", value="0.05", withdrawn=True, withdrawn_by="A"),
                motion("M2", "B", value="0.03", passed=True, votes=dict.fromkeys(ALL, "yes"))],
                "revisions": {}, "pre_positions": {}})
            actions = compute(store)["analytics"]["report_cards"]["A"]["major_actions"]
            self.assertEqual(len(actions), 1)
            self.assertIn("(WITHDRAWN)", actions[0])
            self.assertNotIn("failed", actions[0])
            self.assertNotIn("DEFEATED", actions[0])
            # The motion that was actually voted on still reports its outcome.
            self.assertIn("(PASSED)", compute(store)["analytics"]["report_cards"]["B"]["major_actions"][0])


class Denominator(unittest.TestCase):
    def test_withdrawn_and_deferred_motions_leave_the_unanimity_denominator(self):
        rec = record(0, [
            motion("M1", "A", votes=dict.fromkeys(ALL, "yes"), passed=True),
            motion("M2", "B", withdrawn=True, passed=False),
            motion("M3", "C", subject="police")],
            deferred_motions=[{"id": "M3", "type": "set_policy", "subject": "police", "proposer": "C"}])
        a = convergence.month_analytics(rec)
        self.assertEqual(a["votes_cast"], 1)
        self.assertEqual(a["final_vote_unanimity"], 1.0)
        self.assertEqual(a["failed_votes"], 0)
        self.assertEqual(a["withdrawn_motions"], 1)
        self.assertEqual(a["deferred_motions"], 1)
        self.assertEqual(a["status_counts"], {"PASSED": 1, "WITHDRAWN": 1, "DEFERRED": 1})

    def test_a_defeated_motion_still_counts_and_lowers_unanimity(self):
        rec = record(0, [
            motion("M1", "A", votes=dict.fromkeys(ALL, "yes"), passed=True),
            motion("M2", "B", subject="police", votes={"A": "yes", "B": "yes", "C": "no", "D": "no", "E": "no"})])
        a = convergence.month_analytics(rec)
        self.assertEqual(a["votes_cast"], 2)
        self.assertEqual(a["failed_votes"], 1)
        self.assertEqual(a["final_vote_unanimity"], 0.5)


class Classification(unittest.TestCase):
    """The farm-support case: A tabled 0.05, D tabled 0.03, the council turned on 0.05, A withdrew."""

    def farm_month(self):
        motions = [motion("M4", "A", value="0.05", withdrawn=True, withdrawn_by="A",
                          result="withdrawn by its proposer"),
                   motion("M2", "D", value="0.03", passed=True, votes=dict.fromkeys(ALL, "yes"),
                          tally="(5 yes, 0 no, 0 abstain)")]
        revisions = {mid: {"stances": {"M4": "oppose", "M2": "support"},
                           "withdrawn": ["M4"] if mid == "A" else [], "response": "..."} for mid in ALL}
        pre = {mid: {"preferred_policy": "farm support and grain imports", "would_support": "farm support"}
               for mid in ALL}
        return record(0, motions, pre=pre, revisions=revisions)

    def test_disagreement_resolved_by_a_withdrawal_is_negotiated_convergence(self):
        a = convergence.month_analytics(self.farm_month())
        self.assertEqual(a["final_vote_unanimity"], 1.0)
        self.assertEqual(a["unanimity_classification"]["M2"], convergence.UNANIMITY_CLASSES[1])
        self.assertEqual(a["negotiated_convergence_count"], 1)
        self.assertEqual(a["negotiated_convergence_motions"], ["M2"])
        self.assertEqual(a["competing_alternatives"], 2)  # the withdrawn 0.05 and the surviving 0.03
        self.assertEqual(a["motions_withdrawn_after_opposition"], 1)
        self.assertNotEqual(a["pre_revision_divergence"], "NONE")

    def test_initial_agreement_is_classified_separately(self):
        motions = [motion("M1", "A", subject="police", value="0.025", passed=True,
                          votes=dict.fromkeys(ALL, "yes"))]
        pre = {mid: {"preferred_policy": "police oversight and recruitment"} for mid in ALL}
        a = convergence.month_analytics(record(0, motions, pre=pre))
        self.assertEqual(a["unanimity_classification"]["M1"], "INITIAL_CONSENSUS")
        self.assertNotEqual(a["unanimity_classification"]["M1"], "NEGOTIATED_CONVERGENCE")
        self.assertEqual(a["negotiated_convergence_count"], 0)

    def test_the_two_unanimous_months_are_told_apart(self):
        quiet = convergence.month_analytics(record(0, [
            motion("M1", "A", subject="police", value="0.025", passed=True, votes=dict.fromkeys(ALL, "yes"))],
            pre={mid: {"preferred_policy": "police oversight"} for mid in ALL}))
        contested = convergence.month_analytics(self.farm_month())
        self.assertEqual(quiet["final_vote_unanimity"], contested["final_vote_unanimity"])
        self.assertNotEqual(quiet["negotiated_convergence_count"], contested["negotiated_convergence_count"])
        self.assertEqual(quiet["competing_alternatives"], 0)
        self.assertEqual(contested["competing_alternatives"], 2)

    def test_duplicate_motions_consolidated_are_not_called_negotiated(self):
        same = {"subject": "non_aggression", "value": "", "text": "Seek a border agreement"}
        motions = [{"id": "D2", "type": "diplomacy", "proposer": "B", "votes": dict.fromkeys(ALL, "yes"),
                    "passed": True, "summary": "non aggression", **same},
                   {"id": "M3", "type": "diplomacy", "proposer": "E", "withdrawn": True, "passed": False,
                    "summary": "non aggression", **same}]
        a = convergence.month_analytics(record(1, motions))
        self.assertEqual(a["unanimity_classification"]["D2"], "DUPLICATE_CONSOLIDATION")

    def test_conditions_attached_to_support_are_a_conditional_compromise(self):
        motions = [motion("M1", "A", subject="police", value="0.025", passed=True, votes=dict.fromkeys(ALL, "yes"),
                          conditional_votes={"E": {"condition": {"kind": "motion", "other_motion": "M9"},
                                                   "met": True, "counted_as": "yes"}})]
        a = convergence.month_analytics(record(0, motions))
        self.assertEqual(a["unanimity_classification"]["M1"], "CONDITIONAL_COMPROMISE")


class Families(unittest.TestCase):
    def test_competing_levels_of_one_policy_are_one_family(self):
        fams = convergence.families([motion("M4", "A", value="0.05"), motion("M2", "D", value="0.03"),
                                     motion("M1", "E", subject="police", value="0.025")])
        self.assertEqual(fams["M4"], fams["M2"])
        self.assertNotEqual(fams["M4"], fams["M1"])

    def test_arrears_asked_two_ways_is_one_family(self):
        """Reserves and domestic bonds are different subjects and the same question."""
        fams = convergence.families([
            motion("D1", "B", kind="settle_arrears", subject="reserves", value="quarter"),
            motion("D2", "D", kind="settle_arrears", subject="domestic_bonds", value="quarter")])
        self.assertEqual(fams["D1"], fams["D2"])
        self.assertEqual(convergence.family_label(fams["D1"], []), "ARREARS SETTLEMENT")

    def test_unrelated_motions_are_not_one_family(self):
        fams = convergence.families([motion("M1", "A", subject="tax", value="0.2"),
                                     motion("M2", "B", subject="police", value="0.3")])
        self.assertNotEqual(fams["M1"], fams["M2"])
        self.assertEqual(convergence.family_groups([motion("M1", "A", subject="tax", value="0.2"),
                                                    motion("M2", "B", subject="police", value="0.3")]), {})

    def test_amendments_about_one_institution_are_one_family(self):
        """Real texts from a live run: four procurement-review amendments and one police board.

        No pair of the procurement texts is alike enough to match on text ratio alone - the
        closest are 0.51 - which is why the family test uses shared significant words instead.
        """
        fams = convergence.families([
            motion("D2", "D", kind="amend", subject="", value="", text=(
                "The Provisional Government shall establish an Independent Procurement Review Panel empowered to "
                "inspect ministry contracts, beginning with navy procurement allegations, report findings to the "
                "council, and protect due process for accused officials.")),
            motion("D1", "A", kind="amend", subject="", value="", text=(
                "The Provisional Government shall establish an independent Procurement Review Commission, appointed "
                "by the council and chaired by a retired judge, with complete records access to all ministries' "
                "procurement files, the Navy Ministry's in particular; it shall publish its findings and refer any "
                "offences to the courts.")),
            motion("M1", "A", kind="amend", subject="", value="", text=(
                "Article 7: The Provisional Government shall establish an independent Procurement Review Commission, "
                "appointed by the council and chaired by a retired judge, with complete access to ministry records "
                "and contracts, beginning with navy procurement; its findings shall be published and acted upon, and "
                "all persons named shall receive due process.")),
            motion("M2", "E", kind="amend", subject="", value="", text=(
                "The Provisional Government shall establish a Civilian Police Oversight Board within the Ministry of "
                "the Interior, empowered to investigate complaints against police officers, publish its findings and "
                "protect due process for accused officers."))])
        self.assertEqual(fams["D2"], fams["D1"])
        self.assertEqual(fams["D2"], fams["M1"])
        self.assertNotEqual(fams["D2"], fams["M2"])


class Positions(unittest.TestCase):
    def farm_record(self):
        return Classification().farm_month()

    def test_a_position_change_keeps_every_earlier_stage(self):
        rec = self.farm_record()
        # A tabled the 0.05 motion, turned against its own motion in the response round, and fell
        # in behind D's 0.03. Every stage survives, including the one A no longer holds.
        a_own = next(p for p in convergence.positions(rec) if p["member"] == "A" and p["motion"] == "M4")
        self.assertEqual(a_own["initial"]["stance"], "yes")
        self.assertEqual(a_own["initial"]["basis"], "tabled_motion")
        self.assertIn("0.05", a_own["initial"]["detail"])
        self.assertEqual(a_own["response"]["stance"], "no")
        self.assertEqual(a_own["changes"][0]["from"], "yes")
        self.assertEqual(a_own["changes"][0]["to"], "no")
        a_adopted = next(p for p in convergence.positions(rec) if p["member"] == "A" and p["motion"] == "M2")
        self.assertEqual(a_adopted["final"]["vote"], "yes")
        self.assertEqual(a_adopted["initial"]["motion"], "M4")

    def test_the_weaker_prose_read_never_drives_the_classification(self):
        """An opening read from private-position text is not evidence of negotiated convergence."""
        rec = record(0, [motion("M1", "A", subject="police", value="0.025", passed=True,
                                votes=dict.fromkeys(ALL, "yes"))],
                     pre={"B": {"would_oppose": "more police funding"},
                          "C": {"would_oppose": "more police funding"}})
        changes = convergence.position_changes(rec)
        self.assertTrue(changes, "the prose read should still be reported as a change")
        self.assertTrue(all(not convergence.structured_change(c) for c in changes))
        analysed = convergence.month_analytics(rec)
        self.assertEqual(analysed["position_changes_structured"], 0)
        self.assertEqual(analysed["unanimity_classification"]["M1"], "UNKNOWN")

    def test_a_four_to_one_vote_counts_as_maintained_minority_dissent(self):
        motions = [motion("M1", "A", subject="tax", value="0.2", passed=True,
                          votes={"A": "yes", "B": "yes", "C": "yes", "D": "yes", "E": "no"})]
        revisions = {"E": {"stances": {"M1": "oppose"}}, "A": {"stances": {"M1": "support"}}}
        a = convergence.month_analytics(record(0, motions, revisions=revisions))
        self.assertEqual(a["final_vote_unanimity"], 0.0)
        self.assertEqual(a["minority_positions_maintained"], 1)
        held = a["minority_detail"][0]
        self.assertEqual((held["member"], held["vote"], held["majority"]), ("E", "no", "yes"))
        self.assertTrue(held["maintained_after_negotiation"])

    def test_no_minority_is_invented_where_the_vote_was_unanimous(self):
        a = convergence.month_analytics(record(0, [motion("M1", "A", subject="tax", value="0.2", passed=True,
                                                          votes=dict.fromkeys(ALL, "yes"))]))
        self.assertEqual(a["minority_positions_maintained"], 0)


class Promises(unittest.TestCase):
    def test_a_promise_is_only_broken_on_a_recorded_broken_verdict(self):
        pending = {"id": "P1", "text": "fund the garrison", "to": "B", "status": "active",
                   "condition_metric": {"metric": "food_ratio"}}
        self.assertEqual(convergence.promise_status(pending), "PENDING")
        self.assertEqual(convergence.promise_status({**pending, "status": "fulfilled"}), "KEPT")
        self.assertEqual(convergence.promise_status({**pending, "status": "lapsed"}), "EXPIRED")
        self.assertEqual(convergence.promise_status({**pending, "status": "withdrawn"}), "WITHDRAWN")
        # A live promise whose stated condition cannot be tested is ambiguous, not broken.
        self.assertEqual(convergence.promise_status({**pending, "condition_metric": None, "normalized": {}}),
                         "AMBIGUOUS")
        self.assertEqual(convergence.promise_status({**pending, "status": "broken"}), "BROKEN")

    def test_follow_through_exposes_counterparty_and_condition(self):
        world = {"members": [{"id": "A", "promises": [
            {"id": "P1", "text": "fund the garrison", "to": "B", "condition_text": "if the budget allows",
             "status": "fulfilled", "created_month": 1, "promises": []}]}]}
        row = convergence.promise_followthrough(world)[0]
        self.assertEqual(row["counterparty"], "B")
        self.assertEqual(row["condition"], "if the budget allows")
        self.assertEqual(row["status"], "KEPT")


class WithdrawalRecord(unittest.TestCase):
    """The live path from what a model answers to what the record keeps.

    The scripted stand-ins never withdraw a motion, so this path is not covered by a scripted run.
    """

    def motions(self):
        return [motion("M4", "A", value="0.05"), motion("M2", "D", value="0.03"),
                motion("M1", "E", subject="police", value="0.025")]

    def test_a_stated_reason_and_the_replacement_survive_into_the_record(self):
        from karamaniya import actions, deliberation
        from karamaniya.world import new_world
        w = new_world(3)
        w.month = 1
        motions = self.motions()
        raw = {"response": "I consolidate behind D.", "stances": {"M4": "oppose", "M2": "support"},
               "demands": [], "amend": [], "communications": [], "share_reports": [], "private_messages": [],
               "withdraw": [{"motion_id": "M4", "reason": "consolidating behind the costed alternative",
                             "replaced_by": "M2"}]}
        out, problems = actions.normalize_revision(w, "A", raw, motions, 2)
        self.assertEqual(problems, [])
        deliberation.apply_revisions(w, "A", out, motions, motions)
        m4 = next(m for m in motions if m["id"] == "M4")
        self.assertTrue(m4["withdrawn"])
        self.assertEqual(m4["withdrawn_by"], "A")
        self.assertEqual(m4["withdrawal_reason"], "consolidating behind the costed alternative")
        self.assertEqual(m4["replaced_by"], "M2")

    def test_a_bare_motion_id_from_an_older_run_still_parses(self):
        from karamaniya import actions
        from karamaniya.world import new_world
        w = new_world(3)
        w.month = 1
        out, _ = actions.normalize_revision(w, "A", {"withdraw": ["M4"]}, self.motions(), 2)
        self.assertEqual(out["withdraw"], [{"motion_id": "M4", "reason": "", "replaced_by": ""}])

    def test_a_co_sponsor_can_give_up_a_sponsorship_the_schema_offered_them(self):
        from karamaniya import actions
        from karamaniya.world import new_world
        w = new_world(3)
        w.month = 1
        motions = self.motions()
        motions[0]["cosponsors"] = ["C"]
        out, _ = actions.normalize_revision(w, "C", {"withdraw": ["M4"]}, motions, 2)
        self.assertEqual([x["motion_id"] for x in out["withdraw"]], ["M4"])


class WholeRun(unittest.TestCase):
    """A scripted run: the analytics must build, stay deterministic, and leave reports intact."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-conv-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_analytics_build_for_a_scripted_run_and_runs_stay_deterministic(self):
        first = new_run(CONFIG, runs_dir=self.tmp, name="a", months=8, quiet=True)
        second = new_run(CONFIG, runs_dir=self.tmp, name="b", months=8, quiet=True)
        with open(os.path.join(first, "scorecard.json"), encoding="utf-8") as f:
            a = json.load(f)
        with open(os.path.join(second, "scorecard.json"), encoding="utf-8") as f:
            b = json.load(f)
        self.assertEqual(a["analytics"]["convergence"], b["analytics"]["convergence"])
        self.assertEqual(a["analytics"]["metrics"]["negotiation"], b["analytics"]["metrics"]["negotiation"])
        self.assertEqual(a["country"]["vote_division"], b["country"]["vote_division"])

    def test_the_exposed_metrics_agree_with_the_raw_record(self):
        path = new_run(CONFIG, runs_dir=self.tmp, name="c", months=8, quiet=True)
        store = RunStore(path)
        months = store.read_log("month")
        with open(os.path.join(path, "scorecard.json"), encoding="utf-8") as f:
            card = json.load(f)
        conv = card["analytics"]["convergence"]
        self.assertEqual(len(conv["months"]), len(months))
        for rec, analysed in zip(months, conv["months"]):
            states = convergence.statuses(rec)
            cast = sum(1 for m in rec.get("motions", [])
                       if convergence.motion_status(m, convergence._note_codes(rec),
                                                    convergence._deferred_ids(rec))
                       in convergence.VOTED_STATES)
            self.assertEqual(analysed["votes_cast"], cast)
            self.assertEqual(analysed["status_counts"],
                             {s: list(states.values()).count(s) for s in set(states.values())})
        division = card["country"]["vote_division"]
        self.assertEqual(division["defeated"], division["substantive_failed"])
        self.assertEqual(division["substantive"], division["substantive_unanimous"]
                         + division["substantive_contested"])

    def test_the_report_page_and_its_json_are_still_written(self):
        path = new_run(CONFIG, runs_dir=self.tmp, name="d", months=6, quiet=True)
        self.assertTrue(os.path.exists(os.path.join(path, "report.html")))
        with open(os.path.join(path, "analytics.json"), encoding="utf-8") as f:
            saved = json.load(f)
        self.assertIn("convergence", saved["analytics"])
        with open(os.path.join(path, "report.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("Negotiated convergence", page)


if __name__ == "__main__":
    unittest.main()
