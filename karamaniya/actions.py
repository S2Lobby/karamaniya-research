"""Answer formats for the two phases of a month, and cleanup of what the AIs send back.

Schemas are strict JSON Schema (every property required, no extra keys) so providers
with structured outputs can enforce them. Providers without that get the same shape as a
written example, and whatever comes back is normalised here: bad values are dropped, not
guessed, and every drop is recorded so the report can show format problems per model.
"""
from __future__ import annotations

import re

from .motion_actions import ACTION_TO_SUBJECT, DIPLOMATIC_ACTIONS as DIPLOMATIC_ACTION_TYPES
from .politics import (BOOLS, CONSTITUTION_FIELDS, DIPLOMACY, ENUMS, LEVER_OFFICE, MOTION_TYPES,
                       SHARES, V2_MOTION_TYPES, canonical_diplomacy_subject, canonical_funding,
                       canonical_lever, canonical_office, parse_loan_amount, patronage_subject)
from .world import ARMED_OFFICES, OFFICES, World

STATEMENT_WORDS = 150
DM_WORDS = 80
NOTE_WORDS = 150
PRINCIPLES_WORDS = 32
MAX_MOTIONS = 2


def public_statement_preview(raw: str) -> str:
    """Read only the public statement string from a possibly unfinished JSON reply."""
    match = re.search(r'"statement"\s*:\s*"', raw)
    if not match:
        return ""
    out = []
    i = match.end()
    escapes = {'"': '"', "\\": "\\", "/": "/", "n": "\n", "r": "\r", "t": "\t", "b": "", "f": ""}
    while i < len(raw) and len(out) < 2400:
        char = raw[i]
        if char == '"':
            break
        if char == "\\":
            if i + 1 >= len(raw):
                break
            nxt = raw[i + 1]
            if nxt == "u":
                code = raw[i + 2:i + 6]
                if len(code) < 4 or not all(c in "0123456789abcdefABCDEF" for c in code):
                    break
                out.append(chr(int(code, 16)))
                i += 6
                continue
            out.append(escapes.get(nxt, nxt))
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out).strip()


def words(text, limit: int) -> str:
    parts = str(text or "").split()
    return " ".join(parts[:limit]) + (" [cut]" if len(parts) > limit else "")


def _office_levers(office: str) -> list:
    # An office's patronage is one order ("patronage"); the patronage_* names are for council directives.
    levers = [k for k, v in LEVER_OFFICE.items() if v == office and not k.startswith("patronage_")]
    if office in ARMED_OFFICES:
        levers.append("patronage")
    return levers


def _lever_schema(lever: str) -> dict:
    if lever in ENUMS:
        return {"type": "string", "enum": list(ENUMS[lever])}
    if lever in BOOLS or lever == "patronage":
        return {"type": "boolean"}
    return {"type": "number"}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props),
            "additionalProperties": False}


def _opt_obj(props: dict) -> dict:
    """An object whose fields may be left out. Used where a field only applies to some motions."""
    return {"type": "object", "properties": props, "additionalProperties": False}


def _dm_schema(targets: list) -> dict:
    return {"type": "array", "items": _obj({"to": {"type": "string", "enum": targets},
                                            "text": {"type": "string"}})}


def action_schema(w: World) -> dict:
    """The explicit act of a foreign-policy motion, so it cannot be executed as a different one."""
    from .motion_actions import ACTOR_NAMES
    # Optional, and only meaningful on a foreign-policy motion: an interior directive has no target
    # country. The instructions say so; leaving it out is not an error.
    from .politics import DEAL_ACTIONS, RELIEF_FUNDING, RELIEF_SCOPES
    regions = [r.id for r in w.k_regions()]
    return _opt_obj({"action_type": {"type": "string", "enum": list(DIPLOMATIC_ACTION_TYPES)},
                     # Canonical ids, not display names: "Union" is not an actor and a target that
                     # ambiguous cannot be checked against anything. The normaliser still accepts a
                     # display name for a delegate that writes one.
                     "target": {"type": "string", "enum": list(ACTOR_NAMES)},
                     "issue": {"type": "string"},
                     "terms": {"type": "array", "items": {"type": "string"}},
                     # What is being done to an agreement that may already exist. Asking for larger
                     # grain deliveries is not a new agreement, and filing it as one created the
                     # same agreement over and over while none of them was the one in force.
                     "deal_action": {"type": "string", "enum": list(DEAL_ACTIONS)},
                     # A disaster relief package. Its own action rather than an emergency measure:
                     # a storm is not a curfew, and the only act the engine used to have for a
                     # crisis was the toggle for police powers, so every relief motion was refused
                     # as an unknown measure and the delegate lost its whole policy response.
                     "region": {"type": "string", "enum": regions},
                     "regions": {"type": "array", "items": {"type": "string", "enum": regions},
                                 "minItems": 1, "uniqueItems": True},
                     "amount": {"type": "string"},
                     "funding": {"type": "string", "enum": list(RELIEF_FUNDING)},
                     "funding_plan": {"type": "array", "items": _obj({
                         "source": {"type": "string", "enum": list(RELIEF_FUNDING)},
                         "amount": {"type": "string"}}), "minItems": 1},
                     "scope": {"type": "string", "enum": list(RELIEF_SCOPES)},
                     # A package of settings moved at once, the way a cabinet resolves an austerity or
                     # stimulus programme. Each measure is one lever the council can direct plus a value.
                     "measures": {"type": "array", "minItems": 1, "items": _obj({
                         "lever": {"type": "string"}, "value": {"type": "string"}})},
                     "military_engineers": {"type": "boolean"}})


def condition_schema() -> dict:
    """Optional binding execution safeguards ('pay only if reserves stay above 55M').

    Structured conditions are what the engine tests before mutating state; a conditional
    motion whose floor is not met is blocked, never run unconditionally. Omitting the
    field means no safeguards, and that is not an error.
    """
    from .motion_actions import CONDITION_METRICS
    return {"type": "array",
            "items": {"type": "object", "additionalProperties": False,
                      "properties": {"metric": {"type": "string", "enum": list(CONDITION_METRICS)},
                                     "operator": {"type": "string", "enum": [">=", "<=", "=="]},
                                     "value": {"type": "number"},
                                     "source": {"type": "string"}},
                      "required": ["metric", "operator", "value"]}}


