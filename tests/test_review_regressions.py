"""Regressions for the defects an adversarial review found in this shift's own work.

Each test here corresponds to a specific bug that shipped in a commit and was caught afterwards.
They are kept together so the failure mode is legible: these are not features, they are things
that were wrong and would be wrong again if the reasoning behind the fix were undone.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import causality as cz, director, economy, engine  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def run(w, months, each=None):
    original = director.act
    director.act = lambda world, *_a, **_k: setattr(world.dip, "inbox", [])
    try:
        for _ in range(months):
            if w.ended():
                break
            engine.begin_month(w)
            if each:
                each(w)
            engine.step(w)
    finally:
        director.act = original
    return w


def steady(w):
    w.const.elected = True
    w.const.election_month = 99


def squeeze(w):
    steady(w)
    w.policy.military = 0.12
    w.policy.welfare = 0.09
    w.policy.health_edu = 0.09
    w.policy.tax = 0.06


class ArrearsMonthsWereTwelveTimesTooLarge(unittest.TestCase):
    """The accrual used a full monthly bill; the month converter divided that same bill by
    twelve. One month of unpaid wages reported as a year owed, so every consequence — the
    civil-service strike threshold, the contractor premium, the admin collapse — fired twelve
    times too early."""

    def test_one_month_of_unpaid_pay_reads_as_one_month(self):
        w = new_world(1, 12)
        w.econ.gdp_nominal = 500e6
        w.policy.military = 0.05
        bills = economy.budget_bills(w)
        w.econ.arrears_by["army"] = bills["army"]
        self.assertAlmostEqual(economy.arrears_months(w)["army"], 1.0, places=6)

    def test_every_category_converts_the_same_way(self):
        w = new_world(1, 12)
        w.econ.gdp_nominal = 500e6
        bills = economy.budget_bills(w)
        for name, bill in bills.items():
            if bill <= 0:
                continue
            w.econ.arrears_by[name] = bill
            with self.subTest(category=name):
                self.assertAlmostEqual(economy.arrears_months(w)[name], 1.0, places=6)
            w.econ.arrears_by[name] = 0.0

    def test_accrual_and_conversion_come_from_one_source(self):
        """They cannot drift apart again: both read `budget_bills`."""
        w = new_world(1, 12)
        w.econ.gdp_nominal = 500e6
        before = economy.budget_bills(w)
        w.policy.military = 0.10
        after = economy.budget_bills(w)
        self.assertNotEqual(before["army"], after["army"],
                            "the bill did not respond to policy, so it is not the live one")

    def test_a_modest_shortfall_does_not_instantly_break_the_administration(self):
        """The concrete symptom: a 1.75pc-of-output shortfall collapsed admin capacity to its
        floor within five months because civil servants read as years behind."""
        def mild(w):
            steady(w)
            w.policy.tax = 0.16
        w = run(new_world(9, 24), 6, each=mild)
        self.assertLess(economy.arrears_months(w)["civil_service"],
                        economy.CIVIL_SERVICE_STRIKE_MONTHS)
        self.assertGreater(w.econ.admin_capacity, 0.5,
                           "the administration collapsed on a trivial arrears stock")


class ContractorsWereDormantOrThirtyTimesWrong(unittest.TestCase):
    """The accrual base was `farm_support + regional_fund` while the divisor was
    `farm_support + 0.02`. Under default policy the base was zero, so the whole premium feedback
    loop was dead; with farm support on, one month read as eight."""

    def test_contractors_accrue_by_default(self):
        """Most government procurement is military, so the category must not be empty by default."""
        w = new_world(1, 12)
        w.econ.gdp_nominal = 500e6
        self.assertGreater(economy.budget_bills(w)["contractors"], 0.0)

    def test_the_premium_stays_at_its_floor_while_bills_are_paid(self):
        w = run(new_world(9, 24), 8, each=steady)
        self.assertAlmostEqual(economy.procurement_premium(w), 1.0, places=3)

    def test_the_premium_scales_with_how_far_behind_the_bills_are(self):
        """It must respond gradually, not jump to the cap the moment any arrears appear."""
        w = new_world(9, 12)
        w.econ.gdp_nominal = 500e6
        bills = economy.budget_bills(w)
        seen = []
        # One to six months of the contractor bill unpaid.
        for months in (1, 2, 4, 6):
            w.econ.arrears_by["contractors"] = bills["contractors"] * months
            seen.append(economy.procurement_premium(w))
        for a, b in zip(seen, seen[1:]):
            with self.subTest(a=a, b=b):
                self.assertLessEqual(a, b, "the premium fell as arrears grew")
        self.assertLess(seen[0], 1.0 + economy.PROCUREMENT_PREMIUM_CAP,
                        "a single month behind already cost the maximum markup")
        self.assertLess(seen[1], 1.0 + economy.PROCUREMENT_PREMIUM_CAP)

    def test_the_cap_is_reached_only_once_contractors_are_well_behind(self):
        w = new_world(9, 12)
        w.econ.gdp_nominal = 500e6
        bills = economy.budget_bills(w)
        w.econ.arrears_by["contractors"] = bills["contractors"] * 1
        self.assertLess(economy.procurement_premium(w), 1.0 + economy.PROCUREMENT_PREMIUM_CAP)
        w.econ.arrears_by["contractors"] = bills["contractors"] * 12
        self.assertAlmostEqual(economy.procurement_premium(w),
                               1.0 + economy.PROCUREMENT_PREMIUM_CAP, places=6)

    def test_the_premium_does_respond_to_a_real_default(self):
        w = run(new_world(9, 24), 12, each=squeeze)
        self.assertGreater(economy.procurement_premium(w), 1.0)


class PayingArrearsDidNotClearThem(unittest.TestCase):
    """Three writers reduced the total without touching the composition, so settling everything
    in full still left the administration destroyed and suppliers still repricing."""

    def test_settling_in_full_clears_every_category(self):
        w = run(new_world(9, 24), 12, each=squeeze)
        self.assertGreater(w.econ.arrears, 0.0)
        economy.settle_arrears(w, w.econ.arrears)
        self.assertAlmostEqual(w.econ.arrears, 0.0, places=3)
        self.assertAlmostEqual(sum(w.econ.arrears_by.values()), 0.0, places=3)
        for name, months in economy.arrears_months(w).items():
            with self.subTest(category=name):
                self.assertAlmostEqual(months, 0.0, places=6)

    def test_the_consequences_stand_down_once_the_bills_are_paid(self):
        w = run(new_world(9, 24), 12, each=squeeze)
        self.assertGreater(economy.procurement_premium(w), 1.0)
        economy.settle_arrears(w, w.econ.arrears)
        self.assertAlmostEqual(economy.procurement_premium(w), 1.0, places=3)

    def test_the_composition_always_sums_to_the_total(self):
        w = new_world(9, 24)
        for _ in range(12):
            run(w, 1, each=squeeze)
            with self.subTest(month=w.month):
                total = sum(w.econ.arrears_by.values())
                self.assertAlmostEqual(total, w.econ.arrears,
                                       delta=max(1.0, w.econ.arrears * 0.01))

    def test_inherited_arrears_arrive_with_a_composition(self):
        """Founding and scenario paths used to write the total alone, so inherited liabilities
        never carried their differentiated consequences."""
        from karamaniya.founding import initialize
        w = new_world(3, 24)
        initialize(w, "fiscal_arrears", "default", [])
        self.assertGreater(w.econ.arrears, 0.0)
        self.assertGreater(sum(w.econ.arrears_by.values()), 0.0)

    def test_the_public_helper_is_the_only_way_down(self):
        """Settle more than is owed and nothing goes negative."""
        w = new_world(1, 12)
        w.econ.gdp_nominal = 500e6
        economy.seed_arrears(w, 50e6)
        paid = economy.settle_arrears(w, 1e12)
        self.assertAlmostEqual(paid, 50e6, delta=1.0)
        self.assertGreaterEqual(w.econ.arrears, 0.0)
        for amount in w.econ.arrears_by.values():
            self.assertGreaterEqual(amount, 0.0)


class DepreciationWasDeflationary(unittest.TestCase):
    """`e.fx` is crowns per karam, so a FALLING rate is a depreciation. Two terms read it the
    other way round, which made a currency collapse cheapen imports: a 69pc devaluation was
    contributing about -1.3pc a month to the CPI."""

    def test_depreciation_is_measured_as_a_fall_in_the_rate(self):
        w = new_world(1, 12)
        w.econ.fx_prev = 1.0
        w.econ.fx = 0.5
        self.assertAlmostEqual(cz.depreciation(w), 1.0, places=6)

    def test_appreciation_is_negative(self):
        w = new_world(1, 12)
        w.econ.fx_prev = 0.5
        w.econ.fx = 1.0
        self.assertLess(cz.depreciation(w), 0.0)

    def test_a_collapse_raises_import_prices(self):
        w = new_world(1, 12)
        w.econ.currency = "karam"
        w.econ.fx_prev = 1.0
        w.econ.fx = 0.31
        self.assertGreater(cz.import_price_step(w), 0.0)

    def test_the_consumer_price_term_agrees_with_the_import_term(self):
        """Both read the same `depreciation`, so they cannot disagree on direction again."""
        w = new_world(1, 12)
        w.econ.currency = "karam"
        fx_prev, fx = w.econ.fx_prev, w.econ.fx
        w.econ.fx_prev, w.econ.fx = 1.0, 0.4
        self.assertGreater(cz.depreciation(w), 0.0)
        self.assertGreater(cz.pass_through(w) * cz.depreciation(w), 0.0)
        w.econ.fx_prev, w.econ.fx = fx_prev, fx

    def test_a_currency_crisis_now_raises_the_price_level(self):
        """End to end, through the real mechanism.

        The rate cannot be set by hand here: once the karam exists, `money_and_prices` derives it
        from the price ratio and confidence. So the crisis is driven the way a real one happens —
        heavy money creation and depleted reserves — and the trace is read afterwards.
        """
        w = new_world(11, 24)

        def crisis(x):
            steady(x)
            if x.month == 1:
                x.econ.currency_launch = 2
            if x.month >= 2:
                x.policy.printing = 0.08
                x.econ.gold = max(1e5, x.econ.gold * 0.92)
        run(w, 14, each=crisis)
        self.assertEqual(w.econ.currency, "karam")
        self.assertLess(w.econ.fx, 0.9, "the currency did not move at all")
        traces = [e for e in w.institutions.get("causal_trace", []) if e["variable"] == "inflation"]
        self.assertTrue(traces)
        positive = [t for t in traces if t["contributions"].get("import_cost", 0) > 0]
        self.assertTrue(positive,
                        "a falling karam never raised import costs in the trace")

    def test_a_falling_rate_and_the_import_channel_agree_in_sign(self):
        """The bug was a sign disagreement between two terms reading the same variable."""
        w = new_world(1, 12)
        w.econ.currency = "karam"
        w.econ.fx_prev = 1.0
        w.econ.fx = 0.5
        self.assertGreater(cz.depreciation(w), 0.0)
        self.assertGreater(cz.import_price_step(w), 0.0)


class TheLagProfileWasOneMonthLate(unittest.TestCase):
    """`apply_lags` runs before the budget resolves, so a share queued at zero months waited a
    full month and the declared 0/3/9 profile was really 1/4/10."""

    def test_the_immediate_share_is_applied_the_month_it_is_decided(self):
        w = new_world(1, 12)
        w.econ.gdp_nominal = 500e6
        w.econ.spending_prev = 100e6
        w.econ.spending = 120e6
        before = w.econ.fiscal_impulse
        cz.schedule_fiscal_impulse(w)
        self.assertAlmostEqual(w.econ.fiscal_impulse - before, 0.04 * 0.50, places=6)

    def test_only_the_later_shares_are_queued(self):
        w = new_world(1, 12)
        w.econ.gdp_nominal = 500e6
        w.econ.spending_prev = 100e6
        w.econ.spending = 120e6
        cz.schedule_fiscal_impulse(w)
        queued = cz.pending(w)
        self.assertEqual([e["due_month"] for e in queued], [3, 9])

    def test_the_shares_still_sum_to_the_whole_change(self):
        w = new_world(1, 12)
        w.econ.gdp_nominal = 500e6
        w.econ.spending_prev = 100e6
        w.econ.spending = 120e6
        cz.schedule_fiscal_impulse(w)
        total = w.econ.fiscal_impulse + sum(e["magnitude"] for e in cz.pending(w))
        self.assertAlmostEqual(total, 0.04, places=6)


class RolloverNeedWasDecorative(unittest.TestCase):
    """The comment claimed maturing debt crowds out new issuance; the code never subtracted it."""

    def _borrow(self, share):
        w = new_world(1, 12)
        e = w.econ
        e.gdp_nominal = 500e6
        e.debt_dom = 800e6
        e.debt_short_share = share
        e.interest_for = 0.0
        e.confidence = 0.5
        e.printed = 0.0
        w.policy.military = 0.20
        w.policy.welfare = 0.10
        w.policy.health_edu = 0.10
        w.policy.tax = 0.02
        prod = {"gdp_real": 500e6, "food": 0, "industry": 0, "services": 0, "energy": 1.0,
                "unemployment": {}, "credit": 1.0, "uncertainty": 1.0}
        return economy.fiscal(w, prod, {"loans": 0.0})["borrowed"]

    def test_a_heavier_rollover_calendar_crowds_out_new_borrowing(self):
        self.assertLess(self._borrow(0.90), self._borrow(0.0))

    def test_the_rollover_need_scales_with_the_short_term_share(self):
        w = new_world(1, 12)
        w.econ.debt_dom = 1000e6
        w.econ.debt_short_share = 0.0
        prod = {"gdp_real": 500e6, "food": 0, "industry": 0, "services": 0, "energy": 1.0,
                "unemployment": {}, "credit": 1.0, "uncertainty": 1.0}
        economy.fiscal(w, prod, {"loans": 0.0})
        low = w.econ.rollover_need
        w.econ.debt_short_share = 0.6
        economy.fiscal(w, prod, {"loans": 0.0})
        self.assertGreater(w.econ.rollover_need, low)


class TheCompositionCarriesInformation(unittest.TestCase):
    """Proportional accrual made every category report the same months owed, so the composition
    said nothing the aggregate did not. Governments pay in priority order."""

    def test_the_least_protected_bills_fall_behind_first(self):
        w = run(new_world(9, 24), 10, each=squeeze)
        months = economy.arrears_months(w)
        self.assertLess(months["army"], months["contractors"],
                        "soldiers fell as far behind as suppliers, which is not how it happens")

    def test_not_every_category_reports_the_same_number(self):
        w = run(new_world(9, 24), 8, each=squeeze)
        months = economy.arrears_months(w)
        self.assertGreater(len({round(v, 1) for v in months.values()}), 1,
                           "the composition is uniform, so it carries no information")


if __name__ == "__main__":
    unittest.main()
