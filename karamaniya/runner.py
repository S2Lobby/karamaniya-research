"""Start, resume, stop and check runs."""
from __future__ import annotations

import datetime as dt
import json
import math
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .backends import make_backend
from .config import SEAT_IDS, load_config
from .council import Council, RunPaused, Seat
from . import manifest
from .storage import RunStore
from .versions import stamp
from .world import month_label, new_world

LETTERS = SEAT_IDS


def _seats(cfg: dict, mapping: dict) -> dict:
    by_label = {s["label"]: s for s in cfg["seats"]}
    return {letter: Seat(letter, label, by_label[label], make_backend(by_label[label]))
            for letter, label in mapping.items()}


def _progress(w, council) -> str:
    h = w.history[-1] if w.history else {}
    coups = int(w.counters.get("coups_attempted", 0))
    active = "".join(m.id for m in w.active_members()) or "-"
    return (f"{month_label(w.month - 1)} done | members {active} | approval {h.get('approval', 0):.0%} "
            f"| inflation {h.get('infl_yoy', 0):.0%} | food {h.get('food_ratio', 0):.0%} "
            f"| army {h.get('army', 0):,.0f} | war {'yes' if h.get('war') else 'no'} | coups {coups} "
            f"| spend ${council.spend:.2f}")


def _emit(observer, **event) -> None:
    if observer is not None:
        try:
            observer(event)
        except Exception:  # progress display must never break a run
            pass


def _call_spend_after(store: RunStore, mark: dict) -> float:
    """Cost of call records appended after a checkpoint's log mark."""
    path = store.path / "log.jsonl"
    if not path.exists():
        return 0.0
    try:
        offset = max(0, int(mark.get("log.jsonl", 0)))
        with path.open("rb") as f:
            f.seek(offset)
            tail = f.read()
    except (OSError, TypeError, ValueError):
        return 0.0
    total = 0.0
    for line in tail.splitlines():
        try:
            record = json.loads(line)
            amount = float(record.get("cost_usd") or 0.0) if record.get("type") == "call" else 0.0
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if math.isfinite(amount) and amount > 0:
            total += amount
    return total


def _stage_spend_recovery(store: RunStore, meta: dict, amount: float) -> dict:
    """Persist recovered spend before truncating its source call records."""
    if amount <= 0:
        return meta
    pending = float(meta.get("_pending_call_spend_recovery", 0.0) or 0.0) + amount
    store.set_meta({"_pending_call_spend_recovery": pending})
    return {**meta, "_pending_call_spend_recovery": pending}


def preflight(cfg: dict) -> list:
    """Seats that cannot answer a tiny call. A run refuses to start while any seat is broken."""
    return [r for r in check_seats(cfg) if not r["ok"]]


def _require_seats(cfg: dict, observer, what: str) -> None:
    _emit(observer, type="checking")
    broken = preflight(cfg)
    if broken:
        lines = []
        for b in broken:
            why = "provider usage limit" if b.get("quota") else "seat error"
            lines.append(f"  {b['label']} ({b['provider']} {b['model']}; {why}): {b['error'][:200]}")
        if all(b.get("quota") for b in broken):
            hint = "The saved checkpoint is unchanged. Retry after the provider's limit resets."
        elif any(b.get("quota") for b in broken):
            hint = ("The saved checkpoint is unchanged. Usage limits reset later; fix any other seat errors "
                    "before retrying.")
        else:
            hint = "Check the login, key or model id with `python -m karamaniya check`, then try again."
        raise SystemExit(f"These seats cannot answer, so the run was not {what}:\n" + "\n".join(lines)
                         + "\n" + hint)


def _survey(store: RunStore, council: Council, observer, quiet: bool) -> str:
    """Ask the questionnaire. Returns why the run paused, or "" once it is answered."""
    _emit(observer, type="survey")
    mark = store.mark()
    try:
        answers = council.survey()
    except RunPaused as exc:
        store.rollback(mark)
        return f"paused before Month 1: {exc}. Resume when the limit resets."
    store._write_json("survey.json", answers)
    if not quiet:
        print("Pre-run questionnaire answered.")
    return ""