def motion_schema(w: World, with_emergency: bool = False) -> dict:
    """One tabled motion. Shared by the opening round and by the targeted repair of a bad one."""
    kinds = list(MOTION_TYPES) + (list(V2_MOTION_TYPES) if with_emergency else [])
    return _obj({"type": {"type": "string", "enum": kinds},
                 "subject": {"type": "string"}, "value": {"type": "string"},
                 "text": {"type": "string"}, "action": action_schema(w),
                 "conditions": condition_schema()})


def repair_schema(w: World, limit: int) -> dict:
    """The answer to a MOTION_ACTION_MISMATCH: the corrected motions, and nothing else."""
    return {"type": "object", "additionalProperties": False, "required": ["motions"],
            "properties": {"motions": {"type": "array", "items": motion_schema(w),
                                       "minItems": 1, "maxItems": max(1, limit)}}}


def session_schema(w: World, mid: str) -> dict:
    others = [m.id for m in w.active_members() if m.id != mid] or [mid]
    motion = motion_schema(w)
    promise = _obj({"to": {"type": "string", "enum": ["public", *others]},
                    "text": {"type": "string"}, "condition": {"type": "string"}})
    props = {"private_position": {"type": "string"},
             "statement": {"type": "string"},
             "motions": {"type": "array", "items": motion},
             "promises": {"type": "array", "items": promise},
             "private_messages": _dm_schema(others)}
    if w.human_factor:
        props["principles"] = {"type": "string"}
    return _obj(props)


def forecast_schema() -> dict:
    """One checkable prediction about where a number will be at a stated horizon.

    Deliberately falsifiable: a metric, a direction, a threshold and a date. "Things will get
    worse" is not a forecast and cannot be scored, so the form does not permit it.
    """
    from .forecasts import DIRECTIONS, FORECAST_METRICS, HORIZONS
    return _obj({"metric": {"type": "string", "enum": list(FORECAST_METRICS)},
                 "horizon_months": {"type": "integer", "enum": list(HORIZONS)},
                 "direction": {"type": "string", "enum": list(DIRECTIONS)},
                 "threshold": {"type": "number"},
                 "confidence": {"type": "number"},
                 "rationale": {"type": "string"}})


def decision_schema(w: World, mid: str, motion_ids: list) -> dict:
    others = [m.id for m in w.active_members() if m.id != mid] or [mid]
    props = {}
    if motion_ids:
        props["votes"] = _obj({i: {"type": "string", "enum": ["yes", "no", "abstain", "conditional"]} for i in motion_ids})
        props["vote_reasons"] = _obj({i: {"type": "string"} for i in motion_ids})
        props["vote_conditions"] = {"type": "array", "items": _obj({
            "motion_id": {"type": "string", "enum": motion_ids},
            "metric": {"type": "string", "enum": ["food_ratio", "reserves", "arrears", "unemployment", "army_morale"]},
            "operator": {"type": "string", "enum": [">=", "<="]},
            "value": {"type": "number"},
        })}
    held = w.offices_of(mid)
    orders = {o: _obj({lv: _lever_schema(lv) for lv in _office_levers(o)}) for o in held if o != "head"}
    if orders:
        props["orders"] = _obj(orders)
    if any(o in ARMED_OFFICES for o in held):
        props["coup"] = _obj({"action": {"type": "string", "enum": ["none", "remove", "take_over"]},
                              "members": {"type": "array", "items": {"type": "string", "enum": others}}})
        props["coup_stance"] = {"type": "string", "enum": ["resist", "stand_aside", "join"]}
    props["resign"] = {"type": "boolean"}
    props["private_messages"] = _dm_schema(others)
    props["notes"] = {"type": "string"}
    props["decision_factors"] = {"type": "array", "items": {"type": "string"}}
    return _obj(props)


def example(schema: dict, indent: int = 0) -> str:
    """Render a schema as a readable JSON-like skeleton for the prompt."""
    pad = "  " * indent
    t = schema.get("type")
    if t == "object":
        props = schema.get("properties", {})
        if not props:
            return "{}"
        inner = [f'{pad}  "{k}": {example(v, indent + 1)}' for k, v in props.items()]
        return "{\n" + ",\n".join(inner) + f"\n{pad}}}"
    if t == "array":
        return "[" + example(schema["items"], indent) + ", ...]"
    if "enum" in schema:
        return " | ".join(f'"{x}"' for x in schema["enum"])
    return {"string": '"..."', "number": "number", "boolean": "true | false"}.get(t, '"..."')


# ---- normalisation ----------------------------------------------------------------------
def _dms(w: World, mid: str, raw, quota: int, problems: list) -> list:
    out = []
    ids = {m.id for m in w.active_members()}
    for dm in raw if isinstance(raw, list) else []:
        if len(out) >= quota:
            problems.append("too many private messages")
            break
        if not isinstance(dm, dict):
            continue
        to = str(dm.get("to", "")).strip().upper().replace("DELEGATE ", "")
        text = words(dm.get("text", ""), DM_WORDS)
        if to not in ids:
            problems.append(f"bad private message recipient '{dm.get('to')}'")
            continue
        if to == mid:
            problems.append(f"private message cannot be sent to self ('{to}')")
            continue
        if not text.strip():
            problems.append(f"private message to {to} has an empty body")
            continue
        out.append({"from": mid, "to": to, "text": text})
    return out


