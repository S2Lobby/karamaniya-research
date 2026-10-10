"""World engine 17: an audience that won independence, and audiences that see the votes that matter.

In run 20261010-070501-seed1 the council twice called a referendum on independence (passed 4-1, then 3-2),
granted Kessel Valley cultural status under a Union ultimatum about Imperial citizens, and invited the Union into
a joint inquiry. In the engine none of it moved a delegate's audiences: a referendum motion and a protest carried
no tag, and no audience stood for the people who fought for independence.
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import agents, foreign, standing  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402
from tests.test_orders_vs_directives import resolve, world as orders_world  # noqa: E402

MOVEMENT = "independence movement"


def world(seed: int = 5):
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    agents.ensure(w)                       # the office audiences follow the offices, as they are set now
    for m in w.members:
        for aud in m.agent_state["constituencies"].values():
            aud["support_for_delegate"] = .5
    return w


def support(w, mid, audience):
    return w.member(mid).agent_state["constituencies"][audience]["support_for_delegate"]


def referendum(**extra):
    mo = {"id": "M1", "proposer": "A", "type": "referendum", "subject": "independence", "value": "",
          "summary": "hold a referendum on independence this month"}
    mo.update(extra)
    return mo


def constitution(subject, value, **extra):
    mo = {"id": "M1", "proposer": "A", "type": "constitution", "subject": subject, "value": value,
          "summary": f"constitution: {subject} = {value}"}
    mo.update(extra)
    return mo


def satisfaction_after(setup, indep: float = .6, army: float = 33000):
    """The independence movement's satisfaction in a fresh world, after `setup` has changed it."""
    w = world()
    for p in w.k_pops():
        p.indep = indep
    w.mil.army.size = army
    setup(w)
    return agents._audience_conditions(w, MOVEMENT)[0]


class TheAudience(unittest.TestCase):
    def test_every_delegate_answers_to_it_at_priority_point_seven_five(self):
        w = new_world(5, 36)
        for m in w.members:
            aud = m.agent_state["constituencies"][MOVEMENT]
            self.assertEqual(aud["political_importance"], .75, m.id)
            self.assertEqual(aud["priorities"], ["independence", "national defence", "no concessions on status"])

    def test_a_run_saved_before_gains_it_and_keeps_the_rest(self):
        w = new_world(5, 36)
        m = w.member("A")
        kept = {name: dict(aud) for name, aud in m.agent_state["constituencies"].items() if name != MOVEMENT}
        del m.agent_state["constituencies"][MOVEMENT]
        agents.ensure(w)
        self.assertIn(MOVEMENT, m.agent_state["constituencies"])
        for name, aud in kept.items():
            self.assertEqual(m.agent_state["constituencies"][name]["attention"], aud["attention"], name)


class BeforeTheVote(unittest.TestCase):
    def test_a_yes_to_a_referendum_sours_the_movement_and_the_officers(self):
        w = world()
        ex = standing.vote_exposure(w, "D", referendum())          # D holds the army
        self.assertLess(ex["yes"][MOVEMENT], -.04)
        self.assertLess(ex["yes"]["senior officers"], 0)
        self.assertGreater(ex["no"][MOVEMENT], 0)
        text = standing.exposure_text(w, "D", [referendum()])
        self.assertIn("a yes would sour independence movement (sharply), senior officers (noticeably)", text)
        self.assertIn("a no would earn a little credit with independence movement", text)


