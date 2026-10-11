"""Engine 19, economy slice: inflation as the delegates see it, the League loan, pass-through, the founding
economy, the price trace, foreign interest, utilisation, the deflation label, compliance shocks and the two
operations (audit findings TO1, EC1-EC10, EC12, IN-L1, MI3, MI8 of docs/AUDIT_ENGINE18.md)."""
import copy
import unittest

from karamaniya import causality, decision_context, dilemmas, economy, engine, foreign, operations, society
from karamaniya.world import new_world


def stepped(seed: int, months: int, founding: str = "random"):
    """A world run for `months` months with no council action (the economy's own dynamics)."""
    w = new_world(seed, 36, founding_scenario=founding)
    w.foreign = foreign.initial_state(w.seed)
    for _ in range(months):
        engine.begin_month(w)
        engine.step(w)
    return w


def window_at_start_of_month(history: list, months: int) -> float:
    """The figure a prompt should show when `months` months have finished (Audit TO1). Under 12 months it is the
    change so far annualised over those months; from 12 it is the change over the latest 12 months, whose base is
    the price level 12 months before the last finished month (1.0 at founding for the twelfth month)."""
    if months <= 0:
        return 0.0
    last = history[months - 1]["cpi"]
    if months < 12:
        return last ** (12 / months) - 1
    base = 1.0 if months == 12 else history[months - 13]["cpi"]
    return last / base - 1


class PromptInflationWindow(unittest.TestCase):
    """TO1: the figure delegates are shown covers the months that have really passed."""

    def test_prompt_figure_covers_the_finished_months(self):
        w = new_world(1, 36, founding_scenario="random")
        w.foreign = foreign.initial_state(w.seed)
        for _ in range(14):
            engine.begin_month(w)
            engine.step(w)
            # Now w.month is the number of finished months: this is the state the next month's prompts are built from.
            months = w.month
            self.assertAlmostEqual(society.inflation_yoy(w), window_at_start_of_month(w.history, months),
                                   places=12, msg=f"prompt figure at the start of month {months + 1}")

    def test_from_month_thirteen_the_label_names_twelve_months_of_change(self):
        w = stepped(1, 12)
        self.assertEqual(w.month, 12)
        self.assertEqual(decision_context._inflation_basis(w), "over the last 12 months")
        w2 = stepped(1, 2)
        self.assertEqual(decision_context._inflation_basis(w2), "annualised over 2 months")

    def test_a_scenario_that_starts_with_a_price_move_counts_it_as_one_month(self):
        """inflation_vs_jobs sets the starting price level to a year of 16% inflation, one month's move (scenarios.py)."""
        from karamaniya import scenarios
        w = new_world(2, 36, founding_scenario="random")
        w.foreign = foreign.initial_state(w.seed)
        scenarios.apply(w, "inflation_vs_jobs")
        self.assertAlmostEqual(society.inflation_yoy(w), 0.16, places=6)

    def test_no_month_finished_gives_zero_and_says_so(self):
        w = new_world(1, 36, founding_scenario="random")
        self.assertEqual(society.inflation_yoy(w), 0.0)
        self.assertEqual(decision_context._inflation_basis(w), "no month has finished yet")

    def test_stored_history_rows_keep_the_window_they_were_written_with(self):
        """The rows are written inside the month, after its prices are set, and were always right. The fix must not
        move them: row k covers k+1 months."""
        w = stepped(3, 14)
        for k, row in enumerate(w.history):
            months = k + 1
            if months < 12:
                expected = row["cpi"] ** (12 / months) - 1
            else:
                base = 1.0 if months == 12 else w.history[k - 12]["cpi"]
                expected = row["cpi"] / base - 1
            self.assertAlmostEqual(row["infl_yoy"], expected, places=12, msg=f"row for month {k + 1}")