def normalize_session(w: World, mid: str, data, dm_quota: int) -> tuple:
    problems = []
    if not isinstance(data, dict):
        return {"private_position": "", "statement": "", "motions": [], "promises": [],
                "private_messages": [], "principles": ""}, ["no answer"]
    statement = words(data.get("statement", ""), STATEMENT_WORDS)
    motions = []
    for mo in data.get("motions") or []:
        if len(motions) >= MAX_MOTIONS:
            problems.append("too many motions")
            break
        if not isinstance(mo, dict):
            continue
        motions.append(normalize_motion_v2(w, mo))
    promises = []
    others = {m.id for m in w.active_members()}
    for item in data.get("promises") or []:
        if not isinstance(item, dict) or len(promises) >= 1:
            if len(promises) >= 1:
                problems.append("too many political commitments")
                break
            continue
        text = words(item.get("text", ""), 35)
        to = str(item.get("to", "public")).strip().upper()
        if to != "PUBLIC" and (to not in others or to == mid):
            problems.append(f"bad political commitment recipient '{to}'")
            continue
        if text:
            promises.append({"to": to.lower() if to.lower() == "public" else to,
                             "text": text, "condition": words(item.get("condition", ""), 24)})
    private_position = words(data.get("private_position", ""), 45)
    dms = _dms(w, mid, data.get("private_messages"), dm_quota, problems)
    principles = words(data.get("principles", ""), PRINCIPLES_WORDS) if w.human_factor else ""
    return {"private_position": private_position, "statement": statement, "motions": motions,
            "promises": promises, "private_messages": dms,
            "principles": principles}, problems


def normalize_decision(w: World, mid: str, data, motion_ids: list, dm_quota: int,
                       defer_to_v2: bool = False) -> tuple:
    """Fold a decision answer into the canonical shape.

    `defer_to_v2` is set by normalize_decision_v2, which re-parses vote conditions and private
    messages itself. Without it the two passes each report on the same answer, so a condition that
    v2 accepts is still announced as missing and every over-quota message is counted twice.
    """
    problems = []
    empty = {"votes": {}, "vote_reasons": {}, "vote_conditions": {}, "orders": {}, "coup": None, "coup_stance": "resist", "resign": False,
             "private_messages": [], "notes": "", "decision_factors": []}
    if not isinstance(data, dict):
        return empty, ["no answer"]
    votes = {}
    reasons = {}
    raw_reasons = data.get("vote_reasons") if isinstance(data.get("vote_reasons"), dict) else {}
    raw_votes = data.get("votes") if isinstance(data.get("votes"), dict) else {}
    for i in motion_ids:
        v = str(raw_votes.get(i, "abstain")).strip().lower()
        votes[i] = v if v in ("yes", "no", "abstain", "conditional") else "abstain"
        reasons[i] = words(raw_reasons.get(i, ""), 35)
        if not reasons[i]:
            problems.append(f"missing vote reason for {i}")
    conditions = {}
    raw_conditions = [] if defer_to_v2 else data.get("vote_conditions")
    for item in raw_conditions if isinstance(raw_conditions, list) else []:
        if not isinstance(item, dict):
            continue
        motion_id = item.get("motion_id")
        if motion_id not in motion_ids or votes[motion_id] != "conditional":
            continue
        metric, operator, value = item.get("metric"), item.get("operator"), item.get("value")
        if metric not in ("food_ratio", "reserves", "arrears", "unemployment", "army_morale") or operator not in (">=", "<="):
            problems.append(f"invalid vote condition for {motion_id}")
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            problems.append(f"invalid vote condition value for {motion_id}")
            continue
        if not -1e12 <= value <= 1e12:
            problems.append(f"invalid vote condition value for {motion_id}")
            continue
        conditions.setdefault(motion_id, []).append({"metric": metric, "operator": operator, "value": value})
    for i in motion_ids:
        if votes[i] == "conditional" and i not in conditions and not defer_to_v2:
            problems.append(f"conditional vote missing valid condition for {i}")
    conditions = {key: value[0] if len(value) == 1 else value for key, value in conditions.items()}
    held = w.offices_of(mid)
    orders = {}
    raw_orders = data.get("orders") if isinstance(data.get("orders"), dict) else {}
    for office, levers in raw_orders.items():
        if office not in held:
            if office in OFFICES:
                problems.append(f"orders for an office not held: {office}")
            continue
        if isinstance(levers, dict):
            orders[office] = levers
    coup = None
    armed = any(o in ARMED_OFFICES for o in held)
    raw_coup = data.get("coup")
    if armed and isinstance(raw_coup, dict):
        action = str(raw_coup.get("action", "none")).strip().lower()
        if action in ("remove", "take_over"):
            targets = [str(t).strip().upper().replace("DELEGATE ", "") for t in raw_coup.get("members") or []]
            coup = {"action": action, "members": [t for t in targets if t != mid]}
    stance = str(data.get("coup_stance", "resist")).strip().lower()
    if stance not in ("resist", "stand_aside", "join"):
        stance = "resist"
    resign = data.get("resign") is True
    dms = [] if defer_to_v2 else _dms(w, mid, data.get("private_messages"), dm_quota, problems)
    notes = words(data.get("notes", ""), NOTE_WORDS)
    factors = [words(x, 14) for x in data.get("decision_factors", [])[:4]
               if isinstance(x, str) and words(x, 14)] if isinstance(data.get("decision_factors"), list) else []
    return {"votes": votes, "vote_reasons": reasons, "vote_conditions": conditions,
            "orders": orders, "coup": coup, "coup_stance": stance, "resign": resign,
            "private_messages": dms, "notes": notes, "decision_factors": factors}, problems


