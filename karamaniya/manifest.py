"""What produced this run, recorded so a later reader can judge it.

Karamaniya is meant to be usable as a benchmark — comparing models across seats, seeds and
office assignments — and that only works if a run carries enough context to be interpreted
later. Two runs that differ in output might differ because the models behaved differently, or
because a prompt changed, or because the engine's rules changed, or because a seat was quietly
a different model than the label claimed. The manifest is what tells those apart.

**Language models are not deterministic and this does not pretend otherwise.** The same model at
the same temperature on the same prompt can answer differently twice. What is recorded instead is
everything needed to *analyse* a difference: the exact sampling settings, the model that actually
served each call (not the one requested), the prompt and engine versions, and the seeds that do
govern the deterministic half of the world.

The deterministic half is genuinely reproducible and is worth separating out: given the same seed,
world generation, structural parameters, psychology, foreign dispositions, dilemmas, events and
every stochastic world rule replay identically. Those are the seeds below.
"""
from __future__ import annotations

import platform
import sys

from . import causality, errors, versions
from .world import World

MANIFEST_VERSION = 1

# Each seeded stream, and what it governs. Recording the tag list matters because adding a new
# stream changes the RNG draw sequence for that tag only, and a reader needs to know which.
SEEDED_STREAMS = {
    "world": "regions, population groups, currency and the founding scenario",
    "structural_parameters": "the economy's true causal coefficients (hidden from agents)",
    "psychology": "each delegate's seeded traits, stress and coping",
    "ambitions": "each delegate's private objectives",
    "beliefs": "each delegate's prior beliefs about the world",
    "founding_dossiers": "the private evidence each delegate diagnoses from",
    "foreign_disposition": "each foreign actor's strategy, risk tolerance and constraints",
    "dilemmas": "which live value-conflicts arise and when",
    "events": "stochastic world responses (leaks, incidents, audits, media)",
    "elections": "election administration and response",
    "map": "the island's fixed geography",
}

# Settings that affect what a model returns and therefore whether a run is comparable.
SAMPLING_KEYS = ("temperature", "top_p", "effort", "max_tokens", "seed", "thinking",
                 "reasoning_effort", "framing")


def sampling(cfg: dict) -> dict:
    """Whatever sampling settings this run's seats were given."""
    run = cfg.get("run") or {}
    out = {}
    for key in SAMPLING_KEYS:
        if key in run:
            out[key] = run[key]
    for seat in cfg.get("seats") or []:
        label = seat.get("label")
        for key in ("temperature", "top_p", "effort", "thinking", "model"):
            if seat.get(key) is not None and label:
                out.setdefault("by_seat", {})[label] = out.get("by_seat", {}).get(label, {})
                out["by_seat"][label][key] = seat[key]
    return out


def seats(cfg: dict, mapping: dict | None = None) -> list:
    """The requested model for each seat, beside what actually answered when known."""
    by_label = {s.get("label"): s for s in (cfg.get("seats") or [])}
    mapping = mapping or cfg.get("mapping") or {}
    out = []
    for letter, label in sorted(mapping.items()):
        seat = by_label.get(label) or {}
        out.append({"seat": letter, "label": label, "provider": seat.get("provider"),
                    "model": seat.get("model"), "cli_command": seat.get("cli_command"),
                    "base_url": seat.get("base_url"),
                    "max_prompt_chars": seat.get("max_prompt_chars")})
    return out


def served_from_log(store) -> dict:
    """Which model actually answered each seat, read from the run's own call log.

    Taken from the log rather than from the configuration on purpose: a seat can be relabelled,
    a provider can fall back to a different model, and the label in the config is not evidence of
    what replied. `served_models[seat]` is a list because one seat can legitimately be served by
    more than one model across a long run.
    """
    out: dict[str, set] = {}
    try:
        rows = store.read_log("call")
    except Exception:
        return {}
    for row in rows:
        served = row.get("served_model") or row.get("model")
        seat = row.get("member")
        if served and seat:
            out.setdefault(seat, set()).add(served)
    return {k: sorted(v) for k, v in out.items()}


def build(world: World, cfg: dict, council_state: dict | None = None, store=None) -> dict:
    """The manifest for a run, as it stands."""
    run = cfg.get("run") or {}
    seat_rows = seats(cfg, cfg.get("mapping"))
    served = served_from_log(store) if store is not None else \
        (council_state or {}).get("served_models", {}) or {}
    return {
        "manifest_version": MANIFEST_VERSION,
        "architecture": versions.stamp(world.agent_architecture_version),
        "engine": {
            "world_engine_version": versions.WORLD_ENGINE,
            "event_generator_version": versions.EVENT_GENERATOR,
            "analytics_version": versions.ANALYTICS,
            "causality_version": 1,
            "provenance_version": 1,
            "error_taxonomy_version": 1,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "versions": {
            "agent_prompt": versions.AGENT_PROMPT,
            "psychology": versions.PSYCHOLOGY,
            "output_schema": "actions.py schemas, strict-mode compatible",
        },
        "seeds": {
            "run_seed": world.seed,
            "world_seed": world.seed,
            "months_total": world.months_total,
            "derivation": "rng_for(run_seed, month, tag) -> sha256, one stream per tag",
            "streams": SEEDED_STREAMS,
        },
        "structural_parameters": causality.ensure(world),
        "sampling": sampling(cfg),
        "seats": seat_rows,
        "served_models": {k: (sorted(v) if isinstance(v, (set, list)) else v)
                          for k, v in served.items()},
        "engine_errors": errors.summary(world),
        "founding": {"scenario": run.get("founding_scenario"),
                     "severity": run.get("founding_severity"),
                     "problems": run.get("founding_problems") or []},
        "determinism_note": (
            "The world is fully determined by run_seed: world generation, structural parameters, "
            "psychology, foreign dispositions, dilemmas and every stochastic world rule replay "
            "identically. Model outputs are not deterministic and are not claimed to be; the "
            "sampling block and served_models record what would be needed to interpret a "
            "divergence."),
    }


def divergences(a: dict, b: dict) -> list:
    """Why two runs are not comparable, as a list of human-readable differences.

    Used by the Compare view and by anyone reading a batch: the point is to name the axis that
    differs (a seat, a seed, a prompt version) rather than leaving a reader to guess whether two
    runs are a fair comparison.
    """
    out = []
    if a.get("seeds", {}).get("run_seed") != b.get("seeds", {}).get("run_seed"):
        out.append("last_run_seed")
    if a.get("versions") != b.get("versions"):
        out.append("prompt_or_schema_version")
    if a.get("architecture") != b.get("architecture"):
        out.append("agent_architecture")
    if a.get("structural_parameters") != b.get("structural_parameters"):
        out.append("structural_parameters")
    if a.get("sampling") != b.get("sampling"):
        out.append("sampling_settings")
    sa = {(s["seat"], s.get("label")) for s in a.get("seats", [])}
    sb = {(s["seat"], s.get("label")) for s in b.get("seats", [])}
    if sa != sb:
        out.append("seat_lineup")
    if a.get("founding") != b.get("founding"):
        out.append("founding_conditions")
    return out


def comparable(a: dict, b: dict) -> tuple[bool, list]:
    """Whether a comparison between two runs is like-for-like, and what differs if not."""
    return not divergences(a, b), divergences(a, b)


def error_summary(world: World) -> dict:
    """The run's structured engine errors, for the manifest and the report."""
    return errors.summary(world)
