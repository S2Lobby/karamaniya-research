"""Civil-war combat and territory (Wave C, workstream C2).

`combat(w, rng=None)` fights one month of a civil war. It is a force-ratio model shaped like
`military._combat`: quality from equipment, training and morale, supply from arrears, terrain and
fortification for the defender, a defender bonus, losses proportional to the engaged force and
the ratio, civilian deaths, damage, and a region that changes hands when one side wins its front.

INTERFACE
---------
C1 owns `w.civil_war`. C3 fills `orders`; C4 owns negotiation and the ends; C5 reads
`w.civil_war["last_combat"]` and the month record. The canonical state this module reads is:

    w.civil_war = {
        "since": int, "cause": str,
        "factions": {
            "government": {"members": [member ids], "territory": [region ids]},
            "rebels":     {"members": [member ids], "territory": [region ids]},
        },
        "forces": {                        # share of each armed service on each side
            "army":     {"government": float, "rebels": float, "neutral": float},
            "navy":     {"government": float, "rebels": float, "neutral": float},
            "interior": {"government": float, "rebels": float, "neutral": float},
        },
        "contested": [region ids],         # the fronts fought over this month
        "ceasefire": None | {"active": bool, "broken": bool},
        "intensity": float,                # optional, 1.0 normal, 0..2
        "orders": {                        # optional, filled by C3's faction phase
            "government": {region id or front: "attack" | "defend" | "withdraw"},
            "rebels":     {region id or front: "attack" | "defend" | "withdraw"},
        },
        "progress": {region id: float},    # written here; a front falls at 1.0
        "last_combat": {...},              # written here every month
    }

Tolerance: `forces` may be absent (it is rebuilt from `military.anticipated_response`); a
numeric per-office entry is read as the rebel share. `contested` is processed in sorted region-id
order so a set never makes a run depend on Python's hash seed. A region changes hands only when
its side is the current controller: `"rebels"` for the rebels and `"karamaniya"` for the
government, as C1 designed; `"union"` or anything else is left alone.

The caller runs `combat` once a month after the council and faction phases (the lead picks the
call site). It draws only from `rng_for(seed, month, "civil_war_combat")`, so the month's other
streams are unchanged. It returns the battle record and also stores it in
`w.civil_war["last_combat"]`. With no civil war (`None` or `{}`) it returns `None` and touches
nothing.

CONSTANTS (the scales approved on 2026-10-17, `notes/open-actions-decisions.md`)
-------------------------------------------------------------------------------
SOLDIER_LOSS_MIN/MAX 1.5-2.5% of the engaged force a month: the per-front coefficient is drawn
    in this band and scaled by (enemy/own strength)^0.5, exactly as the Union model's 0.015 and
    0.02 coefficients, so at parity the loss is in the agreed band and a side that is losing
    badly loses more.
CIVILIAN_DEATH_RATE 0.03% of a contested region's population a month, the Union model's 0.0003.
DAMAGE_MIN/MAX +0.02 to +0.04 a month per fighting front at normal intensity.
REFUGEE_MIN/MAX 10-15% of every population group in a region that falls.
DEFECTION_CAP 5 percentage points of a service's allegiance a month: the design asks for a cap;
    this one lets a force cross to the other side in about a year, and the scripted sweep can
    calibrate it.
POLICE_EQUIV 0.35 and NAVY_EQUIV 900 convert police and ships to soldier-equivalents, matching
    `military._force_power`, so the services count in the ratio at the weight politics.py already
    gives them.
RATIO_CAP 4.0 bounds the loss scaling, as `_combat` does. PROGRESS_* are `_combat`'s ground model:
    0.15 x (ratio - ADVANCE_AT) a month at full intensity, erosion of 0.05 when stalled.
"""
from __future__ import annotations

import copy
import math

from . import military
from .world import Pop, World, clamp, rng_for

OFFICES = ("army", "navy", "interior")
EQUIVALENT = {"army": 1.0, "navy": 900.0, "interior": 0.35}   # soldiers per ship / per police officer

