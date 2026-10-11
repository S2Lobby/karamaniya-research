"""World engine 22, slice "scale": what a military or programme choice means, stated where the council reads it.

Run 20261011-105713-seed1, Month 8: the council passed partial mobilization and partial recruitment with no figure
for either. The call-up took 32,841 reservists at once, from a trained reserve of about 131,000, and the army went
from 45,000 to 54,654 in one month. Month 10: a programme set eight levers, and its motion showed only the values it
proposed. Every figure below comes from the engine's own functions, so the tests hold whatever the seed.
"""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import briefing, decision_context, foreign, military  # noqa: E402
from karamaniya.politics import fmt_value  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def world(seed: int = 5):
    """A version-2 world with the five offices held, as tests/test_engine19_military.world builds one."""
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.agent_architecture_version = 2
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def tabled(mid: str, **fields) -> dict:
    """A motion as the council tables it: a proposer, a summary, and whatever the test sets."""
    return {"id": mid, "proposer": "B", "cosponsors": [], "text": "", "summary": "motion", **fields}


class TheSettingsStateWhatMobilizationCalls(unittest.TestCase):
    """Bug 1: CURRENT SETTINGS gives the trained reserve, what each level would call up, and what a called-up
    reservist costs. Partial mobilization called up 32,841 reservists in Month 8 and nobody could know that figure."""

    def test_partial_and_general_call_ups_are_the_engine_figures(self):
        w = world()
        pool = military.reserve_pool(w)
        block = briefing.settings_block(w)
        for level in ("partial", "general"):
            with self.subTest(level=level):
                expected = round(pool * military.MOBILIZATION_SHARE[level], -2)
                self.assertIn(f"{level} would call up about {expected:,.0f} (", block)

    def test_the_trained_reserve_and_the_cost_of_one_reservist_are_stated(self):
        w = world()
        block = briefing.settings_block(w)
        self.assertIn(f"the trained reserve is about {round(military.reserve_pool(w), -3):,.0f}", block)
        head = military.reserve_cost(w, pooled=0.0, embodied=1.0)
        self.assertIn(f"costs about {head['embodied_monthly']:,.0f} a month in pay and "
                      f"{head['activation_one_off']:,.0f} to call up", block)

    def test_a_call_up_already_in_force_is_stated_as_embodied(self):
        w = world()
        w.policy.mobilization = "partial"
        military.call_up(w, military.reserve_pool(w) * military.MOBILIZATION_SHARE["partial"])
        embodied = military.mobilization_of(w).called_up
        block = briefing.settings_block(w)
        self.assertIn(f"about {round(embodied, -2):,.0f} embodied now", block)
        general = round(military.reserve_pool(w) * military.MOBILIZATION_SHARE["general"], -2)
        self.assertIn(f"general would call up about {general:,.0f} (", block)


class TheCallUpFigureIsTheOneTheEngineMakes(unittest.TestCase):
    """Bug 1: the figure a mobilization level states is the call-up _mobilize makes, and its pay and activation
    are the ones update() charges (reserve_cost, Audit MI1)."""

    def test_the_figure_equals_the_call_up_mobilize_makes(self):
        w = world()
        w.policy.mobilization = "partial"
        figures = military.mobilization_figures(w)
        called = military._mobilize(w)
        self.assertAlmostEqual(called, figures["new_call_up"], places=6)
        self.assertAlmostEqual(military.mobilization_of(w).called_up, figures["embodied"], places=6)

    def test_the_pay_and_activation_are_the_charges_update_makes(self):
        w = world()
        figures = military.mobilization_figures(w, "general")
        charged = military.reserve_cost(w, embodied=figures["new_call_up"])
        self.assertAlmostEqual(figures["activation"], charged["activation_one_off"], places=6)
        self.assertAlmostEqual(figures["monthly_pay"],
                               military.reserve_cost(w, pooled=0.0, embodied=figures["embodied"])["embodied_monthly"],
                               places=6)


