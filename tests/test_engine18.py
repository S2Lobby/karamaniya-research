"""World engine 18, agent prompt 15 and psychology 7: what the merge of the engine-18 features added.

The features have their own modules (test_engine18_resolve, _reading, _baselines, _opposition, _plots, _people,
_attribution, _calibration, _ballot, _embargo). These are the pieces that join them: the versions, a scripted run in
which every new part reaches the prompt it was made for, and a secret-ballot run in which the base cannot see a vote.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import versions  # noqa: E402
from karamaniya.config import load_config, normalize_config  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402

CONFIG = os.path.join(ROOT, "council.scripted.toml")
# The monthly prompts carry the private disposition; the founding diagnosis and the formation prompts never have.
MONTHLY = ("session", "decision", "revision")


def scripted_cfg(**run):
    cfg = load_config(CONFIG)
    raw = {"run": {**cfg["run"], "survey": False, "baseline": False, **run}, "seat": cfg["seats"]}
    return normalize_config(raw, "test")


def play(months: int = 4, **run):
    """A scripted run of `months`, its world and every prompt it sent."""
    tmp = tempfile.mkdtemp(prefix="karamaniya-e18-")
    try:
        path = new_run(scripted_cfg(**run), runs_dir=tmp, name="run", months=months, quiet=True, check=False)
        w = RunStore(path).load_checkpoint()[0]
        with open(os.path.join(path, "prompts.jsonl"), encoding="utf-8") as f:
            prompts = [json.loads(line) for line in f]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return w, prompts


def text(prompt: dict) -> str:
    return json.dumps(prompt, ensure_ascii=False)


class Versions(unittest.TestCase):
    def test_the_bump(self):
        self.assertGreaterEqual((versions.WORLD_ENGINE, versions.AGENT_PROMPT, versions.PSYCHOLOGY), (18, 15, 7))


class EveryPartReachesItsPrompt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w, cls.prompts = play(4)
        cls.delegate = [p for p in cls.prompts if p.get("member") in {m.id for m in cls.w.members}
                        and p.get("phase") in MONTHLY]
        cls.cabinet = [p for p in cls.prompts if p.get("actor") in ("veleria", "dorsania")]

    def test_every_delegate_reads_its_past_and_its_base(self):
        for m in self.w.members:
            mine = [text(p) for p in self.delegate if p.get("member") == m.id]
            self.assertTrue(mine, m.id)
            self.assertTrue(all("YOUR PAST:" in t and "YOUR BASE:" in t for t in mine), m.id)

    def test_only_the_head_reads_the_cables_on_how_veleria_reads_karamaniya(self):
        head = self.w.const.offices["head"]
        with_cable = {p.get("member") for p in self.delegate if "Diplomatic cables: Veleria's government reads" in text(p)}
        self.assertEqual(with_cable, {head})

    def test_the_cabinets_see_how_firm_karamaniya_looks(self):
        self.assertTrue(self.cabinet)
        for p in self.cabinet:
            t = text(p)
            self.assertIn("karamaniya_as_you_see_it.resolve", t)
            self.assertRegex(t, r'\\"reading\\": \\"(firm|uncertain|wavering|yielding)\\"')

    def test_the_opposition_is_heard_the_month_after_it_spoke(self):
        said = (self.w.institutions.get("opposition") or {}).get("said", [])
        spoke = sorted({x["month"] for x in said})
        self.assertTrue(spoke, "the opposition said nothing in four scripted months")
        heard = {p.get("month") for p in self.delegate if "The opposition last month:" in text(p)}
        for month in spoke:
            if month + 1 < 4:
                self.assertIn(month + 1, heard)
        self.assertNotIn(0, heard)

    def test_an_open_run_says_nothing_of_a_secret_ballot(self):
        self.assertFalse([p for p in self.prompts if "Votes are secret" in text(p)])


class ASecretBallot(unittest.TestCase):
    def test_the_base_line_says_it_cannot_see_the_votes_and_no_base_moves_by_a_vote(self):
        w, prompts = play(3, ballot="secret")
        delegate = [text(p) for p in prompts if p.get("member") in {m.id for m in w.members}
                    and p.get("phase") in MONTHLY]
        self.assertTrue(delegate)
        self.assertTrue(all("votes are secret, so it cannot see yours" in t for t in delegate))
        self.assertFalse(any("it watches your votes" in t for t in delegate))
        for m in w.members:
            self.assertEqual((m.agent_state.get("base") or {}).get("votes", []), [], m.id)


if __name__ == "__main__":
    unittest.main()
