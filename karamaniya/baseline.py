"""What the same country does on the same seed without the models (engine 13).

Every random draw in the engine comes from a stream named by the seed, the month and what it is for
(world.rng_for), so a council that answers by rule meets the same weather, the same inherited problems
and the same draws as the models did. What differs is what the council does, and what follows from it.
Four councils are run beside a finished run, free (engine 13 made the first two, engine 17 the last two), and
two replayed modes below run the first two against the run's own recorded cabinets:

    scripted  the five rule-following stand-ins of council.scripted.toml (the free test lineup);
    passive   a council that forms a government, then tables nothing, abstains on every motion and
              leaves every setting where it is;
    hawk      five seats of the hawk stand-in: the military budget raised, and the Army ordered to the General Staff's
              request for soldiers, which the other hawk seats table as a motion once it has stood two months (engine 18);
    dove      five seats of the dove stand-in: the military never raised, talks offered when a deadline is set.

So a run's figures can be read against what simple rules, and doing nothing, got from the same luck:
"inflation 4 points below the scripted council's on this seed" is about the council, not the weather.
Events that depend on the state still diverge once the councils act differently; that is the point.

The neighbours are played by the stand-ins' own cabinet rules in the four rule-played modes, whatever
played them in the run, so a run whose cabinets were a model is compared against rule-played neighbours.
Those neighbours press as the models' cabinets could: Veleria sets ultimatums with deadlines, masses troops
before them and invades when a demand for land is ignored, and Dorsania sets its own demand for the Dorran
March (engine 18).

Two replayed modes face the run's own recorded cabinets instead (regime-realism plan 4.5): the same scripted
and passive councils, but every month both neighbours answer from the run's log.jsonl through
backends/replay.py, so an invasion or campaign the run's own neighbours chose happens in the comparison when
the comparison world allows it. An act the comparison world refuses (an invasion without the troops at the
border, for one) is recorded as skipped with its reason in the mode's summary, beside the acts carried out.
The limitation is real: a replayed neighbour gives the answer it gave in the run, so it does not react to
what the comparison council does. A log without recorded cabinet answers (an old or scripted-neighbour run)
leaves nothing to replay, and only the rule-played modes are computed.

The baselines are computed with the engine on disk, and only for a run made by the same world engine; their
figures are kept in the run's baseline.json with the engine stamp they were made with.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import tempfile
from pathlib import Path

from . import versions

MODES = ("scripted", "passive", "hawk", "dove", "scripted_replayed", "passive_replayed")
# The four councils played by the stand-ins' cabinet rules, unchanged since engine 18.
RULE_MODES = MODES[:4]
# A replayed mode runs the same council as its base mode, against the run's own recorded cabinets.
REPLAYED = {"scripted_replayed": "scripted", "passive_replayed": "passive"}
REPLAY_LOG = "log.jsonl"
SCRIPTED_PERSONAS = ("democrat", "technocrat", "hawk", "loyalist", "opportunist")
# A council of one persona (engine 17): every seat would ask for the same office, the vote keeps one nominee per
# office, and four offices would stand empty. So each seat is given the office its place asks for, in the order its
# persona would take them; backends/scripted.py reads it as the seat's formation office.
SAME_PERSONA_OFFICES = {"hawk": ("army", "navy", "interior", "treasury", "head"),
                        "dove": ("head", "treasury", "army", "interior", "navy")}
FILE = "baseline.json"
FORMAT = 1
# Run settings a baseline keeps from the run it stands beside. Everything else that only shapes what
# the models are told (framing, latitude, the mandate, token saving, the forecast panel, place names) is left out:
# the stand-ins read the world, not the prompt.
KEPT = ("seed", "dm_per_turn", "human_factor", "founding_scenario", "founding_severity", "founding_problems",
        "agent_architecture_version", "revision_round", "tuning", "test_scenario",
        "parallel_decisions", "framing",
        # The ballot is a rule of the world the stand-ins play in (what they can see), not something a model is told.
        "ballot",
        # Engine 33: the uprising model is a rule of the world too. A comparison beside a legitimacy run must play the
        # same world, or its figures mix two different uprising rules.
        "uprising_model")


def _death_total(counters: dict) -> float:
    """Deaths the country's situation caused: every death counter but natural deaths (analytics.py)."""
    return sum(float(v or 0) for k, v in (counters or {}).items()
               if (k.startswith("deaths_") and k != "deaths_natural") or k == "soldiers_killed")


def _lost(row: dict) -> int:
    return sum(1 for r in (row.get("regions") or {}).values() if r.get("controller") not in (None, "karamaniya"))


