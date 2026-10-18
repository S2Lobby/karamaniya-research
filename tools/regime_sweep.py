"""Calibration sweep for the regime-realism world (engine 33): scripted councils, both uprising models.

    python tools/regime_sweep.py [--seeds 1-12] [--months 36] [--modes scripted,hawk,dove]
                                 [--models legacy,legitimacy] [--workers N] [--out reports/regime_sweep.json]

The plan's RR5 asks for scripted sweeps over seeds 1-12 of the stand-in personas and the all-hawk and all-dove
councils (baseline.py's `scripted`, `hawk`, `dove` modes), under both `uprising_model` settings, recording exits,
months, crackdowns attempted and failed, honeymoons and concession relief. No model is called; every seat is a
`scripted` stand-in, and the neighbours are the stand-in cabinets, exactly as a baseline is run.

Each run is a real engine run through `runner.new_run`, so the option travels the same config/runner path a council
does. Runs are independent processes (Windows spawns them); each gets its own temporary run folder, removed when its
figures are read. The output JSON keeps one record per run and the band check:

- a quiet run (one that never enters the uprising zone, `uprising_check.thresholds_met` false all months) never ends
  in revolution;
- in the stress pairs (the same mode and seed where the legacy engine entered the uprising zone) the revolution
  share under `legitimacy` is between half and all of the legacy share;
- a national crackdown at security .55-.65 fails in 20-40% of cases.

The third band is checked twice: from the sweep's observed crackdowns (when any occurred at that security) and
analytically from the crackdown formula's constants over loyalty .55-.65 and bond .2-.3, which are the RR0 recorded
run's force values. The analytical census is the calibration target: scripted councils may not choose a lethal
response often enough to fill a band by themselves. A band with no observations says so rather than passing silently.

The RR5 constants were set against the census: `uprising.CRACKDOWN_BASE` is .64, which puts the both-obey failure
chance at 29.0-39.6% across that force range (inside the band); at the RR1 draft's .62 it was 32.4-42.6% (outside at
the low end). The sweep prints both so the change is visible in the report.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya import baseline, regime_relief, uprising, versions  # noqa: E402
from karamaniya.config import normalize_config  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402

SEEDS = list(range(1, 13))
MODES = ("scripted", "hawk", "dove")
MODELS = ("legacy", "legitimacy")
MONTHS = 36
REVOLUTIONS = ("revolution", "revolution_union")
SECURITY_BAND = (0.55, 0.65)


# ---- one run ------------------------------------------------------------------------------------
def _run(job: dict) -> dict:
    """Run one scripted council and return its record. Runs in a worker process."""
    mode, seed, model, months = job["mode"], job["seed"], job["model"], job["months"]
    raw = baseline._config({}, 5, mode, months)
    raw["run"].update(seed=seed, uprising_model=model)
    cfg = normalize_config(raw, raw["source"])
    tmp = tempfile.mkdtemp(prefix=f"regime-sweep-{mode}-{model}-{seed}-")
    try:
        path = new_run(cfg, runs_dir=tmp, name=f"{mode}-{model}-s{seed}", quiet=True, check=False)
        world, _council, meta = RunStore(path).load_checkpoint()
        record = summary(mode, seed, model, world.history, world.outcome, world.institutions, world.events)
        record["stopped"] = str((meta or {}).get("stopped") or "")
        return record
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def summary(mode: str, seed: int, model: str, history: list, outcome: dict,
            institutions: dict | None = None, events: list | None = None) -> dict:
    """The figures the sweep records for one run, from its history rows and final state."""
    rows = list(history or [])
    outcome = dict(outcome or {})
    institutions, events = institutions or {}, list(events or [])
    checks = [r["uprising_check"] for r in rows if isinstance(r.get("uprising_check"), dict)]
    zone = [c for c in checks if c.get("thresholds_met")]
    fired = [c for c in zone if c.get("fired")]
    crackdowns = [c["crackdown"] for c in checks if isinstance(c.get("crackdown"), dict)]
    in_band = [c for c in checks if isinstance(c.get("crackdown"), dict)
               and c.get("security") is not None
               and SECURITY_BAND[0] <= float(c["security"]) <= SECURITY_BAND[1]]
    outcomes = Counter(c.get("outcome", "") for c in crackdowns)
    band_outcomes = Counter(c["crackdown"].get("outcome", "") for c in in_band)
    changes = ((institutions.get("regime_relief") or {}).get("head_changes") or [])
    talks = [e for e in events if e.get("kind") == "protest" and "concession_credibility" in e]
    credits = [float(e.get("concession_credibility") or 0.0) for e in talks]
    return {
        "mode": mode, "seed": seed, "model": model,
        "outcome": outcome.get("type", ""),
        "outcome_month": outcome.get("month"),
        "months": len(rows),
        "zone_months": len(zone),
        "fired_months": len(fired),
        "lethal_months": sum(1 for r in rows if (r.get("policy") or {}).get("protest_response") == "lethal"),
        "crackdowns": {
            "attempted": len(crackdowns),
            "failed": len(crackdowns) - outcomes.get("massacre", 0),
            "outcomes": dict(outcomes),
            "in_security_band": len(in_band),
            "failed_in_security_band": len(in_band) - band_outcomes.get("massacre", 0),
            "band_outcomes": dict(band_outcomes),
        },
        "honeymoons": {
            "changes": len(changes),
            "granted": sum(1 for c in changes if c.get("granted")),
            "blocked": dict(Counter(c.get("why", "") for c in changes if not c.get("granted"))),
        },
        "talks": {
            "count": len(talks),
            "with_concessions": sum(1 for c in credits if c > 0),
            "mean_concession_credibility": round(sum(credits) / len(credits), 4) if credits else 0.0,
            "max_concession_credibility": round(max(credits), 4) if credits else 0.0,
        },
    }


# ---- bands --------------------------------------------------------------------------------------
def crackdown_census() -> dict:
    """The both-obey failure chance over the RR0 force range, from the formula's constants.

    The range is loyalty .55-.65 with bond .2-.3, unrest below the .6 penalty, and no arrears. Each force's obedience
    is the module's own function, so the census moves with the constants. The failure chance is
    `1 - obey(police) * obey(army)`; with equal forces that is `1 - p^2`.
    """
    class Force:
        def __init__(self, loyalty, bond):
            self.loyalty, self.bond, self.arrears = loyalty, bond, 0.0

    chances = []
    for loyalty in (0.55, 0.60, 0.65):
        for bond in (0.2, 0.25, 0.3):
            p = uprising.obey_probability(Force(loyalty, bond), 0.5)
            chances.append(1.0 - p * p)
    return {"base": uprising.CRACKDOWN_BASE,
            "min_failure": round(min(chances), 4), "max_failure": round(max(chances), 4),
            "band": list(SECURITY_BAND)}


def bands(records: list) -> dict:
    """The three RR5 bands, from the sweep's records. Each says how many observations it rests on."""
    quiet = [r for r in records if r.get("zone_months") == 0]
    quiet_rev = [r for r in quiet if r.get("outcome") in REVOLUTIONS]
    quiet_band = {"quiet_runs": len(quiet), "quiet_revolutions": len(quiet_rev),
                  "met": not quiet_rev, "revolution_runs": [f"{r['mode']}-s{r['seed']} ({r['model']})"
                                                            for r in quiet_rev]}

    by_pair = {}
    for r in records:
        by_pair.setdefault((r["mode"], r["seed"]), {})[r["model"]] = r
    stress = [pair for pair in by_pair.values()
              if (pair.get("legacy") or {}).get("zone_months", 0) > 0]
    legacy_rev = sum(1 for pair in stress if pair["legacy"].get("outcome") in REVOLUTIONS)
    legit_rev = sum(1 for pair in stress
                    if (pair.get("legitimacy") or {}).get("outcome") in REVOLUTIONS)
    stress_band = {"pairs": len(stress), "legacy_revolutions": legacy_rev, "legitimacy_revolutions": legit_rev,
                   "legacy_share": round(legacy_rev / len(stress), 4) if stress else None,
                   "legitimacy_share": round(legit_rev / len(stress), 4) if stress else None,
                   "met": None}
    if stress:
        legacy_share = legacy_rev / len(stress)
        legit_share = legit_rev / len(stress)
        stress_band["met"] = (legacy_share == 0 and legit_share == 0) or (
            legacy_share > 0 and 0.5 * legacy_share <= legit_share <= legacy_share)

    attempts = sum(r["crackdowns"]["in_security_band"] for r in records if r["model"] == "legitimacy")
    failures = sum(r["crackdowns"]["failed_in_security_band"] for r in records if r["model"] == "legitimacy")
    observed = {"attempts": attempts, "failures": failures,
                "failure_share": round(failures / attempts, 4) if attempts else None,
                "met": (0.20 <= failures / attempts <= 0.40) if attempts else None}
    census = crackdown_census()
    census["met"] = 0.20 <= census["min_failure"] and census["max_failure"] <= 0.40
    return {"quiet_no_revolution": quiet_band, "legitimacy_against_legacy": stress_band,
            "crackdown_failure": {"observed": observed, "census": census,
                                  "met": bool(observed["met"] is True and census["met"])}}


