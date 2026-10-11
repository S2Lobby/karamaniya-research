"""Engine 19: fixes made in review, after the audit's slices were merged.

The slices were fixed apart; these are the places where one fix met another, or where a fix left a reader behind.
"""
import copy
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import actions, dilemmas, foreign, politics, society, standing, versions  # noqa: E402
from karamaniya.backends.scripted import ScriptedBackend  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


class Versions(unittest.TestCase):
    def test_the_bump(self):
        self.assertEqual((versions.WORLD_ENGINE, versions.AGENT_PROMPT, versions.PSYCHOLOGY, versions.ERROR_TAXONOMY),
                         (19, 16, 8, 4))


class LabelsMarkWhereTheyCut(unittest.TestCase):
    """A motion's summary and a refusal's quote of an earlier amendment shorten the delegate's text. They used to slice
    it silently, mid-word (audit TO2's class); they now cut at a word and say so."""

    LONG = " ".join(f"clause{i}" for i in range(60))

    def test_a_long_amendment_summary_is_marked(self):
        summary = actions.motion_summary(new_world(1, 36), {"type": "amend", "text": self.LONG})
        self.assertTrue(summary.endswith(' [cut]"'), summary)
        self.assertNotIn("clause59", summary)

    def test_a_short_amendment_summary_is_whole(self):
        text = "Article 9: the press is free."
        self.assertEqual(actions.motion_summary(new_world(1, 36), {"type": "amend", "text": text}),
                         f'amend the Charter: "{text}"')

    def test_a_label_cuts_at_a_word(self):
        cut = politics.label(self.LONG, 50)
        self.assertTrue(cut.endswith(" [cut]"))
        self.assertIn(cut[:-len(" [cut]")].split()[-1], self.LONG.split())


class TheStandInsReadAPercentValue(unittest.TestCase):
    """The intake now stores a share its text writes with a percent sign as a percent ("5%", audit MO11). The scripted
    stand-ins read the value with float(), which refused "5%", so their rules on military, tax and welfare skipped
    every such motion."""

    def test_a_percent_value_is_voted_as_its_share(self):
        w = new_world(1, 36)
        w.policy.military = .03
        w.econ.arrears = 5e6
        backend = ScriptedBackend({"persona": "technocrat"})
        mo = {"id": "M1", "type": "set_policy", "subject": "military", "proposer": "B", "text": "Raise it."}
        as_share = backend._vote_rules(w, "A", {**mo, "value": "0.05"})
        as_percent = backend._vote_rules(w, "A", {**mo, "value": "5%"})
        self.assertEqual(as_share, "no")
        self.assertEqual(as_percent, as_share)


class InflationWithoutTheHistoryBehindIt(unittest.TestCase):
    """A world set to a late month without its history (a test, a scenario) indexed past the history once the
    inflation window covered more than 12 months (audit TO1's window). It now annualises the change so far."""

    def test_a_world_at_month_35_with_no_history(self):
        w = new_world(1, 36)
        w.month, w.history = 35, []
        w.econ.cpi = 1.0
        self.assertEqual(society.inflation_yoy(w), 0.0)


class NoPsychologyFromADilemmaWithoutTheHumanFactor(unittest.TestCase):
    """Follow-up C guarded the audits; a corruption ally, an assassination attempt, an intelligence overreach and an
    arms cache still wrote standing through standing.reputation_effect and standing.ensure."""

    def world(self):
        """A world as a run without the human factor holds it: no delegate has any psychology (audit RU5)."""
        w = new_world(2, 36)
        w.human_factor = False
        for m in w.members:
            m.agent_state = {}
        w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
        return w

    def test_reputation_effect_writes_nothing(self):
        w = self.world()
        before = copy.deepcopy(w.member("B").agent_state)
        standing.reputation_effect(w, "B", "corruption", .8)
        self.assertEqual(w.member("B").agent_state, before)

    def test_an_arms_cache_and_an_assassination_attempt_write_nothing(self):
        w = self.world()
        before = {m.id: copy.deepcopy(m.agent_state) for m in w.members}
        add = lambda *args, **kwargs: None  # noqa: E731
        dilemmas._effect(w, {"id": "I1", "kind": "arms_cache", "text": "A cache was found.", "applied": {}}, True, add)
        dilemmas._effect(w, {"id": "I2", "kind": "assassination_attempt", "target": "A", "text": "", "applied": {}},
                         True, add)
        self.assertEqual({m.id: m.agent_state for m in w.members}, before)

    def test_with_the_human_factor_the_effect_stays(self):
        w = new_world(2, 36)
        before = copy.deepcopy(w.member("B").agent_state)
        standing.reputation_effect(w, "B", "corruption", .8)
        self.assertNotEqual(w.member("B").agent_state, before)


class ABorderIncidentOutlastsTheRebuild(unittest.TestCase):
    """foreign._incident wrote Veleria's threat of Karamaniya directly, and positions() rebuilt it from beliefs the next
    month, so the incident no longer counted (the class of audit MI9)."""

    class Always:
        def random(self):
            return 0.0

        def randrange(self, n):
            return 0

    def threat_after_rebuild(self, incident: bool) -> float:
        w = new_world(3, 36)
        w.foreign = foreign.initial_state(w.seed)
        w.month = 6
        if incident:
            with mock.patch.object(foreign, "rng_for", return_value=self.Always()):
                foreign._incident(w, .5)
        foreign.positions(w)            # rebuilds the threat from Veleria's beliefs, as each month does
        return w.foreign["actors"]["veleria"]["threat_perception"]["karamaniya"]

    def test_the_incident_still_counts_after_positions(self):
        self.assertGreater(self.threat_after_rebuild(True), self.threat_after_rebuild(False) + .02)


if __name__ == "__main__":
    unittest.main()