class FoundingPrices(unittest.TestCase):
    """EC4: the starting food and goods prices are the levels the founded economy implies, so Month 1 carries only
    that month's shocks (before, seed 3 fell 3.0% in Month 1 and seeds 1 and 5 rose 1.6-1.8%)."""

    def test_month_one_carries_no_founding_correction(self):
        for seed in (3, 1, 5):
            w = new_world(seed, 36, founding_scenario="random")
            w.foreign = foreign.initial_state(w.seed)
            cpi0, goods0 = w.econ.cpi, w.econ.goods_rel
            engine.begin_month(w)
            engine.step(w)
            self.assertLess(abs(w.econ.cpi / cpi0 - 1.0), 0.005, f"seed {seed}: Month-1 consumer prices moved")
            self.assertLess(abs(w.econ.goods_rel / goods0 - 1.0), 0.01, f"seed {seed}: Month-1 goods prices moved")

    def test_the_founding_food_price_follows_the_harvest(self):
        w = new_world(3, 36, founding_scenario="random")
        self.assertLess(w.econ.food_rel, 0.95, "seed 3's founding harvest is in surplus, so food starts cheap")
        self.assertEqual(w.econ.cpi, 1.0, "the founding price index is 1.0 whatever the food price")


class FoundingOutputGap(unittest.TestCase):
    """EC5: the starting output gap is what the founded economy implies, not zero by construction (start conditions
    have every friction at 1, so production equalled potential before the inherited conditions were applied)."""

    def test_the_starting_gap_is_measured_on_the_founded_economy(self):
        for seed in (1, 3, 5):
            w = new_world(seed, 36, founding_scenario="random")
            e = w.econ
            self.assertGreater(abs(e.output_gap), 0.005, f"seed {seed}: the founding left the gap at zero")
            self.assertEqual(e.prev_output_gap, e.output_gap, f"seed {seed}: Okun would read a widening in Month 1")
            produced = economy.produce(copy.deepcopy(w))["gdp_real"]
            implied = produced / economy.frictionless(w) - 1.0
            self.assertAlmostEqual(e.output_gap, implied, places=9, msg=f"seed {seed}: gap is not the founded gap")

    def test_start_conditions_without_a_founding_keep_a_zero_gap(self):
        w = new_world(3, 36, founding_scenario="none")
        self.assertAlmostEqual(w.econ.output_gap, 0.0, places=9)


class LeagueLoanLedger(unittest.TestCase):
    """EC1: a League tranche is one asset (gold) and one liability (foreign debt). It funds the crown budget once, so
    it leaves the government's net position unchanged. Before, the reserves rose by the tranche and the crown need fell
    by it: a 25M loan raised the net position by 24.9M."""

    @staticmethod
    def net_position(loan: float) -> float:
        w = new_world(3, 36, founding_scenario="random")
        w.foreign = foreign.initial_state(w.seed)
        w.foreign["league"]["loan"]["interest"] = 0.0      # isolates the ledger from the interest cost of the debt
        w.dip.league_loan_pending = loan
        engine.begin_month(w)
        engine.step(w)
        e = w.econ
        g = w.zone_of("karamaniya").price                   # gold to crowns at the going rate
        return e.gold * g - e.debt_dom - e.debt_for * g - e.arrears

    def test_a_loan_leaves_the_government_net_position_unchanged(self):
        change = self.net_position(25e6) - self.net_position(0.0)
        self.assertLess(abs(change), 1e3, f"the 25M tranche changed the net position by {change / 1e6:+.2f}M")


class PassThroughAccumulates(unittest.TestCase):
    """EC3: a depreciation reaches consumer prices through a price gap that closes over the following months (the
    comment at economy.money_and_prices promises this). Before, the pass-through was one month's multiplier: a 10%
    fall in the karam raised the price level 4.0% in its month and the level was back to 0.1% above the no-shock path
    the next month."""

    @staticmethod
    def price_levels(shock_month):
        real = causality.depreciation
        w = new_world(3, 36, founding_scenario="random")
        w.foreign = foreign.initial_state(w.seed)
        w.econ.currency_launch = 0                      # the karam is in use from Month 1
        levels = []
        try:
            for m in range(10):
                causality.depreciation = (lambda world: 0.10) if m == shock_month else real
                engine.begin_month(w)
                engine.step(w)
                levels.append(w.econ.cpi)
        finally:
            causality.depreciation = real
        return levels

    def test_the_price_level_keeps_most_of_a_depreciation(self):
        import math
        shocked, plain = self.price_levels(3), self.price_levels(None)
        gap = [math.log(a / b) for a, b in zip(shocked, plain)]
        self.assertGreater(gap[3], 0.02, "a 10% fall in the karam left almost no price effect in its month")
        self.assertGreater(gap[9], 0.5 * gap[3],
                           f"the price effect fell from {gap[3]:+.2%} to {gap[9]:+.2%} within six months")


