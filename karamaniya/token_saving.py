"""Opt-in ways of spending fewer tokens on the council, and the settings that switch them on.

Every one of them changes what a delegate is sent or when it is asked, so every one is OFF by default
and a run without a `[run.tokens]` table is engine 5 exactly: tests/test_prompt_freeze.py holds the
prompts of a default run to recorded fingerprints. A run that turns one on records it in config.json
and in the manifest (`token_saving`), and manifest.divergences() names it, so a run with a feature on
is never compared with one without as if they were alike.

    [run.tokens]
    layout = "cache_friendly"   # classic | cache_friendly
    schema_hint = "auto"        # example | compact | auto
    briefing = "on_demand"      # full | on_demand
    wakeups = "on_events"       # always | on_events
    max_quiet_months = 3        # with wakeups = "on_events": longest run of quiet months in a row

    [run]
    foreign_cabinet_backend = { provider = "ollama", model = "qwen3.5:9b" }   # one fixed model for both

    [[seat]]
    effort_by_phase = { decision = "high", session = "low", revision = "low" }

What each one does, and what it was measured to save, is in docs/TOKEN_EFFICIENCY.md.
"""
from __future__ import annotations

DEFAULTS = {
    "layout": "classic",
    "schema_hint": "example",
    "briefing": "full",
    "wakeups": "always",
    "max_quiet_months": 3,
}
CHOICES = {
    "layout": ("classic", "cache_friendly"),
    "schema_hint": ("example", "compact", "auto"),
    "briefing": ("full", "on_demand"),
    "wakeups": ("always", "on_events"),
}
#: The phases a seat's effort_by_phase may name: the `phase` every model call is made with.
PHASES = ("session", "revision", "decision", "survey", "founding_diagnosis", "formation_proposal",
          "formation_vote", "motion_repair", "principles_repair", "foreign")


def validate(raw) -> dict:
    """A `[run.tokens]` table, checked. Keeps only what was set: the defaults stay implicit."""
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ValueError("[run.tokens] must be a table")
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"[run.tokens] has unknown settings: {sorted(unknown)}; known: {sorted(DEFAULTS)}")
    out = {}
    for key, value in raw.items():
        if key in CHOICES:
            if value not in CHOICES[key]:
                raise ValueError(f"tokens.{key} must be one of {CHOICES[key]}, not {value!r}")
            out[key] = value
        elif key == "max_quiet_months":
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 12:
                raise ValueError("tokens.max_quiet_months must be a whole number from 1 to 12")
            out[key] = value
    return out


def settings(run: dict | None) -> dict:
    """Every setting with its value for this run, defaults filled in."""
    return {**DEFAULTS, **validate((run or {}).get("tokens"))}


def validate_effort_by_phase(table, where: str = "seat") -> dict:
    if not isinstance(table, dict):
        raise ValueError(f"{where}: effort_by_phase must be a table of phase = effort")
    unknown = set(table) - set(PHASES)
    if unknown:
        raise ValueError(f"{where}: effort_by_phase names unknown phases {sorted(unknown)}; known: {list(PHASES)}")
    return {phase: str(value) for phase, value in table.items()}


def validate_foreign_backend(raw) -> dict:
    if not isinstance(raw, dict) or not raw.get("provider"):
        raise ValueError("foreign_cabinet_backend must be a table with at least a provider")
    out = dict(raw)
    out["label"] = str(out.get("label") or out.get("model") or out["provider"]).strip()
    return out


def describe(cfg: dict) -> dict:
    """What a run changed from the default, for the manifest. Empty for a default run."""
    run = cfg.get("run") or {}
    out = dict(validate(run.get("tokens")))
    if run.get("foreign_cabinet_backend"):
        backend = run["foreign_cabinet_backend"]
        out["foreign_cabinet_backend"] = {k: backend.get(k) for k in ("provider", "model", "label") if backend.get(k)}
    efforts = {s.get("label"): s["effort_by_phase"] for s in (cfg.get("seats") or []) if s.get("effort_by_phase")}
    if efforts:
        out["effort_by_phase"] = efforts
    return out