class TheRecruitmentFiguresAreWhatRecruitAdds(unittest.TestCase):
    """Bug 1: partial recruitment took the army from 45,000 to 54,654 in one month, and nothing said how fast it
    would grow. The figure a level adds in a month is the one military._recruit adds, checked on a copy of the world."""

    def test_each_level_adds_the_figure_the_engine_gives(self):
        for level in ("volunteer", "partial", "general"):
            with self.subTest(level=level):
                w = world()
                w.policy.army_target = 55000.0
                figure = military.recruits_per_month(w, level)
                ghost = copy.deepcopy(w)
                ghost.policy.recruitment = level
                before = ghost.mil.army.size
                military._recruit(ghost)
                self.assertGreater(figure, 0.0)
                self.assertAlmostEqual(ghost.mil.army.size - before, figure, places=6)

    def test_the_figure_is_held_to_the_gap_to_the_target(self):
        w = world()
        w.policy.army_target = w.mil.army.size + 500.0
        self.assertEqual(military.recruits_per_month(w, "general"), 500.0)

    def test_at_the_target_no_level_adds_anyone(self):
        w = world()
        w.policy.army_target = w.mil.army.size
        for level in ("volunteer", "partial", "general"):
            with self.subTest(level=level):
                self.assertEqual(military.recruits_per_month(w, level), 0.0)
        self.assertIn("the army is at or above army_target", briefing.settings_block(w))

    def test_the_settings_block_states_a_month_at_each_level(self):
        w = world()
        w.policy.army_target = 55000.0
        block = briefing.settings_block(w)
        for level in ("volunteer", "partial", "general"):
            with self.subTest(level=level):
                self.assertIn(f"about {round(military.recruits_per_month(w, level), -2):,.0f} at {level}", block)
        self.assertIn("until the army reaches army_target 55,000", block)


class TheTrainedReserveFollowsRecruitment(unittest.TestCase):
    """The reserve is sized by the recruitment setting (RESERVE_RATIO), so a recruitment motion changes how many
    reservists the Army office could call up. reserve_pool_under reads that without changing the world."""

    def test_the_current_setting_gives_the_reserve_pool(self):
        w = world()
        w.policy.recruitment = "partial"
        self.assertEqual(military.reserve_pool_under(w, "partial"), military.reserve_pool(w))
        self.assertEqual(w.policy.recruitment, "partial")

    def test_another_setting_gives_the_pool_the_engine_would_size(self):
        w = world()
        ghost = copy.deepcopy(w)
        ghost.policy.recruitment = "partial"
        self.assertEqual(military.reserve_pool_under(w, "partial"), military.reserve_pool(ghost))
        self.assertEqual(w.policy.recruitment, "none")


