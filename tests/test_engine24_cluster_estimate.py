"""Cluster kit: the time and cost estimate (tools/cluster/estimate.py) and the seat block in its README.

    C:/Users/litle/Karamaniya/research/.venv/Scripts/python.exe -m unittest tests.test_engine24_cluster_estimate -v

The estimate is a model, not a measurement. Its throughput numbers are assumptions until the one-hour rehearsal
has been measured (estimate.py --calibrate), so the tests check the model's arithmetic and its stated worst case,
not any real GPU.
"""
import contextlib
import io
import json
import os
import re
import sys
import tomllib
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "cluster"))

import estimate as est  # noqa: E402
from karamaniya.backends import make_backend  # noqa: E402
from karamaniya.config import normalize_config  # noqa: E402

README = os.path.join(ROOT, "tools", "cluster", "README.md")
M = est.REFERENCE_MODEL
H100 = est.GPUS["h100-80"]


class HorizonAndModel(unittest.TestCase):
    def test_worst_case_is_the_horizon_plus_the_election_extension(self):
        # A Month-36 election can extend a run by up to four months (the coordinator's brief), so 40 is the worst case.
        self.assertEqual(est.horizon_months(36), 40)
        self.assertEqual(est.SCENARIOS["worst"]["months"], 40)
        self.assertEqual(est.SCENARIOS["central"]["months"], 36)

    def test_reference_model_bytes_match_the_qwen3_8b_config(self):
        # 36 layers, 8 KV heads, head dim 128, bf16; 8.19 billion parameters (huggingface Qwen/Qwen3-8B).
        weights_gb, kv_gb_per_token = est.model_bytes(M)
        self.assertAlmostEqual(weights_gb, 16.38, places=2)
        self.assertAlmostEqual(kv_gb_per_token, 0.000147456, places=9)

    def test_prefill_flops_are_linear_plus_attention(self):
        expected = 2 * 8.19e9 * 1000 + 2 * 36 * 4096 * 1000 ** 2
        self.assertAlmostEqual(est.prefill_flops(M, 1000), expected, delta=1e-9 * expected)


class Memory(unittest.TestCase):
    def test_one_h100_holds_17_long_sequences(self):
        # 80 GB x 0.90 - 2 GB overhead - 16.38 GB weights, over 21,000 tokens x 0.147 MB.
        self.assertEqual(est.batch_capacity(H100, 1, M, 21000), 17)

    def test_a_second_gpu_in_the_server_nearly_doubles_the_room_for_sequences(self):
        # 2 x (80 x 0.90 - 2 GB overhead per GPU) - 16.38 GB weights = 123.6 GB, over 3.10 GB per sequence: 39.
        self.assertEqual(est.batch_capacity(H100, 2, M, 21000), 39)

    def test_an_rtx_4090_holds_one_sequence_at_this_context(self):
        self.assertEqual(est.batch_capacity(est.GPUS["rtx-4090"], 1, M, 21000), 1)

    def test_a_model_larger_than_the_card_holds_none(self):
        big = dict(M, params_b=70)   # 140 GB of bf16 weights
        self.assertEqual(est.batch_capacity(est.GPUS["rtx-4090"], 1, big, 21000), 0)

    def test_decode_rate_rises_with_batch(self):
        one = est.decode_rate(H100, 1, M, 1, 21000, 0.6)
        four = est.decode_rate(H100, 1, M, 4, 21000, 0.6)
        self.assertGreater(four, one)

    def test_decode_step_gets_slower_with_longer_context(self):
        short = est.step_seconds(H100, 1, M, 8, 10000, 0.6)
        long = est.step_seconds(H100, 1, M, 8, 30000, 0.6)
        self.assertGreater(long, short)


