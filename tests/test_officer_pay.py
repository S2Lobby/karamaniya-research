"""Officer pay: an Army Command setting the council can direct, with a cost and consequences.

The gap it closes: delegates raised officer pay and retention in four months out of ten and invented settings for
it (army_training_focus, army_recruitment_focus readiness_pay_discipline), because the only lever there was was the
military budget share. The petition and pay-crisis issues had nothing to resolve them with but money in general."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, dilemmas, engine, intelligence, military, politics, standing  # noqa: E402
from tests.test_orders_vs_directives import resolve, world  # noqa: E402

LEVELS = ("freeze", "standard", "raised", "premium")


def run(level, months=12, patronage=False, military_share=None):
    w = world()
    w.months_total = 24
    w.policy.officer_pay = level
    w.policy.patronage["army"] = patronage
    if military_share:
        w.policy.military = military_share
    for _ in range(months):
        engine.begin_month(w)
        engine.step(w)
    return w


class TheScale(unittest.TestCase):
    def test_the_levels_are_ordered_in_cost_and_in_what_they_buy(self):
        rows = [military.OFFICER_PAY[k] for k in LEVELS]
        for key in ("bill", "morale", "loyalty", "training"):
            values = [r[key] for r in rows]
            self.assertEqual(values, sorted(values), key)
        desertion = [r["desert"] for r in rows]
        self.assertEqual(desertion, sorted(desertion, reverse=True))
        self.assertEqual(military.OFFICER_PAY["standard"], {"bill": 1.0, "morale": 0.0, "loyalty": 0.0, "desert": 1.0, "training": 0.0})

    def test_it_is_an_army_setting_with_four_values_and_an_order_field(self):
        w = world()
        self.assertEqual(politics.LEVER_OFFICE["officer_pay"], "army")
        self.assertEqual(politics.ENUMS["officer_pay"], LEVELS)
        self.assertIn("officer_pay", actions._office_levers("army"))
        self.assertEqual(actions._lever_schema("officer_pay"), {"type": "string", "enum": list(LEVELS)})
        schema = actions.decision_schema_v2(w, "B", [])["properties"]["orders"]["properties"]["army"]
        self.assertEqual(schema["properties"]["officer_pay"]["enum"], list(LEVELS))

    def test_a_directive_takes_hold_and_a_bad_value_names_the_choices(self):
        w = world()
        record = resolve(w, {"id": "M1", "proposer": "B", "type": "set_policy", "subject": "officer_pay",
                             "value": "raised", "text": "", "summary": "directive officer_pay = raised"},
                         dict.fromkeys("ABCDE", "yes"), {})
        self.assertEqual(record["motions"][0]["execution_status"], "EXECUTED")
        self.assertEqual((w.policy.officer_pay, w.const.directives["officer_pay"]), ("raised", "raised"))
        bad = politics.validate_motion_detail(world(), {"type": "set_policy", "subject": "officer_pay",
                                                        "value": "generous", "proposer": "B"})
        self.assertEqual(bad["reason_code"], "BAD_VALUE")
        self.assertIn("freeze, standard, raised, premium", bad["explanation"])

    def test_defying_the_directive_is_recorded_like_any_other(self):
        w = world()
        politics.apply_motion(w, {"type": "set_policy", "subject": "officer_pay", "value": "raised", "proposer": "B"})
        defiance = politics.apply_orders(w, "B", {"army": {"officer_pay": "freeze"}}, set(), [])
        self.assertEqual([(d["lever"], d["directive"], d["value"]) for d in defiance], [("officer_pay", "raised", "freeze")])
        self.assertEqual(w.policy.officer_pay, "freeze")


class WhatItDoes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worlds = {level: run(level) for level in LEVELS}

    def test_morale_loyalty_and_training_follow_the_scale(self):
        for attr in ("morale", "loyalty", "training"):
            values = [getattr(self.worlds[k].mil.army, attr) for k in LEVELS]
            self.assertEqual(values, sorted(values), attr)
            self.assertGreater(values[-1] - values[0], .04, attr)

    def test_a_raise_costs_the_pay_bill_and_costing_says_so(self):
        w = world()
        bill = w.mil.army.size * military.ARMY_COST * w.econ.cpi
        cost = lambda value: intelligence.costing(w, {"type": "set_policy", "subject": "officer_pay", "value": value})
        self.assertAlmostEqual(cost("raised"), .12 * bill, delta=1)
        self.assertAlmostEqual(cost("premium"), .28 * bill, delta=1)
        self.assertLess(cost("freeze"), 0)
        self.assertAlmostEqual(cost("standard"), 0.0, delta=1)

    def test_on_a_tight_budget_the_pay_comes_out_of_equipment(self):
        standard, premium = run("standard", military_share=.025), run("premium", military_share=.025)
        self.assertLess(premium.mil.army.equipment, standard.mil.army.equipment - .1)

    def test_an_army_run_on_patronage_credits_the_states_pay_for_less(self):
        gain = lambda patronage: (run("premium", patronage=patronage).mil.army.loyalty
                                  - run("standard", patronage=patronage).mil.army.loyalty)
        self.assertGreater(gain(False), 0)
        self.assertLess(gain(True), gain(False) * .8)
        self.assertGreater(gain(True), 0)

    def test_a_freeze_is_read_by_the_audiences_that_care_and_a_raise_by_the_others(self):
        w = world()
        raised = standing.motion_tags(w, {"type": "set_policy", "subject": "officer_pay", "value": "raised"})
        frozen = standing.motion_tags(w, {"type": "set_policy", "subject": "officer_pay", "value": "freeze"})
        self.assertEqual((raised, frozen), (["officer_pay_up"], ["officer_pay_down"]))
        self.assertLess(standing.ACTION_EFFECTS["officer_pay_down"][1]["senior officers"], 0)
        self.assertGreater(standing.ACTION_EFFECTS["officer_pay_up"][1]["senior officers"], 0)


class TheIssuesItSettles(unittest.TestCase):
    def test_a_frozen_scale_invites_a_petition_and_a_raised_one_does_not(self):
        weights = {}
        for level in LEVELS:
            w = world()
            w.mil.army.morale = .5
            w.policy.officer_pay = level
            weights[level] = dilemmas._w_petition(w)
        self.assertGreater(weights["freeze"], weights["standard"])
        self.assertEqual(weights["raised"], 0)
        self.assertEqual(weights["premium"], 0)

    def test_a_petition_ends_when_the_council_raises_officers_pay(self):
        w = world()
        w.policy.officer_pay = "raised"
        issue = {"kind": "officer_petition", "month": w.month, "truth": {}, "applied": {}}
        self.assertEqual(dilemmas._resolution(w, issue, None), "the council raised officers' pay")
        w2 = world()
        self.assertIsNone(dilemmas._resolution(w2, {**issue}, None))
        w2.policy.military = .05
        self.assertEqual(dilemmas._resolution(w2, {**issue}, None), "the council raised military funding")


if __name__ == "__main__":
    unittest.main()
