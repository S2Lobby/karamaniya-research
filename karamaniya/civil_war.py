"""Civil war between factions of the council: the state, the factions, the forces and the triggers.

Wave C (C1). The run option is ``civil_war = "on" | "off"`` (``civil_war.validate_option``); the
default, ``"off"``, is engine 29's behaviour exactly: no trigger fires, and no engine path reads
``World.civil_war``. The state is built once, by ``start()``, from the coup that began the war::

    w.civil_war = {
        "since": month,
        "cause": "failed_coup" | "handover_coup",
        "factions": {
            "government": {"id", "leader", "members", "forces", "territory", "power_share"},
            "rebels":     {"id", "leader", "members", "forces", "territory", "power_share"},
        },
        "contested": [region ids],
        "neutral_power_share": float,
        "ceasefire": False,          # C4 owns a ceasefire in force
        "offers": [],                # C4 owns offers and acceptances
        "outcome": None,             # C4 owns the war's end
    }

The design is ``notes/CIVIL_WAR-design.md``; the lead's decisions are
``notes/open-actions-decisions.md``. In short:

- **Members.** The government is every active member not in rebellion; the rebels are the coup's
  plotters plus every active member whose coup stance was ``join``. Rebels keep their seats: they
  are listed here, not removed. Each faction's leader is the highest office in ``OFFICES`` order
  (head, treasury, interior, army, navy), ties broken by ``politics._power``.
- **Forces.** For each armed office (army, navy, interior/police), ``military.anticipated_response``
  splits the force under its current holder's order. Every office uses the same rule, mirroring
  ``resolve_coups``: the rebels take ``obey_commander`` when the holder is a rebel, the government
  takes ``obey_government + 0.5 * split`` whether or not the holder is one, and the rest (neutral,
  the other half of a split, and the commander share of a government-held force) is unaligned.
  Shares are weighted by ``politics._power``.
- **Territory.** Regions the engine already lists as ``controller == "rebels"`` join the rebels. The
  other government regions stay government, except that the capital and the two front deployments
  are *contested* when the rebel army share is at least one half. ``controller`` keeps its two
  existing war values (``"rebels"`` and ``"karamaniya"``); the contested set lives in the state, not
  in a new controller value, because briefing, foreign_force, economy and the map already read the
  two existing values.
- **Triggers** (from Month 2 only; the user's rule forbids a civil war in Month 1):
  1. a failed coup whose plotters keep at least ``FAILED_COUP_SHARE`` of the armed power (weighted
     by ``politics._power``) while at least one armed plotter's force is bonded to its commander
     (``bond >= FAILED_COUP_BOND``) or disloyal to the state (``loyalty <= FAILED_COUP_LOYALTY``):
     the plotters are not arrested and the war starts;
  2. a handover coup that succeeds while the government keeps at least
     ``HANDOVER_GOVERNMENT_SHARE`` of the armed power: the war starts instead of the
     kept-power-by-force outcome.

Combat, the faction month and records are other workstreams (C2, C3, C5). This module owns the
negotiation and the ends (C4). The state above gains, on first use:

    "prewar_strength": {"government": float, "rebels": float},   # soldier-equivalents at the start
    "stalemate": {"months", "month", "signature"},               # the partition clock
    "breaches": [{"side", "month", "reason", ...}],              # broken ceasefires
    "next_offer_id": int,
    "settlement": dict | None,
    "outcome": None | {"type", "month", "text", ...},

- **Ceasefire.** ``ceasefire(w, side)`` records an offer (or a fresh offer when one is already
  pending); a call from the other side, or ``ceasefire(..., accept=True)``, accepts it and sets
  ``ceasefire = {"active": True, "broken": False, ...}``, the flag C2's combat reads. A bare
  truthy value also reads as holding, as C2's own ``ceasefire_active`` does. ``breach(w, side)``
  breaks it and records the breach; ``check_end`` also breaks it on an ``attack`` order in
  ``w.civil_war["orders"]`` (C3 should call ``breach`` before combat, so the attack is not
  silently ignored).
- **Settlement.** ``offer(w, side, terms)`` and ``respond(w, side, offer_id/terms, accept)`` work
  the closed list: ``amnesty``, ``power_sharing`` (named offices divided), ``regional_autonomy``
  (a named region), ``forces`` (``integrate`` or ``disarm``), and ``election_date`` (a month
  number, never before Month 36). When both sides accept the same terms in the same month, the
  terms are applied, ``outcome = {"type": "settled", ...}`` is recorded, and the run goes on.
  Offers, acceptances, refusals and breaches stay in ``offers``/``ceasefire``/``breaches``.
- **Ends** (checked once a month by ``check_end``):
  - *victory*: one side holds the capital while the other's armed force (in soldier-equivalents)
    is below 15% of its pre-war strength. ``civil_war_won_by_government`` or
    ``civil_war_won_by_rebels`` is recorded in the war state; the run goes on. On a rebel victory
    the rebels take the offices by faction rank.
  - *partition*: six consecutive months with no change of controller or contested set while a
    ceasefire holds; ``partitioned`` ends the run.
  - *collapse*: no faction holds the capital; ``no_government`` ends the run.
  A run that has already ended gets no second outcome. Under ``civil_war = "off"`` every function
  here is a no-op.
"""
from __future__ import annotations

import re

from .world import ARMED_OFFICES, CHARTER_ELECTION_MONTH, OFFICES

OPTION_ON = "on"
OPTION_OFF = "off"
OPTIONS = (OPTION_ON, OPTION_OFF)

# 0-based month index: Month 2. The user's design rule allows no civil war in Month 1.
FIRST_TRIGGER_MONTH = 1

# The two thresholds are assumptions, to be calibrated by the scripted hawk sweep (design section
# 11; the agreed band: no quiet run starts a civil war, and 10-40% of hawk stress runs do). They
# are not measured facts, and C5 may move them.
FAILED_COUP_SHARE = 0.30       # of all armed power, weighted by politics._power, obeying the plotters
FAILED_COUP_BOND = 0.30        # one armed plotter's force at least this bonded to its commander,
FAILED_COUP_LOYALTY = 0.45     # or at most this loyal to the state
HANDOVER_GOVERNMENT_SHARE = 0.25  # of all armed power kept by the government side

# The capital and the two fronts are the deployments the army's splits are read against
# (`Military.deploy`), in the order the design names them.
DEPLOYMENT_KEYS = ("capital", "north", "east")

# ---- C4: negotiation and the ends -----------------------------------------------------------
SIDES = ("government", "rebels")
OTHER_SIDE = {"government": "rebels", "rebels": "government"}

