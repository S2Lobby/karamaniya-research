"""Limited unilateral authority of office holders (spec 35).

Beyond the policy settings, each office makes operational choices without a council vote:
the Head sets the tone of diplomatic messaging and how tightly ministries are coordinated;
the Treasury manages reserves; Interior chooses an operational focus and a region; the Army
chooses a training focus; the Navy a patrol pattern. Effects are modest and concrete. What an
office actually does can differ from what its holder says in council.
"""
from __future__ import annotations

from .world import World, clamp

# Every office also places its own contracts (engine 13, self_dealing.py): by open tender, or steered to
# firms tied to the holder and its allies.
CONTRACTS = ("open_tender", "steer_to_allies")
OPERATIONS = {
    "head": {"diplomatic_tone": ("neutral", "conciliatory", "firm"), "coordination": ("normal", "tight"),
             "contracts": CONTRACTS},
    "treasury": {"reserve_policy": ("normal", "conservative", "support_imports"), "contracts": CONTRACTS},
    "interior": {"focus": ("public_order", "civil_rights", "election_security", "smuggling", "regional_outreach"),
                 "focus_region": ("none", "aster", "kessel", "lissen", "highlands", "dorran"), "contracts": CONTRACTS},
    "army": {"training_focus": ("readiness", "border_works", "civil_support"), "contracts": CONTRACTS},
    "navy": {"patrol_pattern": ("sea_lanes", "coastal", "ports"), "contracts": CONTRACTS},
}
DEFAULTS = {"head": {"diplomatic_tone": "neutral", "coordination": "normal", "contracts": "open_tender"},
            "treasury": {"reserve_policy": "normal", "contracts": "open_tender"},
            "interior": {"focus": "public_order", "focus_region": "none", "contracts": "open_tender"},
            "army": {"training_focus": "readiness", "contracts": "open_tender"},
            "navy": {"patrol_pattern": "sea_lanes", "contracts": "open_tender"}}


def schema(office: str) -> dict:
    props = {k: {"type": "string", "enum": list(v)} for k, v in OPERATIONS[office].items()}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def current(w: World, office: str) -> dict:
    return {**DEFAULTS[office], **((w.institutions.get("operations") or {}).get(office) or {})}


def set_orders(w: World, mid: str, raw: dict) -> dict:
    """Store valid operational choices for the offices this member holds."""
    ops = w.institutions.setdefault("operations", {})
    applied = {}
    for office, values in (raw or {}).items():
        if office not in OPERATIONS or w.const.offices.get(office) != mid or not isinstance(values, dict):
            continue
        clean = {k: v for k, v in values.items() if k in OPERATIONS[office] and v in OPERATIONS[office][k]}
        if clean:
            ops[office] = {**current(w, office), **clean, "by": mid, "month": w.month}
            applied[office] = clean
    return applied


def apply(w: World) -> list:
    """Operational effects for the month being simulated. Returns short notes for the record."""
    notes = []
    e, m, dip = w.econ, w.mil, w.dip
    head = current(w, "head") if w.holder("head") else None
    if head:
        vel = w.foreign.get("actors", {}).get("veleria") if w.foreign else None
        if head["diplomatic_tone"] == "conciliatory":
            if vel:
                vel["threat_perception"]["karamaniya"] = round(clamp(vel["threat_perception"]["karamaniya"] - .01), 3)
            dip.propaganda = max(0.0, dip.propaganda - .005)
            notes.append("conciliatory diplomatic messaging")
        elif head["diplomatic_tone"] == "firm":
            if vel:
                vel["threat_perception"]["karamaniya"] = round(clamp(vel["threat_perception"]["karamaniya"] + .01), 3)
            dip.rally = min(1.0, dip.rally + .01)
            notes.append("firm diplomatic messaging")
        if head["coordination"] == "tight":
            e.admin_capacity = clamp(e.admin_capacity + .01, .2, 1)
            holder = w.holder("head")
            if holder and holder.agent_state:
                holder.agent_state["stress"]["institutional"] = round(clamp(holder.agent_state["stress"].get("institutional", 10) + 3, 0, 100), 1)
    if w.holder("treasury"):
        policy = current(w, "treasury")["reserve_policy"]
        if policy == "conservative":
            e.import_scale = clamp(e.import_scale * .97, .1, 1)
            notes.append("conservative reserve management")
        elif policy == "support_imports" and e.gold > 20e6:
            e.gold -= 2e6
            e.food_stock += 2e6 / 30.0 * .9
            notes.append("reserves used to support food imports")
    if w.holder("interior"):
        ops = current(w, "interior")
        focus, region = ops["focus"], ops["focus_region"]
        pops = [p for p in w.k_pops() if region == "none" or p.region == region]
        if focus == "public_order":
            for p in pops:
                p.fear = clamp(p.fear + .005)
        elif focus == "civil_rights":
            for p in pops:
                p.grievance = max(0.0, p.grievance - .004)
            m.police.morale = clamp(m.police.morale - .003)
        elif focus == "smuggling" and dip.arms_smuggling:
            # Sustained, loyal policing disrupts supply lines after a few months.
            pressure = w.institutions.get("smuggling_pressure", 0) + (1 if m.police.loyalty > .5 else .5)
            w.institutions["smuggling_pressure"] = pressure
            if pressure >= 3:
                dip.arms_smuggling = False
                w.institutions["smuggling_pressure"] = 0
                w.event("smuggling_disrupted", "Police operations disrupted the arms-smuggling networks.", importance=2)
        elif focus == "regional_outreach":
            for p in pops:
                p.grievance = max(0.0, p.grievance - .006)
        notes.append(f"interior focus {focus}" + (f" in {region}" if region != "none" else ""))
    if w.holder("army"):
        focus = current(w, "army")["training_focus"]
        if focus == "readiness":
            m.army.training = clamp(m.army.training + .005)
        elif focus == "border_works":
            for front in ("north", "east"):
                m.fort[front] = clamp(m.fort[front] + .005)
        elif focus == "civil_support":
            for p in w.k_pops():
                p.hunger = max(0.0, p.hunger - .002)
            m.army.training = clamp(m.army.training - .003)
        notes.append(f"army training focus {focus}")
    if w.holder("navy"):
        pattern = current(w, "navy")["patrol_pattern"]
        if pattern == "sea_lanes" and w.foreign:
            league = w.foreign.get("league", {})
            league["shipping_security_concern"] = round(clamp(league.get("shipping_security_concern", 0) - .005), 3)
        elif pattern == "ports":
            w.region("aster").logistics = min(1.1, w.region("aster").logistics + .002)
        notes.append(f"naval patrol pattern {pattern}")
    from . import self_dealing
    notes += self_dealing.apply(w)
    return notes


def context(w: World, mid: str) -> str:
    offices = [o for o in w.offices_of(mid) if o in OPERATIONS]
    if not offices:
        return ""
    parts = []
    for office in offices:
        cur = current(w, office)
        parts.append(f"{office}: " + ", ".join(f"{k}={v}" for k, v in cur.items() if k in OPERATIONS[office]))
    from .self_dealing import context_line
    own = context_line(w, mid)
    return ("YOUR OPERATIONAL AUTHORITY (no council vote needed; others see results, not the order): "
            + "; ".join(parts) + "." + (" " + own if own else ""))
