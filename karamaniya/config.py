"""Council configuration files (TOML): run settings plus one [[seat]] per AI."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path
from string import ascii_uppercase

MAX_SEATS = 12
SEAT_IDS = ascii_uppercase[:MAX_SEATS]

RUN_DEFAULTS = {
    "months": 36,
    "seed": 1,
    "framing": "simulation",       # simulation | immersive | unobserved
    "dm_per_turn": 3,
    "max_cost_usd": 0.0,           # 0 = no spending cap
    "survey": True,
    "shuffle_seats": True,         # randomise which model sits in which letter
    "parallel_decisions": True,
    "human_factor": True,       # common career pressure and relationships earned through choices
    "founding_scenario": "random",  # random or a named inherited-state archetype or custom
    "founding_severity": "default",  # default | mild | serious | critical
    "founding_problems": [],
    "agent_architecture_version": 2,
    "revision_round": "",          # "" follows tuning (auto) | auto | always | off
    "tuning": {},                  # overrides of karamaniya/tuning.py, e.g. {agenda = {major_motions = 3}}
    "foreign_cabinets": True,      # two monthly strategic calls, reusing configured council backends
    "foreign_cabinet_seats": {},  # optional actor -> existing seat label; otherwise first two configured seats
}


def normalize_config(raw: dict, source: str = "") -> dict:
    """Fill defaults and check a config that came from a file or from the control room."""
    run = {**RUN_DEFAULTS, **(raw.get("run") or {})}
    if raw.get("tuning"):
        run["tuning"] = {**(run.get("tuning") or {}), **raw["tuning"]}
    seats = [dict(s) for s in (raw.get("seat") or raw.get("seats") or [])]
    where = source or "config"
    if not 1 <= len(seats) <= MAX_SEATS:
        raise ValueError(f"{where}: a council needs 1 to {MAX_SEATS} seats, found {len(seats)}")
    for i, s in enumerate(seats):
        if not s.get("provider"):
            raise ValueError(f"{where}: seat {i + 1} has no provider")
        if "max_tokens" in s:
            raw_max_tokens = s["max_tokens"]
            try:
                max_tokens = int(raw_max_tokens)
                whole_number = not isinstance(raw_max_tokens, bool) and not (
                    isinstance(raw_max_tokens, float) and not raw_max_tokens.is_integer())
            except (TypeError, ValueError, OverflowError):
                max_tokens, whole_number = 0, False
            if not whole_number or max_tokens <= 0:
                raise ValueError(f"{where}: seat {i + 1} max_tokens must be a positive integer")
            s["max_tokens"] = max_tokens
        s["label"] = str(s.get("label") or s.get("model") or s.get("persona") or f"seat{i + 1}").strip()
    labels = [s["label"] for s in seats]
    if len(set(labels)) != len(labels):
        raise ValueError(f"{where}: seat labels must be unique, got {labels}")
    if not isinstance(run["foreign_cabinets"], bool):
        raise ValueError("foreign_cabinets must be true or false")
    foreign_seats = run.get("foreign_cabinet_seats") or {}
    if not isinstance(foreign_seats, dict):
        raise ValueError("foreign_cabinet_seats must map actor ids to existing seat labels")
    unknown_actors = set(foreign_seats) - {"veleria", "dorsania"}
    if unknown_actors:
        raise ValueError(f"foreign_cabinet_seats has unknown actors: {sorted(unknown_actors)}")
    unknown_labels = set(foreign_seats.values()) - set(labels)
    if unknown_labels:
        raise ValueError(f"foreign_cabinet_seats must use existing seat labels: {sorted(unknown_labels)}")
    run["foreign_cabinet_seats"] = foreign_seats
    # Token-saving features (karamaniya/token_saving.py): absent unless asked for, so a config that
    # does not mention them normalizes exactly as it always did.
    from . import token_saving
    if "tokens" in run:
        run["tokens"] = token_saving.validate(run["tokens"])
        if not run["tokens"]:
            del run["tokens"]
    if run.get("foreign_cabinet_backend"):
        run["foreign_cabinet_backend"] = token_saving.validate_foreign_backend(run["foreign_cabinet_backend"])
    elif "foreign_cabinet_backend" in run:
        del run["foreign_cabinet_backend"]
    for s in seats:
        if "effort_by_phase" in s:
            s["effort_by_phase"] = token_saving.validate_effort_by_phase(s["effort_by_phase"], f"{where}: seat {s['label']}")
    if run["framing"] not in ("simulation", "immersive", "unobserved"):
        raise ValueError("framing must be 'simulation', 'immersive' or 'unobserved'")
    from .founding import SCENARIOS, TEMPLATES
    if run["founding_scenario"] not in ({"random", "custom"} | set(SCENARIOS)):
        raise ValueError("founding_scenario must be random, custom, or a named scenario")
    if run["founding_severity"] not in ("default", "mild", "serious", "critical"):
        raise ValueError("founding_severity must be default, mild, serious or critical")
    if run["founding_scenario"] == "custom":
        run["founding_problems"] = list(dict.fromkeys(x for x in run.get("founding_problems", []) if x in TEMPLATES))
        if len(run["founding_problems"]) < 3:
            raise ValueError("custom founding scenario requires at least 3 valid founding_problems")
        if len(run["founding_problems"]) > 7:
            raise ValueError("custom founding scenario supports at most 7 founding_problems")
    else:
        run["founding_problems"] = []
    from .tuning import validate as validate_tuning
    run["tuning"] = validate_tuning(run.get("tuning"))
    run["agent_architecture_version"] = int(run.get("agent_architecture_version", 2))
    if run["agent_architecture_version"] not in (1, 2):
        raise ValueError("agent_architecture_version must be 1 or 2")
    if run.get("revision_round", "") not in ("", "auto", "always", "off"):
        raise ValueError("revision_round must be auto, always or off")
    for s in seats:
        base = s.get("trait_baseline")
        if base is not None:
            from .agents import TRAITS
            if not isinstance(base, dict) or set(base) - set(TRAITS):
                raise ValueError(f"{where}: seat {s['label']} trait_baseline has unknown traits")
    if run.get("test_scenario"):
        from .scenarios import resolve_name
        run["test_scenario"] = resolve_name(run["test_scenario"])
    run["months"] = int(run["months"])
    run["seed"] = int(run["seed"])
    if not 1 <= run["months"] <= 120:
        raise ValueError("months must be between 1 and 120")
    return {"run": run, "seats": seats, "source": source}


def load_config(path) -> dict:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return normalize_config(raw, str(Path(path).resolve()))


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{_toml_key(k)} = {_toml_value(x)}" for k, x in v.items()) + " }"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


def _toml_key(k: str) -> str:
    return k if k.replace("_", "").replace("-", "").isalnum() else json.dumps(k)


def dump_config(cfg: dict) -> str:
    """Write a config back as TOML (comments in the original file are not kept)."""
    lines = ["# Written by the Karamaniya control room.", "", "[run]"]
    for k, v in cfg["run"].items():
        lines.append(f"{_toml_key(k)} = {_toml_value(v)}")
    for s in cfg["seats"]:
        lines += ["", "[[seat]]"]
        for k, v in s.items():
            if v is None or v == "":
                continue
            lines.append(f"{_toml_key(k)} = {_toml_value(v)}")
    return "\n".join(lines) + "\n"
