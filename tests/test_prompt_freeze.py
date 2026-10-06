"""A run with no token-saving setting sends exactly what engine 5 sent, and a feature that is on changes
only what it says it changes.

tests/fixtures/prompt_freeze_engine5.json holds the sha256 of the system prompt and of every prompt in a
four-month run of council.scripted.toml (seed 1), produced by the published engine-5 code. The
token-saving features in karamaniya/token_saving.py are all off by default; this is the test that holds
them to it. A deliberate prompt change bumps versions.AGENT_PROMPT and regenerates the fixture with
`python tools/prompt_freeze.py --write`.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya.batch import simulate  # noqa: E402
from karamaniya.tokens import fingerprints  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "prompt_freeze_engine5.json")
SCRIPTED = os.path.join(ROOT, "council.scripted.toml")


def scripted_run(tmp: str, months: int, tokens: dict | None = None, prefix: str = "freeze") -> str:
    """A scripted run in `tmp`, optionally with a [run.tokens] table. Returns the run folder."""
    config = SCRIPTED
    if tokens:
        with open(SCRIPTED, encoding="utf-8") as f:
            text = f.read()
        table = ", ".join(f'{k} = {json.dumps(v)}' for k, v in tokens.items())
        text = text.replace("[run]\n", "[run]\ntokens = { " + table + " }\n", 1)
        config = os.path.join(tmp, f"{prefix}.toml")
        with open(config, "w", encoding="utf-8") as f:
            f.write(text)
    simulate(config, runs=1, months=months, first_seed=1, runs_dir=tmp, prefix=prefix, check=False)
    return os.path.join(tmp, f"{prefix}-seed1")


class ADefaultRunIsEngineFive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE, encoding="utf-8") as f:
            cls.expected = json.load(f)
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-freeze-")
        cls.actual = fingerprints(scripted_run(cls.tmp, cls.expected["months"]))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_system_prompt_is_unchanged(self):
        self.assertEqual(self.actual["system_prompt_sha256"], self.expected["system_prompt_sha256"])

    def test_every_prompt_is_unchanged(self):
        expected = [tuple(e) for e in self.expected["prompts"]]
        actual = [tuple(e) for e in self.actual["prompts"]]
        self.assertEqual([e[:4] for e in actual], [e[:4] for e in expected],
                         "the run made a different set of calls")
        changed = [e[:4] for e, a in zip(expected, actual) if e[4] != a[4]]
        self.assertEqual(changed, [], "these prompts differ from engine 5 (month, phase, member, n)")


def _words(text: str) -> list:
    return sorted(w for w in re.findall(r"[a-z0-9]+", text.lower()))


class TheCacheFriendlyLayoutOnlyMovesThings(unittest.TestCase):
    """Same sections, same words, same calls: the layout reorders a prompt and adds nothing to it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-layout-")
        cls.classic = scripted_run(cls.tmp, 3, prefix="classic")
        cls.friendly = scripted_run(cls.tmp, 3, {"layout": "cache_friendly"}, prefix="friendly")

        def load(run):
            rows = [json.loads(line) for line in open(os.path.join(run, "prompts.jsonl"), encoding="utf-8")]
            keyed, counts = {}, {}
            for r in rows:
                key = (r["month"], r["phase"], r.get("member") or r.get("actor"))
                counts[key] = counts.get(key, 0) + 1
                keyed[key + (counts[key],)] = r
            return keyed
        cls.a, cls.b = load(cls.classic), load(cls.friendly)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_same_calls_are_made(self):
        self.assertEqual(sorted(self.a), sorted(self.b))

    def test_the_layout_is_recorded_with_its_cache_points(self):
        laid_out = [r for r in self.b.values() if (r.get("prompt_meta") or {}).get("layout")]
        self.assertTrue(laid_out)
        for r in laid_out:
            meta = r["prompt_meta"]
            self.assertEqual(meta["layout"], "cache_friendly")
            self.assertTrue(all(0 < p < len(r["prompt"]) for p in meta["cache_points"]))
            self.assertTrue(meta["cache_points"], "the shared part ends somewhere")
        self.assertFalse([r for r in self.a.values() if (r.get("prompt_meta") or {}).get("layout")])

    def test_every_prompt_has_the_same_words(self):
        for key, old in self.a.items():
            with self.subTest(call=key):
                self.assertEqual(_words(self.b[key]["prompt"]), _words(old["prompt"]))

    def test_the_shared_part_really_is_shared(self):
        """Everything before the first cache point is the same for every delegate in every phase of
        the month: that is the part a cache can serve to all of them."""
        by_month = {}
        for (month, phase, who, _n), r in self.b.items():
            points = (r.get("prompt_meta") or {}).get("cache_points") or []
            if points and phase in ("session", "revision", "decision"):
                by_month.setdefault(month, set()).add(r["prompt"][:points[0]])
        self.assertTrue(by_month)
        for month, prefixes in by_month.items():
            self.assertEqual(len(prefixes), 1, f"month {month}: {len(prefixes)} different shared parts")

    def test_the_instructions_still_come_last(self):
        for key, r in self.b.items():
            sections = (r.get("prompt_meta") or {}).get("sections") or []
            if sections:
                with self.subTest(call=key):
                    self.assertIn(sections[-1][0], ("instructions", "schema"))


if __name__ == "__main__":
    unittest.main()
