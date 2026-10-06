"""An Ollama seat's thinking switch, as a config file or the control room writes it."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya.backends import make_backend  # noqa: E402
from karamaniya.backends.ollama import parse_think  # noqa: E402


class OllamaThink(unittest.TestCase):
    def test_booleans_and_the_control_rooms_words(self):
        for raw, want in ((None, None), ("", None), ("default", None), (False, False), ("off", False),
                          ("false", False), ("OFF", False), (True, True), ("on", True), ("true", True)):
            self.assertIs(parse_think(raw), want, raw)

    def test_off_from_the_control_room_really_turns_thinking_off(self):
        # bool("off") is True: without parsing, "off" would have switched thinking on.
        b = make_backend({"provider": "ollama", "model": "qwen3.5:9b", "think": "off", "num_ctx": 16384})
        self.assertIs(b.think, False)
        self.assertEqual(b.num_ctx, 16384)


if __name__ == "__main__":
    unittest.main()
