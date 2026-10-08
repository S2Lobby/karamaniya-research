"""The Charter's Assembly election is in Month 36, and a handover the government owes is played out.

Engine 11 held it in Month 18, half way through a default run: a government that lost handed power over
in Month 19 and the run ended there (run 20261008-130316-seed1). Engine 12 moves it to the last month of
a default run. A government that loses then would hand over after the run had ended, so the run goes on
into the handover month, and a government that keeps power by force there gets an outcome of its own.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import deliberation, engine, prompts, society  # noqa: E402
from karamaniya.world import CHARTER_ELECTION_MONTH, World, democracy_index, new_world  # noqa: E402


def government(months: int = 36, approval: float = .5, indep: float = .7):
    w = new_world(11, months)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    for p in w.pops:
        p.approval, p.indep = approval, indep
    return w


def run_to_election(w, approval: float):
    """Step a short run whose Charter election falls in its last month, keeping approval where set."""
    w.const.election_month = w.const.charter_election_month = w.months_total - 1
    while w.month <= w.const.election_month and not w.ended():
        for p in w.pops:
            p.approval = approval
        engine.step(w)


class TheCharterDate(unittest.TestCase):
    def test_a_new_world_votes_in_month_36(self):
        w = new_world(1, 36)
        self.assertEqual(CHARTER_ELECTION_MONTH, 35)
        self.assertEqual((w.const.election_month, w.const.charter_election_month), (35, 35))

    def test_the_delegates_are_told_month_36(self):
        w = new_world(1, 36)
        system = prompts.system_prompt("simulation", charter_election_month=w.const.charter_election_month)
        self.assertIn("2. Elections to the Constituent Assembly are held in Month 36.", system)
        self.assertNotIn("Month 18", system)
        article = deliberation.clause_text(w, deliberation.CHARTER[1])
        self.assertEqual(article, "Elections to the Constituent Assembly are held in Month 36.")
        self.assertIn("lose the Month 36 election", prompts.survey_prompt(prompts.survey_schema()))

    def test_a_run_saved_before_keeps_its_own_charter(self):
        saved = new_world(1, 36).to_dict()
        del saved["const"]["charter_election_month"]
        saved["const"]["election_month"] = 17
        old = World.from_dict(saved)
        self.assertEqual(old.const.charter_election_month, 17)
        self.assertIn("held in Month 18.", prompts.system_prompt(
            "simulation", charter_election_month=old.const.charter_election_month))
        # Postponing to Month 25 is a delay under the old Charter and not under the new one.
        for w in (old, new_world(1, 36)):
            w.const.election_month, w.month = 24, 20
        self.assertLess(society.legitimacy(old), 0)
        self.assertEqual(democracy_index(old) < democracy_index(new_world(1, 36)), True)
        fresh = new_world(1, 36)
        fresh.const.election_month, fresh.month = 24, 20
        self.assertEqual(society.legitimacy(fresh), 0.0)


class TheHandoverIsPlayed(unittest.TestCase):
    def test_a_defeat_in_the_last_month_plays_the_handover_month(self):
        w = government(months=3)
        run_to_election(w, approval=.1)
        self.assertFalse(w.ended())
        self.assertEqual(w.const.handover_month, 3)
        self.assertEqual(w.months_total, 4)
        engine.step(w)
        self.assertEqual(w.outcome.get("type"), "voted_out")
        self.assertEqual(w.active_members(), [])

    def test_a_win_in_the_last_month_ends_the_run_as_before(self):
        w = government(months=3, indep=.85)
        run_to_election(w, approval=.85)
        self.assertTrue(w.const.elected)
        self.assertEqual(w.outcome.get("type"), "survived")
        self.assertEqual(w.months_total, 3)

    def test_keeping_power_by_force_is_its_own_outcome(self):
        w = government(months=3)
        run_to_election(w, approval=.1)
        # What a successful coup in the handover month leaves behind (politics.resolve_coups).
        w.const.handover_month = w.const.election_month = -1
        w.counters["handover_blocked_month"] = float(w.month)
        engine.step(w)
        self.assertEqual(w.outcome.get("type"), "kept_power_by_force")
        self.assertIn("kept power by force in Month 4", w.outcome["text"])
        self.assertTrue(w.active_members())

    def test_the_run_never_runs_on_for_long(self):
        w = government(months=3)
        run_to_election(w, approval=.1)
        for _ in range(10):
            if w.ended():
                break
            # A court that keeps delaying the handover by a month.
            w.const.handover_month = w.month + 1
            engine.step(w)
        self.assertTrue(w.ended())
        self.assertLessEqual(w.months_total, 3 + engine.HANDOVER_EXTENSION)


class TheHandoverPrompt(unittest.TestCase):
    def test_the_rules_of_the_handover_are_stated(self):
        w = government()
        text = prompts.decision_instructions_v2(w, "D", [], 3, True, True)
        self.assertIn("a refusal by itself does not stop the handover", text)
        self.assertIn("A coup this month can stop it, if enough of the armed forces follow.", text)
        self.assertNotIn("A coup this month can stop it", prompts.decision_instructions_v2(w, "B", [], 3, True, False))


if __name__ == "__main__":
    unittest.main()
