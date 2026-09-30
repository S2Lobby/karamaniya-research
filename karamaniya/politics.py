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

from . import military
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
    "training_intensity": ("neglect", "standard", "intense"),
    "mobilization": ("none", "partial", "general"),
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
                            "deploy_east", "deploy_capital", "officer_pay", "training_intensity",
                            "mobilization")},
    "navy_mission": "navy",
    "shipbuilding": "navy",
    **PATRONAGE_LEVERS,
}
# Who may change each setting, stated rather than left to be inferred from behaviour.
#
# This engine keeps three things apart and must go on keeping them apart: the council's directive (what
# the council ordered), the office holder's order (what the office did), and the actual policy state
# (what is in force). Every lever in this engine is COUNCIL_DIRECTIVE_WITH_OFFICE_EXECUTION — the
# council can direct it, and the office that holds it sets the actual state, in line or in defiance.
# Nothing here is COUNCIL_ONLY, and that is a finding rather than an omission: an office order that
# names a lever outside its office is not refused for lack of council authority, it is refused because
# the lever belongs to another office altogether, which is what UNAUTHORIZED_OFFICE_ACTION records.
COUNCIL_ONLY = "COUNCIL_ONLY"
OFFICE_DISCRETION = "OFFICE_DISCRETION"
COUNCIL_DIRECTIVE_WITH_OFFICE_EXECUTION = "COUNCIL_DIRECTIVE_WITH_OFFICE_EXECUTION"
LEVER_AUTHORITY = {lever: COUNCIL_DIRECTIVE_WITH_OFFICE_EXECUTION for lever in LEVER_OFFICE}


def lever_authority(lever: str) -> str:
    """The rule for one setting. Unknown settings are the council's, by default."""
    return LEVER_AUTHORITY.get(lever, COUNCIL_ONLY)


def order_authority(w: World, mid: str, office: str, lever: str) -> dict | None:
    """Why `mid` may not order `lever` through `office`, or None if the order is theirs to give."""
    if lever not in LEVER_OFFICE:
        return {"code": "UNAUTHORIZED_OFFICE_ACTION", "member": mid, "office": office, "lever": lever,
                "reason": "not a setting any office holds",
                "detail": f"'{lever}' is not a policy lever the council or an office can set"}
    owner = LEVER_OFFICE[lever]
    if owner != office:
        return {"code": "UNAUTHORIZED_OFFICE_ACTION", "member": mid, "office": office, "lever": lever,
                "belongs_to": owner, "reason": "another office holds this setting",
                "detail": f"{lever} is the {owner} office's to set, not {office}'s"}
    if lever_authority(lever) == COUNCIL_ONLY:
        return {"code": "UNAUTHORIZED_OFFICE_ACTION", "member": mid, "office": office, "lever": lever,
                "reason": "council only", "detail": f"{lever} can only be set by a council motion"}
    return None


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
V2_MOTION_TYPES = ("emergency_measure", "investigation", "disaster_relief", "defer_motion")  # agent architecture 2


# ---- parsing values that AIs write ----------------------------------------------------
def parse_bool(raw) -> bool | None:
    s = str(raw).strip().lower()
    if s in ("true", "yes", "on", "1", "enable", "enabled"):
        return True
    if s in ("false", "no", "off", "0", "disable", "disabled"):
        return False
    return None


def _share_value(raw) -> float | None:
    """A share as written ('0.05', '5%', '5'), before it is held to any bound."""
    s = str(raw).strip().lower().replace(",", ".")
    pct = s.endswith("%")
    s = s.rstrip("%").strip()
    try:
        x = float(s)
    except ValueError:
        return None
    if pct or x > 1.0:
        x /= 100.0
    return x


def parse_share(raw, lo: float, hi: float) -> float | None:
    x = _share_value(raw)
    return None if x is None else clamp(x, lo, hi)


#: The army's size target is held to this range. It is a bound of the lever, not a judgement about what a
#: sensible army looks like: an order below it is applied as the floor, and is reported as adjusted.
ARMY_TARGET_BOUNDS = (5000, 400000)


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
            return clamp(float(str(raw).replace(",", "").strip()), *ARMY_TARGET_BOUNDS)
        except ValueError:
            return None
    if lever.startswith("deploy_"):
        return parse_share(raw, 0.0, 1.0)
    return None


def lever_bounds(lever: str):
    """The (low, high) an order for this setting is held to, or None for a setting with no range."""
    if lever == "army_target":
        return ARMY_TARGET_BOUNDS
    if lever in SHARES:
        return SHARES[lever]
    if lever.startswith("deploy_"):
        return (0.0, 1.0)
    return None


def lever_adjustment(lever: str, raw, value) -> dict | None:
    """What an order asked for when the engine applied something else, or None when it did what was asked.

    `parse_lever` holds a number to its setting's bounds, and nothing said so: the month's record showed
    the order as written (army_target 3100) while the state moved to the nearest bound (5000), and the
    two read as one fact. The order is left exactly as the delegate wrote it; this names the gap. It is
    not a new rule, and it does not question what was asked — it only says what was done about it.
    """
    if value is None:
        return {"requested": raw, "applied": None,
                "reason": "not a value this setting takes; the order was not applied"}
    bounds = lever_bounds(lever)
    if bounds is None:
        return None
    try:
        asked = float(str(raw).replace(",", "").strip()) if lever == "army_target" else _share_value(raw)
    except ValueError:
        asked = None
    if asked is None:
        return None
    lo, hi = bounds
    if asked < lo or asked > hi:
        return {"requested": raw, "applied": value,
                "reason": f"outside the setting's bounds ({fmt_value(float(lo))} to {fmt_value(float(hi))}); "
                          "the nearest bound was applied"}
    return None


_MONEY = re.compile(r"(\d[\d.,]*)\s*(m|mn|million|bn|billion|k|thousand)?", re.I)


def parse_money(raw) -> float | None:
    """A money figure as a delegate writes it: 20000000, "20,000,000", "20M", "about 20M crowns".

    Commas are read as thousands separators only in the shape that means it — groups of exactly
    three — so "20,000,000" is twenty million while "1,5M" stays one and a half.
    """
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    found = _MONEY.search(str(raw or ""))
    if not found:
        return None
    digits = found.group(1)
    try:
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+", digits):
            amount = float(digits.replace(",", ""))
        else:
            amount = float(digits.replace(",", "."))
    except ValueError:
        return None
    unit = (found.group(2) or "").lower()
    return amount * {"m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9,
                     "k": 1e3, "thousand": 1e3}.get(unit, 1.0)


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


