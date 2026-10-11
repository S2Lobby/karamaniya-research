"""World engine 20: a higher policy rate in the karam lowers the price level (backlog T94).

Until engine 20 it raised it, through four faults that each turned a tighter rate into dearer goods:
- the whole domestic debt repriced to the new rate at once, so a hike from 6% to 60% lifted the interest bill from 4% to
  28% of monthly output in its first month, and the deficit, the arrears and the unrest drained the reserves and sank
  the karam;
- the goods market read a credit squeeze's lower output as a shortage, against a fixed demand;
- the import bill stayed fixed while exports fell with industry, so the squeeze drained the reserves;
- the karam's launch scaled its price on Karamaniya's own rate, so a rate raised before the launch never bit.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import director, economy, engine, versions  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def karam_run(months: int, rate: float | None = None, hike_from: int = 4, printing: float = 0.02, seed: int = 5):
    """A world that launches the karam in Month 3 and prints `printing` of its money a month from then; from
    `hike_from` its policy rate is `rate` (None keeps the founding 6%). Nothing else governs."""
    w = new_world(seed, 40)
    original = director.act
    director.act = lambda world, *_a, **_k: setattr(world.dip, "inbox", [])
    try:
        for _ in range(months):
            if w.ended():
                break
            engine.begin_month(w)
            w.const.elected, w.const.election_month = True, 99
            if w.month == 1:
                w.econ.currency_launch = 2
            if w.month >= 2:
                w.policy.printing = printing
                if rate is not None and w.month >= hike_from:
                    w.policy.rate = rate
            engine.step(w)
    finally:
        director.act = original
    return w


class Versions(unittest.TestCase):
    def test_the_bump(self):
        self.assertEqual((versions.WORLD_ENGINE, versions.AGENT_PROMPT, versions.PSYCHOLOGY), (20, 16, 8))


class AHikeLowersThePriceLevel(unittest.TestCase):
    def test_a_moderate_hike_lowers_prices_at_every_horizon(self):
        for seed in (1, 5):
            for rate, printing in ((0.35, 0.02), (0.20, 0.01), (0.15, 0.0)):
                for months in (12, 24, 36):
                    with self.subTest(seed=seed, rate=rate, printing=printing, months=months):
                        hiked = karam_run(months, rate, printing=printing, seed=seed)
                        loose = karam_run(months, None, printing=printing, seed=seed)
                        self.assertLess(hiked.econ.cpi, loose.econ.cpi)

    def test_a_hike_before_the_launch_bites_after_it(self):
        """The karam is scaled on the rate its money was held at under the crown, so a rate raised before the launch
        moves the price from the launch on; scaled on Karamaniya's own rate, it was absorbed into the scale."""
        hiked = karam_run(10, 0.35, hike_from=1)
        loose = karam_run(10, None)
        self.assertLess(hiked.zone_of("karamaniya").price, loose.zone_of("karamaniya").price)


class TheDebtReprices(unittest.TestCase):
    def test_only_the_maturing_slice_and_new_borrowing_take_the_new_rate(self):
        class Econ:
            debt_dom, debt_rate, debt_rated, debt_short_share = 1100.0, 0.08, 1000.0, 0.20
        e = Econ()
        economy._reprice_debt(e, 1000.0, 0.62)
        kept = 1000.0 * (1 - 0.20 / 12)
        self.assertAlmostEqual(e.debt_rate, (kept * 0.08 + (1100.0 - kept) * 0.62) / 1100.0)
        self.assertEqual(e.debt_rated, 1100.0)

    def test_repayment_leaves_the_rate(self):
        class Econ:
            debt_dom, debt_rate, debt_rated, debt_short_share = 900.0, 0.08, 1000.0, 0.20
        e = Econ()
        economy._reprice_debt(e, 1000.0, 0.62)
        self.assertAlmostEqual(e.debt_rate, 0.08)

    def test_a_hike_raises_the_interest_bill_month_by_month_not_at_once(self):
        loose = karam_run(5, None)
        hiked = karam_run(5, 0.60)
        share = lambda w: w.econ.interest_dom / w.econ.gdp_nominal  # noqa: E731
        # At once, the whole stock at 62% would have cost about 28% of monthly output; repricing a month's slice at a time
        # it is a few points above the founding bill.
        self.assertLess(share(hiked), share(loose) + 0.03)
        self.assertGreater(share(hiked), share(loose))

    def test_bonds_issued_since_the_last_budget_carry_the_market_rate(self):
        w = new_world(2, 36)
        engine.begin_month(w)
        engine.step(w)                              # the first budget sets the stock's rate
        rated, rate = w.econ.debt_rated, w.econ.debt_rate
        w.econ.debt_dom += 0.1 * rated              # bonds a motion issued during the month
        w.policy.rate = 0.30
        engine.begin_month(w)
        engine.step(w)
        self.assertGreater(w.econ.debt_rate, rate + 0.1 * 0.30 / 1.1 * 0.5)


class DemandFollowsCredit(unittest.TestCase):
    def test_a_credit_squeeze_is_no_shortage_of_goods(self):
        loose = karam_run(8, None)
        hiked = karam_run(8, 0.60)
        self.assertLess(hiked.econ.credit_conditions, 0.95)
        self.assertLessEqual(hiked.econ.goods_rel, loose.econ.goods_rel * 1.02)

    def test_goods_imports_follow_credit(self):
        w = new_world(4, 36)
        engine.begin_month(w)
        prod = economy.produce(w)
        full = economy.trade_and_food(w, prod) and w.econ.goods_imports
        w2 = new_world(4, 36)
        engine.begin_month(w2)
        prod2 = economy.produce(w2)
        w2.econ.credit_conditions = 0.8
        economy.trade_and_food(w2, prod2)
        self.assertAlmostEqual(w2.econ.goods_imports, 0.8 * full, delta=1.0)

    def test_a_world_that_keeps_its_rate_keeps_its_credit(self):
        """Credit tightens only above a 4% real rate, so a world at the founding rate barely moves: the new demand terms
        leave it as it was."""
        w = karam_run(12, None, printing=0.01)
        self.assertGreater(w.econ.credit_conditions, 0.99)


if __name__ == "__main__":
    unittest.main()
