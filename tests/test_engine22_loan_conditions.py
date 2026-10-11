"""Engine 22: a loan is not blocked by the purpose it finances (run 20261011-105713-seed1, Month 8, M5).

A 50M gold loan request from the Maritime League passed 5-0 and never ran. Its text said "Order of use: first,
reserves rebuilt above 60M", and the condition reader took that goal for a floor on reserves after payment. A loan
pays nothing out, so reserves could only rise by the very loan the floor blocked: the gate reported "reserves_after_payment
would fall to 42,881,337 (floor 60,000,000)" and the motion stayed unexecuted.

Three cases from the same run must keep working: an arrears payment from reserves whose 30M floor caps the payment
(Month 10, M4), a bond-financed arrears settlement with a structured reserves condition (Month 4, M5), and a tax
directive gated on league credit (Month 7, M1).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import foreign, motion_actions, politics  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

# The Month 8 loan as tabled, and as the amendment round left it (run 20261011-105713-seed1, Month 8, M5).
TABLED = ("Request a 50-million-gold loan from the Maritime League: reserves rebuilt above 60M, inherited arrears "
          "settled on a published schedule, repayment funded by consolidation. No printing, honest statistics, "
          "disbursement and use published line by line.")
AMENDED = ("Request a 50-million-gold loan from the Maritime League. Order of use: first, reserves rebuilt above 60M; "
           "second, costed immediate defense needs — fortification crews, reserve equipment, the published 90-day "
           "mobilization; third, inherited arrears settled on a published schedule. No printing, honest statistics, "
           "terms, disbursements and repayment published line by line.")
RESERVES_AT_43M = 42_881_336.88


def world(seed: int = 11):
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.agent_architecture_version = 2
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def loan(text: str = AMENDED, **extra) -> dict:
    """The Month 8 loan as the council voted on it: 5-0, carried by its proposer D."""
    return {"id": "M5", "type": "diplomacy", "subject": "loan", "value": "50", "text": text, "proposer": "D",
            "passed": True, "votes": dict.fromkeys("ABCDE", "yes"),
            "action": {"action_type": "loan_request", "target": "MARITIME_LEAGUE", "amount": "50",
                       "issue": "Reserve buffer and arrears settlement ahead of Union pressure",
                       "terms": ["50 million gold", "Accounts published line by line"]}, **extra}


def relief(text: str, action: dict) -> dict:
    return {"id": "D1", "type": "disaster_relief", "subject": "port aster", "value": "20M", "text": text,
            "proposer": "B", "passed": True, "action": action}


def reserve_floors(conditions) -> list:
    return [c for c in conditions if c.get("metric") == "reserves_after_payment"]


class AGoalIsNotACondition(unittest.TestCase):
    """"reserves rebuilt above 60M" says what the money is for; it is not a precondition."""

    def test_the_month_8_loan_text_states_no_reserve_floor(self):
        for text in (TABLED, AMENDED):
            with self.subTest(text=text[:50]):
                self.assertEqual(reserve_floors(motion_actions.parse_conditions(text, "diplomacy", "loan")), [])
                self.assertEqual(motion_actions.motion_conditions(loan(text)), [])

    def test_the_month_8_loan_executes_with_reserves_at_43M(self):
        w = world()
        w.econ.gold = RESERVES_AT_43M
        mo = loan()
        self.assertIsNone(motion_actions.validate_execution(w, mo))
        self.assertEqual(politics.apply_motion(w, {**mo, "proposer": "D"}),
                         "proposal sent to the Maritime League: loan")

    def test_goal_wording_is_not_read_as_a_floor_on_a_reserve_payment(self):
        # A reserve payment, so the motion type cannot be what keeps these from binding: only the wording decides.
        goals = (
            "Pay a quarter of arrears from reserves; reserves rebuilt above 60M.",
            "Pay a quarter of arrears from reserves; rebuild reserves above 60M.",
            "Pay a quarter of arrears from reserves; restore reserves to at least 60M.",
            "Pay a quarter of arrears from reserves; raise reserves above 60M.",
            "Pay a quarter of arrears from reserves; bring reserves above 60M.",
            "Pay a quarter of arrears from reserves; order of use: first, reserves rebuilt above 60M.",
            "Pay a quarter of arrears from reserves; target: reserves above 60M.",
            "Pay a quarter of arrears from reserves; aim: reserves above 60M.",
            "Pay a quarter of arrears from reserves; reserves to be rebuilt above 60M before the next tranche.",
        )
        for text in goals:
            with self.subTest(text=text):
                self.assertEqual(reserve_floors(motion_actions.parse_conditions(text, "settle_arrears", "reserves")), [])

    def test_real_floors_on_a_reserve_payment_still_bind(self):
        floors = {
            "Pay a quarter of arrears from reserves; reserves remain at or above 30 million gold afterward.": 30e6,
            "Pay a quarter of arrears from reserves; keep reserves above 50M.": 50e6,
            "Pay a quarter of arrears from reserves; reserves must stay at least 55M after payment.": 55e6,
            "Pay a quarter of arrears from reserves; reserves not below 45M.": 45e6,
        }
        for text, want in floors.items():
            with self.subTest(text=text):
                got = [c["value"] for c in reserve_floors(
                    motion_actions.parse_conditions(text, "settle_arrears", "reserves"))]
                self.assertEqual(got, [want])


class OnlyAPaymentFromReservesBindsAReserveFloor(unittest.TestCase):
    """A reserves_after_payment floor means something only where reserves are what the motion pays out of."""

    def test_motions_that_pay_nothing_out_of_reserves_get_no_reserve_floor_from_their_text(self):
        text = "Keep reserves above 50M, and spend nothing that takes them below it."
        for kind, subject in (("diplomacy", "loan"), ("diplomacy", "grain_deal"), ("diplomacy", "trade_deal"),
                              ("set_policy", "tax"), ("program", "stabilisation"),
                              ("settle_arrears", "domestic_bonds"), ("investigation", "treasury"),
                              ("disaster_relief", "port aster")):
            with self.subTest(kind=kind, subject=subject):
                self.assertEqual(reserve_floors(motion_actions.parse_conditions(text, kind, subject)), [])

    def test_a_bond_settlement_is_not_held_to_a_reserve_floor(self):
        # Run 20261010-070501-seed1, Month 6, M3: the bonds pay, reserves are untouched, so 80M is not a payment floor.
        text = ("Pay one quarter of inherited arrears (~27M) by issuing domestic bonds. Reserves untouched; creditor "
                "and supplier credibility improved ahead of League trade talks. Executed only if reserves remain above "
                "the 80M floor.")
        self.assertEqual(reserve_floors(motion_actions.parse_conditions(text, "settle_arrears", "domestic_bonds")), [])

    def test_a_structured_reserve_floor_on_a_loan_is_dropped_with_a_note_and_the_loan_still_runs(self):
        w = world()
        w.econ.gold = RESERVES_AT_43M
        structured = [{"metric": "reserves_after_payment", "operator": ">=", "value": 60e6,
                       "source": "reserves rebuilt above 60m"}]
        mo = loan(TABLED, conditions=structured)
        self.assertEqual(motion_actions.motion_conditions(mo), [])
        self.assertIsNone(motion_actions.validate_execution(w, mo))
        notes = motion_actions.dropped_conditions(mo)
        self.assertEqual([(n["metric"], n["operator"], n["value"]) for n in notes],
                         [("reserves_after_payment", ">=", 60e6)])
        self.assertIn("loan_request", notes[0]["note"])

    def test_a_reserve_floor_handed_to_the_gate_for_a_loan_does_not_block_it(self):
        w = world()
        w.econ.gold = RESERVES_AT_43M
        results = motion_actions.evaluate_conditions(
            w, [{"metric": "reserves_after_payment", "operator": ">=", "value": 60e6, "source": "x"}], loan())
        self.assertTrue(results[0]["met"])
        self.assertFalse(results[0]["applies"])

    def test_disaster_relief_binds_a_reserve_floor_only_when_reserves_fund_it(self):
        text = "Storm relief for Port Aster: keep reserves above 40M after the payment; roads and ports first."
        from_reserves = relief(text, {"funding": "reserves", "amount": "20M"})
        mixed = relief(text, {"amount": "20M", "funding_plan": [{"source": "reallocation", "amount": "10M"},
                                                              {"source": "reserves", "amount": "10M"}]})
        from_bonds = relief(text, {"funding": "bonds", "amount": "20M"})
        self.assertEqual([c["value"] for c in reserve_floors(motion_actions.motion_conditions(from_reserves))], [40e6])
        self.assertEqual([c["value"] for c in reserve_floors(motion_actions.motion_conditions(mixed))], [40e6])
        self.assertEqual(reserve_floors(motion_actions.motion_conditions(from_bonds)), [])


class TheThreeCasesFromTheRunThatKeepWorking(unittest.TestCase):
    def test_month_10_arrears_from_reserves_keeps_its_30M_floor_and_the_payment_is_capped(self):
        # Run 20261011-105713-seed1, Month 10, M4: the 30M floor was read from the text and bound with the delegate's 25M.
        text = ("Pay one quarter of outstanding inherited unpaid bills from reserves: soldier and police arrears first in "
                "full, then public wages, every crown published line by line. Payment proceeds only insofar as reserves "
                "remain at or above 30 million gold afterward; nothing is spent that protects grain and coal imports.")
        mo = {"id": "M4", "type": "settle_arrears", "subject": "reserves", "value": "quarter", "text": text,
              "proposer": "D", "passed": True, "votes": dict.fromkeys("ABCDE", "yes")}
        self.assertEqual([(c["metric"], c["operator"], c["value"]) for c in motion_actions.motion_conditions(mo)],
                         [("reserves_after_payment", ">=", 30e6)])
        bound = [{"metric": "reserves_after_payment", "operator": ">=", "value": 25e6,
                  "source": "Treasury cash desk, millions of gold"},
                 {"metric": "reserves_after_payment", "operator": ">=", "value": 30e6,
                  "source": "reserves remain at or above 30 million"}]
        self.assertEqual(politics.payment_floor({**mo, "conditions": bound}), 30e6)

        w = world()
        w.econ.gold = 500e6
        w.econ.arrears = 200e6
        full = politics.settle_arrears_cost(w, mo, floor=0.0)
        self.assertGreater(full, 0.0)
        w.econ.gold = 30e6 + 0.3 * full     # a full quarter would take reserves well under the floor
        self.assertIsNone(motion_actions.validate_execution(w, {**mo, "conditions": bound}))
        result = politics.apply_motion(w, {**mo, "conditions": bound})
        self.assertIn("limited to keep reserves at the reserve floor of 30.0M", result)
        self.assertGreaterEqual(w.econ.gold, 30e6 - 1.0)
        self.assertLess(w.econ.gold, 30e6 + 1e3)

    def test_month_4_bond_settlement_keeps_its_structured_reserves_condition(self):
        # Run 20261011-105713-seed1, Month 4, M5: a bond-financed settlement gated on reserves >= 55M, source kept.
        text = ("Pay half of remaining inherited arrears (~31M) from domestic bond issuance, never reserves. The full bond "
                "terms and payment schedule are published before signature, import cover for food and fuel is protected, "
                "and payment is paired with published quarterly accounts and a plan to close the recurring deficit.")
        stored = [{"metric": "reserves", "operator": ">=", "value": 55_000_000.0, "source": "Treasury cash desk R4-TRE1"}]
        mo = {"id": "M5", "type": "settle_arrears", "subject": "domestic_bonds", "value": "half", "text": text,
              "proposer": "D", "passed": True, "conditions": stored, "votes": dict.fromkeys("ABCDE", "yes")}
        self.assertEqual(motion_actions.motion_conditions(mo), stored)
        w = world()
        w.econ.gold = 60e6
        self.assertIsNone(motion_actions.validate_execution(w, mo))
        w.econ.gold = 50e6
        self.assertEqual(motion_actions.validate_execution(w, mo)["code"], "EXECUTION_BLOCKED_CONDITION")

    def test_month_7_tax_directive_keeps_its_league_credit_gate(self):
        # Run 20261011-105713-seed1, Month 7, M1: the tax rise waits for league credit, and the gate is kept.
        text = ("Raise the tax take to 28% of output with enforcement against evasion, ring-fencing military at 0.05 and "
                "protecting soldier and police pay; protect food and essential wages. The Treasury audit due after Month 7 "
                "is published in full; no rate above 0.28 before the Council reviews the audit and a costed fortification "
                "table. Further steps only if the audit and League credit require them.")
        gate = [{"metric": "league_credit_received", "operator": "==", "value": 1.0, "source": "league credit gate"}]
        mo = {"id": "M1", "type": "set_policy", "subject": "tax", "value": "0.28", "text": text, "proposer": "B",
              "passed": True, "conditions": gate, "votes": dict.fromkeys("ABCDE", "yes")}
        self.assertEqual(motion_actions.motion_conditions(mo), gate)
        w = world()
        self.assertEqual(motion_actions.validate_execution(w, mo)["code"], "EXECUTION_BLOCKED_CONDITION")
        w.econ.loans_in = 10e6
        self.assertIsNone(motion_actions.validate_execution(w, mo))


class ADemandForAGoalIsNotAFloor(unittest.TestCase):
    def test_a_demand_for_a_rebuilding_goal_states_no_floor(self):
        for text in ("Reserves to be rebuilt above 60M before any payment.",
                     "Raise reserves to a 60M floor by Month 9.",
                     "Restore reserves to at least 60M before paying arrears."):
            with self.subTest(text=text):
                self.assertIsNone(motion_actions.floor_from_demand(text))

    def test_a_demand_for_a_floor_still_states_one(self):
        self.assertEqual(motion_actions.floor_from_demand("Ensure reserves do not fall below 50M gold."), 50e6)
        self.assertEqual(motion_actions.floor_from_demand("Do not bring reserves below 50M."), 50e6)
        self.assertEqual(motion_actions.floor_from_demand("Keep reserves above 50 million gold."), 50e6)


if __name__ == "__main__":
    unittest.main()
