"""Engine 19 claim test: which figures the numeric grounding check judges (audit MO3-MO8, MO22, and the regression
found by the engine-19 differential over 133 real motions).

Engine 19 refused 13 motions that engine 18 accepted, and most of those refusals were false. Each read an amount a
motion proposes, requests, pays, settles or borrows, a threshold or condition, a setting the motion sets, a change, or
a figure whose noun names another quantity, as a statement of the state. The check now judges only a statistic the
text states as a fact about the current or past state. MOTIONS are real motion texts (quoted in full from three runs);
the amounts, thresholds and settings in them must not be refused. The state claims below must be refused when false
and accepted when true.
"""
import unittest

from karamaniya import foreign, motion_actions
from karamaniya.world import new_world

# Real motion texts, quoted in full from the run logs: label -> (proposer, text). The first 13 are the false refusals
# of engine 19. The credit line (engine 18 refused it as a claim about Union forces) must keep passing. The rest were
# refused by engine 18 on the same misreading: an amount read as a stock, a rate change read as unemployment.
MOTIONS = {
    '20261008-130316-seed1|2|M3|B': ('B', 'Request a loan of 40M gold from the Maritime League to rebuild foreign reserves and import coverage, on commercial terms, so the arrears settlement and grain imports never compete for the same crowns.'),   # the 40M gold loan
    '20261008-130316-seed1|3|M3|E': ('E', "Storm relief for Port Aster and Lissen Coast: first tranche 10M crown for ports, roads and fields. Funded 4M by reallocation from non-security lines (not forces' pay or food imports) and 6M by domestic bonds; no reserves. Army engineers work under civilian direction. Not an emergency measure."),   # the 10M crown storm relief tranche
    '20261008-130316-seed1|5|M2|E': ('E', "Port Aster main-port repair: 8M from a reallocation line named by Treasury (not welfare, food, fuel or forces' pay; no reserves, no bonds). Civilian contractors by open tender; army engineers not used. Treasury publishes costing, tender lines and schedule before any payment; payment in tranches against certified progress."),   # the 8M Port Aster repair
    '20261008-130316-seed1|0|M5|B': ('B', 'Pay half of the reconciled inherited unpaid state bills (Treasury ledger: about 24M crowns, so ~12M gold) from foreign reserves, only after Treasury publishes reserves, arrears and the monthly grain import bill, with military and police payroll ring-fenced and reserves remaining above 60M gold.'),   # the Treasury half-payment with 24M crowns and 12M gold
    '20261010-002051-seed1|0|M2|D': ('D', 'Pay half of the inherited arrears (about 10M crowns) from reserves, prioritising rail maintenance crews, grain logistics, port and fuel suppliers. This is the sole arrears settlement this month; total arrears paid shall not exceed half without a fresh accounting and vote. Treasury publishes amounts paid, recipients, delivery milestones and remaining arrears monthly.'),   # half of the inherited arrears, about 10M crowns
    '20261008-130316-seed1|2|D1|B': ('B', 'Pay one quarter of inherited unpaid bills from reserves, but only after Treasury certifies in writing that post-payment reserves will be at least 70M gold and that contracted grain imports and current army, navy and police payroll are fully funded; otherwise defer the tranche.'),   # the quarter-payment after 70M gold
    '20261008-130316-seed1|6|M3|B': ('B', 'Pay one quarter of inherited arrears (~27M) by issuing domestic bonds. Reserves untouched; creditor and supplier credibility improved ahead of League trade talks. Executed only if reserves remain above the 80M floor.'),   # the quarter of arrears, executed only if reserves remain above 80M
    '20261008-130316-seed1|5|M5|A': ('A', 'Pay a quarter of inherited arrears from current reserves to stop the worsening solvency trend before we reach 80M gold.",'),   # the quarter of arrears before 80M gold
    '20261010-002051-seed1|1|M3|D': ('D', 'Stabilization and food security package: raise tax to 0.20, lift farm_support to 0.05, hold printing at 0.00, keep debt_service pay, keep stats honest. Military fuel and logistics contractors are named priority creditors and paid on schedule within cash limits. The tax rise roughly funds the farm-support increase, so food security improves without widening the deficit.'),   # the 0.20 tax and food security package
    '20261010-070501-seed1|4|M3|D': ('D', 'Balanced stabilisation: raise tax to 0.24 and welfare to 0.045, relief targeted at workers hit by the export slump. Net deficit reduction with protection for the unemployed. No printing, no reserve draw.'),   # the 0.24 tax and welfare package
    '20261010-070501-seed1|3|M1|A': ('A', 'Raise tax to 22% of output to slow the reserve drain from the 33M/month structural deficit. Modest increase preserves compliance and avoids deepening the export-slump downturn while restoring lender and public confidence in solvency.'),   # the 22 percent tax and the 33M deficit
    '20261010-070501-seed1|4|M2|D': ('D', 'Settle half of remaining inherited arrears (about 28M crowns) with domestic bonds. Verified civil-service wage claims paid first, under the published monthly ledger. No printing, no draw on reserves.'),   # settle half of remaining arrears, about 28M crowns
    '20261010-070501-seed1|2|M2|D': ('D', 'Request a precautionary credit arrangement of 40M gold from the Maritime League to underpin reserves and import coverage. To be drawn only if reserves approach one month of imports; commercial terms; no political conditions accepted.'),   # the 40M gold precautionary credit
    '20261010-070501-seed1|3|D1|B': ('B', 'Renewal of Month 3 motion, commerce-only. Propose to the Maritime League: (1) tariff reduction on Karamanian port dues and League goods; (2) League shipping-insurance pool for food and fuel imports; (3) a credit line up to 25 million gold restricted to grain, fertilizer and fuel purchases; (4) League merchant access to Port Aster and Lissen. No alliance, no base rights, no naval escort obligations, no clause touching our non-aggression pact with Veleria.'),   # the credit line up to 25 million gold (passes in engine 18 as refused)
    '20261008-130316-seed1|4|D2|C': ('C', 'Authorize 12 million gold in targeted Lissen Coast storm relief for roads, fields and port access, funded from reserves. Prioritize restoring transport and protecting agricultural production; use army engineers only if the Army Command volunteers them without diverting essential readiness.'),   # 12M gold storm relief (engine 18 refused)
    '20261008-130316-seed1|6|D4|C': ('C', 'Renew the deferred Lissen Coast relief proposal at 4 million gold, funded by reallocation, for mixed recovery works with military engineers. This complements the 8 million already spent while limiting pressure on reserves.'),   # 4M gold relief renewal (engine 18 refused)
    '20261008-130316-seed1|7|M1|A': ('A', 'Raise annual interest rate from 6% to 7% (a rise of 1 percentage point) immediately after this month to stem currency speculation without causing mass unemployment.'),   # rate 6 to 7 percent (engine 18 refused)
    '20261008-130316-seed1|15|M2|B': ('B', 'Request a loan of 250 million gold from the Maritime League to settle inherited arrears and stabilise reserves, backed by a published consolidation programme: tax 0.30, printing capped at 0.01, honest statistics, and no default on security payrolls.'),   # 250M gold loan (engine 18 refused)
    '20261008-130316-seed1|16|M3|B': ('B', 'Request a 200 million gold loan from the Maritime League, terms published in full, earmarked for arrears clearance and reserve rebuilding, with explicit exclusion of any port, customs or sovereignty concessions.'),   # 200M gold loan (engine 18 refused)
    '20261008-130316-seed1|17|M2|B': ('B', 'Request a transparent standby loan of 150 million gold from the Maritime League to bridge the export downturn and support arrears clearance, as an alternative to money printing. Full terms must be published before acceptance. The facility must exclude sovereign collateral, port or infrastructure concessions, foreign basing rights, foreign military access, and policy conditions affecting command of the armed forces. A debt-service schedule must be published before the vote.'),   # 150M gold standby loan (engine 18 refused)
    '20261010-070501-seed1|6|M4|D': ('D', "Pay all remaining verified inherited arrears (about 99M crowns) via domestic bonds. First tranche: verified wage claims, including soldiers' pay and forces' contracts. No reserves touched. Full settlement ledger and the deficit-halving glide path published to council and public."),   # pay all arrears, about 99M crowns (engine 18 refused)
    '20261010-070501-seed1|8|M5|D': ('D', 'Request a 120 million gold credit line from the Maritime League, held against reserves as insurance through the ultimatum crisis; drawn only if needed, with honest statistics as collateral of credibility.'),   # 120M gold credit line (engine 18 refused)
}


