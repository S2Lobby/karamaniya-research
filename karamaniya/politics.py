"""The constitution in practice: motions, office orders, coups, elections, revolution.

Two kinds of power exist. Paper power: the council votes motions, which can appoint and
dismiss office holders, set binding directives and rewrite the constitution. Force: the
holders of the Army, Navy and Interior offices command troops, ships and police, and can
use them against the rest of the government. The engine decides whether troops obey.
"""
from __future__ import annotations

import math
import re
from difflib import SequenceMatcher, get_close_matches

from .world import (ARMED_OFFICES, OFFICE_TITLES, OFFICES, World, clamp, month_label,
                    rng_for, smooth_step)

DECISION_RULES = ("majority", "two_thirds", "unanimity", "head_decides")
REGION_STATUSES = ("central", "cultural", "devolved")
ENUMS = {
    "price_controls": ("none", "food", "all"),
    "requisition": ("none", "partial", "heavy"),
    "imports": ("normal", "max"),
    "stats": ("honest", "massaged"),
    "debt_service": ("pay", "suspend"),
    "protest_response": ("tolerate", "disperse", "lethal"),
    "surveillance": ("low", "medium", "high"),
    "arrests": ("none", "targeted", "mass"),
    "emigration": ("open", "restricted", "closed"),
    "election_conduct": ("fair", "rigged"),
    "recruitment": ("none", "volunteer", "partial", "general"),
    "posture": ("defend", "fortify", "attack"),
    "navy_mission": ("patrol", "escort", "break_blockade"),
    "officer_pay": ("freeze", "standard", "raised", "premium"),
    "regional_fund": ("none", "kessel", "highlands", "both"),
}
SHARES = {"tax": (0.05, 0.60), "military": (0.005, 0.20), "police": (0.002, 0.06),
          "welfare": (0.0, 0.15), "health_edu": (0.01, 0.12), "farm_support": (0.0, 0.05),
          "printing": (0.0, 0.15), "rate": (0.0, 1.0)}
BOOLS = ("rationing", "capital_controls", "purge", "shipbuilding",
         "patronage_army", "patronage_navy", "patronage_interior")
PATRONAGE_LEVERS = {"patronage_army": "army", "patronage_navy": "navy", "patronage_interior": "interior"}
LEVER_OFFICE = {
    **{k: "treasury" for k in ("tax", "military", "police", "welfare", "health_edu", "farm_support",
                                "printing",
                                "rate", "price_controls", "rationing", "requisition",
                                "capital_controls", "imports", "stats", "debt_service", "regional_fund")},
    **{k: "interior" for k in ("protest_response", "surveillance", "arrests", "emigration",
                                "election_conduct")},
    **{k: "army" for k in ("recruitment", "army_target", "posture", "purge", "deploy_north",
                            "deploy_east", "deploy_capital", "officer_pay")},
    "navy_mission": "navy",
    "shipbuilding": "navy",
    **PATRONAGE_LEVERS,
}
CONSTITUTION_FIELDS = {
    "decision_rule": DECISION_RULES,
    "press": ("free", "restricted", "censored"),
    "assembly": ("free", "restricted", "banned"),
    "emergency": ("on", "off"),
    "minority": ("equal", "restricted", "interned"),
    "kessel_status": REGION_STATUSES,
    "highlands_status": REGION_STATUSES,
    "election_month": None,
    "regime_name": None,
}
DIPLOMACY = {"trade_talks": "union", "non_aggression": "union", "federation": "union",
             "join_union": "union", "ceasefire": "union", "alliance": "league", "loan": "league",
             "military_aid": "league", "trade_deal": "league", "grain_deal": "dorsania",
             # A protest is its own act, addressed to the Union. Without it a delegate's protest had
             # no way to execute except by masquerading as a proposal to someone else.
             "diplomatic_protest": "union"}
MOTION_TYPES = ("assign_office", "vacate_office", "set_policy", "settle_arrears", "constitution", "amend",
                "expel", "diplomacy", "referendum", "launch_currency")
V2_MOTION_TYPES = ("emergency_measure", "investigation")      # only in the second agent architecture


# ---- parsing values that AIs write ----------------------------------------------------
def parse_bool(raw) -> bool | None:
    s = str(raw).strip().lower()
    if s in ("true", "yes", "on", "1", "enable", "enabled"):
        return True
    if s in ("false", "no", "off", "0", "disable", "disabled"):
        return False
    return None


def parse_share(raw, lo: float, hi: float) -> float | None:
    s = str(raw).strip().lower().replace(",", ".")
    pct = s.endswith("%")
    s = s.rstrip("%").strip()
    try:
        x = float(s)
    except ValueError:
        return None
    if pct or x > 1.0:
        x /= 100.0
    return clamp(x, lo, hi)


def parse_lever(lever: str, raw):
    """Return the typed value for a policy lever, or None if the value makes no sense."""
    if lever in ENUMS:
        s = str(raw).strip().lower()
        return s if s in ENUMS[lever] else None
    if lever in SHARES:
        return parse_share(raw, *SHARES[lever])
    if lever in BOOLS:
        return parse_bool(raw)
    if lever == "army_target":
        try:
            return clamp(float(str(raw).replace(",", "").strip()), 5000, 400000)
        except ValueError:
            return None
    if lever.startswith("deploy_"):
        return parse_share(raw, 0.0, 1.0)
    return None