def motion_summary(w: World, mo: dict) -> str:
    t, s, v = mo["type"], mo.get("subject", ""), mo.get("value", "")
    if t == "assign_office":
        return f"appoint {w.member(v.upper()).name if v.upper() in {m.id for m in w.members} else v} to {s}"
    if t == "vacate_office":
        return f"leave {s} vacant"
    if t == "set_policy":
        return f"directive {s} = {v}"
    if t == "settle_arrears":
        return f"pay {v} of inherited unpaid bills using {s.replace('_', ' ')}"
    if t == "disaster_relief":
        payload = mo.get("action") if isinstance(mo.get("action"), dict) else {}
        places = payload.get("regions") or ([payload["region"]] if payload.get("region") else [])
        region_names = {region.id: region.name for region in w.regions}
        place_text = ", ".join(region_names.get(str(x), str(x)) for x in places) if places else (s or "the affected area")
        amount = payload.get("amount") or v or "unspecified amount"
        scope = str(payload.get("scope") or "mixed")
        plan = payload.get("funding_plan")
        if isinstance(plan, list) and plan:
            funding = " + ".join(f"{x.get('amount', '?')} from {str(x.get('source', 'unknown')).replace('_', ' ')}"
                                  for x in plan if isinstance(x, dict))
        else:
            funding = str(payload.get("funding") or "unspecified funding").replace("_", " ")
        engineers = ", with military engineers" if payload.get("military_engineers") else ""
        return f"relief for {place_text}: {amount} ({scope}), funded by {funding}{engineers}"
    if t == "constitution":
        return f"constitution: {s} = {v}"
    if t == "amend":
        return f"amend the Charter: \"{mo.get('text', '')[:160]}\""
    if t == "expel":
        return f"expel {w.member(s.upper()).name if s.upper() in {m.id for m in w.members} else s}"
    if t == "diplomacy":
        from .motion_actions import ACTOR_NAMES, structured_action
        target = structured_action(w, mo).get("target")
        who = {"SOLVARAN_UNION": f"the {w.names['union']}",
               "MARITIME_LEAGUE": f"the {w.names['league']}",
               "DORSANIA": w.names["dorsania"],
               "VELERIA": w.names["veleria"]}.get(target, ACTOR_NAMES.get(target, "the Maritime League"))
        amt = _loan_amount_summary(mo) if s == "loan" else ""
        if s == "diplomatic_protest":
            return f"deliver a diplomatic protest to {who}"
        return f"propose {s.replace('_', ' ')}{amt} to {who}"
    if t == "referendum":
        return "hold a referendum on independence this month"
    if t == "launch_currency":
        return "launch the karam"
    if t == "investigation":
        from . import audits
        office = audits.office_of(s) or s
        return f"close the audit of the {office}" if audits.parse_action(v) == "close" else f"audit the {office}"
    return t


def _loan_amount_summary(motion: dict) -> str:
    """Render the numeric loan amount in the engine's canonical millions-of-gold unit."""
    action = motion.get("action") if isinstance(motion.get("action"), dict) else {}
    amount = parse_loan_amount(motion.get("value"))
    if amount is None:
        amount = parse_loan_amount(action.get("amount"))
    return f" ({amount:g} million)" if amount is not None else ""


CONSTITUTION_HELP = ", ".join(f"{k} ({'/'.join(v) if v else 'text' if k == 'regime_name' else 'month number or none'})"
                              for k, v in CONSTITUTION_FIELDS.items())
SHARE_HELP = ", ".join(SHARES)


# =====================================================================================================
# Version 2 answer formats: opening, revision and decision (spec 11, 33, 34, 42, 58, 68, 69, 74, 88)
# =====================================================================================================
RESPONSE_WORDS = 70
POSITION_FIELDS = ("main_problem", "preferred_policy", "unacceptable_outcome", "would_support", "would_oppose")
EXTERNAL_TARGETS = ["public", "union", "veleria", "dorsania", "league"]


def _arr(items: dict, max_items: int | None = None) -> dict:
    out = {"type": "array", "items": items}
    if max_items:
        out["maxItems"] = max_items
    return out


DM_PER_PHASE = 3


def _v2_dm_schema(targets: list, max_items: int = DM_PER_PHASE) -> dict:
    from .commitments import DM_KINDS
    return _arr(_obj({"to": {"type": "string", "enum": targets}, "text": {"type": "string"},
                      "kind": {"type": "string", "enum": list(DM_KINDS)}}), max_items)


def _offer_dms(props: dict, targets: list, dm_left: int) -> None:
    """Offer private messages only while the member has quota, and cap the schema at what is left.

    The prompt has always carried the remaining count — a member can be told "send up to 0 private
    messages" — but the schema advertised a flat maximum of three in every phase, so that same
    member was shown a structured-output contract permitting three. Observed on a real run:
    delegate B sent one message in the revision phase and one in the decision phase and both were
    rejected as "too many private messages". The engine told it two opposite things and then
    charged the member for the contradiction, which is a schema failure wearing the costume of a
    political choice — exactly what the delegate should never be penalised for.
    """
    if dm_left > 0:
        props["private_messages"] = _v2_dm_schema(targets, min(dm_left, DM_PER_PHASE))


def _comm_schema(w: World, mid: str, others: list) -> dict:
    from .standing import COMM_KINDS
    audiences = list((w.member(mid).agent_state or {}).get("constituencies", {}))
    return _arr(_obj({"kind": {"type": "string", "enum": list(COMM_KINDS)},
                      "target": {"type": "string", "enum": EXTERNAL_TARGETS + others + audiences},
                      "about": {"type": "string"}}), 2)


def _share_schema(w: World, mid: str, others: list) -> dict | None:
    from .intelligence import own_report_ids
    ids = own_report_ids(w, mid)
    if not ids:
        return None
    return _arr(_obj({"report_id": {"type": "string", "enum": ids},
                      "with": {"type": "string", "enum": ["council", *others]}}), 3)


def session_schema_v2(w: World, mid: str, dm_left: int = DM_PER_PHASE) -> dict:
    from .deliberation import TOPICS
    from .intelligence import REQUEST_TOPICS
    others = [m.id for m in w.active_members() if m.id != mid] or [mid]
    motion = motion_schema(w, with_emergency=True)
    motion["properties"]["force_agenda"] = {"type": "boolean"}
    motion["required"].append("force_agenda")
    promise = _obj({"to": {"type": "string", "enum": ["public", *others]}, "text": {"type": "string"},
                    "condition": {"type": "string"}})
    props = {"private_position": _obj({k: {"type": "string"} for k in POSITION_FIELDS}),
             "statement": {"type": "string"},
             "motions": _arr(motion, MAX_MOTIONS),
             "promises": _arr(promise, 1),
             "communications": _comm_schema(w, mid, others),
             "information_requests": _arr(_obj({"topic": {"type": "string", "enum": list(REQUEST_TOPICS)},
                                                "motion_id": {"type": "string"}}), 2),
             "strategy": _obj({"goal": {"type": "string"}, "by_month": {"type": "number"}})}
    _offer_dms(props, others, dm_left)
    share = _share_schema(w, mid, others)
    if share:
        props["share_reports"] = share
    if "head" in w.offices_of(mid):
        props["agenda_priorities"] = _arr({"type": "string", "enum": list(TOPICS)}, 4)
    if w.human_factor:
        props["principles"] = {"type": "string"}
    return _obj(props)


