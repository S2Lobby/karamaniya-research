"""What the same country does on the same seed without the models (engine 13).

Every random draw in the engine comes from a stream named by the seed, the month and what it is for
(world.rng_for), so a council that answers by rule meets the same weather, the same inherited problems
and the same draws as the models did. What differs is what the council does, and what follows from it.
Two councils are run beside a finished run, free and in seconds:

    scripted  the five rule-following stand-ins of council.scripted.toml (the free test lineup);
    passive   a council that forms a government, then tables nothing, abstains on every motion and
              leaves every setting where it is.

So a run's figures can be read against what simple rules, and doing nothing, got from the same luck:
"inflation 4 points below the scripted council's on this seed" is about the council, not the weather.
Events that depend on the state still diverge once the councils act differently; that is the point.

The neighbours are played by the stand-ins' own cabinet rules in both baselines, whatever played them in
the run, so a run whose cabinets were a model is compared against rule-played neighbours. The baselines
are computed with the engine on disk, and only for a run made by the same world engine; their figures are
kept in the run's baseline.json with the engine stamp they were made with.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import tempfile
from pathlib import Path

from . import versions

MODES = ("scripted", "passive")
SCRIPTED_PERSONAS = ("democrat", "technocrat", "hawk", "loyalist", "opportunist")
FILE = "baseline.json"
FORMAT = 1
# Run settings a baseline keeps from the run it stands beside. Everything else that only shapes what
# the models are told (framing, latitude, token saving, the forecast panel, place names) is left out:
# the stand-ins read the world, not the prompt.
KEPT = ("seed", "dm_per_turn", "human_factor", "founding_scenario", "founding_severity", "founding_problems",
        "agent_architecture_version", "revision_round", "tuning", "foreign_cabinets", "test_scenario",
        "parallel_decisions", "framing")


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


def _config(run_cfg: dict, seats: int, mode: str, months: int) -> dict:
    """A council of stand-ins with the run's own world settings, and nothing that reaches a model."""
    run = {k: run_cfg[k] for k in KEPT if k in run_cfg}
    run.update(months=months, survey=False, shuffle_seats=False, baseline=False, report=False, forecast_panel=False)
    personas = (["passive"] * seats if mode == "passive"
                else [SCRIPTED_PERSONAS[i % len(SCRIPTED_PERSONAS)] for i in range(seats)])
    return {"run": run, "source": f"baseline:{mode}",
            "seats": [{"label": f"{mode}-{i + 1}-{p}", "provider": "scripted", "persona": p}
                      for i, p in enumerate(personas)]}


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
    if status != "ok" or months == 0:
        out = {"format": FORMAT, "status": status if months else "no_months",
               "world_engine": versions.WORLD_ENGINE,
               "run_world_engine": (cfg.get("architecture") or {}).get("world_engine_version"),
               "months": months, "this_run": this_run, "modes": {}}
        store._write_json(FILE, out)
        return out
    cached = read(run_dir)
    if (not force and cached.get("status") == "ok" and cached.get("months") == months
            and cached.get("source_fingerprint") == RUNTIME_SOURCE_FINGERPRINT
            and set(modes) <= set(cached.get("modes") or {})):
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
        for mode in modes:
            raw = _config(run_cfg, seats, mode, length)
            bcfg = normalize_config(raw, raw["source"])
            path = new_run(bcfg, runs_dir=tmp, name=f"baseline-{mode}", quiet=True, check=False)
            bworld, _, _ = RunStore(path).load_checkpoint()
            results[mode] = {"summary": summary(bworld.history, bworld.outcome),
                             "monthly": monthly(bworld.history),
                             "personas": [s["persona"] for s in bcfg["seats"]]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out = {"format": FORMAT, "status": "ok", "world_engine": versions.WORLD_ENGINE,
           "agent_prompt": versions.AGENT_PROMPT, "source_fingerprint": RUNTIME_SOURCE_FINGERPRINT,
           "seed": run_cfg.get("seed"), "months": months, "length": length,
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
    """This run minus each baseline, for every compared figure."""
    run = data.get("this_run") or {}
    out = {}
    for mode, result in (data.get("modes") or {}).items():
        base = result.get("summary") or {}
        out[mode] = {k: round(run[k] - base[k], 4) for k in HIGHER_IS_BETTER
                     if isinstance(run.get(k), (int, float)) and isinstance(base.get(k), (int, float))}
    return out