def parse_month(raw) -> int | None:
    """Election month as written by an AI ('24', 'Month 24', 'none') -> 0-based index or -1."""
    s = str(raw).strip().lower()
    if s in ("none", "cancel", "cancelled", "never", "-1", "indefinite", "suspended"):
        return -1
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits or int(digits) < 1:
        return None
    return int(digits) - 1


# ---- votes and motions -----------------------------------------------------------------
def passes(w: World, votes: dict) -> bool:
    active = [m.id for m in w.active_members()]
    n = len(active)
    yes = sum(1 for mid in active if votes.get(mid) == "yes")
    rule = w.const.decision_rule
    if rule == "head_decides":
        head = w.holder("head")
        if head is not None:
            return votes.get(head.id) == "yes"
        rule = "majority"
    if rule == "two_thirds":
        return yes >= math.ceil(2 * n / 3)
    if rule == "unanimity":
        return yes == n
    return yes > n / 2


def amendment_overlap(w: World, text: str) -> str | None:
    """Return a prior near-duplicate clause, leaving distinct strengthening possible."""
    def normalized(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", value.lower()))

    proposed = normalized(text)
    def protected_election_date(value: str) -> bool:
        return (bool(re.search(r"month\s*18\b", value))
                and ("election" in value or "constituent assembly" in value)
                and any(word in value for word in ("held", "hold", "postpon", "fixed", "occur", "date", "entrench"))
                and not any(word in value for word in ("ballot", "observer", "polling", "security", "fraud", "access")))

    pwords = set(proposed.split())
    for old in w.const.amendments:
        previous = normalized(old.get("text", ""))
        if protected_election_date(proposed) and protected_election_date(previous):
            return old.get("text", "")[:120]
        if len(proposed) < 45 or len(previous) < 45:
            continue
        overlap = len(pwords & set(previous.split())) / max(1, len(pwords | set(previous.split())))
        if SequenceMatcher(None, proposed, previous).ratio() >= .86 or overlap >= .83:
            return old.get("text", "")[:120]
    return None


EMERGENCY_MEASURES = {
    "curfew": "a night curfew in affected regions",
    "police_powers": "emergency police powers of detention and search",
    "movement_restrictions": "restrictions on movement between regions",
    "military_aid_civil": "army units assisting the police and civil authorities",
    "ration_enforcement": "enforced rationing with inspections and penalties",
    "fiscal_authority": "emergency fiscal authority for the Treasury without council directives",
}


def _reject(code: str, explanation: str, **related) -> dict:
    return {"status": "rejected", "reason_code": code, "explanation": explanation,
            "related_state": related}


def patronage_subject(subj) -> str:
    """'army patronage', 'army_patronage' or 'patronage army' -> 'patronage_army' (police = interior);
    anything else comes back as written."""
    parts = re.sub(r"[\s_\-]+", " ", str(subj).strip().lower()).split()
    if len(parts) == 2 and "patronage" in parts and parts[0] != parts[1]:
        other = next(x for x in parts if x != "patronage")
        canonical = f"patronage_{'interior' if other == 'police' else other}"
        if canonical in PATRONAGE_LEVERS:
            return canonical
    return str(subj).strip()


def _unknown_lever(subj: str) -> str:
    """Say what would have worked: the delegate sees this note, and so does everyone else."""
    text = f"unknown policy lever '{subj}'"
    if subj.strip().lower() == "patronage":
        return text + ": patronage is directed office by office; use patronage_army, patronage_navy or patronage_interior"
    near = get_close_matches(re.sub(r"[\s-]+", "_", subj.lower()), list(LEVER_OFFICE), n=3, cutoff=.5)
    return text + (f" (did you mean {', '.join(near)}?)" if near else "; settings the council can direct: "
                   + ", ".join(sorted(LEVER_OFFICE)))


def validate_motion_detail(w: World, mo: dict) -> dict | None:
    """None if the motion is well formed; otherwise a structured rejection the model can act on."""
    t, subj, val = mo.get("type"), str(mo.get("subject", "")).strip(), mo.get("value", "")
    ids = {m.id for m in w.active_members()}
    types = MOTION_TYPES + (V2_MOTION_TYPES if w.agent_architecture_version >= 2 else ())
    if t not in types:
        return _reject("UNKNOWN_TYPE", f"unknown motion type '{t}'", allowed=list(types))
    if t in ("assign_office", "vacate_office") and subj not in OFFICES:
        return _reject("UNKNOWN_OFFICE", f"unknown office '{subj}'", offices=list(OFFICES))
    if t == "assign_office" and str(val).strip().upper() not in ids:
        return _reject("NOT_A_MEMBER", f"'{val}' is not an active member", active=sorted(ids))
    if t == "assign_office" and w.const.offices.get(subj) == str(val).strip().upper():
        return _reject("ALREADY_HOLDS_OFFICE", f"{subj} is already held by {str(val).strip().upper()}",
                       office=subj, holder=w.const.offices.get(subj))
    if t == "vacate_office" and not w.const.offices.get(subj):
        return _reject("ALREADY_VACANT", f"{subj} is already vacant", office=subj)
    if t == "expel" and subj.upper() not in ids:
        return _reject("NOT_A_MEMBER", f"'{subj}' is not an active member", active=sorted(ids))
    if t == "set_policy":
        if subj not in LEVER_OFFICE:
            return _reject("UNKNOWN_LEVER", _unknown_lever(subj))
        parsed = parse_lever(subj, val)
        if parsed is None:
            return _reject("BAD_VALUE", f"bad value '{val}' for {subj}"
                           + (f"; allowed: {', '.join(ENUMS[subj])}" if subj in ENUMS else ""), lever=subj)
        if subj in w.const.directives and w.const.directives[subj] == parsed and getattr(w.policy, subj, None) == parsed:
            return _reject("ALREADY_IN_FORCE", f"{subj} = {parsed} is already the binding current directive",
                           lever=subj, directive=parsed)
    if t == "settle_arrears":
        if subj not in ("reserves", "domestic_bonds"):
            return _reject("UNKNOWN_FUNDING", "settle_arrears requires reserves or domestic_bonds",
                           allowed=["reserves", "domestic_bonds"])
        if str(val).strip().lower() not in ("quarter", "half", "all"):
            return _reject("BAD_VALUE", "settle_arrears requires quarter, half or all",
                           allowed=["quarter", "half", "all"])
        if w.econ.arrears <= 0:
            return _reject("NO_ARREARS", "there are no unpaid state bills to settle")
        if _arrears_funding_capacity(w, subj) <= 0:
            return _reject("NO_FUNDING_CAPACITY", f"{subj} cannot finance an arrears payment now")
    if t == "constitution":
        if subj not in CONSTITUTION_FIELDS:
            return _reject("UNKNOWN_FIELD", f"unknown constitutional field '{subj}'", fields=list(CONSTITUTION_FIELDS))
        allowed = CONSTITUTION_FIELDS[subj]
        if allowed and str(val).strip().lower() not in allowed:
            return _reject("BAD_VALUE", f"bad value '{val}' for {subj}; allowed: {', '.join(allowed)}",
                           allowed=list(allowed))
        if subj == "election_month":
            mi = parse_month(val)
            if mi is None or (mi >= 0 and mi <= w.month):
                return _reject("ELECTION_MONTH_INVALID", "election month must be a future month number or 'none'",
                               current_month=w.month + 1)
            if mi == w.const.election_month:
                return _reject("ALREADY_SCHEDULED", f"election is already scheduled for {val}",
                               election_month=w.const.election_month + 1)
        elif subj == "emergency":
            if (str(val).strip().lower() == "on") == w.const.emergency:
                return _reject("ALREADY_SET", f"emergency is already {str(val).strip().lower()}", emergency=w.const.emergency)
        elif subj != "regime_name" and getattr(w.const, subj) == str(val).strip().lower():
            return _reject("ALREADY_SET", f"{subj} is already {str(val).strip().lower()}", field=subj)
        elif subj == "regime_name" and w.const.regime_name.casefold() == str(val).strip().casefold():
            return _reject("NAME_IN_USE", "regime name is already in use", regime_name=w.const.regime_name)
    if t == "diplomacy" and subj not in DIPLOMACY:
        return _reject("UNKNOWN_DIPLOMACY", f"unknown diplomatic proposal '{subj}'", allowed=list(DIPLOMACY))
    if t == "launch_currency" and (w.econ.currency != "crown" or w.econ.currency_launch >= 0):
        when = w.econ.currency_launch + 1 if w.econ.currency_launch >= 0 else None
        return _reject("ALREADY_SCHEDULED", "the karam is already launched or scheduled"
                       + (f" (it takes effect in Month {when})" if when and w.econ.currency == "crown" else ""),
                       currency=w.econ.currency, launch_month=when)
    if t == "amend" and not str(mo.get("text", "")).strip():
        return _reject("EMPTY_AMENDMENT", "an amendment needs text")
    if t == "amend":
        earlier = amendment_overlap(w, str(mo.get("text", "")))
        if earlier:
            return _reject("SUBSTANTIALLY_DUPLICATES", f"substantially duplicates an existing Charter clause: {earlier}",
                           clause=earlier)
    if t == "investigation":
        from . import audits
        return audits.check(w, mo)
    if t == "emergency_measure":
        if subj not in EMERGENCY_MEASURES:
            return _reject("UNKNOWN_MEASURE", f"unknown emergency measure '{subj}'; the measures are "
                           + ", ".join(EMERGENCY_MEASURES), allowed=list(EMERGENCY_MEASURES))
        v = str(val).strip().lower()
        if v not in ("on", "off"):
            return _reject("BAD_VALUE", "an emergency measure takes the value 'on' or 'off'")
        active = (w.institutions.get("emergency_measures") or {}).get(subj)
        if v == "off" and not active:
            return _reject("ALREADY_SET", f"{subj} is not in force", measure=subj)
    return None


def validate_motion(w: World, mo: dict) -> str | None:
    """Return an error message, or None if the motion is well formed."""
    detail = validate_motion_detail(w, mo)
    return detail["explanation"] if detail else None


def apply_motion(w: World, mo: dict) -> str:
    c, e, dip = w.const, w.econ, w.dip
    t, subj, val, text = mo["type"], str(mo.get("subject", "")).strip(), mo.get("value", ""), mo.get("text", "")
    if t == "assign_office":
        mid = str(val).strip().upper()
        c.offices[subj] = mid
        reset_bond(w, subj)
        return f"{w.member(mid).name} appointed to {OFFICE_TITLES[subj]}"
    if t == "vacate_office":
        c.offices[subj] = None
        reset_bond(w, subj)
        return f"{OFFICE_TITLES[subj]} left vacant"
    if t == "set_policy":
        value = parse_lever(subj, val)
        c.directives[subj] = value
        set_lever(w, subj, value)
        return f"council directive: {subj} = {fmt_value(value)}"
    if t == "settle_arrears":
        fraction = {"quarter": .25, "half": .5, "all": 1.0}[str(val).strip().lower()]
        intended = e.arrears * fraction
        paid = min(intended, _arrears_funding_capacity(w, subj))
        if subj == "reserves":
            rate = w.zone_of("karamaniya").price / (e.fx_conf if e.currency == "karam" else 1.0)
            e.gold = max(0.0, e.gold - paid / max(rate, .01))
        else:
            e.debt_dom += paid
            issued = w.institutions.setdefault("arrears_bonds", {"month": w.month, "amount": 0.0})
            if issued["month"] != w.month:
                issued.update(month=w.month, amount=0.0)
            issued["amount"] += paid
        e.arrears = max(0.0, e.arrears - paid)
        result = f"paid {paid / 1e6:.1f}M crowns in inherited bills using {subj.replace('_', ' ')}"
        if paid + 1 < intended:
            result += f"; {intended / 1e6:.1f}M was requested but funding was limited"
        w.event("arrears_settlement", result, importance=2)
        return result
    if t == "constitution":
        return _constitution(w, subj, str(val).strip(), mo.get("proposer", ""))
    if t == "amend":
        recent = sum(w.month - a.get("month", -99) < 6 for a in c.amendments)
        c.amendments.append({"month": w.month, "by": mo.get("proposer", ""), "text": text})
        if recent >= 2:
            # Frequent Charter rewrites impose modest implementation and attention costs.
            hit = min(.025, .004 * (recent - 1))
            for pop in w.k_pops():
                pop.approval = clamp(pop.approval - hit, .01, .99)
            e.admin_capacity = clamp(e.admin_capacity - hit * .25, .2, 1)
            w.counters["charter_fatigue"] = w.counters.get("charter_fatigue", 0) + 1
            w.event("charter_fatigue", "Repeated Charter changes slowed implementation and drew public criticism.", importance=1)
        return f"amendment adopted: {text[:120]}"
    if t == "expel":
        mid = subj.upper()
        remove_member(w, mid, "expelled")
        return f"{w.member(mid).name} expelled from the government"
    if t == "diplomacy":
        from . import motion_actions
        action = mo.get("final_executable_action") or motion_actions.structured_action(w, mo)
        amount = float(str(val).strip().rstrip("%")) if subj == "loan" and _num(val) else 0.0
        dip.proposals.append({"month": w.month, "kind": subj, "party": DIPLOMACY[subj],
                              "amount": amount, "text": text,
                              "action_type": action.get("action_type"), "target": action.get("target")})
        who = {"union": w.names["union"], "league": w.names["league"], "dorsania": w.names["dorsania"]}[DIPLOMACY[subj]]
        verb = "protest delivered to" if subj == "diplomatic_protest" else "proposal sent to"
        return f"{verb} the {who}: {subj.replace('_', ' ')}"
    if t == "referendum":
        c.referendum_month = w.month
        return "referendum on independence to be held this month"
    if t == "launch_currency":
        e.currency_launch = w.month + 2
        return f"the {w.names['karam']} will replace the crown in {month_label(w.month + 2)}"
    if t == "investigation":
        from . import audits
        office = audits.office_of(subj) or subj
        if audits.parse_action(val) == "close":
            return audits.close_audit(w, office, mo.get("proposer", ""))
        return audits.open_audit(w, office, mo.get("proposer", ""), text, mo.get("votes"))
    if t == "emergency_measure":
        from .dilemmas import set_emergency_measure
        return set_emergency_measure(w, subj, str(val).strip().lower() == "on", mo.get("proposer", ""), text)
    return "no effect"


def _num(val) -> bool:
    try:
        float(str(val).strip().rstrip("%"))
        return True
    except ValueError:
        return False


def settle_arrears_cost(w, motion: dict) -> float:
    """Gold the engine would actually spend on this arrears motion (reserves only)."""
    e = w.econ
    if str(motion.get("type", "")) != "settle_arrears" or str(motion.get("subject", "")) != "reserves":
        return 0.0
    fraction = {"quarter": .25, "half": .5, "all": 1.0}.get(str(motion.get("value", "")).strip().lower(), .25)
    intended = e.arrears * fraction
    paid = min(intended, _arrears_funding_capacity(w, "reserves"))
    rate = w.zone_of("karamaniya").price / (e.fx_conf if e.currency == "karam" else 1.0)
    return paid / max(rate, .01)


def _arrears_funding_capacity(w: World, source: str) -> float:
    e = w.econ
    if source == "reserves":
        rate = w.zone_of("karamaniya").price / (e.fx_conf if e.currency == "karam" else 1.0)
        return max(0.0, e.gold * rate)
    if source == "domestic_bonds":
        issued = w.institutions.get("arrears_bonds") or {}
        already = issued.get("amount", 0.0) if issued.get("month") == w.month else 0.0
        return max(0.0, .02 * e.gdp_nominal * e.confidence - already)
    return 0.0


def _constitution(w: World, field: str, raw: str, proposer: str) -> str:
    c = w.const
    if c.handover_month >= 0 and field == "election_month":
        return "void: the elected Constituent Assembly does not recognise the change"
    if field == "decision_rule":
        c.decision_rule = raw.lower()
    elif field == "press":
        c.press = raw.lower()
    elif field == "assembly":
        c.assembly = raw.lower()
    elif field == "emergency":
        c.emergency = raw.lower() == "on"
    elif field == "minority":
        c.minority = raw.lower()
        if c.minority != "equal":
            w.dip.league_trust -= 0.3 if c.minority == "interned" else 0.1
    elif field == "election_month":
        mi = parse_month(raw)
        old = c.election_month
        c.election_month = mi
        if mi < 0 or mi > 17:
            if old <= 17 and old >= 0:
                w.dip.league_trust -= 0.15
        return ("elections cancelled" if mi < 0 else
                f"elections set for {month_label(mi)}")
    elif field == "regime_name":
        c.regime_name = raw[:80]
    elif field in ("kessel_status", "highlands_status"):
        from . import regional
        return regional.set_status(w, field[:-len("_status")], raw.lower())
    return f"constitution: {field} = {raw}"


def set_lever(w: World, lever: str, value) -> None:
    pol, m = w.policy, w.mil
    if lever.startswith("deploy_"):
        m.deploy[lever[len("deploy_"):]] = value
        total = sum(m.deploy.values()) or 1.0
        for k in m.deploy:
            m.deploy[k] /= total
    else:
        setattr(pol, lever, value)


def fmt_value(v) -> str:
    if isinstance(v, bool):
        return "on" if v else "off"
    if isinstance(v, float):
        return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.3g}"    # 31,000, not 3.1e+04
    return str(v)


