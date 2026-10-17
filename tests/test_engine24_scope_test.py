"""The SocioVerse2 scope test (tools/scope_test.py): the decision audit classifies every reply path, the stub is
deterministic, and one run of SocioVerse2's own opinion_diffusion study produces consistent counts and an audit
trail. The integration tests need the vendored SocioVerse2 checkout; they skip when it is absent. No model is
called: the stub endpoint is local and deterministic.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import scope_test  # noqa: E402

VENDOR = Path(ROOT).parent / "_vendor" / "SocioVerse2"


class ClassifyTests(unittest.TestCase):
    def test_the_five_paths_are_told_apart(self):
        self.assertEqual(scope_test.classify("llm", '{"opinion": 0.4}', None, True), "valid_json")
        self.assertEqual(scope_test.classify("llm", "I lean 0.4 today.", None, False), "bare_float")
        self.assertEqual(scope_test.classify("fallback", "no number here", None, False), "unparsed_reply")
        self.assertEqual(scope_test.classify("fallback", "", None, False), "empty_reply")
        self.assertEqual(scope_test.classify("fallback", "", "RuntimeError: boom", False), "call_error")

    def test_the_share_helper_handles_a_zero_denominator(self):
        self.assertIsNone(scope_test._share(0, 0))
        self.assertEqual(scope_test._share(1, 4), 0.25)

    def test_the_own_opinion_is_read_from_both_prompt_languages(self):
        self.assertEqual(scope_test._own_opinion("- Your current stance: 0.417"), 0.417)
        self.assertEqual(scope_test._own_opinion("- 你当前的立场: 0.583"), 0.583)
        self.assertIsNone(scope_test._own_opinion("no stance here"))


class StubTests(unittest.TestCase):
    def test_the_stub_is_deterministic_and_exercises_every_class(self):
        stub = scope_test.StubLLM(seed=7)
        prompt = "- Your current stance: 0.4\n- The current stances of your two neighbours: [0.3, 0.5]"
        self.assertEqual(stub(prompt), stub(prompt))
        seen = set()
        errors = 0
        for i in range(400):
            try:
                reply = stub(f"{prompt}\nagent {i}")
            except scope_test.StubTransportError:
                errors += 1
                continue
            if not reply:
                seen.add("empty")
            elif '"opinion"' in reply:
                seen.add("json")
            elif "undecided" in reply:
                seen.add("unparsed")
            else:
                seen.add("bare")
        self.assertEqual(seen, {"json", "bare", "unparsed", "empty"})
        self.assertGreater(errors, 0)


def _vendor_importable() -> bool:
    """The vendored checkout is present and its dependencies can be imported. The vendor lives outside the
    repository (CI has no copy), and a plain engine environment has no pydantic, so both are skips, not errors."""
    if not (VENDOR / "socioverse" / "__init__.py").is_file():
        return False
    import importlib.util
    return importlib.util.find_spec("pydantic") is not None


@unittest.skipUnless(_vendor_importable(),
                     "vendored SocioVerse2 or its pydantic dependency is not present")
class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="scope-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_once(self, name="run", steps=2):
        return scope_test.run_scope_test(socioverse_root_path=VENDOR, out=self.tmp / name, steps=steps)

    def test_one_run_writes_the_audit_and_the_counts_are_consistent(self):
        summary = self.run_once()
        self.assertEqual(summary["study"], "opinion_diffusion")
        self.assertEqual(summary["decisions"], 12 * 2)
        self.assertEqual(sum(summary["counts"].values()), summary["decisions"])
        self.assertEqual(summary["fallbacks"],
                         sum(summary["counts"][k] for k in ("unparsed_reply", "empty_reply", "call_error")))
        self.assertEqual(summary["quiet_replacements"], summary["counts"]["unparsed_reply"])
        self.assertGreater(summary["counts"]["valid_json"], 0)
        self.assertGreater(summary["counts"]["bare_float"], 0, "the parser's bare-number path should be exercised")
        self.assertFalse(summary["source_in_panel"], "the trajectory panel does not keep the action's source")
        self.assertNotIn("source", summary["panel_fields"])
        self.assertEqual(summary["fallback_rule_disagreements"], 0)
        for name in ("summary.json", "decisions.jsonl", "report.md"):
            self.assertTrue((self.tmp / "run" / name).is_file(), name)
        rows = [json.loads(line) for line in
                (self.tmp / "run" / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), summary["decisions"])
        self.assertEqual({row["label"] for row in rows} - set(scope_test.CLASSES), set())
        self.assertTrue(all(row["fallback_matches_rule"] in (None, True) for row in rows))

    def test_the_same_seed_gives_the_same_audit(self):
        first = self.run_once("first")
        second = self.run_once("second")
        self.assertEqual(first["counts"], second["counts"])
        self.assertEqual(first["quiet_replacements"], second["quiet_replacements"])
        self.assertEqual(first["metrics"], second["metrics"])

    def test_a_non_positive_step_count_is_refused(self):
        with self.assertRaises(scope_test.ScopeTestError):
            self.run_once("bad", steps=0)

    def test_the_scoped_imports_and_the_duckdb_stand_in_are_removed_after_the_run(self):
        # A later test module must see the interpreter it started with: if `socioverse` stayed imported, the wrap
        # tests would run against a vendor path with a fake duckdb instead of skipping.
        self.run_once("cleanup")
        self.assertNotIn("socioverse", sys.modules)
        self.assertNotIn("duckdb", sys.modules)
        self.assertFalse(any(name.startswith("socioverse.") for name in sys.modules))


if __name__ == "__main__":
    unittest.main()
