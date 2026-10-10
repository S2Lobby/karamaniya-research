"""World engine 18: each delegate has a past, and an organised base that can turn on it (biographies.py, bases.py).

In run 20261010-070501-seed1 the five delegates' private opening positions were only 9-12% alike, yet 27 of 40 votes
were five to nothing. Nothing gave a delegate a past, and no one of its own watched its votes. Each delegate now has
both: a past dealt from the founding, and a base that reads its votes through the audiences it watches and can
withdraw its support, publicly, once that support falls low enough.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import agents, bases, biographies, foreign, scorecard, standing  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import World, new_world  # noqa: E402

NEW_KEYS = ("biography", "base")
# The seeded state every other draw produces; a delegate's past and base must leave all of it as it was.
UNCHANGED_IF_NO_PAST = ("traits", "agenda", "long_term_ambitions", "ambitions", "priorities", "fears",
                        "beliefs", "constituencies", "stress", "motion_outcomes")


def world(seed: int = 5):
    w = new_world(seed, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    agents.ensure(w)                       # the office audiences follow the offices, as they are set now
    for m in w.members:
        for aud in m.agent_state["constituencies"].values():
            aud["support_for_delegate"] = .5
    return w


def referendum(votes, passed=True):
    return {"id": "M1", "proposer": "A", "type": "referendum", "subject": "independence", "value": "",
            "summary": "hold a referendum on independence this month", "passed": passed, "void": False,
            "withdrawn": False, "votes": votes}


def cost_the_vote(w, votes, passed=True):
    """The council's record of one referendum this month, costed as the council costs it (apply_vote_costs)."""
    standing.apply_vote_costs(w, {"month": w.month, "motions": [referendum(votes, passed)], "decisions": {},
                                  "defiance": [], "resigned": []})


def one_month(w, votes=None, passed=True):
    """A month in the engine's order: the vote is costed, then the audiences update, then the bases, then the clock."""
    if votes:
        cost_the_vote(w, votes, passed)
    agents._update_stress(w)
    bases.update_all(w)
    w.month += 1


def base(w, mid):
    return w.member(mid).agent_state["base"]


def disown_events(w):
    return [e for e in w.events if e.get("kind") == "base_disowned"]


class TheDealtPasts(unittest.TestCase):
    def test_five_delegates_get_five_different_pasts_from_the_seed(self):
        for seed in (1, 2, 3):
            with self.subTest(seed=seed):
                w = new_world(seed, 36)
                dealt = [m.agent_state["biography"]["id"] for m in w.members]
                self.assertEqual(len(set(dealt)), 5)
                self.assertEqual(dealt, [m.agent_state["biography"]["id"] for m in new_world(seed, 36).members])
        self.assertNotEqual([m.agent_state["biography"]["id"] for m in new_world(1, 36).members],
                            [m.agent_state["biography"]["id"] for m in new_world(2, 36).members])

    def test_eight_delegates_get_all_eight_pasts(self):
        w = new_world(1, 36, member_ids=list("ABCDEFGH"))
        self.assertEqual(sorted(m.agent_state["biography"]["id"] for m in w.members),
                         sorted(spec["id"] for spec in biographies.BIOGRAPHIES))

    def test_each_past_comes_with_the_base_it_is_from(self):
        w = new_world(2, 36)
        for m in w.members:
            self.assertEqual(m.agent_state["base"]["id"], m.agent_state["biography"]["base"], m.id)
            self.assertEqual(m.agent_state["base"]["support"], bases.START, m.id)

    def test_the_catalogue_names_eight_pasts_and_eight_bases_one_to_one(self):
        self.assertEqual(len(biographies.BIOGRAPHIES), 8)
        self.assertEqual(sorted(spec["base"] for spec in biographies.BIOGRAPHIES), sorted(bases.BASES))
        for spec in biographies.BIOGRAPHIES:
            with self.subTest(past=spec["id"]):
                self.assertTrue(2 <= spec["text"].count(". ") + 1 <= 3)
                self.assertNotIn("Delegate", spec["text"])

    def test_the_pasts_state_facts_and_never_tell_a_delegate_what_to_do(self):
        for spec in biographies.BIOGRAPHIES:
            with self.subTest(past=spec["id"]):
                self.assertIsNone(re.search(r"\b(should|must|ought|always|never|vote|votes|voting)\b",
                                            spec["text"].lower()))

    def test_the_draw_leaves_every_other_seeded_value_as_it_was(self):
        with_past = new_world(4, 36)
        with mock.patch.object(biographies, "deal", return_value=None):
            without = new_world(4, 36)
        for a, b in zip(with_past.members, without.members):
            for key in UNCHANGED_IF_NO_PAST:
                self.assertEqual(a.agent_state[key], b.agent_state[key], (a.id, key))
            self.assertEqual({k: v for k, v in a.agent_state.items() if k not in NEW_KEYS}, b.agent_state, a.id)
        self.assertTrue(all(k not in m.agent_state for m in without.members for k in NEW_KEYS))


