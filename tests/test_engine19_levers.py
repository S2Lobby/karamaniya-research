"""Policy values: what a number written for a lever means, and what the engine does when it cannot be read.

Engine 18 audit, slice "policy values": non-finite numbers became policy (CO1), values written in the wrong
units were clamped without a word (MO11, CO10), an alias sent an inflation target to the interest rate (MO16),
and the deployment shares depended on the order of one answer's keys (CO11).
"""
import copy
import dataclasses
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import politics  # noqa: E402
from karamaniya.state_validation import refresh  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

NON_FINITE = ("nan", "NaN", "inf", "-inf", "Infinity", "nan%", "1e400", "9" * 400, float("nan"), float("inf"))


def short(raw) -> str:
    """A value for a subtest label: a four-hundred-digit figure is shown by its start."""
    text = repr(raw)
    return text if len(text) <= 20 else text[:12] + "..."


def motion(lever, value, text="Set the setting.", **extra):
    return {"type": "set_policy", "subject": lever, "value": value, "text": text, "proposer": "A", **extra}


def levers(w):
    """Every value an order can change: the policy settings and the deployment shares."""
    return copy.deepcopy(dataclasses.asdict(w.policy)), dict(w.mil.deploy)


class NonFiniteNumbersAreNoValue(unittest.TestCase):
    """Audit CO1: "nan" and "inf" parse as floats. A NaN passes every bound unchanged, so it became a tax
    rate, then a NaN income in every population, and the state check still said "clean"."""

    def test_every_numeric_parser_refuses_a_non_finite_number(self):
        for raw in NON_FINITE:
            with self.subTest(raw=short(raw)):
                self.assertIsNone(politics._share_value(raw))
                self.assertIsNone(politics.parse_share(raw, 0.0, 1.0))
                for lever in ("tax", "military", "welfare", "rate", "deploy_north", "deploy_capital",
                              "army_target", "import_cap"):
                    self.assertIsNone(politics.parse_lever(lever, raw), lever)
                self.assertIsNone(politics.parse_money(raw))

    def test_a_motion_with_a_non_finite_value_is_refused_as_a_bad_value(self):
        w = new_world(1, member_ids=list("ABCDE"))
        for lever in ("tax", "army_target", "import_cap", "deploy_north"):
            for raw in NON_FINITE:
                with self.subTest(lever=lever, raw=short(raw)):
                    detail = politics.validate_motion_detail(w, motion(lever, raw))
                    self.assertIsNotNone(detail)
                    self.assertEqual(detail["reason_code"], "BAD_VALUE")

    def test_an_order_with_a_non_finite_value_is_logged_invalid_and_changes_nothing(self):
        cases = (("treasury", "tax"), ("treasury", "welfare"), ("treasury", "import_cap"),
                 ("army", "army_target"), ("army", "deploy_north"))
        for office, lever in cases:
            for raw in NON_FINITE:
                with self.subTest(lever=lever, raw=short(raw)):
                    w = new_world(1, member_ids=list("ABCDE"))
                    w.const.offices.update({"treasury": "A", "army": "A"})
                    before = levers(w)
                    history, adjusted = [], []
                    politics.apply_orders(w, "A", {office: {lever: raw}}, order_history=history,
                                          adjusted=adjusted)
                    self.assertEqual(levers(w), before)
                    self.assertEqual([h["status"] for h in history], ["invalid"])
                    self.assertEqual([a["applied"] for a in adjusted], [None])


class AKeyWrittenIntoAValueIsNotTheValue(unittest.TestCase):
    """Found while reading the set_policy path (not in the audit): validation drops a key a model has written
    into the value ("value=0.035") and accepts the motion, but the motion was then applied from the raw text,
    so the setting and its directive became None."""

    def test_a_passed_keyed_value_is_applied_as_its_number(self):
        w = new_world(1, member_ids=list("ABCDE"))
        mo = motion("farm_support", "value=0.035", "Increase farm support to 3.5% of output.")
        self.assertIsNone(politics.validate_motion_detail(w, dict(mo)))
        politics.apply_motion(w, {**mo, "passed": True})
        self.assertEqual(w.policy.farm_support, 0.035)
        self.assertEqual(w.const.directives["farm_support"], 0.035)
        self.assertEqual(politics.directive_bounds(w, dict(mo))[0], {"min": 0.035, "max": 0.035})