def grounding_world():
    """The audit's world (seed 11): reserves 80,000,000 gold, 28,000 soldiers, inflation 0%, unemployment 6%."""
    w = new_world(11, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.agent_architecture_version = 2
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def check(text: str, w=None, mid: str = "A"):
    return motion_actions.check_numeric_grounding(w if w is not None else grounding_world(), mid, text)


class RealMotionAmountsAreNotClaims(unittest.TestCase):
    """Every real motion text passes: its figures are amounts, thresholds or settings, not statements of the state."""

    def test_each_real_motion_passes(self):
        for label, (mid, text) in MOTIONS.items():
            with self.subTest(motion=label):
                self.assertIsNone(check(text, mid=mid))


class StateClaimsAreJudged(unittest.TestCase):
    """What a text states as a fact about the current or past state is still checked: refused when false, passes
    when true."""

    def test_reserves_stated_as_a_level(self):
        claim = check("Our reserves stand at 20,000,000 gold.")
        self.assertEqual((claim["code"], claim["metric"]), ("NUMERIC_GROUNDING_ERROR", "reserves"))
        self.assertIsNone(check("Our reserves stand at 80,000,000 gold."))

    def test_inflation_and_approval_levels(self):
        self.assertEqual(check("Inflation is 40%.")["metric"], "inflation")
        self.assertIsNone(check("Inflation is 0%."))
        self.assertEqual(check("Approval is 95.")["metric"], "approval")
        self.assertIsNone(check("Approval is 48."))

    def test_unemployment_reached_is_judged_not_read_as_a_threshold(self):
        # "reached" is a past state; only the bare "reach" of a target is a threshold.
        w = grounding_world()
        w.econ.unemployment = 0.01            # 9% is far outside tolerance here, so the claim must be judged
        claim = check("Unemployment has reached 9%.", w)
        self.assertEqual((claim["code"], claim["metric"]), ("NUMERIC_GROUNDING_ERROR", "unemployment"))
        w.econ.unemployment = 0.09
        self.assertIsNone(check("Unemployment has reached 9%.", w))

    def test_a_forecast_is_checked_while_a_target_is_not(self):
        # "will reach" states the level expected next month, and is checked; "before we reach" sets an aim, and is not.
        self.assertEqual(check("Unemployment will reach 40% next month.")["metric"], "unemployment")
        self.assertIsNone(check("Unemployment will reach 6% next month."))
        self.assertIsNone(check("We will hold steady before we reach 200M gold in reserves."))

    def test_union_soldiers_are_judged_against_the_union(self):
        self.assertIsNone(check("The Solvaran Union has 95,000 soldiers."))
        self.assertEqual(check("The Solvaran Union has 30,000 soldiers.")["metric"], "union_forces")

    def test_consumer_prices_climbed_is_judged_as_inflation(self):
        self.assertEqual(check("Consumer prices climbed 9%.")["metric"], "inflation")
        w = grounding_world()
        w.econ.cpi = (1.09) ** (1 / 12)        # inflation 9%, the claim is then true
        self.assertIsNone(check("Consumer prices climbed 9%.", w))

    def test_reserves_fell_to_a_level(self):
        self.assertEqual(check("Reserves fell to 15M.")["metric"], "reserves")
        self.assertIsNone(check("Reserves fell to 80M."))

    def test_a_level_stated_in_reserves(self):
        claim = check("We close the month with 12M in reserves.")
        self.assertEqual((claim["metric"], claim["claim_text"]), ("reserves", "12 m"))
        self.assertIsNone(check("We close the month with 80M in reserves."))

    def test_an_amount_noun_that_is_the_subject_of_a_state_claim_does_not_hide_it(self):
        # "printing", "relief" and "credit" name amounts, but in these sentences they are what moved the state.
        self.assertEqual(check("Printing has pushed inflation to 40%.")["metric"], "inflation")
        self.assertEqual(check("Relief spending has pushed unemployment to 40%.")["metric"], "unemployment")
        self.assertEqual(check("Credit has pushed our reserves to 5M.")["metric"], "reserves")

    def test_a_state_after_a_payment_in_the_same_sentence_is_judged(self):
        claim = check("We paid 10M and reserves stand at 5M gold.")
        self.assertEqual((claim["metric"], claim["claim_text"]), ("reserves", "5 m gold"))
        self.assertIsNone(check("We paid 10M and reserves stand at 80M gold."))
        claim = check("Settled arrears: reserves stand at 5M gold.")
        self.assertEqual(claim["metric"], "reserves")

    def test_the_unemployment_rate_is_a_statistic_not_a_lever(self):
        self.assertEqual(check("The unemployment rate has risen to 40%.")["metric"], "unemployment")

    def test_the_level_is_judged_and_the_deficit_figure_is_not(self):
        # 33M is the deficit, a flow that no spec checks; 5M is the level the reserves are stated to have reached.
        claim = check("The 33M deficit has drained reserves to 5M.")
        self.assertEqual((claim["metric"], claim["claim_text"]), ("reserves", "5 m"))
        self.assertIsNone(check("The 33M deficit has drained reserves to 80M."))


class AmountsThresholdsAndSettingsAreNotClaims(unittest.TestCase):
    """The figures a motion proposes, requests, pays, borrows or sets, and the thresholds and conditions it states,
    are not statements of the state, so they are not checked against it. Each sentence is one that would be refused
    if its figure were judged: the figure is far from the audit world's truth."""

    def test_amounts_a_motion_pays_requests_or_allocates(self):
        for text in ("Request a loan of 40M gold from the Maritime League to rebuild foreign reserves.",
                     "First tranche 10M crown for ports, roads and fields; no reserves touched.",
                     "Port Aster main-port repair: 8M from a reallocation line; no reserves.",
                     "Pay half of the inherited arrears (about 10M crowns) from reserves.",
                     "Settle half of remaining inherited arrears (about 28M crowns) with domestic bonds.",
                     "Authorize 12 million gold in relief for roads, funded from reserves.",
                     "Renew the deferred relief proposal at 4 million gold, funded from reserves.",
                     "The 8 million already spent came from reserves.",
                     "Request a credit line of 120 million gold, held against reserves."):
            with self.subTest(text=text):
                self.assertIsNone(check(text))

    def test_a_list_of_payments_is_one_clause(self):
        # "and 6M" continues the payment; only a state after the conjunction starts a new clause.
        self.assertIsNone(check("Pay 10M and 6M from reserves, in two tranches."))

    def test_a_figure_inside_brackets_takes_the_clause_of_its_sentence(self):
        # "about 24M crowns" and "~12M gold" are part of the payment's clause, as the parenthetical is part of the motion.
        self.assertIsNone(check("Pay half of the reconciled inherited unpaid state bills (Treasury ledger: "
                                "about 24M crowns, so ~12M gold) from foreign reserves."))

    def test_thresholds_floors_and_conditions(self):
        for text in ("Executed only if reserves remain above the 200M floor.",
                     "Reserves must stay above 15M.",
                     "Reserves will be at least 200M gold after the payment.",
                     "Stop the solvency slide before we reach 200M gold.",
                     "Pay one quarter of the arrears only if reserves stay above 15M."):
            with self.subTest(text=text):
                self.assertIsNone(check(text))

    def test_a_lever_set_to_a_figure(self):
        # "food security" puts the figure beside a food spec, where 0.20 is far from food coverage of 100%.
        self.assertIsNone(check("Stabilization and food security package: raise tax to 0.20, lift farm_support to 0.05."))
        # "unemployed" puts it beside the unemployment spec, where 0.24 is far from 6%.
        self.assertIsNone(check("Balanced stabilisation: raise tax to 0.24 and welfare to 0.045, protection for the unemployed."))

    def test_a_share_of_output_setting_beside_a_deficit_of_another_quantity(self):
        self.assertIsNone(check("Raise tax to 22% of output to slow the drain on reserves from the 33M/month "
                                "structural deficit."))

    def test_a_lever_moved_from_one_value_to_another(self):
        w = grounding_world()
        w.econ.unemployment = 0.25
        self.assertIsNone(check("Raise annual interest rate from 6% to 7% (a rise of 1 percentage point) without "
                                "causing mass unemployment.", w))

    def test_a_change_is_not_a_level(self):
        w = grounding_world()
        w.econ.unemployment = 0.25
        self.assertIsNone(check("Unemployment fell by 60% this year.", w))
        self.assertIsNone(check("Unemployment rose by 60 percent since the last report.", w))

    def test_a_figure_whose_noun_names_another_quantity(self):
        self.assertIsNone(check("A 24M bill is owed from reserves."))
        self.assertIsNone(check("A 33M deficit has drained reserves."))


class ClaimClauses(unittest.TestCase):
    """The clause the figure sits in, and the setting and figure readings the rule relies on."""

    def test_a_comma_inside_brackets_does_not_end_the_clause(self):
        text = "Pay half of the bills (about 24M crowns, so ~12M gold) from foreign reserves."
        gold = motion_actions._numbers_in(text)[1]
        self.assertIn("Pay", motion_actions._clause_before(text, gold["start"]))

    def test_a_comma_outside_brackets_ends_the_clause(self):
        text = "Pay the bills, and reserves stand at 20M gold."
        level = motion_actions._numbers_in(text)[0]
        self.assertNotIn("Pay", motion_actions._clause_before(text, level["start"]))

    def test_a_decimal_point_does_not_end_the_clause(self):
        text = "The rate is 0.20 and reserves stand at 20M gold."
        level = motion_actions._numbers_in(text)[1]
        self.assertIn("rate", motion_actions._clause_before(text, level["start"]))

    def test_levers_and_their_aliases_set_a_figure(self):
        for before in ("Raise tax to ", "lift farm_support to ", "Raise the policy rate from 0.11 to ",
                       "Raise annual interest rate from ", "Hold printing at ", "raise welfare to "):
            with self.subTest(before=before):
                self.assertTrue(motion_actions._setting_before(before))

    def test_a_state_is_not_a_setting(self):
        for before in ("Reserves fell to ", "Our reserves stand at ", "Inflation is ",
                       "The unemployment rate has risen to "):
            with self.subTest(before=before):
                self.assertFalse(motion_actions._setting_before(before))

    def test_only_the_state_figure_is_a_claim(self):
        text = "The 33M deficit has drained reserves to 5M."
        deficit, level = motion_actions._numbers_in(text)
        self.assertFalse(motion_actions._states_a_fact(text, deficit))
        self.assertTrue(motion_actions._states_a_fact(text, level))


if __name__ == "__main__":
    unittest.main()