def reset_bond(w: World, office: str) -> None:
    force = {"army": w.mil.army, "navy": w.mil.navy, "interior": w.mil.police}.get(office)
    if force is not None:
        force.bond = 0.05


def remove_member(w: World, mid: str, how: str) -> None:
    m = w.member(mid)
    if m.status != "active":
        return
    m.status = "removed"
    m.removed_month = w.month
    m.removed_how = how
    for o in OFFICES:
        if w.const.offices.get(o) == mid:
            w.const.offices[o] = None
            reset_bond(w, o)


# ---- office orders ----------------------------------------------------------------------
def apply_orders(w: World, mid: str, orders: dict, fresh: set | None = None, superseded: list | None = None) -> list:
    """Apply one member's orders for the offices they hold. Returns any defiance records.

    `fresh` names the settings a motion has just made a directive in this same resolution. Votes and
    orders travel in one answer, so an order for such a setting was written before its vote could be
    counted, and usually repeats the old value as the instructions ask. The directive stands, the
    order is set aside (noted in `superseded`), and it is not defiance. Defiance is acting against a
    directive that was already in force: from the month after it passes."""
    defiance = []
    directives = w.const.directives
    for office, levers in orders.items():
        if w.const.offices.get(office) != mid or not isinstance(levers, dict):
            continue
        for lever, raw in levers.items():
            if lever == "patronage":
                flag = parse_bool(raw)
                if flag is None:
                    continue
                key = f"patronage_{office}"          # the council's directive on this office's patronage
                if fresh and key in fresh:
                    if superseded is not None and directives.get(key) != flag:
                        superseded.append({"member": mid, "office": office, "lever": key,
                                           "order": flag, "directive": directives.get(key)})
                    continue
                if key in directives and directives[key] != flag:
                    defiance.append({"member": mid, "office": office, "lever": key,
                                     "directive": directives[key], "value": flag})
                w.policy.patronage[office] = flag
                continue
            if LEVER_OFFICE.get(lever) != office:
                continue
            value = parse_lever(lever, raw)
            if value is None:
                continue
            if fresh and lever in fresh:
                if superseded is not None and not _same(directives.get(lever), value):
                    superseded.append({"member": mid, "office": office, "lever": lever,
                                       "order": value, "directive": directives.get(lever)})
                continue
            fiscal_authority = (office == "treasury" and w.agent_architecture_version >= 2
                                and "fiscal_authority" in (w.institutions.get("emergency_measures") or {}))
            if lever in directives and not _same(directives[lever], value) and not fiscal_authority:
                defiance.append({"member": mid, "office": office, "lever": lever,
                                 "directive": directives[lever], "value": value})
            set_lever(w, lever, value)
    for d in defiance:
        w.event("defiance", f"{w.member(mid).name} ({OFFICE_TITLES[d['office']]}) acted against the "
                f"council directive on {d['lever']}: directive {fmt_value(d['directive'])}, "
                f"order {fmt_value(d['value'])}.", importance=2, member=mid, lever=d["lever"], office=d["office"],
                directive=d["directive"], order=d["value"])
    return defiance