class TheDisposition(unittest.TestCase):
    def test_every_delegate_has_its_past_and_its_base_beside_the_agenda(self):
        w = new_world(1, 36)
        for m in w.members:
            text = agents.disposition_v2(w, m.id)
            lines = text.splitlines()
            self.assertIn("YOUR PAST:", text, m.id)
            self.assertIn("YOUR BASE:", text, m.id)
            self.assertTrue(lines[1].startswith("YOUR POLITICAL AGENDA ("), m.id)
            self.assertTrue(lines[2].startswith("YOUR PAST: "), m.id)
            self.assertTrue(lines[3].startswith("YOUR BASE: "), m.id)

    def test_the_past_is_the_biography_text(self):
        w = new_world(1, 36)
        m = w.member("A")
        self.assertIn(biographies.BY_ID[m.agent_state["biography"]["id"]]["text"], agents.disposition_v2(w, "A"))

    def test_the_base_line_names_the_base_and_how_it_stands(self):
        w = world()
        state = w.member("A").agent_state
        state["base"] = bases.opening("veterans")
        self.assertEqual(bases.text(state), "YOUR BASE: the Veterans of the Winter War league "
                                            "(put you forward; it watches your votes): steady.")
        for support, mood in ((.35, "uneasy"), (.3, "angry"), (.1, "angry")):
            with self.subTest(support=support):
                state["base"]["support"] = support
                self.assertTrue(bases.text(state).endswith(f"(put you forward; it watches your votes): {mood}."))
        state["base"]["disowned"] = True
        self.assertTrue(bases.text(state).endswith("(put you forward; it watches your votes): has disowned you."))

    def test_under_a_secret_ballot_the_base_line_says_it_cannot_see_the_votes(self):
        # Review fix: a secret ballot costs no vote (standing.apply_vote_costs), so no base sees one; the line must not
        # tell the delegate that its base watches its votes.
        w = world()
        w.ballot = "secret"
        state = w.member("A").agent_state
        state["base"] = bases.opening("veterans")
        self.assertEqual(bases.text(state, secret=True), "YOUR BASE: the Veterans of the Winter War league "
                                                         "(put you forward; votes are secret, so it cannot see yours): steady.")
        self.assertIn("votes are secret, so it cannot see yours", agents.disposition_v2(w, "A"))

    def test_the_last_vote_that_cost_the_delegate_is_named_when_the_base_is_uneasy_or_worse(self):
        w = world()
        w.member("A").agent_state["base"] = dict(bases.opening("veterans"), last_cost={
            "month": 6, "motion": "M3", "vote": "yes", "summary": "cede Kessel Valley"})
        state = w.member("A").agent_state
        self.assertNotIn("The last vote that cost you", bases.text(state))           # steady: not named
        state["base"]["support"] = .35
        self.assertTrue(bases.text(state).endswith(
            "The last vote that cost you with it: your yes on M3 (cede Kessel Valley) in Month 7."))
        state["base"]["support"] = .6
        state["base"]["disowned"] = True
        self.assertIn("has disowned you. The last vote that cost you with it: your yes on M3", bases.text(state))

    def test_a_delegate_from_an_older_run_has_no_past_or_base_in_its_disposition(self):
        w = world()
        for m in w.members:
            m.agent_state.pop("biography", None)
            m.agent_state.pop("base", None)
        for m in w.members:
            text = agents.disposition_v2(w, m.id)
            self.assertNotIn("YOUR PAST:", text)
            self.assertNotIn("YOUR BASE:", text)


