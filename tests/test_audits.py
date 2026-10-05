"""Investigations: the council orders an audit of an office; the findings are public and not always right.

The gap it closes: delegates wanted audits in five months out of ten (a Treasury holder tabled an emergency measure
called 'navy procurement audit' and was told there was no such measure), the corruption and procurement issues named
an audit as the trade-off, and there was no way to hold one."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, audits, decision_context, deliberation, dilemmas, engine, intelligence, politics, prompts, standing  # noqa: E402
from karamaniya.world import new_world  # noqa: E402
from tests.test_orders_vs_directives import resolve, world  # noqa: E402


class FixedRng:
    """random() answers from a list (the first is the 'is the audit blurred' draw, the second 'is a verdict wrong')."""
    def __init__(self, *draws):
        self.draws = list(draws) or [.99, .99]

    def random(self):
        return self.draws.pop(0) if self.draws else .99

    def gauss(self, mu, sigma):
        return 0.0


def issue_dict(kind, target, truth, month=0):
    """A live issue as dilemmas.generate builds it, complete enough for a month to be simulated with it in play."""
    return {"id": f"I-{kind}", "kind": kind, "title": kind, "month": month, "text": "", "readings": [], "tradeoffs": [],
            "tags": [], "office_notes": {}, "region": None, "target": target, "truth": truth, "status": "active",
            "expires_month": month + 50, "applied": {}, "started": True}


def motion(subject="army", value="open", proposer="E", **extra):
    return {"id": "M1", "proposer": proposer, "type": "investigation", "subject": subject, "value": value,
            "text": "Audit the procurement books", "summary": f"audit the {subject}", **extra}


def hold(w, office="army", proposer="E", corruption=0.0, capacity=1.0, votes=None):
    w.institutions.setdefault("corruption", {})[office] = corruption
    w.institutions["capacity"] = {o: capacity for o in ("head", "treasury", "interior", "army", "navy")}
    politics.apply_motion(w, {**motion(office, "open", proposer), "votes": votes or {proposer: "yes"}})


def report_with(w, *draws, error_rate=None):
    if error_rate is not None:
        w.tuning = {"audits": {"error_rate": error_rate}}
    real = audits.rng_for
    audits.rng_for = lambda *a: FixedRng(*draws)
    try:
        for _ in range(3):
            if not audits.state(w)["open"]:
                break
            engine.begin_month(w)
            engine.step(w)
    finally:
        audits.rng_for = real
    return audits.state(w)["done"][-1]


class Naming(unittest.TestCase):
    def test_the_ways_a_delegate_names_an_office_reach_one_name(self):
        for written, office in (("navy", "navy"), ("navy procurement audit", "navy"), ("the Army Command", "army"),
                                ("police", "interior"), ("Interior_and_Police", "interior"), ("central bank", "treasury"),
                                ("government", "head")):
            self.assertEqual(audits.office_of(written), office, written)
        self.assertIsNone(audits.office_of("procurement"))
        self.assertIsNone(audits.office_of("army and navy"))         # one office at a time

    def test_the_words_for_opening_and_closing(self):
        for word in ("open", "", "start", "ON"):
            self.assertEqual(audits.parse_action(word), "open", word)
        for word in ("close", "cancel", "stop"):
            self.assertEqual(audits.parse_action(word), "close", word)
        self.assertIsNone(audits.parse_action("maybe"))

    def test_a_motion_is_normalized_to_the_office_and_the_value(self):
        w = world()
        mo = actions.normalize_motion_v2(w, {"type": "investigation", "subject": "Navy procurement", "value": "",
                                             "text": "An audit of naval contracts"})
        self.assertEqual((mo["type"], mo["subject"], mo["value"]), ("investigation", "navy", "open"))
        self.assertEqual(actions.motion_summary(w, mo), "audit the navy")
        self.assertEqual(actions.motion_summary(w, {**mo, "value": "close"}), "close the audit of the navy")

    def test_audit_is_accepted_as_the_investigation_motion_type(self):
        w = world()
        mo = actions.normalize_motion_v2(w, {"type": "audit", "subject": "Treasury", "value": "open"})
        self.assertEqual((mo["type"], mo["subject"], mo["value"]), ("investigation", "treasury", "open"))
        self.assertIsNone(politics.validate_motion_detail(w, mo))

    def test_the_type_is_in_the_second_architectures_schema_and_only_there(self):
        w = world()
        kinds = actions.session_schema_v2(w, "E")["properties"]["motions"]["items"]["properties"]["type"]["enum"]
        self.assertIn("investigation", kinds)
        old = new_world(3, 6, member_ids=list("ABCDE"), agent_architecture_version=1)
        self.assertEqual(politics.validate_motion_detail(old, motion())["reason_code"], "UNKNOWN_TYPE")


class Validation(unittest.TestCase):
    def test_a_good_motion_is_valid(self):
        self.assertIsNone(politics.validate_motion_detail(world(), motion()))
        self.assertIsNone(politics.validate_motion_detail(world(), motion("navy procurement", "")))

    def test_the_rejections_say_what_would_work(self):
        w = world()
        unknown = politics.validate_motion_detail(w, motion("procurement"))
        self.assertEqual(unknown["reason_code"], "UNKNOWN_OFFICE")
        self.assertIn("head, treasury, interior, army, navy", unknown["explanation"])
        self.assertEqual(politics.validate_motion_detail(w, motion(value="maybe"))["reason_code"], "BAD_VALUE")
        self.assertEqual(politics.validate_motion_detail(w, motion(value="close"))["reason_code"], "ALREADY_SET")

    def test_one_audit_of_an_office_at_a_time_and_two_in_all(self):
        w = world()
        hold(w, "army")
        again = politics.validate_motion_detail(w, motion("army"))
        self.assertEqual(again["reason_code"], "ALREADY_SET")
        self.assertIn("reports after Month 2", again["explanation"])
        hold(w, "navy", "C")
        full = politics.validate_motion_detail(w, motion("interior"))
        self.assertEqual(full["reason_code"], "TOO_MANY_OPEN")

    def test_an_office_just_audited_has_to_wait_and_an_inconclusive_one_only_a_little(self):
        w = world()
        hold(w, "army")
        report_with(w, .99, .99)
        w.month += 1
        wait = politics.validate_motion_detail(w, motion("army"))
        self.assertEqual(wait["reason_code"], "RECENTLY_AUDITED")
        self.assertIn("Month 8", wait["explanation"])
        w2 = world()
        hold(w2, "army")
        report_with(w2, 0.0)                                        # blurred: the auditors cannot say
        self.assertEqual(audits.last_done(w2, "army")["verdict"], "inconclusive")
        w2.month += 2
        self.assertIsNone(politics.validate_motion_detail(w2, motion("army")))

    def test_an_audit_under_way_can_be_closed(self):
        w = world()
        hold(w, "army")
        self.assertIsNone(politics.validate_motion_detail(w, motion("army", "close")))
        text = politics.apply_motion(w, motion("army", "close"))
        self.assertEqual(text, "the audit of the Army Command was closed before it reported")
        self.assertEqual(audits.state(w)["open"], [])


class WhileItRuns(unittest.TestCase):
    def test_it_is_ordered_by_a_vote_and_costs_the_member_who_calls_it(self):
        w = world()
        before = standing.ensure(w, "E")["capital"]
        record = resolve(w, motion(), dict.fromkeys("ABCDE", "yes"), {})
        self.assertEqual(record["motions"][0]["execution_status"], "EXECUTED")
        (audit,) = audits.state(w)["open"]
        self.assertEqual((audit["office"], audit["target"], audit["by"], audit["opened"], audit["due"]), ("army", "B", "E", 0, 1))
        self.assertEqual(audit["supporters"], list("ABCDE"))
        self.assertLess(standing.ensure(w, "E")["capital"], before)

    def test_the_office_works_under_strain_and_its_holder_feels_it(self):
        w = world()
        w.institutions["capacity"] = {o: .8 for o in ("head", "treasury", "interior", "army", "navy")}
        self.assertEqual(audits.capacity_penalty(w, "army"), 0.0)
        hold(w, "army")
        self.assertEqual(audits.capacity_penalty(w, "army"), audits.STRAIN)
        self.assertEqual(audits.capacity_penalty(w, "navy"), 0.0)
        before = w.member("B").agent_state["stress"].get("institutional", 10)
        audits.apply_ongoing(w)
        self.assertEqual(w.member("B").agent_state["stress"]["institutional"], round(before + 4, 1))
        cap = standing.update_capacity(w)
        w2 = world()
        w2.institutions["capacity"] = {o: .8 for o in ("head", "treasury", "interior", "army", "navy")}
        self.assertAlmostEqual(standing.update_capacity(w2)["army"] - cap["army"], audits.STRAIN, places=2)

    def test_armed_procurement_slows_while_an_armed_office_is_audited(self):
        w = world()
        self.assertEqual(audits.procurement_factor(w), 1.0)
        hold(w, "interior", "E")
        self.assertEqual(audits.procurement_factor(w), 1.0)
        hold(w, "navy", "C")
        self.assertEqual(audits.procurement_factor(w), audits.PROCUREMENT_DELAY)

        def bought(with_audit):
            x = world()
            if with_audit:
                hold(x, "army")
            for _ in range(2):
                engine.begin_month(x)
                engine.step(x)
            return x.mil.arms
        self.assertLess(bought(True), bought(False))

    def test_the_state_shows_it_and_the_motion_says_what_it_costs(self):
        w = world()
        hold(w, "navy", "C")
        state = decision_context.canonical_hard_state_v2(w, "session", None)
        self.assertIn("Investigations under way: an audit of the Navy Command, ordered in Month 1 by Delegate C, "
                      "reports after Month 2", state)
        block = decision_context.motion_block(world(), "B", [{**motion("army"), "summary": "audit the army"}])
        self.assertIn("reports after 2 months", block)
        self.assertIn("army and navy equipment buying slows", block)

    def test_an_audit_with_missing_initiator_does_not_break_the_briefing(self):
        w = world()
        audits.state(w)["open"].append({"id": "A1-army", "office": "army", "target": None,
                                         "by": "", "opened": 0, "due": 1})
        self.assertIn("ordered in Month 1 by the council", audits.text(w))

    def test_votes_on_it_are_read_by_the_audiences_the_office_answers_to(self):
        w = world()
        for office, tag in (("army", "audit_army"), ("navy", "audit_navy"), ("interior", "audit_interior"),
                            ("treasury", "audit_civil"), ("head", "audit_civil")):
            self.assertEqual(standing.motion_tags(w, motion(office)), [tag], office)
        self.assertEqual(standing.motion_tags(w, motion("army", "close")), [])
        self.assertLess(standing.ACTION_EFFECTS["audit_army"][1]["senior officers"], 0)

    def test_it_is_a_topic_of_its_own(self):
        self.assertEqual(deliberation.topic(motion()), "oversight")
        self.assertIn("oversight", deliberation.TOPICS)

    def test_the_instructions_tell_a_delegate_how(self):
        text = prompts.opening_instructions_v2(world(), "E", 3, list("ABCDE"), 4)
        for phrase in ("MORE LEVERS", "kessel_status and highlands_status", "regional_fund", "officer_pay",
                       "motion type investigation", "value open or close"):
            self.assertIn(phrase, text)


class WhatTheAuditorsFind(unittest.TestCase):
    def test_audit_delivery_events_and_consequences_match_the_month_snapshot(self):
        w = world()
        hold(w, "army", corruption=.09)
        real = audits.rng_for
        audits.rng_for = lambda *_args: FixedRng(.99, .99)
        try:
            for _ in range(2):
                intelligence.generate(w)
                engine.begin_month(w)
                engine.step(w)
        finally:
            audits.rng_for = real

        report = audits.state(w)["done"][-1]
        row = w.history[-1]
        self.assertEqual(report["verdict"], "irregularities")
        self.assertEqual(row["month"], report["month"])
        self.assertTrue(any(event["kind"] == "audit_report" for event in row["events"]))
        self.assertEqual(row["events"], w.last_events)
        self.assertAlmostEqual(row["army_morale"], w.mil.army.morale)
        self.assertAlmostEqual(row["army_bond"], w.mil.army.bond)
        self.assertAlmostEqual(row["league_trust"], w.dip.league_trust)
        self.assertEqual(row["outcome"], w.outcome)
        self.assertTrue(any(x["month"] == row["month"] for x in row["v2"]["contested"]))
        self.assertTrue(any(r["month"] == row["month"] for r in row["v2"]["audits"]["reports"]))

    def test_a_corrupt_office_is_found_out_and_cut_back(self):
        w = world()
        hold(w, "army", corruption=.09, votes={"E": "yes", "A": "yes"})
        report = report_with(w, .99, .99)
        self.assertEqual((report["verdict"], report["accurate"], report["office"], report["target"]), ("irregularities", True, "army", "B"))
        self.assertIn("irregularities found", report["text"])
        self.assertIn("pointing to the office of Delegate B", report["text"])
        self.assertAlmostEqual(w.institutions["corruption"]["army"], .09 * audits.CLEANUP, places=3)
        self.assertGreater(standing.ensure(w, "B")["reputation"]["corrupt"], 25)
        self.assertGreater(standing.ensure(w, "E")["reputation"]["honest"], 50)
        self.assertLess(w.member("D").relationships["B"]["trust"], 50)
        self.assertTrue([e for e in w.events if e["kind"] == "audit_report"] or audits.state(w)["done"])

    def test_a_clean_office_is_cleared_and_the_members_who_called_it_pay(self):
        w = world()
        hold(w, "army", corruption=0.0)
        report = report_with(w, .99, .99)
        self.assertEqual((report["verdict"], report["accurate"]), ("clean", True))
        self.assertEqual(w.institutions["corruption"]["army"], 0.0)
        self.assertGreater(standing.ensure(w, "B")["reputation"]["honest"], 50)
        self.assertGreater(standing.ensure(w, "E")["reputation"]["opportunistic"], 25)
        self.assertLess(w.member("B").relationships["E"]["trust"], 50)
        self.assertTrue([g for g in w.member("B").agent_state.get("grievances", []) if g["against"] == "E"])

    def test_a_blurred_audit_settles_nothing(self):
        w = world()
        hold(w, "army", corruption=.09)
        report = report_with(w, 0.0)
        self.assertEqual((report["verdict"], report["accurate"]), ("inconclusive", None))
        self.assertEqual(w.institutions["corruption"]["army"], .09)
        self.assertIn("neither confirm nor rule out", report["text"])

    def test_a_verdict_can_simply_be_wrong_and_the_record_says_so_but_the_report_does_not(self):
        w = world()
        hold(w, "army", corruption=.09)
        report = report_with(w, .99, 0.0, error_rate=1.0)
        self.assertEqual((report["verdict"], report["accurate"]), ("clean", False))
        self.assertNotIn("wrong", report["text"])
        self.assertTrue(report["truth"]["wrongdoing"])

    def test_an_allegation_that_is_true_is_found_even_where_the_books_are_clean(self):
        w = world()
        w.month = 1
        w.dilemmas = {"active": [issue_dict("corruption_ally", "D", {"true": True})], "history": [], "modifiers": {}}
        hold(w, "treasury", "A", corruption=0.0)
        report = report_with(w, .99, .99)
        self.assertEqual((report["verdict"], report["truth"]["allegation_true"]), ("irregularities", True))

    def test_an_office_is_easier_to_audit_when_the_auditors_are_strong_and_the_books_open(self):
        w = world()
        w.institutions["capacity"] = {"treasury": .9, "head": .9}
        self.assertEqual(audits._auditor_capacity(w, "army"), .9)
        w.institutions["capacity"] = {"treasury": .3, "head": .8}
        self.assertEqual(audits._auditor_capacity(w, "army"), .3)
        self.assertEqual(audits._auditor_capacity(w, "treasury"), .8)          # the Treasury is audited by the Head's office


class TheIssuesItEnds(unittest.TestCase):
    def test_a_procurement_scandal_has_a_fact_behind_it_that_is_not_shown(self):
        w = world()
        w.policy.shipbuilding = True
        w.institutions.setdefault("corruption", {})["navy"] = .1
        import karamaniya.world as world_mod
        rng = world_mod.rng_for(3, 0, "probe")
        details = dilemmas._setup(w, "procurement_scandal", rng)
        self.assertEqual(details["target"], "C")
        self.assertIn("true", details["truth"])
        self.assertNotIn("true", details["text"])

    def test_what_the_audit_finds_ends_the_allegation_about_that_office(self):
        for verdict, draws, outcome in (("irregularities", (.99, .99), "the audit found irregularities in the office"),
                                        ("clean", (.99, .99), "the audit found no wrongdoing"),
                                        ("inconclusive", (0.0,), "the audit was inconclusive and the matter lapsed")):
            w = world()
            corruption = .0 if verdict == "clean" else .09
            hold(w, "army", corruption=corruption)
            issue = issue_dict("procurement_scandal", "B", {"true": corruption > 0})
            w.dilemmas = {"active": [issue], "history": [], "modifiers": {}}
            report = report_with(w, *draws)
            self.assertEqual(report["verdict"], verdict)
            # the month's own review closes the allegation as the report is delivered
            self.assertEqual([(d["id"], d["outcome"]) for d in w.dilemmas["history"]], [("I-procurement_scandal", outcome)], verdict)
            self.assertEqual(w.dilemmas["active"], [])

    def test_a_report_from_an_earlier_month_does_not_end_a_new_allegation(self):
        w = world()
        hold(w, "army")
        report_with(w, .99, .99)
        w.month += 3
        issue = issue_dict("corruption_ally", "B", {"true": True}, month=w.month)
        self.assertIsNone(dilemmas._resolution(w, issue, None))

    def test_the_findings_are_in_every_delegates_memory_and_in_the_state_for_three_months(self):
        w = world()
        hold(w, "army", corruption=.09)
        report_with(w, .99, .99)
        for mid in "ABCDE":
            kinds = [x["kind"] for x in w.member(mid).agent_state["memory"]]
            self.assertIn("audit_report", kinds, mid)
        state = decision_context.canonical_hard_state_v2(w, "session", None)
        self.assertIn("Audit findings (public; auditors can be wrong or unable to say): Audit of the Army Command", state)
        w.month += 4
        self.assertNotIn("Audit findings", decision_context.canonical_hard_state_v2(w, "session", None))


class TheOldArchitecture(unittest.TestCase):
    def test_nothing_runs_in_a_world_that_is_not_the_second_architecture(self):
        w = new_world(3, 6, member_ids=list("ABCDE"), agent_architecture_version=1)
        self.assertEqual((audits.capacity_penalty(w, "army"), audits.procurement_factor(w), audits.deliver(w), audits.text(w)),
                         (0.0, 1.0, [], ""))


if __name__ == "__main__":
    unittest.main()
