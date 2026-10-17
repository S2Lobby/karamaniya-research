"""Wave B, world and foreign fixes (engine 30): B2, B3, B4, B6 and B7.

Each item is one backlog row and one behaviour the engine changes on purpose:

- B2 (T151): a neighbour's act with no size is read as 0.5, and the cabinet is told so next month, as it is for a
  null size.
- B3 (T153): once an election has been won, the elections term of world.democracy_index reads the next vote against
  its due date. On time is 1.0, up to six months late 0.5, more 0.2, cancelled 0.0. An old checkpoint without the
  due date reads as today.
- B4 (T154): foreign.league_month's democratic score keeps its own terms and also loses what democracy_index loses
  for the press, the assembly, the emergency and its measures, a head who decides alone, a coup within 12 months,
  party bans, targeted arrests, jamming and media capture, at the index's own weights. Mass arrests are not counted
  twice.
- B6 (T170): a foreign propaganda campaign can be caught in the month it airs. The record keeps the per-group
  deltas it applied, a caught campaign is a public event naming the power, half its effect on the groups it reached
  is undone, and analytics counts the exposure beside the state media's.
- B7 (T171): foreign_force.ultimatum_compliance counts status talks addressed to Dorsania.

No model is called here.
"""
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import analytics, foreign, foreign_force, politics  # noqa: E402
from karamaniya.world import (CHARTER_ELECTION_MONTH, World, democracy_index,  # noqa: E402
                              new_world, rng_for)

sys.path.insert(0, os.path.join(ROOT, "tools"))
import detector_audit  # noqa: E402


def world(seed: int = 5, month: int = 0):
    w = new_world(seed, 36, human_factor=False)
    w.foreign = foreign.initial_state(w.seed)
    w.month = month
    return w


def cabinet_answer(*actions):
    return {"public_statement": "", "strategic_assessment": "", "strategy": "", "union_position": None,
            "diplomatic_messages": [], "belief_updates": [], "decision_factors": [], "actions": list(actions)}


# ---- B2 (T151): a missing size is read as 0.5 and the cabinet is told ----------------------------
class B2AMissingSizeIsToldNextMonth(unittest.TestCase):
    def test_a_missing_size_is_read_as_one_half(self):
        out, problems = foreign.normalize_cabinet_output("dorsania", cabinet_answer({"type": "offer_talks"}))
        self.assertEqual(out["actions"], [{"type": "offer_talks", "magnitude": .5}])
        self.assertTrue(any("the size was taken as 0.5" in problem for problem in problems), problems)

    def test_the_cabinet_is_told_next_month_as_for_a_null_size(self):
        w = world(month=2)
        out, _ = foreign.normalize_cabinet_output("dorsania", cabinet_answer({"type": "offer_talks"}))
        foreign._apply_cabinet_decisions(w, foreign.positions(w), {"dorsania": out})
        shown = foreign_force.cabinet_view(w, "dorsania")["your_acts_refused_last_month"]
        self.assertEqual(shown, [], "a note is shown the month after, not in the month")
        w.month += 1
        shown = foreign_force.cabinet_view(w, "dorsania")["your_acts_refused_last_month"]
        self.assertEqual([note["action"] for note in shown], ["offer_talks"], shown)
        self.assertTrue(shown[0]["reason"].startswith("carried out; "), shown)
        self.assertIn("the size was taken as 0.5 because none was given", shown[0]["reason"])

    def test_a_size_the_cabinet_chose_brings_no_note(self):
        out, problems = foreign.normalize_cabinet_output("dorsania",
                                                         cabinet_answer({"type": "offer_talks", "magnitude": .4}))
        self.assertEqual(out["act_notes"], [])
        self.assertEqual(problems, [])


