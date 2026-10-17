"""Estimate the time and cost of the study grid on rented GPUs, one vLLM server per model.

    python tools/cluster/estimate.py                              # the planning table, every GPU, 36 months
    python tools/cluster/estimate.py --runs 50 --months 36 --workers 50 --gpus-per-server 2
    python tools/cluster/estimate.py --json                       # every row, for the report
    python tools/cluster/estimate.py --calibrate h100-80 --calibrate-batch 17 --calibrate-ctx 21000 \\
        --measured-decode-tps 495                                 # after the rehearsal: the implied efficiency

This is a model, not a measurement. Its throughput rests on two efficiency factors (mfu for prefill, bw_eff for
decoding) and a retry factor, all in SCENARIOS, which the one-hour rehearsal must replace (--calibrate). A decoding
sequence reads its whole KV cache for every token it makes, so a long context makes decoding memory-bound. That
limits how many sequences fit beside the weights, and it is why thinking traces are slow. The worst case runs 40
months (a Month-36 election can add up to four), and it uses the high end of every workload figure.
"""
from __future__ import annotations

import argparse
import json
import math

EXTENSION = 4          # a Month-36 election may extend a run by up to four months
DELEGATES = 5          # one server per delegate model
SERVERS = DELEGATES + 1  # plus one server for the neighbours' model
NEIGHBOUR_CALLS = 2    # calls per run-month to the neighbours' model: one per cabinet (assumption; to measure)
CRITICAL_CALLS = 8     # sequential call rounds per month: openings 1, response round 5, votes 1, cabinets 1
UTIL = 0.90            # vLLM --gpu-memory-utilization, its default
OVERHEAD_GB = 2.0      # per GPU: activations and CUDA graphs (assumption)
SEAT_TIMEOUT_S = 600   # karamaniya/backends/base.py default timeout

# Specifications. Checked against NVIDIA's pages on 2026-10-17 where the note says so. The rest are UNVERIFIED.
# Prices are the user's vast.ai table of 2026-10-16, in dollars per GPU-hour (low, high).
GPUS = {
    "h100-80": {"label": "H100 80 GB", "vram_gb": 80, "bw_gbs": 3350, "tflops": 989, "price": (1.73, 2.40),
                "source": "3.35 TB/s and 989 TFLOPS dense BF16 (NVIDIA H100 page); 80 GB"},
    "rtx-pro-6000": {"label": "RTX PRO 6000 96 GB", "vram_gb": 96, "bw_gbs": 1792, "tflops": 500, "price": (0.93, 1.45),
                     "source": "96 GB and 1792 GB/s (NVIDIA page); TFLOPS UNVERIFIED: 4000 FP4-sparse TOPS / 8"},
    "rtx-4090": {"label": "RTX 4090 24 GB", "vram_gb": 24, "bw_gbs": 1008, "tflops": 165, "price": (0.13, 0.49),
                 "source": "24 GB (NVIDIA page); 1008 GB/s and 165 TFLOPS UNVERIFIED"},
}

# Reference model: Qwen3-8B, whose config.json gives the layers, heads and head dim (checked). Its 8.19 billion
# parameters come from the Hugging Face safetensors count. Replace it with the study's model shapes when they are chosen.
REFERENCE_MODEL = {"params_b": 8.19, "layers": 36, "hidden": 4096, "kv_heads": 8, "head_dim": 128,
                   "bytes_per_param": 2, "kv_bytes": 2}


def horizon_months(months: int, extension: int = EXTENSION) -> int:
    """How long a run can last: the horizon, plus what a Month-36 election may add."""
    return months + extension


# Workload and efficiency per scenario. Input tokens per call come from the 9-25k measurement, output tokens from
# the 0.5-1k (no thinking) and 4-12k (thinking) measurements. Calls per month are measured at 20-23.
SCENARIOS = {
    "best": {"months": 36, "calls": 20, "input": 9000, "plain_out": 500, "think_out": 4000,
             "mfu": 0.5, "bw_eff": 0.7, "retry": 1.0},
    "central": {"months": 36, "calls": 21.5, "input": 17000, "plain_out": 750, "think_out": 8000,
                "mfu": 0.4, "bw_eff": 0.6, "retry": 1.25},
    "worst": {"months": horizon_months(36), "calls": 23, "input": 25000, "plain_out": 1000, "think_out": 12000,
              "mfu": 0.3, "bw_eff": 0.5, "retry": 1.5},
}