class StateCheckReportsNonFiniteFigures(unittest.TestCase):
    """state_validation must say so when a policy lever, an economic figure or an income is not finite."""

    def warnings(self, w):
        result = refresh(w)
        return [x for x in result["warnings"] if x["code"] == "invalid_numeric_state"]

    def test_a_clean_world_is_clean(self):
        w = new_world(1, member_ids=list("ABCDE"))
        self.assertEqual(refresh(w)["status"], "clean")

    def test_a_non_finite_policy_lever_is_reported(self):
        for lever, value in (("tax", float("nan")), ("army_target", float("inf")), ("import_cap", float("nan"))):
            with self.subTest(lever=lever):
                w = new_world(1, member_ids=list("ABCDE"))
                setattr(w.policy, lever, value)
                found = self.warnings(w)
                self.assertTrue(any(lever in x["detail"] for x in found), found)

    def test_a_non_finite_deployment_share_is_reported(self):
        w = new_world(1, member_ids=list("ABCDE"))
        w.mil.deploy["north"] = float("nan")
        self.assertTrue(any("north" in x["detail"] for x in self.warnings(w)))

    def test_a_non_finite_economic_figure_is_reported(self):
        for name in ("deficit", "revenue", "gdp_nominal"):
            with self.subTest(name=name):
                w = new_world(1, member_ids=list("ABCDE"))
                setattr(w.econ, name, float("inf"))
                self.assertTrue(any(name in x["detail"] for x in self.warnings(w)))

    def test_a_non_finite_population_income_is_reported(self):
        w = new_world(1, member_ids=list("ABCDE"))
        w.pops[0].income = float("nan")
        found = self.warnings(w)
        self.assertEqual(len(found), 1, found)
        self.assertIn("income", found[0]["detail"])


