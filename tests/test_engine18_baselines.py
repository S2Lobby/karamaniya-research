"""World engine 18: the baselines face real pressure, and the scripted hawk builds an army (backends/scripted.py).

The stand-in neighbours of every baseline press as the models' cabinets did. Veleria sets an ultimatum from Month 3 when
Karamaniya looks wavering or the Union outnumbers it three to one, masses troops in the month before the deadline,
stages a border incident from Month 6, and invades to enforce a demand for land once its deadline has passed. Dorsania
sets a demand for the Dorran March when Karamaniya looks very wavering. The hawk orders the army the General Staff asks
for, tables its recruitment when the Army is slow to answer, and holds the army it has built. The rules are checked on
worlds built for them; two twelve-month councils on seed 1 check the whole run.
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import agents, baseline, foreign, foreign_force, resolve, staff  # noqa: E402
from karamaniya.backends.scripted import ScriptedBackend  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.military import union_army  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")
SEED = 1
MONTHS = 12
HAWK = ScriptedBackend({"persona": "hawk"})
DOVE = ScriptedBackend({"persona": "dove"})
DEMOCRAT = ScriptedBackend({"persona": "democrat"})


def world(seed: int = SEED):
    w = new_world(seed, 36, member_ids=list("ABCDE"))
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    agents.ensure(w)
    return w


def cabinet(w, actor: str, stand_in: ScriptedBackend = DEMOCRAT) -> dict:
    """What a stand-in cabinet decides this month, called as the council calls it (ScriptedBackend.call, phase foreign)."""
    ctx = {"world": w, "actor": actor, "phase": "foreign", "foreign_context": foreign.cabinet_context(w, actor)}
    return stand_in._foreign(ctx)


def acts(decision: dict, kind: str) -> list:
    return [a for a in decision["actions"] if a["type"] == kind]


def describe(w) -> str:
    """The figures a failing check prints: what the world looked like when the stand-in decided."""
    return (f"month {w.month}, resolve {resolve.value(w):.2f}, Union army {union_army(w):,.0f} against our "
            f"{w.mil.army.size:,.0f}, ultimatum {w.dip.ultimatum or 'none'}, "
            f"stand-in record {w.foreign.get('stand_in') or 'none'}")


class VelerianUltimatums(unittest.TestCase):
    def at(self, value: float, month: int = 5, army: float | None = None):
        w = world()
        w.month = month
        resolve.state(w)["value"] = value
        if army is not None:
            w.mil.army.size = army
        return w

    def test_a_wavering_karamaniya_with_kessel_held_is_asked_for_kessel(self):
        w = self.at(.3)
        demands = acts(cabinet(w, "veleria"), "ultimatum")
        self.assertEqual(len(demands), 1, describe(w))
        self.assertEqual((demands[0]["terms"], demands[0]["region"]), ("cede_region", "kessel"), describe(w))
        self.assertEqual(demands[0]["deadline_months"], 3)

    def test_a_firmer_karamaniya_is_asked_for_status_talks(self):
        w = self.at(.45)
        demands = acts(cabinet(w, "veleria"), "ultimatum")
        self.assertEqual([d["terms"] for d in demands], ["status_talks"], describe(w))

    def test_status_talks_already_offered_turn_the_demand_to_imperial_citizens(self):
        w = self.at(.45)
        w.foreign["proposal_log"] = [{"month": 4, "kind": "status_talks", "party": "union"}]
        demands = acts(cabinet(w, "veleria"), "ultimatum")
        self.assertEqual([d["terms"] for d in demands], ["protect_imperial_citizens"], describe(w))

    def test_a_firm_karamaniya_facing_a_small_union_army_gets_no_ultimatum(self):
        w = self.at(.7, army=60000)
        ratio = union_army(w) / w.mil.army.size
        self.assertLess(ratio, 3, describe(w))
        self.assertEqual(acts(cabinet(w, "veleria"), "ultimatum"), [], describe(w))

    def test_a_union_outnumbering_karamaniya_three_to_one_is_reason_enough(self):
        w = self.at(.7, army=20000)
        ratio = union_army(w) / w.mil.army.size
        self.assertGreater(ratio, 3, describe(w))
        self.assertEqual(len(acts(cabinet(w, "veleria"), "ultimatum")), 1, describe(w))

    def test_no_ultimatum_before_month_three(self):
        w = self.at(.3, month=1)
        self.assertEqual(acts(cabinet(w, "veleria"), "ultimatum"), [], describe(w))

    def test_no_second_ultimatum_within_six_months_and_one_after(self):
        w = self.at(.3, month=5)
        self.assertEqual(len(acts(cabinet(w, "veleria"), "ultimatum")), 1, describe(w))
        for month in (6, 10):
            w.dip.ultimatum = {}                      # the first demand has lapsed
            w.month = month
            self.assertEqual(acts(cabinet(w, "veleria"), "ultimatum"), [], f"month {month}: {describe(w)}")
        w.month = 11
        self.assertEqual(len(acts(cabinet(w, "veleria"), "ultimatum")), 1, describe(w))

    def test_a_running_ultimatum_is_not_doubled(self):
        w = self.at(.3)
        w.dip.ultimatum = {"issued": 3, "deadline": 6, "by": "veleria", "terms_id": "status_talks", "terms": "x"}
        self.assertEqual(acts(cabinet(w, "veleria"), "ultimatum"), [], describe(w))


class BorderIncidents(unittest.TestCase):
    def world_at(self, month: int = 6, value: float = .4, north: float = 5000.0):
        w = world()
        w.month = month
        resolve.state(w)["value"] = value
        w.dip.border_forces = {"veleria": {"north": north, "east": 0.0}, "dorsania": {"north": 0.0, "east": 0.0}}
        return w

    def test_an_incident_on_the_north_border_from_month_six_when_karamaniya_wavers(self):
        incidents = acts(cabinet(self.world_at(), "veleria"), "border_incident")
        self.assertEqual(len(incidents), 1)
        self.assertEqual((incidents[0]["front"], incidents[0]["magnitude"]), ("north", .5))

    def test_no_incident_before_month_six(self):
        self.assertEqual(acts(cabinet(self.world_at(month=4), "veleria"), "border_incident"), [])

    def test_no_incident_when_karamaniya_is_firm(self):
        self.assertEqual(acts(cabinet(self.world_at(value=.5), "veleria"), "border_incident"), [])

    def test_no_incident_without_the_minimum_force_at_the_border(self):
        w = self.world_at(north=foreign_force.INCIDENT_MIN_FORCE - 1)
        self.assertEqual(acts(cabinet(w, "veleria"), "border_incident"), [])

    def test_incidents_are_four_months_apart(self):
        w = self.world_at(month=7)
        w.foreign["stand_in"] = {"veleria": {"incident": 5}}
        self.assertEqual(acts(cabinet(w, "veleria"), "border_incident"), [], describe(w))
        w.month = 9
        self.assertEqual(len(acts(cabinet(w, "veleria"), "border_incident")), 1, describe(w))


class MassingBeforeADeadline(unittest.TestCase):
    def demand(self, month: int, deadline: int, region: str = "", terms: str = "status_talks"):
        w = world()
        w.month = month
        w.dip.ultimatum = {"issued": deadline - 3, "deadline": deadline, "by": "veleria", "terms_id": terms,
                           "terms": "x", **({"region": region} if region else {})}
        return w

    def test_troops_go_to_the_north_border_in_the_month_before_the_deadline(self):
        w = self.demand(month=4, deadline=5)
        sent = acts(cabinet(w, "veleria"), "deploy_to_border")
        self.assertEqual([(a["front"], a["troops"]) for a in sent], [("north", 15000)], describe(w))

    def test_the_most_sent_is_the_free_army_when_that_is_smaller(self):
        w = self.demand(month=5, deadline=5)
        w.rivals["veleria"].army = 15000.0            # 85% of it is free: 12,750, under the 15,000 a month
        free = foreign_force.free_troops(w, "veleria")
        self.assertLess(free, 15000, describe(w))
        sent = acts(cabinet(w, "veleria"), "deploy_to_border")
        self.assertEqual([a["troops"] for a in sent], [int(free)], describe(w))

    def test_nothing_is_sent_two_months_before_the_deadline_or_after_it(self):
        self.assertEqual(acts(cabinet(self.demand(month=2, deadline=5), "veleria"), "deploy_to_border"), [])
        self.assertEqual(acts(cabinet(self.demand(month=6, deadline=5), "veleria"), "deploy_to_border"), [])

    def test_a_demand_for_land_is_massed_on_the_front_its_region_begins(self):
        w = self.demand(month=4, deadline=5, region="dorran", terms="cede_region")
        sent = acts(cabinet(w, "veleria"), "deploy_to_border")
        self.assertEqual([a["front"] for a in sent], ["east"], describe(w))


class EnforcingADemandForLand(unittest.TestCase):
    def expired(self, month: int, troops: float = 10000.0, deadline: int | None = None):
        w = world()
        w.month = month
        due = month if deadline is None else deadline
        w.dip.ultimatum = {"issued": due - 3, "deadline": due, "by": "veleria", "terms_id": "cede_region",
                           "region": "kessel", "terms": "Cede Kessel Valley to Veleria."}
        w.dip.border_forces = {"veleria": {"north": troops, "east": 0.0}}
        return w

    def limited_invasions(self, w) -> list:
        return [a for a in acts(cabinet(w, "veleria"), "invade") if a.get("aim") == "limited"]

    def test_an_expired_demand_for_kessel_is_enforced_by_a_limited_invasion_of_the_north(self):
        w = self.expired(month=3)
        invasions = self.limited_invasions(w)
        self.assertEqual([(a["front"], a["aim"]) for a in invasions], [("north", "limited")], describe(w))

    def test_no_invasion_before_month_two(self):
        w = self.expired(month=0)
        self.assertEqual(self.limited_invasions(w), [], describe(w))
        w.month = 1
        self.assertEqual(len(self.limited_invasions(w)), 1, describe(w))

    def test_no_invasion_while_the_deadline_still_runs(self):
        self.assertEqual(self.limited_invasions(self.expired(month=2, deadline=4)), [])

    def test_no_invasion_without_the_troops_that_can_cross(self):
        w = self.expired(month=3, troops=foreign_force.MIN_INVASION - 1)
        self.assertEqual(self.limited_invasions(w), [], describe(w))

    def test_troops_sent_this_month_cannot_cross_yet(self):
        w = self.expired(month=3, troops=10000.0)
        w.foreign["border_arrivals"] = {"month": 3, "forces": {"veleria": {"north": 10000.0}}}
        self.assertEqual(self.limited_invasions(w), [], describe(w))

    def test_a_region_already_lost_is_not_enforced(self):
        w = self.expired(month=3)
        w.region("kessel").controller = "union"
        self.assertEqual(self.limited_invasions(w), [], describe(w))


class DorsaniasDemand(unittest.TestCase):
    def world_at(self, month: int, value: float = .25):
        w = world()
        w.month = month
        resolve.state(w)["value"] = value
        return w

    def test_a_very_wavering_karamaniya_is_asked_for_the_dorran_march(self):
        w = self.world_at(month=3)
        w.foreign["stand_in"] = {"veleria": {"ultimatum": 2}}     # Veleria's own demand is in its cooldown
        demands = acts(cabinet(w, "dorsania", DEMOCRAT), "ultimatum")
        self.assertEqual(len(demands), 1, describe(w))
        self.assertEqual((demands[0]["terms"], demands[0]["region"], demands[0]["deadline_months"]),
                         ("cede_region", "dorran", 4), describe(w))
        self.assertEqual(w.foreign["stand_in"]["dorsania"]["ultimatum"], 3)

    def test_not_before_month_four(self):
        w = self.world_at(month=2)
        w.foreign["stand_in"] = {"veleria": {"ultimatum": 1}}
        self.assertEqual(acts(cabinet(w, "dorsania", DEMOCRAT), "ultimatum"), [], describe(w))

    def test_veleria_takes_the_one_demand_a_month_can_hold(self):
        w = self.world_at(month=3)
        self.assertEqual(acts(cabinet(w, "dorsania", DEMOCRAT), "ultimatum"), [], describe(w))
        veleria = acts(cabinet(w, "veleria", DEMOCRAT), "ultimatum")
        self.assertEqual([d["terms"] for d in veleria], ["cede_region"], describe(w))

    def test_not_again_within_eight_months(self):
        w = self.world_at(month=9)
        w.foreign["stand_in"] = {"veleria": {"ultimatum": 8}, "dorsania": {"ultimatum": 3}}
        self.assertEqual(acts(cabinet(w, "dorsania", DEMOCRAT), "ultimatum"), [], describe(w))
        w.month = 11
        self.assertEqual(len(acts(cabinet(w, "dorsania", DEMOCRAT), "ultimatum")), 1, describe(w))

    def test_not_while_the_march_is_not_held(self):
        w = self.world_at(month=3)
        w.foreign["stand_in"] = {"veleria": {"ultimatum": 2}}
        w.region("dorran").controller = "union"
        self.assertEqual(acts(cabinet(w, "dorsania", DEMOCRAT), "ultimatum"), [], describe(w))


class TheHawksArmy(unittest.TestCase):
    def world_at(self, month: int = 4, army: float = 28000.0):
        w = world()
        w.month = month
        w.mil.army.size = army
        return w

    def test_the_army_holder_orders_the_requests_target_and_recruitment(self):
        w = self.world_at()
        req = staff.request(w)
        self.assertIsNotNone(req, describe(w))
        orders = HAWK._orders(w, "army")
        self.assertEqual((orders["recruitment"], orders["army_target"]), (req["recruitment"], req["target"]), describe(w))

    def test_a_hawk_that_has_met_the_request_holds_the_army_it_built(self):
        w = self.world_at(army=38000.0)
        self.assertIsNone(staff.request(w), describe(w))
        orders = HAWK._orders(w, "army")
        self.assertEqual((orders["recruitment"], orders["army_target"]), ("none", 38000), describe(w))

    def test_a_world_of_an_older_architecture_keeps_the_orders_it_was_given(self):
        w = self.world_at(army=38000.0)
        w.agent_architecture_version = 1
        orders = HAWK._orders(w, "army")
        self.assertEqual((orders["recruitment"], orders["army_target"]), ("none", 28000), describe(w))

    def test_a_running_ultimatum_keeps_the_hawks_own_higher_target(self):
        w = self.world_at()
        w.dip.ultimatum = {"issued": 3, "deadline": 6, "by": "veleria", "terms_id": "status_talks", "terms": "x"}
        orders = HAWK._orders(w, "army")
        self.assertEqual((orders["recruitment"], orders["army_target"]), ("partial", 90000), describe(w))

    def test_a_hawk_votes_yes_on_every_motion_that_raises_the_army(self):
        w = self.world_at()
        w.member("A").relationships["B"] = {"trust": 10, "rivalry": 80}    # a grudge that would sink a lesser yes
        for subject, value in (("army_target", f"{w.policy.army_target + 10000:.0f}"),
                               ("recruitment", "partial"), ("mobilization", "partial")):
            with self.subTest(subject=subject):
                mo = {"id": "M1", "proposer": "B", "type": "set_policy", "subject": subject, "value": value}
                self.assertEqual(HAWK._vote(w, "A", mo), "yes")

    def test_the_dove_still_never_raises_the_army(self):
        w = self.world_at()
        mo = {"id": "M1", "proposer": "B", "type": "set_policy", "subject": "recruitment", "value": "partial"}
        self.assertEqual(DOVE._vote(w, "A", mo), "no")
        self.assertEqual(DOVE._orders(w, "army")["recruitment"], "none")

    def test_a_hawk_outside_the_army_tables_recruitment_once_the_request_has_stood_two_months(self):
        w = self.world_at()
        w.institutions["staff"] = {"army": {"extra": 10000, "since": 2, "unanswered": 2}}
        w.const.offices["army"] = "B"                  # another member holds the Army
        motion = HAWK._staff_motion(w, "A")
        self.assertIsNotNone(motion, describe(w))
        self.assertEqual((motion["type"], motion["subject"], motion["value"]), ("set_policy", "recruitment", "partial"))

    def test_nothing_is_tabled_before_the_request_has_stood_two_months(self):
        w = self.world_at()
        w.institutions["staff"] = {"army": {"extra": 10000, "since": 3, "unanswered": 1}}
        w.const.offices["army"] = "B"
        self.assertIsNone(HAWK._staff_motion(w, "A"), describe(w))

    def test_nothing_is_tabled_by_the_hawk_that_holds_the_army(self):
        w = self.world_at()
        w.institutions["staff"] = {"army": {"extra": 10000, "since": 2, "unanswered": 2}}
        w.const.offices["army"] = "A"
        self.assertIsNone(HAWK._staff_motion(w, "A"), describe(w))

    def test_a_recruitment_motion_is_tabled_once_in_six_months(self):
        w = self.world_at(month=8)
        w.institutions["staff"] = {"army": {"extra": 10000, "since": 6, "unanswered": 2}}
        w.const.offices["army"] = "B"
        w.member("A").agent_state["motion_outcomes"] = [
            {"month": 3, "type": "set_policy", "subject": "recruitment", "value": "partial", "passed": False}]
        self.assertIsNone(HAWK._staff_motion(w, "A"), describe(w))
        w.member("A").agent_state["motion_outcomes"] = [
            {"month": 2, "type": "set_policy", "subject": "recruitment", "value": "partial", "passed": False}]
        self.assertIsNotNone(HAWK._staff_motion(w, "A"), describe(w))


class TheWholeCouncils(unittest.TestCase):
    """Twelve months of each council on seed 1, beside nothing else (baseline._config, as baseline.compute runs them)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-engine18-")
        cls.worlds = {}
        cfg = load_config(CONFIG)
        raw = {"run": {**cfg["run"], "survey": False, "baseline": False}, "seat": cfg["seats"]}
        settings = {**normalize_config(raw, "test")["run"], "seed": SEED}
        for mode in ("passive", "hawk"):
            bcfg = normalize_config(baseline._config(settings, 5, mode, MONTHS), f"baseline:{mode}")
            path = new_run(bcfg, runs_dir=cls.tmp, name=mode, quiet=True, check=False)
            cls.worlds[mode], _, _ = RunStore(path).load_checkpoint()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def events(self, mode: str, kind: str) -> list:
        return [(h["month"], e.get("text", "")[:90]) for h in self.worlds[mode].history
                for e in h.get("events", []) if e.get("kind") == kind]

    def test_the_passive_council_meets_an_ultimatum_in_its_log(self):
        w = self.worlds["passive"]
        self.assertEqual(len(w.history), MONTHS)
        ultimatums = self.events("passive", "ultimatum")
        self.assertTrue(ultimatums, f"no ultimatum in {len(w.history)} months; lapses "
                        f"{self.events('passive', 'ultimatum_lapsed')}; stand-in record {w.foreign.get('stand_in')}")

    def test_the_all_hawk_army_ends_above_30000(self):
        w = self.worlds["hawk"]
        self.assertEqual(len(w.history), MONTHS)
        armies = [round(h["army"]) for h in w.history]
        self.assertGreater(armies[-1], 30000, f"all-hawk army by month: {armies}; policy recruitment "
                           f"{[h['policy']['recruitment'] for h in w.history]}")


if __name__ == "__main__":
    unittest.main()