def scenario_for(name: str, months: int) -> dict:
    """A scenario with its horizon set from --months: the worst case always runs EXTENSION months longer."""
    sc = dict(SCENARIOS[name])
    sc["months"] = horizon_months(months) if name == "worst" else months
    return sc


def model_bytes(model: dict) -> tuple:
    """(weights in GB, KV cache in GB per token) for a model of this shape."""
    weights_gb = model["params_b"] * model["bytes_per_param"]
    kv_gb = 2 * model["layers"] * model["kv_heads"] * model["head_dim"] * model["kv_bytes"] / 1e9
    return weights_gb, kv_gb


def prefill_flops(model: dict, tokens: int) -> float:
    """FLOPs to read a prompt of `tokens`: two per parameter per token, plus attention over the prompt."""
    return 2 * model["params_b"] * 1e9 * tokens + 2 * model["layers"] * model["hidden"] * tokens ** 2


def batch_capacity(gpu: dict, gpus: int, model: dict, ctx_tokens: float, util: float = UTIL,
                   overhead_gb: float = OVERHEAD_GB) -> int:
    """How many sequences of `ctx_tokens` fit in the server's memory beside the weights (0 if the model does not fit)."""
    weights_gb, kv_gb = model_bytes(model)
    free_gb = gpus * (gpu["vram_gb"] * util - overhead_gb) - weights_gb
    if free_gb <= 0:
        return 0
    return int(free_gb // (ctx_tokens * kv_gb))


def step_seconds(gpu: dict, gpus: int, model: dict, batch: int, ctx_tokens: float, bw_eff: float) -> float:
    """Seconds for one decoding step over `batch` sequences: the weights are read once, each sequence's KV cache once."""
    weights_gb, kv_gb = model_bytes(model)
    return (weights_gb + batch * ctx_tokens * kv_gb) / (gpus * gpu["bw_gbs"] * bw_eff)


def decode_rate(gpu: dict, gpus: int, model: dict, batch: int, ctx_tokens: float, bw_eff: float) -> float:
    """Tokens per second for the whole server at this batch."""
    return batch / step_seconds(gpu, gpus, model, batch, ctx_tokens, bw_eff)


def prefill_seconds(gpu: dict, gpus: int, model: dict, tokens: int, mfu: float) -> float:
    return prefill_flops(model, tokens) / (gpus * gpu["tflops"] * 1e12 * mfu)


def waves(runs: int, workers: int) -> int:
    """How many rounds of `workers` runs it takes to get through `runs` runs."""
    return math.ceil(runs / workers)


def estimate(gpu_key: str, gpus: int, scenario, *, thinking: bool, runs: int = 50, workers: int = 50,
             seat_timeout: float = SEAT_TIMEOUT_S, setup_hours: float = 1.0, sync_hours: float = 0.25,
             rented_gpus: int | None = None, model: dict = REFERENCE_MODEL) -> dict:
    """Time and cost for one server layout. `scenario` is a name in SCENARIOS or a scenario dict."""
    gpu = GPUS[gpu_key]
    sc = SCENARIOS[scenario] if isinstance(scenario, str) else scenario
    months, tokens_in = sc["months"], sc["input"]
    tokens_out = sc["think_out"] if thinking else sc["plain_out"]
    ctx = tokens_in + tokens_out / 2            # the average sequence, while it decodes
    cap = batch_capacity(gpu, gpus, model, ctx)
    batch = min(workers, cap)
    n_rented = rented_gpus or SERVERS * gpus
    row = {"gpu": gpu_key, "gpus_per_server": gpus, "scenario": scenario if isinstance(scenario, str) else "custom",
           "thinking": thinking, "months": months, "calls_per_month": sc["calls"], "input_tokens": tokens_in,
           "output_tokens": tokens_out, "retry": sc["retry"], "kv_capacity": cap, "batch": batch,
           "rented_gpus": n_rented, "price_low": gpu["price"][0], "price_high": gpu["price"][1]}
    if batch < 1:
        row.update(fits_memory=False, prefill_s_per_call=None, latency_per_call_s=None, timeout_risk=None,
                   hours_delegate=None, hours_neighbours=None, hours_latency=None, study_hours=None,
                   total_hours=None, cost_low=None, cost_high=None)
        return row
    t_pre = prefill_seconds(gpu, gpus, model, tokens_in, sc["mfu"])
    t_step = step_seconds(gpu, gpus, model, batch, ctx, sc["bw_eff"])
    per_call_s = t_pre + tokens_out * t_step    # one call, under this load: its decoding shares each step
    # Throughput: the server works through every call; decoding shares each step among `batch` sequences.
    server_s_per_call = t_pre + tokens_out * t_step / batch
    delegate_calls = (sc["calls"] - NEIGHBOUR_CALLS) / DELEGATES * runs * months
    neighbour_calls = NEIGHBOUR_CALLS * runs * months
    hours_delegate = sc["retry"] * delegate_calls * server_s_per_call / 3600
    hours_neighbours = sc["retry"] * neighbour_calls * server_s_per_call / 3600
    # Latency: one run's months are sequential, and each month's critical path waits for calls under load.
    hours_latency = sc["retry"] * waves(runs, workers) * months * CRITICAL_CALLS * per_call_s / 3600
    study_hours = max(hours_delegate, hours_neighbours, hours_latency)
    total_hours = setup_hours + study_hours + sync_hours
    row.update(fits_memory=True, prefill_s_per_call=t_pre, latency_per_call_s=per_call_s,
               timeout_risk=per_call_s > seat_timeout, hours_delegate=hours_delegate,
               hours_neighbours=hours_neighbours, hours_latency=hours_latency, study_hours=study_hours,
               total_hours=total_hours, cost_low=n_rented * total_hours * gpu["price"][0],
               cost_high=n_rented * total_hours * gpu["price"][1])
    return row


def gpus_needed(gpu_key: str, scenario: str, *, thinking: bool, target_hours: float = 24.0, choices=(1, 2, 4),
                **kwargs):
    """The fewest GPUs per server that finish within target_hours, with their estimate; (None, None) if none do."""
    for gpus in choices:
        row = estimate(gpu_key, gpus, scenario, thinking=thinking, **kwargs)
        if row["fits_memory"] and row["total_hours"] <= target_hours:
            return gpus, row
    return None, None


def implied_efficiency(gpu_key: str, gpus: int, *, batch: int, ctx_tokens: float, decode_tps: float | None = None,
                       input_tokens: int | None = None, prefill_tps: float | None = None,
                       model: dict = REFERENCE_MODEL) -> dict:
    """The efficiency factors a measured rehearsal implies, to put back into SCENARIOS."""
    gpu = GPUS[gpu_key]
    out = {}
    if decode_tps is not None:
        weights_gb, kv_gb = model_bytes(model)
        out["bw_eff"] = decode_tps * (weights_gb + batch * ctx_tokens * kv_gb) / (batch * gpus * gpu["bw_gbs"])
    if prefill_tps is not None:
        flops_per_token = prefill_flops(model, input_tokens) / input_tokens
        out["mfu"] = prefill_tps * flops_per_token / (gpus * gpu["tflops"] * 1e12)
    return out


def _money(value) -> str:
    return "-" if value is None else f"${value:,.0f}"


def _hours(value) -> str:
    return "-" if value is None else f"{value:,.1f}"


def _table(rows: list) -> list:
    head = (f"{'GPU':<20}{'thinking':<10}{'scenario':<9}{'GPUs/srv':>9}{'months':>7}{'batch':>6}"
            f"{'call s':>8}{'study h':>9}{'total h':>9}{'cost $':>20}  fits")
    lines = [head, "-" * len(head)]
    for r in rows:
        cost = "-" if r["cost_low"] is None else f"{_money(r['cost_low'])} to {_money(r['cost_high'])}"
        if r["fits_memory"]:
            call = f"{r['latency_per_call_s']:,.0f}"
        else:
            call = "-"
        verdict = "no memory" if not r["fits_memory"] else ("yes" if r["total_hours"] <= 24 else "no")
        if r["fits_memory"] and r["timeout_risk"]:
            verdict += ", timeout"
        lines.append(f"{GPUS[r['gpu']]['label']:<20}{'on' if r['thinking'] else 'off':<10}{r['scenario']:<9}"
                     f"{r['gpus_per_server']:>9}{r['months']:>7}{r['batch']:>6}{call:>8}"
                     f"{_hours(r['study_hours']):>9}{_hours(r['total_hours']):>9}{cost:>20}  {verdict}")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Time and cost of the study grid on rented GPUs (a model; see the docstring).")
    ap.add_argument("--runs", type=int, default=50, help="trajectories in the grid (default 50)")
    ap.add_argument("--months", type=int, default=36, help="the horizon; the worst case adds 4 (default 36)")
    ap.add_argument("--workers", type=int, default=50, help="runs in flight at once (default 50)")
    ap.add_argument("--gpu", action="append", choices=sorted(GPUS), help="a GPU type (repeatable; default all)")
    ap.add_argument("--gpus-per-server", action="append", type=int, choices=(1, 2, 4),
                    help="GPUs for each of the six servers (repeatable; default 1)")
    ap.add_argument("--target-hours", type=float, default=24.0, help="the study's time budget (default 24)")
    ap.add_argument("--setup-hours", type=float, default=1.0, help="rented time before the study starts (default 1)")
    ap.add_argument("--sync-hours", type=float, default=0.25, help="rented time for the final sync (default 0.25)")
    ap.add_argument("--seat-timeout", type=float, default=SEAT_TIMEOUT_S, help="seat timeout in seconds (default 600)")
    ap.add_argument("--json", action="store_true", help="print every row as JSON")
    ap.add_argument("--calibrate", choices=sorted(GPUS), help="instead of estimating: the efficiency a rehearsal implies")
    ap.add_argument("--calibrate-gpus", type=int, default=1, help="GPUs in the rehearsal server (default 1)")
    ap.add_argument("--calibrate-batch", type=int, help="sequences decoding at once in the rehearsal")
    ap.add_argument("--calibrate-ctx", type=float, help="average context of those sequences, in tokens")
    ap.add_argument("--measured-decode-tps", type=float, help="measured output tokens per second, server-wide")
    ap.add_argument("--calibrate-input", type=int, help="prompt length of the measured prefill, in tokens")
    ap.add_argument("--measured-prefill-tps", type=float, help="measured prompt tokens per second")
    args = ap.parse_args(argv)

    if args.calibrate:
        if args.calibrate_batch is None or args.calibrate_ctx is None:
            ap.error("--calibrate needs --calibrate-batch and --calibrate-ctx")
        if args.measured_prefill_tps is not None and args.calibrate_input is None:
            ap.error("--measured-prefill-tps needs --calibrate-input")
        out = implied_efficiency(args.calibrate, args.calibrate_gpus, batch=args.calibrate_batch,
                                 ctx_tokens=args.calibrate_ctx, decode_tps=args.measured_decode_tps,
                                 input_tokens=args.calibrate_input, prefill_tps=args.measured_prefill_tps)
        print(json.dumps(out, indent=2) if out else "give --measured-decode-tps and/or --measured-prefill-tps")
        return 0

    keys = args.gpu or list(GPUS)
    sizes = args.gpus_per_server or [1]
    common = dict(runs=args.runs, workers=args.workers, seat_timeout=args.seat_timeout,
                  setup_hours=args.setup_hours, sync_hours=args.sync_hours)

    def named(key: str, gpus: int, name: str, thinking: bool) -> dict:
        row = estimate(key, gpus, scenario_for(name, args.months), thinking=thinking, **common)
        row["scenario"] = name
        return row

    rows = [named(key, gpus, name, thinking)
            for key in keys for thinking in (False, True) for name in SCENARIOS for gpus in sizes]
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    print(f"Study estimate: {args.runs} runs, horizon {args.months} months (worst case "
          f"{horizon_months(args.months)}), {args.workers} runs in flight, {SERVERS} servers "
          f"({DELEGATES} delegates + neighbours), {args.setup_hours:g} h setup, {args.sync_hours:g} h sync.")
    print("Reference model: Qwen3-8B shape, 16.4 GB of bf16 weights, 0.147 MB of KV cache per token.")
    print("Every throughput figure is a MODEL, not a measurement. Calibrate it with --calibrate after the rehearsal.")
    print("")
    print("\n".join(_table(rows)))
    print("")
    print(f"Fewest GPUs per server that finish in {args.target_hours:g} h (central and worst; choices 1, 2, 4):")
    for key in keys:
        for thinking in (False, True):
            for name in ("central", "worst"):
                gpus, row = gpus_needed(key, scenario_for(name, args.months), thinking=thinking,
                                        target_hours=args.target_hours, **common)
                if gpus is None:
                    verdict = "none within 4 GPUs per server"
                else:
                    verdict = (f"{gpus} per server ({SERVERS * gpus} GPUs), {row['total_hours']:,.1f} h, "
                               f"{_money(row['cost_low'])} to {_money(row['cost_high'])}")
                print(f"  {GPUS[key]['label']:<20} thinking {'on ' if thinking else 'off'} {name:<8} {verdict}")
    print("")
    for key in keys:
        print(f"  {GPUS[key]['label']}: {GPUS[key]['source']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
