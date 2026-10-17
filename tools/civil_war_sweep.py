"""The scripted 36-month civil-war sweeps: quiet arms start no war, a minority of hawk runs do.

    python tools/civil_war_sweep.py --root runs/cw-sweep --seeds 1 2 3 4 5 6 --months 36
    python tools/civil_war_sweep.py --root runs/cw-sweep --seed 1        # one seed, for a process
    python tools/civil_war_sweep.py --root runs/cw-sweep --summary-only  # re-read the runs on disk

Every run is a council of rule-following stand-ins (`karamaniya/backends/scripted.py`); no model is
called and no API key is read. The quiet arms are `karamaniya/baseline.py`'s:

  passive  a council that forms a government and then does nothing;
  scripted the five mixed stand-ins of council.scripted.toml;
  dove     five dove stand-ins (the military is never raised).

The stress arm is the scripted coup plotter (`plotter`): one hawk holding the army against four
seats that resist the handover, which is the shape in which the failed-coup trigger can be
reached. `hawk` (baseline.py's all-hawk council) is kept as a diagnostic: every armed office there
is held by a stand-aside hawk, so the handover is a total takeover and the trigger cannot fire.

Each arm runs twice on the same seed: the on run with `run.civil_war = "on"` and its twin with the
arm absent (`"off"`), so `tools/civil_war_report.py` can compare the war against the same run
without it. The quiet arms must start zero wars; the plotter arm is the stress arm whose band the
C-1 decisions memo set at 10-40% of runs.

Results, per run and per arm, are written to `<root>/sweep.json` and `<root>/sweep.md`. The
coordinator starts one process per seed (the plan's rule) and waits for all of them; the children
are this same script with `--seed N`. A run that fails is recorded as failed with its error, never
silently dropped.

Exit status: 0 when every run finished and the band holds, 1 when a band check fails, 2 when the
sweep could not be run or a run failed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from karamaniya import baseline  # noqa: E402
from karamaniya.config import normalize_config  # noqa: E402
from karamaniya.runner import new_run  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402

ARMS = ("passive", "scripted", "dove", "hawk", "plotter")
QUIET_ARMS = ("passive", "scripted", "dove")
# The stress arm. `plotter` is the scripted coup plotter: one hawk holding the army against four
# seats that resist the handover, which is the shape in which the failed-coup trigger (C1's first
# trigger) can be reached at all. `hawk` (baseline.py's all-hawk council) is kept as a diagnostic:
# every armed office there is held by a stand-aside hawk, so the handover is a total takeover and
# the trigger never fires (C1's review commit records the same shape).
STRESS_ARM = "plotter"
DIAGNOSTIC_ARMS = ("hawk",)
# A company of one plotter: the hawk takes the army, every other seat refuses the takeover.
PLOTTER_SEATS = (("hawk", "army"), ("loyalist", "head"), ("democrat", "treasury"),
                 ("loyalist", "interior"), ("technocrat", "navy"))
# The band agreed at C-1 (notes/open-actions-decisions.md, Wave C): no quiet run starts a civil war,
# and 10-40% of the hawk stress runs do.
HAWK_BAND = (0.10, 0.40)
MONTHS = 36


def run_name(seed: int, arm: str, option: str) -> str:
    return f"seed{seed}-{arm}-{option}"


def config_for(arm: str, seed: int, months: int, option: str, twin: str | None,
               scenario: str | None = None) -> dict:
    """A baseline-style stand-in council with the war arm set. Mirrors baseline._config's seats."""
    seats = []
    if arm == "plotter":
        for i, (persona, office) in enumerate(PLOTTER_SEATS):
            seats.append({"label": f"{arm}-{i + 1}-{persona}", "provider": "scripted",
                          "persona": persona, "formation_office": office})
    else:
        if arm == "passive":
            personas = ["passive"] * 5
        elif arm in baseline.SAME_PERSONA_OFFICES:
            personas = [arm] * 5
        else:
            personas = [baseline.SCRIPTED_PERSONAS[i % len(baseline.SCRIPTED_PERSONAS)] for i in range(5)]
        for i, persona in enumerate(personas):
            seat = {"label": f"{arm}-{i + 1}-{persona}", "provider": "scripted", "persona": persona}
            if arm in baseline.SAME_PERSONA_OFFICES:
                offices = baseline.SAME_PERSONA_OFFICES[arm]
                seat["formation_office"] = offices[i % len(offices)]
            seats.append(seat)
    run = {
        "months": months, "seed": seed, "survey": False, "shuffle_seats": False,
        "baseline": False, "report": False, "debrief": False, "forecast_panel": False,
        "foreign_cabinets": True, "civil_war": option,
    }
    if twin:
        run["twin"] = twin
    if scenario:
        run["test_scenario"] = scenario
    return normalize_config({"run": run, "seat": seats}, f"cw-sweep:{arm}:{option}")