# The closed settlement list (notes/CIVIL_WAR-design.md section 6; the user approved it on
# 2026-10-17) is amnesty, power sharing, regional autonomy, the forces, and an election date.
# Anything else is refused in words. The force term's two modes:
FORCE_MODES = ("integrate", "disarm")

# Soldier-equivalents, the same weights C2's combat and `military._force_power` use: a sailor
# counts 900 times a soldier and a police officer 0.35, so a navy's six ships are not compared to
# an army's men as if they were six people.
FORCE_EQUIVALENT = {"army": 1.0, "navy": 900.0, "interior": 0.35}

# Approved scales: one side holds the capital and the other's force is below 15% of its pre-war
# strength; six months without a front moving and a ceasefire partition the country.
VICTORY_SHARE = 0.15
PARTITION_MONTHS = 6

# The design's hard rule: no election before Month 36. `election_date` in the offer is a 1-based
# month number (the way the prompts say months); `Constituent.election_month` is 0-based.
EARLIEST_ELECTION_MONTH = CHARTER_ELECTION_MONTH + 1


# ---- the run option and the state ----------------------------------------------------------
def validate_option(value) -> str:
    """Normalise the run option. An absent option (None) means off, as it did before this arm."""
    if value is None:
        return OPTION_OFF
    if not isinstance(value, str):
        raise ValueError("civil_war must be 'on' or 'off'")
    value = value.strip().lower()
    if value not in OPTIONS:
        raise ValueError("civil_war must be 'on' or 'off'")
    return value


def option(w) -> str:
    """The run option as the world carries it."""
    return validate_option(getattr(w, "civil_war_option", OPTION_OFF))


def enabled(w) -> bool:
    return option(w) == OPTION_ON


def state(w):
    """The civil-war state, or None. Under the default option nothing reads it."""
    return getattr(w, "civil_war", None)


def is_rebel(w, mid: str) -> bool:
    current = state(w)
    return bool(current) and mid in current["factions"]["rebels"]["members"]


def rebel_ids(w) -> set:
    current = state(w)
    return set(current["factions"]["rebels"]["members"]) if current else set()


# ---- the forces ------------------------------------------------------------------------------
def _power(w, office: str) -> float:
    # Lazy: politics imports this module at its trigger call sites, so a top-level import would
    # close a cycle. The world model's own weighting must be reused, not copied.
    from .politics import _power as power
    return power(w, office)


def _force(w, office: str):
    from .politics import _force as force
    return force(w, office)


def armed_divisions(w) -> dict:
    """Every armed office's anticipated split under an order from its current holder.

    This is the same call and the same order resolve_coups makes for an armed plotter, made for all
    three offices so that a handover split can be judged from the record before any removals. The
    holder id does not enter the model (``unit_response`` reads the office, the force, the state and
    the government's legitimacy only); it is kept so a reader can see who commanded.
    """
    from . import military
    divisions = {}
    for office in ARMED_OFFICES:
        holder = w.holder(office)
        division = military.anticipated_response(
            w, {"kind": "coup", "office": office,
                "leader": holder.id if holder is not None else None})
        divisions[office] = {
            "holder": holder.id if holder is not None else None,
            "power": round(_power(w, office), 3),
            **{k: round(v, 6) for k, v in division.items()},
        }
    return divisions


def _total_power(divisions: dict) -> float:
    return sum(d.get("power", 0.0) for d in divisions.values()) or 1.0


def commander_share(rec: dict) -> float:
    """The plotters' combined ``obey_commander`` share of the armed power, weighted by ``_power``."""
    divisions = rec.get("divisions") or {}
    plotters = set(rec.get("armed") or rec.get("plotters") or [])
    if not divisions:
        return 0.0
    obeying = sum(d.get("power", 0.0) * d.get("obey_commander", 0.0)
                  for d in divisions.values() if d.get("holder") in plotters)
    return obeying / _total_power(divisions)


def government_share(divisions: dict) -> float:
    """The whole armed power's government share: ``obey_government + 0.5 * split``.

    A diagnostic for reports; the handover trigger does not use it, because the loyal police and
    navy count in it even when the plotters' own commands stayed whole (see ``handover_starts``).
    """
    keeping = sum(d.get("power", 0.0) * (d.get("obey_government", 0.0) + 0.5 * d.get("split", 0.0))
                  for d in divisions.values())
    return keeping / _total_power(divisions)


# ---- the triggers ----------------------------------------------------------------------------
def failed_coup_starts(w, rec: dict) -> bool:
    """Whether a failed coup's conditions start the war (predicate; starts nothing)."""
    if not enabled(w) or state(w) is not None or w.month < FIRST_TRIGGER_MONTH:
        return False
    divisions = rec.get("divisions") or {}
    if not divisions or commander_share(rec) < FAILED_COUP_SHARE:
        return False
    armed = set(rec.get("armed") or rec.get("plotters") or [])
    for office, division in divisions.items():
        if division.get("holder") not in armed:
            continue
        force = _force(w, office)
        if force.bond >= FAILED_COUP_BOND or force.loyalty <= FAILED_COUP_LOYALTY:
            return True
    return False


def maybe_start_from_failed_coup(w, rec: dict):
    """Start the war on a failed coup whose plotters keep their force; None leaves today's path."""
    if not failed_coup_starts(w, rec):
        return None
    return start(w, "failed_coup",
                 plotters=rec.get("plotters") or rec.get("armed") or [],
                 divisions=rec.get("divisions"))


def handover_starts(w, rec: dict) -> bool:
    """Whether a handover coup splits a command the plotters actually hold.

    Only armed offices held by a plotter are judged. A total takeover — the plotter's own force
    obeys its commander, so its ``obey_government + 0.5 * split`` stays below the threshold —
    keeps the kept-power-by-force outcome even when the government-held police or navy remain
    loyal; a loyal police share alone must not turn every quiet handover coup into a war. The war
    starts when one of the plotters' own commands keeps at least ``HANDOVER_GOVERNMENT_SHARE`` of
    itself with the government.
    """
    if not enabled(w) or state(w) is not None or w.month < FIRST_TRIGGER_MONTH:
        return False
    divisions = rec.get("divisions") or armed_divisions(w)
    plotters = set(rec.get("plotters") or rec.get("armed") or [])
    for division in divisions.values():
        if division.get("holder") not in plotters:
            continue
        if (division.get("obey_government", 0.0) + 0.5 * division.get("split", 0.0)
                >= HANDOVER_GOVERNMENT_SHARE):
            return True
    return False


def maybe_start_from_handover(w, rec: dict):
    """Start the war instead of recording kept-power-by-force; None leaves today's outcome."""
    if not handover_starts(w, rec):
        return None
    return start(w, "handover_coup",
                 plotters=rec.get("plotters") or rec.get("armed") or [],
                 divisions=rec.get("divisions"))