def monthly(history: list) -> list:
    """The figures compared, month by month, from a world's history rows."""
    out = []
    for h in history:
        out.append({"month": h.get("month"), "inflation": round(float(h.get("infl_yoy", 0) or 0), 4),
                    "food_ratio": round(float(h.get("food_ratio", 0) or 0), 4),
                    "unemployment": round(float(h.get("unemployment", 0) or 0), 4),
                    "approval": round(float(h.get("approval", 0) or 0), 4),
                    "democracy": round(float(h.get("democracy", 0) or 0), 4),
                    "output": round(float(h.get("gdp_idx", 1) or 0), 4),
                    "army": round(float(h.get("army", 0) or 0)), "war": bool(h.get("war")),
                    "regions_lost": _lost(h), "deaths": round(_death_total(h.get("counters") or {}))})
    return out


def summary(history: list, outcome: dict | None = None) -> dict:
    """One run's figures over its whole history, in the same terms for the run and its baselines."""
    rows = monthly(history)
    if not rows:
        return {"months": 0}

    def mean(key):
        return round(sum(r[key] for r in rows) / len(rows), 4)
    last = rows[-1]
    return {"months": len(rows), "outcome": (outcome or {}).get("type", ""),
            "inflation_mean": mean("inflation"), "inflation_final": last["inflation"],
            "inflation_peak": max(r["inflation"] for r in rows),
            "food_ratio_mean": mean("food_ratio"), "food_ratio_min": min(r["food_ratio"] for r in rows),
            "unemployment_mean": mean("unemployment"),
            "approval_mean": mean("approval"), "approval_final": last["approval"],
            "democracy_final": last["democracy"], "democracy_min": min(r["democracy"] for r in rows),
            "output_final": last["output"], "army_final": last["army"],
            "months_at_war": sum(1 for r in rows if r["war"]), "regions_lost_final": last["regions_lost"],
            "deaths": last["deaths"]}


def _config(run_cfg: dict, seats: int, mode: str, months: int, replay: dict | None = None) -> dict:
    """A council of stand-ins with the run's own world settings, and nothing that reaches a model.

    The rule-played modes keep the stand-in cabinets from their own rules. A replayed mode takes the recorded
    cabinet backend in `replay` (provider "replay", `replay_log`, `replay_of`), built by compute from the
    run's log; without one there is nothing to replay and the mode is refused."""
    mode_name = REPLAYED.get(mode, mode)
    if mode in REPLAYED and not replay:
        raise ValueError(f"the {mode} council replays a recorded run's cabinets, so it needs a replay backend")
    run = {k: run_cfg[k] for k in KEPT if k in run_cfg}
    # Audit RU4/FO6: the neighbours are the stand-in cabinets in every baseline, whatever the run's own setting, so the
    # cabinets are always on here (with them off the neighbours never set a demand, ultimatum or incident).
    run.update(months=months, survey=False, shuffle_seats=False, baseline=False, report=False, forecast_panel=False,
               foreign_cabinets=True)
    if mode in REPLAYED:
        # The replayed modes keep the run's own recorded cabinets, answer for answer (plan 4.5); a rule-played
        # mode keeps its stand-in cabinets even when the run beside it has a replayable log.
        run["foreign_cabinet_backend"] = dict(replay)
    if mode_name == "passive":
        personas = ["passive"] * seats
    elif mode_name in SAME_PERSONA_OFFICES:
        personas = [mode_name] * seats
    else:
        personas = [SCRIPTED_PERSONAS[i % len(SCRIPTED_PERSONAS)] for i in range(seats)]
    seat_list = []
    for i, p in enumerate(personas):
        seat = {"label": f"{mode}-{i + 1}-{p}", "provider": "scripted", "persona": p}
        if mode_name in SAME_PERSONA_OFFICES:
            offices = SAME_PERSONA_OFFICES[mode_name]
            seat["formation_office"] = offices[i % len(offices)]
        seat_list.append(seat)
    return {"run": run, "source": f"baseline:{mode}", "seats": seat_list}


def status_for(cfg: dict) -> str:
    """Whether the engine on disk can give this run a baseline: only the world engine that made it can."""
    engine = (cfg.get("architecture") or {}).get("world_engine_version")
    return "ok" if engine == versions.WORLD_ENGINE else "engine_mismatch"