def _run_one(root: Path, arm: str, seed: int, months: int, option: str, twin: str | None,
             scenario: str | None = None) -> dict:
    name = run_name(seed, arm, option)
    cfg = config_for(arm, seed, months, option, twin, scenario)
    try:
        path = new_run(cfg, runs_dir=str(root), name=name, quiet=True, check=False)
    except Exception as exc:  # a failed run is recorded, never silently dropped
        return {"arm": arm, "seed": seed, "option": option, "run": name, "status": "failed",
                "error": f"{type(exc).__name__}: {str(exc)[:500]}"}
    world, _, meta = RunStore(path).load_checkpoint()
    state = getattr(world, "civil_war", None)
    history = list(world.history)
    return {
        "arm": arm, "seed": seed, "option": option, "run": name, "status": "ok",
        "path": str(Path(path).resolve()),
        "months": len(history),
        "outcome": (world.outcome or {}).get("type", ""),
        "war_started": isinstance(state, dict) and bool(state),
        "war_since": (state or {}).get("since") if isinstance(state, dict) else None,
        "war_outcome": ((state or {}).get("outcome") or {}).get("type") if isinstance(state, dict) else None,
        "stopped": str((meta or {}).get("stopped") or ""),
    }


def run_seed(root: Path, seed: int, months: int, arms, scenario: str | None = None) -> list:
    """Every arm for one seed, in this process. The on run first, then its off twin."""
    out = []
    for arm in arms:
        out.append(_run_one(root, arm, seed, months, "on", run_name(seed, arm, "off"), scenario))
        out.append(_run_one(root, arm, seed, months, "off", None, scenario))
    return out


def summarise(root: Path, seeds, arms) -> dict:
    """Read the run folders on disk into one record; the report file is written from this."""
    rows = []
    for name in sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []:
        path = root / name
        if not (path / "checkpoint.json").is_file() or not (path / "config.json").is_file():
            continue
        cfg = json.loads((path / "config.json").read_text(encoding="utf-8"))
        run = cfg.get("run") or {}
        option = run.get("civil_war", "off")
        arm = str(cfg.get("source", "")).split(":")[1] if str(cfg.get("source", "")).startswith("cw-sweep:") else ""
        if not arm or int(run.get("seed", 0)) not in seeds:
            continue
        world, _, meta = RunStore(path).load_checkpoint()
        state = getattr(world, "civil_war", None)
        rows.append({
            "arm": arm, "seed": int(run.get("seed", 0)), "option": option, "run": name,
            "path": str(path.resolve()), "months": len(world.history),
            "outcome": (world.outcome or {}).get("type", ""),
            "war_started": isinstance(state, dict) and bool(state),
            "war_since": (state or {}).get("since") if isinstance(state, dict) else None,
            "war_outcome": ((state or {}).get("outcome") or {}).get("type") if isinstance(state, dict) else None,
            "stopped": str((meta or {}).get("stopped") or ""),
        })
    rows.sort(key=lambda r: (r["seed"], r["arm"], 0 if r["option"] == "on" else 1))
    per_arm = {}
    for arm in arms:
        on = [r for r in rows if r["arm"] == arm and r["option"] == "on"]
        started = [r for r in on if r["war_started"]]
        per_arm[arm] = {"runs": len(on), "started": len(started),
                        "started_share": round(len(started) / len(on), 4) if on else None,
                        "seeds_started": [r["seed"] for r in started],
                        "runs_failed": [r["run"] for r in on if r["stopped"]],
                        "outcomes": {r["run"]: r["outcome"] for r in on}}
    checks = {
        "quiet_zero": all(per_arm[arm]["started"] == 0 for arm in QUIET_ARMS if arm in per_arm),
        "hawk_band": (per_arm.get(STRESS_ARM, {}).get("started_share") is not None
                      and HAWK_BAND[0] <= per_arm[STRESS_ARM]["started_share"] <= HAWK_BAND[1]),
        "stress_arm": STRESS_ARM,
        "band": list(HAWK_BAND),
    }
    return {"format": 1, "seeds": list(seeds), "arms": list(arms), "runs": rows,
            "per_arm": per_arm, "checks": checks}