def revision_schema(w: World, mid: str, motions: list, dm_left: int = DM_PER_PHASE) -> dict:
    others = [m.id for m in w.active_members() if m.id != mid] or [mid]
    ids = [m["id"] for m in motions if not m.get("withdrawn")]
    own = [m["id"] for m in motions if m["proposer"] == mid and not m.get("withdrawn")]
    sponsored = [m["id"] for m in motions if mid in m.get("cosponsors", []) and not m.get("withdrawn")]
    props = {"response": {"type": "string"}}
    if ids:
        props["stances"] = _obj({i: {"type": "string", "enum": ["support", "oppose", "undecided", "conditional"]} for i in ids})
        props["demands"] = _arr(_obj({"motion_id": {"type": "string", "enum": ids}, "demand": {"type": "string"}}), 2)
    if own or sponsored:
        props["withdraw"] = _arr(_obj({"motion_id": {"type": "string", "enum": own + sponsored},
                                       "reason": {"type": "string"},
                                       "replaced_by": {"type": "string", "enum": ids + ["none"]}}))
    if own:
        amend_props = {"motion_id": {"type": "string", "enum": own}, "value": {"type": "string"},
                       "text": {"type": "string"}}
        if any(m.get("type") == "program" and m.get("id") in own for m in motions):
            # A program amendment replaces a package. Requiring the complete new measure list
            # prevents the engine from executing cached measures from the original wording.
            amend_props["measures"] = _arr(_obj({"lever": {"type": "string"}, "value": {"type": "string"}}))
        props["amend"] = _arr(_obj(amend_props), 1)
    props["communications"] = _comm_schema(w, mid, others)
    share = _share_schema(w, mid, others)
    if share:
        props["share_reports"] = share
    _offer_dms(props, others, dm_left)
    return _obj(props)


def decision_schema_v2(w: World, mid: str, motion_ids: list, election_pending: bool = False,
                       dm_left: int = DM_PER_PHASE) -> dict:
    from .beliefs import ids_for_schema
    from .deliberation import METRICS
    from .operations import OPERATIONS, schema as op_schema
    others = [m.id for m in w.active_members() if m.id != mid] or [mid]
    props = {}
    if motion_ids:
        props["votes"] = _obj({i: {"type": "string", "enum": ["yes", "no", "abstain", "conditional"]} for i in motion_ids})
        props["vote_reasons"] = _obj({i: {"type": "string"} for i in motion_ids})
        props["vote_conditions"] = _arr(_obj({
            "motion_id": {"type": "string", "enum": motion_ids},
            "kind": {"type": "string", "enum": ["metric", "motion"]},
            # Structured-output providers require every object property even when a field only
            # applies to one condition kind. Make the unused branch explicit instead of forcing
            # models to invent a metric for motion dependencies (or another motion for metrics).
            "metric": {"type": "string", "enum": [*METRICS, "none"]},
            "operator": {"type": "string", "enum": [">=", "<=", "none"]},
            "value": {"type": "number"},
            "other_motion": {"type": "string", "enum": motion_ids + ["none"]},
            "other_outcome": {"type": "string", "enum": ["passes", "fails", "none"]},
            "if_unmet": {"type": "string", "enum": ["no", "abstain"]}}))
    held = w.offices_of(mid)
    orders = {o: _obj({lv: _lever_schema(lv) for lv in _office_levers(o)}) for o in held if o != "head"}
    if orders:
        props["orders"] = _obj(orders)
    ops = {o: op_schema(o) for o in held if o in OPERATIONS}
    if ops:
        props["operations"] = _obj(ops)
    if any(o in ARMED_OFFICES for o in held):
        props["coup"] = _obj({"action": {"type": "string", "enum": ["none", "remove", "take_over"]},
                              "members": {"type": "array", "items": {"type": "string", "enum": others}}})
        props["coup_stance"] = {"type": "string", "enum": ["resist", "stand_aside", "join"]}
    if election_pending:
        props["election_response"] = {"type": "string", "enum": ["concede", "legal_challenge", "request_recount",
                                                                 "negotiate_coalition", "resign", "refuse"]}
    props["resign"] = {"type": "boolean"}
    props["belief_updates"] = _arr(_obj({"proposition": {"type": "string", "enum": ids_for_schema(w, mid)},
                                         "direction": {"type": "string", "enum": ["more_likely", "less_likely"]},
                                         "reason": {"type": "string"}}), 3)
    props["forecasts"] = _arr(forecast_schema(), 2)
    _offer_dms(props, others, dm_left)
    props["notes"] = {"type": "string"}
    props["decision_factors"] = _arr({"type": "string"}, 4)
    return _obj(props)


def _v2_dms(w: World, mid: str, raw, quota: int, problems: list) -> list:
    from .commitments import DM_KINDS, infer_kind
    out = _dms(w, mid, raw, quota, problems)
    kinds = {}
    for dm in raw if isinstance(raw, list) else []:
        if isinstance(dm, dict):
            kinds.setdefault(str(dm.get("to", "")).strip().upper().replace("DELEGATE ", ""), []).append(
                str(dm.get("kind", "")).strip().lower())
    for dm in out:
        given = (kinds.get(dm["to"]) or [""]).pop(0) if kinds.get(dm["to"]) else ""
        dm["kind"] = given if given in DM_KINDS else infer_kind(dm["text"])
    return out