SOLDIER_LOSS_MIN = 0.015
SOLDIER_LOSS_MAX = 0.025
CIVILIAN_DEATH_RATE = 0.0003
DAMAGE_MIN = 0.02
DAMAGE_MAX = 0.04
REFUGEE_MIN = 0.10
REFUGEE_MAX = 0.15
DEFECTION_CAP = 0.05
RATIO_CAP = 4.0
PROGRESS_RATIO_CAP = 6.0
PROGRESS_RATE = 0.15
PROGRESS_DECAY = 0.05
MAX_FRONT_LOSS_SHARE = 0.4
DEFAULT_INTENSITY = 1.0
INTENSITY_RANGE = (0.0, 2.0)


def intensity_of(state: dict) -> float:
    """The war's monthly intensity, clamped; a malformed value reads as a normal month."""
    try:
        return clamp(float(state.get("intensity", DEFAULT_INTENSITY)), *INTENSITY_RANGE)
    except (TypeError, ValueError):
        return DEFAULT_INTENSITY


def ceasefire_active(state: dict) -> bool:
    """Whether a ceasefire holds. A dict may name `active` and `broken`; a bare truthy value holds."""
    ceasefire = state.get("ceasefire")
    if not ceasefire:
        return False
    if isinstance(ceasefire, dict):
        return bool(ceasefire.get("active", True)) and not bool(ceasefire.get("broken", False))
    return bool(ceasefire)