class TheBaseReactsToVotes(unittest.TestCase):
    def setUp(self):
        self.w = world()
        for mid in ("A", "C"):
            self.w.member(mid).agent_state["base"] = bases.opening("veterans")

    def test_a_yes_on_a_passed_independence_referendum_costs_a_veterans_base_and_a_no_gains_it(self):
        yes_no = {"A": "yes", "C": "no", "B": "yes", "D": "abstain", "E": "yes"}
        cost_the_vote(self.w, yes_no)
        bases.update_all(self.w)
        # The veterans read a referendum through their whole mix: the movement (-1.6) at .5, the enlisted men (-.6) at
        # .3 and the border communities (-.3) at .2, -1.04 in all, whatever seat their delegate holds. A yes is
        # .02 x -1.04 x the vote scale of 1.5, scaled by 1.5, then the drift back toward .55. A no is half a yes, in
        # the other direction.
        self.assertAlmostEqual(base(self.w, "A")["support"], .553, places=3)
        self.assertAlmostEqual(base(self.w, "C")["support"], .620, places=3)
        self.assertLess(base(self.w, "A")["support"], bases.START)
        self.assertGreater(base(self.w, "C")["support"], bases.START)

    def test_a_base_whose_audiences_belong_to_another_office_still_sees_its_delegates_vote(self):
        # Review fix: the first version read only the audiences the delegate answered to, so the Vell community council
        # (regional administrations and urban residents, the Interior's audiences) never moved behind the head of
        # government. A yes on emergency powers costs it now.
        self.w.member("A").agent_state["base"] = bases.opening("vell")
        emergency = {"id": "M2", "proposer": "A", "type": "constitution", "subject": "emergency", "value": "on",
                     "summary": "declare emergency powers", "passed": True, "void": False, "withdrawn": False,
                     "votes": {"A": "yes"}}
        self.assertNotIn("regional administrations", self.w.member("A").agent_state["constituencies"])
        standing.apply_vote_costs(self.w, {"month": self.w.month, "motions": [emergency], "decisions": {},
                                           "defiance": [], "resigned": []})
        bases.update_all(self.w)
        self.assertLess(base(self.w, "A")["support"], bases.START - .02)
        self.assertEqual(base(self.w, "A")["last_cost"]["motion"], "M2")

    def test_the_monthly_update_of_the_engine_moves_the_base(self):
        cost_the_vote(self.w, {"A": "yes", "C": "no"})
        agents.update_conditions(self.w)
        self.assertLess(base(self.w, "A")["support"], bases.START)
        self.assertGreater(base(self.w, "C")["support"], bases.START)

    def test_it_reads_the_votes_of_the_month_just_resolved_and_not_older_ones(self):
        cost_the_vote(self.w, {"A": "yes"})
        self.w.month = 1
        bases.update_all(self.w)
        self.assertGreater(base(self.w, "A")["support"], .57)         # only the drift back toward .55

    def test_an_audience_outside_the_base_mix_leaves_the_base_where_it_was(self):
        self.w.member("A").agent_state["base"] = bases.opening("merchants")
        cost_the_vote(self.w, {"A": "yes"})
        bases.update_all(self.w)
        self.assertAlmostEqual(base(self.w, "A")["support"], bases.START + bases.REST_SHARE * (bases.REST - bases.START),
                               places=3)
        self.assertIsNone(base(self.w, "A")["last_cost"])

    def test_with_nothing_to_read_a_base_drifts_back_toward_rest_by_a_twentieth_of_the_gap(self):
        self.w.member("A").agent_state["base"] = dict(bases.opening("veterans"), support=.15)
        bases.update_all(self.w)
        self.assertEqual(base(self.w, "A")["support"], .17)           # .15 + .05 x (.55 - .15)