def _comms(raw, problems: list) -> list:
    from .standing import COMM_KINDS
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or len(out) >= 2:
            continue
        kind = str(item.get("kind", "")).strip().lower()
        # Some models put report sharing in communications despite the dedicated field.
        # It is migrated below instead of reported as an unknown communication kind.
        if kind == "share_reports":
            continue
        if kind not in COMM_KINDS:
            problems.append(f"unknown communication kind '{kind}'")
            continue
        out.append({"kind": kind, "target": str(item.get("target", "public")).strip(),
                    "about": words(item.get("about", ""), 40)})
    return out


def _legacy_report_shares(w, mid: str, raw) -> list:
    """Recover report IDs placed in a share_reports communication item."""
    from .intelligence import own_report_ids
    known = own_report_ids(w, mid)
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or str(item.get("kind", "")).strip().lower() != "share_reports":
            continue
        description = " ".join(str(item.get(k, "")) for k in ("target", "about", "text", "message"))
        target = str(item.get("target", "council")).strip()
        recipient = "council" if target.casefold() in ("", "public", "council", "full council") else target.upper()
        matched = [rid for rid in known if rid.casefold() in description.casefold()]
        out.extend({"report_id": rid, "with": recipient} for rid in matched)
    return out[:3]


def normalize_motion_v2(w: World, raw: dict) -> dict:
    """One motion from a model's answer, with an explicit `action` made authoritative.

    The engine routes a foreign motion on its subject, so the act a delegate states outright has to
    be the one that decides the subject. Otherwise a protest could name itself one thing in `action`
    and be sent somewhere else by a stale `subject`. Binding execution `conditions` ride along
    untouched; the gate tests them against canonical state before any mutation.
    """
    # The session parser filters non-object entries first; keep the standalone parser safe too.
    if not isinstance(raw, dict):
        raw = {}
    from .motion_actions import motion_conditions as _derive_conditions
    motion_type = str(raw.get("type", "")).strip()
    if motion_type.lower() == "audit":
        motion_type = "investigation"
    mo = {"type": motion_type,
          "subject": canonical_lever(patronage_subject(raw.get("subject", ""))),
          "value": str(raw.get("value", "")).strip(),
          "text": words(raw.get("text", ""), 120),
          "action": _explicit_action(w, raw.get("action"))}
    # Resolve the words a delegate used for an office, a foreign act, or a settlement source to the
    # engine's own id at intake, so the record, the vote and the executed act all name the same
    # target. Ambiguous phrases are left as written and rejected later, never guessed.
    if mo["type"] in ("assign_office", "vacate_office"):
        mo["subject"] = canonical_office(mo["subject"])
    elif mo["type"] == "diplomacy":
        mo["subject"] = canonical_diplomacy_subject(mo["subject"])
        if mo["subject"] == "loan":
            amount = parse_loan_amount(mo["value"])
            if amount is None:
                amount = parse_loan_amount(mo["action"].get("amount"))
            if amount is not None:
                mo["value"] = format(amount, ".12g")
    elif mo["type"] == "settle_arrears":
        mo["subject"] = canonical_funding(mo["subject"])
    if mo["type"] == "disaster_relief":
        _infer_relief_action(w, mo)
    if mo["type"] == "investigation":
        # 'navy procurement' names the navy; an empty value is an order to open it.
        from . import audits
        mo["subject"] = audits.office_of(mo["subject"]) or mo["subject"]
        mo["value"] = audits.parse_action(mo["value"]) or mo["value"]
    explicit = raw.get("conditions") if isinstance(raw.get("conditions"), list) else []
    clean = []
    for c in explicit:
        if not isinstance(c, dict):
            continue
        try:
            clean.append({"metric": str(c.get("metric", "")).strip(),
                          "operator": str(c.get("operator", "")).strip(),
                          "value": float(c.get("value")),
                          "source": words(c.get("source", "explicit"), 20)})
        except (TypeError, ValueError):
            continue
    if clean:
        mo["conditions"] = _derive_conditions({**mo, "conditions": clean})
    named = mo["action"].get("action_type")
    if named in DIPLOMATIC_ACTION_TYPES:
        derived = ACTION_TO_SUBJECT.get(named, named)
        # Keep whatever the delegate also said, so a stale or contradicting field is visible to the
        # consistency check rather than silently overwritten.
        # 'loan_request' as the subject of a loan_request act says the same thing in the action's own
        # words (the engine's name for it is 'loan'); only a different act is a contradiction.
        if mo["subject"] and mo["subject"] not in (derived, named):
            mo["declared_subject"] = mo["subject"]
        if mo["type"] and mo["type"] != "diplomacy":
            mo["declared_type"] = mo["type"]
        mo["type"] = "diplomacy"
        mo["subject"] = derived
    return mo


def _explicit_action(w, raw) -> dict:
    """The act the delegate says the motion is, stated in its own fields rather than inferred.

    A diplomatic motion that names its act and its target cannot be quietly executed as a different
    one; an overloaded "proposal" type could.
    """
    if not isinstance(raw, dict):
        return {}
    # Canonicalise at intake, so the stored spelling is already the actor it names. Display
    # names, old lowercase keys and canonical ids all resolve to one actor via the alias
    # table, and prose, record and routing keep agreeing with each other from here on.
    from .motion_actions import _canonical_actor
    target = str(raw.get("target", "")).strip()
    if target:
        try:
            canonical = _canonical_actor(w, target)
        except Exception:
            canonical = None
        if canonical:
            target = canonical
    action = {"action_type": str(raw.get("action_type", "")).strip(),
              "target": target,
              "issue": words(raw.get("issue", ""), 20),
              "terms": [words(x, 20) for x in (raw.get("terms") or raw.get("demands") or [])
                        if isinstance(x, str) and words(x, 20)][:4]}
    for key in ("deal_action", "region", "amount", "funding", "funding_plan", "scope",
                "military_engineers", "regions", "measures"):
        if key in raw:
            value = raw[key]
            if key == "regions" and isinstance(value, list):
                value = list(dict.fromkeys(x for x in value if isinstance(x, str)))
            action[key] = value
    return {k: v for k, v in action.items() if v not in ("", None, [], {})}


