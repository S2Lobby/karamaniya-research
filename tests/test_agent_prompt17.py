"""Agent prompt 17: a delegate asked to act on its own appointment or principles is told which delegate it is.

The formation proposal and vote, and the request to restate a declaration of principles that duplicated another
delegate's, did not say it. In run 20261011-094417-seed1 Claude Haiku 5.5, voting on sixteen slates and appointments
with its own among them, spent part of its reasoning guessing which nominee it was, and voted for the broadest consensus
because it could not tell which slate was in its own interest. The session, revision and decision prompts said it
already. The seats are the engine's scripted stand-ins, so nothing here calls a model.
"""
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import versions  # noqa: E402
from karamaniya.backends import CallResult  # noqa: E402
from karamaniya.backends.scripted import ScriptedBackend  # noqa: E402
from karamaniya.world import OFFICE_TITLES  # noqa: E402
from tests.test_engine19_council import scripted_council  # noqa: E402

YOU_ARE = re.compile(r"^YOU ARE (.+)$", re.M)


def recording_backend(prompts: dict):
    """A scripted seat that keeps every prompt it is sent, by phase and member."""
    class Seat(ScriptedBackend):
        def call(self, system, user, schema, context):
            prompts.setdefault((context.get("phase"), context.get("member")), []).append(user)
            return super().call(system, user, schema, context)
    return Seat


class Versions(unittest.TestCase):
    def test_the_bump(self):
        self.assertEqual((versions.WORLD_ENGINE, versions.AGENT_PROMPT, versions.PSYCHOLOGY), (20, 17, 8))


class TheDelegateIsNamed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="prompt17-")
        cls.prompts = {}
        cls.council, cls.w = scripted_council(cls.tmp, recording_backend(cls.prompts))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def named(self, prompt: str) -> list:
        return YOU_ARE.findall(prompt)

    def test_the_formation_proposal_and_vote_say_who_is_asked(self):
        for phase in ("formation_proposal", "formation_vote"):
            for m in self.w.active_members():
                sent = self.prompts.get((phase, m.id))
                self.assertTrue(sent, (phase, m.id))
                for prompt in sent:
                    self.assertEqual(self.named(prompt), [m.name.upper()], (phase, m.id))
                    self.assertIn(f"YOU ARE {m.name.upper()}\nOffice: none", prompt)    # every office is vacant

    def test_a_session_prompt_names_the_delegate_once(self):
        """The role block names the delegate in the session prompts; the new line is not added a second time."""
        self.council.run_month()
        sessions = [(mid, p) for (phase, mid), sent in self.prompts.items() if phase == "session" for p in sent]
        self.assertTrue(sessions)
        for mid, prompt in sessions:
            self.assertEqual(self.named(prompt), [self.w.member(mid).name.upper()], mid)

    def test_a_delegate_restating_its_principles_is_told_who_it_is_and_its_office(self):
        same = "Fair elections on schedule, honest statistics and no force against civilians."
        first, second = (m.id for m in self.w.active_members()[:2])
        opening = [(mid, CallResult(data={"principles": same}), {"principles": same}, []) for mid in (first, second)]
        self.council._repair_duplicate_principles(opening, [])
        sent = self.prompts.get(("principles_repair", second))
        self.assertTrue(sent, "the second, duplicated declaration was asked to be restated")
        holder = self.w.member(second)
        self.assertEqual(self.named(sent[-1]), [holder.name.upper()])
        offices = ", ".join(OFFICE_TITLES[o] for o in self.w.offices_of(second)) or "none"
        self.assertIn(f"YOU ARE {holder.name.upper()}\nOffice: {offices}", sent[-1])


if __name__ == "__main__":
    unittest.main()
