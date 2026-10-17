"""Engine 24: world engine 24 and agent prompt 21 (psychology 8 and error taxonomy 5 unchanged).

    python -m unittest tests.test_engine24_versions
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import versions  # noqa: E402


class Versions(unittest.TestCase):
    def test_the_bump(self):
        # At least: engine 25 bumped both again (tests/test_engine25_versions.py pins the current tuple).
        self.assertGreaterEqual((versions.WORLD_ENGINE, versions.AGENT_PROMPT, versions.PSYCHOLOGY,
                                 versions.ERROR_TAXONOMY), (24, 21, 8, 5))


if __name__ == "__main__":
    unittest.main()
