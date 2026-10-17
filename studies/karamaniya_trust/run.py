"""One command for the Karamaniya study on SocioVerse2 (studies/karamaniya_trust). See README.md.

    python studies/karamaniya_trust/run.py --dry-run
        Runs council.scripted.toml through the wrap for two months (scripted seats: no model, no key). The same seed
        is then replayed through the legacy loop (karamaniya.runner.new_run), and the two are checked month by month
        and in their final world. Writes trajectory/dry_run/ and reports/dry_run.md.

    python studies/karamaniya_trust/run.py COUNCIL.toml [--months N] [--seed S] [--name NAME]
        A real run with the seats of COUNCIL.toml. Its seats call models and cost money, so the user starts it.
        Writes trajectory/<name>/ (default name: run) and reports/<name>.md.

    python studies/karamaniya_trust/run.py --materialize
        Writes population/population.json and population/roster.jsonl for the study's seed: the five delegates and
        their state at step 0. Scripted seats only, so no model is called.

The wrap needs socioverse2 0.2.0 in the Python that runs this file (its own venv; see README.md).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]  # the repository: karamaniya/ and council.scripted.toml live here
DRY_COUNCIL = ROOT / "council.scripted.toml"
DRY_MONTHS = 2
DRY_SEED = 4201  # the study's default seed; the pilot used seed 1 and 1001-1013


def _prepare_path() -> None:
    """Import from the repository root. This folder's subfolders (environment, simulation, ...) are not packages."""
    if sys.path and Path(sys.path[0] or ".").resolve() == STUDY:
        sys.path.pop(0)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def _require_socioverse() -> None:
    try:
        import socioverse  # noqa: F401
    except ImportError:
        raise SystemExit("socioverse2 is not installed in this Python. Install socioverse2==0.2.0 in its own venv "
                         "(see README.md, Setup), then run this command with that venv's python.")


