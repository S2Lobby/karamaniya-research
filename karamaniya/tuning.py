"""Tuning parameters for the agent architecture, in one place.

Every number that shapes psychology, information, deliberation, standing or events lives
here instead of being scattered through the modules. A run can override any of them with
a [tuning] table in its council file, for example:

    [tuning]
    intelligence = { error_rate = 0.25 }
    agenda = { major_motions = 3 }

The overrides are stored in the world (World.tuning), so a resumed run keeps the values it
started with and a comparison can show which settings differed.
"""
from __future__ import annotations

import copy

DEFAULTS = {
    "psychology": {
        "trait_sd": 14.0,            # seeded spread around each baseline (spec: 10-20 points)
        "trait_min": 8.0, "trait_max": 92.0,
        "factor_loading": 0.55,      # how strongly correlated traits move together (0 = independent)
        "role_drift_per_month": 0.35,  # how far an office pulls its holder's outlook each month
        "role_drift_cap": 9.0,       # the most an office can move one trait over a run
        "stress_memory": 0.65,       # share of last month's stress carried into this month
        "principle_drift_cap": 3.0,  # largest monthly change of a commitment's internal strength
        "priority_shift": 0.06,      # how much a salient crisis raises a related priority's weight
    },
    "relationships": {
        "contested_vote_trust": 0.8, "routine_vote_trust": 0.08, "opposed_vote_resentment": 1.0,
        "criticism_resentment": 3.0, "criticism_rivalry": 2.0, "endorsement_trust": 1.5,
        "credit_theft_rivalry": 6.0, "credit_theft_resentment": 4.0,
        "resignation_demand_resentment": 8.0, "shared_intel_trust": 1.2,
        "accurate_intel_reliability": 3.0, "wrong_intel_reliability": -4.0,
        "withheld_intel_trust": -5.0, "broken_promise_trust": -8.0, "broken_promise_resentment": 5.0,
        "kept_promise_trust": 4.0, "grievance_floor": 5.0, "major_grievance_decay": 0.985,
    },
    "intelligence": {
        "error_rate": 0.18,          # chance a report is materially wrong before modifiers
        "deception_rate": 0.10,      # extra chance on Union-related subjects when propaganda is high
        "stale_rate": 0.08,
        "wrong_shift": (0.25, 0.6),  # how far a wrong report's centre moves from the truth
        "request_capacity": 3,       # requests a ministry can answer in one month
        "report_months_kept": 6,
        "contested": True,           # one subject a month read differently by two departments
        "contested_rate": 1.0,       # chance a month has such a dispute when both offices are held
        "contested_bias": (3.0, 12.0),  # how far each department's method leans, in points
        "contested_min_gap": 10.0,   # the two readings are at least this far apart
    },
    "leaks": {
        "base": 0.035, "max_per_month": 2, "rival_multiplier": 1.8, "stress_weight": 0.6,
        "press": {"free": 1.0, "restricted": 0.5, "censored": 0.2},
    },
    "agenda": {
        "major_motions": 4,          # substantive motions the council can seriously handle a month
        "emergency_extra": 1,        # extra slot during war, blockade, ultimatum or emergency rule
        "force_capital": 0.55,       # political capital needed to force a motion onto a full agenda
        "force_cost": 0.08,          # capital spent when forcing
        "carry_over_months": 1,      # a deferred motion waits this long before it lapses
    },
    "amendments": {
        "capital_cost": 0.05, "repeat_cost": 0.03, "fatigue_window": 6,
        "redundant_similarity": 0.83, "overlap_warning": 0.45,
    },
    "revision": {"mode": "auto", "max_amendments": 1},   # auto | always | off
    "standing": {
        "credit_office": 0.4, "credit_proposer": 0.3, "credit_voters": 0.1, "credit_claim": 0.2,
        "approval_memory": 0.75, "capital_regen": 0.04,
        "vote_cost_scale": 1.5,      # audience reaction to a recorded vote, relative to other acts
    },
    "media": {
        "narratives_per_month": 3,
        "reach": {"free": {"state": 0.35, "independent": 0.35, "nationalist": 0.15, "regional": 0.1, "foreign": 0.05},
                  "restricted": {"state": 0.6, "independent": 0.15, "nationalist": 0.15, "regional": 0.05, "foreign": 0.05},
                  "censored": {"state": 0.85, "independent": 0.0, "nationalist": 0.1, "regional": 0.0, "foreign": 0.05}},
    },
    "dilemmas": {"max_new_per_month": 2, "base_rate": 0.22, "max_active": 4},
    "memory": {"recent_months": 3, "retrieved_items": 4, "minor_decay": 0.88, "salience_floor": 8},
    "context": {"default_budget": 60000, "cline_margin": 700},
    "temperature": {"enabled": False, "min": 0.4, "max": 0.9},
    "bureaucracy": {"patronage_corruption": 0.04, "arrears_penalty": 0.5},
    "audits": {"months": 2,          # how long the auditors take, counting the month it is ordered
               "cooldown": 6,        # months before an office that was cleared or condemned can be audited again
               "max_open": 2,        # investigations the auditors can carry at once
               "error_rate": 0.08,   # chance a conclusive verdict is simply wrong
               "capital_cost": 0.04},  # political capital the member who calls it spends
}


def merged(overrides: dict | None) -> dict:
    """Defaults with a run's overrides applied section by section."""
    out = copy.deepcopy(DEFAULTS)
    for section, values in (overrides or {}).items():
        if section in out and isinstance(values, dict) and isinstance(out[section], dict):
            for key, value in values.items():
                if isinstance(out[section].get(key), dict) and isinstance(value, dict):
                    out[section][key] = {**out[section][key], **value}
                else:
                    out[section][key] = value
        elif section in out:
            out[section] = values
    return out


def get(w, path: str):
    """A tuning value for this world, e.g. get(w, "agenda.major_motions")."""
    section, _, key = path.partition(".")
    overrides = getattr(w, "tuning", None) or {}
    value = (overrides.get(section) or {}).get(key) if isinstance(overrides.get(section), dict) else None
    if value is None:
        value = DEFAULTS[section][key]
    elif isinstance(value, dict) and isinstance(DEFAULTS[section].get(key), dict):
        value = {**DEFAULTS[section][key], **value}
    return value


def validate(overrides) -> dict:
    """Keep only known sections and keys, so a typo in a council file is reported, not ignored."""
    if overrides in (None, ""):
        return {}
    if not isinstance(overrides, dict):
        raise ValueError("tuning must be a table of sections")
    clean = {}
    for section, values in overrides.items():
        if section not in DEFAULTS:
            raise ValueError(f"unknown tuning section '{section}' (known: {', '.join(DEFAULTS)})")
        if not isinstance(values, dict):
            raise ValueError(f"tuning section '{section}' must be a table")
        unknown = set(values) - set(DEFAULTS[section])
        if unknown:
            raise ValueError(f"unknown tuning keys in '{section}': {', '.join(sorted(unknown))}")
        clean[section] = dict(values)
    return clean