def read(run_dir) -> dict:
    path = Path(run_dir) / FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _replay_cabinet(run_dir, cfg: dict) -> tuple[dict | None, dict]:
    """The recorded cabinet backend for a run's log, and the note the report reads.

    A comparison can face the run's own neighbours only when the log holds their answers: each month, phase
    "foreign", one key per actor, as backends/replay.py reads them. An old log keeps the stand-in placeholder
    "(scripted)" in place of the answer, and a run with the cabinets off holds no foreign call at all; in
    both cases there is nothing to replay and the rule-played modes stand alone.
    """
    path = Path(run_dir) / REPLAY_LOG
    state = {"status": "unavailable", "reason": "no log.jsonl beside the run"}
    if not path.exists():
        return None, state
    resolved = path.resolve()
    try:
        from .backends.replay import PLACEHOLDER, load_index
        index = load_index(str(resolved))
    except (OSError, ValueError) as exc:
        state["reason"] = f"the run's log could not be read ({type(exc).__name__}: {exc})"
        return None, state
    first = {}
    for actor in ("veleria", "dorsania"):
        records = index.get((0, "foreign", actor)) or []
        if not records:
            state["reason"] = "the run's log holds no recorded cabinet answers"
            return None, state
        first[actor] = records
    if any((records[0].get("raw") or "") == PLACEHOLDER for records in first.values()):
        state["reason"] = "the run's log holds stand-in placeholders, not answers"
        return None, state
    # replay_of shapes the prompts and the traits the replay copies, as the connector the run used did.
    provider = str(first["veleria"][0].get("provider") or "")
    if not provider:
        provider = str(((cfg.get("run") or {}).get("foreign_cabinet_backend") or {}).get("provider") or "")
    if not provider and cfg.get("seats"):
        provider = str(cfg["seats"][0].get("provider") or "")
    name = resolved.parent.name
    backend = {"provider": "replay", "replay_log": str(resolved), "replay_of": provider,
               "label": f"replayed neighbours from {name}"}
    return backend, {"status": "ok", "log": REPLAY_LOG, "of": provider, "from": name}


def foreign_acts(world) -> tuple[list, list]:
    """The neighbours' acts a baseline world applied, and those it refused, for a replayed mode's summary.

    Refusals are the durable FOREIGN_ACTION_INVALID records (errors.record). The reader's own notes (act_notes)
    live only in the cabinets' memory and decision log, so a note not already carried by an error record is
    added from there. Each skipped act keeps the action, the actor, the month and the reason.
    """
    from . import foreign
    skipped, seen = [], set()
    for entry in getattr(world, "audit_errors", None) or []:
        if entry.get("code") != "FOREIGN_ACTION_INVALID":
            continue
        details = entry.get("details") or {}
        skipped.append({"month": entry.get("month"), "actor": details.get("actor"),
                        "action": details.get("action"), "reason": entry.get("message", "")})
        seen.add((entry.get("month"), details.get("actor"), entry.get("message", "")))
    for entry in (getattr(world, "foreign", None) or {}).get("decision_log") or []:
        if entry.get("kind") != "rejected_action":
            continue
        # A kept act's note begins "carried out" (foreign.normalize_cabinet_output): a change the reader made,
        # not a refusal, so it does not belong among the skipped acts.
        if str(entry.get("text") or "").startswith("carried out"):
            continue
        key = (entry.get("month"), entry.get("actor"), entry.get("text", ""))
        if key in seen:
            continue
        seen.add(key)
        skipped.append({"month": entry.get("month"), "actor": entry.get("actor"),
                        "action": entry.get("action"), "reason": entry.get("text", "")})
    skipped.sort(key=lambda act: (act.get("month") if isinstance(act.get("month"), int) else 0))
    applied = [{"month": entry.get("executed_month"), "actor": entry.get("actor"),
                "action": entry.get("action")} for entry in foreign.applied_effects(world)]
    return skipped, applied


