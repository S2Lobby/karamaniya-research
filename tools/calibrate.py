"""Do the world's dynamics stay in plausible ranges across many seeds and simple councils? (engine 18)

    python tools/calibrate.py --seeds 1-10 --months 36 --modes passive,scripted,hawk,dove [--out report.json]

Each seed and mode is one council of stand-ins (baseline.py; no model is called), played out on that seed in a
temporary folder, and every check in karamaniya/calibration.py is evaluated on the finished world. For each check the
table gives its range, how many runs it applied to and passed, the smallest, median and largest figure, and the run that
came closest to failing it. The exit code is 0 when every check passes in at least 90% of the runs it applies to. A run
that raises is a failed run for every check, and makes the exit code 1 whatever the shares. --out writes every figure,
run by run, as JSON. docs/CALIBRATION.md says how to read the table and what to do when a check fails.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import statistics
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import baseline, calibration, versions  # noqa: E402
from karamaniya.manifest import RUNTIME_SOURCE_FINGERPRINT  # noqa: E402

COUNCIL = os.path.join(ROOT, "council.scripted.toml")
PASS_SHARE = 0.9    # a check passes the tool when it passes in at least this share of the runs it applies to
FORMAT = 1


def parse_seeds(text: str) -> list:
    """'1-10' is seeds 1 to 10; '1,3,7-9' is 1, 3, 7, 8 and 9."""
    seeds = []
    for part in text.split(","):
        match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", part)
        if not match:
            raise argparse.ArgumentTypeError(f"not a seed or a range of seeds: {part!r}")
        lo = int(match.group(1))
        hi = int(match.group(2) or lo)
        if hi < lo:
            raise argparse.ArgumentTypeError(f"empty range of seeds: {part!r}")
        seeds.extend(range(lo, hi + 1))
    return list(dict.fromkeys(seeds))


def parse_modes(text: str) -> list:
    modes = [m.strip() for m in text.split(",") if m.strip()]
    if not modes or any(m not in baseline.RULE_MODES for m in modes):
        raise argparse.ArgumentTypeError(f"modes are {', '.join(baseline.RULE_MODES)}; got {text!r}")
    return list(dict.fromkeys(modes))


def fmt(value, unit: str) -> str:
    if value is None:
        return "-"
    if unit == "pct":
        return f"{value * 100:.1f}%"
    if unit == "soldiers":
        return f"{value:,.0f}"
    return f"{value:.3f}"


def describe_range(low, high, unit: str) -> str:
    if low is None:
        return f"at most {fmt(high, unit)}"
    if high is None:
        return f"at least {fmt(low, unit)}"
    return f"{fmt(low, unit)} to {fmt(high, unit)}"


def play(settings: dict, seeds: list, modes: list, months: int, runs_dir: str) -> list:
    """Every seed under every council mode, one run each. A run that raises is recorded, not hidden."""
    runs = []
    total = len(seeds) * len(modes)
    for seed in seeds:
        for mode in modes:
            record = {"seed": seed, "mode": mode, "months": months}
            try:
                world, seconds = calibration.simulate(settings, seed, mode, months, runs_dir)
                record.update(seconds=round(seconds, 2), history_months=len(world.history), error=None,
                              results=calibration.evaluate(world),
                              summary=baseline.summary(world.history, world.outcome),
                              monthly=baseline.monthly(world.history),
                              rivals={rid: round(r.gdp_real / r.gdp_real0, 4)
                                      for rid, r in world.rivals.items() if r.gdp_real0 > 0},
                              rivals_monthly={rid: [round(float(row["nations"][rid]["output_annual"])
                                                          / 12 / r.gdp_real0, 4) for row in world.history]
                                              for rid, r in world.rivals.items() if r.gdp_real0 > 0})
                failed = [name for name, r in record["results"].items() if r["applies"] and not r["ok"]]
                verdict = f"failed: {', '.join(failed)}" if failed else "every check inside its range"
            except Exception as exc:  # a run that breaks is a finding; it is reported and counted as a failure
                record.update(seconds=None, history_months=0, results=None, summary=None, monthly=None, rivals=None,
                              rivals_monthly=None, error=f"{type(exc).__name__}: {exc}")
                verdict = f"ERROR {record['error']}"
            runs.append(record)
            took = f"{record['seconds']:.1f} s" if record["seconds"] is not None else "-"
            print(f"[{len(runs)}/{total}] seed {seed:>3} {mode:<9} {took:>8}  {verdict}", flush=True)
    return runs


def summarise(runs: list, name: str, check, months: int) -> dict:
    """One check over every run: how many runs it applied to and passed, its figures, and the worst run."""
    low, high = check.bounds(months)
    judged = []    # (margin, seed, mode, figure, ok) for every run the check applied to; an errored run is -inf
    skipped = 0
    for run in runs:
        if run["error"] is not None:
            judged.append((-math.inf, run["seed"], run["mode"], None, False))
            continue
        result = run["results"][name]
        if not result["applies"]:
            skipped += 1
            continue
        judged.append((result["margin"], run["seed"], run["mode"], result["value"], result["ok"]))
    figures = [figure for _, _, _, figure, _ in judged if figure is not None]
    passed = sum(1 for *_, ok in judged if ok)
    worst = min(judged, key=lambda j: j[0]) if judged else None
    return {"unit": check.unit, "reason": check.reason, "low": low, "high": high,
            "applied": len(judged), "passed": passed, "skipped": skipped,
            "ok": bool(judged) and passed / len(judged) >= PASS_SHARE,
            "smallest": min(figures) if figures else None,
            "median": statistics.median(figures) if figures else None,
            "largest": max(figures) if figures else None,
            "worst": ({"seed": worst[1], "mode": worst[2], "value": worst[3], "margin": (
                None if math.isinf(worst[0]) else worst[0])} if worst else None)}


def print_table(checks: dict, runs: list, months: int) -> None:
    print()
    print(f"{'check':<23} {'range':<21} {'passed':>8} {'skipped':>7} {'smallest':>11} {'median':>11} "
          f"{'largest':>11}  worst run")
    for name, s in checks.items():
        if s["applied"] == 0:
            print(f"{name:<23} {describe_range(s['low'], s['high'], s['unit']):<21} {'0/0':>8} {s['skipped']:>7} "
                  f"{'-':>11} {'-':>11} {'-':>11}  not assessed: no run qualified")
            continue
        worst = s["worst"]
        if worst["value"] is None:
            where = f"seed {worst['seed']} {worst['mode']}: error"
        else:
            where = f"seed {worst['seed']} {worst['mode']}: {fmt(worst['value'], s['unit'])}"
        print(f"{name:<23} {describe_range(s['low'], s['high'], s['unit']):<21} "
              f"{str(s['passed']) + '/' + str(s['applied']):>8} {s['skipped']:>7} "
              f"{fmt(s['smallest'], s['unit']):>11} {fmt(s['median'], s['unit']):>11} "
              f"{fmt(s['largest'], s['unit']):>11}  {where}")
    seconds = [r["seconds"] for r in runs if r["seconds"] is not None]
    if seconds:
        print(f"\ntime: {sum(seconds):.1f} s for {len(runs)} runs, {statistics.mean(seconds):.1f} s a run on average, "
              f"{max(seconds):.1f} s the slowest")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=parse_seeds, required=True, help="e.g. 1-10, or 1,3,7-9")
    ap.add_argument("--months", type=int, default=calibration.REFERENCE_MONTHS, help="months per run (default 36)")
    ap.add_argument("--modes", type=parse_modes, default=list(baseline.RULE_MODES),
                    help=f"councils to play, of {', '.join(baseline.RULE_MODES)} (default: all)")
    ap.add_argument("--out", help="write every figure, run by run, to this JSON file")
    args = ap.parse_args(argv)
    if not 1 <= args.months <= 120:
        ap.error("--months must be between 1 and 120")

    started = time.perf_counter()
    settings = calibration.scripted_settings(COUNCIL)
    print(f"calibration: {len(args.seeds)} seeds ({args.seeds[0]}-{args.seeds[-1]}) x {len(args.modes)} councils "
          f"({', '.join(args.modes)}), {args.months} months each, world engine {versions.WORLD_ENGINE}", flush=True)
    tmp = tempfile.mkdtemp(prefix="karamaniya-calibrate-")
    try:
        runs = play(settings, args.seeds, args.modes, args.months, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    seconds = time.perf_counter() - started

    checks = {name: summarise(runs, name, check, args.months) for name, check in calibration.CHECKS.items()}
    print_table(checks, runs, args.months)
    errors = [r for r in runs if r["error"] is not None]
    failing = [name for name, s in checks.items() if not s["ok"]]
    if errors:
        print(f"\nFAIL: {len(errors)} run(s) raised an error; see the lines above.")
    if failing:
        print(f"FAIL: {', '.join(failing)} below the {PASS_SHARE:.0%} pass share (or not assessed).")
    if not errors and not failing:
        print(f"PASS: every check passes in at least {PASS_SHARE:.0%} of the runs it applies to.")

    if args.out:
        report = {"format": FORMAT, "world_engine": versions.WORLD_ENGINE, "agent_prompt": versions.AGENT_PROMPT,
                  "source_fingerprint": RUNTIME_SOURCE_FINGERPRINT, "council": os.path.basename(COUNCIL),
                  "seeds": args.seeds, "modes": args.modes, "months": args.months, "pass_share": PASS_SHARE,
                  "seconds": round(seconds, 2), "checks": checks, "runs": runs}
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(report, f, indent=1)
            f.write("\n")
        print(f"wrote {args.out}")
    return 0 if not errors and not failing else 1


if __name__ == "__main__":
    raise SystemExit(main())