# ---- the state -------------------------------------------------------------------------------
def _member_rank(w, mid: str) -> tuple:
    """The highest office a member holds, then the armed power behind it (highest first)."""
    offices = w.offices_of(mid)
    ranks = [OFFICES.index(office) for office in offices if office in OFFICES]
    power = sum(_power(w, office) for office in offices if office in ARMED_OFFICES)
    return (min(ranks) if ranks else len(OFFICES), -power, mid)


def _leader(w, members: list):
    return min(members, key=lambda mid: _member_rank(w, mid)) if members else None


def _deployment_region(w, key: str):
    """The Karamaniya region a deployment key stands on: the capital, or the front's first region."""
    for region in w.regions:
        if region.nation != "karamaniya":
            continue
        if (region.capital if key == "capital" else region.front == key):
            return region
    return None


def _ordered(ids) -> list:
    seen = set()
    out = []
    for rid in ids:
        if rid not in seen:
            seen.add(rid)
            out.append(rid)
    return out


def start(w, cause: str, plotters=None, stances=None, divisions=None):
    """Build the factions, the armed shares and the territory, and mark the war on the world.

    ``plotters`` is the coup leader and everyone marked ``join`` (resolve_coups' set);
    ``stances`` may supply the joiners directly. ``divisions`` is the coup record's
    ``anticipated_response`` split, reused so the trigger and the state judge the same numbers.
    Returns the state; a running war's state is returned unchanged; None when the arm is off.
    """
    if not enabled(w):
        return None
    current = state(w)
    if current is not None:
        return current
    active = {member.id for member in w.active_members()}
    plotters = {mid for mid in (plotters or []) if mid in active}
    joiners = {mid for mid, stance in (stances or {}).items()
               if stance == "join" and mid in active}
    rebels = sorted(plotters | joiners)
    rebel_set = set(rebels)
    government = sorted(active - rebel_set)

    divisions = dict(divisions or armed_divisions(w))
    missing = [office for office in ARMED_OFFICES if office not in divisions]
    if missing:
        fresh = armed_divisions(w)
        for office in missing:
            divisions[office] = fresh[office]

    forces = {"government": {}, "rebels": {}}
    power = {"government": 0.0, "rebels": 0.0}
    unaligned = 0.0
    for office in ARMED_OFFICES:
        division = divisions[office]
        holder = division.get("holder")
        # The same rule as resolve_coups' attack and defend, applied to every office: the rebels
        # get obey_commander when the holder is a rebel; the government gets
        # obey_government + 0.5 * split whether or not the holder is one. What is left is
        # unaligned: neutral plus the other half of any split, and (for a government-held force)
        # the share that would follow a coup order from its own commander.
        rebel_share = division["obey_commander"] if holder in rebel_set else 0.0
        government_share_ = division["obey_government"] + 0.5 * division["split"]
        unaligned_share = max(0.0, 1.0 - rebel_share - government_share_)
        power["rebels"] += division["power"] * rebel_share
        power["government"] += division["power"] * government_share_
        unaligned += division["power"] * unaligned_share
        size = _force(w, office).size
        for side, share in (("rebels", rebel_share), ("government", government_share_)):
            forces[side][office] = {
                "holder": holder,
                "power": division["power"],
                "share": round(share, 4),
                "size": round(size * share, 1),
                "neutral_share": round(division["neutral"], 4),
                "unaligned_share": round(unaligned_share, 4),
            }
    total = _total_power(divisions)

    rebel_territory = [r.id for r in w.regions
                       if r.nation == "karamaniya" and r.controller == "rebels"]
    government_territory = [r.id for r in w.regions
                            if r.nation == "karamaniya" and r.controller == "karamaniya"]
    army = divisions["army"]
    rebel_army_share = army["obey_commander"] if army.get("holder") in rebel_set else 0.0
    contested = []
    for key in DEPLOYMENT_KEYS:
        region = _deployment_region(w, key)
        if region is None or region.controller != "karamaniya":
            continue
        if rebel_army_share >= 0.5:
            contested.append(region.id)

    leader = _leader(w, rebels)
    state_ = {
        "since": w.month,
        "cause": cause,
        "factions": {
            "government": {
                "id": "government",
                "leader": _leader(w, government),
                "members": government,
                "forces": forces["government"],
                "territory": government_territory,
                "power_share": round(power["government"] / total, 4),
            },
            "rebels": {
                "id": "rebels",
                "leader": leader,
                "members": rebels,
                "forces": forces["rebels"],
                "territory": rebel_territory,
                "power_share": round(power["rebels"] / total, 4),
            },
        },
        "contested": contested,
        "unaligned_power_share": round(unaligned / total, 4),
        # C4 reads these. The pre-war strength is fixed here, once, in soldier-equivalents; every
        # later "below 15%" test compares the current strength with it.
        "prewar_strength": {
            side: round(sum(forces[side][office]["size"] * FORCE_EQUIVALENT[office]
                            for office in ARMED_OFFICES), 1)
            for side in SIDES
        },
        "stalemate": {"months": 0, "month": None, "signature": None},
        "breaches": [],
        "next_offer_id": 1,
        "settlement": None,
        "ceasefire": False,
        "offers": [],
        "outcome": None,
    }
    w.civil_war = state_
    where = [w.region(rid).name for rid in _ordered(rebel_territory + contested)]
    leader_name = w.member(leader).name if leader is not None else "The armed officers"
    w.event("civil_war",
            f"Civil war: {leader_name} and the officers who follow them have broken with the "
            f"government. Fighting has begun in {', '.join(where) if where else 'the country'}.",
            importance=3,
            detail={"cause": cause, "rebels": rebels, "contested": contested})
    return state_


# ---- C4: state helpers ----------------------------------------------------------------------
def running(w) -> bool:
    """Whether a civil war is still being fought. C3 uses this to decide whether the faction month
    still has a war to answer; a settled or won war is over but the run goes on."""
    current = state(w)
    return bool(enabled(w) and isinstance(current, dict) and current and not current.get("outcome"))


def war_outcome(w):
    """The war's outcome record, or None. It is not `w.outcome` unless the run itself has ended."""
    current = state(w)
    return current.get("outcome") if isinstance(current, dict) else None


def _normalise_side(side):
    if not isinstance(side, str):
        return None
    text = side.strip().lower()
    if text in ("government", "gov", "state"):
        return "government"
    if text in ("rebels", "rebel", "rebellion"):
        return "rebels"
    return None


def _other(side: str) -> str:
    return OTHER_SIDE[side]


def _truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "no", "none", "off", "0", "refuse", "reject")
    return bool(value)


def _float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _refusal(problem: str, kind: str = "settlement"):
    return {"ok": False, "kind": kind, "action": "refused", "offer": None,
            "offer_id": None, "terms": None, "problems": [problem], "settled": False}