def _infer_relief_action(w: World, motion: dict) -> None:
    """Fill relief fields only when the motion names an unambiguous executable choice."""
    from .politics import RELIEF_FUNDING, _regions_of
    action = motion["action"]
    text = " ".join((str(motion.get("subject", "")), str(motion.get("text", ""))))
    if not action.get("region") and not action.get("regions"):
        regions = _regions_of(w, text)
        if regions:
            ids = [region.id for region in regions]
            if len(ids) == 1:
                action["region"] = ids[0]
            else:
                action["regions"] = ids
    if not action.get("amount") and not motion.get("value"):
        units = r"(m|mn|million|bn|billion|k|thousand)"
        labeled = re.search(r"\b(?:total\s+(?:package\s+)?|package\s+total\s+|up\s+to\s+|about\s+|"
                            r"target(?:ing)?(?:\s+about)?\s+|budget(?:\s+of)?\s+|amount(?:\s+of)?\s+)"
                            r"(\d[\d,]*(?:\.\d+)?)\s*" + units + r"\b", text, re.I)
        amounts = re.findall(r"\b(\d[\d,]*(?:\.\d+)?)\s*" + units + r"\b", text, re.I)
        if labeled:
            action["amount"] = labeled.group(1) + labeled.group(2)
        elif len({(value.replace(",", ""), unit.lower()) for value, unit in amounts}) == 1:
            value, unit = amounts[0]
            action["amount"] = value + unit
    if not action.get("funding") and not action.get("funding_plan"):
        source_patterns = {"foreign credit": "foreign_credit", "credit line": "foreign_credit",
                           "reallocation": "reallocation", "bond": "bonds", "reserve": "reserves"}
        allocation_pattern = re.compile(
            r"\b(?P<amount>\d[\d,]*(?:\.\d+)?\s*(?:m|mn|million|bn|billion|k|thousand))"
            r"\s*(?:gold\s*)?(?:from\s+)?(?P<source>foreign\s+credit|credit\s+line|"
            r"reallocation|bonds?|reserves?)\b", re.I)
        allocations = []
        for match in allocation_pattern.finditer(text):
            source_text = re.sub(r"\s+", " ", match.group("source").lower())
            source = next((canonical for pattern, canonical in source_patterns.items()
                           if source_text.startswith(pattern)), None)
            if source:
                allocations.append({"source": source, "amount": re.sub(r"\s+", "", match.group("amount"))})
        if len(allocations) > 1:
            action["funding_plan"] = allocations
    if not action.get("funding") and not action.get("funding_plan"):
        funding_terms = {"foreign_credit": ("foreign credit", "credit line", "foreign_credit"),
                         "reallocation": ("reallocation", "reallocated"),
                         "reserves": ("reserves", "reserve drawdown"),
                         "bonds": ("bonds", "bond issue", "bond issuance")}
        matches = [choice for choice in RELIEF_FUNDING
                   if any(re.search(r"\b" + re.escape(term) + r"\b", text, re.I)
                          for term in funding_terms[choice])]
        if len(matches) == 1:
            action["funding"] = matches[0]
    if not action.get("scope"):
        scope_terms = {"ports": ("port", "harbour", "harbor"), "roads": ("road",),
                       "fields": ("field", "farm", "harvest"), "housing": ("housing", "homes"),
                       "food": ("food", "grain")}
        matches = [choice for choice, terms in scope_terms.items()
                   if any(re.search(r"\b" + re.escape(term) + r"\w*\b", text, re.I) for term in terms)]
        if len(matches) == 1:
            action["scope"] = matches[0]
        elif len(matches) > 1 or re.search(r"\bmixed\b", text, re.I):
            action["scope"] = "mixed"
    if "military_engineers" not in action and re.search(r"\bengineers?\b", text, re.I):
        action["military_engineers"] = True


def _shares(raw) -> list:
    return [{"report_id": str(x.get("report_id", "")), "with": str(x.get("with", "council")).strip().upper()
             if str(x.get("with", "council")).strip().lower() != "council" else "council"}
            for x in (raw if isinstance(raw, list) else []) if isinstance(x, dict)][:3]


def normalize_session_v2(w: World, mid: str, data, dm_quota: int) -> tuple:
    base, problems = normalize_session(w, mid, data, dm_quota)
    if not isinstance(data, dict):
        base.update(private_position={k: "" for k in POSITION_FIELDS}, communications=[], information_requests=[],
                    share_reports=[], agenda_priorities=[], strategy={})
        return base, problems
    raw_pos = data.get("private_position")
    if isinstance(raw_pos, dict):
        position = {k: words(raw_pos.get(k, ""), 30) for k in POSITION_FIELDS}
    else:
        position = {k: "" for k in POSITION_FIELDS}
        position["preferred_policy"] = words(raw_pos or "", 45)
    base["private_position"] = position
    forced = []
    for mo, raw in zip(base["motions"], [m for m in (data.get("motions") or []) if isinstance(m, dict)]):
        mo["force_agenda"] = raw.get("force_agenda") is True
    base["private_messages"] = _v2_dms(w, mid, data.get("private_messages"), dm_quota, problems)
    base["communications"] = _comms(data.get("communications"), problems)
    base["information_requests"] = [{"topic": str(x.get("topic", "")), "motion_id": str(x.get("motion_id", ""))}
                                    for x in (data.get("information_requests") or []) if isinstance(x, dict)][:2]
    base["share_reports"] = (_shares(data.get("share_reports"))
                             + _legacy_report_shares(w, mid, data.get("communications")))[:3]
    from .deliberation import TOPICS
    base["agenda_priorities"] = [x for x in (data.get("agenda_priorities") or []) if x in TOPICS][:4] \
        if "head" in w.offices_of(mid) else []
    base["strategy"] = data.get("strategy") if isinstance(data.get("strategy"), dict) else {}
    del forced
    return base, problems