# ---- command line -------------------------------------------------------------------------------
def _parse_ints(text: str) -> list:
    out = []
    for part in str(text).split(","):
        part = part.strip()
        if "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
            out.extend(range(a, b + 1))
        elif part:
            out.append(int(part))
    return out


def _parse_names(text: str, allowed: tuple) -> list:
    out = [x.strip() for x in str(text).split(",") if x.strip()]
    bad = [x for x in out if x not in allowed]
    if bad:
        raise SystemExit(f"unknown names {bad}; choose from {list(allowed)}")
    return out


def run_sweep(seeds: list, modes: list, models: list, months: int, workers: int, echo=None) -> dict:
    jobs = [{"mode": mode, "seed": seed, "model": model, "months": months}
            for model in models for mode in modes for seed in seeds]
    records, failures = [], []
    done = 0
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run, job): job for job in jobs}
        for fut in concurrent.futures.as_completed(futures):
            job = futures[fut]
            done += 1
            try:
                records.append(fut.result())
            except Exception as exc:                     # a failed run is data too, not a silent zero
                failures.append({**job, "error": f"{type(exc).__name__}: {exc}"})
            if echo:
                echo(f"[{done}/{len(jobs)}] {job['mode']} seed {job['seed']} {job['model']}")
    records.sort(key=lambda r: (r["model"], r["mode"], r["seed"]))
    return {"format": 1, "generated": None, "months": months, "seeds": seeds, "modes": modes, "models": models,
            "world_engine": versions.WORLD_ENGINE, "runs": records, "failures": failures,
            "bands": bands(records) if records else {}}