def _live_state(w):
    """The state while a war is running: the arm is on, a war exists, and it has no outcome yet."""
    if not enabled(w):
        return None
    current = state(w)
    if not isinstance(current, dict) or not current or current.get("outcome"):
        return None
    return current


def _active_members(w, current, side: str) -> list:
    out = []
    factions = (current or {}).get("factions") or {}
    for mid in (factions.get(side) or {}).get("members") or []:
        try:
            member = w.member(mid)
        except KeyError:
            continue
        if member.status == "active":
            out.append(member)
    return out


def _contested_ids(current: dict) -> list:
    """The contested region ids. C2 tolerates a dict entry that names its region; so do we."""
    out = []
    for entry in current.get("contested") or []:
        rid = entry.get("region") or entry.get("id") if isinstance(entry, dict) else entry
        if rid:
            out.append(str(rid))
    return out


def _capital_region(w):
    for region in w.regions:
        if region.nation == "karamaniya" and region.capital:
            return region
    return None


# ---- C4: strengths --------------------------------------------------------------------------
def strength(w, side: str, current: dict | None = None) -> float:
    """A faction's armed strength in soldier-equivalents (the weights C2's combat uses).

    C2 rewrites ``w.civil_war["forces"]`` each month; while it is absent, C1's per-faction shares
    are the record. The service size is read live, so combat losses C2 has already taken out of
    the forces count here.
    """
    side = _normalise_side(side) or side
    current = current if isinstance(current, dict) else state(w)
    if not isinstance(current, dict):
        return 0.0
    services = current.get("forces")
    total = 0.0
    for office in ARMED_OFFICES:
        force = _force(w, office)
        size = max(0.0, _float(getattr(force, "size", 0.0)))
        share = None
        if isinstance(services, dict) and office in services:
            entry = services.get(office)
            if isinstance(entry, dict):
                share = max(0.0, _float(entry.get(side)))
            elif isinstance(entry, (int, float)):
                value = max(0.0, min(1.0, _float(entry)))
                share = value if side == "rebels" else 1.0 - value
        if share is None:
            try:
                share = _float((current["factions"][side]["forces"].get(office) or {}).get("share"))
            except (KeyError, TypeError, AttributeError):
                share = 0.0
        total += size * FORCE_EQUIVALENT[office] * max(0.0, min(1.0, share))
    return total


def prewar_strength(w, side: str, current: dict | None = None) -> float:
    """The faction's strength when the war began. A checkpoint from before C4 falls back to the
    per-faction sizes C1 recorded at the start."""
    side = _normalise_side(side) or side
    current = current if isinstance(current, dict) else state(w)
    if not isinstance(current, dict):
        return 0.0
    recorded = current.get("prewar_strength")
    if isinstance(recorded, dict) and side in recorded:
        return max(0.0, _float(recorded.get(side)))
    # A checkpoint written between C1 and C4 keeps C1's per-faction sizes; write them down as the
    # pre-war record the first time a caller asks, so every later check reads the same numbers.
    computed = {}
    for name in SIDES:
        total = 0.0
        for office in ARMED_OFFICES:
            try:
                size = _float(((current["factions"][name]["forces"].get(office) or {}).get("size")))
            except (KeyError, TypeError, AttributeError):
                size = 0.0
            total += max(0.0, size) * FORCE_EQUIVALENT[office]
        computed[name] = round(total, 1)
    current["prewar_strength"] = computed
    return computed.get(side, 0.0)


# ---- C4: the settlement list ----------------------------------------------------------------
def _canonical_offices(w, current, value, problems):
    """Power sharing: office -> the side that takes it."""
    if isinstance(value, dict):
        items = list(value.items())
    elif isinstance(value, (list, tuple)):
        items = []
        for item in value:
            if isinstance(item, dict) and item.get("office") is not None:
                items.append((item.get("office"), item.get("side")))
            else:
                problems.append("Power sharing must name an office and the side that takes it.")
    else:
        problems.append("Power sharing must name offices and the side each one goes to.")
        return {}
    out = {}
    for raw_office, raw_side in items:
        office = str(raw_office).strip().lower()
        side = _normalise_side(raw_side)
        if office not in OFFICES:
            problems.append(f"Power sharing names an office that does not exist: '{raw_office}'.")
            continue
        if side is None:
            problems.append(f"Power sharing names a side that does not exist: '{raw_side}' "
                            "(use government or rebels).")
            continue
        out[office] = side
    for side in sorted(set(out.values())):
        if not _active_members(w, current, side):
            problems.append(f"Power sharing gives an office to the {side}, which has no active members.")
    return {office: out[office] for office in OFFICES if office in out}


def _canonical_region(w, value, problems):
    raw = value
    if isinstance(value, dict):
        raw = value.get("region") or value.get("id")
    if not isinstance(raw, str) or not raw.strip():
        problems.append("Regional autonomy must name a region.")
        return None
    key = raw.strip().lower()
    region = None
    try:
        region = w.region(key)
    except KeyError:
        for candidate in w.regions:
            if candidate.nation == "karamaniya" and candidate.name.strip().lower() == key:
                region = candidate
                break
    if region is None or region.nation != "karamaniya":
        problems.append(f"Regional autonomy names a region Karamaniya does not hold: '{raw}'.")
        return None
    return region.id


def _canonical_forces(value, problems):
    if isinstance(value, dict):
        value = value.get("mode") or value.get("forces") or value.get("value")
    text = str(value).strip().lower() if value is not None else ""
    if text in ("integrate", "integration"):
        return "integrate"
    if text in ("disarm", "disarmament"):
        return "disarm"
    problems.append("The forces term must be integration ('integrate') or disarmament ('disarm'), "
                    f"not '{value}'.")
    return None


def _canonical_election_month(w, value, problems):
    """An election date is a 1-based month number, the way the prompts say months."""
    raw = value
    if isinstance(value, dict):
        raw = value.get("month") or value.get("election_date") or value.get("value")
    month = None
    if isinstance(raw, bool):
        month = None
    elif isinstance(raw, (int, float)):
        month = int(raw)
    elif isinstance(raw, str):
        digits = re.findall(r"\d+", raw)
        if digits:
            month = int(digits[0])
    if month is None:
        problems.append("The election date must be a month number, such as 36 for Month 36.")
        return None
    if month < EARLIEST_ELECTION_MONTH:
        problems.append(f"No election may be scheduled before Month {EARLIEST_ELECTION_MONTH}; "
                        f"the offer asks for Month {month}.")
        return None
    if month - 1 < w.month:
        problems.append(f"The election date Month {month} has already passed.")
        return None
    return month


