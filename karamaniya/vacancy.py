"""Office vacancy authority patch (parallel-safe, additive).

Separation doctrine encoded here:

- office holder (``world.const.offices`` + member ``status``) is distinct from
- standing / operational orders (``world.institutions['operations']`` and any
  caller-held order records) which are distinct from
- council directives (``world.const.directives``) which are distinct from
- actual world state (``world.policy``, ``world.mil.deploy``, ...).

Rules: deployments / operational state survive removal; a conflicting
standing order never overrides a council directive; a removed holder loses
order authority immediately but retains delegate identity.
"""
from __future__ import annotations

from .world import ARMED_OFFICES, OFFICES

VACANCY_LOG_KEY = "vacancy_log"

POLITICAL_PREFERENCE = "POLITICAL_PREFERENCE"
EXECUTABLE_OFFICE_PLAN = "EXECUTABLE_OFFICE_PLAN"
PRE_REMOVAL_ORDER = "PRE_REMOVAL_ORDER"

_OCCUPIED = "occupied"
_VACANT = "vacant"


def _member_id(member):
    if member is None:
        return None
    mid = getattr(member, "id", member)
    try:
        s = str(mid).strip()
    except Exception:
        return None
    return s.upper() if s else None


def _check_office(office: str) -> str:
    o = str(office)
    if o not in OFFICES:
        raise ValueError(f"unknown office '{office}'")
    return o


def _is_active(world, mid) -> bool:
    if not mid:
        return False
    try:
        m = world.member(str(mid))
    except Exception:
        return False
    return getattr(m, "status", None) == "active"


def _log(world) -> dict:
    inst = getattr(world, "institutions", None)
    if not isinstance(inst, dict):
        return {}
    existing = inst.get(VACANCY_LOG_KEY)
    if not isinstance(existing, dict):
        existing = {}
        inst[VACANCY_LOG_KEY] = existing
    return existing


def vacancy_state_for(world, office: str) -> dict:
    """Canonical vacancy state. Reads const.offices; writes vacancy_log only."""
    o = _check_office(office)
    log = _log(world)
    entry = log.get(o)
    if not isinstance(entry, dict):
        entry = {}
        if isinstance(getattr(world, "institutions", None), dict):
            log[o] = entry
    try:
        offices = world.const.offices
        raw = offices.get(o) if isinstance(offices, dict) else None
    except Exception:
        raw = None
    month = int(getattr(world, "month", 0) or 0)
    active = _is_active(world, raw) if raw is not None else False
    if active:
        holder = str(raw)
        former = entry.get("former_holder")
        entry["holder"] = holder
        if "former_holder" not in entry:
            entry["former_holder"] = None
            former = None
        entry["vacant_since"] = None
        entry["status"] = _OCCUPIED
        return {"office": o, "holder": holder, "former_holder": former,
                "vacant_since": None, "status": _OCCUPIED,
                "interim_appointment_required": False, "continuity_risk": "none"}
    prev_holder = entry.get("holder")
    if entry.get("vacant_since") is None:
        if raw is not None and not active:
            former_holder = str(raw)
        elif isinstance(prev_holder, str) and prev_holder:
            former_holder = prev_holder
        else:
            former_holder = entry.get("former_holder")
        if former_holder is None:
            # Read-only fallback: last recorded operator of this office.
            try:
                ops = (world.institutions.get("operations") or {}).get(o) or {}
                by = ops.get("by")
                if isinstance(by, str) and by:
                    former_holder = by
            except Exception:
                pass
        entry["holder"] = None
        entry["former_holder"] = former_holder
        entry["vacant_since"] = month
        entry["status"] = _VACANT
    else:
        if entry.get("former_holder") is None and raw is not None and not active:
            entry["former_holder"] = str(raw)
        entry["holder"] = None
        entry["status"] = _VACANT
    risk = _risk_for_vacant(o)
    return {"office": o, "holder": None, "former_holder": entry.get("former_holder"),
            "vacant_since": entry.get("vacant_since"), "status": _VACANT,
            "interim_appointment_required": True, "continuity_risk": risk}


def can_issue_orders(world, member, office: str) -> bool:
    """False for a removed holder; true only for the active canonical holder."""
    try:
        o = str(office)
    except Exception:
        return False
    if o not in OFFICES:
        return False
    mid = _member_id(member)
    if not mid:
        return False
    try:
        offices = world.const.offices
        canonical = offices.get(o) if isinstance(offices, dict) else None
    except Exception:
        return False
    if canonical is None or str(canonical) != mid:
        return False
    return _is_active(world, mid)


def label_pre_removal_orders(orders, removal_month) -> list:
    """Copies of orders; those with month < removal_month get PRE_REMOVAL_ORDER."""
    try:
        cutoff = int(removal_month)
    except Exception:
        cutoff = 0
    src = orders if isinstance(orders, list) else []
    out = []
    for item in src:
        if not isinstance(item, dict):
            continue
        copy = dict(item)
        try:
            m = int(copy.get("month", 0))
        except Exception:
            m = 0
        if m < cutoff:
            copy["label"] = PRE_REMOVAL_ORDER
        out.append(copy)
    return out


def continuity_requirements(world, office: str) -> dict:
    """Continuity needs; deployments preserved; standing orders never win."""
    o = _check_office(office)
    state = vacancy_state_for(world, o)
    if state["status"] == _VACANT:
        requirements = ["appoint_interim_holder",
                        "preserve_deployments_and_operational_state",
                        "council_directives_prevail_over_standing_orders"]
        if o in ARMED_OFFICES:
            requirements.append("monitor_force_loyalty_and_arrears")
        if o == "head":
            requirements.append("maintain_coordination_and_messaging")
        if o == "treasury":
            requirements.append("maintain_fiscal_operations")
    else:
        requirements = ["no_action_required"]
    return {"office": o, "status": state["status"], "holder": state["holder"],
            "former_holder": state["former_holder"], "vacant_since": state["vacant_since"],
            "interim_appointment_required": state["interim_appointment_required"],
            "continuity_risk": state["continuity_risk"], "requirements": requirements,
            "deployments_preserved": True, "standing_orders_override_directives": False}


def note_kind_for_member(world, member) -> str:
    """POLITICAL_PREFERENCE when member holds no office, else EXECUTABLE_OFFICE_PLAN."""
    mid = _member_id(member)
    if not mid:
        return POLITICAL_PREFERENCE
    try:
        m = world.member(mid)
    except Exception:
        return POLITICAL_PREFERENCE
    if getattr(m, "status", None) != "active":
        return POLITICAL_PREFERENCE
    try:
        held = world.offices_of(mid)
    except Exception:
        held = []
    if held:
        return EXECUTABLE_OFFICE_PLAN
    return POLITICAL_PREFERENCE


def _risk_for_vacant(office: str) -> str:
    if office in ARMED_OFFICES:
        return "high"
    return "medium"