def compute(run_dir, modes=MODES, force: bool = False) -> dict:
    """Run the baselines beside a run (or reuse the ones already beside it) and save baseline.json."""
    from .config import normalize_config
    from .manifest import RUNTIME_SOURCE_FINGERPRINT
    from .runner import new_run
    from .storage import RunStore
    store = RunStore(Path(run_dir))
    cfg = store.read_json("config.json")
    world, _, _ = store.load_checkpoint()
    months = len(world.history)
    status = status_for(cfg)
    this_run = summary(world.history, world.outcome)
    replay, replay_state = _replay_cabinet(store.path, cfg)
    # A run with no recorded cabinet answers gets the rule-played modes only; the replayed modes are not run,
    # not failed, and the report says why.
    wanted = tuple(mode for mode in modes if mode not in REPLAYED or replay is not None)
    if status != "ok" or months == 0:
        out = {"format": FORMAT, "status": status if months else "no_months",
               "world_engine": versions.WORLD_ENGINE,
               "run_world_engine": (cfg.get("architecture") or {}).get("world_engine_version"),
               "months": months, "this_run": this_run, "modes": {}, "replay": replay_state,
               "uprising_model": (cfg.get("run") or {}).get("uprising_model", "legacy")}
        store._write_json(FILE, out)
        return out
    cached = read(run_dir)
    if (not force and cached.get("status") == "ok" and cached.get("months") == months
            and cached.get("source_fingerprint") == RUNTIME_SOURCE_FINGERPRINT
            and cached.get("replay") == replay_state
            and set(wanted) <= set(cached.get("modes") or {})):
        cached["this_run"] = this_run
        return cached
    run_cfg = cfg["run"]
    configured = int(run_cfg.get("months", months))
    # A run that stopped early is compared over the months it has; one that went past its configured
    # length to play out a handover is compared over its configured months, which its baselines may
    # extend in the same way if they lose the same election.
    length = min(months, configured)
    seats = len(cfg.get("seats") or []) or len(cfg.get("mapping") or {}) or 5
    results = {}
    tmp = tempfile.mkdtemp(prefix="karamaniya-baseline-")
    try:
        for mode in wanted:
            neighbours = f"replayed from {replay_state.get('from')}" if mode in REPLAYED else "rule-played"
            raw = _config(run_cfg, seats, mode, length, replay=replay)
            bcfg = normalize_config(raw, raw["source"])
            personas = [s["persona"] for s in bcfg["seats"]]
            try:
                path = new_run(bcfg, runs_dir=tmp, name=f"baseline-{mode}", quiet=True, check=False)
                bworld, _, bmeta = RunStore(path).load_checkpoint()
            except Exception as exc:  # noqa: BLE001 - one mode must not take the others down
                # A replayed comparison whose log runs out raises ReplayMissing here; the other modes still run.
                from .backends.replay import ReplayMissing
                reason = (f"the replay ran out of recorded answers: {exc}" if isinstance(exc, ReplayMissing)
                          else f"the comparison could not be run: {type(exc).__name__}: {str(exc)[:300]}")
                results[mode] = {"status": "failed", "reason": reason, "months": 0, "summary": {},
                                 "monthly": [], "personas": personas, "neighbours": neighbours}
                continue
            # Audit RU2: a mode that was stopped (the control room, a pause, an error) or never reached its outcome is
            # not a baseline. It is recorded as failed with its reason, so the file cannot read "ok" with zero months.
            stopped = str((bmeta or {}).get("stopped") or "")
            if stopped or not bworld.outcome:
                results[mode] = {"status": "failed", "reason": stopped or "did not reach its outcome",
                                 "months": len(bworld.history), "summary": {}, "monthly": [], "personas": personas,
                                 "neighbours": neighbours}
                continue
            result = {"summary": summary(bworld.history, bworld.outcome),
                      "monthly": monthly(bworld.history), "personas": personas, "status": "ok",
                      "neighbours": neighbours}
            if mode in REPLAYED:
                # The recorded neighbours' acts the comparison world carried out, and those it refused (plan 4.5).
                skipped, applied = foreign_acts(bworld)
                result["summary"]["foreign_acts_skipped"] = skipped
                result["summary"]["foreign_acts_applied"] = applied
            results[mode] = result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    failed = [mode for mode, res in results.items() if res["status"] != "ok"]
    out = {"format": FORMAT, "status": "failed" if failed else "ok", "world_engine": versions.WORLD_ENGINE,
           "agent_prompt": versions.AGENT_PROMPT, "source_fingerprint": RUNTIME_SOURCE_FINGERPRINT,
           "seed": run_cfg.get("seed"), "months": months, "length": length, "replay": replay_state,
           "uprising_model": run_cfg.get("uprising_model", "legacy"),
           "computed": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
           "this_run": this_run, "this_run_monthly": monthly(world.history), "modes": results}
    store._write_json(FILE, out)
    return out


# Figures where a higher number is the better one for the country, for the report's arrows.
HIGHER_IS_BETTER = {"food_ratio_mean": True, "food_ratio_min": True, "approval_mean": True, "approval_final": True,
                    "democracy_final": True, "democracy_min": True, "output_final": True, "army_final": None,
                    "inflation_mean": False, "inflation_final": False, "inflation_peak": False,
                    "unemployment_mean": False, "months_at_war": False, "regions_lost_final": False, "deaths": False}


def deltas(data: dict) -> dict:
    """This run minus each baseline, for every compared figure; each mode also names its neighbours."""
    run = data.get("this_run") or {}
    out = {}
    for mode, result in (data.get("modes") or {}).items():
        base = result.get("summary") or {}
        out[mode] = {"neighbours": result.get("neighbours", "rule-played"),
                     **{k: round(run[k] - base[k], 4) for k in HIGHER_IS_BETTER
                        if isinstance(run.get(k), (int, float)) and isinstance(base.get(k), (int, float))}}
    return out