def combat(w: World, rng=None) -> dict | None:
    """Fight the month's civil-war fronts and return the battle record (see the module docstring).

    `rng` is for tests and dry runs. The engine passes nothing, and the draw comes from
    `rng_for(w.seed, w.month, "civil_war_combat")`.
    """
    state = getattr(w, "civil_war", None)
    if not isinstance(state, dict) or not state:
        return None
    if state.get("outcome") or getattr(w, "outcome", None):
        return None
    if rng is None:
        rng = rng_for(w.seed, w.month, "civil_war_combat")

    record = {
        "month": w.month,
        "fronts": {},
        "losses": {"government": 0.0, "rebels": 0.0, "civilians": 0.0},
        "losses_equivalent": {"government": 0.0, "rebels": 0.0},
        "losses_by_office": {office: {"government": 0.0, "rebels": 0.0} for office in OFFICES},
        "control_changes": [],
        "refugees": 0.0,
        "defections": {},
        "ceasefire": False,
        "intensity": intensity_of(state),
    }
    if ceasefire_active(state):
        record["ceasefire"] = True
        state["last_combat"] = record
        return record

    record["defections"] = _defections(w, state)
    intensity = record["intensity"]
    if intensity <= 0.0:
        # A paused war (intensity 0) still lets allegiance drift; it fights nothing.
        state["last_combat"] = record
        return record
    contested = sorted({str(rid) for rid in (state.get("contested") or [])})
    n_fronts = max(1, len(contested))
    men_lost = {office: {"government": 0.0, "rebels": 0.0} for office in OFFICES}
    loss_equivalent = {"government": 0.0, "rebels": 0.0}
    fought = False

    for rid in contested:
        try:
            region = w.region(rid)
        except KeyError:
            continue
        if region.nation != "karamaniya":
            continue
        holder = _holder_side(region)
        if holder is None:
            continue
        attacker = "rebels" if holder == "government" else "government"
        attacker_order = _order(state, attacker, region)
        defender_order = _order(state, holder, region)

        if defender_order == "withdraw":
            _change_control(w, state, region, attacker, record, rng, routed=True, fought=False)
            record["fronts"][rid] = _front_record(region, attacker, holder, 0.0, {}, {}, 0.0, 0.0,
                                                  {}, {}, 0.0, 0.0, _progress_of(state, rid),
                                                  "defender withdrew")
            continue
        if attacker_order in ("defend", "withdraw"):
            record["fronts"][rid] = _front_record(region, attacker, holder, 0.0, {}, {}, 0.0, 0.0,
                                                  {}, {}, 0.0, 0.0, _decay_progress(state, rid, intensity),
                                                  "attacker held")
            continue

        attacking = _profile(w, state, attacker, n_fronts, region)
        defending = _profile(w, state, holder, n_fronts, region)
        attack_eq = _engaged_equivalent(attacking)
        defend_eq = _engaged_equivalent(defending)
        if attack_eq <= 0.0:
            record["fronts"][rid] = _front_record(region, attacker, holder, 0.0, attacking, defending,
                                                  0.0, 0.0, {}, {}, 0.0, 0.0,
                                                  _decay_progress(state, rid, intensity),
                                                  "no attacking force")
            continue
        if defend_eq <= 0.0:
            _change_control(w, state, region, attacker, record, rng, routed=True, fought=False)
            record["fronts"][rid] = _front_record(region, attacker, holder, 0.0, attacking, defending,
                                                  0.0, 0.0, {}, {}, 0.0, 0.0,
                                                  _progress_of(state, rid), "undefended")
            continue

        attack_strength = _strength(attacking)
        defend_strength = _strength(defending) * max(0.1, region.terrain) * (1.0 + _fort(w, state, region))
        ratio = attack_strength / max(1e-9, defend_strength * military.DEFENDER_BONUS)
        if not math.isfinite(ratio) or ratio <= 0.0:
            ratio = 1e-6

        # The coefficient is the approved band; ratio^0.5 decides how much of it each side pays,
        # as in _combat. A 40% cap on a single front stops one month annihilating a force.
        attack_coefficient = rng.uniform(SOLDIER_LOSS_MIN, SOLDIER_LOSS_MAX)
        defend_coefficient = rng.uniform(SOLDIER_LOSS_MIN, SOLDIER_LOSS_MAX)
        attack_loss_eq = min(
            MAX_FRONT_LOSS_SHARE * attack_eq,
            attack_eq * attack_coefficient * min(RATIO_CAP, 1.0 / ratio) ** 0.5 * intensity)
        defend_loss_eq = min(
            MAX_FRONT_LOSS_SHARE * defend_eq,
            defend_eq * defend_coefficient * min(RATIO_CAP, ratio) ** 0.5 * intensity)
        attack_men = _loss_men(attacking, attack_loss_eq)
        defend_men = _loss_men(defending, defend_loss_eq)
        for office, men in attack_men.items():
            men_lost[office][attacker] += men
        for office, men in defend_men.items():
            men_lost[office][holder] += men
        loss_equivalent[attacker] += attack_loss_eq
        loss_equivalent[holder] += defend_loss_eq
        fought = True

        population = sum(p.size for p in w.pops if p.region == rid)
        civilian_deaths = CIVILIAN_DEATH_RATE * population * intensity
        _kill_civilians(w, rid, civilian_deaths)
        damage = rng.uniform(DAMAGE_MIN, DAMAGE_MAX) * intensity
        region.damage = clamp(region.damage + damage)

        progress = _progress_of(state, rid)
        if ratio > military.ADVANCE_AT:
            progress += PROGRESS_RATE * (min(PROGRESS_RATIO_CAP, ratio) - military.ADVANCE_AT) * intensity
        else:
            progress = max(0.0, progress - PROGRESS_DECAY * intensity)
        state.setdefault("progress", {})[rid] = progress
        fell = progress >= 1.0
        record["fronts"][rid] = _front_record(
            region, attacker, holder, ratio, attacking, defending, attack_loss_eq, defend_loss_eq,
            attack_men, defend_men, civilian_deaths, damage, progress,
            "front won" if fell else ("advancing" if ratio > military.ADVANCE_AT else "stalled"))
        if fell:
            _change_control(w, state, region, attacker, record, rng, routed=False, fought=True,
                            rebel_men=_engaged_men(attacking) if attacker == "rebels"
                            else _engaged_men(defending))

    _apply_losses(w, state, men_lost)
    _sync_territory(w, state)

    record["losses"]["government"] = sum(men_lost[o]["government"] for o in OFFICES)
    record["losses"]["rebels"] = sum(men_lost[o]["rebels"] for o in OFFICES)
    record["losses_by_office"] = {office: {"government": round(men_lost[office]["government"], 3),
                                           "rebels": round(men_lost[office]["rebels"], 3)}
                                  for office in OFFICES}
    record["losses_equivalent"] = {k: round(v, 3) for k, v in loss_equivalent.items()}
    civilians = sum(f["civilian_deaths"] for f in record["fronts"].values())
    record["losses"]["civilians"] = civilians
    if fought:
        names = ", ".join(w.region(rid).name for rid in record["fronts"]
                          if record["fronts"][rid]["ratio"] > 0.0)
        total_men = record["losses"]["government"] + record["losses"]["rebels"]
        w.event("civil_war_combat",
                f"Civil war: fighting in {names}. About {total_men * 0.3:,.0f} soldiers and "
                f"{civilians:,.0f} civilians killed this month.",
                importance=2, detail=copy.deepcopy(record))
    state["last_combat"] = record
    return record