def canonical_terms(w, terms):
    """Validate an offer against the closed list; return ``(canonical, problems)``.

    ``terms`` may be a map (the canonical shape), a bare term name, or a list of names and maps.
    The canonical shape is ``{"amnesty": True, "power_sharing": {office: side},
    "regional_autonomy": region_id, "forces": "integrate" | "disarm", "election_date": month}``.
    """
    problems = []
    if isinstance(terms, str):
        terms = {terms: True}
    elif isinstance(terms, (list, tuple)):
        merged = {}
        for item in terms:
            if isinstance(item, str):
                merged[item] = True
            elif isinstance(item, dict):
                merged.update(item)
            else:
                problems.append("Each settlement term must be a name or a map of its details.")
        terms = merged
    if not isinstance(terms, dict):
        return None, ["The settlement terms must be a map of terms or a list of terms."]
    current = state(w) or {}
    canonical = {}
    for raw_key, raw_value in terms.items():
        key = str(raw_key).strip().lower().replace("-", "_").replace(" ", "_")
        if key == "amnesty":
            if _truthy(raw_value):
                canonical["amnesty"] = True
        elif key in ("power_sharing", "power_sharing_offices", "offices"):
            assignments = _canonical_offices(w, current, raw_value, problems)
            if assignments:
                canonical["power_sharing"] = assignments
        elif key in ("regional_autonomy", "autonomy"):
            rid = _canonical_region(w, raw_value, problems)
            if rid is not None:
                canonical["regional_autonomy"] = rid
        elif key in ("forces", "force"):
            mode = _canonical_forces(raw_value, problems)
            if mode is not None:
                canonical["forces"] = mode
        elif key in ("election_date", "election", "election_month"):
            month = _canonical_election_month(w, raw_value, problems)
            if month is not None:
                canonical["election_date"] = month
        else:
            problems.append(f"The settlement terms are a closed list; '{raw_key}' is not one of "
                            "them (amnesty, power sharing, regional autonomy, the forces, an "
                            "election date).")
    if not canonical and not problems:
        problems.append("An offer must name at least one settlement term.")
    return (canonical or None), problems


def _settlement_problems(w, current, terms):
    """Re-check a canonical settlement against the state as it is when it is accepted."""
    problems = []
    for office, side in (terms.get("power_sharing") or {}).items():
        if office not in OFFICES:
            problems.append(f"Power sharing names an office that does not exist: '{office}'.")
        elif not _active_members(w, current, side):
            problems.append(f"Power sharing gives {office} to the {side}, which has no active members.")
    rid = terms.get("regional_autonomy")
    if rid is not None:
        try:
            region = w.region(rid)
        except KeyError:
            region = None
        if region is None or region.nation != "karamaniya":
            problems.append(f"Regional autonomy names a region Karamaniya does not hold: '{rid}'.")
    mode = terms.get("forces")
    if mode is not None and mode not in FORCE_MODES:
        problems.append(f"The forces term is not one this engine can carry out: '{mode}'.")
    month = terms.get("election_date")
    if month is not None:
        if not isinstance(month, int) or month < EARLIEST_ELECTION_MONTH:
            problems.append(f"No election may be scheduled before Month {EARLIEST_ELECTION_MONTH}.")
        elif month - 1 < w.month:
            problems.append(f"The election date Month {month} has already passed.")
    return problems


# ---- C4: offers and responses ---------------------------------------------------------------
def _record_offer(w, current, side, canonical, problems) -> dict:
    offer_id = int(_float(current.get("next_offer_id"), 1) or 1)
    current["next_offer_id"] = offer_id + 1
    record = {"id": offer_id, "kind": "settlement", "from": side, "month": w.month,
              "terms": canonical, "status": "invalid" if problems else "pending",
              "responses": [], "problems": list(problems)}
    current.setdefault("offers", []).append(record)
    return record


def offer(w, side, terms):
    """Offer settlement terms from one side. Returns a record in words.

    The same terms offered by the other side in the same month are mutual acceptance, and settle.
    """
    current = _live_state(w)
    if current is None:
        return _refusal("No civil war is running, or the war is already over.")
    side_name = _normalise_side(side)
    if side_name is None:
        return _refusal(f"Unknown side: '{side}'. Use government or rebels.")
    canonical, problems = canonical_terms(w, terms)
    if canonical is None and not problems:
        problems = ["An offer must name at least one settlement term."]
    if problems:
        record = _record_offer(w, current, side_name, canonical, problems)
        return {"ok": False, "kind": "settlement", "action": "invalid", "side": side_name,
                "offer": record, "offer_id": record["id"], "terms": canonical,
                "problems": problems, "settled": False}
    for prior in reversed(current.setdefault("offers", [])):
        if (prior.get("kind") == "settlement" and prior.get("status") == "pending"
                and prior.get("month") == w.month and prior.get("from") == _other(side_name)
                and prior.get("terms") == canonical):
            prior["responses"].append({"side": side_name, "month": w.month, "accept": True,
                                       "via": "matching_offer"})
            record = _record_offer(w, current, side_name, canonical, [])
            record["status"] = "settled"
            record["responses"].append({"side": _other(side_name), "month": w.month,
                                        "accept": True, "via": "matching_offer"})
            applied, failures = _settle(w, current, prior, [side_name, _other(side_name)])
            if failures:
                record["status"] = "invalid"
                return {"ok": False, "kind": "settlement", "action": "invalid",
                        "side": side_name, "offer": record, "offer_id": record["id"],
                        "terms": canonical, "problems": failures, "settled": False}
            return {"ok": True, "kind": "settlement", "action": "settled", "side": side_name,
                    "offer": record, "offer_id": record["id"], "terms": canonical,
                    "problems": [], "settled": True, "outcome": current.get("outcome"),
                    "applied": applied}
    record = _record_offer(w, current, side_name, canonical, [])
    return {"ok": True, "kind": "settlement", "action": "offered", "side": side_name,
            "offer": record, "offer_id": record["id"], "terms": canonical,
            "problems": [], "settled": False}