def write_summary(root: Path, data: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "sweep.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                                     encoding="utf-8", newline="\n")
    lines = ["# Civil-war scripted sweeps", "",
             f"Seeds {', '.join(str(s) for s in data['seeds'])}; {MONTHS} months; "
             "rule-following stand-ins only, no model calls.", ""]
    lines += ["## Per arm", ""]
    lines += ["| arm | runs | wars started | share | seeds |", "|---|---|---|---|---|"]
    for arm in data["arms"]:
        item = data["per_arm"][arm]
        share = "NA" if item["started_share"] is None else f"{item['started_share']:.0%}"
        lines.append(f"| {arm} | {item['runs']} | {item['started']} | {share} | "
                     f"{', '.join(str(s) for s in item['seeds_started']) or '-'} |")
    lines += ["", f"Band: quiet arms 0 wars; {data['checks']['stress_arm']} "
                  f"{data['checks']['band'][0]:.0%}-{data['checks']['band'][1]:.0%}. "
                  f"Quiet zero: {data['checks']['quiet_zero']}; "
                  f"stress arm in band: {data['checks']['hawk_band']}.", "", "## Every run", "",
              "| seed | arm | arm state | months | run outcome | war since | war outcome |",
              "|---|---|---|---|---|---|---|"]
    for row in data["runs"]:
        lines.append(f"| {row['seed']} | {row['arm']} | {row['option']} | {row['months']} | "
                     f"{row['outcome'] or '-'} | "
                     f"{'-' if row['war_since'] is None else 'Month ' + str(row['war_since'] + 1)} | "
                     f"{row['war_outcome'] or ('running' if row['war_started'] else '-')} |")
    (root / "sweep.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def coordinator(args) -> int:
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    seeds = [int(s) for s in args.seeds]
    children = []
    for seed in seeds:
        command = [sys.executable, str(Path(__file__).resolve()), "--root", str(root),
                   "--seed", str(seed), "--months", str(args.months), "--arms", ",".join(args.arms)]
        if args.scenario:
            command += ["--scenario", args.scenario]
        log = open(root / f"seed{seed}.log", "w", encoding="utf-8")
        children.append((seed, subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                                cwd=str(ROOT)), log))
    failed = []
    for seed, child, log in children:
        code = child.wait()
        log.close()
        if code != 0:
            failed.append((seed, code))
    data = summarise(root, seeds, args.arms)
    write_summary(root, data)
    print(f"civil_war_sweep: {len(data['runs'])} runs; per arm: "
          + "; ".join(f"{arm} {data['per_arm'][arm]['started']}/{data['per_arm'][arm]['runs']}"
                      for arm in args.arms if arm in data["per_arm"]))
    print(f"wrote {root / 'sweep.json'} and {root / 'sweep.md'}")
    if failed:
        print(f"civil_war_sweep: seed processes failed: {failed}", file=sys.stderr)
        return 2
    if not (data["checks"]["quiet_zero"] and data["checks"]["hawk_band"]):
        print("civil_war_sweep: band check failed: " + json.dumps(data["checks"]), file=sys.stderr)
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Scripted 36-month civil-war sweeps, one process per seed.")
    parser.add_argument("--root", required=True, help="the folder the run folders and the summary live in")
    parser.add_argument("--seeds", nargs="+", default=["1", "2", "3", "4", "5", "6"],
                        help="seeds for the coordinator (default 1-6)")
    parser.add_argument("--seed", type=int, default=None,
                        help="run one seed in this process (the coordinator starts one of these per seed)")
    parser.add_argument("--months", type=int, default=MONTHS)
    parser.add_argument("--arms", default=",".join(ARMS), help=f"comma-separated arms (default {','.join(ARMS)})")
    parser.add_argument("--scenario", default=None,
                        help="a test scenario applied before Month 1 (calibration experiments only)")
    parser.add_argument("--summary-only", action="store_true", help="re-read the run folders; run nothing")
    args = parser.parse_args(argv)
    args.arms = tuple(a.strip() for a in args.arms.split(",") if a.strip())
    unknown = [a for a in args.arms if a not in ARMS]
    if unknown:
        print(f"civil_war_sweep: unknown arms: {unknown}", file=sys.stderr)
        return 2
    root = Path(args.root)
    if args.summary_only:
        data = summarise(root, [int(s) for s in args.seeds], args.arms)
        write_summary(root, data)
        print(f"wrote {root / 'sweep.json'} and {root / 'sweep.md'}")
        return 0 if data["checks"]["quiet_zero"] and data["checks"]["hawk_band"] else 1
    if args.seed is None:
        return coordinator(args)
    results = run_seed(root, args.seed, args.months, args.arms, args.scenario)
    for result in results:
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if all(r["status"] == "ok" for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