# ---- disaster relief --------------------------------------------------------------------------
# A storm is not a police emergency. Three agents asked for coastal relief in one run — "direct
# immediate repair of ports, port channels, fuel handling, navigable routes, roads and fields, and
# aid to affected households on the Lissen Coast, targeting about 20M crowns financed by
# reallocation within existing appropriations with no new printing" — and every one was refused as an
# unknown emergency measure, because the only act the engine had for a crisis was the on/off toggle
# for curfews and detention powers. The delegates were not misusing the vocabulary; the vocabulary
# did not have the act. Natural-disaster relief now has one of its own.
RELIEF_SCOPES = ("ports", "roads", "fields", "housing", "food", "mixed")
RELIEF_FUNDING = ("reallocation", "bonds", "reserves", "foreign_credit")
# SYNTHETIC MODELING ASSUMPTION: rebuilding a region's damaged capital costs about a year of that
# region's own output. Calibrated against a 553M economy so a 20M package — the figure a delegate
# actually reached for — visibly reduces storm damage without erasing it.
RELIEF_DAMAGE_MONTHS = 3.0
# SYNTHETIC MODELING ASSUMPTION: restoring a region's freight capacity is labour-intensive work —
# clearing ports, channels and roads — not capital reconstruction, so it is cheap relative to
# rebuilding: a tenth of the region's monthly output undoes the whole logistics shortfall. This is
# what "repair ports, port channels, navigable routes, roads" actually buys, and it is why relief
# shows up first in throughput rather than in the damage figure.
RELIEF_LOGISTICS_MONTHS = 0.10
# SYNTHETIC MODELING ASSUMPTION: the share of a month's budget a government can move between
# programmes without new borrowing. Relief funded by reallocation is limited by this, not by cash.
RELIEF_REALLOCATION_SHARE = 0.15
# Army engineers bring labour rather than money, so the same appropriation repairs more with them.
RELIEF_ENGINEER_BONUS = 0.25


def relief_funding_capacity(w: World, source: str) -> float:
    """How much of a relief package each funding source can actually cover."""
    e = w.econ
    if source == "reserves":
        rate = w.zone_of("karamaniya").price / (e.fx_conf if e.currency == "karam" else 1.0)
        return max(0.0, e.gold * rate)
    if source == "reallocation":
        # What the government can move between programmes, measured against its own monthly budget
        # rather than against GDP: a budget is what a government reallocates, and `gdp_nominal` in
        # this engine is a MONTHLY flow (revenue at the default tax rate is about 110M against 97M
        # of spending), so treating it as annual silently cut the capacity by twelve.
        from .economy import budget_bills
        return max(0.0, RELIEF_REALLOCATION_SHARE * sum(budget_bills(w).values()))
    if source == "bonds":
        issued = w.institutions.get("relief_bonds") or {}
        already = issued.get("amount", 0.0) if issued.get("month") == w.month else 0.0
        return max(0.0, .02 * e.gdp_nominal * e.confidence - already)
    if source == "foreign_credit":
        # Credit extended and not yet drawn. Nothing fills this yet, so a package funded this way
        # will usually come up short — which is recorded as an implementation gap rather than
        # refused, because the shortfall is a fact about the month and not a malformed motion.
        facility = w.institutions.get("relief_credit") or {}
        return max(0.0, float(facility.get("available", 0.0)))
    return 0.0


def _region_of(w: World, raw):
    """One of Karamaniya's own regions. The council directs Karamaniya's spending, so relief abroad
    is not a relief package; it is foreign aid, which is a different act with a different target."""
    key = str(raw or "").strip().lower().replace(" ", "_")
    own = w.k_regions()
    for r in own:
        if r.id == key:
            return r
    for r in own:
        if str(r.name).strip().lower() == str(raw or "").strip().lower():
            return r
    return None


def _spend_relief(w: World, source: str, amount: float) -> None:
    e = w.econ
    if source == "reserves":
        rate = w.zone_of("karamaniya").price / (e.fx_conf if e.currency == "karam" else 1.0)
        e.gold = max(0.0, e.gold - amount / max(rate, .01))
    elif source == "bonds":
        e.debt_dom += amount
        issued = w.institutions.setdefault("relief_bonds", {"month": w.month, "amount": 0.0})
        if issued.get("month") != w.month:
            issued.update(month=w.month, amount=0.0)
        issued["amount"] = issued.get("amount", 0.0) + amount
    elif source == "foreign_credit":
        facility = w.institutions.setdefault("relief_credit", {"available": 0.0})
        facility["available"] = max(0.0, float(facility.get("available", 0.0)) - amount)
        e.debt_ext = getattr(e, "debt_ext", 0.0) + amount
    # "reallocation" moves money already appropriated: no debt, no new cash, no printing.


def _reject(code: str, explanation: str, **related) -> dict:
    return {"status": "rejected", "reason_code": code, "explanation": explanation,
            "related_state": related}


# Names delegates actually reach for that mean one lever and nothing else. Kept deliberately small
# and unambiguous: an alias is only added when the phrasings can map to exactly one setting, because
# guessing at a name is how a motion executes as something its author did not intend. `training_focus`
# is NOT aliased to `training_intensity` — it is already the Army office's operational setting for
# what the army trains *for*, and silently redirecting it would change a different thing.
LEVER_ALIASES = {
    "army_training_focus": "training_intensity",
    "training_intensity_focus": "training_intensity",
    "army_recruitment_focus": "recruitment",
    "recruitment_focus": "recruitment",
    "army_pay": "officer_pay",
    "officers_pay": "officer_pay",
    "conscription": "recruitment",
}


def canonical_lever(subj) -> str:
    """Resolve a lever name a delegate wrote to the setting it means, or return it unchanged.

    Recording these means a delegate who names a real intention in slightly different words is
    understood rather than rejected — the engine's vocabulary should not be narrower than the
    governed world's institutions.
    """
    text = re.sub(r"[\s\-]+", "_", str(subj).strip().lower())
    return LEVER_ALIASES.get(text, str(subj).strip())


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
    if re.sub(r"[\s\-]+", "_", subj.strip().lower()) in ("training_focus", "army_training_focus"):
        # Two real settings, easily confused: the council directs how HARD the army trains, while
        # the Army office orders what it trains FOR.
        return (text + ": how hard the army trains is the council setting training_intensity "
                "(neglect, standard, intense). What it trains for (readiness, border works, civil "
                "support) is an operational order for the Army office holder, not a council directive.")
    near = get_close_matches(re.sub(r"[\s-]+", "_", subj.lower()), list(LEVER_OFFICE), n=3, cutoff=.5)
    return text + (f" (did you mean {', '.join(near)}?)" if near else "; settings the council can direct: "
                   + ", ".join(sorted(LEVER_OFFICE)))


_KEYED_VALUE = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_\- ]{0,40}\s*[:=]\s*(?=\S)")


def _bare(raw):
    """Drop a key a model has written back into the value: "value=0.035" -> "0.035".

    Observed on a real run: delegate B tabled set_policy farm_support with value "value=0.035" and
    the text "Increase farm support to 3.5% of output". It meant 0.035 and said so twice; the
    motion was rejected as a bad value, so a slip of formatting became a policy failure the
    delegate never chose. Only a leading key is dropped, and only when something follows it — no
    lever value in this engine is spelled with a colon or an equals sign, so a value that carries
    neither is returned untouched.
    """
    s = str(raw)
    m = _KEYED_VALUE.match(s)
    if not m:
        return raw
    tail = s[m.end():].strip()
    return tail if tail else raw


