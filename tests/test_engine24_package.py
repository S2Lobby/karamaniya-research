"""The submission package (tools/package.py): the file selection and the secret/forbidden checks, the manifest,
and one real build from HEAD followed by the clean-machine smoke test in a fresh venv that runs only the README's
one command. The integration class skips until the package files are committed, because the build reads a commit
and never the working tree.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import package  # noqa: E402


def git_ok(*args) -> bool:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        return False
    return subprocess.run(["git", "-C", str(ROOT), *args], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


class SelectionTests(unittest.TestCase):
    def test_the_engine_study_tools_and_docs_are_selected(self):
        for path in ("karamaniya/runner.py", "karamaniya/versions.py", "studies/karamaniya_trust/run.py",
                     "studies/karamaniya_trust/study.yaml", "tools/study_grid.py", "tools/package.py",
                     "docs/SCOPE_TEST.md", "paper/socioverse/PREREGISTRATION.md"):
            self.assertTrue(package.included(path), path)

    def test_artwork_trajectory_stores_and_unrelated_files_are_not(self):
        for path in ("karamaniya/council-chamber.png", "studies/karamaniya_trust/trajectory/dry_run/study.duckdb",
                     "studies/karamaniya_trust/trajectory/run/wrapped_run/checkpoint.json",
                     "studies/karamaniya_trust/trajectory/dry_run/progress.jsonl", "bench/bench.py", "figures/x.png"):
            self.assertFalse(package.included(path), path)

    def test_the_zip_mapping_renames_the_two_readmes(self):
        self.assertEqual(package.zip_name("docs/SUBMISSION_README.md"), "README.md")
        self.assertEqual(package.zip_name("README.md"), "README-engine.md")
        self.assertEqual(package.zip_name("karamaniya/runner.py"), "karamaniya/runner.py")

    def test_private_runs_and_binary_stores_are_forbidden(self):
        for path, why in ((".env", ".env"), ("private/x.json", "folder"), ("runs/x/checkpoint.json", "folder"),
                          ("studies/x/trajectory/wrapped_run/log.jsonl", "folder"),
                          ("a/study.duckdb", "store"), ("a/panel.parquet", "store"), ("a/server.pem", "certificate")):
            self.assertTrue(package.forbidden_path(path), (path, why))
        for path in ("README.md", "karamaniya/runner.py", "studies/karamaniya_trust/trajectory/dry_run/summary.json"):
            self.assertEqual(package.forbidden_path(path), "", path)

    def test_a_key_like_value_is_a_finding_but_a_placeholder_is_not(self):
        self.assertEqual(package.secret_findings(b"export OPENAI_API_KEY=sk-" + b"a" * 30), ["key-like assignment"])
        self.assertEqual(package.secret_findings(b"API_KEY=YOUR_KEY_HERE_NOT_A_REAL_KEY"), [])
        self.assertEqual(package.secret_findings(b"API_KEY=<your key>"), [])
        self.assertEqual(package.secret_findings(b"grep TYPESAFE_API_KEY docs"), [])

    def test_the_readme_command_is_read_and_nothing_else(self):
        text = ("# Package\n\n```bash\npython -m karamaniya simulate council.scripted.toml --runs 1 "
                "--months 1 --prefix package-smoke\n```\n")
        self.assertEqual(package.readme_command(text),
                         ["python", "-m", "karamaniya", "simulate", "council.scripted.toml", "--runs", "1",
                          "--months", "1", "--prefix", "package-smoke"])
        with self.assertRaises(package.PackageError):
            package.readme_command("# no command here")


@unittest.skipUnless(git_ok("cat-file", "-e", "HEAD:tools/package.py")
                     and git_ok("cat-file", "-e", "HEAD:docs/SUBMISSION_README.md"),
                     "the package files are not committed at HEAD; commit them, then run this test")
class BuildAndSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="package-test-"))
        cls.manifest = package.build_package("HEAD", out=cls.tmp / "package.zip")
        cls.zip = Path(cls.manifest["zip"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_manifest_is_pinned_to_the_commit_and_names_the_versions(self):
        head = package.resolve_commit("HEAD")
        self.assertEqual(self.manifest["commit"], head)
        self.assertEqual(self.manifest["versions"]["world_engine"], 26)
        self.assertIn("agent_prompt", self.manifest["versions"])
        self.assertTrue(all(len(entry["sha256"]) == 64 for entry in self.manifest["files"]))

    def test_the_zip_has_the_required_files_no_forbidden_path_and_no_env(self):
        check = package.verify_zip(self.zip)
        self.assertEqual(check["forbidden"], [])
        self.assertEqual(check["missing"], [])
        self.assertEqual(check["hash_mismatches"], [])
        names = set(check["names"])
        self.assertIn("README.md", names)
        self.assertIn("PACKAGE_MANIFEST.json", names)
        self.assertFalse(any(name.endswith(".env") or "/.env" in name for name in names))
        with zipfile.ZipFile(self.zip) as z:
            readme = z.read("README.md").decode("utf-8")
        self.assertIn("python -m karamaniya simulate", readme)

    def test_the_clean_machine_smoke_runs_the_readme_command(self):
        result = package.smoke(self.zip)
        self.assertEqual(result["returncode"], 0, result.get("output_tail"))
        self.assertTrue(result["checkpoints"], result)
        self.assertIn("karamaniya simulate", result["command"])


if __name__ == "__main__":
    unittest.main()
