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

Combat, the faction month and negotiation are other workstreams (C2-C4). They read the state above
and update ``contested``, ``ceasefire``, ``offers`` and ``outcome``; this module does not fight.
"""
from __future__ import annotations

from .world import ARMED_OFFICES, OFFICES

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