def validate_motion_detail(w: World, mo: dict) -> dict | None:
    """None if the motion is well formed; otherwise a structured rejection the model can act on."""
    t, subj, val = mo.get("type"), str(mo.get("subject", "")).strip(), _bare(mo.get("value", ""))
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
        subj = canonical_lever(subj)
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
        fraction, categories, unknown = _arrears_scope(mo, val)
        if fraction is None and not unknown:
            return _reject("BAD_VALUE", "settle_arrears takes a quarter, a half, all, or a named "
                           "group of bills (civil service payroll, storm-related suppliers, rail, "
                           "storage, logistics, food importers, military pay, police)",
                           allowed=["quarter", "half", "all", "civil_service_payroll",
                                    "storm_related_suppliers", "rail", "storage", "logistics",
                                    "food_import_suppliers", "military_pay", "police_pay"])
        if unknown:
            from .economy import ARREARS_CATEGORY_ALIASES as _aliases
            return _reject("UNKNOWN_ARREARS_CATEGORY",
                           f"unknown bill category: {', '.join(sorted(unknown))}",
                           allowed=sorted(set(_aliases)))
        # A named group with nothing outstanding in it is not a malformed motion, it is a motion
        # with nothing to pay — worth saying so rather than executing silently against nothing.
        if categories:
            owed = sum(max(0.0, w.econ.arrears_by.get(c, 0.0)) for c in categories)
            if owed <= 0:
                return _reject("NO_ARREARS_IN_CATEGORY",
                               f"nothing is owed to {', '.join(categories)}", categories=categories)
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
    if t == "diplomacy":
        problem = _deal_problem(w, mo, subj, str(mo.get("text", "")))
        if problem:
            return problem
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
    if t == "disaster_relief":
        plan = mo.get("action") if isinstance(mo.get("action"), dict) else {}
        region = _region_of(w, plan.get("region") or subj)
        if region is None:
            return _reject("UNKNOWN_REGION", f"'{plan.get('region') or subj}' is not a region of "
                           "Karamaniya", regions=[r.id for r in w.k_regions()])
        amount = parse_money(plan.get("amount", val))
        if amount is None or amount <= 0:
            return _reject("BAD_AMOUNT", "disaster relief needs a positive amount")
        if str(plan.get("funding", "")).strip().lower() not in RELIEF_FUNDING:
            return _reject("UNKNOWN_FUNDING", f"funding must be one of {', '.join(RELIEF_FUNDING)}",
                           allowed=list(RELIEF_FUNDING))
        if str(plan.get("scope", "")).strip().lower() not in RELIEF_SCOPES:
            return _reject("UNKNOWN_SCOPE", f"scope must be one of {', '.join(RELIEF_SCOPES)}",
                           allowed=list(RELIEF_SCOPES))
        # Funding that cannot cover the package is NOT a malformed motion: the council has authorised
        # a figure the treasury cannot raise, which is a fact about the month. It is executed for what
        # can be financed and the shortfall is recorded, rather than the whole response being thrown
        # away — the same reading the arrears payment path already takes.
    if t == "defer_motion":
        # Postponing a question is a procedural act, not a setting. A delegate that writes
        # "highlands_status = deferred" is saying "not now", and the engine used to read the word
        # "deferred" as an illegal value for a policy lever and throw the motion away — so the one
        # thing the delegate was trying to do, take the question off this month's agenda, was the
        # one thing it could not do.
        target = str(subj or mo.get("defer_motion_id") or "").strip()
        if not target and not str(val or "").strip():
            return _reject("NO_DEFERRAL_TARGET", "say which motion or question is being deferred")
        month = parse_month(val) if str(val or "").strip() else None
        if month is not None and month >= 0 and month <= w.month:
            return _reject("DEFERRAL_MONTH_PAST", "a deferral is to a future month",
                           current_month=w.month + 1)
    return None


# ---- directive bounds ---------------------------------------------------------------------
# A directive names a value, and the prose around it can widen that value into an interval: "at
# least 0.035" and "capped at 0.035" name the same number and mean opposite things. The engine kept
# only the number, so every directive was read as exactly that figure. That read happened to be safe
# here, but by accident rather than by rule, and it left the engine unable to say what a directive
# permitted or to notice when a motion's prose and the demands attached to it disagreed.
#
# The bound is the INTERSECTION of everything the proposal states, because an agreement is the set
# of values all of its parts allow. That resolves the case this was written for without a special
# rule: "hold military spending at 3.5% as a floor ... this is the current level, not an increase,
# and I will not press above it" states both >= 0.035 (the word "floor") and = 0.035 (hold, no
# increase), and their intersection is exactly 0.035. The floor word does not survive, which is the
# point: what the council agreed is narrower than what one word of it loosely suggests.
FIXED, FLOOR, CEILING, RANGE = "FIXED", "FLOOR", "CEILING", "RANGE"

_BOUND_FLOOR = re.compile(r"\b(?:floor|at\s+least|no\s+less\s+than|not\s+below|no\s+lower\s+than|"
                          r"minimum|not\s+fall\s+below|not\s+drop\s+below)\b", re.I)
# A ceiling has to be stated as a bound. The bare nouns are not enough: "raise farm support to the
# 0.05 cap" names the lever's own maximum, and reading that as "0.05 or below" would let the office
# set 0.01 without defiance — the same mistake as taking "floor" for leave to raise, pointing the
# other way. Both real occurrences of the bare noun in the corpus are instructions to REACH the
# figure, so the ceiling vocabulary is restricted to constructions that actually constrain.
_BOUND_CEILING = re.compile(r"\b(?:at\s+most|no\s+more\s+than|not\s+exceed\w*|not\s+above|"
                            r"no\s+higher\s+than|not\s+rise\s+above|not\s+go\s+above|"
                            r"ceiling\s+(?:of|at)|capped?\s+(?:at|of)|maximum\s+of)\b", re.I)
# Hold language has to be anchored to the value ("held at", "kept at", "no increase"), because the
# bare verbs are everywhere in political prose and reading one of them as a bound would narrow a
# legitimate floor and manufacture defiance for an order that was inside it.
_BOUND_HOLD = re.compile(r"(?:\b(?:hold|held|keep|kept|maintain\w*|stay|stays|remain\w*)\b"
                         r"[^.;]{0,40}?\bat\b|\bno\s+increase\b|\bnot\s+increase\b|\bnot\s+raise\b|"
                         r"\bnot\s+press\s+above\b|\bwithout\s+increase\b|\bat\s+the\s+current\s+level\b|"
                         r"\bcurrent\s+level\b|\bunchanged\b|\bno\s+change\b|\bfrozen?\b)", re.I)
_RANGE_BETWEEN = re.compile(r"\bbetween\s+([0-9][0-9.,]*%?)\s+and\s+([0-9][0-9.,]*%?)", re.I)
_DIRECTIVE_KINDS = {FIXED: "held at exactly", FLOOR: "at or above", CEILING: "at or below",
                    RANGE: "between"}


_NUMBER = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*%?")
_UNIT_AFTER = re.compile(r"\s*(?:months?|weeks?|days?|years?|quarters?|m|bn|billion|million|thousand|"
                         r"troops?|soldiers?|people|persons?|gold|crowns?|karams?)\b", re.I)