class ValuesOutsideTheirRangeAreRefusedNotClamped(unittest.TestCase):
    """Audit MO11: a motion's value was read as a share and held to the nearest bound without a word. "military
    0.8", written for 0.8%, became 80% and then 20% of output; "rate 1", written for 1%, a 100% interest rate.
    Audit CO10: an office order is held the same way, and the record says so (lever_adjustment)."""

    def setUp(self):
        self.w = new_world(1, member_ids=list("ABCDE"))
        self.w.const.offices.update({"treasury": "A", "army": "A"})

    def test_a_value_outside_its_range_is_refused_with_a_code_that_names_the_range(self):
        cases = (("military", "0.8", "Raise military spending to 0.8 of output."),
                 ("welfare", "0.20", "Raise welfare support to 20 percent of spending."),
                 ("tax", "0.9", "Raise the tax to 90% of output."),
                 ("army_target", "3100", "Cut the army target to 3,100."),
                 ("import_cap", "-5", "Set a negative import cap."))
        for lever, value, text in cases:
            with self.subTest(lever=lever, value=value):
                detail = politics.validate_motion_detail(self.w, motion(lever, value, text))
                self.assertIsNotNone(detail, "the value was accepted, and clamped")
                self.assertEqual(detail["reason_code"], "VALUE_OUT_OF_RANGE")
                self.assertIn("range", detail["explanation"])
                self.assertIn(lever, detail["explanation"])

    def test_the_refusal_states_the_range_within_the_words_a_delegate_sees_next_month(self):
        detail = politics.validate_motion_detail(self.w, motion("military", "0.8", "Raise military spending to 0.8 of output."))
        self.assertIsNotNone(detail, "the value was accepted, and clamped")
        self.assertIn("0.5% to 20%", detail["explanation"])
        self.assertLess(detail["explanation"].index("0.5%"), 300)
        army = politics.validate_motion_detail(self.w, motion("army_target", "3100", "Cut the army target."))
        self.assertIsNotNone(army, "the army target was accepted, and clamped")
        self.assertIn("5,000 to 400,000", army["explanation"])

    def test_a_value_at_either_bound_is_accepted(self):
        cases = (("military", "0.005"), ("military", "0.2"), ("welfare", "0"), ("welfare", "0.15"),
                 ("farm_support", "0.05"), ("tax", "60%"), ("army_target", "5000"), ("army_target", "400000"),
                 ("import_cap", "0"), ("deploy_north", "1"))
        for lever, value in cases:
            with self.subTest(lever=lever, value=value):
                self.assertIsNone(politics.validate_motion_detail(self.w, motion(lever, value, "Set it.")))

    def test_a_share_the_text_writes_with_a_percent_sign_is_read_as_that_percent(self):
        mo = motion("military", "0.8", "Raise military spending to 0.8% of output.")
        self.assertIsNone(politics.validate_motion_detail(self.w, dict(mo)))
        result = politics.apply_motion(self.w, {**mo, "passed": True})
        self.assertAlmostEqual(self.w.policy.military, 0.008)
        self.assertAlmostEqual(self.w.const.directives["military"], 0.008)
        self.assertIn("read as 0.8%", result)

    def test_the_directive_bounds_use_the_same_reading(self):
        bound, clashes = politics.directive_bounds(
            self.w, motion("military", "0.8", "Raise military spending to 0.8% of output."))
        self.assertEqual(clashes, [])
        self.assertEqual(bound, {"min": 0.008, "max": 0.008})

    def test_a_rate_written_with_a_percent_sign_is_read_as_that_percent(self):
        mo = motion("rate", "1", "Set the policy interest rate to 1%.")
        self.assertIsNone(politics.validate_motion_detail(self.w, dict(mo)))
        politics.apply_motion(self.w, {**mo, "passed": True})
        self.assertAlmostEqual(self.w.policy.rate, 0.01)

    def test_a_percent_the_range_cannot_hold_is_refused_not_clamped(self):
        detail = politics.validate_motion_detail(self.w, motion("tax", "1", "Raise the tax share to 1% of output."))
        self.assertIsNotNone(detail, "the value was accepted, and clamped")
        self.assertEqual(detail["reason_code"], "VALUE_OUT_OF_RANGE")

    def test_a_number_the_text_does_not_write_as_a_percent_is_not_reread(self):
        mo = motion("military", "0.1", "Raise military spending to 10% of output.")
        self.assertIsNone(politics.validate_motion_detail(self.w, dict(mo)))
        result = politics.apply_motion(self.w, {**mo, "passed": True})
        self.assertAlmostEqual(self.w.policy.military, 0.1)
        self.assertNotIn("read as", result)

    def test_an_order_outside_its_range_is_held_to_the_bound_and_the_record_says_so(self):
        adjusted = []
        politics.apply_orders(self.w, "A", {"treasury": {"military": 0.8}}, adjusted=adjusted)
        self.assertEqual(self.w.policy.military, 0.2)
        self.assertEqual([(a["lever"], a["requested"], a["applied"]) for a in adjusted], [("military", 0.8, 0.2)])

    def test_an_import_cap_order_held_to_a_bound_is_recorded_too(self):
        adjusted = []
        politics.apply_orders(self.w, "A", {"treasury": {"import_cap": -5}}, adjusted=adjusted)
        self.assertEqual(self.w.policy.import_cap, 0.0)
        self.assertEqual([(a["lever"], a["requested"], a["applied"]) for a in adjusted], [("import_cap", -5, 0.0)])

    def test_the_refusal_is_a_registered_code_and_reaches_the_author_next_month(self):
        from karamaniya import errors
        from karamaniya.council import _rejected_last_month
        self.assertTrue(errors.is_registered("VALUE_OUT_OF_RANGE"))
        mo = motion("military", "0.8", "Raise military spending to 0.8 of output.")
        detail = politics.validate_motion_detail(self.w, dict(mo))
        self.assertIsNotNone(detail, "the value was accepted, and clamped")
        record = {"rejected_motions": [{"member": "A", "motion": {"type": "set_policy", "subject": "military",
                                                                  "value": "0.8", "text": mo["text"]}, **detail}]}
        text = _rejected_last_month(record, "A")[0].text
        self.assertIn("VALUE_OUT_OF_RANGE", text)
        self.assertIn("0.5% to 20%", text)