def _diagnose(store: RunStore, council: Council, observer, quiet: bool) -> str:
    _emit(observer, type="founding_start", month=0)
    mark = store.mark()
    try:
        diagnoses = council.diagnose_founding()
    except RunPaused as exc:
        store.rollback(mark)
        return f"paused before Month 1 founding diagnoses: {exc}. Resume when the limit resets."
    if not quiet:
        valid = sum(d.get("status") == "submitted" for d in diagnoses.values())
        print(f"Independent founding diagnoses: {valid}/{len(diagnoses)} valid submissions.")
    return ""


def _form_government(store: RunStore, council: Council, observer, quiet: bool) -> str:
    _emit(observer, type="formation_start", month=0)
    mark = store.mark()
    try:
        council.form_government()
    except RunPaused as exc:
        store.rollback(mark)
        return f"paused before Month 1 government formation: {exc}. Resume when the limit resets."
    if not quiet:
        print("Procedural government formation voted.")
    return ""


def _end(store: RunStore, world, council: Council, stopped: str, quiet: bool, observer) -> Path:
    from .report import build_report
    # Refresh the manifest now the run has calls behind it: this is where "which model actually
    # answered" and the structured engine-error tally become meaningful.
    try:
        existing = store.read_json("manifest.json") or {}
        cfg = store.read_json("config.json") or {}
        existing.update({k: v for k, v in manifest.build(world, cfg, store=store).items()})
        existing["outcome"] = dict(world.outcome)
        existing["stopped"] = stopped
        existing["months_simulated"] = len(world.history)
        store._write_json("manifest.json", existing)
    except Exception:
        pass  # a manifest failure must never take down a finished run
    if not quiet:
        print(f"Stopped: {stopped} (resume to continue)" if stopped else f"Outcome: {world.outcome.get('text')}")
    path = build_report(store)
    _emit(observer, type="finished", stopped=stopped, outcome=dict(world.outcome), spend=council.spend)
    if not quiet:
        print(f"Report: {path}")
    return store.path


