"""Every run carries enough context to be interpreted later, and comparable runs are recognised."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import manifest  # noqa: E402
from karamaniya.config import load_config  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import new_world  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "council.scripted.toml")


def cfg_with(mapping=None, **run_over):
    cfg = load_config(CONFIG)
    run = {**cfg["run"], **run_over}
    out = {**cfg, "run": run}
    if mapping:
        out["mapping"] = mapping
    return out


class Contents(unittest.TestCase):
    def test_a_manifest_names_the_seed_and_how_seeds_derive(self):
        m = manifest.build(new_world(42, 12), cfg_with())
        self.assertEqual(m["seeds"]["run_seed"], 42)
        self.assertEqual(m["seeds"]["world_seed"], 42)
        self.assertIn("rng_for", m["seeds"]["derivation"])
        for stream in ("world", "structural_parameters", "psychology", "foreign_disposition"):
            self.assertIn(stream, m["seeds"]["streams"])

    def test_a_manifest_names_every_version_that_changes_behaviour(self):
        m = manifest.build(new_world(1, 12), cfg_with())
        for key in ("agent_prompt", "psychology", "output_schema"):
            self.assertIn(key, m["versions"])
        for key in ("world_engine_version", "event_generator_version", "analytics_version", "python"):
            self.assertIn(key, m["engine"])
        self.assertIn("agent", m["architecture"])

    def test_a_manifest_records_the_structural_parameters_the_world_was_given(self):
        w = new_world(7, 12)
        m = manifest.build(w, cfg_with())
        from karamaniya import causality
        self.assertEqual(m["structural_parameters"], causality.ensure(w))

    def test_a_manifest_records_the_seat_lineup(self):
        m = manifest.build(new_world(1, 12), cfg_with(mapping={"A": "kimi-k3", "B": "Mimo"}))
        self.assertEqual([s["seat"] for s in m["seats"]], ["A", "B"])
        self.assertEqual(m["seats"][0]["label"], "kimi-k3")

    def test_a_manifest_says_models_are_not_deterministic(self):
        m = manifest.build(new_world(1, 12), cfg_with())
        self.assertIn("not deterministic", m["determinism_note"])
        self.assertIn("model outputs are not deterministic", m["determinism_note"].lower())

    def test_the_manifest_is_json_serialisable(self):
        m = manifest.build(new_world(3, 12), cfg_with())
        self.assertIsInstance(json.dumps(m), str)
        self.assertEqual(len(m["engine"]["source_fingerprint"]), 64)


class Comparability(unittest.TestCase):
    def test_two_identical_runs_are_comparable(self):
        a = manifest.build(new_world(5, 12), cfg_with())
        b = manifest.build(new_world(5, 12), cfg_with())
        ok, differences = manifest.comparable(a, b)
        self.assertTrue(ok, differences)

    def test_a_different_seed_is_reported_as_the_axis_that_differs(self):
        a = manifest.build(new_world(5, 12), cfg_with())
        b = manifest.build(new_world(6, 12), cfg_with())
        ok, differences = manifest.comparable(a, b)
        self.assertFalse(ok)
        self.assertIn("last_run_seed", differences)

    def test_a_different_seat_lineup_is_reported(self):
        a = manifest.build(new_world(5, 12), cfg_with(mapping={"A": "kimi-k3"}))
        b = manifest.build(new_world(5, 12), cfg_with(mapping={"A": "Mimo"}))
        self.assertIn("seat_lineup", manifest.divergences(a, b))

    def test_different_sampling_settings_are_reported(self):
        a = manifest.build(new_world(5, 12), cfg_with(temperature=0.2))
        b = manifest.build(new_world(5, 12), cfg_with(temperature=0.9))
        self.assertIn("sampling_settings", manifest.divergences(a, b))

    def test_a_hand_edited_parameter_block_is_caught(self):
        """Two runs whose worlds differ underneath must not be compared as a model difference."""
        a = manifest.build(new_world(5, 12), cfg_with())
        w = new_world(5, 12)
        from karamaniya import causality
        causality.ensure(w)["import_dependency"] = 0.33
        b = manifest.build(w, cfg_with())
        self.assertIn("structural_parameters", manifest.divergences(a, b))

    def test_different_engine_source_is_not_reported_as_a_comparable_run(self):
        a = manifest.build(new_world(5, 12), cfg_with())
        b = manifest.build(new_world(5, 12), cfg_with())
        b["engine"]["source_fingerprint"] = "0" * 64
        self.assertIn("engine_source", manifest.divergences(a, b))

    def test_refreshing_a_legacy_run_does_not_stamp_current_code_on_old_history(self):
        w = new_world(5, 12)
        w.history.append({"month": 0})
        m = manifest.build(w, cfg_with())
        self.assertIsNone(m["engine"]["source_fingerprint"])

    def test_two_legacy_manifests_are_not_claimed_comparable_without_source_hashes(self):
        a = manifest.build(new_world(5, 12), cfg_with())
        b = manifest.build(new_world(5, 12), cfg_with())
        a["engine"]["source_fingerprint"] = None
        b["engine"]["source_fingerprint"] = None
        self.assertIn("engine_source_unrecorded", manifest.divergences(a, b))

    def test_source_fingerprint_is_stable_and_ignores_bytecode_cache(self):
        root = tempfile.mkdtemp(prefix="karamaniya-source-hash-")
        try:
            os.makedirs(os.path.join(root, "__pycache__"))
            with open(os.path.join(root, "world.py"), "w", encoding="utf-8") as f:
                f.write("engine rule one\n")
            with open(os.path.join(root, "__pycache__", "world.cpython.pyc"), "wb") as f:
                f.write(b"cache one")
            first = manifest.source_fingerprint(root)
            self.assertEqual(first, manifest.source_fingerprint(root))
            with open(os.path.join(root, "__pycache__", "world.cpython.pyc"), "wb") as f:
                f.write(b"cache two")
            self.assertEqual(first, manifest.source_fingerprint(root))
            with open(os.path.join(root, "world.py"), "w", encoding="utf-8") as f:
                f.write("engine rule two\n")
            self.assertNotEqual(first, manifest.source_fingerprint(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)


class InARun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-manifest-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_real_run_writes_a_manifest_before_it_starts(self):
        path = new_run(CONFIG, runs_dir=self.tmp, name="m", months=3, quiet=True)
        with open(os.path.join(path, "manifest.json"), encoding="utf-8") as f:
            m = json.load(f)
        self.assertEqual(m["seeds"]["run_seed"], load_config(CONFIG)["run"]["seed"])
        self.assertTrue(m["seats"])

    def test_the_manifest_is_refreshed_when_the_run_ends(self):
        path = new_run(CONFIG, runs_dir=self.tmp, name="m2", months=3, quiet=True)
        with open(os.path.join(path, "manifest.json"), encoding="utf-8") as f:
            m = json.load(f)
        self.assertIn("outcome", m)
        self.assertIn("months_simulated", m)
        self.assertGreaterEqual(m["months_simulated"], 1)
        self.assertIn("engine_errors", m)

    def test_the_manifest_records_which_model_actually_answered(self):
        path = new_run(CONFIG, runs_dir=self.tmp, name="m3", months=2, quiet=True)
        with open(os.path.join(path, "manifest.json"), encoding="utf-8") as f:
            m = json.load(f)
        self.assertTrue(m["served_models"], "no served model was recorded")
        for seat, models in m["served_models"].items():
            with self.subTest(seat=seat):
                self.assertTrue(models)
                self.assertIsInstance(models, list)

    def test_served_models_come_from_the_log_not_the_config(self):
        store = RunStore(os.path.join(self.tmp, "logtest"))
        store.log({"type": "call", "member": "A", "served_model": "actually-this-one"})
        self.assertEqual(manifest.served_from_log(store), {"A": ["actually-this-one"]})

    def test_a_seat_served_by_two_models_records_both(self):
        store = RunStore(os.path.join(self.tmp, "logtest2"))
        store.log({"type": "call", "member": "A", "served_model": "one"})
        store.log({"type": "call", "member": "A", "served_model": "two"})
        self.assertEqual(manifest.served_from_log(store), {"A": ["one", "two"]})

    def test_a_missing_log_yields_no_served_models_rather_than_an_error(self):
        store = RunStore(os.path.join(self.tmp, "empty"))
        self.assertEqual(manifest.served_from_log(store), {})

    def _manifest_of(self, name):
        path = os.path.join(new_run(CONFIG, runs_dir=self.tmp, name=name, months=1, quiet=True),
                            "manifest.json")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def test_the_same_seed_produces_the_same_manifest(self):
        a = self._manifest_of("s1")
        b = self._manifest_of("s2")
        for block in ("seeds", "structural_parameters", "versions", "architecture"):
            with self.subTest(block=block):
                self.assertEqual(a[block], b[block])


if __name__ == "__main__":
    unittest.main()
