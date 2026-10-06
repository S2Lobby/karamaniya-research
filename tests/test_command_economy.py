"""The command-economy and one-party axes: additive and default-preserving (private / multi_party
reproduce prior behaviour), but when a council reaches for them the engine responds with real,
documented consequences -- output depends on administrative capacity, nationalisation triggers
capital flight, and abolishing parties costs liberty and legitimacy."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import director, economy, motion_actions, politics, society  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


class Ownership(unittest.TestCase):
    def _gdp(self, own, admin):
        w = new_world(3, 6)
        w.policy.ownership = own
        w.econ.admin_capacity = admin
        return economy.produce(w)["gdp_real"]

    def test_state_lowers_output_when_administration_is_weak(self):
        self.assertLess(self._gdp("state", 0.30), self._gdp("private", 0.30))

    def test_a_capable_bureaucracy_runs_the_economy_better(self):
        self.assertGreater(self._gdp("state", 0.95), self._gdp("state", 0.30))

    def test_ownership_never_raises_output_and_state_loses_most(self):
        # private is the baseline (own factors 1.0); moving toward state never increases output and
        # costs the most. This is the invariant that keeps the default behaviour intact.
        admin = 0.6
        p, m, s = self._gdp("private", admin), self._gdp("mixed", admin), self._gdp("state", admin)
        self.assertGreaterEqual(p, m)
        self.assertGreaterEqual(m, s)

    def test_nationalising_triggers_capital_flight(self):
        w = new_world(3, 6)
        w.econ.gold = 100e6
        politics.set_lever(w, "ownership", "state")
        self.assertEqual(w.policy.ownership, "state")
        self.assertLess(w.econ.gold, 100e6)

    def test_ownership_is_a_directable_treasury_lever(self):
        self.assertEqual(politics.LEVER_OFFICE.get("ownership"), "treasury")
        self.assertEqual(politics.parse_lever("ownership", "state"), "state")
        w = new_world(4, 12)
        mo = {"type": "set_policy", "subject": "ownership", "value": "state", "text": "nationalise"}
        self.assertIsNone(politics.validate_motion_detail(w, {**mo, "passed": True}))


class Parties(unittest.TestCase):
    def test_one_party_costs_liberty_and_legitimacy(self):
        w = new_world(3, 6)
        base_lib, base_leg = society.liberty_deficit(w), society.legitimacy(w)
        w.const.parties = "one_party"
        self.assertGreater(society.liberty_deficit(w), base_lib)
        self.assertLess(society.legitimacy(w), base_leg)

    def test_multi_party_default_changes_nothing(self):
        w = new_world(3, 6)
        self.assertEqual(w.const.parties, "multi_party")
        self.assertEqual(society.liberty_deficit(w), society.liberty_deficit(new_world(3, 6)))

    def test_constitution_motion_sets_parties(self):
        w = new_world(4, 12)
        mo = {"type": "constitution", "subject": "parties", "value": "one_party", "text": "one party"}
        self.assertIsNone(politics.validate_motion_detail(w, mo))
        politics.apply_motion(w, mo)
        self.assertEqual(w.const.parties, "one_party")


class ImportCap(unittest.TestCase):
    def _goods_imports(self, cap):
        w = new_world(3, 6)
        w.policy.import_cap = cap
        economy.trade_and_food(w, economy.produce(w))
        return w.econ.goods_imports

    def test_cap_limits_goods_imports_and_zero_is_no_limit(self):
        capped = self._goods_imports(5e6)
        self.assertLessEqual(capped, 5e6 + 1)
        self.assertGreater(self._goods_imports(0.0), capped)

    def test_is_a_numeric_treasury_lever(self):
        self.assertEqual(politics.LEVER_OFFICE.get("import_cap"), "treasury")
        self.assertEqual(politics.parse_lever("import_cap", "12,000,000"), 12e6)


class Planning(unittest.TestCase):
    def _mix(self, plan, admin):
        w = new_world(3, 6)
        w.policy.planning = plan
        w.econ.admin_capacity = admin
        p = economy.produce(w)
        return p["industry"], p["services"]

    def test_command_shifts_toward_industry_away_from_services(self):
        i0, s0 = self._mix("none", 0.9)
        i1, s1 = self._mix("command", 0.9)
        self.assertGreater(i1, i0)
        self.assertLess(s1, s0)

    def test_command_needs_a_capable_bureaucracy(self):
        self.assertGreater(self._mix("command", 0.95)[0], self._mix("command", 0.30)[0])


class Amnesty(unittest.TestCase):
    def test_release_lowers_grievance_and_costs_security_loyalty(self):
        w = new_world(3, 6)
        for p in w.k_pops():
            p.grievance = 0.5
        before = w.mil.police.loyalty
        politics.set_lever(w, "amnesty", "release")
        self.assertTrue(all(p.grievance < 0.5 for p in w.k_pops()))
        self.assertLess(w.mil.police.loyalty, before)
        self.assertEqual(w.policy.amnesty, "release")

    def test_default_none_does_nothing(self):
        w = new_world(3, 6)
        self.assertEqual(w.policy.amnesty, "none")


class Renounce(unittest.TestCase):
    def test_reverses_a_non_aggression_pact_and_an_alliance(self):
        w = new_world(3, 6)
        w.dip.nonaggression = True
        director._renounce(w, "union")
        self.assertFalse(w.dip.nonaggression)
        w.dip.league_alliance = True
        t0 = w.dip.league_trust
        director._renounce(w, "league")
        self.assertFalse(w.dip.league_alliance)
        self.assertLess(w.dip.league_trust, t0)

    def test_renounce_is_addressable_to_any_power(self):
        w = new_world(3, 6)
        mo = {"type": "diplomacy", "subject": "renounce", "value": "", "text": "withdraw",
              "action": {"action_type": "renounce", "target": "Maritime League"}, "passed": True}
        self.assertIsNone(motion_actions.validate_execution(w, mo))


class StatisticsTrust(unittest.TestCase):
    def test_statistics_scandal_clamps_and_synchronizes_league_trust(self):
        w = new_world(3, 6)
        w.set_league_trust(.1)
        w.policy.stats = "massaged"

        with patch("karamaniya.world.rng_for") as rng:
            rng.return_value.random.return_value = 0.0
            economy.statistics(w)

        self.assertEqual(w.dip.league_trust, 0.0)
        self.assertEqual(w.foreign["league"]["trust_in_karamaniya"], 0.0)
        self.assertEqual(w.counters["stats_scandals"], 1.0)


if __name__ == "__main__":
    unittest.main()
