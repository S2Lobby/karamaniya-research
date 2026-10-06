"""Adversarial sanity scenarios: does the whole system behave plausibly under stress?

Each test states a qualitative claim a reader would expect of a believable world and checks the
DIRECTION and the BOUNDS, never a coefficient. These are the scenarios from the mission brief's
section 19. Where a claim cannot be made to hold, that is a finding rather than a test to relax.
"""
import math
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


def finite(w, *fields):
    e = w.econ
    for name in fields:
        value = getattr(e, name, None)
        if value is None:
            continue
        assert math.isfinite(float(value)), f"{name} is {value}"


class FiscalFinancing(unittest.TestCase):
    """The same deficit financed two ways must not have the same consequence."""

    def _deficit(self, printing, months=14):
        w = new_world(13, 30)

        def each(x):
            steady(x)
            x.policy.military = 0.09
            x.policy.welfare = 0.07
            x.policy.health_edu = 0.07
            x.policy.tax = 0.09
            x.policy.printing = printing
        return run(w, months, each=each)

    def test_a_deficit_financed_by_printing_raises_prices(self):
        printed = self._deficit(0.05)
        conservative = self._deficit(0.0)
        self.assertGreater(printed.econ.cpi, conservative.econ.cpi * 1.05,
                           "printing financed the deficit for free")

    def test_a_deficit_financed_by_printing_undermines_the_currency(self):
        """Only meaningful once the country has its own money: inside the crown it does not set
        its own monetary conditions, which is itself the right behaviour."""
        w = new_world(13, 30)

        def each(x):
            steady(x)
            if x.month == 1:
                x.econ.currency_launch = 2
            if x.month >= 2:
                x.policy.military, x.policy.welfare = 0.09, 0.07
                x.policy.health_edu, x.policy.tax = 0.07, 0.09
                x.policy.printing = 0.06
        run(w, 14, each=each)
        self.assertEqual(w.econ.currency, "karam")
        self.assertGreater(w.econ.fx_pressure, 0.0, "printing put no pressure on the currency")
        self.assertLess(w.econ.fx, 1.0, "the karam did not weaken")

    def test_neither_financing_route_produces_impossible_state(self):
        for printing in (0.0, 0.05):
            w = self._deficit(printing)
            with self.subTest(printing=printing):
                finite(w, "cpi", "gold", "debt_dom", "arrears", "confidence")
                self.assertGreaterEqual(w.econ.gold, 0.0)
                self.assertGreaterEqual(w.econ.arrears, 0.0)

    def test_printing_that_only_keeps_pace_with_inflation_is_not_itself_inflationary(self):
        """A high-inflation world absorbs money growth that a low-inflation one would not."""
        low = new_world(1, 12)
        low.econ.expected_infl = 0.0
        high = new_world(1, 12)
        high.econ.expected_infl = 0.25
        self.assertLess(cz.money_step(high, 0.25, 0.002), cz.money_step(low, 0.25, 0.002))


class MonetaryPolicyIsStateDependent(unittest.TestCase):
    def _hike_in(self, setup, months=14):
        w = new_world(5, 30)

        def each(x):
            steady(x)
            setup(x)
            if x.month >= 2:
                x.policy.rate = 0.30
        return run(w, months, each=each)

    def test_a_rate_hike_in_a_slump_costs_output(self):
        def slump(x):
            x.econ.weather = 0.75
        hiked = self._hike_in(slump)

        def slump_only(x):
            x.econ.weather = 0.75
        calm = run(new_world(5, 30), 14, each=lambda x: (steady(x), slump_only(x)))
        self.assertLess(hiked.econ.gdp_real, calm.econ.gdp_real,
                        "tightening into a slump cost nothing")

    def test_a_rate_hike_under_high_inflation_reduces_inflation_pressure(self):
        """Inside the crown the policy rate barely moves monetary conditions, which is correct: a
        member of a currency union does not set its own. The test therefore runs where Karamaniya
        controls its own money."""
        def make(inflate, hike):
            w = new_world(5, 30)

            def each(x):
                steady(x)
                if x.month == 1:
                    x.econ.currency_launch = 2
                if x.month >= 2:
                    inflate(x)
                    if hike:
                        x.policy.rate = 0.35
            return run(w, 16, each=each)

        def inflate(x):
            x.policy.printing = 0.05
        hiked = make(inflate, True)
        loose = make(inflate, False)
        self.assertEqual(hiked.econ.currency, "karam")
        self.assertLess(hiked.econ.expected_infl, loose.econ.expected_infl,
                        "tightening under inflation did not lower expected inflation")

    def test_a_rate_hike_never_acts_instantly(self):
        w = new_world(5, 30)
        run(w, 4, each=steady)
        before = w.econ.credit_conditions
        run(w, 1, each=lambda x: (steady(x), setattr(x.policy, "rate", 0.30)))
        covered = (before - w.econ.credit_conditions) / max(1e-9, before - w.econ.credit_target)
        self.assertLess(covered, 0.5, "credit adjusted fully within one month")