def _shown(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def _write_text(path: Path, text: str) -> None:
    """Write with LF line endings. Path.write_text would write CRLF on Windows; the repository is LF."""
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _json(path: Path, data) -> None:
    _write_text(path, json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


def _legacy_run(config: Path, months: int, seed: int, out: Path):
    """The same seed through the legacy loop itself: karamaniya.runner.new_run, observed month by month."""
    from karamaniya.config import load_config
    from karamaniya.runner import new_run

    events = []
    path = new_run(load_config(config), runs_dir=out, name="legacy_run", months=months, seed=seed, quiet=True,
                   check=False, observer=events.append)
    states = [{k: e[k] for k in ("stats", "members", "offices", "removed")}
              for e in events if e["type"] == "month_done"]
    world = json.loads((Path(path) / "checkpoint.json").read_text(encoding="utf-8"))["world"]
    return states, world


def _parity(config: Path, months: int, seed: int, out: Path, seam) -> dict:
    states, legacy_world = _legacy_run(config, months, seed, out)
    wrapped_world = json.loads((seam.run_dir / "checkpoint.json").read_text(encoding="utf-8"))["world"]
    per_month = [mine == theirs for mine, theirs in zip(seam.trace, states)]
    # The legacy run may run past `months` (a handover extension), so the check counts the months both ran.
    check = {
        "equal": len(seam.trace) == len(states) and all(per_month) and wrapped_world == legacy_world,
        "months": months,
        "months_run_legacy": len(states),
        "months_run_wrapped": len(seam.trace),
        "seed": seed,
        "per_month_equal": per_month,
        "world_equal": wrapped_world == legacy_world,
        "legacy_run": "legacy_run",
        "wrapped_run": "wrapped_run",
    }
    _json(out / "parity_check.json", check)
    return check


def _report(path: Path, title: str, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_text(path, "\n".join([f"# {title}", "", *lines]) + "\n")


def run_cell(*, config: Path, months: int, seed: int, name: str, out: Path, report_dir: Path, check: bool,
             dry_run: bool = False) -> int:
    """One run of the study: the wrap, the legacy run folder, the trajectory and, for a dry run, the parity check.

    GRID HOOK: tools/study_grid.py (a later branch) calls this once per grid cell: one rotation, one seed and one
    action-order protocol. Those cell settings are not wired yet; the grid runner will pass them as arguments here.
    """
    from studies.karamaniya_trust.adapter.engine_seam import SeamPaused
    from studies.karamaniya_trust.adapter.providers import build_karamaniya_simulator

    out.mkdir(parents=True, exist_ok=True)
    if dry_run:
        # A dry run regenerates its own run folders. A real run never overwrites one: the legacy refuses that too.
        for stale in ("wrapped_run", "legacy_run"):
            shutil.rmtree(out / stale, ignore_errors=True)
    sim, seam = build_karamaniya_simulator(config=config, runs_dir=out, name="wrapped_run", months=months,
                                           seed=seed, trajectory_dir=out, check=check)
    status, history = "finished", None
    try:
        history = sim.run()
    except SeamPaused as exc:
        status = f"paused: {exc}"
    seam.finish()
    world = seam.world
    summary = {
        "study_id": "karamaniya_trust",
        "council": _shown(config),
        "months": months,
        "seed": seed,
        "dry_run": dry_run,
        "status": status,
        "months_run": seam.months_done,
        "steps_in_trajectory": len(history.rows) if history is not None else 0,
        "mapping": seam.mapping,
        "outcome": (world.outcome or {}).get("text", ""),
        "wrapped_run": "wrapped_run",
        "trajectory": "study.duckdb (panel, metrics, events); metrics_history.json",
    }
    if history is not None:
        _json(out / "metrics_history.json", {"study_id": history.study_id,
                                              "schema_columns": history.schema_columns,
                                              "rows": [dict(sorted(r.items())) for r in history.rows]})
    code = 0
    if dry_run:
        parity = _parity(config, months, seed, out, seam)
        summary["parity_equal"] = parity["equal"]
        if not parity["equal"]:
            code = 1
    _json(out / "summary.json", summary)
    lines = [f"Council: {_shown(config)} (scripted seats: no model, no key)" if dry_run else
             f"Council: {_shown(config)}",
             f"Seed {seed}, {months} months, status: {status}.",
             "", "Seats: " + ", ".join(f"{k} {v}" for k, v in sorted(seam.mapping.items())), ""]
    if history is not None:
        lines += ["| step | approval | inflation (yoy) | unrest | food ratio | army | active | exits | "
                  "motions voted | refused | invalid rate | mismatch rate |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        ran = [r for r in history.rows if r["step"] == 0 or r["month_ran"]]
        for r in ran:
            lines.append(f"| {r['step']} | {r['approval']:.3f} | {r['inflation_yoy']:.3f} | {r['unrest']:.3f} | "
                         f"{r['food_ratio']:.3f} | {r['army']:,.0f} | {r['active_members']} | {r['exits']} | "
                         f"{r['motions_voted']} | {r['motions_refused']} | {r['invalid_action_rate']:.3f} | "
                         f"{r['execution_mismatch_rate']:.3f} |")
        if len(ran) < len(history.rows):
            lines.append(f"\nSteps {ran[-1]['step'] + 1}-{history.rows[-1]['step']} are past the legacy end and run "
                         "no month (month_ran 0 in metrics_history.json).")
        lines.append("")
    if dry_run:
        lines.append(f"Parity with the legacy loop (new_run, same seed): every month equal: "
                     f"{'yes' if all(parity['per_month_equal']) else 'NO'} "
                     f"({sum(parity['per_month_equal'])}/{len(parity['per_month_equal'])} months, legacy "
                     f"{parity['months_run_legacy']}, wrapped {parity['months_run_wrapped']}); "
                     f"final world equal: {'yes' if parity['world_equal'] else 'NO'}.")
    if world.outcome:
        lines.append(f"Outcome: {world.outcome.get('text', '')}")
    _report(report_dir / f"{name}.md", f"Karamaniya trust study: {name.replace('_', ' ')}", lines)
    print(f"{name}: {status}; months run {seam.months_done}; output in {_shown(out)}")
    if dry_run:
        print(f"parity with the legacy loop: {'equal' if parity['equal'] else 'NOT EQUAL'}")
    return code


def materialize() -> int:
    """population/population.json and population/roster.jsonl for the study's default seed (scripted seats only)."""
    from karamaniya.config import load_config
    from socioverse.schemas import PopulationBundle

    from studies.karamaniya_trust.adapter.providers import build_karamaniya_simulator, load_bundles

    cfg = load_config(DRY_COUNCIL)
    if any(s.get("provider") != "scripted" for s in cfg["seats"]):
        raise SystemExit("--materialize is for the scripted council only (it runs the founding phases)")
    with tempfile.TemporaryDirectory(prefix="kt-materialize-") as tmp:
        sim, _seam = build_karamaniya_simulator(config=DRY_COUNCIL, runs_dir=Path(tmp), name="materialize",
                                                months=DRY_MONTHS, seed=DRY_SEED, trajectory_dir=Path(tmp),
                                                check=False)
        personas, rows = sim.materialize_initial()
    _env, pop_template, _sim = load_bundles()
    bundle = PopulationBundle(
        study_id=pop_template.study_id,
        personas=personas,
        interaction=pop_template.interaction,
        propagation=pop_template.propagation,
        provider_ref=pop_template.provider_ref,
        provider_args={"config": _shown(DRY_COUNCIL), "seed": DRY_SEED},
        materialized_count=len(personas),
    )
    _write_text(STUDY / "population" / "population.json",
                json.dumps(bundle.model_dump(mode="json"), indent=1, ensure_ascii=False) + "\n")
    _write_text(STUDY / "population" / "roster.jsonl",
                "".join(json.dumps(row.model_dump(mode="json"), ensure_ascii=False) + "\n" for row in rows))
    print(f"wrote population/population.json ({len(personas)} delegates) and population/roster.jsonl")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="The Karamaniya study on SocioVerse2 (see README.md).")
    ap.add_argument("council", nargs="?", help="a council file (TOML) for a real run")
    ap.add_argument("--dry-run", action="store_true",
                    help=f"scripted seats ({_shown(DRY_COUNCIL)}), {DRY_MONTHS} months, seed {DRY_SEED}, "
                         "with the parity check against the legacy loop")
    ap.add_argument("--materialize", action="store_true", help="write population/ for the study's seed")
    ap.add_argument("--months", type=int, help="months to run (default: the council file's)")
    ap.add_argument("--seed", type=int, help="run seed (default: the council file's)")
    ap.add_argument("--name", help="run name: the output folder and report (default: dry_run or run)")
    ap.add_argument("--out", type=Path, help="output folder (default: trajectory/<name>)")
    ap.add_argument("--report-dir", type=Path, default=STUDY / "reports", help="where the report goes")
    ap.add_argument("--no-check", action="store_true", help="skip the tiny seat check a real run makes first")
    args = ap.parse_args(argv)
    _prepare_path()
    _require_socioverse()
    if args.materialize:
        return materialize()
    if args.dry_run:
        config, months = DRY_COUNCIL, args.months if args.months is not None else DRY_MONTHS
        seed = args.seed if args.seed is not None else DRY_SEED
        name, check = args.name or "dry_run", False
    else:
        if not args.council:
            ap.error("give a council file, or use --dry-run")
        config = Path(args.council).resolve()
        if not config.is_file():
            ap.error(f"no council file at {config}")
        from karamaniya.config import load_config

        base = load_config(config)["run"]
        months = args.months if args.months is not None else int(base["months"])
        seed = args.seed if args.seed is not None else int(base["seed"])
        name, check = args.name or "run", not args.no_check
    out = args.out or STUDY / "trajectory" / name
    return run_cell(config=config, months=months, seed=seed, name=name, out=out, report_dir=args.report_dir,
                    check=check, dry_run=bool(args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
