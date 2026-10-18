"""Engine 33 (regime realism): world engine 33, agent prompt 30 (psychology 8, error taxonomy 8).

The release adds the `uprising_model = "legitimacy"` world and changes no prompt: the defaults are `legacy`, and a
scripted engine-32 run replays identically (tools/replay_run.py on reports/rr-base-36/base-seed1).

    python -m unittest tests.test_engine33_versions
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import versions  # noqa: E402


class Versions(unittest.TestCase):
    def test_the_bump(self):
        self.assertEqual((versions.WORLD_ENGINE, versions.AGENT_PROMPT, versions.PSYCHOLOGY,
                          versions.ERROR_TAXONOMY), (33, 30, 8, 8))


if __name__ == "__main__":
    unittest.main()