def new_run(config, runs_dir="runs", name=None, months=None, seed=None, framing=None,
            survey=None, quiet=False, check=True, observer=None, stop_event=None,
            live_report=False) -> Path:
    """Start a run. `config` is a path to a TOML file or an already loaded config dict."""
    cfg = config if isinstance(config, dict) else load_config(config)
    cfg = {**cfg, "run": dict(cfg["run"])}
    if check:
        _require_seats(cfg, observer, "started")
    run = cfg["run"]
    for key, val in (("months", months), ("seed", seed), ("framing", framing), ("survey", survey)):
        if val is not None:
            run[key] = val
    try:
        run["months"] = int(run["months"])
    except (TypeError, ValueError) as exc:
        raise ValueError("months must be between 1 and 120") from exc
    if not 1 <= run["months"] <= 120:
        raise ValueError("months must be between 1 and 120")
    labels = [s["label"] for s in cfg["seats"]]
    order = list(range(len(labels)))
    if run["shuffle_seats"]:
        random.Random(f"seats:{run['seed']}").shuffle(order)
    mapping = {LETTERS[i]: labels[j] for i, j in enumerate(order)}
    created = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = name or f"{created}-seed{run['seed']}"
    store = RunStore(Path(runs_dir) / run_id)
    if store.exists("checkpoint.json"):
        raise FileExistsError(f"{store.path} already has a run; use resume")
    architecture = int(run.get("agent_architecture_version", 2))
    store.save_config({**cfg, "mapping": mapping, "created": created, "architecture": stamp(architecture)})
    by_label = {s["label"]: s for s in cfg["seats"]}
    baselines = {letter: by_label[label].get("trait_baseline") for letter, label in mapping.items()
                 if by_label[label].get("trait_baseline")}
    world = new_world(run["seed"], run["months"], run["framing"], member_ids=list(mapping),
                      human_factor=run.get("human_factor", True),
                      founding_scenario=run.get("founding_scenario", "random"),
                      founding_severity=run.get("founding_severity", "default"),
                      founding_problems=run.get("founding_problems"),
                      agent_architecture_version=architecture, tuning=run.get("tuning"),
                      trait_baselines=baselines)
    # The manifest is written before the first call, so a run that dies early is still readable.
    store._write_json("manifest.json", manifest.build(world, {**cfg, "mapping": mapping}))
    council = Council(world, _seats(cfg, mapping), run, store, observer=observer)
    (store.path / "system_prompt.txt").write_text(council.system, encoding="utf-8")
    _emit(observer, type="started", run_id=run_id, mapping=mapping, months_total=run["months"])
    if not quiet:
        print(f"Run {run_id}: {len(mapping)} seats, {run['months']} months, seed {run['seed']}, "
              f"framing {run['framing']}")
        for letter, label in mapping.items():
            print(f"  Delegate {letter} = {label}")
    # Checkpoint BEFORE the first call. The questionnaire, the five independent diagnoses and the
    # government formation are twenty model calls that used to happen with nothing on disk: the
    # first checkpoint came after all of them, so a machine going down mid-formation lost the lot
    # and left a run directory with no resume point at all. Observed for real — seventeen paid calls
    # lost because a server was killed during the formation vote.
    def _save(**flags):
        store.save_checkpoint(world, council.state(),
                              {"run_id": run_id, "stopped": "", "log_mark": store.mark(), **flags})

    _save(survey_pending=bool(run["survey"]), founding_diagnosis_pending=True,
          government_formation_pending=True)
    paused = _survey(store, council, observer, quiet) if run["survey"] else ""
    if not paused:
        _save(survey_pending=False, founding_diagnosis_pending=True, government_formation_pending=True)
    diagnosis_pending = False
    if not paused:
        paused = _diagnose(store, council, observer, quiet)
        diagnosis_pending = bool(paused)
        if not paused:
            _save(survey_pending=False, founding_diagnosis_pending=False,
                  government_formation_pending=True)
    formation_pending = False
    if not paused:
        paused = _form_government(store, council, observer, quiet)
        formation_pending = bool(paused)
    if not paused:
        _apply_scenario(world, run)
    store.save_checkpoint(world, council.state(), {"run_id": run_id, "stopped": paused, "log_mark": store.mark(),
                                                   "survey_pending": bool(paused and run["survey"] and not diagnosis_pending and not formation_pending),
                                                   "founding_diagnosis_pending": diagnosis_pending,
                                                   "government_formation_pending": formation_pending})
    if paused:
        return _end(store, world, council, paused, quiet, observer)
    return _loop(store, world, council, run, quiet, observer, stop_event, live_report)