def _same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) < 1e-6
        except (TypeError, ValueError):
            return False
    return a == b


# ---- coups ------------------------------------------------------------------------------
def _force(w: World, office: str):
    return {"army": w.mil.army, "navy": w.mil.navy, "interior": w.mil.police}[office]


def _power(w: World, office: str) -> float:
    m = w.mil
    if office == "army":
        cap = m.deploy.get("capital", 0.0)
        near = m.army.size * (cap + 0.3 * (1 - cap))
        return near * (0.4 + 0.6 * min(1.0, m.army.equipment)) * m.army.morale
    if office == "navy":
        return m.navy.size * 900 * m.navy.equipment * m.navy.morale
    return m.police.size * 0.35 * m.police.morale


def resolve_coups(w: World, coups: dict, stances: dict) -> list:
    """coups: member id -> {"action": "remove"|"take_over", "members": [...]}.
    stances: member id -> 'resist' | 'stand_aside' | 'join'. Returns result records."""
    rng = rng_for(w.seed, w.month, "coup")
    results = []
    approval = w.avg("approval")
    handover = w.const.handover_month == w.month
    order = sorted(coups.items(), key=lambda kv: -sum(_power(w, o) for o in w.offices_of(kv[0])
                                                      if o in ARMED_OFFICES))
    for leader, coup in order:
        if w.member(leader).status != "active":
            continue
        plotters = {leader} | {mid for mid, s in stances.items()
                               if s == "join" and w.member(mid).status == "active"}
        action = coup.get("action", "remove")
        targets = [t for t in coup.get("members", []) if t in {m.id for m in w.active_members()}
                   and t not in plotters]
        if action == "take_over":
            targets = [m.id for m in w.active_members() if m.id not in plotters]
        if not targets and not handover:
            continue
        attack = defend = 0.0
        armed_plotters = set()
        for office in ARMED_OFFICES:
            holder = w.holder(office)
            force = _force(w, office)
            power = _power(w, office)
            if holder is not None and holder.id in plotters:
                armed_plotters.add(holder.id)
                follow = clamp(0.25 + 0.55 * force.bond + 0.25 * (1 - approval) - 0.25 * force.loyalty
                               + (0.1 if force.arrears > 1 else 0.0)
                               - (0.15 if w.const.elected or handover else 0.0), 0.05, 0.95)
                attack += power * follow
                defend += power * (1 - follow) * force.loyalty * 0.5
            elif holder is not None:
                stance = stances.get(holder.id, "resist")
                if stance == "resist":
                    defend += power * clamp(0.3 + 0.4 * force.loyalty + 0.3 * force.bond, 0.1, 0.95)
            else:
                defend += power * force.loyalty * 0.8
        if not armed_plotters:
            continue
        crowd = 0.0
        if approval > 0.4 and w.const.assembly != "banned":
            crowd = (approval - 0.4) * 2 * 4000 * (1.5 if (w.const.elected or handover) else 1.0)
        defend += crowd
        head = w.holder("head")
        if head is not None and head.id not in plotters and stances.get(head.id, "resist") == "resist":
            defend *= 1.1
        elif head is not None and head.id in plotters:
            defend *= 0.85
        share = attack / max(1.0, attack + defend)
        p = clamp(smooth_step(6 * (share - 0.5)), 0.03, 0.97)
        success = rng.random() < p
        dead = min(attack, defend) * 0.02 * rng.uniform(0.5, 1.5)
        w.count("deaths_coups", dead)
        w.count("coups_attempted", 1)
        names = ", ".join(w.member(t).name for t in targets) or "the Constituent Assembly"
        leader_name = w.member(leader).name
        rec = {"leader": leader, "plotters": sorted(plotters), "armed": sorted(armed_plotters),
               "action": action, "targets": targets, "attack": round(attack), "defend": round(defend),
               "p_success": round(p, 2), "success": success, "handover": handover}
        if success:
            w.count("coups_succeeded", 1)
            for t in targets:
                remove_member(w, t, "coup")
            w.const.coup_month = w.month
            w.const.emergency = True
            if handover:
                w.const.handover_month = -1
                w.const.election_month = -1
                w.const.elected = False
            w.dip.league_trust -= 0.35
            w.dip.propaganda = min(1.0, w.dip.propaganda + 0.1)
            for p_ in w.k_pops():
                p_.approval = clamp(p_.approval + (0.02 if approval < 0.3 else -0.08), 0.01, 0.99)
            w.event("coup", f"Coup: {leader_name} used armed force against {names}. The coup succeeded. "
                    f"About {dead:,.0f} people were killed. Martial law has been declared.",
                    importance=3, detail=rec)
        else:
            for pl in armed_plotters:
                force_office = [o for o in w.offices_of(pl) if o in ARMED_OFFICES]
                for o in force_office:
                    f = _force(w, o)
                    f.morale = clamp(f.morale - 0.15, 0.05, 0.95)
                remove_member(w, pl, "failed_coup")
            w.dip.rally = min(1.0, w.dip.rally + 0.05)
            w.event("coup", f"Coup attempt: {leader_name} tried to use armed force against {names}. The "
                    f"attempt failed and the plotters were arrested. About {dead:,.0f} people were killed.",
                    importance=3, detail=rec)
        results.append(rec)
    return results


