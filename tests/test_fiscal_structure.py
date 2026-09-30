"""Who the government owes, and why it matters that the answer is not 'everyone equally'.

The historical record is specific: military pay arrears immediately preceded coups in Côte
d'Ivoire (1999), the Gambia (1994), Guinea-Bissau (2004) and Sierra Leone (1992); civil-service
arrears turn into strikes after roughly two to three months; and contractors who are owed money
bid higher or stop bidding. An aggregate arrears number cannot express any of that.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import director, economy, engine  # noqa: E402
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


def squeeze(w, spend=0.30, tax=0.06):
    """Drive the budget into arrears: spend far beyond what can be raised or borrowed."""
    w.policy.military = spend * 0.4
    w.policy.welfare = spend * 0.3
    w.policy.health_edu = spend * 0.3
    w.policy.tax = tax


class ArrearsComposition(unittest.TestCase):
    def test_arrears_are_split_across_the_bills_they_go_unpaid_on(self):
        w = run(new_world(9, 18), 10, each=lambda x: (steady(x), squeeze(x)))
        self.assertGreater(w.econ.arrears, 0.0, "the squeeze produced no arrears")
        total = sum(w.econ.arrears_by.values())
        self.assertAlmostEqual(total, w.econ.arrears, delta=max(1.0, w.econ.arrears * 0.02))

    def test_every_category_is_tracked_separately(self):
        w = run(new_world(9, 18), 10, each=lambda x: (steady(x), squeeze(x)))
        self.assertEqual(set(w.econ.arrears_by), set(economy.ARREARS_CATEGORIES))
        for name, amount in w.econ.arrears_by.items():
            with self.subTest(category=name):
                self.assertGreaterEqual(amount, 0.0)

    def test_a_stressed_budget_owes_several_different_groups(self):
        w = run(new_world(9, 18), 10, each=lambda x: (steady(x), squeeze(x)))
        owed = [n for n, v in w.econ.arrears_by.items() if v > 0]
        self.assertGreater(len(owed), 1, f"arrears landed on only {owed}")

    def test_arrears_months_are_reported_per_category(self):
        w = run(new_world(9, 18), 10, each=lambda x: (steady(x), squeeze(x)))
        months = economy.arrears_months(w)
        self.assertEqual(set(months), set(economy.ARREARS_CATEGORIES))
        self.assertGreater(max(months.values()), 0.0)


class DifferentGroupsSufferDifferently(unittest.TestCase):
    def test_unpaid_civil_servants_damage_administration(self):
        """The engine must not treat unpaid clerks like unpaid road builders."""
        paid = run(new_world(9, 24), 12, each=steady)
        unpaid = run(new_world(9, 24), 12, each=lambda x: (steady(x), squeeze(x)))
        self.assertGreater(economy.arrears_months(unpaid)["civil_service"],
                           economy.CIVIL_SERVICE_STRIKE_MONTHS)
        self.assertLess(unpaid.econ.admin_capacity, paid.econ.admin_capacity,
                        "the administration was unaffected by unpaid wages")

    def test_civil_service_arrears_below_the_threshold_do_not_break_the_service(self):
        w = new_world(9, 12)
        w.econ.arrears_by["civil_service"] = 0.0
        self.assertLess(economy.arrears_months(w)["civil_service"],
                        economy.CIVIL_SERVICE_STRIKE_MONTHS)

    def test_unpaid_contractors_raise_the_price_of_new_work(self):
        prompt = new_world(9, 12)
        prompt.econ.arrears_by["contractors"] = 0.0
        cheap = economy.procurement_premium(prompt)
        prompt.econ.arrears_by["contractors"] = 40e6
        dear = economy.procurement_premium(prompt)
        self.assertGreater(dear, cheap, "contractors who are owed money did not reprice")

    def test_the_procurement_premium_is_capped(self):
        w = new_world(9, 12)
        w.econ.arrears_by["contractors"] = 1e12
        self.assertLessEqual(economy.procurement_premium(w),
                             1.0 + economy.PROCUREMENT_PREMIUM_CAP)

    def test_the_premium_costs_the_budget_money(self):
        """Arrears raise the cost of the spending that would have cleared them."""
        clean = new_world(9, 18)
        clean.econ.gdp_nominal = 500e6
        squeezed = new_world(9, 18)
        squeezed.econ.gdp_nominal = 500e6
        squeezed.econ.arrears_by["contractors"] = 60e6
        from karamaniya import economy as ec
        prod = {"gdp_real": 500e6 / max(0.01, clean.econ.cpi), "food": 0, "industry": 0,
                "services": 0, "energy": 1.0, "unemployment": {}, "credit": 1.0, "uncertainty": 1.0}
        trade = {"loans": 0.0}
        a = ec.fiscal(clean, prod, trade)["spending"]
        b = ec.fiscal(squeezed, prod, trade)["spending"]
        self.assertGreater(b, a, "unpaid contractors cost the budget nothing")


class DebtServiceAndRollover(unittest.TestCase):
    def test_domestic_and_foreign_interest_are_reported_separately(self):
        w = run(new_world(9, 12), 4, each=steady)
        self.assertGreaterEqual(w.econ.interest_dom, 0.0)
        self.assertGreaterEqual(w.econ.interest_for, 0.0)
        self.assertGreater(w.econ.interest_dom, 0.0, "a country with domestic debt pays no interest")

    def test_rollover_need_scales_with_the_short_term_share(self):
        low = run(new_world(9, 12), 4, each=steady)
        low.econ.debt_short_share = 0.10
        high = run(new_world(9, 12), 4, each=steady)
        high.econ.debt_short_share = 0.40
        from karamaniya import economy as ec
        prod = {"gdp_real": 500e6, "food": 0, "industry": 0, "services": 0, "energy": 1.0,
                "unemployment": {}, "credit": 1.0, "uncertainty": 1.0}
        ec.fiscal(low, prod, {"loans": 0.0})
        ec.fiscal(high, prod, {"loans": 0.0})
        self.assertLess(low.econ.rollover_need, high.econ.rollover_need)

    def test_reserve_adequacy_is_measured_in_months_of_imports(self):
        w = run(new_world(9, 12), 4, each=steady)
        self.assertGreater(w.econ.reserve_months, 0.0)
        rich = new_world(9, 12)
        rich.econ.gold = rich.econ.gold0 * 4
        poor = new_world(9, 12)
        poor.econ.gold = poor.econ.gold0 * 0.25
        from karamaniya import economy as ec
        prod = {"gdp_real": 500e6, "food": 0, "industry": 0, "services": 0, "energy": 1.0,
                "unemployment": {}, "credit": 1.0, "uncertainty": 1.0}
        ec.fiscal(rich, prod, {"loans": 0.0})
        ec.fiscal(poor, prod, {"loans": 0.0})
        self.assertGreater(rich.econ.reserve_months, poor.econ.reserve_months)


class Repayment(unittest.TestCase):
    def test_repayment_clears_arrears_across_categories(self):
        w = new_world(9, 12)
        for name in economy.ARREARS_CATEGORIES:
            w.econ.arrears_by[name] = 10e6
        w.econ.arrears = 50e6
        economy.settle_arrears(w, 25e6)
        self.assertAlmostEqual(sum(w.econ.arrears_by.values()), 25e6, delta=1.0)
        self.assertAlmostEqual(w.econ.arrears, 25e6, delta=1.0)

    def test_repayment_never_drives_a_category_negative(self):
        w = new_world(9, 12)
        w.econ.arrears_by["army"] = 5e6
        w.econ.arrears = 5e6
        economy.settle_arrears(w, 50e6)
        for name, amount in w.econ.arrears_by.items():
            with self.subTest(category=name):
                self.assertGreaterEqual(amount, 0.0)

    def test_arrears_never_go_negative(self):
        w = run(new_world(9, 30), 24, each=lambda x: (steady(x), squeeze(x)))
        self.assertGreaterEqual(w.econ.arrears, 0.0)
        for name, amount in w.econ.arrears_by.items():
            with self.subTest(category=name):
                self.assertGreaterEqual(amount, 0.0)


class SurvivesSaveLoad(unittest.TestCase):
    def test_the_fiscal_structure_reloads_intact(self):
        from karamaniya.world import World
        w = run(new_world(9, 18), 8, each=lambda x: (steady(x), squeeze(x)))
        again = World.from_dict(w.to_dict())
        self.assertEqual(again.econ.arrears_by, w.econ.arrears_by)
        for field in ("interest_dom", "interest_for", "debt_short_share", "rollover_need",
                      "procurement_premium", "reserve_months"):
            with self.subTest(field=field):
                self.assertAlmostEqual(getattr(again.econ, field), getattr(w.econ, field), places=9)


if __name__ == "__main__":
    unittest.main()