class TheDisowning(unittest.TestCase):
    def setUp(self):
        self.w = world()
        self.w.member("A").agent_state["base"] = bases.opening("veterans")
        self.approval0 = standing.ensure(self.w, "A")["personal_approval"]
        self.clout0 = self.w.member("A").clout

    def test_repeated_costly_votes_disown_once_with_the_approval_and_clout_hits(self):
        trail = []
        for _ in range(14):
            one_month(self.w, {"A": "yes"})
            trail.append(base(self.w, "A")["support"])
        first = next(i for i, s in enumerate(trail) if s < bases.DISOWN)
        events = disown_events(self.w)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["text"], "The Veterans of the Winter War league has disowned Delegate A.")
        self.assertEqual(events[0]["importance"], 2)
        self.assertEqual(events[0]["member"], "A")
        self.assertTrue(base(self.w, "A")["disowned"])
        self.assertEqual(base(self.w, "A")["disowned_month"], first)
        # The disowning costs .03 of approval at once and .1 of clout; every uneasy month costs .005 of approval.
        uneasy_months = sum(1 for s in trail if s < bases.UNEASY)
        self.assertAlmostEqual(standing.ensure(self.w, "A")["personal_approval"],
                               self.approval0 - bases.UNEASY_APPROVAL * uneasy_months - bases.DISOWN_APPROVAL, places=3)
        self.assertAlmostEqual(self.w.member("A").clout, self.clout0 - bases.DISOWN_CLOUT, places=3)
        self.assertEqual(self.w.member("A").status, "active")          # the base never removes a delegate

    def test_an_uneasy_base_slips_the_approval_each_month_but_disowns_nobody(self):
        self.w.member("A").agent_state["base"] = dict(bases.opening("veterans"), support=.35)
        for _ in range(3):
            bases.update_all(self.w)
            self.w.month += 1
        self.assertGreaterEqual(base(self.w, "A")["support"], .35)
        self.assertLess(base(self.w, "A")["support"], bases.UNEASY)
        self.assertAlmostEqual(standing.ensure(self.w, "A")["personal_approval"], .5 - 3 * bases.UNEASY_APPROVAL, places=3)
        self.assertEqual(disown_events(self.w), [])
        self.assertEqual(self.w.member("A").clout, self.clout0)

    def test_recovering_above_uneasy_clears_the_disowning_and_a_later_fall_disowns_again(self):
        for _ in range(14):
            one_month(self.w, {"A": "yes"})
        self.assertTrue(base(self.w, "A")["disowned"])
        base(self.w, "A")["support"] = .45
        bases.update_all(self.w)                                      # nothing to read: drifts up past UNEASY
        self.assertFalse(base(self.w, "A")["disowned"])
        self.assertEqual(bases.mood(base(self.w, "A")), "steady")
        self.w.month += 1
        for _ in range(14):
            one_month(self.w, {"A": "yes"})
        self.assertEqual(len(disown_events(self.w)), 2)

    def test_the_mood_and_the_disowned_flag_persist_through_a_save_and_load(self):
        for _ in range(14):
            one_month(self.w, {"A": "yes"})
        data = json.loads(json.dumps(self.w.to_dict()))
        loaded = World.from_dict(data)
        self.assertEqual(loaded.member("A").agent_state["base"], self.w.member("A").agent_state["base"])
        self.assertEqual(loaded.member("A").agent_state["biography"], self.w.member("A").agent_state["biography"])


