"""Three refusals at intake that were wrong (HANDOFF section 9.E E5, E6 and section 9.F F3).

E6: a loan whose amount is written in its text ("50M gold") was refused as BAD_LOAN_AMOUNT. The text is now read,
    and the amount is taken only when the value and the text name exactly one amount, with a unit.
F3: a number in braces or brackets ("{0.35}") was refused as a bad value. One matched pair is taken off; a placeholder
    or a fragment stays a refusal.
E5: an unknown lever that is, or nearly is, a constitution setting now says it is changed by a constitution motion.
    The census input itself (`set_policy highlands_status cultural`) is already a constitution motion at intake
    (actions.normalize_motion_v2, engine 8); the guard test below records that.

Tests marked "guard" pass on the old code too: they hold what must not change.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, politics  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

LEAGUE_ACTION = {"action_type": "loan_request", "target": "Maritime League"}
EMERGENCY_TEXT = ("Request emergency loan from Maritime League: 50M gold, secured by future export revenues and "
                  "trade surpluses. Terms to include no austerity conditions.")


def world():
    return new_world(11)


def loan(value="", text=EMERGENCY_TEXT, action=None):
    return {"type": "diplomacy", "subject": "loan", "value": value, "text": text, "proposer": "B",
            "action": dict(LEAGUE_ACTION) if action is None else action}


def motion(lever, value, text="Set the setting.", **extra):
    return {"type": "set_policy", "subject": lever, "value": value, "text": text, "proposer": "A", **extra}


class LoanAmountWrittenInTheText(unittest.TestCase):
    def test_an_amount_written_in_the_text_passes_and_is_written_back(self):
        w = world()
        mo = loan()
        self.assertIsNone(politics.validate_motion_detail(w, mo))
        self.assertEqual(mo["value"], "50")

    def test_the_value_with_a_parenthesis_names_its_amount(self):
        w = world()
        mo = loan(value="100 million gold (max available without default)",
                  text="Request emergency loan from Maritime League.")
        self.assertIsNone(politics.validate_motion_detail(w, mo))
        self.assertEqual(mo["value"], "100")

    def test_the_unit_spellings_all_read_as_millions(self):
        w = world()
        for written, want in (("50M gold", "50"), ("50 million gold", "50"), ("50,000,000 gold", "50"),
                              ("1.5 billion gold", "1500"), ("500k gold", "0.5"), ("50million", "50")):
            with self.subTest(written=written):
                mo = loan(text=f"Request a loan of {written} from the Maritime League.")
                self.assertIsNone(politics.validate_motion_detail(w, mo))
                self.assertEqual(mo["value"], want)

    def test_a_text_without_an_amount_is_refused_and_says_so(self):
        w = world()
        problem = politics.validate_motion_detail(w, loan(
            text="Request emergency loan from Maritime League to cover deficit and service debt, contingent on "
                 "maintaining independent currency."))
        self.assertEqual(problem["reason_code"], "BAD_LOAN_AMOUNT")
        self.assertIn("names no amount", problem["explanation"])

    def test_several_amounts_are_refused_and_each_is_named(self):
        w = world()
        problem = politics.validate_motion_detail(w, loan(
            text="Request a loan of 15 million gold for grain, and 50M gold for the reserves."))
        self.assertEqual(problem["reason_code"], "BAD_LOAN_AMOUNT")
        self.assertIn("several amounts", problem["explanation"])
        self.assertIn("15 million gold", problem["explanation"])
        self.assertIn("50M gold", problem["explanation"])

    def test_a_value_and_a_text_naming_different_amounts_are_refused(self):
        w = world()
        problem = politics.validate_motion_detail(w, loan(
            value="100 million gold (max available without default)", text="Request a loan of 50M gold."))
        self.assertEqual(problem["reason_code"], "BAD_LOAN_AMOUNT")
        self.assertIn("several amounts", problem["explanation"])

    def test_the_same_amount_in_the_value_and_the_text_is_one_amount(self):
        w = world()
        mo = loan(value="100 million gold (max available without default)",
                  text="Request 100 million gold in one tranche.")
        self.assertIsNone(politics.validate_motion_detail(w, mo))
        self.assertEqual(mo["value"], "100")

    def test_a_figure_with_no_unit_is_not_guessed(self):
        w = world()
        problem = politics.validate_motion_detail(w, loan(text="Request a loan of 50 gold from the Maritime League."))
        self.assertEqual(problem["reason_code"], "BAD_LOAN_AMOUNT")
        self.assertIn("no unit", problem["explanation"])

    def test_a_negative_amount_in_the_text_is_refused(self):
        # guard: the old refusal says "positive" too; the point is that -50M is never read as 50
        w = world()
        problem = politics.validate_motion_detail(w, loan(text="Request a loan of -50M gold from the Maritime League."))
        self.assertEqual(problem["reason_code"], "BAD_LOAN_AMOUNT")
        self.assertIn("positive", problem["explanation"])

    def test_a_full_count_of_gold_in_the_value_is_read_in_millions(self):
        w = world()
        mo = loan(value="50,000,000 gold", text="Request a loan from the Maritime League.")
        self.assertIsNone(politics.validate_motion_detail(w, mo))
        self.assertEqual(mo["value"], "50")

    def test_a_decimal_comma_is_not_a_thousands_separator(self):
        w = world()
        mo = loan(value="1,5 million", text="Request a loan from the Maritime League.")
        self.assertIsNone(politics.validate_motion_detail(w, mo))
        self.assertEqual(mo["value"], "1.5")

    def test_a_value_in_figures_reads_as_it_always_did(self):
        # guard: the bare value is millions of gold, as the prompt states it
        w = world()
        for value, want in (("50", "50"), ("50M", "50"), ("150 million", "150"), ("2.5", "2.5"), ("1,500", "1500")):
            with self.subTest(value=value):
                mo = loan(value=value, text="Request a loan from the Maritime League.")
                self.assertIsNone(politics.validate_motion_detail(w, mo))
                self.assertEqual(mo["value"], want)

    def test_a_non_finite_loan_amount_is_refused(self):
        w = world()
        problem = politics.validate_motion_detail(w, loan(value="9" * 400, text="Request a loan from Maritime League."))
        self.assertIsNotNone(problem)
        self.assertEqual(problem["reason_code"], "BAD_LOAN_AMOUNT")

    def test_intake_writes_the_text_amount_back_and_the_summary_names_it(self):
        w = world()
        raw = {"type": "diplomacy", "subject": "loan", "value": "", "text": EMERGENCY_TEXT, "action": dict(LEAGUE_ACTION)}
        mo = actions.normalize_motion_v2(w, raw)
        self.assertEqual(mo["value"], "50")
        mo["proposer"] = "B"
        self.assertIsNone(politics.validate_motion_detail(w, dict(mo)))
        self.assertIn("(50 million)", actions.motion_summary(w, mo))

    def test_the_text_amount_is_the_amount_executed(self):
        w = world()
        mo = loan()
        mo.update(id="M6", proposer="B")
        self.assertIsNone(politics.validate_motion_detail(w, mo))
        politics.apply_motion(w, mo)
        self.assertEqual(w.dip.proposals[-1]["amount"], 50)


class BracketedNumberIsThatNumber(unittest.TestCase):
    def test_a_number_in_braces_or_brackets_is_read_as_that_number(self):
        cases = (("tax", "{0.35}", 0.35), ("tax", "[0.35]", 0.35), ("tax", " { 0.35 } ", 0.35),
                 ("military", "{0.035}", 0.035), ("deploy_north", "{0.4}", 0.4), ("tax", "{25%}", 0.25),
                 ("army_target", "{60000}", 60000), ("import_cap", "[1000000]", 1e6))
        for lever, raw, want in cases:
            with self.subTest(lever=lever, raw=raw):
                self.assertAlmostEqual(politics.parse_lever(lever, raw), want)

    def test_a_motion_with_a_bracketed_value_passes(self):
        w = world()
        mo = motion("tax", "{0.35}", "Increase tax to 0.35 of output immediately.")
        self.assertIsNone(politics.validate_motion_detail(w, mo))

    def test_a_bracketed_value_is_applied_as_its_number(self):
        w = world()
        mo = motion("tax", "{0.35}", "Increase tax to 0.35 of output.")
        self.assertIsNone(politics.validate_motion_detail(w, dict(mo)))
        politics.apply_motion(w, {**mo, "passed": True})
        self.assertEqual(w.const.directives["tax"], 0.35)

    def test_placeholders_and_fragments_stay_refused(self):
        # guard: these are the values the census refused, and they must stay refused
        w = world()
        for raw in (">=", "{calculated_for_deficit}", "], set_policy", "{}", "[0.35", "0.35}", "{0.35]", "{nan}",
                    "[inf]", "{1e400}", "{" + "9" * 400 + "}", "{{0.35}}"):
            with self.subTest(raw=raw[:20]):
                self.assertIsNone(politics.parse_lever("tax", raw))
                problem = politics.validate_motion_detail(w, motion("tax", raw, "Raise tax."))
                self.assertEqual(problem["reason_code"], "BAD_VALUE")


class ConstitutionChannelNamedInTheRefusal(unittest.TestCase):
    def test_a_near_miss_of_a_constitution_field_says_it_is_a_constitution_motion(self):
        w = world()
        problem = politics.validate_motion_detail(w, motion("highland_status", "cultural",
                                                            "Grant the Highlands cultural status."))
        self.assertEqual(problem["reason_code"], "UNKNOWN_LEVER")
        self.assertIn("constitution motion", problem["explanation"])
        self.assertIn("highlands_status", problem["explanation"])
        self.assertIn("central/cultural/devolved", problem["explanation"])

    def test_a_constitution_field_inside_a_program_says_so(self):
        w = world()
        mo = {"type": "program", "subject": "", "value": "", "text": "a package", "proposer": "A",
              "action": {"measures": [{"lever": "highlands_status", "value": "cultural"}]}}
        problem = politics.validate_motion_detail(w, mo)
        self.assertEqual(problem["reason_code"], "UNKNOWN_LEVER")
        self.assertIn("constitution motion", problem["explanation"])

    def test_the_census_input_is_a_constitution_motion_at_intake(self):
        # guard: this is what main does today, and what the census line described before the fix (see the report)
        w = world()
        raw = {"type": "set_policy", "subject": "highlands_status", "value": "cultural",
               "text": "Grant the Highlands cultural status."}
        mo = actions.normalize_motion_v2(w, dict(raw))
        self.assertEqual((mo["type"], mo["subject"]), ("constitution", "highlands_status"))
        self.assertIsNone(politics.validate_motion_detail(w, {**mo, "proposer": "A"}))

    def test_an_ordinary_unknown_lever_keeps_its_message(self):
        # guard: a name that is not a constitution setting gets no constitution sentence
        w = world()
        problem = politics.validate_motion_detail(w, motion("unemployment", "0.05", "Cut unemployment."))
        self.assertEqual(problem["reason_code"], "UNKNOWN_LEVER")
        self.assertNotIn("constitution", problem["explanation"])


if __name__ == "__main__":
    unittest.main()
