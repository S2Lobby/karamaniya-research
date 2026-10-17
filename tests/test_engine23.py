"""World engine 23, agent prompt 20: the review items of engine 22 that its changelog listed and its code did not do.

The office brief, the League credit line, the recruitment pace and the cabinets' refusal notes have their own tests in
the engine 22 files (test_engine22_dispatches, test_engine22_scale, test_engine22_foreign_intake); this file pins the
version and the loose ends of the ultimatum reply.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import actions, errors, foreign, integrity, politics, versions  # noqa: E402
from karamaniya.world import new_world  # noqa: E402


def world():
    w = new_world(11, 36)
    w.foreign = foreign.initial_state(w.seed)
    w.agent_architecture_version = 2
    w.const.offices.update({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"})
    w.month = 6
    return w


def reply(target: str = "DORSANIA", text: str = "Karamaniya rejects Dorsania's ultimatum: equal rights are already "
                                                  "guaranteed by the Charter.") -> dict:
    return {"id": "M1", "type": "diplomacy", "subject": "ultimatum_reply", "value": "", "proposer": "C", "text": text,
            "action": {"action_type": "ultimatum_reply", "target": target, "terms": []}}


def dorsania_ultimatum(w):
    w.dip.ultimatum = {"issued": w.month - 1, "deadline": w.month + 2, "by": "dorsania",
                       "terms": "Guarantee the rights and safety of Imperial citizens in Karamaniya.",
                       "terms_id": "protect_imperial_citizens"}


class Versions(unittest.TestCase):
    def test_the_bump(self):
        self.assertGreaterEqual((versions.WORLD_ENGINE, versions.AGENT_PROMPT, versions.PSYCHOLOGY, versions.ERROR_TAXONOMY),
                                (23, 20, 8, 5))


class TheReplysRefusalsAreRegistered(unittest.TestCase):
    """Engine 22 refused a reply with NO_ULTIMATUM or ULTIMATUM_NOT_FROM_TARGET, codes the taxonomy did not hold, so
    they were recorded as UNREGISTERED_ERROR_CODE."""

    def test_no_ultimatum_is_a_registered_refusal(self):
        w = world()
        problem = politics.validate_motion_detail(w, reply())
        self.assertEqual(problem["reason_code"], "NO_ULTIMATUM")
        self.assertTrue(errors.describe("NO_ULTIMATUM")["registered"])

    def test_a_reply_to_the_wrong_power_is_a_registered_refusal(self):
        w = world()
        dorsania_ultimatum(w)
        # The text names no power, so the words and the action do not disagree; the target alone is wrong.
        problem = politics.validate_motion_detail(w, reply("VELERIA", "Karamaniya rejects the ultimatum."))
        self.assertEqual(problem["reason_code"], "ULTIMATUM_NOT_FROM_TARGET")
        self.assertTrue(errors.describe("ULTIMATUM_NOT_FROM_TARGET")["registered"])
        entry = errors.record(w, problem["reason_code"], problem["explanation"])
        self.assertEqual(entry["code"], "ULTIMATUM_NOT_FROM_TARGET")


class TheReplyIsNamedAndTraced(unittest.TestCase):
    def test_the_motion_title_says_it_answers_the_ultimatum(self):
        # Engine 22 titled it "propose ultimatum reply to Dorsania".
        self.assertEqual(actions.motion_summary(world(), reply()), "answer the ultimatum of Dorsania")

    def test_the_integrity_record_names_the_state_it_touches(self):
        self.assertEqual(integrity.ACTION_EFFECTS["ultimatum_reply"], ("dip.ultimatum",))


if __name__ == "__main__":
    unittest.main()
