"""Council configuration files (TOML): run settings plus one [[seat]] per AI."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path
from string import ascii_uppercase

MAX_SEATS = 12
SEAT_IDS = ascii_uppercase[:MAX_SEATS]
# Engine 24 (S1): "formation" is the Month-0 vote that fills the offices. "by_letter" skips the vote and fixes them
# by letter, so that moving a model between letters moves it between offices (the SocioVerse rotations need this).
OFFICE_ASSIGNMENTS = ("formation", "by_letter")
OFFICES_BY_LETTER = {"A": "head", "B": "treasury", "C": "interior", "D": "army", "E": "navy"}

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
    "judge": False,                # evaluator models observing the run from outside it (judges.py)
    "foreign_cabinet_seats": {},  # optional actor -> existing seat label; otherwise first two configured seats
    "office_assignment": "formation",  # formation (the Month-0 vote) | by_letter (A-E hold the five offices; engine 24)
    "action_order": "seeded_shuffle",  # seeded_shuffle | fixed_precedence: the speaking order (council.speaking_order)
    # Wave A (plan 4.6): the arms. `harness` is offered by every call site through actions.harness_of; "menu" is
    # engine 29 exactly. `referee_effects` = "zeroed" is the ablation: rulings are made and logged, effects are not
    # applied. `referee_backend` is a seat-like model, absent by default and required under "open". `knockout` is the
    # removal arm, absent by default (the normalizer deletes it when unset, as the ballot and latitude arms are).
    "harness": "menu",
    "referee_effects": "applied",
    "referee_backend": None,
    "knockout": None,
}

REFEREE_EFFECTS = ("applied", "zeroed")


def check_office_assignment(run: dict, seat_count: int, where: str = "config") -> None:
    """Refuse an unknown office_assignment, and by_letter for a council that is not exactly five members."""
    value = run.get("office_assignment", "formation")
    if value not in OFFICE_ASSIGNMENTS:
        raise ValueError(f"{where}: office_assignment must be 'formation' or 'by_letter', got {value!r}")
    if value == "by_letter" and seat_count != len(OFFICES_BY_LETTER):
        raise ValueError(f"{where}: office_assignment = 'by_letter' needs exactly five members (A to E hold head "
                         f"of government, treasury, interior, army and navy), found {seat_count}")


def _model_of(cfg: dict) -> str:
    """The model a seat-like config names. A scripted stand-in names its persona rather than a model."""
    return str(cfg.get("model") or cfg.get("persona") or "").strip().lower()


def check_referee_backend(run: dict, seats: list, where: str = "config") -> None:
    """Validate and normalize `referee_backend`; refuse a referee that is one of the council's seats.

    The referee is a seat-like config, handled as `foreign_cabinet_backend` is: at least a provider, and a label
    defaulted from its model or provider. It must not be a council seat (the same provider and model, or the same
    label), because the plan requires a different model family from every delegate. The config can check identity,
    not family, so the family rule is stated here and in docs/REFEREE_CODEBOOK.md rather than guessed from a model
    table. Under `harness = "open"` it is required: an open run with no referee cannot rule an act, and a run is
    refused at start rather than failing at the first act.
    """
    from .actions import validate_harness
    harness = validate_harness(run.get("harness", "menu"))
    raw = run.get("referee_backend")
    if raw:
        if not isinstance(raw, dict) or not raw.get("provider"):
            raise ValueError(f"{where}: referee_backend must be a table with at least a provider")
        backend = dict(raw)
        backend["label"] = str(backend.get("label") or backend.get("model") or backend["provider"]).strip()
        provider, model, label = str(backend["provider"]).strip().lower(), _model_of(backend), backend["label"]
        for seat in seats:
            same_label = str(seat.get("label") or "").strip() == label
            same_model = (str(seat.get("provider") or "").strip().lower() == provider
                          and _model_of(seat) == model)
            if same_label or same_model:
                what = "label" if same_label else "provider and model"
                raise ValueError(
                    f"{where}: referee_backend must not be one of the council's seats; it matches the {what} of "
                    f"seat {seat.get('label')!r}. The referee must come from a different model family than every "
                    "delegate. The config can check only that it is not the same seat, so check the family "
                    "yourself: pick a model from another maker's family.")
        run["referee_backend"] = backend
    elif "referee_backend" in run:
        del run["referee_backend"]
    if harness == "open" and not run.get("referee_backend"):
        raise ValueError(
            f"{where}: harness = 'open' needs run.referee_backend: a fixed seat-like model (provider, model, "
            "temperature 0) from a different model family than every delegate. The referee rules open acts and is "
            "machinery, not a council seat; without it no open act could be carried out.")


def check_knockout(run: dict, where: str = "config") -> None:
    """Validate `knockout` and keep it absent when unset, so a default config normalizes exactly as before."""
    from .knockout import validate_option
    try:
        option = validate_option(run.get("knockout"))
    except ValueError as exc:
        raise ValueError(f"{where}: {exc}") from exc
    if option is None:
        run.pop("knockout", None)
    else:
        run["knockout"] = option


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
    # Wave A arms (plan 4.6). `harness` and `referee_effects` stay in the normalized run like office_assignment and
    # action_order; `referee_backend` and `knockout` are absent when unset.
    from .actions import validate_harness
    run["harness"] = validate_harness(run.get("harness", "menu"))
    if run["referee_effects"] not in REFEREE_EFFECTS:
        raise ValueError(f"referee_effects must be 'applied' or 'zeroed', got {run['referee_effects']!r}")
    check_referee_backend(run, seats, where)
    check_knockout(run, where)
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
    check_office_assignment(run, len(seats), where)

    if run.get("judge"):
        if run["judge"] is not True:
            raise ValueError("judge must be true or false")
        backs = run.get("judge_backends")
        if not isinstance(backs, list) or not 1 <= len(backs) <= 3:
            raise ValueError("judge = true needs judge_backends: a list of 1 to 3 evaluator models")
        judges = []
        for i, b in enumerate(backs):
            if not isinstance(b, dict) or not b.get("provider"):
                raise ValueError(f"judge {i + 1} needs at least a provider")
            j = dict(b)
            j["label"] = str(j.get("label") or j.get("model") or j["provider"]).strip()
            judges.append(j)
        run["judge_backends"] = judges
        every = run.get("judge_every_months", 1)
        if not isinstance(every, int) or isinstance(every, bool) or not 1 <= every <= 12:
            raise ValueError("judge_every_months must be a whole number from 1 to 12")
        run["judge_every_months"] = every
    else:
        for key in ("judge_backends", "judge_every_months", "judge_questions"):
            run.pop(key, None)
    for s in seats:
        if "effort_by_phase" in s:
            s["effort_by_phase"] = token_saving.validate_effort_by_phase(s["effort_by_phase"], f"{where}: seat {s['label']}")
    if run["framing"] not in ("simulation", "immersive", "unobserved"):
        raise ValueError("framing must be 'simulation', 'immersive' or 'unobserved'")
    # Engine 13 switches, absent at their defaults, so a default config normalizes as it always did: a run
    # writes its report, and each decision answers the monthly forecast panel (forecasts.py). The same-seed
    # baselines (baseline.py) run after a run with at least one model seat; true runs them for a council of
    # stand-ins too, false never.
    # Engine 29 adds debrief, the closing question once a run has ended (runner._debrief): absent means asked.
    for key in ("baseline", "report", "forecast_panel", "debrief"):
        if key in run:
            if not isinstance(run[key], bool):
                raise ValueError(f"{key} must be true or false")
            if run[key] and key != "baseline":
                del run[key]
    # Place names drawn from the seed (naming.py): absent means the canonical names.
    if "world_names" in run:
        if run["world_names"] not in ("fixed", "seeded"):
            raise ValueError("world_names must be 'fixed' or 'seeded'")
        if run["world_names"] == "fixed":
            del run["world_names"]
    # The latitude arm (prompts.LATITUDE_TEXT): absent unless asked for, so a default config normalizes
    # exactly as it always did.
    if "latitude" in run:
        if run["latitude"] not in ("default", "permitted"):
            raise ValueError("latitude must be 'default' or 'permitted'")
        if run["latitude"] == "default":
            del run["latitude"]
    # The mandate arm (prompts.MANDATE_TEXT, engine 16), absent unless asked for, like the latitude arm.
    if "mandate" in run:
        if run["mandate"] not in ("default", "crisis"):
            raise ValueError("mandate must be 'default' or 'crisis'")
        if run["mandate"] == "default":
            del run["mandate"]
    # The ballot arm (engine 18): "open", the default, is absent from the run; "secret" hides each member's vote from
    # the other members (standing.py, agents.py, human.py). A config that does not mention it normalizes as before.
    if "ballot" in run:
        if run["ballot"] not in ("open", "secret"):
            raise ValueError("ballot must be 'open' or 'secret'")
        if run["ballot"] == "open":
            del run["ballot"]
    # The action-order arm (brief 9.S3). It is always recorded, unlike the arms above, because the study compares the
    # two protocols on the same seeds and each run's config.json must say which one it used. "seeded_shuffle" is the
    # order the council has always drawn each month; "fixed_precedence" speaks the office holders first, in the order
    # of world.OFFICES, and the other active members in letter order.
    if run["action_order"] not in ("seeded_shuffle", "fixed_precedence"):
        raise ValueError("action_order must be 'seeded_shuffle' or 'fixed_precedence'")
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