class DeploymentSharesDoNotDependOnTheOrderOfKeys(unittest.TestCase):
    """Audit CO11: each deployment share renormalised the others, so the shares one answer set depended on the order
    its keys were written in. The shares of an answer are all set, then normalised once."""

    ORDERS = {"deploy_north": 0.4, "deploy_east": 0.3, "deploy_capital": 0.3}

    def deploy_after(self, keys):
        w = new_world(1, 12, member_ids=list("ABCDE"))
        w.const.offices["army"] = "A"
        history = []
        politics.apply_orders(w, "A", {"army": {k: self.ORDERS[k] for k in keys}}, order_history=history,
                              adjusted=[])
        return {k: round(v, 9) for k, v in w.mil.deploy.items()}, history

    def test_three_shares_that_sum_to_one_end_as_written_whatever_the_key_order(self):
        keys = list(self.ORDERS)
        forward, _ = self.deploy_after(keys)
        backward, _ = self.deploy_after(list(reversed(keys)))
        self.assertEqual(forward, backward)
        self.assertEqual(forward, {"north": 0.4, "east": 0.3, "capital": 0.3})

    def test_the_record_shows_the_shares_the_answer_left(self):
        keys = list(self.ORDERS)
        for order in (keys, list(reversed(keys))):
            final, history = self.deploy_after(order)
            self.assertEqual(len(history), 3)
            for row in history:
                with self.subTest(order=order, lever=row["lever"]):
                    self.assertEqual(row["status"], "applied")
                    self.assertAlmostEqual(row["actual_value"], final[row["lever"][len("deploy_"):]], places=9)

    def test_a_single_share_set_alone_is_normalised_as_before(self):
        w = new_world(1, 12, member_ids=list("ABCDE"))
        w.const.offices["army"] = "A"
        politics.apply_orders(w, "A", {"army": {"deploy_north": 0.6}}, adjusted=[])
        total = 0.6 + 0.25 + 0.40          # the default split is 0.35 / 0.25 / 0.40; only north is set
        self.assertAlmostEqual(w.mil.deploy["north"], 0.6 / total)
        self.assertAlmostEqual(w.mil.deploy["east"], 0.25 / total)
        self.assertAlmostEqual(w.mil.deploy["capital"], 0.40 / total)


class AnInflationTargetIsNotTheInterestRate(unittest.TestCase):
    """Audit MO16: "inflation_rate" was an alias for the interest rate. There is no inflation-target setting, and an
    alias must mean the same setting, so a motion on an inflation target set the policy rate instead."""

    def test_the_alias_is_gone_and_an_inflation_motion_is_refused_as_an_unknown_lever(self):
        from karamaniya import actions, foreign
        self.assertNotIn("inflation_rate", politics.LEVER_ALIASES)
        self.assertEqual(politics.canonical_lever("interest_rate"), "rate")
        w = new_world(11, 36)
        w.foreign = foreign.initial_state(w.seed)
        w.agent_architecture_version = 2
        w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
        raw = {"type": "set_policy", "subject": "inflation_rate", "value": "0.03",
               "text": "Set the inflation rate target at 3% a year to stabilise prices."}
        mo = {**actions.normalize_motion_v2(w, raw), "proposer": "A"}
        self.assertNotEqual(mo["subject"], "rate")
        detail = politics.validate_motion_detail(w, dict(mo))
        self.assertIsNotNone(detail, "an inflation target was accepted as the interest rate")
        self.assertEqual(detail["reason_code"], "UNKNOWN_LEVER")
        self.assertEqual(w.const.directives.get("rate"), None)


if __name__ == "__main__":
    unittest.main()
