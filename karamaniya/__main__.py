"""Command line: python -m karamaniya <command> ..."""
from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m karamaniya",
                                 description="An AI council governs Karamaniya. Watch what it does.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="start a new run from a council config")
    r.add_argument("config")
    r.add_argument("--months", type=int)
    r.add_argument("--seed", type=int)
    r.add_argument("--name")
    r.add_argument("--framing", choices=["simulation", "immersive"])
    r.add_argument("--no-survey", action="store_true")
    r.add_argument("--runs-dir", default="runs")
    r.add_argument("--no-check", action="store_true", help="skip the seat check before the run")

    s = sub.add_parser("resume", help="continue a stopped or paused run")
    s.add_argument("run_dir")
    s.add_argument("--no-check", action="store_true", help="skip the seat check before resuming")

    g = sub.add_parser("gui", help="open the control room in your browser")
    g.add_argument("--port", type=int, default=8770)
    g.add_argument("--root", default=".", help="folder with the council files and .env (default: here)")
    g.add_argument("--runs-dir", help="where runs are kept (default: ROOT/runs)")
    g.add_argument("--no-open", action="store_true", help="do not open a browser, just print the address")
    g.add_argument("--verbose", action="store_true", help="log every request")

    p = sub.add_parser("report", help="rebuild a run's report.html")
    p.add_argument("run_dir")

    c = sub.add_parser("check", help="make one tiny call per seat to test keys and models")
    c.add_argument("config")

    wld = sub.add_parser("world", help="run the world with nobody governing, to see the pressure")
    wld.add_argument("--months", type=int, default=36)
    wld.add_argument("--seed", type=int, default=1)

    a = sub.add_parser("audit", help="check a run for motions executed as a different act")
    a.add_argument("run_dir")
    a.add_argument("--write", action="store_true",
                   help="write correction.json beside the run (recorded history is never altered)")

    an = sub.add_parser("analyze", help="scan runs for engine bugs and what delegates could not do")
    an.add_argument("runs_dir", nargs="?", default="runs")
    an.add_argument("--recent", type=int, help="only the N most recently written runs")
    an.add_argument("--run", help="one run id, listed in full detail")
    an.add_argument("--json", dest="json_out", help="also write machine-readable findings to this file")

    batch = sub.add_parser("simulate", help="run one model-seat assignment across several seeds")
    batch.add_argument("config", nargs="?", default="council.scripted.toml")
    batch.add_argument("--runs", type=int, default=5)
    batch.add_argument("--months", type=int, default=36)
    batch.add_argument("--first-seed", type=int, default=1)
    batch.add_argument("--runs-dir", default="runs")
    batch.add_argument("--prefix", default="batch")
    batch.add_argument("--no-check", action="store_true")
    batch.add_argument("--shuffle-seats", action="store_true", help="vary model-seat assignment between seeds")
    batch.add_argument("--rotate-seats", action="store_true", help="move each model one seat along per seed")
    batch.add_argument("--scenario", default="", help="test scenario A-E applied after government formation")

    args = ap.parse_args(argv)
    if args.cmd != "gui":
        from .envfile import load_env
        load_env(".env")  # keys saved from the control room work on the command line too
    if args.cmd == "gui":
        from .gui import serve
        serve(root=args.root, runs_dir=args.runs_dir, port=args.port, open_browser=not args.no_open,
              verbose=args.verbose)
    elif args.cmd == "run":
        from .runner import new_run
        new_run(args.config, runs_dir=args.runs_dir, name=args.name, months=args.months, seed=args.seed,
                framing=args.framing, survey=False if args.no_survey else None, check=not args.no_check)
    elif args.cmd == "resume":
        from .runner import resume_run
        resume_run(args.run_dir, check=not args.no_check)
    elif args.cmd == "report":
        from .report import build_report
        from .storage import RunStore
        print(build_report(RunStore(args.run_dir)))
    elif args.cmd == "check":
        from .runner import check_seats
        ok = True
        for res in check_seats(args.config):
            status = "OK " if res["ok"] else "FAIL"
            ok &= res["ok"]
            print(f"{status} {res['label']:<22} {res['provider']:<12} asked {res['model'] or '-':<22} "
                  f"answered by {res['served_model'] or '-':<24} {res['latency_s']:>6.1f}s "
                  f"${res['cost_usd']:.4f} {res['error'][:120]}")
        return 0 if ok else 1
    elif args.cmd == "world":
        from . import engine
        from .world import new_world
        w = new_world(args.seed, args.months, founding_scenario="random")
        while not w.ended():
            engine.begin_month(w)
            engine.step(w)
        for h in w.history:
            print(f"Month {h['month'] + 1:2d}: approval {h['approval']:.0%}, inflation {h['infl_yoy']:.0%}, "
                  f"food {h['food_ratio']:.0%}, output {h['gdp_idx']:.0%}, unrest {h['unrest']:.2f}")
        print("Outcome:", w.outcome.get("text"))
    elif args.cmd == "audit":
        from . import integrity
        from .storage import RunStore
        store = RunStore(args.run_dir)
        record = integrity.mark(store, write=args.write)
        print(f"{record['run']}: {record['classification']}")
        print(record["explanation"])
        for f in record["findings"]:
            print(f"  Month {f['month'] + 1} {f['motion']} by {f['proposer']}: "
                  f"executed={f['executed']} | {f['structured_action']['action_type']} -> "
                  f"{f['structured_action']['target']}")
            print(f"    text:   {f['prose'][:150]}")
            print(f"    result: {f['recorded_result']}")
        executed_wrongly = [f for f in record["findings"] if f["executed"]]
        if executed_wrongly:
            print(f"  last clean month: {record['last_clean_month'] + 1}")
            print(f"  replay: {record['replay']['how']}")
        if args.write:
            print(f"  wrote {store.path / 'correction.json'}")
        return 1 if executed_wrongly else 0
    elif args.cmd == "analyze":
        from .analyze import analyze
        analyze(args.runs_dir, recent=args.recent, run_id=args.run, json_out=args.json_out)
    elif args.cmd == "simulate":
        from .batch import simulate
        result = simulate(args.config, runs=args.runs, months=args.months,
                          first_seed=args.first_seed, runs_dir=args.runs_dir,
                          prefix=args.prefix, check=not args.no_check,
                          same_seats=not args.shuffle_seats, rotate_seats=args.rotate_seats,
                          scenario=args.scenario)
        print("Aggregate:", result["totals"])
        print("Convergence check:", result["convergence_check"])
        print("Relationship variation across seeds (mean SD of directional trust):",
              result["relationship_variation_across_seeds"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