class AfterTheVote(unittest.TestCase):
    def test_a_passed_referendum_costs_the_yes_voters_and_eases_the_no_voters(self):
        w = world()
        before = dict(standing.ensure(w, "A")["reputation"])
        mo = referendum(passed=True, void=False, withdrawn=False,
                        votes={"A": "yes", "B": "yes", "C": "no", "D": "abstain", "E": "yes"})
        standing.apply_vote_costs(w, {"month": w.month, "motions": [mo], "decisions": {}, "defiance": [], "resigned": []})
        yes = support(w, "A", MOVEMENT) - .5
        self.assertAlmostEqual(yes, -.048, places=3)                      # 1.6 x .02 x the vote scale of 1.5
        self.assertAlmostEqual(support(w, "C", MOVEMENT) - .5, -yes / 2, places=3)   # a no is half the yes
        self.assertEqual(support(w, "D", MOVEMENT), .5)                    # abstained
        after = standing.ensure(w, "A")["reputation"]
        self.assertEqual(after["reckless"] - before["reckless"], 2)
        self.assertEqual(after["strong"] - before["strong"], -1)


class OtherVotes(unittest.TestCase):
    def test_a_protest_and_an_alliance_with_the_league_are_tagged(self):
        w = world()
        self.assertEqual(standing.motion_tags(w, {"type": "diplomacy", "subject": "diplomatic_protest", "value": ""}),
                         ["protest"])
        self.assertEqual(standing.motion_tags(w, {"type": "diplomacy", "subject": "alliance", "value": ""}),
                         ["alliance_league"])

    def test_a_referendum_motion_is_an_independence_vote(self):
        self.assertEqual(standing.motion_tags(world(), referendum()), ["independence_vote"])

    def test_raising_a_region_is_autonomy_for_it(self):
        w = world()
        self.assertEqual(standing.motion_tags(w, constitution("kessel_status", "cultural")), ["autonomy_kessel"])
        self.assertEqual(standing.motion_tags(w, constitution("highlands_status", "cultural")), ["autonomy_highlands"])
        self.assertEqual(standing.motion_tags(w, constitution("kessel_status", "central")), [])

    def test_lowering_a_region_is_centralisation(self):
        w = world()
        w.const.kessel_status = "cultural"
        self.assertEqual(standing.motion_tags(w, constitution("kessel_status", "central")), ["centralisation"])
        w.const.highlands_status = "devolved"
        self.assertEqual(standing.motion_tags(w, constitution("highlands_status", "cultural")), ["centralisation"])

    def test_once_taken_the_record_says_what_the_status_replaced(self):
        w = world()
        w.const.kessel_status = "devolved"                                 # executed: it replaced cultural
        self.assertEqual(standing.motion_tags(w, constitution("kessel_status", "devolved", previous_value="cultural")),
                         ["autonomy_kessel"])

    def test_other_constitution_motions_keep_their_tags(self):
        w = world()
        self.assertEqual(standing.motion_tags(w, constitution("emergency", "on")), ["emergency"])
        self.assertEqual(standing.motion_tags(w, constitution("press", "free")), [])

    def test_the_concessions_cost_the_movement_as_specified(self):
        table = standing.ACTION_EFFECTS
        self.assertEqual(table["concede_union"][1][MOVEMENT], -2.0)
        self.assertEqual(table["status_talks"][1][MOVEMENT], -1.0)
        self.assertEqual(table["anti_union"][1][MOVEMENT], .8)
        self.assertEqual(table["military_up"][1][MOVEMENT], .5)
        self.assertEqual(table["military_down"][1][MOVEMENT], -.5)
        self.assertEqual(table["conscription"][1][MOVEMENT], .3)
        self.assertEqual(table["peace_overture"][1][MOVEMENT], -.2)


class ThroughTheCouncil(unittest.TestCase):
    """A status vote as the council resolves it. The record keeps the status it replaced, which the audiences read."""
    FOUR_TO_ONE = {"A": "yes", "B": "yes", "C": "yes", "D": "no", "E": "yes"}

    def test_a_passed_raise_records_the_status_it_replaced_and_reaches_the_movement(self):
        w = orders_world()
        record = resolve(w, constitution("kessel_status", "cultural"), self.FOUR_TO_ONE, {})
        mo = record["motions"][0]
        self.assertTrue(mo["passed"])
        self.assertEqual(mo["previous_value"], "central")
        self.assertEqual(standing.motion_tags(w, mo), ["autonomy_kessel"])
        standing.apply_vote_costs(w, record)
        self.assertAlmostEqual(support(w, "A", MOVEMENT), .5 - .018, places=3)   # -.6 x .02 x 1.5

    def test_a_passed_lowering_is_centralisation(self):
        w = orders_world()
        w.const.kessel_status = "devolved"
        record = resolve(w, constitution("kessel_status", "cultural"), self.FOUR_TO_ONE, {})
        mo = record["motions"][0]
        self.assertEqual(mo["previous_value"], "devolved")
        self.assertEqual(standing.motion_tags(w, mo), ["centralisation"])