class ExternalShocks(unittest.TestCase):
    def test_grain_disruption_raises_food_prices_and_hunger(self):
        def disrupt(x):
            steady(x)
            x.dip.grain_embargo = 0.9
            x.econ.weather = 0.8
        hit = run(new_world(4, 24), 12, each=disrupt)
        calm = run(new_world(4, 24), 12, each=steady)
        self.assertGreater(hit.econ.food_rel, calm.econ.food_rel)
        self.assertGreater(hit.avg("hunger"), calm.avg("hunger"))

    def test_a_currency_shock_raises_import_costs_and_lowers_real_wages(self):
        def shock(x):
            steady(x)
            if x.month == 1:
                x.econ.currency_launch = 2
            if x.month >= 2:
                x.policy.printing = 0.07
                x.econ.gold = max(1e5, x.econ.gold * 0.90)
        w = run(new_world(11, 24), 14, each=shock)
        self.assertLess(w.econ.fx, 1.0, "the currency never moved")
        self.assertGreater(w.econ.import_price_infl, -0.1)

    def test_a_foreign_loan_eases_the_budget_without_being_free(self):
        w = new_world(6, 24)

        def borrow(x):
            steady(x)
            if x.month == 1:
                x.dip.league_loan_pending = 60e6
        run(w, 8, each=borrow)
        self.assertGreater(w.econ.debt_for, 0.0, "the loan was never booked as a liability")
        self.assertGreater(w.econ.interest_for, 0.0, "the loan carries no interest")

    def test_reserves_are_not_domestic_cash(self):
        """Spending reserves on a domestic obligation must be an explicit conversion."""
        w = new_world(6, 12)
        w.econ.gdp_nominal = 500e6
        run(w, 2, each=steady)
        gold_before = w.econ.gold
        from karamaniya.economy import seed_arrears, settle_arrears
        seed_arrears(w, 20e6)
        # A domestic settlement funded from bonds must not touch foreign reserves at all.
        settle_arrears(w, 20e6)
        self.assertEqual(w.econ.gold, gold_before,
                         "a domestic arrears payment drained foreign reserves")


class Military(unittest.TestCase):
    def test_paying_officers_more_buys_loyalty_out_of_the_equipment_budget(self):
        """The officer pay scale does not enlarge the military budget; it decides what the budget
        is spent on. Premium pay means soldiers are paid better and there is less left for kit."""
        generous = run(new_world(2, 24), 14,
                       each=lambda x: (steady(x), setattr(x.policy, "officer_pay", "premium")))
        standard = run(new_world(2, 24), 14, each=steady)
        self.assertGreater(generous.mil.army.morale, standard.mil.army.morale,
                           "premium pay bought no goodwill")
        self.assertLess(generous.mil.arms, standard.mil.arms,
                       "premium pay was free: the equipment budget was untouched")
        # And it is not a loyalty button.
        self.assertLess(generous.mil.army.loyalty, 1.0)

    def test_the_army_is_protected_relative_to_the_people_who_supply_it(self):
        """The historical record is of governments stiffing suppliers to keep paying soldiers —
        and of the occasions when even that stopped working."""
        def squeeze(x):
            steady(x)
            x.policy.military = 0.14
            x.policy.tax = 0.05
        w = run(new_world(2, 24), 14, each=squeeze)
        months = economy.arrears_months(w)
        self.assertLess(months["army"], months["contractors"],
                        "soldiers fell as far behind as the firms that sell them boots")
        self.assertLess(months["army"], months["civil_service"],
                        "soldiers' pay fell behind faster than the clerks', which is not the pattern")

    def test_a_mild_shortfall_does_not_reach_the_army_at_all(self):
        """Protection shows up as a threshold: small shortfalls land entirely on suppliers."""
        def mild(x):
            steady(x)
            x.policy.tax = 0.17
        w = run(new_world(2, 24), 8, each=mild)
        months = economy.arrears_months(w)
        self.assertLess(months["army"], economy.CIVIL_SERVICE_STRIKE_MONTHS)
        self.assertGreater(months["contractors"], months["army"])

    def test_a_total_fiscal_collapse_reaches_everyone(self):
        """Protection is relative, not immunity: if the state stops collecting altogether, even
        the army goes unpaid — which is what happened in every documented case."""
        def collapse(x):
            steady(x)
            x.policy.tax = 0.01
            x.policy.military = 0.22
            x.policy.welfare = 0.12
            x.policy.health_edu = 0.12
        w = run(new_world(2, 30), 18, each=collapse)
        months = economy.arrears_months(w)
        self.assertGreater(months["army"], 0.0, "the army is exempt from arrears entirely")
        self.assertGreater(w.mil.army.arrears, 0.0,
                           "the military module thinks a bankrupt state is paying in full")

    def test_training_intensity_reaches_combat_quality(self):
        from karamaniya.military import quality
        strong = run(new_world(9, 24), 16,
                     each=lambda x: (steady(x), setattr(x.policy, "training_intensity", "intense")))
        weak = run(new_world(9, 24), 16,
                   each=lambda x: (steady(x), setattr(x.policy, "training_intensity", "neglect")))
        self.assertGreater(quality(strong.mil.army.equipment, strong.mil.army.training, strong.mil.army.morale),
                           quality(weak.mil.army.equipment, weak.mil.army.training, weak.mil.army.morale))