def respond(w, side, offer_id=None, terms=None, accept=True):
    """Answer a settlement offer: accept or refuse it.

    ``side`` is the side answering; the offer must come from the other side and, for a settlement,
    from the same month. ``offer_id`` names the offer, or ``terms`` finds the one carrying the same
    terms. Returns a record in words.
    """
    current = _live_state(w)
    if current is None:
        return _refusal("No civil war is running, or the war is already over.")
    side_name = _normalise_side(side)
    if side_name is None:
        return _refusal(f"Unknown side: '{side}'. Use government or rebels.")
    accepted = _truthy(accept)
    offers = current.setdefault("offers", [])
    canonical = None
    if isinstance(offer_id, str) and offer_id.strip().isdigit():
        offer_id = int(offer_id.strip())
    if offer_id is not None:
        match = next((o for o in offers
                      if o.get("kind") == "settlement" and o.get("id") == offer_id), None)
        if match is None:
            return _refusal(f"No settlement offer {offer_id} exists.")
    else:
        if terms is not None:
            canonical, problems = canonical_terms(w, terms)
            if problems:
                result = _refusal("The terms do not name an offer that can be answered.")
                result["problems"] = problems
                return result
        match = None
        for candidate in reversed(offers):
            if candidate.get("kind") != "settlement" or candidate.get("status") != "pending":
                continue
            if candidate.get("from") == side_name:
                continue
            if canonical is not None and candidate.get("terms") != canonical:
                continue
            match = candidate
            break
        if match is None:
            return _refusal("No offer from the other side is waiting for an answer.")
    if match.get("from") == side_name:
        return _refusal("A side cannot answer its own offer.")
    if match.get("status") != "pending":
        return _refusal(f"That offer is already {match.get('status')}.")
    if match.get("month") != w.month:
        match["status"] = "expired"
        match["expired_month"] = w.month
        return _refusal("That offer is from an earlier month; an offer and its acceptance must "
                        "come in the same month.")
    match["responses"].append({"side": side_name, "month": w.month, "accept": accepted})
    if not accepted:
        match["status"] = "refused"
        return {"ok": True, "kind": "settlement", "action": "refused", "side": side_name,
                "offer": match, "offer_id": match.get("id"), "terms": match.get("terms"),
                "problems": [], "settled": False, "outcome": current.get("outcome")}
    match["status"] = "settled"
    applied, failures = _settle(w, current, match, [side_name])
    if failures:
        return {"ok": False, "kind": "settlement", "action": "invalid", "side": side_name,
                "offer": match, "offer_id": match.get("id"), "terms": match.get("terms"),
                "problems": failures, "settled": False}
    return {"ok": True, "kind": "settlement", "action": "settled", "side": side_name,
            "offer": match, "offer_id": match.get("id"), "terms": match.get("terms"),
            "problems": [], "settled": True, "outcome": current.get("outcome"), "applied": applied}


# ---- C4: applying a settlement --------------------------------------------------------------
def _assign_offices(w, current, assignments: dict) -> dict:
    """Give each named office to the highest-ranked active member of the named side."""
    from .politics import reset_bond
    taken = {side: set() for side in SIDES}
    assigned = {}
    for office in OFFICES:
        side = assignments.get(office)
        if side not in SIDES:
            continue
        members = sorted(_active_members(w, current, side),
                         key=lambda member: _member_rank(w, member.id))
        if not members:
            continue
        pick = next((member for member in members if member.id not in taken[side]), members[0])
        taken[side].add(pick.id)
        w.const.offices[office] = pick.id
        reset_bond(w, office)
        assigned[office] = pick.id
    return assigned


def _service_shares(w, current) -> dict:
    """Every service's side shares, from C2's block when it exists, else from C1's factions."""
    services = current.get("forces")
    out = {}
    for office in ARMED_OFFICES:
        entry = services.get(office) if isinstance(services, dict) else None
        if isinstance(entry, dict):
            shares = {side: max(0.0, _float(entry.get(side)))
                      for side in ("government", "rebels", "neutral")}
        elif isinstance(entry, (int, float)):
            rebel = max(0.0, min(1.0, _float(entry)))
            shares = {"government": 1.0 - rebel, "rebels": rebel, "neutral": 0.0}
        else:
            government = _float(((current["factions"]["government"]["forces"].get(office) or {})
                                 .get("share")))
            rebels = _float(((current["factions"]["rebels"]["forces"].get(office) or {})
                             .get("share")))
            shares = {"government": government, "rebels": rebels,
                      "neutral": max(0.0, 1.0 - government - rebels)}
        total = sum(shares.values()) or 1.0
        out[office] = {side: value / total for side, value in shares.items()}
    return out


def _apply_forces(w, current, mode: str) -> dict:
    """Integrate the rebel share into the state's forces, or take it out of them."""
    shares = _service_shares(w, current)
    details = {}
    for office in ARMED_OFFICES:
        entry = shares[office]
        rebel = max(0.0, min(1.0, _float(entry.get("rebels"))))
        force = _force(w, office)
        if mode == "disarm":
            before = max(0.0, _float(getattr(force, "size", 0.0)))
            force.size = max(0.0, before * (1.0 - rebel))
            details[office] = {"mode": "disarm", "rebel_share": round(rebel, 6),
                               "size_before": round(before, 1),
                               "size_after": round(force.size, 1)}
        else:
            details[office] = {"mode": "integrate", "rebel_share": round(rebel, 6)}
        shares[office] = {"government": 1.0, "rebels": 0.0, "neutral": 0.0}
        # Keep C1's per-faction blocks consistent for readers that use them.
        for side in SIDES:
            block = current["factions"][side]["forces"].setdefault(office, {})
            block["share"] = 1.0 if side == "government" else 0.0
            block["size"] = round(max(0.0, _float(getattr(force, "size", 0.0))) * block["share"], 1)
            block["unaligned_share"] = 0.0
            block["neutral_share"] = 0.0
    current["forces"] = shares
    return details


def _apply_terms(w, current, terms: dict) -> dict:
    applied = {}
    if terms.get("amnesty"):
        from . import politics
        politics.set_lever(w, "amnesty", "release")
        applied["amnesty"] = "release"
    if terms.get("power_sharing"):
        applied["assigned_offices"] = _assign_offices(w, current, terms["power_sharing"])
    rid = terms.get("regional_autonomy")
    if rid is not None:
        from . import regional
        applied["regional_autonomy"] = rid
        if rid in regional.REGIONS:
            regional.set_status(w, rid, "devolved")
            applied["regional_status"] = "devolved"
        else:
            # Only Kessel Valley and the Vell Highlands have a status the engine reads. A grant
            # for another region is recorded as an agreed term; no mechanic is invented for it.
            w.institutions.setdefault("civil_war_settlement", {}).setdefault("autonomy", []).append(rid)
            w.event("regional_status",
                    f"{w.region(rid).name} is granted autonomy under the settlement.",
                    importance=2, region=rid)
    if terms.get("forces"):
        applied["forces"] = _apply_forces(w, current, terms["forces"])
    month = terms.get("election_date")
    if month is not None:
        w.const.election_month = month - 1
        w.const.elected = False
        w.const.handover_month = -1
        applied["election_date"] = month
        w.event("election_scheduled",
                f"The settlement schedules the next election for Month {month}.", importance=2)
    return applied