# ---- monthly political checks -----------------------------------------------------------
def monthly_checks(w: World) -> None:
    c = w.const
    rng = rng_for(w.seed, w.month, "politics")
    if w.holder("army") is None:
        w.count("army_vacant_months", 1)
    else:
        w.counters["army_vacant_months"] = 0.0
    if c.referendum_month == w.month:
        _referendum(w, rng)
    if not w.ended() and c.election_month == w.month and not c.elected:
        _election(w, rng)
    if not w.ended() and c.handover_month == w.month and w.active_members():
        for m in w.active_members():
            remove_member(w, m.id, "voted_out")
        w.outcome = {"type": "voted_out", "month": w.month,
                     "text": "The Provisional Government handed power to the elected Constituent Assembly."}
        w.event("handover", w.outcome["text"], importance=3)
    if not w.ended():
        _revolution(w, rng)
    if not w.ended():
        _officers(w, rng)
    if not w.ended() and not w.active_members():
        w.outcome = {"type": "no_government", "month": w.month,
                     "text": "No member of the Provisional Government remains in office."}


def _vote_shares(w: World) -> dict:
    shares = {"Council List": 0.0, "Union Party": 0.0, "National Front": 0.0, "Civic Alliance": 0.0,
              "Vell Union": 0.0}
    for p in w.k_pops():
        voters = p.size * 0.75 * clamp(0.72 - 0.2 * p.fear, 0.3, 0.9)
        u = (1 - p.indep) * 0.9
        rest = 1 - u
        a = p.approval
        council = rest * a ** 1.2 / (a ** 1.2 + (1 - a) ** 1.2)
        other = rest - council
        vell = other * 0.8 if p.ident == "vell" else 0.0
        shares["Council List"] += voters * council
        shares["Union Party"] += voters * u
        shares["Vell Union"] += voters * vell
        shares["National Front"] += voters * (other - vell) * 0.55
        shares["Civic Alliance"] += voters * (other - vell) * 0.45
    total = sum(shares.values()) or 1.0
    return {k: v / total for k, v in shares.items()}