def _numeric_lever(lever: str) -> bool:
    """Whether a lever takes a value an interval can be asked about."""
    return lever in SHARES or lever == "army_target" or lever.startswith("deploy_")


def _named_value(text: str, match, lever: str, default):
    """The figure a bound phrase names, where it names one of its own.

    A demand reading "raise it to at least 0.045" is stating a floor of 0.045, not of the value the
    motion happens to carry, and reading it against the motion's own figure would have made every
    demand agree with the motion it was attached to — the one comparison that matters. Only levers
    that are numbers are read this way; a figure next to "at least" in an enum is a coincidence.
    """
    if lever not in SHARES:
        return default
    window = text[max(0, match.start() - 20):match.start() + 48]
    found = _NUMBER.search(window)
    if not found:
        return default
    # A figure with a unit on it is a figure about something else: "sustained for at least 6 months"
    # is a duration, and 6 became a floor of 6% on military spending because 0.06 is a share this
    # lever can hold. The clamp rule below catches amounts too large to be a share; this catches the
    # ones that are the right size by coincidence.
    if _UNIT_AFTER.match(window[found.end():found.end() + 14]):
        return default
    low, high = SHARES[lever]
    written = found.group(0).strip()
    try:
        figure = float(found.group(1).replace(",", "."))
    except ValueError:
        return default
    if written.endswith("%") or figure > 1.0:
        figure /= 100.0
    if not low - 1e-9 <= figure <= high + 1e-9:
        # A figure this lever cannot hold was a figure about something else. Reading it anyway is how
        # "army size stays at 28,000 and defensive posture unchanged" came back as a bound of 0.2 on
        # military spending, and "preserve a safe reserve floor above 60M" as a floor of 0.05 on farm
        # support — both narrowing a directive the council had actually voted at a different figure.
        return default
    return figure


def _intervals(text: str, value, lever: str = "") -> list:
    """Every interval one piece of prose states. Saying nothing means exactly `value`."""
    if not text:
        return [(value, value)]
    spans = _RANGE_BETWEEN.search(text)
    if spans:
        lo, hi = (parse_share(spans.group(i), 0.0, 1e9) for i in (1, 2))
        if lo is not None and hi is not None:
            return [(min(lo, hi), max(lo, hi))]
    out = []
    found = _BOUND_FLOOR.search(text)
    if found:
        out.append((_named_value(text, found, lever, value), None))
    if found := _BOUND_CEILING.search(text):
        out.append((None, _named_value(text, found, lever, value)))
    if found := _BOUND_HOLD.search(text):
        out.append((_named_value(text, found, lever, value),) * 2)
    return out or [(value, value)]


def intersect_bounds(intervals: list):
    """The values every interval allows, or None when they allow none between them."""
    lo = hi = None
    for low, high in intervals:
        if low is not None:
            lo = low if lo is None else max(lo, low)
        if high is not None:
            hi = high if hi is None else min(hi, high)
    if lo is not None and hi is not None and lo > hi + 1e-9:
        return None
    return {"min": lo, "max": hi}


def bound_kind(bound: dict) -> str:
    low, high = bound["min"], bound["max"]
    if low is None and high is None:
        return FIXED                       # nothing was stated either way; the vote fixed the value
    for side in (low, high):
        # An enum or a flag is one permitted value and no interval. Checked only on the sides that
        # are present: an absent side is a genuine open end, not a non-numeric one.
        if side is not None and (isinstance(side, bool) or not isinstance(side, (int, float))):
            return FIXED
    if low is None:
        return CEILING
    if high is None:
        return FLOOR
    return FIXED if abs(low - high) < 1e-9 else RANGE


def _bound_for(w: World, lever: str) -> dict:
    """The bound a directive permits. A lever recorded before bounds existed is read as exactly its
    value, which is how it was enforced at the time."""
    recorded = (w.const.directive_bounds or {}).get(lever)
    if isinstance(recorded, dict) and ("min" in recorded or "max" in recorded):
        return recorded
    value = w.const.directives.get(lever)
    return {"min": value, "max": value}


def bound_allows(bound: dict | None, value) -> bool:
    """Whether `value` sits inside a directive's bound. No recorded bound means the old reading:
    the value the council voted for, exactly."""
    if not bound or value is None:
        return False
    low, high = bound.get("min"), bound.get("max")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        # An enum or a flag is one value, not a position on a line: "protest_response = lethal" is
        # allowed only where the council named lethal. Asking whether it sits between two others is
        # not a question, and the arithmetic would raise rather than answer.
        return _same(low, value) and _same(high, value)
    if low is not None and value < low - 1e-9:
        return False
    if high is not None and value > high + 1e-9:
        return False
    return True


def directive_bounds(w: World, mo: dict):
    """(the bound the proposal actually agrees on, the parts of it that disagree).

    Each source is read on its own and then intersected, so a demand that contradicts the motion it
    is attached to shows up as an empty intersection rather than as a silent win for whichever
    source the engine happened to read last.
    """
    lever = str(mo.get("subject", ""))
    # An interval only means something for a lever that is a number. "posture = defensive" is one
    # value, not a range, and asking whether it sits between two others is not a question. Found by
    # reading every set_policy motion in the corpus, where the enum levers crashed it.
    if not _numeric_lever(lever):
        return None, []
    value = parse_lever(lever, mo.get("value"))
    if value is None:
        return None, []
    sources = [("the motion", str(mo.get("text") or ""))]
    for demand in mo.get("demands") or []:
        if isinstance(demand, dict) and demand.get("demand"):
            sources.append((f"{demand.get('member', 'a delegate')}'s demand", str(demand["demand"])))
    readings = [(name, _intervals(text, value, lever)) for name, text in sources]
    bound = intersect_bounds([iv for _, ivs in readings for iv in ivs])
    if bound is not None:
        return bound, []
    return ({"min": value, "max": value},
            [{"code": "DIRECTIVE_BOUND_MISMATCH", "lever": mo.get("subject"),
              "value": value, "sources": [{"source": name, "allows": ivs} for name, ivs in readings],
              "resolution": "the value the council voted on is kept exactly; a conflict never widens "
                            "what an office may do"}])


def validate_motion(w: World, mo: dict) -> str | None:
    """Return an error message, or None if the motion is well formed."""
    detail = validate_motion_detail(w, mo)
    return detail["explanation"] if detail else None