def _settlement_text(w, terms: dict) -> str:
    parts = []
    if terms.get("amnesty"):
        parts.append("a general amnesty")
    if terms.get("power_sharing"):
        parts.append("a division of offices")
    rid = terms.get("regional_autonomy")
    if rid is not None:
        parts.append(f"autonomy for {w.region(rid).name}")
    if terms.get("forces") == "integrate":
        parts.append("the integration of the forces")
    elif terms.get("forces") == "disarm":
        parts.append("the disarmament of the rebel forces")
    if terms.get("election_date"):
        parts.append(f"an election in Month {terms['election_date']}")
    return ("The government and the rebels have accepted a settlement: "
            + ", ".join(parts) + ". The war is over and the government continues.")


def _settle(w, current, offer_record, accepted_by):
    """Apply accepted terms; return ``(applied, problems)``. Nothing applies if a term is invalid."""
    terms = offer_record.get("terms") or {}
    problems = _settlement_problems(w, current, terms)
    if problems:
        offer_record["status"] = "invalid"
        offer_record["problems"] = list(offer_record.get("problems") or []) + problems
        return None, problems
    # Write down the pre-war strengths before the forces term moves any size; a checkpoint that
    # predates C4 has them only in C1's faction blocks, which the settlement rewrites.
    for name in SIDES:
        prewar_strength(w, name, current)
    applied = _apply_terms(w, current, terms)
    current["settlement"] = {
        "month": w.month, "terms": terms, "offer_id": offer_record.get("id"),
        "accepted_by": list(accepted_by), "applied": applied,
        "assigned_offices": applied.get("assigned_offices", {}),
    }
    text = _settlement_text(w, terms)
    _finish(w, current, "settled", text, terminal=False,
            extra={"terms": terms, "offer_id": offer_record.get("id"),
                   "assigned_offices": applied.get("assigned_offices", {})})
    return applied, []


# ---- C4: ceasefire --------------------------------------------------------------------------
def ceasefire_active(w) -> bool:
    """Whether a ceasefire holds, reading the same shapes as C2's ``ceasefire_active``: a dict
    with ``active`` (default true) and ``broken`` (default false), or any other truthy value."""
    current = w if isinstance(w, dict) else state(w)
    if not isinstance(current, dict):
        return False
    return _ceasefire_holds(current.get("ceasefire"))


def _ceasefire_holds(block) -> bool:
    if not block:
        return False
    if isinstance(block, dict):
        return bool(block.get("active", True)) and not bool(block.get("broken", False))
    return bool(block)


def _ceasefire_block(current) -> dict:
    block = current.get("ceasefire")
    if not isinstance(block, dict):
        block = {"active": False, "broken": False, "since": None, "offers": []}
        current["ceasefire"] = block
    block.setdefault("active", False)
    block.setdefault("broken", False)
    block.setdefault("since", None)
    block.setdefault("offers", [])
    return block


def ceasefire(w, side, accept=False):
    """Offer a ceasefire from one side, or accept the other side's offer with ``accept=True``.

    An offer alone changes no combat. A call from the other side, with or without ``accept``,
    supplies the second acceptance: the flag C2 reads is set and combat stops while it holds.
    """
    current = _live_state(w)
    if current is None:
        return _refusal("No civil war is running, or the war is already over.", kind="ceasefire")
    side_name = _normalise_side(side)
    if side_name is None:
        return _refusal(f"Unknown side: '{side}'. Use government or rebels.", kind="ceasefire")
    block = _ceasefire_block(current)
    if _ceasefire_holds(block):
        return {"ok": True, "kind": "ceasefire", "action": "already_active", "side": side_name,
                "active": True, "ceasefire": block, "problems": [], "settled": False}
    pending = [entry for entry in block["offers"] if entry.get("status") == "pending"]
    other = next((entry for entry in reversed(pending)
                  if entry.get("side") != side_name), None)
    own = next((entry for entry in reversed(pending)
                if entry.get("side") == side_name), None)
    if _truthy(accept):
        if other is None:
            return _refusal(f"No ceasefire offer from the {_other(side_name)} is waiting.",
                            kind="ceasefire")
        other["status"] = "accepted"
        other["response_month"] = w.month
        _ceasefire_on(w, block)
        return {"ok": True, "kind": "ceasefire", "action": "accepted", "side": side_name,
                "active": True, "ceasefire": block, "problems": [], "settled": False}
    if other is not None:
        # The other side offered first; this call is the second acceptance.
        other["status"] = "accepted"
        other["response_month"] = w.month
        block["offers"].append({"side": side_name, "month": w.month, "status": "accepted",
                                "response_month": w.month})
        _ceasefire_on(w, block)
        return {"ok": True, "kind": "ceasefire", "action": "accepted", "side": side_name,
                "active": True, "ceasefire": block, "problems": [], "settled": False}
    if own is not None:
        own["month"] = w.month
        return {"ok": True, "kind": "ceasefire", "action": "offered", "side": side_name,
                "active": False, "ceasefire": block, "problems": [], "settled": False}
    block["offers"].append({"side": side_name, "month": w.month, "status": "pending"})
    return {"ok": True, "kind": "ceasefire", "action": "offered", "side": side_name,
            "active": False, "ceasefire": block, "problems": [], "settled": False}


def _ceasefire_on(w, block) -> None:
    block["active"] = True
    block["broken"] = False
    block["accepted_month"] = w.month
    if block.get("since") is None:
        block["since"] = w.month
    w.event("ceasefire", "A ceasefire is in force: both sides have accepted it.", importance=2)


def refuse_ceasefire(w, side, reason=""):
    """Record a refusal of the other side's pending ceasefire offer."""
    current = _live_state(w)
    if current is None:
        return _refusal("No civil war is running, or the war is already over.", kind="ceasefire")
    side_name = _normalise_side(side)
    if side_name is None:
        return _refusal(f"Unknown side: '{side}'. Use government or rebels.", kind="ceasefire")
    block = _ceasefire_block(current)
    pending = [entry for entry in block["offers"]
               if entry.get("status") == "pending" and entry.get("side") != side_name]
    if not pending:
        return _refusal("No ceasefire offer from the other side is waiting.", kind="ceasefire")
    entry = pending[-1]
    entry["status"] = "refused"
    entry["response_month"] = w.month
    entry["reason"] = str(reason)
    return {"ok": True, "kind": "ceasefire", "action": "refused", "side": side_name,
            "offer": entry, "active": False, "ceasefire": block, "problems": [], "settled": False}


