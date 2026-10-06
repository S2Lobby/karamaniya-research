"""A lone dissenter proven right three months on is remembered, and gains a modest name for judgement."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import agents, memory, psychology, standing  # noqa: E402
from karamaniya.engine import step  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

OFFICES = {"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"}


def tax_rise(previous, votes=None, **extra):
    motion = {"id": "M1", "proposer": "A", "type": "set_policy", "subject": "tax", "value": "0.45",
              "summary": "raise the tax rate to 45%", "passed": True, "void": False,
              "votes": votes or {"A": "yes", "B": "no", "C": "yes", "D": "yes", "E": "yes"},
              "eligible_voters": list("ABCDE"), "previous_value": previous, "execution_status": "EXECUTED",
              "tally": "(4 yes, 1 no, 0 abstain)", "vote_reasons": {"B": "It will not pay the bills."}}
    motion.update(extra)
    return motion


def adopt(w, motion):
    """What the council phase does after a vote: execute, then record politics and memory."""
    w.policy.tax = 0.45
    record = {"month": w.month, "motions": [motion], "decisions": {}, "defiance": [], "resigned": [],
              "communications": []}
    agents.update_political(w, record)
    memory.record_month(w, record)


class LoneDissent(unittest.TestCase):
    def test_lone_dissenter_needs_one_no_against_three_or_more_yes(self):
        self.assertEqual(psychology.lone_dissenter(tax_rise(.2)), "B")
        self.assertIsNone(psychology.lone_dissenter(tax_rise(.2, votes={"A": "yes", "B": "no", "C": "no",
                                                                          "D": "yes", "E": "yes"})))
        self.assertIsNone(psychology.lone_dissenter(tax_rise(.2, votes={"A": "yes", "B": "no", "C": "yes",
                                                                          "D": "abstain", "E": "abstain"})))
        self.assertIsNone(psychology.lone_dissenter(tax_rise(.2, passed=False)))
        self.assertIsNone(psychology.lone_dissenter(tax_rise(.2, void=True)))

    def test_direction_reads_rises_and_cuts_for_every_kind_of_lever(self):
        self.assertEqual(psychology.policy_direction("tax", "0.45", .2), 1)
        self.assertEqual(psychology.policy_direction("tax", "15%", .2), -1)
        self.assertEqual(psychology.policy_direction("tax", "20%", .2), 0)
        self.assertEqual(psychology.policy_direction("protest_response", "lethal", "tolerate"), 1)
        self.assertEqual(psychology.policy_direction("rationing", "off", True), -1)
        self.assertEqual(psychology.policy_direction("tax", "0.45", None), 0)

    def test_a_cut_is_judged_on_what_a_cut_is_for(self):
        w = new_world(5)
        w.history = [{"arrears_gdp": .10, "unemployment": .10} for _ in range(3)] + \
                    [{"arrears_gdp": .14, "unemployment": .07}]
        rise = psychology.judge_policy(w, "tax", 2, 1)
        cut = psychology.judge_policy(w, "tax", 2, -1)
        self.assertEqual((rise["verdict"], rise["target"]), ("failed", "unpaid bills"))
        self.assertEqual((cut["verdict"], cut["target"], cut["side"]), ("worked", "unemployment", "unpaid bills"))

    def test_stand_is_recorded_once_and_only_for_an_executed_change(self):
        w = new_world(5)
        w.const.offices.update(OFFICES)
        adopt(w, tax_rise(w.policy.tax))
        stands = w.member("B").agent_state["minority_stands"]
        self.assertEqual(len(stands), 1)
        self.assertEqual((stands[0]["subject"], stands[0]["adopted"], stands[0]["supporters"]),
                         ("tax", .45, ["A", "C", "D", "E"]))
        self.assertIn("will not pay", stands[0]["reason"])
        self.assertTrue(any(x["kind"] == "minority_stand" for x in w.member("B").agent_state["memory"]))
        blocked = new_world(5)
        adopt(blocked, tax_rise(blocked.policy.tax, execution_status="EXECUTION_BLOCKED"))
        self.assertEqual(blocked.member("B").agent_state.get("minority_stands", []), [])

    def test_a_directive_the_office_holder_defied_is_not_a_stand(self):
        w = new_world(5)
        w.const.offices.update(OFFICES)
        previous = w.policy.tax
        record = {"month": w.month, "motions": [tax_rise(previous)], "decisions": {}, "defiance": [],
                  "resigned": [], "communications": []}
        # The Treasury holder kept the old rate by order, so the rise never took effect.
        agents.update_political(w, record)
        self.assertEqual(w.member("B").agent_state.get("minority_stands", []), [])


class Vindication(unittest.TestCase):
    def world_with_stand(self, arrears_after):
        w = new_world(5)
        w.const.offices.update(OFFICES)
        w.month = 3
        adopt(w, tax_rise(.2))
        w.history = [{"arrears_gdp": .10, "unemployment": .08} for _ in range(6)] + \
                    [{"arrears_gdp": arrears_after, "unemployment": .08}]
        w.month = 6
        return w

    def judge(self, w):
        state = w.member("B").agent_state
        judged = psychology.judge_stands(w, "B", state)
        for stand in judged:
            agents._stand_judged(w, "B", stand)
        return judged

    def test_failed_policy_vindicates_the_lone_no(self):
        w = self.world_with_stand(arrears_after=.15)
        before = dict(standing.ensure(w, "B")["reputation"])
        respect = w.member("C").relationships["B"]["respect"]
        judged = self.judge(w)
        self.assertEqual([s["verdict"] for s in judged], ["failed"])
        mem = w.member("B").agent_state["memory"]
        vind = [x for x in mem if x["kind"] == "vindicated"]
        self.assertEqual(len(vind), 1)
        self.assertIn("You stood alone against raise the tax rate to 45% in Month 4", vind[0]["text"])
        self.assertIn("It failed as you warned", vind[0]["text"])
        self.assertTrue(vind[0]["protected"])
        self.assertGreaterEqual(vind[0]["salience"], 60)
        for other in "ACDE":
            self.assertTrue(any(x["kind"] == "ignored_warning" for x in w.member(other).agent_state["memory"]), other)
        after = standing.ensure(w, "B")["reputation"]
        self.assertEqual(after["decisive"] - before["decisive"], 2)
        self.assertEqual(after["strong"] - before["strong"], 1)
        self.assertGreater(w.member("C").relationships["B"]["respect"], respect)
        self.assertEqual(w.analytics["vindications"][-1]["member"], "B")
        # Judged once: a second pass in the same or a later month changes nothing.
        self.assertEqual(self.judge(w), [])
        self.assertEqual(len([x for x in w.member("B").agent_state["memory"] if x["kind"] == "vindicated"]), 1)

    def test_policy_that_worked_is_remembered_quietly_without_reward(self):
        w = self.world_with_stand(arrears_after=.05)
        before = dict(standing.ensure(w, "B")["reputation"])
        judged = self.judge(w)
        self.assertEqual([s["verdict"] for s in judged], ["worked"])
        kinds = {x["kind"] for x in w.member("B").agent_state["memory"]}
        self.assertIn("minority_mistaken", kinds)
        self.assertNotIn("vindicated", kinds)
        self.assertEqual(standing.ensure(w, "B")["reputation"], before)
        self.assertFalse(any(x["kind"] == "ignored_warning" for x in w.member("A").agent_state["memory"]))

    def test_a_reversed_policy_is_not_judged(self):
        w = self.world_with_stand(arrears_after=.15)
        w.policy.tax = .2          # the council undid the rise before its effect could be told
        self.assertEqual(self.judge(w), [])
        self.assertEqual(w.member("B").agent_state["minority_stands"][0]["verdict"], "reversed")
        self.assertFalse(any(x["kind"] == "vindicated" for x in w.member("B").agent_state["memory"]))

    def test_confidence_follows_the_verdict(self):
        w = self.world_with_stand(arrears_after=.15)
        state = w.member("B").agent_state
        self.judge(w)
        state["confidence"] = 55.0
        psychology.update_confidence(w, "B", state, None)
        vindicated = state["confidence"]
        state["confidence"] = 55.0
        for stand in state["minority_stands"]:
            stand["judged_month"] = -1
        psychology.update_confidence(w, "B", state, None)
        self.assertAlmostEqual(vindicated - state["confidence"], 3.0, places=5)


class Wiring(unittest.TestCase):
    def test_monthly_update_judges_a_stand_three_months_later(self):
        w = new_world(9)
        w.const.offices.update(OFFICES)
        agents.ensure(w)
        for _ in range(3):
            step(w)
        self.assertEqual(w.month, 3)
        adopt(w, tax_rise(.2))
        for _ in range(3):
            step(w)
            stand = w.member("B").agent_state["minority_stands"][0]
            self.assertNotIn("verdict", stand)
        step(w)                     # the Month 7 update is three months after adoption in Month 4
        stand = w.member("B").agent_state["minority_stands"][0]
        self.assertEqual(stand["judged_month"], 6)
        self.assertIn(stand["verdict"], ("worked", "failed", "unclear", "reversed"))


if __name__ == "__main__":
    unittest.main()
