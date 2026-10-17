"""Engine 30: world engine 32, agent prompt 29 (psychology 8, error taxonomy 8).

The release merges three waves: Wave B (world engine 30, agent prompt 27), Wave A (31, 28) and
Wave C (32, 29). The tuple below is the release's, not any one wave's.

    python -m unittest tests.test_engine30_versions
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
                          versions.ERROR_TAXONOMY), (32, 29, 8, 8))


if __name__ == "__main__":
    unittest.main()
