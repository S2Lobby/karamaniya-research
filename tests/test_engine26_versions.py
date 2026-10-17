"""Engine 26: world engine 26 and agent prompt 23 (psychology 8 and error taxonomy 5 unchanged).

    python -m unittest tests.test_engine26_versions
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import versions  # noqa: E402


class Versions(unittest.TestCase):
    def test_the_bump(self):
        self.assertEqual((versions.WORLD_ENGINE, versions.AGENT_PROMPT, versions.PSYCHOLOGY, versions.ERROR_TAXONOMY),
                         (26, 23, 8, 5))


if __name__ == "__main__":
    unittest.main()
