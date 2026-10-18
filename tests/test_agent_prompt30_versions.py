"""Agent prompt 30 (world engine 32, psychology 8, error taxonomy 8 unchanged): a CLI seat's folder names nothing.

A CLI shows its working directory to the model. Run 20261018-014944-seed1 ran its CLI seats in `karamaniya-<tool>-`
folders, and Haiku's reasoning picked the name up ("Skipping karamaniya-related items"; "a sandboxed directory with a
naming pattern" in its closing answer).

    python -m unittest tests.test_agent_prompt30_versions
"""
from __future__ import annotations

import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import versions  # noqa: E402
from karamaniya.backends import cli_common  # noqa: E402


class Versions(unittest.TestCase):
    def test_the_bump(self):
        self.assertEqual((versions.WORLD_ENGINE, versions.AGENT_PROMPT, versions.PSYCHOLOGY,
                          versions.ERROR_TAXONOMY), (32, 30, 8, 8))


class CliFolder(unittest.TestCase):
    def test_a_cli_seat_runs_in_an_empty_folder_whose_name_names_nothing(self):
        folders = [cli_common.scratch_dir() for _ in range(3)]
        try:
            self.assertEqual(len(set(folders)), 3)
            for folder in folders:
                self.assertTrue(os.path.isdir(folder))
                self.assertEqual(os.listdir(folder), [])
                name = os.path.basename(folder).lower()
                for word in ("karamaniya", "claude", "cline", "codex", "copilot", "qoder", "agy", "seat",
                             "delegate", "sim", "test", "eval"):
                    self.assertNotIn(word, name)
        finally:
            for folder in folders:
                shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