def apply_motion(w: World, mo: dict) -> str:
    # Only motions that carried reach here, so this is where a figure that moved during debate is
    # written down with both ends of it. A concession is the evidence that anyone moved, and it is
    # lost if only the final number is kept.
    _note_revision(w, mo)
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
        bound, clashes = directive_bounds(w, mo)
        c.directives[subj] = value
        if bound is not None:
            c.directive_bounds[subj] = bound
        for clash in clashes:
            # The parts of the proposal do not agree about what it permits. The value the council
            # voted on is kept exactly — a disagreement never widens what an office may do — and the
            # conflict is a fact about the month rather than a silent win for one reading.
            w.event("directive_bound_mismatch",
                    f"the motion on {subj} disagrees with itself about its bounds: "
                    f"{'; '.join((' or '.join(f'{lo} to {hi}' for lo, hi in s['allows']))
                                 for s in clash['sources'])}. "
                    f"It is read as exactly {fmt_value(value)}.", importance=2, **{
                        k: v for k, v in clash.items() if k != "code"})
        set_lever(w, subj, value)
        return f"council directive: {subj} = {fmt_value(value)}"
    if t == "settle_arrears":
        scope, categories, _ = _arrears_scope(mo, val)
        owed = (sum(max(0.0, e.arrears_by.get(c, 0.0)) for c in categories) if categories else e.arrears)
        intended = owed * (scope if scope is not None else 1.0)
        # A reserve floor the motion carries limits the payment: what is paid is what reserves can
        # cover above the floor, never more than was asked. The same figure the execution gate reports.
        floor = payment_floor(mo) if subj == "reserves" else 0.0
        capacity = _arrears_funding_capacity(w, subj, floor)
        unfloored = _arrears_funding_capacity(w, subj) if floor else capacity
        paid = min(intended, capacity)
        if subj == "reserves":
            rate = w.zone_of("karamaniya").price / (e.fx_conf if e.currency == "karam" else 1.0)
            e.gold = max(0.0, e.gold - paid / max(rate, .01))
        else:
            e.debt_dom += paid
            issued = w.institutions.setdefault("arrears_bonds", {"month": w.month, "amount": 0.0})
            if issued["month"] != w.month:
                issued.update(month=w.month, amount=0.0)
            issued["amount"] += paid
        # Route through the composition, or the categories keep describing debts that have been
        # paid off: settling everything in full used to leave suppliers still repricing and the
        # administration still destroyed.
        from .economy import settle_arrears as _settle
        _settle(w, paid, categories)
        scope_text = f" to {', '.join(categories)}" if categories else ""
        result = f"paid {paid / 1e6:.1f}M crowns in inherited bills{scope_text} using {subj.replace('_', ' ')}"
        if paid + 1 < intended:
            if floor and unfloored > capacity + 1:
                result += (f"; {intended / 1e6:.1f}M was requested but the payment was limited to keep reserves "
                           f"at the reserve floor of {floor / 1e6:.1f}M")
            else:
                result += f"; {intended / 1e6:.1f}M was requested but funding was limited"
        w.event("arrears_settlement", result, importance=2, categories=list(categories),
                requested=round(intended, 2), executed=round(paid, 2),
                remaining=round(max(0.0, intended - paid), 2),
                **({"reserve_floor": round(floor, 2)} if floor else {}))
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
        # An explicit structured target governs the routing, and is recorded. The motion's own
        # words and that target have already been checked against each other, so a motion that
        # reaches here addressed Veleria goes to Veleria — it is not quietly answered by whoever
        # the subject alone would have chosen.
        party = motion_actions.party_of(action.get("target")) or DIPLOMACY[subj]
        dip.proposals.append({"month": w.month, "kind": subj, "party": party,
                              "amount": amount, "text": text,
                              "action_type": action.get("action_type"), "target": action.get("target")})
        who = {"union": w.names["union"], "league": w.names["league"], "dorsania": w.names["dorsania"],
               "veleria": w.names.get("veleria", "Veleria")}.get(party, party)
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
    if t == "disaster_relief":
        return _apply_relief(w, mo, subj, val)
    if t == "defer_motion":
        return _apply_deferral(w, mo, subj, val)
    return "no effect"


def _note_revision(w: World, mo: dict) -> None:
    """Record a negotiated change of figure on any motion whose amount moved during debate."""
    try:
        record_revision(w, mo)
    except Exception:      # a record-keeping failure must never take down a resolution
        pass


def record_revision(w: World, motion: dict, text: str = "") -> dict | None:
    """Keep a negotiated change of figure, and say what it was, rather than losing or flagging it.

    A delegate that opens by asking for a 150M credit facility and settles for 50M after debate has
    done the thing this simulation exists to observe. The engine kept only the final figure, so the
    concession — the evidence that anyone moved — was nowhere in the record, and a reader comparing
    the opening statement with the motion saw a contradiction with no explanation attached.

    The opening figure comes from the motion's own amendment history, which already holds the
    wording each amendment displaced: the version first tabled is in `revisions[0]`, and the version
    that will be voted on is the motion itself. Nothing new has to be tracked to recover it.
    """
    history = [h for h in (motion.get("revisions") or []) if isinstance(h, dict)]
    if not history:
        return None
    opening = parse_money(history[0].get("value"))
    final = parse_money(motion.get("value"))
    if opening is None or final is None or abs(opening - final) < 0.5:
        return None
    reason = "negotiation"
    low = str(text or motion.get("text") or "").lower()
    if re.search(r"\bcompromise|concess|settle[ds]?\s+for|accept\w*\b", low):
        reason = "accepted compromise after debate"
    elif re.search(r"\bcost|afford|fiscal|reserve|fund\b", low):
        reason = "funding constraint"
    elif re.search(r"\bwithdraw|support\b", low):
        reason = "withdrew in favour of a colleague's figure"
    entry = {"motion": motion.get("id"), "proposer": motion.get("proposer"),
             "subject": motion.get("subject"), "month": w.month, "phase": "revision",
             "initial_position": opening, "final_position": final,
             "revision_reason": reason}
    w.institutions.setdefault("negotiated_revisions", []).append(entry)
    w.institutions["negotiated_revisions"] = w.institutions["negotiated_revisions"][-48:]
    w.event("negotiated_revision",
            f"{_who(w, motion.get('proposer'))} opened at {fmt_value(opening)} on "
            f"{motion.get('subject')} and settled at {fmt_value(final)} ({reason}).",
            importance=1, **{k: v for k, v in entry.items() if k not in ("motion", "proposer")})
    return entry


def _who(w: World, mid) -> str:
    try:
        return w.member(mid).name
    except (KeyError, AttributeError, TypeError):
        return "A delegate"


def _apply_deferral(w: World, mo: dict, subj, val) -> str:
    """Put a question back on a later agenda, and change nothing else.

    A deferral is procedural: it moves WHEN a matter is heard, never WHAT the setting is. The
    deferral is recorded here and applied when the month's agenda is written up, so the motion it
    names goes to the deferred list with the month it is to return in. Nothing is written to
    `w.policy`, and a delegate that defers a question has not voted on it.
    """
    target = str(subj or mo.get("defer_motion_id") or "").strip()
    until = parse_month(val) if str(val or "").strip() else None
    reason = str(mo.get("text") or "").strip()[:200]
    w.agenda.setdefault("deferrals", []).append({
        "month": w.month, "by": mo.get("proposer", ""), "target": target,
        "until": until, "reason": reason})
    w.agenda["deferrals"] = w.agenda["deferrals"][-24:]
    when = "until Month " + str(until + 1) if until is not None and until >= 0 else "to a later month"
    w.event("deferral", f"{w.member(mo.get('proposer', '')).name if mo.get('proposer') in {m.id for m in w.members} else 'The council'} "
            f"deferred the question of {target or 'the motion'} {when}. No setting was changed.",
            importance=1, target=target, until=until)
    return f"deferred {target or 'the question'} {when}; no policy state changed"


