"""The council can direct an office's patronage. The rules text says it can pass directives on any
setting and lists patronage among them; the engine rejected it as an unknown lever. In a real run the
Interior holder tabled it in two months running, to switch off the Army's."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import actions, decision_context, motion_actions, politics, prompts  # noqa: E402
from karamaniya.world import World  # noqa: E402
from tests.test_orders_vs_directives import resolve, world  # noqa: E402

E_TEXT = ("The council directs Army Command to end the army patronage programme. Officers must owe "
          "constitutional loyalty to the state, not personal loyalty to their individual commander. Patronage "
          "that builds the latter rather than the former elevates extraconstitutional risk during any crisis.")


def patronage_motion(subject="patronage_army", value="off", **extra):
    return {"id": "M1", "proposer": "E", "type": "set_policy", "subject": subject, "value": value,
            "text": E_TEXT, "summary": f"directive {subject} = {value}", **extra}


class Naming(unittest.TestCase):
    def test_the_ways_a_delegate_writes_it_reach_one_name(self):
        for written in ("army patronage", "Army_Patronage", "patronage army", "patronage_army"):
            self.assertEqual(politics.patronage_subject(written), "patronage_army", written)
        self.assertEqual(politics.patronage_subject("police patronage"), "patronage_interior")
        self.assertEqual(politics.patronage_subject("navy patronage"), "patronage_navy")
        self.assertEqual(politics.patronage_subject("tax"), "tax")
        self.assertEqual(politics.patronage_subject("patronage"), "patronage")          # which office?

    def test_a_motion_is_normalized_to_the_canonical_subject(self):
        w = world()
        mo = actions.normalize_motion_v2(w, {"type": "set_policy", "subject": "army patronage", "value": "off",
                                             "text": E_TEXT})
        self.assertEqual((mo["type"], mo["subject"], mo["value"]), ("set_policy", "patronage_army", "off"))

    def test_the_orders_schema_still_has_one_patronage_order_and_no_directive_names(self):
        for office in ("army", "navy", "interior"):
            levers = actions._office_levers(office)
            self.assertIn("patronage", levers)
            self.assertFalse([k for k in levers if k.startswith("patronage_")], office)
        self.assertNotIn("patronage", actions._office_levers("treasury"))


class Validation(unittest.TestCase):
    def check(self, w, **kw):
        return politics.validate_motion_detail(w, patronage_motion(**kw))

    def test_a_directive_on_an_armed_offices_patronage_is_valid(self):
        w = world()
        w.policy.patronage["army"] = True
        self.assertIsNone(self.check(w))
        self.assertIsNone(self.check(w, subject="patronage_navy", value="on"))
        self.assertEqual(politics.LEVER_OFFICE["patronage_army"], "army")

    def test_bare_patronage_and_bad_values_are_refused_with_a_way_forward(self):
        w = world()
        bare = self.check(w, subject="patronage")
        self.assertEqual(bare["reason_code"], "UNKNOWN_LEVER")
        self.assertIn("use patronage_army, patronage_navy or patronage_interior", bare["explanation"])
        self.assertEqual(self.check(w, value="maybe")["reason_code"], "BAD_VALUE")

    def test_a_directive_already_in_force_is_refused(self):
        w = world()
        w.policy.patronage["army"] = True
        politics.apply_motion(w, patronage_motion())
        self.assertEqual(self.check(w)["reason_code"], "ALREADY_IN_FORCE")

    def test_the_words_of_the_real_motion_do_not_clash_with_its_action(self):
        w = world()
        w.policy.patronage["army"] = True
        self.assertIsNone(motion_actions.conflict(w, {**patronage_motion(), "action": {}}))


class Effect(unittest.TestCase):
    def test_a_directive_switches_the_flag_and_is_recorded(self):
        w = world()
        w.policy.patronage["army"] = True
        summary = politics.apply_motion(w, patronage_motion())
        self.assertEqual(summary, "council directive: patronage_army = off")
        self.assertFalse(w.policy.patronage["army"])
        self.assertIs(w.const.directives["patronage_army"], False)

    def test_it_survives_a_save_and_load(self):
        w = world()
        w.policy.patronage["army"] = True
        politics.apply_motion(w, patronage_motion())
        again = World.from_dict(w.to_dict())
        self.assertFalse(again.policy.patronage_army)
        self.assertIs(again.const.directives["patronage_army"], False)

    def test_delegates_see_the_current_setting_in_the_motion_block(self):
        w = world()
        w.policy.patronage["army"] = True
        block = decision_context.motion_block(w, "A", [patronage_motion()])
        self.assertIn("patronage_army", block)
        self.assertIn("now True, proposed False; office army", block)


class TheContest(unittest.TestCase):
    """E moves to switch off the Army's patronage; B, who holds the Army and defends it, votes no."""

    def test_the_vote_binds_that_month_and_defying_it_later_is_recorded(self):
        w = world()
        w.policy.patronage["army"] = True
        votes = {"A": "yes", "B": "no", "C": "yes", "D": "yes", "E": "yes"}
        record = resolve(w, patronage_motion(), votes, {"B": {"army": {"patronage": True}}})
        self.assertEqual(record["defiance"], [])                     # B could not know the vote's outcome
        self.assertFalse(w.policy.patronage["army"])                # the council's directive stands
        self.assertEqual([(s["member"], s["lever"], s["order"], s["directive"]) for s in record["superseded_orders"]],
                         [("B", "patronage_army", True, False)])
        self.assertEqual(record["motions"][0]["previous_value"], True)
        # Next month B orders it back on, knowing the directive: that is defiance, and it is recorded.
        w.month += 1
        other = {"id": "M1", "proposer": "A", "type": "set_policy", "subject": "tax", "value": "0.22", "text": "",
                 "summary": "directive tax = 0.22"}
        record = resolve(w, other, dict.fromkeys("ABCDE", "yes"), {"B": {"army": {"patronage": True}}})
        self.assertEqual([(d["member"], d["lever"], d["directive"], d["value"]) for d in record["defiance"]],
                         [("B", "patronage_army", False, True)])
        self.assertTrue(w.policy.patronage["army"])                 # the holder's order still wins, as for any setting
        self.assertTrue(any(e["kind"] == "defiance" and "patronage_army" in e["text"] for e in w.events))

    def test_without_a_directive_the_holders_order_is_all_there_is(self):
        w = world()
        record = resolve(w, {"id": "M1", "proposer": "A", "type": "set_policy", "subject": "tax", "value": "0.22",
                             "text": "", "summary": "directive tax = 0.22"}, dict.fromkeys("ABCDE", "yes"),
                         {"B": {"army": {"patronage": True}}})
        self.assertEqual(record["defiance"], [])
        self.assertTrue(w.policy.patronage["army"])


class TheRulesTextSaysSo(unittest.TestCase):
    def test_new_runs_are_told_the_names(self):
        self.assertIn("patronage_army, patronage_navy or patronage_interior", prompts.system_prompt("simulation", True, 5))

    def test_a_resumed_run_with_an_older_system_prompt_is_told_in_the_opening_instructions(self):
        w = world()
        text = prompts.opening_instructions_v2(w, "E", 2, list("ABCDE"), 4)
        self.assertIn("patronage_army, patronage_navy or patronage_interior", text)


if __name__ == "__main__":
    unittest.main()
