"""Plan and run the study grid: five models, five rotations, the seeds, and two action-order protocols.

    python tools/study_grid.py plan <study.toml> <out_dir> [--no-study-options]
    python tools/study_grid.py run <out_dir>/plan.json [--workers N] [--max-resumes K] [--runs-dir DIR] [--dry-run]

A study file is a council config plus a [study] table. The [run] table names the neighbours model through
foreign_cabinet_backend (brief S4), and there are five [[seat]] tables, one per model:

    [study]
    seeds = [2101, 2102, 2103, 2104, 2105]
    rotations = 5                                  # 1 to 5; rotation r runs over 0 .. rotations-1
    protocols = ["seeded_shuffle", "fixed_precedence"]
    months = 36

Rotation r puts model i (its seat number in the study file, counting from 0) at letter (i + r) mod 5. Under
run.office_assignment = "by_letter" the letters are head, treasury, interior, army and navy, so across five
rotations every model holds every office once per seed. Two protocols x five seeds x five rotations is 50 rows.

plan writes, into out_dir:
    plan.json             the rows, described below
    configs/<name>.toml   one council config per row; its seat order carries the rotation
    study.toml            a copy of the study file, for provenance

plan.json is a JSON list, one object per row:
    {"name": "sv-seeded_shuffle-s2101-r0",     # sv-<protocol>-s<seed>-r<rotation>
     "protocol": "seeded_shuffle",              # run.action_order
     "seed": 2101,                              # run.seed
     "rotation": 0,
     "config": "configs/sv-seeded_shuffle-s2101-r0.toml",   # relative to the folder of plan.json
     "seat_map": {"A": "<seat label>", "B": "...", "C": "...", "D": "...", "E": "..."}}

run starts every row that is not finished, each in its own process, and keeps status.json beside plan.json. A dry
run (--dry-run) puts scripted seats in place of every seat and of the neighbours, caps the months at 2, and keeps
its own files (status-dry-run.json, logs-dry-run/, run folders named dry-<row>), so it never marks a study row done.

status.json (status-dry-run.json for a dry run) is a JSON object keyed by row name. Each value:
    {"state": "pending" | "running" | "paused" | "done" | "failed",
     "reason": "",            # paused or failed: the engine's text or the error; done: a note, if the engine raised
                              # after the run had ended (its report, say)
     "months_done": 0,
     "outcome": "",           # once the run has ended: its outcome type, e.g. "survived" or "voted_out"
     "resumes": 0,            # resume attempts so far; the first attempt is not a resume
     "wall_seconds": 0.0,     # wall time over all attempts on this row
     "spend_usd": 0.0,        # the engine's recorded spend, from the checkpoint
     "run_dir": "...",        # absolute path of the run folder: runs/<row>, or runs/dry-<row> for a dry run
     "log": "logs/<row>.log", # relative to the folder of plan.json
     "updated": "2026-10-17T10:00:00"}

A row is done when its run has ended. A paused row (an engine pause such as a usage limit, or a refused seat) is
resumed by the next `run`, once per invocation, until it has used --max-resumes resumes; then it is failed. A row
left "running" by a killed invocation counts as paused. A seat check that fails for a wrong key or model id is not a
pause: the runner fails the row at once, without spending a resume (wave-3 decision). Failed rows are not retried.
The exit code is 0 when every row is done, 1 when a row failed, 3 when rows are paused or pending, and 2 when the
plan was refused.

A router seat is refused before a plan is written (wave-3 decision): a seat whose model is an auto/router label
would answer with different models from call to call, so a model effect could not be attributed. A seat with no model
identifier is refused for the same reason, except a scripted seat, which names a persona instead.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import shutil
import sys
import time
import tomllib
import traceback
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # the package imports from the repository root, in worker processes too

from karamaniya.config import RUN_DEFAULTS, _toml_key, _toml_value, load_config, normalize_config  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402

LETTERS = "ABCDE"
PROTOCOLS = ("seeded_shuffle", "fixed_precedence")
STUDY_KEYS = ("seeds", "rotations", "protocols", "months")
# [run] keys the plan writes for each row; a study file may not set them itself.
GRID_KEYS = ("seed", "months", "shuffle_seats", "office_assignment", "action_order")
STUDY_OPTIONS = ("office_assignment", "action_order")
ROW_KEYS = ("name", "protocol", "seed", "rotation", "config", "seat_map")
DRY_PERSONAS = ("democrat", "technocrat", "hawk", "loyalist", "opportunist")  # as council.scripted.toml
DRY_MONTHS = 2
DEFAULT_MAX_RESUMES = 3
# A fixed model identifier per seat is a study requirement (WAVE3_PLAN): a router or auto label answers with different
# models from call to call, so a model contrast could not be attributed. The pilot had an "auto" seat and an
# "openrouter/free" seat, and their served_models listed two and eight identifiers.
ROUTER_MODELS = frozenset({"auto", "router", "default", "openrouter/auto", "openrouter/free"})
# runner._require_seats raises SystemExit with one of three hints. These two mean a broken login, key or model id:
# retrying cannot fix that, so the row fails at once instead of spending every resume on it (wave-3 decision).
PERMANENT_SEAT_HINTS = ("Check the login, key or model id", "fix any other seat errors before retrying")


def router_reason(seat: dict) -> str:
    """Why a seat is not one fixed model, or "" when it names one. Scripted seats name a persona, not a model."""
    if str(seat.get("provider") or "").strip().lower() == "scripted":
        return ""
    model = str(seat.get("model") or "").strip().lower()
    if not model:
        return "the seat names no model"
    if model in ROUTER_MODELS or model.endswith("/auto"):
        return f"the model {model!r} is a router or auto label, not one fixed model"
    return ""


def seat_start_failure(message: str) -> bool:
    """Whether a seat-check SystemExit says a seat cannot start for a persistent reason (a wrong key or model id)."""
    text = str(message or "")
    return any(hint in text for hint in PERMANENT_SEAT_HINTS)


# ---- plan --------------------------------------------------------------------------------------------------

def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _study_settings(study: dict) -> dict:
    unknown = sorted(set(study) - set(STUDY_KEYS))
    if unknown:
        raise ValueError(f"[study] has unknown keys {unknown}; the keys are {list(STUDY_KEYS)}")
    missing = [key for key in STUDY_KEYS if key not in study]
    if missing:
        raise ValueError(f"[study] is missing {missing}")
    seeds, rotations = study["seeds"], study["rotations"]
    protocols, months = study["protocols"], study["months"]
    if not isinstance(seeds, list) or not seeds or not all(_is_int(s) for s in seeds) or len(set(seeds)) != len(seeds):
        raise ValueError("[study] seeds must be a list of different whole numbers")
    if not _is_int(rotations) or not 1 <= rotations <= len(LETTERS):
        raise ValueError(f"[study] rotations must be a whole number from 1 to {len(LETTERS)}")
    if (not isinstance(protocols, list) or not protocols or len(set(protocols)) != len(protocols)
            or not all(p in PROTOCOLS for p in protocols)):
        raise ValueError(f"[study] protocols must be a list of different names from {list(PROTOCOLS)}")
    if not _is_int(months) or not 1 <= months <= 120:
        raise ValueError("[study] months must be a whole number from 1 to 120")
    return {"seeds": seeds, "rotations": rotations, "protocols": protocols, "months": months}


def _dump(run: dict, seats: list, header: list) -> str:
    """A council config as TOML (the same value writer as the control room's config.dump_config)."""
    lines = [f"# {line}" for line in header] + ["", "[run]"]
    lines += [f"{_toml_key(k)} = {_toml_value(v)}" for k, v in run.items()]
    for seat in seats:
        lines += ["", "[[seat]]"] + [f"{_toml_key(k)} = {_toml_value(v)}" for k, v in seat.items()]
    return "\n".join(lines) + "\n"


def plan_study(study_path, out_dir, *, no_study_options: bool = False) -> list:
    """Write the configs, plan.json and a copy of the study file into out_dir. Returns the rows."""
    study_path, out = Path(study_path), Path(out_dir)
    if (out / "plan.json").exists():
        raise FileExistsError(f"{out / 'plan.json'} exists; a plan is never overwritten, because its runs depend on it")
    with open(study_path, "rb") as f:
        raw = tomllib.load(f)
    unknown = sorted(set(raw) - {"study", "run", "seat"})
    if unknown:
        raise ValueError(f"the study file has tables {unknown}; it takes [study], [run] and [[seat]]")
    settings = _study_settings(raw.get("study") or {})
    run = dict(raw.get("run") or {})
    grid = [key for key in GRID_KEYS if key in run]
    if grid:
        raise ValueError(f"[run] sets {grid}; the plan sets these for every row, so take them out of the study file")
    backend = run.get("foreign_cabinet_backend")
    if not isinstance(backend, dict) or not backend.get("provider"):
        raise ValueError("the study must name the neighbours model in [run].foreign_cabinet_backend (brief S4): "
                         "without it the two cabinets borrow the first two seats, which change with the rotation")
    seats = [dict(seat) for seat in raw.get("seat") or []]
    if len(seats) != len(LETTERS):
        raise ValueError(f"the study needs exactly five [[seat]] tables, one per model and office; found {len(seats)}")
    base = normalize_config({"run": run, "seat": seats}, str(study_path))
    for seat, normalized in zip(seats, base["seats"]):
        seat["label"] = normalized["label"]
    for seat in seats:
        why = router_reason(seat)
        if why:
            raise ValueError(f"seat {seat['label']!r}: {why}; the study needs one fixed model per seat "
                             "(router seats are excluded from the study)")

    out.mkdir(parents=True, exist_ok=True)
    (out / "configs").mkdir(exist_ok=True)
    rows = []
    for protocol in settings["protocols"]:
        for seed in settings["seeds"]:
            for rotation in range(settings["rotations"]):
                name = f"sv-{protocol}-s{seed}-r{rotation}"
                # Seat position p holds model order[p]; model i therefore ends at letter (i + rotation) mod 5.
                order = [(p - rotation) % len(LETTERS) for p in range(len(LETTERS))]
                row_seats = [seats[order[p]] for p in range(len(LETTERS))]
                row_run = {**run, "seed": seed, "months": settings["months"], "shuffle_seats": False}
                if not no_study_options:
                    row_run.update(office_assignment="by_letter", action_order=protocol)
                config = out / "configs" / f"{name}.toml"
                config.write_text(_dump(row_run, row_seats, [
                    f"Row {name}, written by tools/study_grid.py plan. Change the study file and plan again, "
                    "rather than this file."]), encoding="utf-8", newline="\n")
                try:
                    load_config(config)
                except ValueError as exc:
                    raise ValueError(f"{name}: {exc}") from exc
                rows.append({"name": name, "protocol": protocol, "seed": seed, "rotation": rotation,
                             "config": config.relative_to(out).as_posix(),
                             "seat_map": {LETTERS[p]: row_seats[p]["label"] for p in range(len(LETTERS))}})
    (out / "plan.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                   newline="\n")
    shutil.copyfile(study_path, out / "study.toml")
    return rows


def load_plan(plan_path) -> list:
    rows = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{plan_path}: a plan is a non-empty JSON list of rows")
    names = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(ROW_KEYS):
            raise ValueError(f"{plan_path}: each row has exactly the keys {list(ROW_KEYS)}")
        if row["name"] in names:
            raise ValueError(f"{plan_path}: row {row['name']} appears twice")
        names.add(row["name"])
    return rows


def check_engine_options(raw_run: dict, *, dry_run: bool) -> None:
    """Refuse a config whose study options this engine would ignore. The engine keeps unknown [run] keys without a
    word, so an unlisted option would run as if it were absent: the formation vote and the seeded order."""
    unknown = [key for key in STUDY_OPTIONS if key in raw_run and key not in RUN_DEFAULTS]
    if unknown:
        raise ValueError(f"this engine does not list {unknown} in karamaniya/config.py RUN_DEFAULTS, so a run would "
                         "silently ignore them; the office and order branches must be merged first")
    absent = [key for key in STUDY_OPTIONS if key not in raw_run]
    if absent and not dry_run:
        raise ValueError(f"the config has no {absent}: it was planned with --no-study-options, which is for "
                         "machinery tests; only --dry-run may run it")


def dry_run_config(cfg: dict) -> dict:
    """The same config with scripted seats and a scripted neighbours model, no judges, and at most DRY_MONTHS."""
    run = dict(cfg["run"])
    run["months"] = min(int(run["months"]), DRY_MONTHS)
    run["judge"] = False
    run.pop("judge_backends", None)
    run.pop("judge_every_months", None)
    backend = run.get("foreign_cabinet_backend")
    if backend:
        run["foreign_cabinet_backend"] = {"label": f"dry-{backend.get('label') or 'neighbours'}",
                                          "provider": "scripted", "persona": "hawk"}
    seats = [{"label": seat["label"], "provider": "scripted", "persona": DRY_PERSONAS[i % len(DRY_PERSONAS)]}
             for i, seat in enumerate(cfg["seats"])]
    return {"run": run, "seats": seats, "source": cfg.get("source", "")}


# ---- run ---------------------------------------------------------------------------------------------------

def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _write_status(path: Path, status: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


@contextlib.contextmanager
def _locked(path: Path):
    """One invocation at a time per plan: two would resume the same run folders."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"{path.name} exists: another run of this plan is in progress, or one was killed. "
                           "If none is running, delete it and run again.") from exc
    with os.fdopen(fd, "w") as f:
        f.write(str(os.getpid()))
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def _blank(name: str, runs_root: Path, dry_run: bool, log_dir: Path) -> dict:
    run_name = f"dry-{name}" if dry_run else name
    return {"state": "pending", "reason": "", "months_done": 0, "outcome": "", "resumes": 0, "wall_seconds": 0.0,
            "spend_usd": 0.0, "run_dir": str(runs_root / run_name), "log": f"{log_dir.name}/{name}.log",
            "updated": ""}


def _checkpoint_facts(run_dir: Path):
    """What the checkpoint says about a run folder, or None when no checkpoint has been written."""
    if not (run_dir / "checkpoint.json").exists():
        return None
    world, council_state, meta = RunStore(run_dir).load_checkpoint()
    return {"months_done": len(world.history), "ended": world.ended(),
            "outcome": (world.outcome or {}).get("type", ""),
            "stopped": str((meta or {}).get("stopped") or ""),
            "spend_usd": round(float((council_state or {}).get("spend", 0.0) or 0.0), 4)}


def _settle(run_dir: Path, error):
    """(state, reason, facts) for a run folder after one attempt. The checkpoint is the record of the run; an
    exception from the engine's entry points says why nothing new was written."""
    facts = _checkpoint_facts(run_dir)
    if facts is not None and facts["ended"]:
        # The run is over. An exception after the end (say, while its report was written) is noted, not a failure.
        note = "" if error is None else f"the engine raised after the run ended: {type(error).__name__}: {error}"
        return "done", note[:500], facts
    if isinstance(error, SystemExit):                 # the engine's seat check refused to start or resume
        reason = (str(error.code) if error.code else "stopped")[:500]
        # A usage limit is temporary and worth a resume; a wrong key or model id is not (wave-3 decision).
        return ("failed" if seat_start_failure(reason) else "paused"), reason, facts
    if error is not None:
        return "failed", f"{type(error).__name__}: {error}"[:500], facts
    if facts is None:
        return "failed", "the run wrote no checkpoint", facts
    stopped = facts["stopped"]
    if stopped.startswith("paused"):
        return "paused", stopped, facts
    if stopped:
        return "failed", stopped, facts
    return "failed", f"stopped at Month {facts['months_done']} with no reason recorded", facts


def _foreign_folder(run_dir: Path, task: dict) -> str:
    """Why a folder being resumed is not this row's (a folder from another plan, say), or "" when it is."""
    saved = RunStore(run_dir).read_json("config.json")
    if saved.get("mapping") != task["seat_map"] or (saved.get("run") or {}).get("seed") != task["seed"]:
        return f"{run_dir} is not this row's run: its config has another seed or seat order"
    return ""


def _attempt(engine, run_dir: Path, task: dict):
    """Call the engine for one row, then (state, reason, facts) for its folder. The checkpoint decides the state
    only when the engine was called: before that, the folder is left as it was."""
    if task["action"] == "resume":
        try:
            wrong = _foreign_folder(run_dir, task)
        except Exception as exc:
            traceback.print_exc()
            return "failed", f"{run_dir} could not be checked: {type(exc).__name__}: {exc}"[:500], None
        if wrong:
            return "failed", wrong[:500], None
    error = None
    try:
        if task["action"] == "resume":
            engine.resume_run(str(run_dir), quiet=False, check=not task["dry_run"])
        else:
            engine.new_run(task["config"], runs_dir=str(run_dir.parent), name=run_dir.name, quiet=False,
                           check=not task["dry_run"])
    except SystemExit as exc:                         # the engine's seat check refused to start or resume
        error = exc
    except Exception as exc:
        traceback.print_exc()
        error = exc
    try:
        return _settle(run_dir, error)
    except Exception as exc:
        traceback.print_exc()
        return "failed", f"checkpoint unreadable: {type(exc).__name__}: {exc}"[:500], None


def _execute(task: dict, engine=None) -> dict:
    """Start or resume one row, then read where its run stopped. Runs in its own process (one task per process),
    or in this one when a test passes an engine."""
    if engine is None:
        from karamaniya import runner as engine
    run_dir = Path(task["run_dir"])
    began = time.monotonic()
    with open(task["log"], "a", encoding="utf-8", newline="\n") as log, \
            contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        print(f"=== {_now()} {task['action']} {task['name']} in {run_dir} ===", flush=True)
        state, reason, facts = _attempt(engine, run_dir, task)
        print(f"=== {state}{': ' + reason if reason else ''} ===", flush=True)
    return {"name": task["name"], "state": state, "reason": reason, "updated": _now(),
            "months_done": facts["months_done"] if facts else 0,
            "outcome": facts["outcome"] if facts else "", "spend_usd": facts["spend_usd"] if facts else 0.0,
            "wall_seconds": round(time.monotonic() - began, 1)}


def _interrupted(task: dict, reason: str) -> dict:
    """A row whose worker died: its checkpoint is still at the last finished month, so it is paused."""
    return {"name": task["name"], "state": "paused", "reason": reason, "updated": _now(), "wall_seconds": 0.0}


def _submit(pool, task: dict, engine) -> Future:
    if pool is None:                                  # tests: the engine runs here, one row at a time
        future = Future()
        try:
            future.set_result(_execute(task, engine))
        except Exception as exc:
            future.set_exception(exc)
        return future
    try:
        return pool.submit(_execute, task)
    except BrokenProcessPool as exc:
        future = Future()
        future.set_exception(exc)
        return future


def _give_up(rec: dict, max_resumes: int) -> None:
    rec["state"] = "failed"
    rec["updated"] = _now()
    rec["reason"] = (f"still paused after {rec['resumes']} resume(s), the limit set by --max-resumes "
                     f"({max_resumes}): {rec['reason']}")


def _record(status: dict, task: dict, result: dict, max_resumes: int) -> None:
    rec = status[task["name"]]
    if task["counted"]:
        rec["resumes"] += 1
    for key in ("state", "reason", "months_done", "outcome", "spend_usd", "updated"):
        if key in result:
            rec[key] = result[key]
    rec["wall_seconds"] = round(rec["wall_seconds"] + result.get("wall_seconds", 0.0), 1)
    if rec["state"] == "paused" and rec["resumes"] >= max_resumes:
        _give_up(rec, max_resumes)


def run_plan(plan_path, *, workers: int = 1, max_resumes: int = DEFAULT_MAX_RESUMES, runs_dir="runs",
             dry_run: bool = False, engine=None, out=None) -> dict:
    """Start or resume every row of a plan that is not finished. Returns each row's status record."""
    say = out or (lambda line: print(line, flush=True))
    if workers < 1:
        raise ValueError("--workers must be at least 1")
    if max_resumes < 0:
        raise ValueError("--max-resumes must be 0 or more")
    plan_path = Path(plan_path).resolve()
    plan_dir = plan_path.parent
    rows = load_plan(plan_path)
    runs_root = Path(runs_dir).resolve()
    status_path = plan_dir / ("status-dry-run.json" if dry_run else "status.json")
    log_dir = plan_dir / ("logs-dry-run" if dry_run else "logs")
    lock_path = plan_dir / (".grid-dry.lock" if dry_run else ".grid.lock")

    # Every config is checked before anything starts. The engine checks one run at a time, so it cannot see a grid.
    configs = {}
    for row in rows:
        path = (plan_dir / row["config"]).resolve()
        try:
            with open(path, "rb") as f:
                check_engine_options(tomllib.load(f).get("run") or {}, dry_run=dry_run)
            cfg = load_config(path)
        except ValueError as exc:
            raise ValueError(f"{row['name']}: {exc}") from exc
        for seat in cfg["seats"]:                     # a hand-edited config must not smuggle in a router
            why = router_reason(seat)
            if why:
                raise ValueError(f"{row['name']}: seat {seat.get('label')!r}: {why}; router seats are excluded "
                                 "from the study")
        configs[row["name"]] = (dry_run_config(cfg) if dry_run else str(path), cfg)
    cline = any(seat.get("provider") == "cline_cli" for _, cfg in configs.values() for seat in cfg["seats"])
    if cline and workers > 1 and not dry_run:
        say("warning: Cline seats share ~/.cline across processes. The engine serializes Cline calls inside one "
            "process only, so --workers above 1 with Cline seats is UNVERIFIED.")

    log_dir.mkdir(parents=True, exist_ok=True)
    with _locked(lock_path):
        status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
        for row in rows:
            rec = status.setdefault(row["name"], _blank(row["name"], runs_root, dry_run, log_dir))
            if rec["state"] == "running":
                rec.update(state="paused", reason="interrupted: the last run stopped while this row was running")
        tasks = []
        for row in rows:
            rec = status[row["name"]]
            if rec["state"] in ("done", "failed"):
                continue
            if rec["state"] == "paused" and rec["resumes"] >= max_resumes:
                _give_up(rec, max_resumes)
                continue
            run_dir = Path(rec["run_dir"])
            tasks.append({"name": row["name"], "run_dir": str(run_dir), "seed": row["seed"],
                          "seat_map": row["seat_map"], "config": configs[row["name"]][0], "dry_run": dry_run,
                          "action": "resume" if (run_dir / "checkpoint.json").exists() else "new",
                          "counted": rec["state"] != "pending", "log": str(plan_dir / rec["log"])})
        _write_status(status_path, status)

        pool = None if engine is not None else ProcessPoolExecutor(max_workers=workers, max_tasks_per_child=1)
        queue, inflight, finished = list(tasks), {}, 0
        try:
            while queue or inflight:
                while queue and len(inflight) < workers:
                    task = queue.pop(0)
                    status[task["name"]].update(state="running", updated=_now())
                    _write_status(status_path, status)
                    inflight[_submit(pool, task, engine)] = task
                done, _ = wait(list(inflight), return_when=FIRST_COMPLETED)
                for future in done:
                    task = inflight.pop(future)
                    try:
                        result = future.result()
                    except BrokenProcessPool as exc:  # a killed worker: its checkpoint is safe, so the row is paused
                        result = _interrupted(task, f"the worker process died ({exc}); rerun the command to resume")
                    except Exception as exc:          # _execute catches its own errors, so this is a bug
                        result = {"name": task["name"], "state": "failed", "updated": _now(),
                                  "reason": f"{type(exc).__name__}: {exc}"[:500]}
                    _record(status, task, result, max_resumes)
                    _write_status(status_path, status)
                    finished += 1
                    rec = status[task["name"]]
                    reason = " | ".join(rec["reason"].splitlines())   # one line here; status.json keeps all of it
                    say(f"[{finished}/{len(tasks)}] {task['name']}: {rec['state']}" + (f" ({reason})" if reason else ""))
        finally:
            if pool is not None:
                pool.shutdown(wait=True, cancel_futures=True)
        _write_status(status_path, status)
        final = {row["name"]: status[row["name"]] for row in rows}
        counts = Counter(rec["state"] for rec in final.values())
        say("summary: " + ", ".join(f"{counts.get(s, 0)} {s}" for s in ("done", "paused", "failed", "pending"))
            + f" (of {len(rows)} rows, status in {status_path.name})")
        if counts.get("paused"):
            say("rerun the same command to resume the paused rows")
    return final


# ---- command line ------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan", help="write the configs, plan.json and a copy of the study file")
    pl.add_argument("study")
    pl.add_argument("out_dir")
    pl.add_argument("--no-study-options", action="store_true",
                    help="leave out office_assignment and action_order (for machinery tests on an engine without them)")
    rn = sub.add_parser("run", help="start the rows of a plan that are not finished, and resume the paused ones")
    rn.add_argument("plan")
    rn.add_argument("--workers", type=int, default=1, help="rows run at once, one process each (default 1)")
    rn.add_argument("--max-resumes", type=int, default=DEFAULT_MAX_RESUMES,
                    help=f"resumes allowed per row before it is failed (default {DEFAULT_MAX_RESUMES})")
    rn.add_argument("--runs-dir", default="runs", help="where run folders go (default: runs)")
    rn.add_argument("--dry-run", action="store_true",
                    help=f"scripted seats, no model calls, at most {DRY_MONTHS} months; keeps its own status file")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "plan":
            rows = plan_study(args.study, args.out_dir, no_study_options=args.no_study_options)
            print(f"planned {len(rows)} rows: {Path(args.out_dir) / 'plan.json'} "
                  f"(configs in {Path(args.out_dir) / 'configs'})")
            if args.no_study_options:
                print("note: --no-study-options leaves out office_assignment and action_order. Use these configs "
                      "for --dry-run and machinery tests only.")
            elif any(key not in RUN_DEFAULTS for key in STUDY_OPTIONS):
                print(f"note: these configs set {', '.join(STUDY_OPTIONS)}, which this engine does not list in "
                      "RUN_DEFAULTS yet; `run` refuses them until the office and order branches are merged.")
            return 0
        if not args.dry_run:
            from karamaniya.envfile import load_env
            load_env(".env")                          # keys saved from the control room, as the CLI does
        final = run_plan(args.plan, workers=args.workers, max_resumes=args.max_resumes, runs_dir=args.runs_dir,
                         dry_run=args.dry_run)
    except (ValueError, OSError, RuntimeError, tomllib.TOMLDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    states = {rec["state"] for rec in final.values()}
    if "failed" in states:
        return 1
    return 0 if states == {"done"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