def resume_run(run_dir, quiet=False, observer=None, stop_event=None, live_report=False, check=True) -> Path:
    store = RunStore(run_dir)
    cfg = store.read_json("config.json")
    if check:
        _require_seats(cfg, observer, "resumed")
    world, council_state, meta = store.load_checkpoint()
    # If a month was interrupted by a crash rather than by a clean pause, its log lines are still
    # there and the replay would write a second copy of them. Cut back to where the logs stood when
    # the last month actually finished. Preserve any logged call cost before truncating those
    # records, so replaying an abandoned month cannot make the spending cap forget paid calls.
    # A checkpoint written before this mark existed has none, and is left alone.
    meta = dict(meta or {})
    log_mark = meta.get("log_mark")
    pending_spend = meta.get("_pending_call_spend_recovery")
    if pending_spend is not None:
        try:
            orphaned_spend = max(0.0, float(pending_spend))
        except (TypeError, ValueError):
            orphaned_spend = 0.0
    else:
        orphaned_spend = _call_spend_after(store, log_mark) if log_mark else 0.0
        meta = _stage_spend_recovery(store, meta, orphaned_spend)
    if log_mark:
        store.rollback(log_mark)
    if orphaned_spend > 0:
        council_state = dict(council_state)
        council_state["spend"] = float(council_state.get("spend", 0.0) or 0.0) + orphaned_spend
        meta.pop("_pending_call_spend_recovery", None)
        meta["log_mark"] = store.mark()
        store.save_checkpoint(world, council_state, meta)
    upgraded = _maybe_upgrade(store, cfg, world, quiet)
    council = Council(world, _seats(cfg, cfg["mapping"]), cfg["run"], store, observer=observer)
    prompt_path = store.path / "system_prompt.txt"
    if prompt_path.exists() and not upgraded:
        council.system = prompt_path.read_text(encoding="utf-8")
    elif upgraded:
        prompt_path.write_text(council.system, encoding="utf-8")
    council.load_state(council_state)
    _emit(observer, type="started", run_id=store.path.name, mapping=cfg["mapping"],
          months_total=world.months_total, months_done=len(world.history))
    if not quiet:
        print(f"Resuming {store.path.name} at {month_label(world.month)}")
    if meta.get("survey_pending"):
        paused = _survey(store, council, observer, quiet)
        if paused:
            meta.update({"stopped": paused})
            store.save_checkpoint(world, council.state(), meta)
            return _end(store, world, council, paused, quiet, observer)
        meta.update({"survey_pending": False, "stopped": "", "log_mark": store.mark()})
        store.save_checkpoint(world, council.state(), meta)
    if meta.get("founding_diagnosis_pending") or (world.founding and not world.founding.get("diagnoses")):
        paused = _diagnose(store, council, observer, quiet)
        if paused:
            meta.update({"stopped": paused, "founding_diagnosis_pending": True})
            store.save_checkpoint(world, council.state(), meta)
            return _end(store, world, council, paused, quiet, observer)
        meta.update({"founding_diagnosis_pending": False, "stopped": "", "log_mark": store.mark()})
        store.save_checkpoint(world, council.state(), meta)
    if world.month == 0 and world.founding and (meta.get("government_formation_pending") or not world.founding.get("formation")):
        paused = _form_government(store, council, observer, quiet)
        if paused:
            meta.update({"stopped": paused, "government_formation_pending": True})
            store.save_checkpoint(world, council.state(), meta)
            return _end(store, world, council, paused, quiet, observer)
        meta.update({"government_formation_pending": False, "stopped": "", "log_mark": store.mark()})
        store.save_checkpoint(world, council.state(), meta)
    if not world.history:
        _apply_scenario(world, cfg["run"])
        meta.update({"stopped": "", "log_mark": store.mark()})
        store.save_checkpoint(world, council.state(), meta)
    return _loop(store, world, council, cfg["run"], quiet, observer, stop_event, live_report)


def _apply_scenario(world, run: dict) -> None:
    """A deterministic test scenario (spec 96) is applied once, after government formation."""
    if run.get("test_scenario") and not world.agenda.get("scenario_applied"):
        from .scenarios import apply as apply_scenario
        apply_scenario(world, run["test_scenario"])


def _maybe_upgrade(store: RunStore, cfg: dict, world, quiet: bool) -> bool:
    """Spec 106: a version-1 run that has not simulated a month yet moves to the current agent
    architecture (its founding diagnoses and appointments are kept). Runs with recorded months keep
    the architecture they were recorded under, so their history stays comparable."""
    from .versions import AGENT_ARCHITECTURE
    if (world.agent_architecture_version != 1 or world.history or not world.human_factor
            or cfg.get("run", {}).get("agent_architecture_version") == 1 and cfg.get("pin_architecture")):
        return False
    from . import agents
    world.agent_architecture_version = AGENT_ARCHITECTURE
    agents.ensure(world)
    cfg["architecture"] = {**stamp(AGENT_ARCHITECTURE), "migrated_from": 1, "migrated_at_month": world.month}
    cfg["run"] = {**cfg.get("run", {}), "agent_architecture_version": AGENT_ARCHITECTURE}
    store.save_config(cfg)
    store.log({"type": "migration", "month": world.month, "from": 1, "to": AGENT_ARCHITECTURE,
               "note": "no month had been simulated; founding diagnoses and appointments were kept"})
    if not quiet:
        print(f"Upgraded {store.path.name} to agent architecture v{AGENT_ARCHITECTURE} before Month 1.")
    return True