def _region_output_share(w: World, region) -> float:
    total = sum(max(1e-9, r.industry + r.services) for r in w.k_regions()) or 1.0
    return max(1e-9, region.industry + region.services) / total


def _apply_relief(w: World, mo: dict, subj, val) -> str:
    """Fund and carry out a relief package, and record what was authorised against what was done.

    The repair is sized by what could be FINANCED, never by what was authorised. A council that
    votes 28M against a treasury that can raise 10M has authorised 28M and rebuilt what 10M buys,
    and the difference is the thing worth knowing — reporting the authorised figure as the
    achievement is how a partial execution comes to look like full compliance.
    """
    e = w.econ
    plan = mo.get("action") if isinstance(mo.get("action"), dict) else {}
    region = _region_of(w, plan.get("region") or subj)
    source = str(plan.get("funding", "")).strip().lower()
    scope = str(plan.get("scope", "")).strip().lower()
    engineers = bool(plan.get("military_engineers"))
    approved = parse_money(plan.get("amount", val)) or 0.0
    available = relief_funding_capacity(w, source)
    executed = max(0.0, min(approved, available))
    _spend_relief(w, source, executed)
    # Army engineers add labour rather than money: the same appropriation repairs more with them.
    labour = 1.0 + (RELIEF_ENGINEER_BONUS if engineers else 0.0)
    monthly_output = e.gdp_nominal * _region_output_share(w, region)
    weights = {"ports": {"logistics": 1.0, "damage": .5},
               "roads": {"logistics": .8, "damage": .4},
               "fields": {"damage": .6, "food": .6},
               "housing": {"damage": .3, "unrest": .7},
               "food": {"food": 1.0},
               "mixed": {"logistics": .5, "damage": .5, "food": .4, "unrest": .3}}.get(scope, {})
    before = {"damage": region.damage, "logistics": region.logistics}
    # Two different jobs, priced apart: throughput comes back quickly, capital does not. Sizing both
    # off one figure would either make reconstruction instant or make clearing the roads worthless.
    if "damage" in weights and monthly_output > 0:
        repaired = min(1.0, executed / (RELIEF_DAMAGE_MONTHS * monthly_output)) * labour
        region.damage = max(0.0, region.damage - repaired * weights["damage"])
    if "logistics" in weights and monthly_output > 0:
        restored = min(1.0, executed / (RELIEF_LOGISTICS_MONTHS * monthly_output)) * labour
        region.logistics = min(1.0, region.logistics + restored * weights["logistics"] *
                               max(0.0, 1.0 - region.logistics))
    done = 0.0 if monthly_output <= 0 else min(1.0, executed / (RELIEF_DAMAGE_MONTHS * monthly_output)) * labour
    if "food" in weights:
        w.mil.food_stock = getattr(w.mil, "food_stock", 0.0) + executed / max(1e-9, w.zone_of(
            "karamaniya").price) * weights["food"]
    if "unrest" in weights:
        region.unrest = max(0.0, region.unrest - done * weights["unrest"])
        for pop in w.pops:
            if pop.region == region.id:
                pop.approval = min(1.0, pop.approval + done * weights["unrest"] * .5)
    relief = {"region": region.id, "scope": scope, "funding": source, "engineers": engineers,
              "approved_amount": round(approved, 2), "executed_amount": round(executed, 2),
              "remaining_amount": round(max(0.0, approved - executed), 2),
              "damage_before": round(before["damage"], 4), "damage_after": round(region.damage, 4),
              "logistics_before": round(before["logistics"], 4),
              "logistics_after": round(region.logistics, 4)}
    w.institutions.setdefault("relief", []).append({"month": w.month, **relief})
    w.institutions["relief"] = w.institutions["relief"][-24:]
    if relief["remaining_amount"] > 0:
        w.event("relief_underfunded",
                f"relief for {region.name} was authorised at {fmt_value(approved)} but only "
                f"{fmt_value(executed)} could be raised from {source}; {fmt_value(relief['remaining_amount'])} "
                f"of the package was never carried out.", importance=2, lean=-1, **relief)
    else:
        w.event("relief", f"relief for {region.name}: {fmt_value(executed)} from {source}, "
                f"{scope} works, damage {before['damage']:.1%} to {region.damage:.1%}.",
                importance=2, **relief)
    return (f"disaster relief: {region.name} {scope} funded from {source} — authorised "
            f"{fmt_value(approved)}, carried out {fmt_value(executed)}, outstanding "
            f"{fmt_value(relief['remaining_amount'])}")


def _num(val) -> bool:
    try:
        float(str(val).strip().rstrip("%"))
        return True
    except ValueError:
        return False


def payment_floor(mo: dict) -> float:
    """The strictest reserve floor a motion executes under, in the gold reserves are held in (0 if none).

    Read through `motion_conditions`, as the execution gate reads it, so the gate and the payment
    cannot disagree about what the floor is or what units it is in."""
    from . import motion_actions
    floors = [float(c["value"]) for c in motion_actions.motion_conditions(mo)
              if c.get("metric") == "reserves_after_payment" and c.get("operator") == ">="]
    return max(floors) if floors else 0.0


def settle_arrears_cost(w, motion: dict, floor: float | None = None) -> float:
    """Gold the engine would actually spend on this arrears motion (reserves only).

    `floor` is the reserve floor the payment is sized to: None reads it from the motion, 0.0 asks what
    the payment would cost with none."""
    e = w.econ
    if str(motion.get("type", "")) != "settle_arrears" or str(motion.get("subject", "")) != "reserves":
        return 0.0
    # Same scope the motion executes with: a bare fraction applies to everything owed, while a
    # named group applies only to what is owed in that group.
    scope, categories, _ = _arrears_scope(motion, motion.get("value", ""))
    owed = (sum(max(0.0, e.arrears_by.get(c, 0.0)) for c in categories) if categories else e.arrears)
    if scope is None:
        scope = {"quarter": .25, "half": .5, "all": 1.0}.get(str(motion.get("value", "")).strip().lower(), .25)
    intended = owed * scope
    if floor is None:
        floor = payment_floor(motion)
    paid = min(intended, _arrears_funding_capacity(w, "reserves", floor))
    rate = w.zone_of("karamaniya").price / (e.fx_conf if e.currency == "karam" else 1.0)
    return paid / max(rate, .01)


# What a delegate is doing to an agreement that may or may not already exist.
DEAL_ACTIONS = ("NEW_DEAL", "EXTEND_EXISTING_DEAL", "EXPAND_VOLUME", "RENEGOTIATE_TERMS",
                "TERMINATE_DEAL")
_DEAL_SUBJECTS = {"grain_deal": "grain agreement", "trade_deal": "trade deal",
                  "trade_talks": "trade arrangement", "alliance": "alliance",
                  "loan": "credit facility", "military_aid": "aid agreement"}
