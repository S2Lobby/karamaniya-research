"""Wave 3 across workstreams: the state campaign, a foreign campaign and the counter in one month.

A (state media) and B (the Union's propaganda) share `w.media`: A owns credibility, the line and the
state records; B appends foreign records and reads credibility. Both media restrictions reach the
democracy index. This is the plan's definition-of-done test: the two campaigns leave their records,
jamming costs credibility, and the composed index takes both penalties.

    python -m unittest tests.test_engine27_wave3_integration
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import foreign, politics  # noqa: E402
from karamaniya.world import (BROADCAST_JAM_PENALTY, MEDIA_CAPTURE_PENALTY, democracy_index,  # noqa: E402
                              new_world)


def world():
    w = new_world(5, 36, human_factor=False)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    return w


def state_campaign(w, intensity="high"):
    """Table a media_campaign the way the council does, then run the month's media step."""
    mo = {"id": "M1", "type": "media_campaign", "subject": "", "value": "",
          "text": "The government reports on its work this month.",
          "action": {"kinds": ["claim_figures"], "claims": [{"metric": "inflation", "value": 1.0}],
                     "intensity": intensity},
          "proposer": "A", "votes": {"A": "yes", "B": "yes", "C": "no", "D": "yes", "E": "abstain"}}
    problem = politics.validate_motion(w, mo)
    if problem:
        raise AssertionError(problem)
    politics.apply_motion(w, mo)
    politics.media_month(w)


def foreign_campaign(w, actor="veleria"):
    """One cabinet's propaganda act, read and applied as the engine resolves it."""
    answer = {"public_statement": "", "strategic_assessment": "", "strategy": "", "union_position": None,
              "diplomatic_messages": [], "belief_updates": [], "decision_factors": [],
              "actions": [{"type": "propaganda", "target": "country", "message": "government_failing",
                           "magnitude": .8}]}
    out, problems = foreign.normalize_cabinet_output(actor, answer)
    if problems:
        raise AssertionError(problems)
    foreign._apply_cabinet_decisions(w, foreign.positions(w), {actor: out})
    return out


class TheThreeMediaInstrumentsCompose(unittest.TestCase):
    def test_the_state_and_foreign_campaigns_both_leave_records(self):
        w = world()
        state_campaign(w)
        foreign_campaign(w)
        sources = [record["source"] for record in w.media["campaigns"]]
        self.assertIn("state", sources)
        self.assertIn("veleria", sources)
        self.assertTrue(w.media["capture"], "a high-intensity state line is media capture")

    def test_jamming_costs_credibility_and_the_index_takes_both_penalties(self):
        w = world()
        state_campaign(w)
        before = w.media["credibility"]
        w.policy.foreign_broadcasts = "jammed"
        foreign.broadcast_month(w)
        self.assertEqual(w.media["credibility"], round(before - foreign.BROADCAST_JAM_CREDIBILITY, 4))
        with_both = democracy_index(w)
        w.media["capture"] = False
        w.policy.foreign_broadcasts = "open"
        neither = democracy_index(w)
        self.assertAlmostEqual(neither - with_both, MEDIA_CAPTURE_PENALTY + BROADCAST_JAM_PENALTY, places=6)

    def test_a_foreign_campaign_does_not_clobber_the_state_record(self):
        w = world()
        state_campaign(w)
        state_records = [r for r in w.media["campaigns"] if r["source"] == "state"]
        foreign_campaign(w)
        self.assertEqual([r for r in w.media["campaigns"] if r["source"] == "state"], state_records)


if __name__ == "__main__":
    unittest.main()