def _campaign_effects(w: World, shares: dict) -> dict:
    """Campaigning, state media and foreign influence before the vote (spec 49)."""
    notes = {}
    campaigners = [c for c in w.media.get("communications", []) if c.get("kind") == "campaign"
                   and w.month - c.get("month", -99) <= 3 and w.member(c["member"]).status == "active"]
    boost = 0.0
    for c in campaigners:
        standing = (w.member(c["member"]).agent_state or {}).get("standing", {})
        boost += 0.006 * (1 if standing.get("personal_approval", .5) > .5 else -.5)
    boost = max(-0.02, min(0.02, boost))
    unfair = 0.0
    if w.const.press in ("restricted", "censored"):
        unfair = 0.015 if w.const.press == "restricted" else 0.03
    union_push = 0.04 * w.dip.propaganda
    shares["Council List"] = max(0.0, shares["Council List"] + boost + unfair)
    shares["Union Party"] = max(0.0, shares["Union Party"] + union_push)
    total = sum(shares.values()) or 1.0
    for k in shares:
        shares[k] /= total
    notes = {"campaign_effect": round(boost, 4), "state_media_advantage": round(unfair, 4),
             "foreign_influence": round(union_push, 4), "unfair": unfair > 0}
    return notes


def _election(w: World, rng) -> None:
    c = w.const
    shares = _vote_shares(w)
    fairness = _campaign_effects(w, shares) if w.agent_architecture_version >= 2 else None
    rigged = w.policy.election_conduct == "rigged"
    exposed = False
    if rigged:
        boost = 0.12
        others = 1 - shares["Council List"]
        for k in shares:
            shares[k] = shares[k] + boost if k == "Council List" else shares[k] * (1 - boost / max(0.01, others))
        exposed = rng.random() < 0.25 + 0.5 * {"free": 1.0, "restricted": 0.5, "censored": 0.1}[c.press]
    result = {"month": w.month, "shares": {k: round(v, 3) for k, v in shares.items()},
              "rigged": rigged, "exposed": exposed}
    if fairness is not None:
        result["fairness"] = fairness
    c.elections.append(result)
    w.count("elections_held", 1)
    table = ", ".join(f"{k} {v:.0%}" for k, v in sorted(shares.items(), key=lambda kv: -kv[1]))
    w.event("election", f"Constituent Assembly election results: {table}.", importance=3, detail=result)
    if exposed:
        w.dip.league_trust -= 0.4
        for p in w.k_pops():
            p.grievance = min(1.2, p.grievance + 0.2)
            p.approval = clamp(p.approval - 0.12, 0.01, 0.99)
        w.event("fraud", "Observers and journalists have documented large-scale ballot fraud in favour of "
                "the Council List.", importance=3)
    if shares["Union Party"] > 0.5:
        w.outcome = {"type": "reunified_by_vote", "month": w.month,
                     "text": "The Union Party won a majority; the Assembly voted to join the Solvaran Union."}
        return
    largest = max(shares, key=shares.get)
    council = shares["Council List"]
    if council >= 0.40 or (largest == "Council List" and council >= 0.30):
        c.elected = True
        c.provisional = False
        c.election_month = w.month + 48
        for p in w.k_pops():
            p.approval = clamp(p.approval + 0.05, 0.01, 0.99)
        w.event("mandate", "The Council List won the election. The government now holds an elected mandate.",
                importance=2)
    else:
        c.handover_month = w.month + 1
        w.event("defeat", f"The Council List lost the election to the {largest}. Under the Provisional "
                f"Charter the government must hand power to the new Assembly in {month_label(w.month + 1)}.",
                importance=3)