_DEAL_WORDS = {
    "EXTEND_EXISTING_DEAL": r"\bextend\w*|\brenew\w*|\broll\s+over|\bcontinue\w*\s+(?:the\s+)?(?:deal|agreement)",
    "EXPAND_VOLUME": r"\bexpand\w*|\bincreas\w*|\blarger|\bmore\s+(?:deliver|grain|volume|supplies)|"
                     r"\bscale\s+up|\bhigher\s+(?:volume|deliveries)",
    "RENEGOTIATE_TERMS": r"\brenegotiat\w*|\brevis\w*\s+(?:the\s+)?terms|\bnew\s+terms|"
                         r"\breopen\w*\s+(?:the\s+)?(?:deal|agreement|terms)",
    "TERMINATE_DEAL": r"\bterminat\w*|\bcancel\w*|\bend\s+(?:the\s+)?(?:deal|agreement)|\bwithdraw\s+from",
}


def active_deals(w: World, party: str) -> list:
    """Agreements with this party that have not run out, as the state model records them."""
    actor = ((w.foreign or {}).get("actors") or {}).get(party) or {}
    out = []
    for c in (actor.get("diplomacy") or {}).get("commitments", []):
        if isinstance(c, dict) and c.get("partner") == "karamaniya" and c.get("until", 0) > w.month:
            out.append(c)
    return out


def deal_action_for(mo: dict, text: str, existing: list) -> str | None:
    """What the motion is doing to the agreement: named explicitly, or read from its words.

    A delegate that asks for larger grain deliveries after a storm is not proposing a new
    agreement — it is asking to change one that exists, and the engine used to file it as a fresh
    deal every time, so the same agreement was created over and over and none of them was ever the
    one in force. Where the words name the act unmistakably, they settle it; where they do not, the
    engine asks rather than choosing between EXPAND and RENEGOTIATE on the delegate's behalf.
    """
    explicit = mo.get("action") if isinstance(mo.get("action"), dict) else {}
    declared = str(explicit.get("deal_action") or "").strip().upper()
    if declared in DEAL_ACTIONS:
        return declared
    if not existing:
        return "TERMINATE_DEAL" if re.search(_DEAL_WORDS["TERMINATE_DEAL"], text or "", re.I) else "NEW_DEAL"
    for action in ("TERMINATE_DEAL", "EXTEND_EXISTING_DEAL", "RENEGOTIATE_TERMS", "EXPAND_VOLUME"):
        if re.search(_DEAL_WORDS[action], text or "", re.I):
            return action
    return None


def _deal_problem(w: World, mo: dict, subj: str, text: str):
    """None if the deal action is coherent with what is already in force, else a rejection."""
    from .motion_actions import party_of, structured_action
    action = structured_action(w, mo)
    party = party_of(action.get("target")) or DIPLOMACY.get(subj)
    if not party:
        return None
    existing = active_deals(w, party)
    what = _DEAL_SUBJECTS.get(subj, subj.replace("_", " "))
    chosen = deal_action_for(mo, text, existing)
    if existing and chosen == "NEW_DEAL":
        return _reject("DEAL_ALREADY_EXISTS",
                       f"an agreement with {party} is already in force until Month "
                       f"{int(existing[0].get('until', 0)) + 1}; say what you are doing to it — "
                       "EXTEND_EXISTING_DEAL, EXPAND_VOLUME, RENEGOTIATE_TERMS or TERMINATE_DEAL",
                       in_force=existing[0], allowed=list(DEAL_ACTIONS))
    if existing and chosen is None:
        return _reject("UNKNOWN_DEAL_INTENT",
                       f"an agreement with {party} is already in force; state whether this extends "
                       "it, expands its volume, renegotiates its terms or terminates it",
                       allowed=list(DEAL_ACTIONS))
    if not existing and chosen in ("EXTEND_EXISTING_DEAL", "EXPAND_VOLUME", "RENEGOTIATE_TERMS",
                                   "TERMINATE_DEAL"):
        return _reject("NO_EXISTING_DEAL", f"there is no {what} with {party} to {chosen.lower().replace('_', ' ')}",
                       allowed=["NEW_DEAL"])
    return None


def _arrears_scope(mo: dict, raw) -> tuple:
    """(fraction, the categories named, the categories not recognised) from however it was written.

    A delegate writes "all_of_current_arrears_that_are_storm_related" or "half, rail and storage" or
    just "quarter". All three say precisely which bills are to be paid, and the engine used to
    accept only the three bare fractions and throw the rest away as a bad value — the one phrase
    that named exactly who was owed money was the one phrase it refused.
    """
    from .economy import ARREARS_CATEGORIES_ORDER, ARREARS_CATEGORY_ALIASES
    text = str(raw or "")
    explicit = mo.get("action") if isinstance(mo.get("action"), dict) else {}
    chosen = [str(c) for c in (explicit.get("categories") or [])] if isinstance(
        explicit.get("categories"), list) else []
    if explicit.get("region"):
        chosen.append(str(explicit["region"]))
    # A delegate writes the scope as prose glued together with underscores —
    # "all_of_current_arrears_that_are_storm_related" — so the phrase has to be taken apart before
    # it can be read. Every run of up to three neighbouring words is offered as a candidate, which
    # is what lets "storm_related" and "civil_service_payroll" be found inside a sentence.
    tokens = [t for t in re.split(r"[^a-z]+", text.lower()) if t]
    found, consumed = set(), set()
    for size in (3, 2, 1):
        for i in range(len(tokens) - size + 1):
            name = ARREARS_CATEGORY_ALIASES.get("_".join(tokens[i:i + size]))
            if name:
                found.add(name)
                consumed.update(range(i, i + size))
    for candidate in chosen:
        name = ARREARS_CATEGORY_ALIASES.get(candidate)
        if name:
            found.add(name)
    categories = [name for name in ARREARS_CATEGORIES_ORDER if name in found]
    fraction = None
    for word, frac in (("quarter", .25), ("half", .5), ("all", 1.0)):
        if word in tokens or any(ARREARS_CATEGORY_ALIASES.get(c) == word for c in chosen):
            fraction = frac
            break
    # A word that was part of a recognised phrase is not an unknown one: "storm" is spoken for by
    # "storm_related", and reporting it would make the delegate's own correct wording an error.
    # But a "_related" coinage the engine has no alias for IS the delegate naming a category it
    # does not have: "moon_related" is not prose, it is an unknown bill category wearing the
    # same grammar as a known one.
    unknown = {tokens[i] for i in range(len(tokens))
               if i not in consumed and tokens[i] not in ARREARS_CATEGORY_ALIASES
               and _categorical(tokens[i])}
    for i in range(len(tokens) - 1):
        if tokens[i + 1] == "related" and i not in consumed and (i + 1) not in consumed:
            unknown.add(tokens[i] + "_related")
    if fraction is None and not categories and not unknown:
        return None, [], set()
    return (fraction if fraction is not None else 1.0), categories, unknown


def _categorical(word: str) -> bool:
    """Whether a stray word was plausibly meant as a category rather than as prose."""
    return any(token in word for token in ("_", "supplier", "payroll", "pay", "service", "debt",
                                           "rail", "storage", "logistic", "storm", "military",
                                           "police", "army", "food", "civil"))


