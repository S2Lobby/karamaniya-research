"""Engine 19: the delegates' relationships, promises, reputation and bases (audit AG1-AG12, docs/AUDIT_ENGINE18.md).

Each class is one audit finding. The tests drive the engine's own functions on a seeded world, with no model and no
network, and each one fails on the engine-18 code it describes.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import agents, bases, commitments, memory, standing  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

NO_VOTES = {"motions": [], "defiance": [], "coups": []}
CONFIG = os.path.join(ROOT, "council.scripted.toml")
SETTINGS_WITH_ONE_OFF_LOSSES = ("tax", "military", "price_controls", "rationing", "requisition")


def scripted_cfg(seed: int = 1):
    cfg = load_config(CONFIG)
    raw = {"run": {**cfg["run"], "survey": False, "baseline": False, "seed": seed}, "seat": cfg["seats"]}
    return normalize_config(raw, "test")


def world(seed: int = 1):
    w = new_world(seed, 36)
    agents.ensure(w)
    return w


def massage_motion(**extra):
    """A passed motion to massage the published statistics, as a set_policy motion (the engine's stats lever)."""
    mo = {"id": "M9", "type": "set_policy", "subject": "stats", "value": "massaged", "previous_value": "honest",
          "proposer": "B", "passed": True, "void": False, "summary": "massage the published statistics",
          "votes": {"A": "yes", "B": "yes", "C": "yes"}}
    mo.update(extra)
    return mo


class AG1RelationshipChangesKeepTheirSize(unittest.TestCase):
    """Audit AG1: each change was rounded to 0.1, so decay stopped at a floor and routine votes built nothing."""

    def test_monthly_decay_is_not_stopped_by_rounding(self):
        w = world()
        rel = w.member("A").relationships["B"]
        rel["resentment"], rel["fear"] = 1.0, 5.0
        for _ in range(36):
            agents._relationships(w, NO_VOTES)
        self.assertAlmostEqual(rel["resentment"], 1.0 * 0.985 ** 36, places=6)
        self.assertAlmostEqual(rel["fear"], 5.0 * 0.99 ** 36, places=6)

    def test_twelve_routine_yes_votes_build_trust_respect_and_affinity(self):
        w = world()
        a, b = w.member("A").relationships["B"], w.member("B").relationships["A"]
        for rel in (a, b):
            rel["trust"], rel["respect"], rel["ideological_affinity"] = 50.0, 50.0, 60.0
        routine = {"motions": [{"id": "MX", "proposer": "A", "passed": True, "void": False,
                                "votes": {"A": "yes", "B": "yes"}}], "defiance": [], "coups": []}
        for _ in range(12):
            agents._relationships(w, routine)
        self.assertAlmostEqual(a["trust"], 50.0 + 12 * .08, places=6)
        self.assertAlmostEqual(a["respect"], 50.0 + 12 * .04, places=6)
        self.assertAlmostEqual(a["ideological_affinity"], 60.0 + 12 * .08 * .18, places=6)

    def test_a_small_change_is_stored_exactly(self):
        rel = {"trust": 50.0, "respect": 50.0}
        agents._change(rel, trust=0.04, respect=-0.04)
        self.assertAlmostEqual(rel["trust"], 50.04, places=9)
        self.assertAlmostEqual(rel["respect"], 49.96, places=9)


class AG2MassagingTheStatisticsIsDishonesty(unittest.TestCase):
    """Audit AG2: a yes vote to massage the statistics was tagged repression, so the honest reputation never moved; as an
    order it was not charged at all, because action_tags_for does not emit dishonesty."""

    def test_dishonesty_is_an_effect_the_audiences_are_charged(self):
        self.assertIn("dishonesty", standing.ACTION_EFFECTS)

    def test_a_yes_vote_to_massage_the_statistics_is_tagged_dishonesty_not_repression(self):
        w = world()
        record = {"motions": [massage_motion()], "decisions": {}, "pre_resolution": {"election_month": -1}}
        self.assertEqual(sorted(agents._action_tags(record, "A")), ["dishonesty"])
        self.assertEqual(standing.action_tags_for(w, "A", record), ["dishonesty"])

    def test_a_yes_vote_on_it_lowers_the_honest_reputation_as_it_is_charged(self):
        w = world()
        record = {"motions": [massage_motion()], "decisions": {}, "pre_resolution": {"election_month": -1}}
        for tag in standing.action_tags_for(w, "A", record):
            standing.reputation_effect(w, "A", tag)
        self.assertEqual(standing.ensure(w, "A")["reputation"]["honest"], 50.0 - 8)

    def test_an_order_to_massage_the_statistics_is_charged_as_dishonesty(self):
        w = world()
        record = {"motions": [], "decisions": {"A": {"orders": {"treasury": {"stats": "massaged"}}}},
                  "pre_resolution": {"election_month": -1}}
        self.assertEqual(standing.action_tags_for(w, "A", record), ["dishonesty"])

    def test_under_a_secret_ballot_the_vote_is_not_read_but_the_order_still_is(self):
        w = world()
        w.ballot = "secret"
        vote = {"motions": [massage_motion()], "decisions": {}, "pre_resolution": {"election_month": -1}}
        order = {"motions": [], "decisions": {"A": {"orders": {"treasury": {"stats": "massaged"}}}},
                 "pre_resolution": {"election_month": -1}}
        self.assertEqual(standing.action_tags_for(w, "A", vote), [])
        self.assertEqual(standing.action_tags_for(w, "A", order), ["dishonesty"])


class AG11ALeverChangesOnlyWhenItMoves(unittest.TestCase):
    """Audit AG11: changed_levers held every ordered lever at its current value, so the arms and grain losses fired every
    month a delegate repeated a setting. Here a six-month scripted run records what each month's implementation step is
    given, and every lever it names must have moved since the month before."""

    def test_a_lever_named_as_changed_has_moved_since_the_month_before(self):
        seen = []
        real = standing.implementation_effects

        def record(w, changed):
            seen.append((w.month, dict(changed or {}), {k: getattr(w.policy, k, None) for k in SETTINGS_WITH_ONE_OFF_LOSSES}))
            return real(w, changed)

        tmp = tempfile.mkdtemp(prefix="karamaniya-engine19-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with mock.patch.object(standing, "implementation_effects", record):
            new_run(scripted_cfg(), runs_dir=tmp, name="ag11", months=6, quiet=True, check=False)
        self.assertGreaterEqual(len(seen), 5)
        for (_, _, before), (month, changed, now) in zip(seen, seen[1:]):
            moved = {lever for lever in SETTINGS_WITH_ONE_OFF_LOSSES if now[lever] != before[lever]}
            named = {lever for lever in changed if lever in SETTINGS_WITH_ONE_OFF_LOSSES}
            self.assertEqual(named, moved, f"month {month}: named as changed {sorted(named)}, moved {sorted(moved)}")


class AG12ABaseReadsTheConductOfAYesVote(unittest.TestCase):
    """Audit AG12: the audiences take a yes vote's conduct (here an election delay) through standing.action_tags_for, but
    the delegate's base never read it, so the Charter founders' base did not register a yes that postponed the election."""

    def election_delay_vote(self, vote: str):
        return {"motions": [{"id": "M4", "proposer": "C", "type": "constitution", "subject": "election_month", "value": "none",
                             "summary": "suspend the election", "passed": True, "void": False, "withdrawn": False,
                             "votes": {"C": vote, "A": "no"}}],
                "decisions": {}, "defiance": [], "coups": [],
                "pre_resolution": {"election_month": 30}}

    def test_a_yes_vote_that_delays_the_election_is_noted_by_the_base(self):
        w = world()
        w.member("C").agent_state["base"] = bases.opening("lawyers")
        rows = standing.apply_vote_costs(w, self.election_delay_vote("yes"))
        self.assertEqual([r for r in rows if r["member"] == "C"], [])            # the audiences' own reading is unchanged
        noted = w.member("C").agent_state["base"].get("votes", [])
        self.assertEqual(len(noted), 1)
        # The Charter founders' mix (national electorate .5, coalition partners .3, civil service .2) through the
        # election_delay table (national electorate -1.5, coalition partners -.6) at the yes vote's full strength:
        # .02 x (.5 x -1.5 + .3 x -.6) = -0.0186.
        self.assertAlmostEqual(noted[0]["effect"], -0.0186, places=4)

    def test_the_base_moves_on_it_at_the_monthly_update(self):
        w = world()
        base = w.member("C").agent_state["base"] = bases.opening("lawyers")
        standing.apply_vote_costs(w, self.election_delay_vote("yes"))
        bases.update_all(w)
        # START .6 + BASE_SCALE 1.5 x -0.0186 = .5721, then REST_SHARE .05 of the gap to REST .55 closes: .571.
        self.assertAlmostEqual(base["support"], 0.571, places=3)

    def test_under_a_secret_ballot_no_base_notes_it(self):
        w = world()
        w.ballot = "secret"
        w.member("C").agent_state["base"] = bases.opening("lawyers")
        standing.apply_vote_costs(w, self.election_delay_vote("yes"))
        self.assertEqual(w.member("C").agent_state["base"].get("votes", []), [])


class AG6GrievancesAreListedInAFixedOrder(unittest.TestCase):
    """Audit AG6: the offices a passed programme touched were a set, so the grievances its losing holder took came in an
    order that depended on the hash seed of the process, and so did the prompt that lists the first three."""

    CHILD = """
import sys
sys.path.insert(0, {ROOT})
from karamaniya import agents
from karamaniya.world import new_world
w = new_world(1, 36)
agents.ensure(w)
w.ballot = "open"
w.const.offices.update({"head": "A", "treasury": "B", "interior": "B", "army": "C", "navy": "D"})
b = w.member("B")
b.agent_state["grievances"] = []
record = {"month": w.month, "pre_resolution": {}, "decisions": {}, "motions": [{
    "id": "P1", "type": "program", "proposer": "A", "passed": True, "void": False,
    "summary": "a package of tax and protest measures", "eligible_voters": ["A", "B", "C", "D", "E"],
    "votes": {"A": "yes", "B": "no", "C": "yes", "D": "yes", "E": "yes"},
    "measures": [{"lever": "tax", "value": 0.25}, {"lever": "protest_response", "value": "disperse"}]}]}
agents._political_obligations(w, record)
print(" | ".join(g["reason"] for g in b.agent_state["grievances"]))
"""

    def test_the_grievance_order_is_the_same_under_every_hash_seed(self):
        code = self.CHILD.replace("{ROOT}", repr(ROOT))
        outs = []
        for seed in ("0", "1", "2"):
            done = subprocess.run([sys.executable, "-c", code], env={**os.environ, "PYTHONHASHSEED": seed}, cwd=ROOT,
                                  capture_output=True, text=True, timeout=300)
            self.assertEqual(done.returncode, 0, done.stderr[-500:])
            outs.append(done.stdout.strip().splitlines()[-1])
        self.assertEqual(outs[0], "interior policy enacted over my objection | treasury policy enacted over my objection")
        self.assertEqual(set(outs), {outs[0]})


class AG8ABaseEndsWithItsDelegate(unittest.TestCase):
    """Audit AG8: a base was updated every month, though its delegate had left the council, so the ex-member's approval
    slipped and a public disowning was recorded for a member who was no longer there."""

    def test_the_base_of_a_delegate_who_has_left_is_not_updated(self):
        w = world()
        gone = w.member("C")
        gone.status = "resigned"
        base = gone.agent_state["base"] = bases.opening("officers")
        base["support"] = 0.20
        standing.ensure(w, "C")["personal_approval"] = 0.336
        bases.update_all(w)
        self.assertEqual(base["support"], 0.20)
        self.assertFalse(base.get("disowned"))
        self.assertEqual(standing.ensure(w, "C")["personal_approval"], 0.336)
        self.assertEqual([e for e in w.events if e.get("kind") == "base_disowned"], [])

    def test_an_active_delegates_base_is_still_updated(self):
        w = world()
        base = w.member("A").agent_state["base"] = bases.opening("officers")
        base["support"] = 0.20
        bases.update_all(w)
        self.assertGreater(base["support"], 0.20)


class AG9AnAudienceKeepsItsSupportWhileTheOfficeIsAway(unittest.TestCase):
    """Audit AG9: an audience was rebuilt from its defaults when its office was lost and regained, so a delegate's standing
    with the police service (0.91 support) came back as a new seat at 0.5."""

    def test_an_office_audience_comes_back_with_its_support(self):
        w = world()
        w.const.offices["interior"] = "B"
        agents.ensure(w)
        audience = w.member("B").agent_state["constituencies"]["police service"]
        audience["support_for_delegate"], audience["satisfaction"] = 0.91, 0.22
        w.const.offices["interior"] = "C"
        agents.ensure(w)
        self.assertNotIn("police service", w.member("B").agent_state["constituencies"])   # not read while away
        w.const.offices["interior"] = "B"
        agents.ensure(w)
        audience = w.member("B").agent_state["constituencies"]["police service"]
        self.assertEqual((audience["support_for_delegate"], audience["satisfaction"]), (0.91, 0.22))


class AG10ASecretBallotKeepsNoStand(unittest.TestCase):
    """Audit AG10: a secret ballot keeps no lone dissent (agents.update_political says so), yet memory.record_month wrote a
    'You stood alone' memory for the dissenter under either ballot."""

    def test_a_lone_dissent_is_remembered_only_under_an_open_ballot(self):
        for ballot, expected in (("open", ["minority_stand"]), ("secret", [])):
            w = world()
            w.ballot = ballot
            w.month = 2
            dissent = motion_voted("M1", "a tax change", {"A": "yes", "B": "yes", "C": "yes", "D": "yes", "E": "no"},
                                   proposer="A", eligible_voters=list("ABCDE"))
            memory.record_month(w, {"month": 2, "motions": [dissent], "decisions": {}})
            stands = [x["kind"] for x in w.member("E").agent_state.get("memory", []) if x["kind"] == "minority_stand"]
            self.assertEqual(stands, expected, ballot)


def vote_record(*motions):
    return {"motions": list(motions), "decisions": {}, "defiance": [], "coups": []}


def motion_voted(mid, summary, votes, **extra):
    mo = {"id": mid, "proposer": "B", "type": "set_policy", "subject": "tax", "value": "0.2", "summary": summary,
          "passed": True, "void": False, "withdrawn": False, "votes": votes}
    mo.update(extra)
    return mo


class AG3PromisesAreJudgedInTheMonthTheyAreMade(unittest.TestCase):
    """Audit AG3: a statement promise was skipped in the month it was made (commitments.evaluate), so a same-month broken
    pledge was never recorded; a pledge naming a motion id was never judged; and a topic pledge was judged later
    against an unrelated motion with the same word."""

    def test_a_statement_promise_broken_by_the_same_months_vote_is_broken_that_month(self):
        w = world()
        w.month = 2
        promise = commitments.record(w, "A", "I will vote for the budget motion.", to="public")
        results = commitments.evaluate(w, vote_record(motion_voted("M1", "the budget motion", {"A": "no", "B": "yes"})))
        self.assertEqual([r["verdict"] for r in results], ["broken"])
        self.assertEqual(promise["status"], "broken")

    def test_a_pledge_naming_a_motion_id_is_judged_on_that_motion_in_its_month(self):
        w = world()
        w.month = 2
        promise = commitments.record(w, "C", "I will vote for motion M1.", to="public")
        results = commitments.evaluate(w, vote_record(
            motion_voted("M1", "a tax change", {"C": "no", "B": "yes"}),
            motion_voted("M2", "a second tax change", {"C": "yes", "B": "yes"})))
        self.assertEqual([r["verdict"] for r in results], ["broken"])
        self.assertEqual(promise["status"], "broken")

    def test_a_topic_pledge_is_not_judged_on_a_later_motion_with_the_same_word(self):
        w = world()
        w.month = 2
        promise = commitments.record(w, "D", "I will vote for the budget motion.", to="public")
        w.month = 3
        results = commitments.evaluate(w, vote_record(
            motion_voted("M7", "a budget motion for the next year", {"D": "no", "B": "yes"})))
        self.assertEqual(results, [])
        self.assertEqual(promise["status"], "active")


class AG4APublicOrderIsJudgedUnderASecretBallot(unittest.TestCase):
    """Audit AG4: under a secret ballot a promise to fund, raise, cut or limit a policy was not judged at all, so a public
    office order that broke it was never recorded. Only the part that reads votes is hidden."""

    def fund_promise(self, ballot: str, **extra):
        w = world()
        w.ballot = ballot
        w.month = 2
        promise = commitments.record(w, "A", "I will increase the military budget.", to="B", source="dm",
                                     kind="promise", **extra)
        return w, promise

    def test_an_order_contrary_to_a_fund_promise_is_broken_under_both_ballots(self):
        for ballot in ("open", "secret"):
            w, promise = self.fund_promise(ballot)
            halved = str(w.policy.military / 2)
            results = commitments.evaluate(w, {"motions": [], "decisions": {
                "A": {"orders": {"treasury": {"military": halved}}}}})
            self.assertEqual([r["verdict"] for r in results], ["broken"], ballot)
            self.assertEqual(promise["status"], "broken", ballot)

    def test_a_vote_for_a_fund_promise_is_judged_only_when_the_ballot_is_open(self):
        vote = motion_voted("M1", "raise the military budget", {"A": "yes", "B": "yes"}, subject="military",
                            value="0.05", previous_value=0.03)
        for ballot, verdicts in (("open", ["kept"]), ("secret", [])):
            w, promise = self.fund_promise(ballot)
            results = commitments.evaluate(w, vote_record(vote))
            self.assertEqual([r["verdict"] for r in results], verdicts, ballot)

    def test_a_deadline_is_not_a_verdict_on_votes_nobody_can_see(self):
        for ballot, verdicts in (("open", ["broken"]), ("secret", [])):
            w, promise = self.fund_promise(ballot, deadline_month=3)
            w.month = 3
            results = commitments.evaluate(w, {"motions": [], "decisions": {}})
            self.assertEqual([r["verdict"] for r in results], verdicts, ballot)


if __name__ == "__main__":
    unittest.main()