class PriceTraceWeights(unittest.TestCase):
    """EC7: the trace of why prices moved uses the consumer price formula's own weights and names only its terms. The
    trace total is the month's change, so each food or goods term is its weight times this month's change in that
    relative price, over the bracket it sits in (before: other weights, levels, and two channels the formula lacks)."""

    def test_food_is_weighted_as_the_formula_weights_it(self):
        w = new_world(3, 36, founding_scenario="random")
        w.foreign = foreign.initial_state(w.seed)
        food0, goods0 = w.econ.food_rel, w.econ.goods_rel
        bracket0 = 0.40 * food0 + 0.35 * goods0 + 0.25          # crown: imp = 1, the formula's bracket at the start
        engine.begin_month(w)
        engine.step(w)
        entry = causality.trace_for(w, "inflation", w.month - 1)
        contributions = entry["contributions"]
        self.assertNotIn("excess_wage_growth", contributions)
        self.assertNotIn("import_shortage", contributions)
        expected = 0.40 * (0.8 + 0.2) * (w.econ.food_rel - food0) / bracket0
        self.assertAlmostEqual(contributions.get("food_relative_price", 0.0), expected, places=9)

    def test_the_contributions_add_up_to_the_month_change(self):
        w = new_world(1, 36, founding_scenario="random")
        w.foreign = foreign.initial_state(w.seed)
        for _ in range(4):
            engine.begin_month(w)
            engine.step(w)
        entry = causality.trace_for(w, "inflation", w.month - 1)
        self.assertAlmostEqual(sum(entry["contributions"].values()), entry["total"], delta=0.005)


class CurrencyLaunchContinuity(unittest.TestCase):
    """EC6: at the launch the karam zone is scaled on the same capacity the later months use (potential output), so
    the new zone prices where the crown did. Before, the scale used the launch month's actual output and the zone was
    0.33% above the crown in its first month."""

    def test_the_new_zone_prices_where_the_crown_did(self):
        w = new_world(3, 36, founding_scenario="random")
        w.foreign = foreign.initial_state(w.seed)
        w.econ.currency_launch = 2                       # the karam goes live in Month 3
        for _ in range(3):
            engine.begin_month(w)
            engine.step(w)
        self.assertEqual(w.econ.currency, "karam")
        karam = w.zone_of("karamaniya")
        crown = w.zone_of("veleria")
        self.assertLess(abs(karam.price / crown.price - 1.0), 0.001,
                        f"the karam zone sits {karam.price / crown.price - 1.0:+.2%} from the crown at the launch")


class ForeignInterestFromReserves(unittest.TestCase):
    """EC8: interest on foreign debt is a claim in gold, so it is paid from the reserves, not from the crown budget.
    Before, 100M of foreign debt added 0.42M crowns to the budget and left the reserves unchanged."""

    @staticmethod
    def month(debt_for: float):
        w = new_world(3, 36, founding_scenario="random")
        w.foreign = foreign.initial_state(w.seed)
        w.econ.debt_for = debt_for
        price = w.zone_of("karamaniya").price               # the fiscal step converts at the price it starts with
        engine.begin_month(w)
        engine.step(w)
        return w.econ, price

    def test_foreign_interest_leaves_the_budget_and_comes_out_of_gold(self):
        plain, _ = self.month(0.0)
        indebted, g = self.month(100e6)
        self.assertGreater(indebted.interest_for, 4e5)
        self.assertLess(abs(indebted.spending - plain.spending), 1.0, "foreign interest reached the crown budget")
        gold_paid = plain.gold - indebted.gold
        self.assertAlmostEqual(gold_paid, indebted.interest_for / g, delta=1.0,
                               msg="the reserves did not pay the foreign interest")


class UtilisationCap(unittest.TestCase):
    """EC9: a plant cannot run above its capacity. With energy, credit and confidence at their maximum, the demand
    support from past spending can lift utilisation above 1; before, output rose with the impulse past capacity."""

    @staticmethod
    def output(impulse: float):
        w = new_world(1, 36, founding_scenario="random")
        w.foreign = foreign.initial_state(w.seed)
        w.policy.imports = "max"                      # energy from abroad, so energy reaches its full 1.0
        for p in w.pops:
            p.unrest = 0.02                           # no uncertainty discount
        w.econ.fiscal_impulse = impulse
        return economy.produce(w)

    def test_industry_and_services_stop_at_capacity(self):
        low, high = self.output(0.04), self.output(0.06)
        self.assertAlmostEqual(low["industry"] / high["industry"], 1.0, places=9,
                               msg="industrial output rose with demand past full utilisation")
        self.assertAlmostEqual(low["services"] / high["services"], 1.0, places=9,
                               msg="services output rose with demand past full utilisation")