# ---- the battle shape -------------------------------------------------------------------------

def _force(w: World, office: str):
    return {"army": w.mil.army, "navy": w.mil.navy, "interior": w.mil.police}.get(office)


def _holder_side(region) -> str | None:
    if region.controller == "rebels":
        return "rebels"
    if region.controller == "karamaniya":
        return "government"
    return None


def _order(state: dict, side: str, region) -> str | None:
    orders = state.get("orders")
    if not isinstance(orders, dict):
        return None
    entry = orders.get(side)
    if not isinstance(entry, dict):
        return None
    for key in (region.id, region.front):
        if key and key in entry:
            return str(entry[key]).strip().lower()
    return None


def _fort(w: World, state: dict, region) -> float:
    """The front's fortification, from the war state first and the General Staff's works second."""
    fort = state.get("fort")
    if isinstance(fort, dict):
        try:
            return max(0.0, float(fort.get(region.id, 0.0) or 0.0))
        except (TypeError, ValueError):
            pass
    try:
        forts = getattr(w.mil, "fort", None) or {}
        return max(0.0, float(forts.get(region.front, 0.0))) if region.front else 0.0
    except (TypeError, ValueError):
        return 0.0


def _supply(force) -> float:
    """The Union model's supply term: unpaid soldiers fight worse."""
    return clamp(1 - 0.15 * min(3.0, force.arrears), 0.5, 1.0)


def _profile(w: World, state: dict, side: str, n_fronts: int, region) -> dict:
    """The men and quality this side commits to one front.

    A side's share of each service is spread equally over the contested regions. Navies count
    only on a coast; police and ships are converted to soldier-equivalents so the ratio compares
    like with like.
    """
    shares = _shares(state, w)
    profile = {}
    for office in OFFICES:
        force = _force(w, office)
        if force is None:
            continue
        if office == "navy" and not region.coast:
            continue
        share = shares.get(office, {}).get(side, 0.0)
        if share <= 0.0:
            continue
        men = force.size * share / max(1, n_fronts)
        if men <= 0.0:
            continue
        profile[office] = {"men": men, "equivalent": men * EQUIVALENT[office],
                           "quality": military.quality(force.equipment, force.training, force.morale),
                           "supply": _supply(force)}
    return profile


def _strength(profile: dict) -> float:
    return sum(p["men"] * p["quality"] * p["supply"] for p in profile.values())


def _engaged_equivalent(profile: dict) -> float:
    return sum(p["equivalent"] for p in profile.values())


def _engaged_men(profile: dict) -> float:
    return sum(p["men"] for p in profile.values())


def _loss_men(profile: dict, loss_equivalent: float) -> dict:
    """Split an equivalent-strength loss across the services that fought, in actual men."""
    total = _engaged_equivalent(profile)
    if total <= 0.0 or loss_equivalent <= 0.0:
        return {}
    return {office: loss_equivalent * p["equivalent"] / total / EQUIVALENT[office]
            for office, p in profile.items()}