class TheMovementsSatisfaction(unittest.TestCase):
    def test_support_for_independence_and_a_larger_army_raise_it(self):
        strong = satisfaction_after(lambda w: None, indep=.8, army=45000)
        weak = satisfaction_after(lambda w: None, indep=.5, army=25000)
        self.assertGreater(strong, weak)

    def test_the_force_ratio_counts_only_past_its_thresholds(self):
        # The Union's army is 95,000: a ratio of 2 at 47,500 soldiers and of 3 at about 31,700.
        between = satisfaction_after(lambda w: None, army=45000)           # ratio 2.1
        self.assertAlmostEqual(satisfaction_after(lambda w: None, army=33000), between)   # ratio 2.9: no effect
        self.assertLess(satisfaction_after(lambda w: None, army=25000), between)          # ratio 3.8: worse
        self.assertGreater(satisfaction_after(lambda w: None, army=50000), between)       # ratio 1.9: better

    def test_a_step_on_status_in_the_last_three_months_costs_it(self):
        calm = satisfaction_after(lambda w: None)
        for kind in ("federation", "join_union", "status_talks"):
            with self.subTest(kind=kind):
                def pending(w, kind=kind):
                    w.month = 4
                    w.dip.proposals.append({"month": 1, "kind": kind, "party": "union"})
                def old(w, kind=kind):
                    w.month = 5
                    w.foreign["proposal_log"] = [{"month": 1, "kind": kind, "party": "union"}]
                self.assertAlmostEqual(calm - satisfaction_after(pending), .15, places=6)
                self.assertAlmostEqual(satisfaction_after(old), calm, places=6)   # four months on, it is over

    def test_a_referendum_called_counts_for_three_months_and_the_default_does_not(self):
        calm = satisfaction_after(lambda w: None)                          # no referendum has ever been called

        def called(w):
            w.const.referendum_month = 1
            w.month = 3
        self.assertAlmostEqual(calm - satisfaction_after(called), .15, places=6)

    def test_the_monthly_update_carries_it_into_the_audience(self):
        def monthly(indep, army):
            w = world()
            for p in w.k_pops():
                p.indep = indep
            w.mil.army.size = army
            agents._update_stress(w)
            return w.member("A").agent_state["constituencies"][MOVEMENT]["satisfaction"]
        self.assertGreater(monthly(.8, 45000), monthly(.5, 25000))
        target = satisfaction_after(lambda w: None, indep=.8, army=45000)
        self.assertEqual(monthly(.8, 45000), round(.65 * .5 + .35 * target, 2))


class AScriptedRun(unittest.TestCase):
    """Three months through the council: the audience is kept by every delegate and the monthly update reaches it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-engine17-audiences-")
        path = new_run(os.path.join(ROOT, "council.scripted.toml"), runs_dir=cls.tmp, name="e17a", months=3, quiet=True)
        cls.world = RunStore(path).load_checkpoint()[0]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_delegate_keeps_the_audience_and_its_history(self):
        for m in self.world.members:
            self.assertEqual(m.agent_state["constituencies"][MOVEMENT]["political_importance"], .75, m.id)
            self.assertGreaterEqual(len(m.agent_state["constituency_history"][MOVEMENT]), 1, m.id)


if __name__ == "__main__":
    unittest.main()