class TheOldCheckpoints(unittest.TestCase):
    def test_a_delegate_from_an_older_run_is_not_given_a_past_or_a_base(self):
        w = new_world(1, 36)
        for m in w.members:
            del m.agent_state["biography"]
            del m.agent_state["base"]
        agents.ensure(w)
        self.assertFalse(any(k in m.agent_state for m in w.members for k in NEW_KEYS))

    def test_an_older_run_keeps_its_monthly_update_without_a_base(self):
        w = world()
        for m in w.members:
            m.agent_state.pop("biography", None)
            m.agent_state.pop("base", None)
        cost_the_vote(w, {"A": "yes"})
        agents.update_conditions(w)                                   # the monthly update runs as before
        self.assertTrue(all(not any(k in m.agent_state for k in NEW_KEYS) for m in w.members))
        self.assertEqual(disown_events(w), [])

    def test_a_saved_run_loads_with_its_past_and_base_intact(self):
        w = new_world(3, 36)
        loaded = World.from_dict(json.loads(json.dumps(w.to_dict())))
        for m in w.members:
            self.assertEqual(loaded.member(m.id).agent_state["biography"], m.agent_state["biography"])
            self.assertEqual(loaded.member(m.id).agent_state["base"], m.agent_state["base"])


class TheScorecardBase(unittest.TestCase):
    def test_a_delegate_without_a_base_has_empty_figures(self):
        self.assertEqual(bases.scorecard({}), {"id": "", "support_final": None, "disowned_month": None})

    def test_a_delegates_base_is_summarised_as_the_scorecard_names_it(self):
        state = {"base": dict(bases.opening("farmers"), support=.4, disowned_month=5)}
        self.assertEqual(bases.scorecard(state), {"id": "farmers", "support_final": .4, "disowned_month": 5})


class AScriptedRun(unittest.TestCase):
    """Three months through the council: every delegate keeps its past and base, the prompts carry them, and the
    scorecard reports each base."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-engine18-people-")
        cls.path = new_run(os.path.join(ROOT, "council.scripted.toml"), runs_dir=cls.tmp, name="e18p", months=3,
                           quiet=True)
        cls.world = RunStore(cls.path).load_checkpoint()[0]
        cls.card = scorecard.compute(RunStore(cls.path))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_delegate_keeps_its_past_and_its_base(self):
        for m in self.world.members:
            self.assertIn(m.agent_state["biography"]["id"], biographies.BY_ID, m.id)
            self.assertIn(m.agent_state["base"]["id"], bases.BASES, m.id)

    def test_every_monthly_prompt_has_the_past_and_the_base(self):
        with open(os.path.join(self.path, "prompts.jsonl"), encoding="utf-8") as f:
            prompts = [json.loads(line) for line in f]
        monthly = [p for p in prompts if p.get("phase") in ("session", "decision")]
        self.assertTrue(monthly)
        self.assertTrue(all("YOUR PAST: " in p["prompt"] and "YOUR BASE: " in p["prompt"] for p in monthly))

    def test_the_scorecard_carries_each_base(self):
        for letter, member in self.card["members"].items():
            with self.subTest(member=letter):
                state = self.world.member(letter).agent_state
                self.assertEqual(member["base"]["id"], state["base"]["id"])
                self.assertEqual(member["base"]["support_final"], state["base"]["support"])
                self.assertIsNone(member["base"]["disowned_month"])


class TheCatalogue(unittest.TestCase):
    def test_every_audience_a_base_reads_is_one_the_vote_table_names(self):
        named = {audience for _, audiences in standing.ACTION_EFFECTS.values() for audience in audiences}
        for name, spec in bases.BASES.items():
            with self.subTest(base=name):
                self.assertTrue(set(spec["mix"]) <= named, set(spec["mix"]) - named)
                self.assertAlmostEqual(sum(spec["mix"].values()), 1.0, places=9)


if __name__ == "__main__":
    unittest.main()
