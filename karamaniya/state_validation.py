"""Non-fatal integrity checks for canonical simulation state and recorded snapshots."""
from __future__ import annotations

import math

from .world import OFFICES, World

VERSION = 1
FATALITY_COUNTERS = ("deaths_famine", "deaths_state_violence", "deaths_war_civilian",
                     "deaths_internment", "deaths_coups", "deaths_natural", "soldiers_killed")


def validate(w: World, snapshot: dict | None = None) -> list[dict]:
    issues = []

    def issue(code: str, detail: str) -> None:
        issues.append({"code": code, "month": w.month, "detail": detail})

    ids = {m.id for m in w.members}
    for office in OFFICES:
        holder = w.const.offices.get(office)
        if holder is not None and (holder not in ids or w.member(holder).status != "active"):
            issue("officeholder_invalid", f"{office} points to missing or inactive member {holder}.")
    currency_memberships = [z.id for z in w.zones if "karamaniya" in z.members]
    if len(currency_memberships) != 1:
        issue("currency_membership", f"Karamaniya belongs to {len(currency_memberships)} currency zones.")
    if w.econ.currency == "karam" and any(z.id == "crown" and "karamaniya" in z.members for z in w.zones):
        issue("currency_duplicate", "Karamaniya uses the karam but remains in the crown currency area.")
    for name, value in (("army", w.mil.army.size), ("navy", w.mil.navy.size), ("police", w.mil.police.size),
                        ("debt_dom", w.econ.debt_dom), ("debt_for", w.econ.debt_for),
                        ("reserves", w.econ.gold), ("arrears", w.econ.arrears)):
        if not math.isfinite(float(value)) or value < 0:
            issue("invalid_numeric_state", f"{name} is not a finite non-negative value ({value}).")
    for region in w.regions:
        if region.nation == "karamaniya" and region.controller not in ("karamaniya", "union", "rebels"):
            issue("region_controller", f"{region.id} has unknown controller {region.controller!r}.")
    election = w.const.election_month
    if election < -1:
        issue("election_timing", f"Election month has invalid value {election}.")
    # Reconcile every tracked casualty counter against structured events generated at
    # the exact point of increment. Natural deaths and military deaths stay distinct.
    previous = w.history[-2].get("counters", {}) if len(w.history) > 1 else {}
    observed = {key: 0.0 for key in FATALITY_COUNTERS}
    for event in w.events:
        if event.get("kind") == "fatality_counter" and event.get("counter") in observed:
            observed[event["counter"]] += float(event.get("amount", 0.0))
    for key in FATALITY_COUNTERS:
        delta = float(w.counters.get(key, 0.0)) - float(previous.get(key, 0.0))
        if not math.isclose(delta, observed[key], rel_tol=1e-8, abs_tol=1):
            issue("fatality_counter_mismatch",
                  f"{key} changed by {delta}, but structured monthly fatality events total {observed[key]}.")
    if snapshot:
        hard = snapshot.get("hard_state", {})
        canonical = {
            "currency": w.econ.currency, "currency_launch": w.econ.currency_launch,
            "war": w.dip.war, "ceasefire": w.dip.ceasefire, "blockade": w.dip.blockade,
            "union_formed": w.dip.union_formed, "federation": w.dip.federation,
            "league_alliance": w.dip.league_alliance, "league_sanctions": w.dip.league_sanctions,
            "offices": dict(w.const.offices), "directives": dict(w.const.directives),
            "election_month": w.const.election_month,
            "army": w.mil.army.size, "navy": w.mil.navy.size, "police": w.mil.police.size,
            "debt_dom": w.econ.debt_dom, "debt_for": w.econ.debt_for, "reserves": w.econ.gold,
            "arrears": w.econ.arrears,
            "regions": {r.id: r.controller for r in w.regions if r.nation == "karamaniya"},
        }
        for name, actual in canonical.items():
            recorded = hard.get(name)
            if recorded is None:
                continue
            if isinstance(actual, float):
                equal = math.isclose(float(recorded), actual, rel_tol=1e-8, abs_tol=1)
            else:
                equal = actual == recorded
            if not equal:
                issue("hard_state_mismatch", f"Recorded {name} differs from canonical current state.")
        facts = (
            ("currency", w.econ.currency, snapshot.get("currency")),
            ("war", w.dip.war, snapshot.get("war")),
        )
        for name, actual, recorded in facts:
            if recorded is not None and actual != recorded:
                issue("snapshot_mismatch", f"Recorded {name}={recorded!r} differs from canonical {actual!r}.")
        recorded_offices = snapshot.get("offices")
        if recorded_offices is not None and recorded_offices != w.const.offices:
            issue("snapshot_mismatch", "Recorded officeholders differ from canonical officeholders.")
        recorded_election = snapshot.get("constitution", {}).get("election_month")
        if recorded_election is not None and recorded_election != election:
            issue("snapshot_mismatch", f"Recorded election month {recorded_election} differs from canonical {election}.")
        for current_key, historical_key in (("army", "army"), ("navy", "navy"), ("police", "police")):
            recorded = snapshot.get(historical_key)
            current = getattr(w.mil, current_key).size if current_key != "police" else w.mil.police.size
            if recorded is not None and not math.isclose(float(recorded), float(current), rel_tol=1e-8, abs_tol=1):
                issue("snapshot_mismatch", f"Recorded {current_key} size {recorded} differs from canonical {current}.")
        counters = snapshot.get("counters", {})
        for key, value in w.counters.items():
            if key in counters and not math.isclose(float(value), float(counters[key]), rel_tol=1e-9, abs_tol=1):
                issue("snapshot_mismatch", f"Cumulative counter {key} differs from the recorded snapshot.")
    return issues


def refresh(w: World, snapshot: dict | None = None) -> dict:
    issues = validate(w, snapshot)
    w.integrity = {"version": VERSION, "status": "clean" if not issues else "warnings",
                   "checked_month": w.month, "warnings": issues}
    if snapshot is not None:
        snapshot["integrity"] = w.integrity
    return w.integrity