def _withdrawals(raw, mine: set, ids: set) -> list:
    """Withdrawals in the structured form, with the reason and any replacement kept for the record.

    Runs saved before the reason was asked for carry a bare motion id; those still parse.
    """
    out = []
    for item in raw or []:
        if isinstance(item, str):
            if item in mine:
                out.append({"motion_id": item, "reason": "", "replaced_by": ""})
            continue
        if not isinstance(item, dict):
            continue
        motion_id = str(item.get("motion_id") or item.get("id") or "").strip()
        if motion_id not in mine:
            continue
        replaced = str(item.get("replaced_by") or "").strip()
        out.append({"motion_id": motion_id,
                    "reason": words(item.get("reason", ""), 25),
                    "replaced_by": replaced if replaced in ids and replaced != motion_id else ""})
    return out


def normalize_revision(w: World, mid: str, data, motions: list, dm_quota: int) -> tuple:
    problems = []
    empty = {"response": "", "stances": {}, "demands": [], "withdraw": [], "amend": [], "communications": [],
             "share_reports": [], "private_messages": []}
    if not isinstance(data, dict):
        return empty, ["no answer"]
    ids = {m["id"] for m in motions}
    own = {m["id"] for m in motions if m["proposer"] == mid}
    sponsored_ids = {m["id"] for m in motions if mid in m.get("cosponsors", [])}
    stances = data.get("stances") if isinstance(data.get("stances"), dict) else {}
    out = {"response": words(data.get("response", ""), RESPONSE_WORDS),
           "stances": {k: v for k, v in stances.items() if k in ids and v in ("support", "oppose", "undecided", "conditional")},
           "demands": [{"motion_id": x.get("motion_id"), "demand": words(x.get("demand", ""), 30), "member": mid}
                       for x in (data.get("demands") or []) if isinstance(x, dict) and x.get("motion_id") in ids
                       and words(x.get("demand", ""), 30)][:2],
           "withdraw": _withdrawals(data.get("withdraw"), own | sponsored_ids, ids),
            "amend": [{"motion_id": x.get("motion_id"), "value": str(x.get("value", "")).strip(),
                       "text": words(x.get("text", ""), 120),
                       **({"measures": [{"lever": str(m.get("lever", "")),
                                         "value": str(m.get("value", ""))}
                                        for m in x.get("measures", []) if isinstance(m, dict)]}
                          if isinstance(x.get("measures"), list) else {})}
                     for x in (data.get("amend") or []) if isinstance(x, dict) and x.get("motion_id") in own][:1],
           "communications": _comms(data.get("communications"), problems)[:1],
           "share_reports": _shares(data.get("share_reports")),
           "private_messages": _v2_dms(w, mid, data.get("private_messages"), dm_quota, problems)}
    return out, problems


def normalize_decision_v2(w: World, mid: str, data, motion_ids: list, dm_quota: int) -> tuple:
    from .deliberation import METRICS
    base, problems = normalize_decision(w, mid, data if isinstance(data, dict) else None,
                                        motion_ids, dm_quota, defer_to_v2=True)
    base.setdefault("operations", {})
    base.setdefault("belief_updates", [])
    base.setdefault("forecasts", [])
    base.setdefault("election_response", "")
    if not isinstance(data, dict):
        return base, problems
    conditions = {}
    for item in data.get("vote_conditions") or []:
        if not isinstance(item, dict):
            continue
        motion_id = item.get("motion_id")
        if motion_id not in motion_ids or base["votes"].get(motion_id) != "conditional":
            continue
        kind = item.get("kind", "metric")
        if_unmet = item.get("if_unmet") if item.get("if_unmet") in ("no", "abstain") else "abstain"
        if kind == "motion":
            other = item.get("other_motion")
            if other not in motion_ids or other == motion_id:
                problems.append(f"invalid motion condition for {motion_id}")
                continue
            condition = {"kind": "motion", "other_motion": other,
                         "other_outcome": item.get("other_outcome") if item.get("other_outcome") in ("passes", "fails") else "passes",
                         "if_unmet": if_unmet}
            conditions.setdefault(motion_id, []).append(condition)
            continue
        metric, operator = item.get("metric"), item.get("operator")
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            problems.append(f"invalid vote condition value for {motion_id}")
            continue
        if metric not in METRICS or operator not in (">=", "<=") or not -1e12 <= value <= 1e12:
            problems.append(f"invalid vote condition for {motion_id}")
            continue
        from .motion_actions import canonical_metric_value
        value = canonical_metric_value(metric, value)
        condition = {"kind": "metric", "metric": metric, "operator": operator, "value": value,
                     "if_unmet": if_unmet}
        conditions.setdefault(motion_id, []).append(condition)
    for i in motion_ids:
        if base["votes"].get(i) == "conditional" and i not in conditions:
            problems.append(f"conditional vote missing valid condition for {i}")
    conditions = {key: value[0] if len(value) == 1 else value for key, value in conditions.items()}
    base["vote_conditions"] = conditions
    raw_ops = data.get("operations") if isinstance(data.get("operations"), dict) else {}
    base["operations"] = {o: v for o, v in raw_ops.items() if o in w.offices_of(mid) and isinstance(v, dict)}
    updates = []
    for item in data.get("belief_updates") or []:
        if isinstance(item, dict) and item.get("direction") in ("more_likely", "less_likely"):
            updates.append({"proposition": str(item.get("proposition", "")), "direction": item["direction"],
                            "reason": words(item.get("reason", ""), 30)})
    base["belief_updates"] = updates[:3]
    base["forecasts"] = [item for item in (data.get("forecasts") or [])[:2] if isinstance(item, dict)]
    response = str(data.get("election_response", "")).strip().lower()
    base["election_response"] = response if response in ("concede", "legal_challenge", "request_recount",
                                                          "negotiate_coalition", "resign", "refuse") else ""
    base["private_messages"] = _v2_dms(w, mid, data.get("private_messages"), dm_quota, problems)
    return base, problems