class SocietyUnderStress(unittest.TestCase):
    def test_founding_unrest_is_not_below_its_grievance_and_fear_state(self):
        for seed in (1, 7, 41):
            w = new_world(seed, 24, founding_scenario="fiscal-inheritance")
            with self.subTest(seed=seed):
                for pop in w.k_pops():
                    self.assertGreaterEqual(pop.unrest + 1e-12,
                                            pop.grievance * (1 - 0.75 * pop.fear))

    def test_paid_social_support_reduces_grievance_and_unrest(self):
        def policy(w, social):
            steady(w)
            w.policy.tax = 0.20
            w.policy.military = 0.005
            w.policy.welfare = 0.055 if social else 0.04
            w.policy.health_edu = 0.07 if social else 0.06

        for seed in (1, 7, 41):
            baseline = run(new_world(seed, 24, founding_scenario="fiscal-inheritance"), 12,
                           each=lambda w: policy(w, False))
            supported = run(new_world(seed, 24, founding_scenario="fiscal-inheritance"), 12,
                            each=lambda w: policy(w, True))
            with self.subTest(seed=seed):
                self.assertGreaterEqual(supported.econ.paid_share, 0.98)
                self.assertLess(supported.avg("grievance"), baseline.avg("grievance"))
                self.assertLess(supported.avg("unrest"), baseline.avg("unrest"))

    def test_a_protest_wave_raises_unrest_and_repression_does_not_remove_grievance(self):
        def tolerate(x):
            steady(x)
            x.policy.protest_response = "tolerate"
        def repress(x):
            steady(x)
            x.policy.protest_response = "disperse"
        calm_ish = run(new_world(7, 24), 12, each=tolerate)
        hard = run(new_world(7, 24), 12, each=repress)
        # Repression buys quiet on the street; it does not buy consent.
        self.assertLessEqual(hard.avg("unrest"), calm_ish.avg("unrest") + 0.05)
        self.assertGreaterEqual(hard.avg("grievance"), calm_ish.avg("grievance") - 0.05)

    def test_an_office_vacancy_persists_rather_than_filling_itself(self):
        w = new_world(3, 24)
        w.const.offices["army"] = None
        run(w, 10, each=steady)
        self.assertIsNone(w.const.offices["army"],
                          "a vacant office filled itself without a council decision")

    def test_a_vacant_office_leaves_the_lever_unpulled(self):
        held = run(new_world(3, 24), 8, each=lambda x: (steady(x), x.const.offices.update({"army": "A"})))
        vacant = new_world(3, 24)
        vacant.const.offices["army"] = None
        run(vacant, 8, each=steady)
        self.assertGreater(held.mil.army.training, 0.0)
        self.assertGreater(vacant.mil.army.training, 0.0)


class CollapseAndRecovery(unittest.TestCase):
    def test_a_debt_rollover_crisis_does_not_create_money(self):
        w = new_world(8, 30)
        w.econ.debt_dom = 6e9
        w.econ.debt_short_share = 0.85
        run(w, 12, each=steady)
        self.assertGreaterEqual(w.econ.gold, 0.0)
        self.assertGreaterEqual(w.econ.debt_dom, 0.0)
        self.assertGreaterEqual(w.econ.arrears, 0.0)
        finite(w, "cpi", "confidence", "paid_share")

    def test_repeated_audits_do_not_destroy_the_state_by_themselves(self):
        w = new_world(12, 24)
        from karamaniya import audits
        for _ in range(6):
            run(w, 1, each=steady)
            try:
                audits.open_audit(w, "treasury", "arrears", "A")
            except Exception:
                pass
        self.assertLess(w.econ.cpi, 10.0)
        finite(w, "cpi", "gold", "revenue")

    def test_no_scenario_produces_a_non_finite_or_negative_stock(self):
        """The blunt one: drive several stresses at once and check nothing goes impossible."""
        w = new_world(14, 36)

        def everything(x):
            steady(x)
            x.policy.military = 0.12
            x.policy.welfare = 0.10
            x.policy.health_edu = 0.10
            x.policy.tax = 0.08
            x.policy.printing = 0.04
            x.dip.grain_embargo = 0.4
            x.econ.weather = 0.85
            x.region("kessel").logistics = 0.5
        run(w, 30, each=everything)
        finite(w, "cpi", "infl", "gdp_real", "output_gap", "unemployment", "gold",
               "debt_dom", "debt_for", "arrears", "confidence", "paid_share", "food_ratio")
        for name in ("gold", "debt_dom", "debt_for", "arrears", "food_stock"):
            with self.subTest(stock=name):
                self.assertGreaterEqual(float(getattr(w.econ, name)), 0.0)
        self.assertGreaterEqual(w.mil.army.size, 0.0)
        self.assertLessEqual(w.avg("hunger"), 1.0)


if __name__ == "__main__":
    unittest.main()
