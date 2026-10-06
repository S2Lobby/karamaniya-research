"""Regional policy: how far the capital rules Kessel Valley and the Vell Highlands, and what it spends there.

The gap it closes: Kessel came up in every one of the first ten months, the regional_autonomy, separatist_rally
and governor_defiance issues were live, and the council had no lever for any of it beyond policing and a word in
a Charter amendment."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, dilemmas, engine, intelligence, politics, regional  # noqa: E402
from karamaniya.world import new_world  # noqa: E402
from tests.test_orders_vs_directives import resolve, world  # noqa: E402


def run(setup=None, months=8, seed=3):
    w = new_world(seed, 24, member_ids=list("ABCDE"))
    w.const.offices.update({"head": "A", "treasury": "D", "interior": "E", "army": "B", "navy": "C"})
    if setup:
        setup(w)
    for _ in range(months):
        engine.begin_month(w)
        engine.step(w)
    return w


def region(w, rid, attr):
    pops = [p for p in w.pops if p.region == rid]
    return sum(getattr(p, attr) * p.size for p in pops) / sum(p.size for p in pops)


def set_status(rid, status):
    return lambda w: setattr(w.const, f"{rid}_status", status)


def effects(w):
    got = {}
    regional.effects(w, lambda kind, where, value: got.__setitem__((kind, where), got.get((kind, where), 0) + value))
    return got


class TheSettings(unittest.TestCase):
    def test_status_is_a_charter_setting_and_the_fund_a_treasury_one(self):
        self.assertEqual(politics.CONSTITUTION_FIELDS["kessel_status"], ("central", "cultural", "devolved"))
        self.assertEqual(politics.CONSTITUTION_FIELDS["highlands_status"], ("central", "cultural", "devolved"))
        self.assertEqual(politics.LEVER_OFFICE["regional_fund"], "treasury")
        self.assertEqual(politics.ENUMS["regional_fund"], ("none", "kessel", "highlands", "both"))
        self.assertIn("regional_fund", actions._office_levers("treasury"))

    def test_a_status_passes_by_vote_and_cannot_be_repeated_or_misspelt(self):
        w = world()
        motion = {"id": "M1", "proposer": "A", "type": "constitution", "subject": "highlands_status", "value": "cultural",
                  "text": "", "summary": "constitution: highlands_status = cultural"}
        record = resolve(w, motion, {"A": "yes", "B": "yes", "C": "yes", "D": "no", "E": "yes"}, {})
        self.assertEqual(record["motions"][0]["result"], "Vell Highlands status set to cultural (was central)")
        self.assertEqual(w.const.highlands_status, "cultural")
        self.assertEqual(politics.validate_motion_detail(w, {**motion, "proposer": "A"})["reason_code"], "ALREADY_SET")
        bad = politics.validate_motion_detail(w, {**motion, "value": "autonomy", "proposer": "A"})
        self.assertEqual(bad["reason_code"], "BAD_VALUE")
        self.assertIn("central, cultural, devolved", bad["explanation"])

    def test_the_fund_is_a_directive_like_any_other(self):
        w = world()
        record = resolve(w, {"id": "M1", "proposer": "D", "type": "set_policy", "subject": "regional_fund", "value": "kessel",
                             "text": "", "summary": "directive regional_fund = kessel"}, dict.fromkeys("ABCDE", "yes"), {})
        self.assertEqual(record["motions"][0]["execution_status"], "EXECUTED")
        self.assertEqual((w.policy.regional_fund, w.const.directives["regional_fund"]), ("kessel", "kessel"))

    def test_the_canonical_state_says_who_governs_what(self):
        w = world()
        self.assertEqual(regional.text(w), "Regions (Charter status): Kessel Valley central; Vell Highlands central. "
                                            "Regional development fund: none.")
        resolve(w, {"id": "M1", "proposer": "A", "type": "constitution", "subject": "kessel_status", "value": "devolved",
                    "text": "", "summary": ""}, dict.fromkeys("ABCDE", "yes"), {})
        w.policy.regional_fund = "both"
        self.assertEqual(regional.text(w), "Regions (Charter status): Kessel Valley devolved (since Month 1); "
                                            "Vell Highlands central. Regional development fund: Kessel Valley and Vell Highlands.")


class WhatStatusDoes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.central = run()
        cls.cultural = run(set_status("highlands", "cultural"))
        cls.devolved = run(set_status("highlands", "devolved"))
        cls.kessel = run(set_status("kessel", "devolved"))

    def test_the_region_is_calmer_the_further_the_settlement_goes(self):
        g = [region(x, "highlands", "grievance") for x in (self.central, self.cultural, self.devolved)]
        self.assertGreater(g[0], g[1] + .02)
        self.assertGreater(g[1], g[2] + .02)
        a = [region(x, "highlands", "approval") for x in (self.central, self.cultural, self.devolved)]
        self.assertEqual(a, sorted(a))
        i = [region(x, "highlands", "indep") for x in (self.central, self.cultural, self.devolved)]
        self.assertEqual(i, sorted(i))

    def test_the_other_region_notices_what_it_did_not_get(self):
        self.assertGreater(region(self.devolved, "kessel", "grievance"), region(self.central, "kessel", "grievance") + .015)
        self.assertGreater(region(self.kessel, "highlands", "grievance"), region(self.central, "highlands", "grievance") + .01)

    def test_kessel_answers_to_the_same_treatment(self):
        self.assertLess(region(self.kessel, "kessel", "grievance"), region(self.central, "kessel", "grievance") - .04)
        self.assertGreater(region(self.kessel, "kessel", "indep"), region(self.central, "kessel", "indep"))

    def test_a_settlement_beside_a_restricted_minority_is_worth_half(self):
        full = regional.STATUS_EFFECT["highlands"]["devolved"]
        w = world()
        w.const.highlands_status = "devolved"
        for kind in ("grievance", "approval", "indep"):
            self.assertAlmostEqual(effects(w)[(kind, "highlands")], full[kind], msg=kind)
        w.const.minority = "restricted"
        for kind in ("grievance", "approval", "indep"):
            self.assertAlmostEqual(effects(w)[(kind, "highlands")], full[kind] * .5, msg=kind)
        w.const.kessel_status = "devolved"                       # Kessel's settlement does not depend on the Vell's rights
        self.assertAlmostEqual(effects(w)[("grievance", "kessel")], regional.STATUS_EFFECT["kessel"]["devolved"]["grievance"])

    def test_the_union_takes_back_some_of_what_kessels_status_buys(self):
        w = world()
        w.const.kessel_status = "devolved"
        calm = effects(w)[("indep", "kessel")]
        w.dip.union_formed = True
        worked = effects(w)[("indep", "kessel")]
        self.assertLess(worked, calm)
        self.assertGreater(worked, 0)

    def test_taking_a_status_back_is_worse_than_never_granting_it(self):
        w = run(set_status("highlands", "devolved"), months=3)
        before = region(w, "highlands", "grievance"), region(w, "highlands", "approval")
        text = politics.apply_motion(w, {"type": "constitution", "subject": "highlands_status", "value": "central", "proposer": "A"})
        self.assertEqual(text, "Vell Highlands status set to central (was devolved)")
        self.assertGreater(region(w, "highlands", "grievance"), before[0] + .1)
        self.assertLess(region(w, "highlands", "approval"), before[1] - .05)
        self.assertTrue([e for e in w.events if e["kind"] == "regional_status" and "taken back" in e["text"]])

    def test_a_status_costs_money_a_month(self):
        base = run(months=1)
        for status in ("cultural", "devolved"):
            w = run(set_status("kessel", status), months=1)
            self.assertAlmostEqual((w.econ.spending - base.econ.spending) / w.econ.gdp_nominal, regional.UPKEEP[status],
                                   delta=1e-4, msg=status)


class WhatTheFundDoes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.none = run()
        cls.kessel = run(lambda w: setattr(w.policy, "regional_fund", "kessel"))
        cls.both = run(lambda w: setattr(w.policy, "regional_fund", "both"))

    def test_incomes_rise_in_the_funded_region_only(self):
        self.assertGreater(region(self.kessel, "kessel", "income"), region(self.none, "kessel", "income") + .03)
        self.assertAlmostEqual(region(self.kessel, "highlands", "income"), region(self.none, "highlands", "income"), delta=.005)
        self.assertGreater(region(self.both, "highlands", "income"), region(self.none, "highlands", "income") + .03)

    def test_it_calms_the_region_without_touching_the_charter_or_the_other_region(self):
        self.assertLess(region(self.kessel, "kessel", "grievance"), region(self.none, "kessel", "grievance") - .02)
        self.assertAlmostEqual(region(self.kessel, "highlands", "grievance"), region(self.none, "highlands", "grievance"), delta=.005)
        self.assertEqual((self.kessel.const.kessel_status, self.kessel.const.highlands_status), ("central", "central"))

    def test_the_region_builds_up_industry_to_a_cap(self):
        self.assertGreater(self.kessel.institutions["regional"]["industry_gain"]["kessel"], .01)
        w = world()
        w.policy.regional_fund = "kessel"
        for _ in range(60):
            regional.effects(w, lambda *a: None)
        self.assertAlmostEqual(w.institutions["regional"]["industry_gain"]["kessel"],
                               regional.FUND_INDUSTRY_CAP)

    def test_a_partially_paid_fund_cannot_overshoot_the_industry_cap(self):
        w = world()
        w.policy.regional_fund = "kessel"
        w.econ.paid_share = 0.73
        for _ in range(60):
            regional.effects(w, lambda *a: None)
        self.assertLessEqual(w.institutions["regional"]["industry_gain"]["kessel"],
                             regional.FUND_INDUSTRY_CAP)
        self.assertAlmostEqual(w.institutions["regional"]["industry_gain"]["kessel"],
                               regional.FUND_INDUSTRY_CAP)

    def test_it_costs_a_share_of_output_per_region_and_costing_says_so(self):
        base = run(months=1)
        for fund, count in (("kessel", 1), ("highlands", 1), ("both", 2)):
            w = run(lambda w, fund=fund: setattr(w.policy, "regional_fund", fund), months=1)
            self.assertAlmostEqual((w.econ.spending - base.econ.spending) / w.econ.gdp_nominal, count * regional.FUND_COST, delta=1e-4)
        w = world()
        w.econ.gdp_nominal = 500e6
        cost = lambda value: intelligence.costing(w, {"type": "set_policy", "subject": "regional_fund", "value": value})
        self.assertAlmostEqual(cost("kessel"), regional.FUND_COST * 500e6)
        self.assertAlmostEqual(cost("both"), 2 * regional.FUND_COST * 500e6)
        w.policy.regional_fund = "both"
        self.assertAlmostEqual(cost("kessel"), -regional.FUND_COST * 500e6)

    def test_money_that_was_not_paid_buys_nothing(self):
        w = world()
        w.policy.regional_fund = "kessel"
        w.econ.paid_share = 0.0
        self.assertEqual(regional.income_boost(w, "kessel"), 0.0)
        w.econ.paid_share = 1.0
        self.assertAlmostEqual(regional.income_boost(w, "kessel"), regional.FUND_INCOME)
        self.assertEqual(regional.income_boost(w, "highlands"), 0.0)


class TheIssuesItSettles(unittest.TestCase):
    def issue(self, kind, month=0, **extra):
        return {"kind": kind, "month": month, "truth": {}, "applied": {}, **extra}

    def test_a_highlands_settlement_answers_the_autonomy_demand_and_stops_it_recurring(self):
        w = world()
        w.month = 3
        issue = self.issue("regional_autonomy", month=2)
        self.assertIsNone(dilemmas._resolution(w, issue, None))
        politics.apply_motion(w, {"type": "constitution", "subject": "highlands_status", "value": "cultural", "proposer": "A"})
        self.assertEqual(dilemmas._resolution(w, issue, None), "the council granted regional autonomy")
        self.assertEqual(dilemmas._w_autonomy(w), 0)

    def test_a_settlement_from_before_the_issue_does_not_count_as_its_answer(self):
        w = world()
        politics.apply_motion(w, {"type": "constitution", "subject": "highlands_status", "value": "cultural", "proposer": "A"})
        w.month = 6
        self.assertIsNone(dilemmas._resolution(w, self.issue("regional_autonomy", month=5), None))

    def test_a_governor_has_less_to_defy_where_the_region_is_settled(self):
        w = world()
        for p in w.pops:
            if p.region == "highlands":
                p.grievance = .6
        weights = []
        for status in ("central", "cultural", "devolved"):
            w.const.highlands_status = status
            weights.append(dilemmas._w_governor(w))
        self.assertGreater(weights[0], weights[1])
        self.assertGreater(weights[1], weights[2])

    def test_a_governor_standoff_ends_with_the_settlement_or_the_money(self):
        w = world()
        w.month = 4
        issue = self.issue("governor_defiance", month=3, region="highlands")
        self.assertIsNone(dilemmas._resolution(w, issue, None))
        w.policy.regional_fund = "highlands"
        self.assertEqual(dilemmas._resolution(w, issue, None), "regional funding brought the governor to terms")
        w.policy.regional_fund = "none"
        w.const.highlands_status = "devolved"
        w.institutions["regional"] = {"changes": [{"month": 4, "region": "highlands", "from": "central", "to": "devolved"}]}
        self.assertEqual(dilemmas._resolution(w, issue, None), "the Vell Highlands settlement ended the standoff")

    def test_a_blockade_in_kessel_ends_with_a_negotiated_settlement_when_the_region_is_funded(self):
        w = world()
        issue = self.issue("rail_blockade", region="kessel")
        self.assertIsNone(dilemmas._resolution(w, issue, None))
        w.policy.regional_fund = "kessel"
        self.assertEqual(dilemmas._resolution(w, issue, None), "a negotiated settlement reopened the line")


class TheOldArchitecture(unittest.TestCase):
    def test_nothing_happens_in_a_world_that_is_not_the_second_architecture(self):
        w = new_world(3, 6, member_ids=list("ABCDE"), agent_architecture_version=1)
        w.const.highlands_status = "devolved"
        w.policy.regional_fund = "both"
        got = []
        regional.effects(w, lambda *a: got.append(a))
        self.assertEqual((got, regional.spending(w), regional.income_boost(w, "kessel"), regional.text(w)), ([], 0.0, 0.0, ""))


if __name__ == "__main__":
    unittest.main()