def _loop(store: RunStore, world, council: Council, run: dict, quiet: bool, observer=None,
          stop_event=None, live_report=False) -> Path:
    from .report import build_report
    cap = float(run.get("max_cost_usd") or 0.0)
    stopped, paused = "", False
    if live_report and world.history:
        build_report(store)
    while not world.ended():
        if cap and council.spend >= cap:
            stopped = f"spending cap of ${cap:.2f} reached"
            break
        if stop_event is not None and stop_event.is_set():
            stopped = "stopped from the control room"
            break
        mark = store.mark()
        try:
            council.run_month()
        except RunPaused as exc:
            # Nothing of the unfinished month is kept: its log lines go, the checkpoint stays at the
            # last finished month, and resuming replays the month from the start.
            stopped = (f"paused in {month_label(world.month)}: {exc}. Resume when the limit resets; "
                       "the month will be replayed.")
            paused = True
            saved_world, saved_council_state, saved_meta = store.load_checkpoint()
            saved_council_state = dict(saved_council_state)
            saved_meta = dict(saved_meta or {})
            saved_spend = float(saved_council_state.get("spend", 0.0) or 0.0)
            attempt_spend = max(0.0, float(council.spend) - saved_spend)
            saved_meta = _stage_spend_recovery(store, saved_meta, attempt_spend)
            store.rollback(mark)
            saved_council_state["spend"] = saved_spend + attempt_spend
            saved_meta.pop("_pending_call_spend_recovery", None)
            saved_meta.update({"stopped": stopped, "log_mark": store.mark()})
            store.save_checkpoint(saved_world, saved_council_state, saved_meta)
            break
        # Record where the logs stand now that the month is finished. A clean pause rolls the
        # unfinished month out of the logs, but a crash cannot — nothing runs — so the partial
        # month's lines stay and the replay appends a second copy. Storing the mark lets the next
        # resume truncate back to the last month that actually completed.
        store.save_checkpoint(world, council.state(), {"stopped": "", "log_mark": store.mark()})
        if live_report:
            build_report(store)
        h = world.history[-1]
        _emit(observer, type="month_done", months_done=len(world.history), spend=council.spend,
              outcome=dict(world.outcome), line=_progress(world, council),
              events=[e["text"] for e in h.get("events", []) if e.get("public", True)
                      and e.get("importance", 1) >= 2][:10],
              stats={k: h.get(k) for k in ("approval", "infl_yoy", "food_ratio", "army", "war", "unrest",
                                           "democracy")},
              members={m.id: m.status for m in world.members}, offices=dict(world.const.offices))
        if not quiet:
            print(_progress(world, council), flush=True)
        if cap and council.spend >= cap and not world.ended():
            stopped = f"spending cap of ${cap:.2f} reached"
            break
    if paused:
        store.set_meta({"stopped": stopped})
    else:
        store.save_checkpoint(world, council.state(), {"stopped": stopped, "log_mark": store.mark()})
    return _end(store, world, council, stopped, quiet, observer)


def check_seats(config) -> list:
    """One tiny call per seat, all at once: are keys and models working, which model answers?"""
    cfg = config if isinstance(config, dict) else load_config(config)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}, "note": {"type": "string"}},
              "required": ["ok", "note"], "additionalProperties": False}

    def one(s):
        try:
            backend = make_backend(s)
            backend.retries = 0
            backend.timeout = min(backend.timeout, 120)
            res = backend.complete("You are a connectivity check. Answer with the JSON requested.",
                                   'Reply with {"ok": true, "note": "ready"}.', schema, {"phase": "survey"})
            return {"label": s["label"], "provider": s["provider"], "model": s.get("model", ""),
                    "served_model": res.served_model, "ok": res.data is not None,
                    "error": res.error, "quota": res.quota,
                    "latency_s": res.latency_s, "cost_usd": res.cost_usd}
        except Exception as exc:  # report every seat, even if one is misconfigured
            return {"label": s["label"], "provider": s["provider"], "model": s.get("model", ""),
                    "served_model": "", "ok": False, "error": f"{type(exc).__name__}: {exc}",
                    "quota": False, "latency_s": 0, "cost_usd": 0}

    with ThreadPoolExecutor(max_workers=max(1, len(cfg["seats"]))) as ex:
        return list(ex.map(one, cfg["seats"]))