class Estimate(unittest.TestCase):
    def test_cost_is_rented_gpus_times_total_hours_times_price(self):
        r = est.estimate("h100-80", 1, "central", thinking=False)
        self.assertEqual(r["rented_gpus"], 6)
        self.assertAlmostEqual(r["cost_low"], 6 * r["total_hours"] * 1.73, delta=1e-6)
        self.assertAlmostEqual(r["cost_high"], 6 * r["total_hours"] * 2.40, delta=1e-6)

    def test_thinking_takes_longer_than_no_thinking(self):
        plain = est.estimate("h100-80", 1, "central", thinking=False)
        think = est.estimate("h100-80", 1, "central", thinking=True)
        self.assertGreater(think["total_hours"], plain["total_hours"])

    def test_worst_case_takes_longer_than_central(self):
        for thinking in (False, True):
            with self.subTest(thinking=thinking):
                central = est.estimate("h100-80", 1, "central", thinking=thinking)
                worst = est.estimate("h100-80", 1, "worst", thinking=thinking)
                self.assertGreater(worst["total_hours"], central["total_hours"])
                self.assertEqual(worst["months"], 40)

    def test_more_gpus_per_server_cut_the_delegate_throughput_hours(self):
        one = est.estimate("h100-80", 1, "central", thinking=True)
        two = est.estimate("h100-80", 2, "central", thinking=True)
        self.assertLess(two["hours_delegate"], one["hours_delegate"])

    def test_waves_when_fewer_workers_than_runs(self):
        self.assertEqual(est.waves(50, 50), 1)
        self.assertEqual(est.waves(50, 25), 2)
        self.assertEqual(est.waves(50, 7), 8)

    def test_no_thinking_fits_one_day_on_one_h100_per_server(self):
        r = est.estimate("h100-80", 1, "central", thinking=False)
        self.assertTrue(r["fits_memory"])
        self.assertLess(r["total_hours"], 24)

    def test_thinking_over_36_months_does_not_fit_one_day_on_one_gpu_per_server(self):
        r = est.estimate("h100-80", 1, "central", thinking=True)
        self.assertGreater(r["total_hours"], 24)

    def test_a_call_that_outlasts_the_seat_timeout_is_flagged(self):
        calm = est.estimate("h100-80", 1, "central", thinking=True)
        self.assertFalse(calm["timeout_risk"])            # about 275 s a call, under the 600 s seat default
        tight = est.estimate("h100-80", 1, "central", thinking=True, seat_timeout=60)
        self.assertTrue(tight["timeout_risk"])

    def test_a_model_that_does_not_fit_is_flagged_not_priced(self):
        big = dict(M, params_b=70)
        r = est.estimate("rtx-4090", 1, "central", thinking=False, model=big)
        self.assertFalse(r["fits_memory"])
        self.assertEqual(r["batch"], 0)

    def test_gpus_needed_finds_the_smallest_fit(self):
        g, r = est.gpus_needed("h100-80", "central", thinking=False)
        self.assertEqual(g, 1)
        self.assertLessEqual(r["total_hours"], 24)

    def test_gpus_needed_is_none_when_nothing_fits(self):
        self.assertEqual(est.gpus_needed("rtx-4090", "worst", thinking=True), (None, None))


class Calibration(unittest.TestCase):
    def test_measured_decode_rate_gives_back_the_bandwidth_efficiency(self):
        tps = est.decode_rate(H100, 1, M, 17, 21000, 0.55)
        got = est.implied_efficiency("h100-80", 1, batch=17, ctx_tokens=21000, decode_tps=tps)
        self.assertAlmostEqual(got["bw_eff"], 0.55, places=9)

    def test_measured_prefill_rate_gives_back_the_compute_efficiency(self):
        flops_per_token = est.prefill_flops(M, 17000) / 17000
        tps = (1 * H100["tflops"] * 1e12 * 0.4) / flops_per_token
        got = est.implied_efficiency("h100-80", 1, batch=1, ctx_tokens=17000, prefill_tps=tps, input_tokens=17000)
        self.assertAlmostEqual(got["mfu"], 0.4, places=9)


class Cli(unittest.TestCase):
    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = est.main(argv)
        return rc, buf.getvalue()

    def test_default_run_prints_central_and_worst_rows_with_40_months(self):
        rc, out = self._run([])
        self.assertEqual(rc, 0)
        self.assertIn("central", out)
        self.assertIn("worst", out)
        self.assertIn("40", out)

    def test_json_output_is_a_list_of_estimates(self):
        rc, out = self._run(["--json", "--gpu", "h100-80", "--gpus-per-server", "1"])
        self.assertEqual(rc, 0)
        rows = json.loads(out)
        self.assertTrue(rows)
        self.assertTrue(all("total_hours" in row for row in rows))

    def test_calibration_prints_the_implied_bandwidth_efficiency(self):
        rc, out = self._run(["--calibrate", "h100-80", "--calibrate-batch", "17", "--calibrate-ctx", "21000",
                             "--measured-decode-tps", "495"])
        self.assertEqual(rc, 0)
        self.assertIn("bw_eff", out)


class ClusterSeatConfig(unittest.TestCase):
    """The README's seat blocks must be ones the engine accepts, pointing at loopback, with no key."""

    @classmethod
    def setUpClass(cls):
        with open(README, encoding="utf-8") as f:
            cls.text = f.read()
        blocks = re.findall(r"```toml\n(.*?)```", cls.text, re.S)
        cls.seat_blocks = [b for b in blocks if "openai_compat" in b and "[[seat]]" in b]

    def test_readme_has_a_seat_block(self):
        self.assertTrue(self.seat_blocks)

    def test_seat_block_is_accepted_and_builds_a_backend_on_loopback(self):
        cfg = normalize_config(tomllib.loads(self.seat_blocks[0]))
        backend = make_backend(cfg["seats"][0])
        self.assertTrue(backend.base_url.startswith("http://127.0.0.1:"), backend.base_url)
        self.assertEqual(backend.api_key, "")

    def test_no_seat_block_names_a_key_or_a_remote_host(self):
        for block in self.seat_blocks:
            with self.subTest(block=block[:60]):
                self.assertNotIn("api_key", block)
                for url in re.findall(r'base_url\s*=\s*"([^"]+)"', block):
                    self.assertTrue(url.startswith("http://127.0.0.1:"), url)

    def test_readme_names_the_engine_options_the_setup_needs(self):
        self.assertIn("office_assignment", self.text)
        self.assertIn("action_order", self.text)


if __name__ == "__main__":
    unittest.main()