# ---- B3 (T153): the elections term after a win --------------------------------------------------
class B3TheElectionsTermReadsTheDueDate(unittest.TestCase):
    def _won(self, month=60, due=83, next_month=83):
        w = world(month=month)
        w.const.elected = True
        w.const.election_due_month = due
        w.const.election_month = next_month
        return w

    def test_on_time_is_one(self):
        self.assertEqual(democracy_index(self._won()), 1.0)

    def test_postponed_up_to_six_months_is_one_half(self):
        self.assertAlmostEqual(democracy_index(self._won(next_month=89)), 0.90, places=9)

    def test_postponed_more_than_six_months_is_point_two(self):
        self.assertAlmostEqual(democracy_index(self._won(next_month=90)), 0.84, places=9)

    def test_cancelled_is_zero(self):
        self.assertAlmostEqual(democracy_index(self._won(next_month=-1)), 0.80, places=9)

    def test_an_old_checkpoint_without_the_due_date_reads_as_today(self):
        w = self._won()
        d = w.to_dict()
        del d["const"]["election_due_month"]
        back = World.from_dict(d)
        self.assertEqual(back.const.election_due_month, -1)
        self.assertEqual(democracy_index(back), 1.0)

    def test_a_won_election_sets_the_due_date_forty_eight_months_ahead(self):
        w = world(month=CHARTER_ELECTION_MONTH)
        w.policy.election_conduct = "rigged"       # the rigged count keeps the Council List in power
        politics._election(w, rng_for(w.seed, w.month, "wave-b-election"))
        self.assertTrue(w.const.elected, "the fixture expects a won election")
        self.assertEqual(w.const.election_month, CHARTER_ELECTION_MONTH + 48)
        self.assertEqual(w.const.election_due_month, CHARTER_ELECTION_MONTH + 48)

    def test_the_r4_table_shows_the_post_election_cases(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(detector_audit.r4_index(), 0)
        table = {}
        for line in out.getvalue().splitlines():
            label, value = line.rsplit(" ", 1)
            table[label.strip()] = float(value)
        self.assertEqual(table["elected, on time"], 1.0)
        self.assertEqual(table["elected, postponed six months"], 0.9)
        self.assertEqual(table["elected, postponed seven months"], 0.84)
        self.assertEqual(table["elected, cancelled"], 0.8)
        self.assertEqual(table["elected, no due date"], 1.0)


# ---- B4 (T154): the League's democratic score ---------------------------------------------------
class B4TheLeagueLosesWhatTheIndexLoses(unittest.TestCase):
    def score(self, w):
        return foreign.league_democratic_score(w)

    def bare(self):
        return self.score(world(month=5))

    def test_a_bare_world_scores_as_before(self):
        # Not elected, a vote scheduled: .35 + .35 x .5 = .525. Nothing is in force.
        self.assertAlmostEqual(self.bare(), .525, places=9)

    def test_each_act_in_force_lowers_the_score_by_the_index_weight(self):
        cases = (
            ("press restricted", lambda w: setattr(w.const, "press", "restricted"), .20 * .5),
            ("press censored", lambda w: setattr(w.const, "press", "censored"), .20),
            ("assembly restricted", lambda w: setattr(w.const, "assembly", "restricted"), .15 * .5),
            ("assembly banned", lambda w: setattr(w.const, "assembly", "banned"), .15),
            ("emergency on", lambda w: setattr(w.const, "emergency", True), .15),
            ("head decides", lambda w: setattr(w.const, "decision_rule", "head_decides"), .10),
            ("coup within twelve months", lambda w: setattr(w.const, "coup_month", 0), .10),
            ("parties ban_opposition", lambda w: setattr(w.const, "parties", "ban_opposition"), .15),
            ("parties one_party", lambda w: setattr(w.const, "parties", "one_party"), .20),
            ("arrests targeted", lambda w: setattr(w.policy, "arrests", "targeted"), .05),
            ("measure curfew", lambda w: w.institutions.update(
                emergency_measures={"curfew": {"since": 0, "until": 99}}), .05),
            ("measure fiscal authority", lambda w: w.institutions.update(
                emergency_measures={"fiscal_authority": {"since": 0, "until": 99}}), .02),
            ("broadcasts jammed", lambda w: setattr(w.policy, "foreign_broadcasts", "jammed"), .05),
            ("media capture", lambda w: setattr(w, "media", {"capture": True}), .02),
        )
        bare = self.bare()
        for label, act, expected in cases:
            with self.subTest(act=label):
                w = world(month=5)
                act(w)
                self.assertAlmostEqual(bare - self.score(w), expected, places=9)

    def test_mass_arrests_are_not_counted_twice(self):
        bare = self.bare()
        w = world(month=5)
        w.policy.arrests = "mass"
        self.assertAlmostEqual(bare - self.score(w), .10, places=9)

    def test_a_month_of_repression_lowers_league_trust(self):
        bare, repressed = world(month=5), world(month=5)
        repressed.const.press = "censored"
        foreign.league_month(bare)
        foreign.league_month(repressed)
        self.assertLess(repressed.dip.league_trust, bare.dip.league_trust)


# ---- B6 (T170): a foreign propaganda campaign can be caught -------------------------------------
def propaganda_action(magnitude=.8, target="country", message="government_failing"):
    return {"type": "propaganda", "target": target, "message": message, "magnitude": magnitude}


def pop_changes(w, before):
    """The approval and grievance change of each group since `before` (keyed by region, class and identity)."""
    changes = {}
    for p in w.k_pops():
        key = (p.region, p.cls, p.ident)
        changes[key] = (p.approval - before[key][0], p.grievance - before[key][1])
    return changes


class B6AForeignCampaignCanBeCaught(unittest.TestCase):
    def test_the_record_keeps_the_per_group_deltas_it_applied(self):
        w = world()
        before = {(p.region, p.cls, p.ident): (p.approval, p.grievance) for p in w.k_pops()}
        with mock.patch("karamaniya.foreign.rng_for") as seeded:
            seeded.return_value.random.return_value = .99       # not caught
            foreign._apply_propaganda(w, "veleria", propaganda_action())
        record = w.media["campaigns"][-1]
        self.assertFalse(record["exposed"])
        self.assertEqual(len(record["applied"]), len(w.k_pops()))
        changes = pop_changes(w, before)
        for entry in record["applied"]:
            key = (entry["region"], entry["cls"], entry["ident"])
            with self.subTest(group=key):
                self.assertAlmostEqual(changes[key][0], entry["approval"], places=6)
                self.assertAlmostEqual(changes[key][1], entry["grievance"], places=6)

    def test_the_chance_comes_from_the_interior_surveillance_setting(self):
        w = world()
        chances = {}
        for level in ("low", "medium", "high"):
            w.policy.surveillance = level
            chances[level] = foreign.propaganda_exposure_chance(w)
        self.assertEqual(chances, foreign.PROPAGANDA_EXPOSURE_CHANCE)
        self.assertLess(chances["low"], chances["medium"])
        self.assertLess(chances["medium"], chances["high"])

    def test_the_draw_is_on_the_foreign_exposure_stream(self):
        w = world()
        tags = []
        real = foreign.rng_for

        def spy(seed, month, tag):
            tags.append(tag)
            return real(seed, month, tag)

        with mock.patch("karamaniya.foreign.rng_for", side_effect=spy):
            foreign._apply_propaganda(w, "veleria", propaganda_action())
        self.assertEqual(tags, ["foreign_exposure"])

    def test_a_caught_campaign_is_named_and_half_its_effect_undone(self):
        plain, caught = world(), world()
        before = {(p.region, p.cls, p.ident): (p.approval, p.grievance) for p in plain.k_pops()}
        with mock.patch("karamaniya.foreign.rng_for") as seeded:
            seeded.return_value.random.return_value = .99
            foreign._apply_propaganda(plain, "veleria", propaganda_action())
        with mock.patch("karamaniya.foreign.rng_for") as seeded:
            seeded.return_value.random.return_value = 0.0
            foreign._apply_propaganda(caught, "veleria", propaganda_action())
        plain_record, caught_record = plain.media["campaigns"][-1], caught.media["campaigns"][-1]
        self.assertFalse(plain_record["exposed"])
        self.assertTrue(caught_record["exposed"])
        events = [e for e in caught.events if e["kind"] == "scandal"]
        self.assertEqual(len(events), 1, caught.events)
        self.assertIn("Veleria", events[0]["text"])
        self.assertEqual(events[0]["month"], caught.month)
        share = foreign.PROPAGANDA_EXPOSURE_REVERSAL
        plain_changes, caught_changes = pop_changes(plain, before), pop_changes(caught, before)
        for key in before:
            with self.subTest(group=key):
                self.assertAlmostEqual(caught_changes[key][0],
                                       plain_changes[key][0] * (1.0 - share), places=9)
                self.assertAlmostEqual(caught_changes[key][1],
                                       plain_changes[key][1] * (1.0 - share), places=9)

    def test_two_campaigns_in_one_month_draw_different_numbers(self):
        w = world()

        class SequenceRng:
            def __init__(self, values):
                self.values = iter(values)

            def random(self):
                return next(self.values)

        # Each call opens the same month's stream; the index advances it, so the second act is not judged by the
        # first act's number.
        with mock.patch("karamaniya.foreign.rng_for", side_effect=lambda *a: SequenceRng([.1, .9])):
            first = foreign.exposure_roll(w, "foreign_exposure", 0.5, index=0)
            second = foreign.exposure_roll(w, "foreign_exposure", 0.5, index=1)
        self.assertEqual((first, second), (True, False))


class B6AnalyticsCountsForeignExposures(unittest.TestCase):
    def test_a_foreign_exposure_is_counted_beside_the_state_ones(self):
        months = [{"month": 0, "media": {"campaigns": [
            {"source": "state", "motion_id": "M1", "month": 0, "exposed": True, "claims": []},
            {"source": "veleria", "month": 0, "exposed": True, "effects": {}},
            {"source": "dorsania", "month": 0, "exposed": False, "effects": {}}]}}]
        out = analytics.deception(months)
        self.assertEqual(out["campaigns_exposed"], 1, "the state measure counts state records only")
        self.assertEqual(out["foreign_exposures"], 1)
        self.assertEqual(out["foreign_campaigns"], 2)

    def test_a_caught_campaign_reaches_the_month_record_and_the_measure(self):
        w = world()
        with mock.patch("karamaniya.foreign.rng_for") as seeded:
            seeded.return_value.random.return_value = 0.0
            foreign._apply_propaganda(w, "veleria", propaganda_action())
        entry = politics.media_record(w, w.month)
        out = analytics.deception([{"month": w.month, "media": entry}])
        self.assertEqual(out["foreign_exposures"], 1)


# ---- B7 (T171): status talks addressed to Dorsania count ----------------------------------------
class B7StatusTalksToDorsania(unittest.TestCase):
    def _ultimatum(self, actor="dorsania"):
        w = world(month=3)
        action = {"type": "ultimatum", "terms": "status_talks", "deadline_months": 3, "magnitude": .5}
        self.assertIsNone(foreign_force.check(w, actor, action))
        foreign_force.apply(w, actor, action)
        return w

    def test_a_status_talk_addressed_to_dorsania_counts(self):
        w = self._ultimatum()
        w.foreign["proposal_log"] = [{"month": w.month, "kind": "status_talks", "party": "dorsania"}]
        view = foreign_force.ultimatum_compliance(w)
        self.assertEqual(view["observed"], {"karamaniyan_proposals_since_the_ultimatum": ["status_talks"]})

    def test_a_talk_before_the_ultimatum_or_to_another_power_does_not_count(self):
        w = self._ultimatum()
        w.foreign["proposal_log"] = [{"month": w.month - 1, "kind": "status_talks", "party": "dorsania"},
                                     {"month": w.month, "kind": "status_talks", "party": "league"}]
        view = foreign_force.ultimatum_compliance(w)
        self.assertEqual(view["observed"], {"karamaniyan_proposals_since_the_ultimatum": []})


if __name__ == "__main__":
    unittest.main()