def _arrears_funding_capacity(w: World, source: str, floor: float = 0.0) -> float:
    """Crowns a source can fund. From reserves, that is what they hold above `floor` (gold), in crowns."""
    e = w.econ
    if source == "reserves":
        rate = w.zone_of("karamaniya").price / (e.fx_conf if e.currency == "karam" else 1.0)
        return max(0.0, (e.gold - floor) * rate)
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
# What happened between a binding directive and the order an office gave. The four values are kept
# apart because "passed" is not "in force" and "in force" is not "carried out":
COMPLIANT = "COMPLIANT"                     # the office is where the council put it
SUPERSEDED_ORDER = "SUPERSEDED_ORDER"       # the order contradicted a directive passed this month
EXPLICIT_VIOLATION = "EXPLICIT_VIOLATION"   # the office moved against a directive already in force
BLOCKED_EXECUTION = "BLOCKED_EXECUTION"     # the directive could not be carried out
PENDING = "PENDING"                         # ordered, not yet observable


def _compliance(w: World, office: str, lever: str, mid: str, ordered, note: str, status: str) -> dict:
    """One lever's directive, the order given, the value actually in force, and which of them won."""
    directive = w.const.directives.get(lever)
    actual = getattr(w.policy, lever, None)
    if actual is None:
        actual = (w.policy.patronage or {}).get(office) if lever.startswith("patronage_") else None
    return {"code": "DIRECTIVE_ORDER_MISMATCH" if status != COMPLIANT else "",
            "member": mid, "office": office, "lever": lever,
            "directive_value": directive, "office_order_value": ordered,
            "actual_executed_value": actual, "compliance_status": status, "note": note}


def apply_orders(w: World, mid: str, orders: dict, fresh: set | None = None, superseded: list | None = None,
                 unauthorized: list | None = None, compliance: list | None = None,
                 adjusted: list | None = None) -> list:
    """Apply one member's orders for the offices they hold. Returns any defiance records.

    `adjusted`, when given, collects an entry for every order where what was applied is not what was
    asked: a number outside its setting's bounds, or a value the setting does not take.

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
                    if adjusted is not None:
                        adjusted.append({"member": mid, "office": office, "lever": lever, **lever_adjustment(
                            lever, raw, None)})
                    continue
                key = f"patronage_{office}"          # the council's directive on this office's patronage
                if fresh and key in fresh:
                    if superseded is not None and directives.get(key) != flag:
                        superseded.append({"member": mid, "office": office, "lever": key,
                                           "order": flag, "directive": directives.get(key)})
                    if compliance is not None and directives.get(key) != flag:
                        compliance.append(_compliance(w, office, key, mid, flag,
                                                      "the directive passed this month; the order was "
                                                      "written before its vote was counted", SUPERSEDED_ORDER))
                    elif compliance is not None:
                        compliance.append(_compliance(w, office, key, mid, flag, "in line", COMPLIANT))
                    continue
                if key in directives and directives[key] != flag:
                    defiance.append({"member": mid, "office": office, "lever": key,
                                     "directive": directives[key], "value": flag})
                    if compliance is not None:
                        compliance.append(_compliance(w, office, key, mid, flag,
                                                      "ordered against a directive already in force",
                                                      EXPLICIT_VIOLATION))
                w.policy.patronage[office] = flag
                if compliance is not None and (key not in directives or directives[key] == flag):
                    compliance.append(_compliance(w, office, key, mid, flag, "in line", COMPLIANT))
                continue
            refusal = order_authority(w, mid, office, lever)
            if refusal:
                # This used to be a bare `continue`: an order for a setting the office does not hold
                # was dropped without a word, so a delegate could believe it had directed something it
                # never touched, and the record showed nothing at all. Recorded, and announced, it is
                # a fact about the month instead of a silence.
                if unauthorized is not None:
                    unauthorized.append({**refusal, "order": raw})
                    w.event("unauthorized_order",
                            f"{w.member(mid).name} ({OFFICE_TITLES[office]}) ordered {lever}, which is not "
                            f"{office}'s to set: {refusal['detail']}.", importance=1, member=mid,
                            lever=lever, office=office, reason=refusal["reason"])
                continue
            value = parse_lever(lever, raw)
            gap = lever_adjustment(lever, raw, value)
            if gap is not None and adjusted is not None:
                adjusted.append({"member": mid, "office": office, "lever": lever, **gap})
            if value is None:
                continue
            if fresh and lever in fresh:
                if superseded is not None and not _same(directives.get(lever), value):
                    superseded.append({"member": mid, "office": office, "lever": lever,
                                       "order": value, "directive": directives.get(lever)})
                if compliance is not None:
                    clash = not _same(directives.get(lever), value)
                    compliance.append(_compliance(
                        w, office, lever, mid, value,
                        "the directive passed this month; the order was written before its vote was counted"
                        if clash else "in line",
                        SUPERSEDED_ORDER if clash else COMPLIANT))
                continue
            fiscal_authority = (office == "treasury" and w.agent_architecture_version >= 2
                                and "fiscal_authority" in (w.institutions.get("emergency_measures") or {}))
            # Against the bound, not against the number. Reading only the number treated every
            # directive as fixed, which is safe but blind: it cannot tell a ceiling from a floor and
            # would have called an order inside a genuine floor a defiance. Reading the bound is what
            # stops "floor 0.035" being taken as leave to raise spending when the same proposal also
            # says no increase — that intersection is 0.035 exactly, and 0.04 is outside it.
            against = (lever in directives and not bound_allows(_bound_for(w, lever), value)
                       and not fiscal_authority)
            if against:
                defiance.append({"member": mid, "office": office, "lever": lever,
                                 "directive": directives[lever], "value": value})
            set_lever(w, lever, value)
            if compliance is not None and lever in directives:
                # The order stands and the state moves, which is the existing behaviour: a directive
                # binds the office, and an office that moves against one is recorded acting against
                # it rather than prevented. What is new is that the three values are written down
                # beside each other, so the contradiction is visible instead of implied.
                compliance.append(_compliance(
                    w, office, lever, mid, value,
                    "ordered against a directive already in force" if against else "in line",
                    EXPLICIT_VIOLATION if against else COMPLIANT))
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
                # The army is not one mind. `anticipated_response` returns the share of units that
                # would obey the plotter, obey the government, stay neutral or split, from the same
                # state the scalar below used to collapse: institutional loyalty, personal bond,
                # pay arrears and the legitimacy of the government. Units that would join do so
                # only if they expect enough others to join, so a plot that looks like it will fail
                # collapses further rather than being carried by a determined few. Whole-army
                # obedience is not a producible answer: the commander's share is capped.
                division = military.anticipated_response(
                    w, {"kind": "coup", "office": office, "leader": holder.id})
                attack += power * division["obey_commander"]
                # Units that stay in barracks are not defending the government either, so they
                # count for neither side; a split garrison defends at half weight.
                defend += power * (division["obey_government"]
                                   + 0.5 * division["split"]) * force.loyalty
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
