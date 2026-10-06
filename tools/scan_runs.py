"""Scan every saved run for engine faults, and say what it found.

Two kinds of problem are worth separating, and conflating them is how a bookkeeping bug gets
mistaken for an interesting political event:

    FAULTS      the engine broke a rule about itself: a NaN, a negative army, a counter that does
                not reconcile, an error string the run carried on through. These are bugs.
    SIGNALS     the run recorded something the engine flagged deliberately: a motion blocked on
                an unmet condition, a rejected action, a duplicate foreign effect. These are data,
                and a rise in them is worth reading rather than silencing.

Usage:
    python tools/scan_runs.py                 # every run under runs/
    python tools/scan_runs.py runs/<name>     # one run
    python tools/scan_runs.py --json          # machine readable
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Quantities that are counts or stocks and can never legitimately be negative.
NON_NEGATIVE = ("gold", "debt_dom", "debt_for", "arrears", "food_stock", "state_grain",
                "gdp_real", "cpi", "wage", "population")
# Quantities that must always be finite numbers.
FINITE = ("cpi", "infl", "wage", "gdp_real", "unemployment", "food_ratio", "energy",
          "output_gap", "potential_output", "real_wage", "expected_infl", "confidence",
          "paid_share", "import_scale")
# Cumulative counters that may only ever rise.
MONOTONIC = ("deaths_famine", "deaths_state_violence", "deaths_war_civilian", "deaths_internment",
             "deaths_coups", "soldiers_killed", "emigrated", "births", "deaths_natural")

TEXT_SIGNALS = ("ERROR", "UNKNOWN", "MISMATCH", "NaN", "undefined", "unauthorized", "stale",
                "duplicate", "invalid", "Traceback", "None")


def _finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def load_run(path: str) -> dict:
    out = {"name": os.path.basename(path.rstrip("/\\")), "path": path,
           "faults": [], "signals": Counter(), "months": 0}
    log_path = os.path.join(path, "log.jsonl")
    calls = []
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as exc:
                    out["faults"].append({"where": f"log.jsonl:{lineno}", "kind": "unparsable_log_line",
                                          "detail": str(exc)})
                    continue
                if rec.get("type") == "call":
                    calls.append(rec)
                elif rec.get("type") == "month":
                    out["months"] = max(out["months"], int(rec.get("month", 0)) + 1)
    out["calls"] = calls

    for rec in calls:
        where = f"call month {rec.get('month')} {rec.get('member')} {rec.get('phase')}"
        if rec.get("error"):
            out["faults"].append({"where": where, "kind": "call_error", "detail": str(rec["error"])[:300]})
        if rec.get("quota"):
            out["signals"]["quota_pause"] += 1
        if rec.get("refusal"):
            out["signals"]["refusal"] += 1
        if rec.get("format_retry"):
            out["signals"]["format_retry"] += 1
        if int(rec.get("attempts", 1)) > 1:
            out["signals"]["retried_call"] += 1
        if rec.get("raw") in (None, "", "(no answer)") or rec.get("served_model") in (None, ""):
            out["signals"]["empty_or_unserved_call"] += 1

    ckpt = os.path.join(path, "checkpoint.json")
    if os.path.exists(ckpt):
        try:
            with open(ckpt, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            out["faults"].append({"where": "checkpoint.json", "kind": "unparsable_checkpoint",
                                  "detail": str(exc)})
            return out
        world = data.get("world", data)
        _check_world(out, world)
    return out


def _check_world(out: dict, world: dict) -> None:
    econ = world.get("econ") or {}

    def fault(kind, detail):
        out["faults"].append({"where": "checkpoint", "kind": kind, "detail": detail})

    for name in FINITE:
        if name in econ and not _finite(econ[name]):
            fault("non_finite_state", f"econ.{name} = {econ[name]!r}")
    for name in NON_NEGATIVE:
        value = econ.get(name)
        if value is None:
            continue
        if not _finite(value):
            fault("non_finite_state", f"econ.{name} = {value!r}")
        elif float(value) < 0:
            fault("negative_impossible", f"econ.{name} = {value!r}")

    mil = world.get("mil") or {}
    for force in ("army", "navy", "police"):
        f = mil.get(force) or {}
        if not _finite(f.get("size", 0)):
            fault("non_finite_state", f"mil.{force}.size = {f.get('size')!r}")
        elif float(f.get("size", 0)) < 0:
            fault("negative_impossible", f"mil.{force}.size = {f.get('size')!r}")

    counters = world.get("counters") or {}
    history = world.get("history") or []
    previous = {}
    for row in history:
        row_counters = row.get("counters") or {}
        for key in MONOTONIC:
            if key in previous and key in row_counters:
                if float(row_counters[key]) < float(previous[key]) - 1e-6:
                    fault("counter_went_backwards",
                          f"{key} fell from {previous[key]} to {row_counters[key]} in month {row.get('month')}")
        previous = {**previous, **row_counters}

    integrity = world.get("integrity") or {}
    if integrity.get("warnings"):
        for warning in integrity["warnings"]:
            out["signals"][f"integrity:{warning.get('code', 'unknown')}"] += 1

    for entry in world.get("audit_errors") or []:
        out["signals"][f"engine_error:{entry.get('code')}"] += 1
        if entry.get("severity") == "error":
            fault("engine_error_severe", f"{entry.get('code')}: {entry.get('message')}")

    # Motions: a passed motion that never executed is a signal, not a fault — but a motion with
    # no canonical status at all is a fault, because downstream readers infer one from "not passed".
    for row in history:
        for motion in (row.get("motions") or []):
            status = motion.get("status") or motion.get("vote_status")
            if not status:
                fault("motion_without_status",
                      f"month {row.get('month')} motion {motion.get('id')} has no canonical status")
            if motion.get("passed") and motion.get("execution_status") is None and status == "PASSED":
                out["signals"]["passed_without_execution_record"] += 1


def scan(paths: list[str]) -> dict:
    runs = [load_run(p) for p in paths]
    totals = Counter()
    for run in runs:
        for key, value in run["signals"].items():
            totals[key] += value
    elapsed = Counter()
    for run in runs:
        elapsed["calls"] += len(run.get("calls", []))
        elapsed["months"] += run["months"]
    return {"runs": runs, "signals": dict(totals.most_common()), "totals": dict(elapsed),
            "runs_with_faults": sum(1 for r in runs if r["faults"])}


def run_dirs(base: str) -> list[str]:
    if base != os.path.join(ROOT, "runs"):
        return [base] if os.path.isdir(os.path.join(base, "log.jsonl")) or \
            os.path.exists(os.path.join(base, "checkpoint.json")) else []
    out = []
    for name in sorted(os.listdir(base)):
        full = os.path.join(base, name)
        if os.path.isdir(full) and os.path.exists(os.path.join(full, "checkpoint.json")):
            out.append(full)
    return out


def _print(report: dict) -> None:
    bad = [r for r in report["runs"] if r["faults"]]
    print(f"scanned {len(report['runs'])} runs, {report['totals']['calls']:,} calls, "
          f"{report['totals']['months']:,} simulated months")
    print(f"runs with faults: {len(bad)}\n")
    if bad:
        kinds = Counter(f["kind"] for r in bad for f in r["faults"])
        print("FAULTS by kind:")
        for kind, count in kinds.most_common():
            print(f"  {kind:<32} {count}")
        print()
        for run in bad[:12]:
            print(f"  {run['name']}:")
            for f in run["faults"][:6]:
                print(f"     [{f['kind']}] {f['where']}: {f['detail'][:140]}")
            if len(run["faults"]) > 6:
                print(f"     ... and {len(run['faults']) - 6} more")
    if report["signals"]:
        print("\nSIGNALS (recorded deliberately, not faults):")
        for key, count in list(report["signals"].items())[:30]:
            print(f"  {key:<40} {count}")


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    base = args[0] if args else os.path.join(ROOT, "runs")
    report = scan(run_dirs(base))
    if "--json" in argv:
        print(json.dumps(report, indent=1, default=str)[:200000])
    else:
        _print(report)
    return 1 if report["runs_with_faults"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