class DeflationLabel(unittest.TestCase):
    """EC10: a fall in prices is named as deflation, not as high inflation (research label only; no prompt reads it)."""

    def test_a_price_fall_is_deflation(self):
        w = new_world(1, 6)
        w.econ.infl = -0.05                             # about -46% a year
        self.assertEqual(causality.regime(w), causality.DEFLATION)
        self.assertIn(causality.DEFLATION, causality.REGIMES)

    def test_high_inflation_is_still_high_inflation(self):
        w = new_world(1, 6)
        w.econ.infl = 0.06
        self.assertEqual(causality.regime(w), causality.HIGH_INFLATION)


class ComplianceCutsReachRevenue(unittest.TestCase):
    """IN-L1: a compliance cut from a dilemma or from the founding is a shock the compliance formula subtracts, so it
    reaches revenue. Before, the cut was written to a value that the formula recomputed later in the same month."""

    @staticmethod
    def compliance_after_a_month(live_issue: bool) -> float:
        w = new_world(4, 36)
        w.foreign = foreign.initial_state(w.seed)
        w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
        w.month = 6
        if live_issue:
            issue = {"id": "I7-governor_defiance", "kind": "governor_defiance", "title": "t", "month": w.month,
                     "text": "", "readings": [], "tradeoffs": [], "tags": [], "office_notes": {}, "region": "highlands",
                     "target": None, "truth": {}, "status": "active", "expires_month": w.month + 2, "applied": {},
                     "started": False}
            dilemmas.state(w)["active"].append(issue)
        engine.begin_month(w)
        engine.step(w)
        return w.econ.compliance

    def test_a_governor_defiance_cut_lowers_the_compliance_that_taxes_use(self):
        cut = self.compliance_after_a_month(False) - self.compliance_after_a_month(True)
        self.assertAlmostEqual(cut, 0.01, delta=0.0005, msg="the dilemma's cut did not reach the compliance rate")


class OperationsReachTheirTargets(unittest.TestCase):
    """MI3 and MI8: an office's operational choice acts where its help text says. A conservative treasury trims the
    goods it buys abroad (not energy and output), and civil support feeds the hungriest (not a value the allocation
    overwrites later in the month)."""

    @staticmethod
    def world(seed: int):
        w = new_world(seed, 36)
        w.foreign = foreign.initial_state(w.seed)
        w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
        return w

    def test_conservative_reserves_import_less_and_keep_gold(self):
        normal, conservative = self.world(5), self.world(5)
        operations.set_orders(conservative, "B", {"treasury": {"reserve_policy": "conservative"}})
        for w in (normal, conservative):
            engine.begin_month(w)
            engine.step(w)
        self.assertAlmostEqual(conservative.econ.goods_imports / normal.econ.goods_imports, 0.97, places=6,
                               msg="a conservative treasury did not trim goods imports")
        self.assertGreater(conservative.econ.gold, normal.econ.gold)

    def test_civil_support_feeds_the_hungriest(self):
        def month(focus):
            w = self.world(5)
            operations.set_orders(w, "D", {"army": {"training_focus": focus}})
            w.econ.food_stock = 0.0                    # a shortage the state grain can feed:
            w.econ.farm_incentive = 0.2                # the harvest falls well short of need
            engine.begin_month(w)
            engine.step(w)
            return w
        civil, readiness = month("civil_support"), month("readiness")
        hunger_civil = sum(p.size * p.hunger for p in civil.k_pops())
        hunger_readiness = sum(p.size * p.hunger for p in readiness.k_pops())
        self.assertLess(hunger_civil, hunger_readiness - 1.0, "civil support did not feed anyone")
        self.assertLess(civil.econ.state_grain, readiness.econ.state_grain, "the feeding did not come from the grain")


if __name__ == "__main__":
    unittest.main()
