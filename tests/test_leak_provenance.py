"""End to end: a leak read through the real council path keeps its raw source intact.

The unit tests in test_provenance.py prove the module obeys its own rules. This file proves the
engine actually uses it, on the real code path, with a real Council.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import provenance  # noqa: E402
from karamaniya import memory  # noqa: E402
from karamaniya.council import Council  # noqa: E402
from karamaniya.runner import _seats  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "council.scripted.toml")

# A hedged warning. The press frame will drop the hedge; the source must not change.
HEDGED = "Our fiscal fragility may cause a coup."


class LeakThroughTheCouncil(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-leak-")
        from karamaniya.config import load_config
        from karamaniya.world import new_world
        cfg = load_config(CONFIG)
        mapping = {letter: seat["label"] for letter, seat in zip("ABCDE", cfg["seats"])}
        cfg = {**cfg, "mapping": mapping}
        self.cfg = cfg
        w = new_world(cfg["run"]["seed"], 6, member_ids=list(mapping),
                      agent_architecture_version=int(cfg["run"].get("agent_architecture_version", 2)))
        self.store = RunStore(os.path.join(self.tmp, "r"))
        self.council = Council(w, _seats(cfg, mapping), cfg["run"], self.store)
        self.w = w
        # Give two delegates a reason to be the leak's subject and object.
        w.const.offices["army"] = "B"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _leak(self, text):
        return {"month": self.w.month, "kind": "dm", "suspect": "C", "from": "B", "to": "C",
                "text": text, "headline": f"A private message from {self.w.member('B').name} "
                                            f"to {self.w.member('C').name} was published"}

    def _publish(self, text):
        leak = self._leak(text)
        self.council._publish_leaks([leak], [])
        return leak

    def test_a_published_leak_gets_a_provenance_record(self):
        leak = self._publish(HEDGED)
        self.assertIn("provenance_id", leak)
        pid = leak["provenance_id"]
        self.assertEqual(provenance.raw_text(self.w, pid), HEDGED)

    def test_the_press_layer_may_reframe_the_source(self):
        pid = self._publish(HEDGED)["provenance_id"]
        s = provenance.summary(self.w, pid)
        self.assertEqual(s["raw"], HEDGED)
        # Whatever it printed, the canonical reading is still a warning.
        self.assertFalse(s["asserts_intent"])
        self.assertTrue(s["canonical"]["hedged"])

    def test_a_hedged_warning_does_not_become_a_plot_because_the_press_framed_it(self):
        self._publish(HEDGED)
        kinds = [e["kind"] for e in self.w.events]
        self.assertNotIn("plot_exposed", kinds,
                         "a hedged warning was treated as a plot")
        self.assertIn("leak", kinds)

    def test_a_real_plot_still_registers(self):
        self._publish("We will use the army to remove the council next week.")
        kinds = [e["kind"] for e in self.w.events]
        self.assertIn("plot_exposed", kinds, "a genuine statement of intent was missed")

    def test_the_leak_event_is_emitted_exactly_once(self):
        self._publish(HEDGED)
        leaks = [e for e in self.w.events if e["kind"] == "leak"]
        self.assertEqual(len(leaks), 1)

    def test_published_text_and_route_reach_the_public_chronicle_and_memories(self):
        text = "I will support the grain corridor, but keep the troop deployment under civilian control."
        self._publish(text)
        event = next(e for e in self.w.events if e["kind"] == "leak")
        self.assertEqual(event["leaked_text"], text)
        self.assertEqual((event["from"], event["to"]), ("B", "C"))
        completed_month = self.w.month
        self.w.last_events = list(self.w.events)
        self.w.month = completed_month + 1
        memory.record_month(self.w, {"month": completed_month, "motions": []},
                            events=self.w.last_events, completed_month=completed_month)
        entries = [x for x in self.w.member("A").agent_state["memory"] if x["kind"] == "leak"]
        self.assertEqual(len(entries), 1)
        self.assertIn(text, entries[0]["text"])
        self.assertIn("Delegate B to Delegate C", entries[0]["text"])
        self.assertEqual(entries[0]["provenance"]["layer"], "RAW_SOURCE")
        self.assertEqual(entries[0]["month"], completed_month)

    def test_provenance_survives_the_runs_own_save_and_load(self):
        from karamaniya.world import World
        pid = self._publish(HEDGED)["provenance_id"]
        again = World.from_dict(self.w.to_dict())
        self.assertEqual(provenance.raw_text(again, pid), HEDGED)
        self.assertFalse(provenance.layer(again, pid, provenance.CANONICAL_FACT)["asserts_intent"])

    def test_the_record_is_reachable_from_the_run_log(self):
        pid = self._publish(HEDGED)["provenance_id"]
        self.store.save_checkpoint(self.w, self.council.state(), {"stopped": "test"})
        with open(os.path.join(self.store.path, "checkpoint.json"), encoding="utf-8") as f:
            stored = json.loads(f.read())
        world = stored["world"] if "world" in stored else stored
        self.assertIn("provenance", world.get("institutions", {}))
        self.assertIn(pid, world["institutions"]["provenance"])


if __name__ == "__main__":
    unittest.main()