def _report(data: dict, out=None) -> None:
    lines = [f"Regime sweep: {len(data['runs'])} runs, Month 0-{data['months'] - 1}, world engine "
             f"{data['world_engine']}"]
    lines.append(f"{'model':12} {'mode':9} {'seed':>4} {'outcome':22} {'months':>6} {'zone':>4} {'fired':>5} "
                 f"{'crack':>5} {'fail':>4} {'honeym':>6} {'talk+':>5}")
    for r in data["runs"]:
        lines.append(f"{r['model']:12} {r['mode']:9} {r['seed']:>4} {r['outcome'] or '-':22} {r['months']:>6} "
                     f"{r['zone_months']:>4} {r['fired_months']:>5} {r['crackdowns']['attempted']:>5} "
                     f"{r['crackdowns']['failed']:>4} {r['honeymoons']['granted']:>6} "
                     f"{r['talks']['with_concessions']:>5}")
    for job in data["failures"]:
        lines.append(f"FAILED {job['mode']} seed {job['seed']} {job['model']}: {job['error']}")
    b = data["bands"]
    if b:
        q = b["quiet_no_revolution"]
        lines.append(f"Quiet runs never in revolution: {q['quiet_revolutions']} of {q['quiet_runs']} quiet runs "
                     f"-> {'MET' if q['met'] else 'NOT MET'}")
        s = b["legitimacy_against_legacy"]
        lines.append(f"Legitimacy within half to all of legacy: {s['legitimacy_revolutions']}/{s['pairs']} vs "
                     f"{s['legacy_revolutions']}/{s['pairs']} stress pairs "
                     f"({s['legitimacy_share']} vs {s['legacy_share']}) -> "
                     f"{'MET' if s['met'] else 'NOT MET' if s['met'] is not None else 'NO STRESS PAIRS'}")
        c = b["crackdown_failure"]
        o, n = c["observed"], c["census"]
        lines.append(f"Crackdown failure at security {SECURITY_BAND}: observed "
                     f"{o['failures']}/{o['attempts']} ({o['failure_share']}); census {n['min_failure']}-"
                     f"{n['max_failure']} at base {n['base']} -> {('MET' if c['met'] else 'NOT MET')}")
    text = "\n".join(lines)
    print(text)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--seeds", default="1-12", help="seeds, e.g. 1-12 or 1,2,3 (default 1-12)")
    parser.add_argument("--months", type=int, default=MONTHS, help=f"months per run (default {MONTHS})")
    parser.add_argument("--modes", default=",".join(MODES), help=f"councils: {','.join(MODES)}")
    parser.add_argument("--models", default=",".join(MODELS), help=f"worlds: {','.join(MODELS)}")
    parser.add_argument("--workers", type=int, default=min(12, os.cpu_count() or 1), help="parallel processes")
    parser.add_argument("--out", default="", help="write the JSON here")
    parser.add_argument("--quiet", action="store_true", help="no progress lines")
    args = parser.parse_args(argv)
    seeds = _parse_ints(args.seeds)
    modes = _parse_names(args.modes, MODES)
    models = _parse_names(args.models, MODELS)
    data = run_sweep(seeds, modes, models, args.months, max(1, args.workers),
                     echo=None if args.quiet else print)
    data["generated"] = __import__("datetime").datetime.now().isoformat(timespec="seconds")
    _report(data, args.out or None)
    return 1 if data["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
