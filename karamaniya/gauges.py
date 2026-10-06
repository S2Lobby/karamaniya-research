"""The state of the state: five slow gauges the whole world can read.

Most modules already compute their own numbers from policy and events. What was missing was one
place that answers the question a citizen, a creditor and a foreign cabinet all actually ask:
*how is this country holding together?* These gauges are deliberately slow - they are stocks, not
flows - so a single good or bad month moves them only a little, while a run of them changes what
everyone else does.

They are read, never written, by the rest of the engine: policy, economy, society, standing and
the foreign cabinets all condition on them, so the same country looks attractive or fragile to
everyone at once. Determinism is preserved because every input is already seeded.
"""
from __future__ import annotations

from .world import World, clamp

GAUGE_NAMES = {
    "state_capacity": "state capacity",
    "public_trust": "public trust in government",
    "institutional_integrity": "institutional integrity",
    "social_cohesion": "social cohesion",
    "war_weariness": "public war weariness",
}


def _memory(w: World) -> dict:
    return w.institutions.setdefault("state_gauges", {})


def _previous(w: World) -> dict:
    return _memory(w).get("current") or {}


def compute(w: World) -> dict:
    """This month's reading of the five gauges, before smoothing."""
    e, m, c, dip = w.econ, w.mil, w.const, w.dip
    pops = w.k_pops()
    total = sum(p.size for p in pops) or 1.0
    cap = (w.institutions.get("capacity") or {})
    corruption = (w.institutions.get("corruption") or {})
    mean_cap = sum(cap.values()) / len(cap) if cap else 0.6
    mean_corr = sum(corruption.values()) / len(corruption) if corruption else 0.1

    state_capacity = clamp(0.6 * mean_cap + 0.25 * e.admin_capacity + 0.15 * e.compliance)

    avg_approval = sum(p.approval * p.size for p in pops) / total
    unrest = sum(p.unrest * p.size for p in pops) / total
    fear = sum(p.fear * p.size for p in pops) / total
    scandal = 0.12 if w.month - e.scandal_month < 6 else 0.0
    public_trust = clamp(0.7 * avg_approval + 0.3 * (1 - unrest) - 0.5 * fear - scandal)

    honesty = 0.0 if w.policy.stats == "honest" else -0.12
    legality = -0.12 if c.emergency else 0.0
    legality -= 0.15 if w.month - c.coup_month < 12 else 0.0
    elections = 0.0
    if c.elections:
        last = c.elections[-1]
        if last.get("rigged"):
            elections = -0.2
        elif (last.get("fairness") or {}).get("unfair"):
            elections = -0.08
        else:
            elections = 0.08
    institutional_integrity = clamp(0.55 * mean_cap + 0.45 * (1 - min(1.0, mean_corr * 2.2))
                                    + honesty + legality + elections)

    ident = {}
    for name in ("karamanian", "imperial", "vell"):
        group = [p for p in pops if p.ident == name]
        ident[name] = (sum(p.size for p in group) / total) if group else 0.0
    minority_opp = {"equal": 0.0, "restricted": 0.25, "interned": 0.5}[c.minority]
    grievance = sum(p.grievance * p.size for p in pops) / total
    cohesion = clamp(0.85 - 0.55 * grievance - 0.35 * minority_opp - 0.25 * unrest)
    if min(ident.values()) > 0.05 and public_trust < 0.45:
        cohesion -= 0.05

    killed = w.counters.get("soldiers_killed", 0.0)
    weariness = clamp(0.85 * dip.union_weariness + 0.15 * min(1.0, killed / 20000))
    if dip.war and w.mil.last_combat:
        losing = sum(1 for k, v in w.mil.last_combat.items()
                     if isinstance(v, dict) and v.get("k_loss", 0) > v.get("u_loss", 0))
        weariness = clamp(weariness + 0.06 * losing)

    return {"state_capacity": round(state_capacity, 4),
            "public_trust": round(public_trust, 4),
            "institutional_integrity": round(institutional_integrity, 4),
            "social_cohesion": round(cohesion, 4),
            "war_weariness": round(weariness, 4)}


def update(w: World) -> dict:
    """Smooth this month's reading into the gauges the rest of the engine reads."""
    fresh = compute(w)
    memory = _memory(w)
    previous = _previous(w)
    current = {}
    for key, value in fresh.items():
        was = previous.get(key, value)
        current[key] = round(clamp(was + 0.25 * (value - was)), 4)
    history = memory.setdefault("history", [])
    history.append({"month": w.month, **current})
    memory["history"] = history[-120:]
    memory["current"] = current
    return current


def get(w: World, gauge: str, default: float = 0.5) -> float:
    """Read one gauge. A run that predates the gauges reports the neutral default."""
    return float(_previous(w).get(gauge, default))


def trend(w: World, gauge: str, months: int = 3) -> float:
    """How much the gauge moved over the last few months, for prose that says 'slipping'."""
    history = _memory(w).get("history") or []
    if len(history) < 2:
        return 0.0
    window = history[-min(months, len(history)):]
    return round(window[-1].get(gauge, 0.5) - window[0].get(gauge, 0.5), 4)


def text(w: World) -> str:
    """A plain-language reading, for briefings and for the analyst report."""
    current = _previous(w)
    if not current:
        return ""
    band = lambda v: "high" if v >= 0.66 else "weak" if v <= 0.38 else "middling"
    lines = []
    for key, name in GAUGE_NAMES.items():
        value = current.get(key)
        if value is None:
            continue
        move = trend(w, key)
        direction = " (improving)" if move > 0.03 else " (slipping)" if move < -0.03 else ""
        lines.append(f"- {name}: {band(value)}{direction}")
    return "STATE OF THE COUNTRY (how the country is holding together)\n" + "\n".join(lines)

