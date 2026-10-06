"""The run-analysis teammate: scan runs and report engine bugs and what delegates could not do.

    python -m karamaniya analyze                 # every run under runs/
    python -m karamaniya analyze --recent 12     # the twelve most recently written runs
    python -m karamaniya analyze --run <id>      # one run, with every blocked intent listed
    python -m karamaniya analyze --json out.json # also write machine-readable findings

It reads each run's own files (config.json, checkpoint.json, log.jsonl) and never calls a model, so
it is free and reproducible. It answers two questions the raw reports do not:

1. Where did the engine behave degenerately -- a series that only ever moves one way whatever the
   council does, a quantity pinned at a constant, a state the world is not allowed to hold?
2. What did the delegates try to do that the harness could not express -- the gaps worth closing --
   kept strictly apart from rejections that were correct (a duplicate, no political capital, a
   statistic with no source behind it). Conflating the two is how a real limit gets mistaken for a
   delegate error, or the other way round.
"""
from __future__ import annotations

import json
import math
import os
import sys
from statistics import median

# Series that should move with policy and events. A variable that drifts one way in almost every
# run, whatever the council chose, is an engine attractor worth explaining rather than a finding.
DYNAMICS = ("approval", "unrest", "indep", "army", "infl_yoy", "food_ratio", "gdp_idx",
            "deficit_gdp", "arrears_gdp", "paid_share", "democracy", "unemployment", "hunger")

