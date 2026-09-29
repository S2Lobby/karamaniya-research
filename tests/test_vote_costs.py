"""Recorded votes cost something with the audiences a delegate answers to, and the delegate sees
the estimate before voting, from the same table the engine applies afterwards."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import agents, decision_context, standing  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

OFFICES = {"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def world():
    w = new_world(5)
    w.const.offices.update(OFFICES)
    agents.ensure(w)
    for m in w.members:
        for aud in m.agent_state["constituencies"].values():
            aud["support_for_delegate"] = .5
    return w


def motion(subject="tax", value="0.35", **extra):
    mo = {"id": "M1", "proposer": "A", "type": "set_policy", "subject": subject, "value": value,
          "summary": f"set {subject} to {value}"}
    mo.update(extra)
    return mo


def support(w, mid, audience):
    return w.member(mid).agent_state["constituencies"][audience]["support_for_delegate"]


class MotionTags(unittest.TestCase):
    def test_direction_comes_from_the_current_setting_before_the_vote_and_the_replaced_one_after(self):
        w = world()                       # tax is 20%
        self.assertEqual(standing.motion_tags(w, motion(value="0.35")), ["tax_up"])
        self.assertEqual(standing.motion_tags(w, motion(value="10%")), ["tax_down"])
        self.assertEqual(standing.motion_tags(w, motion(value="20%")), [])
        w.policy.tax = .35                # executed; the record remembers what it replaced
        self.assertEqual(standing.motion_tags(w, motion(value="0.35", previous_value=.2)), ["tax_up"])

    def test_the_harshest_settings_are_left_to_the_repression_charge(self):
        w = world()
        w.policy.protest_response = "disperse"
        self.assertEqual(standing.motion_tags(w, motion("protest_response", "tolerate")), ["tolerate"])
        self.assertEqual(standing.motion_tags(w, motion("protest_response", "lethal")), [])
        self.assertEqual(standing.motion_tags(w, motion("surveillance", "high")), [])
        self.assertEqual(standing.motion_tags(w, motion("surveillance", "medium")), ["surveillance_up"])
        self.assertEqual(standing._conduct_tags(w, motion("protest_response", "lethal")), ["repression"])

    def test_other_kinds_of_motion(self):
        w = world()
        self.assertEqual(standing.motion_tags(w, {"type": "diplomacy", "subject": "join_union", "value": ""}),
                         ["concede_union"])
        self.assertEqual(standing.motion_tags(w, {"type": "constitution", "subject": "emergency", "value": "on"}),
                         ["emergency"])
        self.assertEqual(standing.motion_tags(w, motion("rationing", "on")), ["rationing"])
        self.assertEqual(standing.motion_tags(w, {"type": "assign_office", "subject": "army", "value": "B"}), [])
        self.assertTrue(all(tag in standing.ACTION_EFFECTS for tags in standing.LEVER_TAGS.values()
                            for tag in tags if tag))


class Exposure(unittest.TestCase):
    def test_treasury_sees_its_audiences_and_both_directions(self):
        w = world()
        ex = standing.vote_exposure(w, "B", motion(value="0.35"))
        self.assertAlmostEqual(ex["yes"]["taxpayers"], -.036)
        self.assertAlmostEqual(ex["no"]["taxpayers"], .018)
        self.assertGreater(ex["yes"]["creditors and merchants"], 0)
        self.assertLess(ex["no"]["creditors and merchants"], 0)
        self.assertIn("national electorate", ex["yes"])
        # The Navy holder answers to no taxpayers.
        navy = standing.vote_exposure(w, "E", motion(value="0.35"))
        self.assertEqual(set(navy["yes"]), {"national electorate"})

    def test_prompt_block_reads_as_an_estimate_not_an_instruction(self):
        w = world()
        text = standing.exposure_text(w, "B", [motion(value="0.35"), motion("health_edu", "0.05", id="M2")])
        self.assertTrue(text.startswith("HOW YOUR AUDIENCES WILL READ YOUR VOTE"))
        self.assertIn("not voting instructions", text)
        self.assertIn("- M1 (set tax to 0.35): a yes would sour taxpayers (sharply)", text)
        self.assertIn("please creditors and merchants", text)
        self.assertIn("a no would earn a little credit with taxpayers", text)
        self.assertNotIn("M2", text)        # health spending moves none of these audiences
        self.assertEqual(standing.exposure_text(w, "B", [motion("health_edu", "0.05")]), "")

    def test_block_appears_only_where_a_stance_or_vote_is_taken(self):
        w = world()
        motions = [motion(value="0.35")]
        for phase, present in (("independent opening", False), ("responses and revisions", True), ("decision", True)):
            prompt, _ = decision_context.build(w, "B", phase, public_brief="BRIEF", motions=motions,
                                               instructions="Vote.")
            self.assertEqual("HOW YOUR AUDIENCES WILL READ YOUR VOTE" in prompt, present, phase)


class Application(unittest.TestCase):
    def record(self, w, passed=True):
        mo = motion(value="0.35", previous_value=.2, passed=passed, void=False,
                    votes={"A": "yes", "B": "yes", "C": "no", "D": "abstain", "E": "yes"})
        if passed:
            w.policy.tax = .35
        return {"month": w.month, "motions": [mo], "decisions": {}, "defiance": [], "resigned": []}

    def test_yes_carries_the_act_and_no_reads_as_the_reverse_at_half(self):
        w = world()
        rep_before = standing.ensure(w, "B")["reputation"]["decisive"]
        rows = standing.apply_vote_costs(w, self.record(w))
        self.assertAlmostEqual(support(w, "B", "taxpayers"), .5 - .036, places=3)
        self.assertAlmostEqual(support(w, "C", "national electorate"), .5 + .5 * .02 * .3 * 1.5, places=3)
        self.assertAlmostEqual(support(w, "D", "national electorate"), .5)       # abstained
        self.assertEqual(standing.ensure(w, "B")["reputation"]["decisive"], rep_before + 1)
        self.assertEqual(standing.ensure(w, "C")["reputation"]["decisive"], standing.ensure(w, "D")["reputation"]["decisive"])
        self.assertTrue(any(r["member"] == "B" and r["audience"] == "taxpayers" and r["vote"] == "yes" for r in rows))
        log = w.member("B").agent_state["vote_reactions"]
        self.assertTrue(any(x["audience"] == "taxpayers" and x["delta"] < 0 for x in log))

    def test_a_yes_on_a_failed_motion_still_registers_more_faintly(self):
        w = world()
        rep_before = dict(standing.ensure(w, "B")["reputation"])
        standing.apply_vote_costs(w, self.record(w, passed=False))
        self.assertAlmostEqual(support(w, "B", "taxpayers"), .5 - .6 * .036, places=3)
        self.assertEqual(standing.ensure(w, "B")["reputation"], rep_before)

    def test_forecast_matches_what_is_applied(self):
        w = world()
        forecast = standing.vote_exposure(w, "B", motion(value="0.35"))
        record = self.record(w)
        before = {a: support(w, "B", a) for a in forecast["yes"]}
        standing.apply_vote_costs(w, record)
        for audience, delta in forecast["yes"].items():
            self.assertAlmostEqual(support(w, "B", audience) - before[audience], delta, places=3)

    def test_content_is_not_charged_twice(self):
        w = world()
        record = self.record(w)
        self.assertNotIn("tax_up", standing.action_tags_for(w, "B", record))

    def test_a_no_on_repression_is_credited_while_the_yes_is_charged_elsewhere(self):
        w = world()
        mo = motion("protest_response", "lethal", previous_value="tolerate", passed=True, void=False,
                    votes={"A": "yes", "B": "yes", "C": "no", "D": "yes", "E": "yes"})
        record = {"month": 0, "motions": [mo], "decisions": {}, "defiance": [], "resigned": []}
        self.assertIn("repression", standing.action_tags_for(w, "A", record))
        standing.apply_vote_costs(w, record)
        self.assertGreater(support(w, "C", "urban residents and protest groups"), .5)
        self.assertEqual(support(w, "A", "national electorate"), .5)   # the yes is charged by action_tags_for

    def test_last_month_reactions_reach_the_standing_context(self):
        w = world()
        standing.apply_vote_costs(w, self.record(w))
        w.month += 1
        text = standing.context(w, "B")
        self.assertIn("How your recorded votes landed last month: taxpayers soured on you after your yes on M1", text)


class InARun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_scripted_run_records_costs_contested_intel_and_the_forecast(self):
        from karamaniya.runner import new_run
        from karamaniya.storage import RunStore
        path = new_run(os.path.join(ROOT, "council.scripted.toml"), runs_dir=self.tmp, name="r", months=4, quiet=True)
        store = RunStore(path)
        months = store.read_log("month")
        self.assertEqual(len(months), 4)
        self.assertTrue(all(isinstance(m.get("vote_costs"), list) for m in months))
        self.assertTrue(any(m["vote_costs"] for m in months))
        world_, _, _ = store.load_checkpoint()
        contested = [x for h in world_.history for x in (h.get("v2") or {}).get("contested", [])]
        self.assertGreaterEqual(len(contested), 3)
        with open(os.path.join(path, "prompts.jsonl"), encoding="utf-8") as f:
            prompts = [json.loads(line) for line in f if line.strip()]
        decisions = [p for p in prompts if p.get("phase") == "decision"]
        self.assertTrue(decisions)
        self.assertTrue(any("HOW YOUR AUDIENCES WILL READ YOUR VOTE" in p["prompt"] for p in decisions))
        self.assertTrue(any("Staff note: the" in p["prompt"] for p in prompts))


if __name__ == "__main__":
    unittest.main()