def _progress_of(state: dict, rid: str) -> float:
    try:
        return max(0.0, float((state.get("progress") or {}).get(rid, 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _decay_progress(state: dict, rid: str, intensity: float) -> float:
    progress = max(0.0, _progress_of(state, rid) - PROGRESS_DECAY * intensity)
    state.setdefault("progress", {})[rid] = progress
    return progress


def _front_record(region, attacker, defender, ratio, attacking, defending,
                  attack_loss_eq, defend_loss_eq, attack_men, defend_men,
                  civilian_deaths, damage, progress, note) -> dict:
    """One front's month, with every figure attributed to a side, not to an attacker/defender role."""
    government_profile = attacking if attacker == "government" else defending
    rebel_profile = defending if attacker == "government" else attacking
    government_loss_eq = attack_loss_eq if attacker == "government" else defend_loss_eq
    rebel_loss_eq = defend_loss_eq if attacker == "government" else attack_loss_eq
    government_men = attack_men if attacker == "government" else defend_men
    rebel_men = defend_men if attacker == "government" else attack_men
    return {
        "region": region.id,
        "front": region.front,
        "attacker": attacker,
        "defender": defender,
        "ratio": round(ratio, 3),
        "engaged_equivalent": {"government": round(_engaged_equivalent(government_profile), 1),
                               "rebels": round(_engaged_equivalent(rebel_profile), 1)},
        "engaged_men": {"government": round(_engaged_men(government_profile), 1),
                        "rebels": round(_engaged_men(rebel_profile), 1)},
        "losses_equivalent": {"government": round(government_loss_eq, 3),
                              "rebels": round(rebel_loss_eq, 3)},
        "losses_men": {"government": round(sum(government_men.values()), 1),
                       "rebels": round(sum(rebel_men.values()), 1)},
        "civilian_deaths": round(civilian_deaths, 1),
        "damage": round(damage, 4),
        "progress": round(progress, 3),
        "note": note,
    }


# ---- forces, defection and control -------------------------------------------------------------

def _member_ids(entry) -> set:
    """Member ids from `{"members": [...]}` or from a bare list; dicts may carry `id`."""
    if isinstance(entry, dict):
        members = entry.get("members") or []
    elif isinstance(entry, (list, tuple, set)):
        members = entry
    else:
        return set()
    ids = set()
    for member in members:
        if isinstance(member, dict):
            if member.get("id") is not None:
                ids.add(str(member["id"]))
        else:
            ids.add(str(member))
    return ids


def _normalise_entry(entry: dict) -> dict:
    out = {}
    for key in ("government", "rebels", "neutral"):
        try:
            out[key] = max(0.0, float(entry.get(key, 0.0) or 0.0))
        except (TypeError, ValueError):
            out[key] = 0.0
    total = sum(out.values())
    if total <= 1e-9:
        return {"government": 1.0, "rebels": 0.0, "neutral": 0.0}
    return {key: value / total for key, value in out.items()}


def _shares(state: dict, w: World) -> dict:
    """The per-service allegiance shares, rebuilt from the engine when C1's block is absent."""
    forces = state.get("forces")
    usable = isinstance(forces, dict) and any(
        isinstance(forces.get(office), (dict, int, float)) for office in OFFICES)
    if not usable:
        rebuilt = _build_shares(w, state)
        if rebuilt is not None:
            forces = rebuilt
        else:
            forces = {office: {"government": 1.0, "rebels": 0.0, "neutral": 0.0} for office in OFFICES}
        state["forces"] = forces
    for office in OFFICES:
        entry = forces.get(office)
        if isinstance(entry, dict):
            forces[office] = _normalise_entry(entry)
        elif isinstance(entry, (int, float)):
            rebel = clamp(float(entry))
            forces[office] = {"government": 1.0 - rebel, "rebels": rebel, "neutral": 0.0}
        else:
            forces[office] = {"government": 1.0, "rebels": 0.0, "neutral": 0.0}
    return forces


def _build_shares(w: World, state: dict) -> dict | None:
    """C1's starting shares, in the engine's own terms, when the state does not carry them."""
    factions = state.get("factions")
    if not isinstance(factions, dict):
        return None
    rebel_ids = _member_ids(factions.get("rebels") or {})
    forces = {}
    for office in OFFICES:
        holder = w.const.offices.get(office)
        holder_side = "rebels" if holder in rebel_ids else "government"
        response = military.anticipated_response(w, {"office": office})
        government = (response["obey_government"] + 0.5 * response["split"]
                      + (response["obey_commander"] if holder_side == "government" else 0.0))
        rebels = 0.5 * response["split"] + (response["obey_commander"] if holder_side == "rebels" else 0.0)
        total = government + rebels + response["neutral"]
        if total <= 0.0:
            government, rebels = 1.0, 0.0
        forces[office] = _normalise_entry({"government": government, "rebels": rebels,
                                           "neutral": response["neutral"]})
    return forces


def _defections(w: World, state: dict) -> dict:
    """Move each service's allegiance toward what `anticipated_response` now says, capped monthly.

    The office holder's side gets the units that obey the commander; the government gets the units
    that obey the state; a split force goes half to each. The design asks for a monthly cap, so no
    single month can hand a service to the other side.
    """
    forces = _shares(state, w)
    factions = state.get("factions")
    if not isinstance(factions, dict):
        return {}
    rebel_ids = _member_ids(factions.get("rebels") or {}) if isinstance(factions, dict) else set()
    out = {}
    for office in OFFICES:
        entry = forces.get(office)
        if not isinstance(entry, dict):
            continue
        holder = w.const.offices.get(office)
        holder_side = "rebels" if holder in rebel_ids else "government"
        response = military.anticipated_response(w, {"office": office})
        # `obey_commander` is the share obeying the office holder. The design's phrase "the
        # government share is obey_government + 0.5*split when the holder is not a rebel" omits it;
        # those units are obeying the government's own commander, so they stay with the government
        # rather than vanishing from its order of battle.
        target = {
            "government": (response["obey_government"] + 0.5 * response["split"]
                           + (response["obey_commander"] if holder_side == "government" else 0.0)),
            "rebels": (0.5 * response["split"]
                       + (response["obey_commander"] if holder_side == "rebels" else 0.0)),
        }
        before = {key: round(entry.get(key, 0.0), 6) for key in ("government", "rebels", "neutral")}
        for side in ("government", "rebels"):
            delta = clamp(target[side] - entry.get(side, 0.0), -DEFECTION_CAP, DEFECTION_CAP)
            entry[side] = max(0.0, entry.get(side, 0.0) + delta)
        entry["neutral"] = max(0.0, 1.0 - entry["government"] - entry["rebels"])
        total = sum(entry.values())
        if total > 0.0:
            for key in entry:
                entry[key] = max(0.0, entry[key] / total)
        out[office] = {"before": before,
                       "after": {key: round(entry.get(key, 0.0), 6)
                                 for key in ("government", "rebels", "neutral")},
                       "target": {key: round(value, 6) for key, value in target.items()}}
    return out


def _apply_losses(w: World, state: dict, men_lost: dict) -> None:
    """Take the month's dead and wounded out of the forces and the population."""
    forces = _shares(state, w)
    for office in OFFICES:
        force = _force(w, office)
        if force is None:
            continue
        government = max(0.0, men_lost[office]["government"])
        rebels = max(0.0, men_lost[office]["rebels"])
        total = government + rebels
        if total <= 0.0:
            continue
        size_before = max(0.0, force.size)
        if size_before <= 0.0:
            continue
        total = min(total, size_before)
        fraction = total / size_before
        shares = forces.setdefault(office, {"government": 1.0, "rebels": 0.0, "neutral": 0.0})
        for side, lost in (("government", government), ("rebels", rebels)):
            shares[side] = max(0.0, shares.get(side, 0.0) - lost / size_before)
        # Renormalise to the surviving force: the dead leave a gap in the old shares, and the
        # living are redistributed over what remains. This keeps the side that did not fight at
        # its old absolute strength and removes exactly the dead from the other.
        denominator = max(1e-9, 1.0 - fraction)
        for key in ("government", "rebels", "neutral"):
            shares[key] = max(0.0, shares.get(key, 0.0) / denominator)
        share_total = sum(shares.values())
        if share_total > 0.0:
            for key in shares:
                shares[key] /= share_total
        force.size = max(0.0, size_before - total)
        killed = total * 0.3       # the Union model's 30% killed, 70% wounded or released
        if office == "army":
            w.mil.killed += killed
            w.count("soldiers_killed", killed)
            w.count("civil_war_soldiers_killed", killed)
            w.count("civil_war_government_killed", government * 0.3)
            w.count("civil_war_rebel_killed", rebels * 0.3)
            # The existing casualty path removes the dead and the released from the population
            # and from any embodied reserve, exactly as _combat does for active losses.
            military._release(w, government * 0.3 + rebels * 0.3, killed=True)
            military._release(w, government * 0.7 + rebels * 0.7, killed=False)
        else:
            w.count("civil_war_security_killed", killed)


def _change_control(w: World, state: dict, region, winner: str, record: dict, rng,
                    routed: bool, fought: bool, rebel_men: float | None = None) -> float:
    """The region changes hands; the other side's people flee, and the territory lists move."""
    previous = region.controller
    if winner == "rebels":
        military.occupy(w, region.id, "rebels")
        region.rebels = max(region.rebels, float(rebel_men or 500.0))
    else:
        region.controller = "karamaniya"
        region.rebels = 0.0
        w.event("civil_war_recapture", f"Government forces have retaken {region.name}.",
                importance=3, region=region.id)
    moved = _flee(w, region, winner, rng)
    state.setdefault("progress", {}).pop(region.id, None)
    state["contested"] = [rid for rid in (state.get("contested") or []) if rid != region.id]
    record["control_changes"].append({"region": region.id, "from": previous, "to": region.controller,
                                      "routed": bool(routed), "fought": bool(fought),
                                      "refugees": round(moved)})
    record["refugees"] += moved
    return moved


def _flee(w: World, region, winner: str, rng) -> float:
    """10-15% of a fallen region's people flee to the other side's remaining territory.

    This is the faction version of `military.occupy`'s flee path, which only runs when the Union
    takes a region. The destination is one safe region, chosen by damage (the capital preferred on
    a tie) and then by id so a run does not depend on list order.
    """
    destination_side = "karamaniya" if winner == "rebels" else "rebels"
    safe = [x for x in w.regions if x.nation == "karamaniya" and x.id != region.id
            and x.controller == destination_side]
    if not safe:
        # The other side holds nothing left: people are displaced inside the winner's territory.
        safe = [x for x in w.regions if x.nation == "karamaniya" and x.id != region.id]
    if not safe:
        return 0.0
    destination = min(safe, key=lambda x: (x.damage + (0.0 if x.capital else 0.1), x.id))
    fraction = rng.uniform(REFUGEE_MIN, REFUGEE_MAX)
    moved = 0.0
    for pop in [p for p in w.pops if p.region == region.id]:
        flee = pop.size * fraction
        if flee < 1.0:
            continue
        pop.size = max(0.0, pop.size - flee)
        target = next((q for q in w.pops if q.region == destination.id and q.cls == pop.cls
                       and q.ident == pop.ident), None)
        if target is None:
            target = Pop(region=destination.id, cls=pop.cls, ident=pop.ident, size=0.0,
                         approval=pop.approval, indep=pop.indep)
            w.pops.append(target)
        _merge(target, pop, flee)
        moved += flee
    if moved > 0.0:
        w.count("refugees", moved)
        w.count("civil_war_refugees", moved)
    return moved


def _kill_civilians(w: World, rid: str, number: float) -> None:
    """Proportional civilian deaths, as `military._kill_civilians`, with a civil-war counter."""
    pops = [p for p in w.pops if p.region == rid]
    total = sum(p.size for p in pops)
    if total <= 0.0 or number <= 0.0:
        return
    for pop in pops:
        pop.size = max(0.0, pop.size - number * pop.size / total)
    w.count("deaths_war_civilian", number)
    w.count("civil_war_civilians_killed", number)


def _merge(target, source, number: float) -> None:
    """Move `number` people from `source` into `target`, blending their attitudes."""
    total = target.size + number
    if total <= 0.0:
        return
    for attr in ("approval", "indep", "unrest", "grievance", "fear", "hunger", "income", "savings"):
        setattr(target, attr, (getattr(target, attr) * target.size
                               + getattr(source, attr) * number) / total)
    target.size = total


def _sync_territory(w: World, state: dict) -> None:
    """Keep C1's territory lists equal to what the controllers now say, in a stable order."""
    factions = state.get("factions")
    if not isinstance(factions, dict):
        return
    for side, controller in (("government", "karamaniya"), ("rebels", "rebels")):
        entry = factions.get(side)
        if isinstance(entry, dict):
            entry["territory"] = sorted(r.id for r in w.regions
                                        if r.nation == "karamaniya" and r.controller == controller)