# Intents the harness could not express: a delegate named a real thing the engine has no word for.
# These are the "the engine limited them" cases -- the ones to fix.
GAP_CODES = {
    "UNKNOWN_LEVER", "UNKNOWN_REGION", "UNKNOWN_OFFICE", "UNKNOWN_FUNDING", "UNKNOWN_TYPE",
    "UNKNOWN_MEASURE", "UNKNOWN_SCOPE", "UNKNOWN_DIPLOMACY", "UNKNOWN_TARGET",
    "ACTION_NOT_VALID_FOR_TARGET", "NO_STRUCTURED_ACTION", "NO_TARGET",
}
# Faithfulness and correctness guards. Mostly rejections the harness *should* make, but a spike in
# one of them (or a recurring example) can mean the guard is over-firing, so they are reported apart.
GUARD_CODES = {
    "MOTION_ACTION_MISMATCH", "MOTION_ACTION_MISMATCH_AFTER_REPAIR", "MOTION_ACTION_MISMATCH_UNREPAIRED",
    "MOTION_CONDITION_MISMATCH", "NUMERIC_GROUNDING_ERROR", "EXECUTION_BLOCKED_CONDITION",
    "BAD_VALUE", "BAD_AMOUNT",
}
# Ordinary governance friction: the delegate erred or a legitimate constraint bound. Not a bug.
PROCEDURAL_CODES = {
    "SAME_MOTION_TABLED", "SUBSTANTIALLY_DUPLICATES", "INSUFFICIENT_CAPITAL", "MOTION_WITHDRAWN",
    "MOTION_NOT_HEARD", "NOT_PASSED", "SESSION_VOID", "DUPLICATE_ACTION", "ALREADY_SET",
    "NO_EXISTING_DEAL",
    "ALREADY_HOLDS_OFFICE", "ALREADY_VACANT", "RECENTLY_AUDITED", "NOT_A_MEMBER",
    "UNAUTHORIZED_OFFICE_ACTION",
}


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _iter_log(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _bucket(code: str) -> str:
    if code in GAP_CODES:
        return "gap"
    if code in GUARD_CODES:
        return "guard"
    if code in PROCEDURAL_CODES:
        return "procedural"
    return "other"


def _mono_share(vals):
    """Fraction of month-to-month steps moving the same way; >=0.9 over many months is a smell."""
    if len(vals) < 6:
        return None
    diffs = [b - a for a, b in zip(vals, vals[1:])]
    up = sum(1 for d in diffs if d > 1e-9)
    down = sum(1 for d in diffs if d < -1e-9)
    n = len(diffs) or 1
    return max(up, down) / n


def _check_saved_scorecard(run_dir: str, hist: list, anomalies: list) -> None:
    """Catch a saved scorecard that no longer describes the checkpoint beside it.

    This is a cross-artifact check only: both values come from the run's saved world history and
    scorecard, so it does not need call or prompt logs. Older runs without a scorecard are fine.
    """
    path = os.path.join(run_dir, "scorecard.json")
    if not os.path.exists(path):
        return
    scorecard = _read_json(path)
    if scorecard is None:
        anomalies.append("scorecard.json is present but unreadable")
        return
    if not isinstance(scorecard, dict):
        anomalies.append("scorecard.json is not an object")
        return
    country = scorecard.get("country") or {}
    if not isinstance(country, dict):
        anomalies.append("scorecard.json has no country object")
        return
    if not hist:
        return

    if isinstance(country.get("months_run"), int) and country["months_run"] != len(hist):
        anomalies.append(
            f"scorecard reports {country['months_run']} months but checkpoint history has {len(hist)} rows")

    last = hist[-1]
    checks = {
        "final_inflation_yoy": "infl_yoy",
        "final_approval": "approval",
        "final_output": "gdp_idx",
        "democracy_final": "democracy",
    }
    for card_key, history_key in checks.items():
        recorded = country.get(card_key)
        current = last.get(history_key) if isinstance(last, dict) else None
        if (isinstance(recorded, (int, float)) and isinstance(current, (int, float))
                and not math.isclose(float(recorded), float(current), rel_tol=1e-9, abs_tol=1e-9)):
            anomalies.append(
                f"scorecard {card_key}={recorded!r} disagrees with checkpoint history "
                f"{history_key}={current!r}")


def analyze_run(run_dir: str, detail: bool = False) -> dict:
    """Everything one run's own files say about engine health and harness friction."""
    out = {"id": os.path.basename(run_dir.rstrip("/\\")), "months": 0, "dynamics": [],
           "anomalies": [], "friction": {"gap": 0, "guard": 0, "procedural": 0, "other": 0},
           "codes": {}, "gap_examples": [], "calls": {"total": 0, "refusals": 0, "errors": 0,
                                                       "format_retries": 0, "quota": 0}}
    ck = _read_json(os.path.join(run_dir, "checkpoint.json")) or {}
    hist = (ck.get("world") or {}).get("history") or []
    out["months"] = len(hist)

    # Engine dynamics: flag series that only ever move one way, and constants that should vary.
    for var in DYNAMICS:
        vals = [h[var] for h in hist if isinstance(h.get(var), (int, float))]
        if len(vals) < 6:
            continue
        share = _mono_share(vals)
        if share and share >= 0.9:
            direction = "up" if vals[-1] >= vals[0] else "down"
            out["dynamics"].append({"var": var, "drift": direction, "monotone": round(share, 2),
                                    "start": round(vals[0], 4), "end": round(vals[-1], 4)})
        if max(vals) - min(vals) < 1e-6:
            out["anomalies"].append(f"{var} is pinned at {vals[0]!r} for all {len(vals)} months")
    # States the world is not allowed to hold.
    econ = (ck.get("world") or {}).get("econ") or {}
    for key in ("gold", "arrears", "debt_dom"):
        v = econ.get(key)
        if isinstance(v, (int, float)) and v < 0:
            out["anomalies"].append(f"econ.{key} is negative ({v})")

    _check_saved_scorecard(run_dir, hist, out["anomalies"])

    # Harness friction and call health, straight from the month and call records.
    for rec in _iter_log(os.path.join(run_dir, "log.jsonl")):
        kind = rec.get("type")
        if kind == "call":
            out["calls"]["total"] += 1
            if rec.get("refusal"):
                out["calls"]["refusals"] += 1
            if rec.get("error"):
                out["calls"]["errors"] += 1
            if rec.get("format_retry"):
                out["calls"]["format_retries"] += 1
            if rec.get("quota"):
                out["calls"]["quota"] += 1
        elif kind == "month":
            for rm in rec.get("rejected_motions") or []:
                code = str(rm.get("reason_code", "UNSPECIFIED"))
                bucket = _bucket(code)
                out["friction"][bucket] += 1
                out["codes"][code] = out["codes"].get(code, 0) + 1
                if bucket == "gap":
                    mo = rm.get("motion") or {}
                    out["gap_examples"].append({
                        "code": code, "type": mo.get("type"), "subject": mo.get("subject"),
                        "value": mo.get("value"), "member": rm.get("member"),
                        "text": str(mo.get("text", ""))[:120],
                        "why": str(rm.get("explanation", ""))[:160]})
            for key in ("unauthorized_orders", "grounding"):
                v = rec.get(key)
                if isinstance(v, list):
                    out["friction"]["guard"] += len(v)
    return out


def discover(runs_dir: str, recent: int | None = None) -> list:
    dirs = [os.path.dirname(p) for p in _glob_logs(runs_dir)]
    dirs.sort(key=lambda d: os.path.getmtime(d), reverse=True)
    return dirs[:recent] if recent else dirs


def _glob_logs(runs_dir: str) -> list:
    if not os.path.isdir(runs_dir):
        return []
    return [os.path.join(runs_dir, name, "log.jsonl") for name in os.listdir(runs_dir)
            if os.path.isdir(os.path.join(runs_dir, name))]


def aggregate(runs: list) -> dict:
    """Totals across runs, plus how often each variable drifts one way (the engine-health signal)."""
    agg = {"runs": len(runs), "friction": {"gap": 0, "guard": 0, "procedural": 0, "other": 0},
           "codes": {}, "calls": {"total": 0, "refusals": 0, "errors": 0, "format_retries": 0, "quota": 0},
           "drift": {}, "anomalous_runs": 0}
    for r in runs:
        for b, n in r["friction"].items():
            agg["friction"][b] += n
        for code, n in r["codes"].items():
            agg["codes"][code] = agg["codes"].get(code, 0) + n
        for k, v in r["calls"].items():
            agg["calls"][k] += v
        if r["anomalies"]:
            agg["anomalous_runs"] += 1
        for d in r["dynamics"]:
            agg["drift"].setdefault(d["var"], []).append(d["drift"])
    agg["drift"] = {var: {"runs_drifting": len(dirs), "of_runs": len(runs),
                          "dominant": max(set(dirs), key=dirs.count) if dirs else ""}
                    for var, dirs in agg["drift"].items()}
    return agg


def _report(runs: list, agg: dict, detail_run: str | None) -> str:
    L = []
    L.append(f"Karamaniya run analysis — {agg['runs']} run(s) scanned, no model calls")
    L.append("")
    L.append("== Harness friction (rejected intents), by whether it was the harness's fault ==")
    L.append(f"  GAP  (engine could not express the intent) : {agg['friction']['gap']}")
    L.append(f"  GUARD (faithfulness/correctness check)     : {agg['friction']['guard']}")
    L.append(f"  PROCEDURAL (correct governance rejection)  : {agg['friction']['procedural']}")
    L.append(f"  OTHER                                      : {agg['friction']['other']}")
    if agg["codes"]:
        L.append("\n  top rejection codes:")
        for code, n in sorted(agg["codes"].items(), key=lambda kv: -kv[1])[:12]:
            L.append(f"    {n:5d}  [{_bucket(code):10}] {code}")
    L.append("\n== Engine health: variables that drift one way across runs (attractors to explain) ==")
    if agg["drift"]:
        for var, d in sorted(agg["drift"].items(), key=lambda kv: -kv[1]["runs_drifting"]):
            L.append(f"  {var:12} drifts {d['dominant']:>4} in {d['runs_drifting']}/{d['of_runs']} runs")
    else:
        L.append("  none flagged")
    L.append(f"\n== Call health == total {agg['calls']['total']}  refusals {agg['calls']['refusals']}  "
             f"errors {agg['calls']['errors']}  format-retries {agg['calls']['format_retries']}  "
             f"quota {agg['calls']['quota']}")
    if agg["anomalous_runs"]:
        L.append(f"\n== Anomalies: {agg['anomalous_runs']} run(s) with impossible/pinned states ==")
        for r in runs:
            if r["anomalies"]:
                L.append(f"  {r['id']}: " + "; ".join(r["anomalies"][:4]))
    gap_runs = [r for r in runs if r["gap_examples"]]
    if gap_runs:
        L.append("\n== What delegates tried that the engine could not express ==")
        for r in gap_runs:
            L.append(f"  run {r['id']}:")
            for g in r["gap_examples"][: (40 if detail_run == r["id"] else 6)]:
                L.append(f"    [{g['code']}] {g['member']} {g['type']}/{g['subject']}"
                         + (f"={g['value']}" if g['value'] else "") + f" :: {g['text']!r}")
                if g["why"]:
                    L.append(f"        why: {g['why']}")
    return "\n".join(L)


def analyze(runs_dir: str = "runs", recent: int | None = None, run_id: str | None = None,
            json_out: str | None = None, verbose: bool = False) -> dict:
    # A run's prose carries arbitrary Unicode (non-breaking hyphens, curly quotes, em dashes) that a
    # Windows console (cp1252) cannot encode; report and JSON must never crash on it.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    if run_id:
        dirs = [os.path.join(runs_dir, run_id)]
    else:
        dirs = discover(runs_dir, recent)
    runs = [analyze_run(d, detail=(d == dirs[0] and bool(run_id))) for d in dirs if os.path.isdir(d)]
    agg = aggregate(runs)
    print(_report(runs, agg, run_id))
    if json_out:
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump({"aggregate": agg, "runs": runs}, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nwrote {json_out}")
    return {"aggregate": agg, "runs": runs}