def breach(w, side, reason="attack", order=None, target=None):
    """Break a ceasefire in force and record the breach. C3 should call this when a side orders an
    attack, before combat; ``check_end`` catches an attack order as a backstop."""
    current = _live_state(w)
    if current is None:
        return _refusal("No civil war is running, or the war is already over.", kind="ceasefire")
    side_name = _normalise_side(side)
    if side_name is None:
        return _refusal(f"Unknown side: '{side}'. Use government or rebels.", kind="ceasefire")
    block = _ceasefire_block(current)
    if not _ceasefire_holds(block):
        return _refusal("No ceasefire is in force.", kind="ceasefire")
    block["active"] = False
    block["broken"] = True
    record = {"side": side_name, "month": w.month, "reason": str(reason)}
    if order is not None:
        record["order"] = order
    if target is not None:
        record["target"] = target
    block["breach"] = record
    current.setdefault("breaches", []).append(dict(record))
    w.event("ceasefire_broken", f"The {side_name} have broken the ceasefire ({reason}).",
            importance=3, detail=record)
    return {"ok": True, "kind": "ceasefire", "action": "broken", "side": side_name,
            "breach": record, "ceasefire": block, "problems": [], "settled": False}


def _break_from_orders(w, current) -> None:
    if not _ceasefire_holds(current.get("ceasefire")):
        return None
    orders = current.get("orders")
    if not isinstance(orders, dict):
        return None
    for side in SIDES:
        side_orders = orders.get(side)
        if not isinstance(side_orders, dict):
            continue
        for target, order in side_orders.items():
            if str(order).strip().lower() == "attack":
                return breach(w, side, "attack", order="attack", target=str(target))
    return None


# ---- C4: the ends ---------------------------------------------------------------------------
def _expire_offers(w, current) -> None:
    for offer_record in current.get("offers") or []:
        if (offer_record.get("kind") == "settlement"
                and offer_record.get("status") == "pending"
                and offer_record.get("month") != w.month):
            offer_record["status"] = "expired"
            offer_record["expired_month"] = w.month


def _control_signature(w, current) -> list:
    rows = [[region.id, region.controller] for region in sorted(w.regions, key=lambda r: r.id)
            if region.nation == "karamaniya"]
    rows.append(["contested", sorted(_contested_ids(current))])
    return rows


def _advance_stalemate(w, current) -> int:
    """Count the month once if no controller and no contested set changed since the last check."""
    signature = _control_signature(w, current)
    block = current.setdefault("stalemate", {"months": 0, "month": None, "signature": None})
    combat = current.get("last_combat")
    if (isinstance(combat, dict) and combat.get("month") == w.month
            and combat.get("control_changes")):
        # C2 recorded a region changing hands this month, whatever the state now says.
        block["months"] = 1
        block["signature"] = signature
        block["month"] = w.month
        return 1
    if block.get("signature") is None:
        block["months"] = 1
    elif block.get("month") == w.month:
        return int(_float(block.get("months"), 1) or 1)
    elif signature == block.get("signature"):
        block["months"] = int(_float(block.get("months"), 0) or 0) + 1
    else:
        block["months"] = 1
    block["signature"] = signature
    block["month"] = w.month
    return int(_float(block.get("months"), 0) or 0)


def _rebel_government(w, current) -> dict:
    """A rebel victory: every office is vacated and the rebels take them by faction rank."""
    from .politics import reset_bond
    rebels = sorted(_active_members(w, current, "rebels"),
                    key=lambda member: _member_rank(w, member.id))
    for office in OFFICES:
        w.const.offices[office] = None
    assigned = {}
    for member, office in zip(rebels, OFFICES):
        w.const.offices[office] = member.id
        reset_bond(w, office)
        assigned[office] = member.id
    return assigned


def _victory(w, current):
    capital = _capital_region(w)
    if capital is None:
        return None
    if capital.controller == "karamaniya":
        pre = prewar_strength(w, "rebels", current)
        if pre > 0.0 and strength(w, "rebels", current) < VICTORY_SHARE * pre:
            return ("civil_war_won_by_government",
                    "The government has won the civil war: it holds the capital and the rebel "
                    "forces are broken.", None)
    elif capital.controller == "rebels":
        pre = prewar_strength(w, "government", current)
        if pre > 0.0 and strength(w, "government", current) < VICTORY_SHARE * pre:
            assigned = _rebel_government(w, current)
            leader = ((current.get("factions") or {}).get("rebels") or {}).get("leader")
            name = w.member(leader).name if leader is not None else "The rebel leaders"
            return ("civil_war_won_by_rebels",
                    f"The rebels have won the civil war: they hold the capital and the "
                    f"government's forces are broken. {name} now heads the government.",
                    {"assigned_offices": assigned})
    return None


def _collapse(w, current):
    capital = _capital_region(w)
    if capital is not None and capital.controller in ("karamaniya", "rebels"):
        return None
    return ("no_government", "No faction holds the capital. No government remains.", None)


def _partition(w, current):
    block = current.get("stalemate") or {}
    months = int(_float(block.get("months"), 0) or 0)
    if months < PARTITION_MONTHS or not ceasefire_active(current):
        return None
    return ("partitioned",
            f"After {months} months without a front moving, and with a ceasefire holding, the "
            "two sides have accepted a partition. Karamaniya is divided.", None)


def _finish(w, current, kind: str, text: str, terminal: bool = False, extra=None) -> dict:
    """Record a war outcome. Only a terminal outcome becomes the run's outcome."""
    outcome = {"type": kind, "month": w.month, "text": text}
    if extra:
        outcome.update(extra)
    current["outcome"] = outcome
    block = current.get("ceasefire")
    if isinstance(block, dict):
        block["active"] = False
        block["broken"] = bool(block.get("broken", False))
        block["ended"] = w.month
    for pending in current.get("offers") or []:
        if pending.get("status") == "pending":
            pending["status"] = "void"
    if terminal:
        w.outcome = {"type": kind, "month": w.month, "text": text}
    w.event("civil_war", text, importance=3, detail={"result": kind, **(extra or {})})
    return outcome


def check_end(w):
    """Check the war's ends once a month; return the war's outcome record or None.

    Ends: victory (the run goes on), collapse (the run ends with ``no_government``), partition
    (the run ends with ``partitioned``). An attack order in ``w.civil_war["orders"]`` breaks a
    ceasefire first. An ended run is never given a second outcome.
    """
    if not enabled(w):
        return None
    current = state(w)
    if not isinstance(current, dict) or not current:
        return None
    if w.ended():
        return current.get("outcome") if isinstance(current.get("outcome"), dict) else None
    if current.get("outcome"):
        return current["outcome"]
    _expire_offers(w, current)
    _break_from_orders(w, current)
    _advance_stalemate(w, current)
    result = _victory(w, current)
    if result is None:
        result = _collapse(w, current)
    if result is None:
        result = _partition(w, current)
    if result is None:
        return None
    kind, text, extra = result
    return _finish(w, current, kind, text,
                   terminal=kind in ("partitioned", "no_government"), extra=extra)