class TheMotionsShowWhatTheyChange(unittest.TestCase):
    """Bugs 1 and 2: a motion that sets mobilization or recruitment states its current value, its proposed value and
    the figures; a programme shows each measure as lever: current → proposed, the way a set_policy motion shows its
    value."""

    def test_a_mobilization_motion_shows_the_call_up_it_proposes(self):
        w = world()
        pool = military.reserve_pool(w)
        block = decision_context.motion_block(
            w, "B", [tabled("M1", type="set_policy", subject="mobilization", value="partial")])
        self.assertIn("now none, proposed partial", block)
        partial = round(pool * military.MOBILIZATION_SHARE["partial"], -2)
        self.assertIn(f"partial would call up about {partial:,.0f} reservists", block)
        self.assertIn("not yet embodied costs about", block)

    def test_a_mobilization_motion_that_sends_reservists_home_says_so(self):
        w = world()
        w.policy.mobilization = "partial"
        military.call_up(w, military.reserve_pool(w) * military.MOBILIZATION_SHARE["partial"])
        embodied = military.mobilization_of(w).called_up
        block = decision_context.motion_block(
            w, "B", [tabled("M1", type="set_policy", subject="mobilization", value="none")])
        self.assertIn("now partial, proposed none", block)
        self.assertIn(f"would send about {round(embodied, -2):,.0f} embodied reservists home", block)

    def test_a_level_already_embodied_is_not_costed_again(self):
        """In the real run's final state the pool had drifted a few dozen reservists above the call-up, and the block
        read 'calling up the 0 not yet embodied costs about 0.0M once'. A difference under a hundred is not a call-up."""
        for drift in (0.0, 50.0):
            with self.subTest(drift=drift):
                w = world()
                w.policy.mobilization = "partial"
                military.call_up(w, military.reserve_pool(w) * military.MOBILIZATION_SHARE["partial"] - drift)
                block = decision_context.motion_block(
                    w, "B", [tabled("M1", type="set_policy", subject="mobilization", value="partial")])
                self.assertNotIn("not yet embodied", block)

    def test_a_recruitment_motion_shows_a_month_at_the_proposed_level(self):
        w = world()
        w.policy.army_target = 55000.0
        block = decision_context.motion_block(
            w, "B", [tabled("M2", type="set_policy", subject="recruitment", value="partial")])
        self.assertIn("now none, proposed partial", block)
        adds = round(military.recruits_per_month(w, "partial"), -2)
        self.assertIn(f"at partial would add about {adds:,.0f} soldiers", block)

    def test_a_recruitment_motion_shows_the_trained_reserve_it_would_size(self):
        w = world()
        w.policy.army_target = 55000.0
        block = decision_context.motion_block(
            w, "B", [tabled("M2", type="set_policy", subject="recruitment", value="partial")])
        self.assertIn(f"about {round(military.reserve_pool_under(w, 'partial'), -3):,.0f} under partial", block)

    def test_a_programme_shows_each_measure_as_current_arrow_proposed(self):
        w = world()
        w.policy.rate = 0.065
        w.policy.capital_controls = False
        program = tabled("M3", type="program", subject="", value="", action={"measures": [
            {"lever": "rate", "value": "0.03"}, {"lever": "capital_controls", "value": True}]})
        block = decision_context.motion_block(w, "B", [program])
        self.assertIn(f"rate: {fmt_value(w.policy.rate)} → 0.03", block)
        self.assertIn(f"capital_controls: {fmt_value(w.policy.capital_controls)} → on", block)

    def test_a_validated_programme_reads_the_same_as_a_tabled_one(self):
        w = world()
        w.policy.rate = 0.065
        program = tabled("M3", type="program", subject="", value="",
                         measures=[("rate", 0.03), ("capital_controls", True)])
        block = decision_context.motion_block(w, "B", [program])
        self.assertIn(f"rate: {fmt_value(w.policy.rate)} → 0.03", block)
        self.assertIn("capital_controls: off → on", block)

    def test_a_programme_that_sets_mobilization_states_the_call_up(self):
        w = world()
        pool = military.reserve_pool(w)
        program = tabled("M4", type="program", subject="", value="", action={"measures": [
            {"lever": "mobilization", "value": "partial"}]})
        block = decision_context.motion_block(w, "B", [program])
        self.assertIn("mobilization: none → partial", block)
        partial = round(pool * military.MOBILIZATION_SHARE["partial"], -2)
        self.assertIn(f"partial would call up about {partial:,.0f} reservists", block)


class DescribingTheFiguresChangesNothing(unittest.TestCase):
    """The figures are read off the world; printing them must not move a single number in it."""

    def test_the_settings_and_the_motions_leave_the_world_as_they_were(self):
        w = world()
        w.policy.army_target = 55000.0
        before = w.to_dict()
        briefing.settings_block(w)
        decision_context.motion_block(w, "B", [
            tabled("M1", type="set_policy", subject="mobilization", value="general"),
            tabled("M2", type="set_policy", subject="recruitment", value="partial"),
            tabled("M3", type="program", subject="", value="", action={"measures": [
                {"lever": "mobilization", "value": "partial"}, {"lever": "rate", "value": "0.03"}]})])
        self.assertEqual(w.to_dict(), before)


if __name__ == "__main__":
    unittest.main()