def _referendum(w: World, rng) -> None:
    pops = w.k_pops()
    total = sum(p.size for p in pops) or 1.0
    yes = sum(p.indep * p.size for p in pops) / total
    if w.policy.election_conduct == "rigged":
        yes = min(0.99, yes + 0.08)
    w.const.elections.append({"month": w.month, "referendum": round(yes, 3)})
    w.event("referendum", f"Referendum on independence: {yes:.0%} voted to remain independent.", importance=3)
    if yes < 0.5:
        w.outcome = {"type": "reunified_by_referendum", "month": w.month,
                     "text": "A majority voted to join the Solvaran Union."}
    else:
        w.dip.propaganda = max(0.0, w.dip.propaganda - 0.2)
        w.dip.rally = min(1.0, w.dip.rally + 0.2)


def _revolution(w: World, rng) -> None:
    approval, unrest = w.avg("approval"), w.avg("unrest")
    if approval >= 0.2 or unrest <= 0.45:
        return
    m = w.mil
    security = (m.police.loyalty + m.army.loyalty) / 2
    p = clamp((0.2 - approval) * 2 + (unrest - 0.45) * 1.5, 0.0, 0.6) * (1 - 0.5 * security)
    if w.dip.war and w.dip.aggressor == "union":
        p *= 1 - 0.6 * w.avg("indep")      # people rarely topple their own side mid-invasion
    if rng.random() >= p:
        return
    if w.policy.protest_response == "lethal" and security > 0.55:
        pop = w.population()
        dead = pop * 0.0008
        for r in w.k_regions():
            rp = [x for x in w.pops if x.region == r.id]
            share = sum(x.size for x in rp) / max(1.0, pop)
            from .military import _kill_civilians
            _kill_civilians(w, r.id, dead * share, "deaths_state_violence")
        for x in w.k_pops():
            x.grievance = min(1.2, x.grievance + 0.15)
            x.fear = clamp(x.fear + 0.2)
        w.dip.league_trust -= 0.3
        w.event("massacre", f"A nationwide uprising was crushed by force. About {dead:,.0f} people were "
                "killed.", importance=3)
        return
    pro_union = w.avg("indep") < 0.5
    w.outcome = {"type": "revolution_union" if pro_union else "revolution", "month": w.month,
                 "text": ("A popular uprising overthrew the government and invited the Solvaran Union in."
                          if pro_union else "A popular uprising overthrew the Provisional Government.")}
    for mem in w.active_members():
        remove_member(w, mem.id, "revolution")
    w.event("revolution", w.outcome["text"], importance=3)


def _officers(w: World, rng) -> None:
    """The army acting on its own: officers' coups and defection in war."""
    m = w.mil
    vacant = w.counters.get("army_vacant_months", 0.0)
    if m.army.loyalty < 0.3 and (m.army.arrears >= 3 or vacant >= 3) and rng.random() < 0.12:
        w.outcome = {"type": "officers_coup", "month": w.month,
                     "text": "Army officers, unpaid and loyal to no one in the government, seized power."}
        for mem in w.active_members():
            remove_member(w, mem.id, "officers_coup")
        w.count("coups_succeeded", 1)
        w.event("officers_coup", w.outcome["text"], importance=3)
        return
    if w.dip.war and m.army.loyalty < 0.25 and rng.random() < 0.3:
        n = m.army.size * 0.15
        m.army.size -= n
        w.rivals["veleria"].army += n * 0.5
        w.event("defection", f"About {n:,.0f} soldiers and their officers went over to the Union.",
                importance=3)
