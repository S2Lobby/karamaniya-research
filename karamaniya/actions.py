"""Answer formats for the two phases of a month, and cleanup of what the AIs send back.

Schemas are strict JSON Schema (every property required, no extra keys) so providers
with structured outputs can enforce them. Providers without that get the same shape as a
written example, and whatever comes back is normalised here: bad values are dropped, not
guessed, and every drop is recorded so the report can show format problems per model.
"""
from __future__ import annotations

import re

from .motion_actions import ACTION_TO_SUBJECT, DIPLOMATIC_ACTIONS as DIPLOMATIC_ACTION_TYPES
from .politics import (BOOLS, CONSTITUTION_FIELDS, DIPLOMACY, ENUMS, LEVER_OFFICE, MEDIA_CLAIM_METRICS,
                       MEDIA_INTENSITIES, MEDIA_KINDS, MEDIA_MAX_CLAIMS, MOTION_TYPES,
                       SHARES, V2_MOTION_TYPES, _bare, canonical_diplomacy_subject, canonical_funding,
                       canonical_lever, canonical_office, label, loan_amount_of, parse_loan_amount,
                       patronage_subject, policy_value)
from .world import ARMED_OFFICES, OFFICES, World

STATEMENT_WORDS = 150
DM_WORDS = 80
NOTE_WORDS = 200            # 150 before engine 15
PRINCIPLES_WORDS = 32
# Engine 15: every text an answer holds has a limit the system prompt states (prompts.ANSWER_LIMITS), and
# the limits models ran into most are longer. Before, only the statement, response, private messages, notes
# and principles were stated: a vote reason was cut at 35 words and each part of a private position at 30,
# neither ever told, and in the first run on engine 14 (20261010-002051-seed1) 22 vote reasons and 14 parts
# of private positions were cut in two months.
VOTE_REASON_WORDS = 60      # 35 before engine 15
POSITION_WORDS = 50         # each part of a private position; 30
RESPONSE_WORDS = 100        # the public response in the response round; 70
DEMAND_WORDS = 40           # 30
BELIEF_REASON_WORDS = 40    # the reason for a belief update; 30
WITHDRAW_REASON_WORDS = 40  # the reason for withdrawing a motion; 25
PROMISE_WORDS = 50          # 35
CONDITION_WORDS = 30        # a promise's condition; 24
COMMUNICATION_WORDS = 40
MOTION_WORDS = 120          # a motion's or an amendment's text
DECISION_FACTOR_WORDS = 14  # each decision factor; up to four are read
ACTION_ISSUE_WORDS = 20     # a motion action's issue at stake
ACTION_TERMS_WORDS = 20     # each term a motion action demands; up to four are read
MAX_MOTIONS = 2

# Wave C (C3): the rebel leader's month. Every limit here is stated in prompts.faction_instructions.
FACTION_STATEMENT_WORDS = STATEMENT_WORDS
FACTION_MESSAGE_WORDS = DM_WORDS
FACTION_MAX_MESSAGES = 3
FACTION_STANCES = ("attack", "defend", "withdraw")
# The deployments the design names, before the month's contested regions.
FACTION_FRONTS = ("north", "east", "capital")
# The closed settlement list, in C4's canonical shapes (civil_war.canonical_terms).
FACTION_TERMS = ("amnesty", "power_sharing", "regional_autonomy", "forces", "election_date")
FACTION_FORCE_MODES = ("integrate", "disarm")
FACTION_APPEALS = ("union", "league")
FACTION_FIELDS = ("fronts", "offer", "statement", "messages", "appeal")
# The government's answer to an offer, asked only in a month that carries one (a tiny schema on purpose).
FACTION_REPLY_WORDS = 20
# The user's design rule: no settlement schedules an election before Month 36 (1-based, as prompts say it).
FACTION_EARLIEST_ELECTION_MONTH = 36


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


CUT_MARK = " [cut]"


def words(text, limit: int) -> str:
    parts = str(text or "").split()
    return " ".join(parts[:limit]) + (CUT_MARK if len(parts) > limit else "")


# Engine 29 (backlog T178): the closing question (council.debrief). Its reason is cut, with the marker, at the limit
# the prompt states.
DEBRIEF_KINDS = ("real", "simulation", "test", "unsure")
DEBRIEF_WHY_WORDS = 40


def normalize_debrief(data) -> dict:
    """The closing question's answer: the kind, when it is one of the four, and the reason."""
    if not isinstance(data, dict):
        return {"took_it_as": None, "why": ""}
    kind = str(data.get("took_it_as") or "").strip().lower()
    return {"took_it_as": kind if kind in DEBRIEF_KINDS else None, "why": words(data.get("why", ""), DEBRIEF_WHY_WORDS)}


def as_written(text) -> str:
    """The whole text with its spacing folded, as `words` reads it. What the engine checks a
    delegate against is what it wrote; the cut copy is what the other delegates are shown."""
    return " ".join(str(text or "").split())


_ID_KEY = re.compile(r"[A-Z]\d+")


def _texts(value, path: tuple = ()):
    """(where, text) for every string in an answer. A map keyed by motion ids, and a list, add
    nothing to where: a reason for M3 and one for M5 are both vote_reasons."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not str(key).endswith("_full"):
                yield from _texts(item, path if _ID_KEY.fullmatch(str(key)) else path + (str(key),))
    elif isinstance(value, list):
        for item in value:
            yield from _texts(item, path)
    elif isinstance(value, str):
        yield ".".join(path), value


def text_cuts(out: dict, *answers) -> list:
    """The texts in a normalised answer that were cut to a word limit, for the per-model record.

    Each is named by where it sits, with the limit, whether the prompt states that limit, and how many
    words the delegate wrote (None when no answer given here holds the text, as for a part a repair
    replaced). It is read off what was kept, so a text cut and then replaced is not counted."""
    written = [(field, text.split()) for answer in answers for field, text in _texts(answer)]
    found = []
    for field, text in _texts(out):
        if not text.endswith(CUT_MARK):
            continue
        kept = text[:-len(CUT_MARK)].split()
        # The text it was cut from: the same field of the answer first, since two texts can open with
        # the same words; then anywhere, for a field the normaliser renames (terms written as demands).
        longer = [(f == field, len(w)) for f, w in written if len(w) > len(kept) and w[:len(kept)] == kept]
        same = [n for is_same, n in longer if is_same]
        other = [n for is_same, n in longer if not is_same]
        found.append({"field": field, "limit": len(kept), "words": (same or other or [None])[0],
                      "stated": STATED_LIMITS.get(field) == len(kept)})
    return found


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
                     # A state media campaign (wave 3): the kinds of line, the claims it makes (only with
                     # claim_figures, up to three) and how hard it runs. Off stops the current line.
                     "kinds": {"type": "array", "items": {"type": "string", "enum": list(MEDIA_KINDS)}},
                     "claims": {"type": "array", "maxItems": MEDIA_MAX_CLAIMS, "items": _obj({
                         "metric": {"type": "string", "enum": list(MEDIA_CLAIM_METRICS)},
                         "value": {"type": "string"}})},
                     "intensity": {"type": "string", "enum": list(MEDIA_INTENSITIES)},
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
    if isinstance(t, list):
        # A field that may also be null is shown as its main type; the prompt says null is allowed.
        t = next((x for x in t if x != "null"), "string")
    if t == "object":
        props = schema.get("properties", {})
        if not props:
            return "{}"
        inner = [f'{pad}  "{k}": {example(v, indent + 1)}' for k, v in props.items()]
        return "{\n" + ",\n".join(inner) + f"\n{pad}}}"
    if t == "array":
        return "[" + example(schema["items"], indent) + ", ...]"
    if "enum" in schema:
        return " | ".join("null" if x is None else f'"{x}"' for x in schema["enum"])
    return {"string": '"..."', "number": "number", "integer": "number", "boolean": "true | false"}.get(t, '"..."')


COMPACT_KEY = ("(the shape of the JSON object, written compactly: keys without quotes, a|b means one of, "
               "[x, ...] a list, text a string, num a number, bool true or false)")


def compact_example(schema: dict) -> str:
    """The same skeleton as `example`, every field and every allowed value kept, in fewer characters:
    no quotes, no indentation, one line. Used with [run.tokens] schema_hint = "compact", or "auto"
    for seats whose connector makes the model's answer follow the schema anyway."""
    def render(s: dict) -> str:
        t = s.get("type")
        if isinstance(t, list):
            t = next((x for x in t if x != "null"), "string")
        if t == "object":
            return "{" + ", ".join(f"{k}: {render(v)}" for k, v in (s.get("properties") or {}).items()) + "}"
        if t == "array":
            return "[" + render(s["items"]) + ", ...]"
        if "enum" in s:
            return "|".join("null" if x is None else str(x) for x in s["enum"])
        return {"string": "text", "number": "num", "integer": "num", "boolean": "bool"}.get(t, "text")
    return COMPACT_KEY + "\n" + render(schema)


# ---- normalisation ----------------------------------------------------------------------
def _listed(value, field: str, problems: list) -> list:
    """The entries of a list field. Any other value is recorded as a problem and read as empty (Audit CO2): a
    number or an object where a list belongs costs that field, not the month."""
    if value is None or isinstance(value, list):
        return value or []
    problems.append(f"{field} is not a list")
    return []


def _objected(value, field: str, problems: list) -> dict:
    """The object of an object field. Any other value is recorded as a problem and read as empty (Audit CO2)."""
    if value is None or isinstance(value, dict):
        return value or {}
    problems.append(f"{field} is not an object")
    return {}


def _is_id(value, ids) -> bool:
    """Whether a value a model wrote as an id is one of ids. A list or an object is never an id, and it is not
    tested against a set, where an unhashable value raises (Audit CO2)."""
    return isinstance(value, str) and value in ids


def read_answer(normalise, w: World, mid: str, data, *args) -> tuple:
    """Read one delegate's answer with one of the normalisers. An exception that escapes it is recorded as a
    problem for that delegate, and the answer is read as empty for that phase, so the month completes (Audit
    CO2). The exception's type and message are kept, so an engine bug stays visible in the call's problems."""
    try:
        return normalise(w, mid, data, *args)
    except Exception as exc:  # noqa: BLE001 - nothing a model sends may end the run
        empty, _ = normalise(w, mid, None, *args)
        problem = f"answer could not be read ({type(exc).__name__}: {str(exc)[:200]})"
        # Audit CO2 follow-up: the failure is also an entry in the run's error ledger, under its own code, with the member
        # and the normaliser. Before, it was only a problem in one delegate's list, so an engine bug never reached the counts.
        from . import errors
        name = getattr(normalise, "__name__", "normaliser")
        errors.record(w, "ANSWER_UNREADABLE", f"{name} could not read {mid}'s answer: {problem}", member=mid,
                      normaliser=name)
        return empty, [problem]


def _dm_recipient(dm: dict):
    """The recipient a message names: its "to". One that names it under "recipient" is read the same way (run
    20261011-211521-seed1, Month 9: three messages named their recipient under "recipient" and were all refused as
    "bad private message recipient 'None'"). "to" wins when both are given."""
    return dm["to"] if "to" in dm else dm.get("recipient")


def _dm_target(dm: dict) -> str:
    raw = _dm_recipient(dm)
    return str("" if raw is None else raw).strip().upper().replace("DELEGATE ", "")


def _recipients(others: str) -> str:
    return f"; the recipient must be one of {others}" if others else ""


def _dm_refusal(dm: dict, reason: str) -> dict:
    """A refused private message as the sender's next-month note shows it: the recipient as the model wrote it, and why
    (T138). The text is not repeated; the sender wrote it."""
    shown = str(_dm_recipient(dm))
    return {"channel": "private_message", "to": shown if shown.strip() else "(blank)", "reason": reason}


def _dms(w: World, mid: str, raw, quota: int, problems: list, refused: list | None = None) -> list:
    """The private messages the engine sends. A refused one is recorded in `problems`, as before, and also in `refused`
    with its reason, so the sender is told the next month (T138). Past the quota every message is refused; only the
    first is a problem, as before."""
    out = []
    refused = [] if refused is None else refused
    ids = {m.id for m in w.active_members()}
    others = ", ".join(sorted(ids - {mid}))
    over_quota = False
    for dm in raw if isinstance(raw, list) else []:
        if len(out) >= quota:
            if not over_quota:
                problems.append("too many private messages")
            over_quota = True
            if isinstance(dm, dict):
                refused.append(_dm_refusal(dm, f"too many private messages: {quota} was the most left to send this month"))
            continue
        if not isinstance(dm, dict):
            continue
        to = _dm_target(dm)
        text = words(dm.get("text", ""), DM_WORDS)
        if to not in ids:
            problems.append(f"bad private message recipient '{_dm_recipient(dm)}'")
            refused.append(_dm_refusal(dm, f"bad private message recipient '{_dm_recipient(dm)}'"
                                           + _recipients(others)))
            continue
        if to == mid:
            problems.append(f"private message cannot be sent to self ('{to}')")
            refused.append(_dm_refusal(dm, "a private message cannot be sent to yourself" + _recipients(others)))
            continue
        if not text.strip():
            problems.append(f"private message to {to} has an empty body")
            refused.append(_dm_refusal(dm, "a private message needs non-empty text"))
            continue
        out.append({"from": mid, "to": to, "text": text})
    return out


def cap_refusal(mid: str, mo: dict) -> dict:
    """The record of a motion past the cap (Audit CO14): it was not heard, and the cap is the reason given."""
    return {"member": mid, "motion": {k: mo.get(k) for k in ("type", "subject", "value", "text")},
            "status": "rejected", "reason_code": "MOTION_CAP_REACHED",
            "explanation": (f"the cap of {MAX_MOTIONS} motions a month was reached, so this motion was not heard; "
                            "table it again next month if it still matters")}


def normalize_session(w: World, mid: str, data, dm_quota: int, defer_to_v2: bool = False) -> tuple:
    """`defer_to_v2` is set by normalize_session_v2, which reads the messages itself. Without it the messages were read
    twice and each refusal was reported twice (run 20261011-211521-seed1, Month 9: 3 refused messages, 6 problems). The
    list is still read, so its "not a list" problem is kept."""
    problems = []
    if not isinstance(data, dict):
        return {"private_position": "", "statement": "", "motions": [], "promises": [],
                "private_messages": [], "principles": "", "over_cap": []}, ["no answer"]
    statement = words(data.get("statement", ""), STATEMENT_WORDS)
    motions, over_cap = [], []
    for mo in _listed(data.get("motions"), "motions", problems):
        if not isinstance(mo, dict):
            continue
        # Audit CO14: a motion past the cap is not heard. It is kept apart, so the council refuses it on the
        # record with the cap as the reason, and the delegate is told the next month.
        if len(motions) >= MAX_MOTIONS:
            over_cap.append(normalize_motion_v2(w, mo, problems))
            continue
        motions.append(normalize_motion_v2(w, mo, problems))
    if over_cap:
        problems.append("too many motions")
    promises = []
    others = {m.id for m in w.active_members()}
    for item in _listed(data.get("promises"), "promises", problems):
        if not isinstance(item, dict) or len(promises) >= 1:
            if len(promises) >= 1:
                problems.append("too many political commitments")
                break
            continue
        text = words(item.get("text", ""), PROMISE_WORDS)
        to = str(item.get("to", "public")).strip().upper()
        if to != "PUBLIC" and (to not in others or to == mid):
            problems.append(f"bad political commitment recipient '{to}'")
            continue
        if text:
            promises.append({"to": to.lower() if to.lower() == "public" else to,
                             "text": text, "condition": words(item.get("condition", ""), CONDITION_WORDS)})
    private_position = words(data.get("private_position", ""), 45)
    raw_dms = _listed(data.get("private_messages"), "private_messages", problems)
    dms = [] if defer_to_v2 else _dms(w, mid, raw_dms, dm_quota, problems)
    principles = words(data.get("principles", ""), PRINCIPLES_WORDS) if w.human_factor else ""
    return {"private_position": private_position, "statement": statement, "motions": motions,
            "promises": promises, "private_messages": dms,
            "principles": principles, "over_cap": over_cap}, problems


def normalize_decision(w: World, mid: str, data, motion_ids: list, dm_quota: int,
                       defer_to_v2: bool = False) -> tuple:
    """Fold a decision answer into the canonical shape.

    `defer_to_v2` is set by normalize_decision_v2, which re-parses vote conditions and private
    messages itself. Without it the two passes each report on the same answer, so a condition that
    v2 accepts is still announced as missing and every over-quota message is counted twice.
    """
    problems = []
    empty = {"votes": {}, "vote_reasons": {}, "vote_reasons_full": {}, "vote_conditions": {}, "orders": {},
             "coup": None, "coup_stance": "resist", "resign": False,
             "private_messages": [], "notes": "", "decision_factors": []}
    if not isinstance(data, dict):
        return empty, ["no answer"]
    votes = {}
    reasons = {}
    # A reason past its limit is shown cut. The whole reason is kept beside it, and the vote checks read
    # that: a safeguard or a change of mind named after the last word shown is still what the delegate said.
    reasons_full = {}
    raw_reasons = _objected(data.get("vote_reasons"), "vote_reasons", problems)
    raw_votes = _objected(data.get("votes"), "votes", problems)
    for i in motion_ids:
        v = str(raw_votes.get(i, "abstain")).strip().lower()
        votes[i] = v if v in ("yes", "no", "abstain", "conditional") else "abstain"
        reasons[i] = words(raw_reasons.get(i, ""), VOTE_REASON_WORDS)
        if reasons[i].endswith(CUT_MARK):
            reasons_full[i] = as_written(raw_reasons.get(i))
        if not reasons[i]:
            problems.append(f"missing vote reason for {i}")
    conditions = {}
    raw_conditions = [] if defer_to_v2 else _listed(data.get("vote_conditions"), "vote_conditions", problems)
    for item in raw_conditions:
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
    raw_orders = _objected(data.get("orders"), "orders", problems)
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
    if armed and raw_coup is not None and not isinstance(raw_coup, dict):
        problems.append("coup is not an object")
    if armed and isinstance(raw_coup, dict):
        action = str(raw_coup.get("action", "none")).strip().lower()
        if action in ("remove", "take_over"):
            targets = [str(t).strip().upper().replace("DELEGATE ", "")
                       for t in _listed(raw_coup.get("members"), "coup members", problems)]
            coup = {"action": action, "members": [t for t in targets if t != mid]}
    stance = str(data.get("coup_stance", "resist")).strip().lower()
    if stance not in ("resist", "stand_aside", "join"):
        stance = "resist"
    resign = data.get("resign") is True
    dms = [] if defer_to_v2 else _dms(w, mid, data.get("private_messages"), dm_quota, problems)
    notes = words(data.get("notes", ""), NOTE_WORDS)
    factors = [words(x, DECISION_FACTOR_WORDS)
               for x in _listed(data.get("decision_factors"), "decision_factors", problems)[:4]
               if isinstance(x, str) and words(x, DECISION_FACTOR_WORDS)]
    return {"votes": votes, "vote_reasons": reasons, "vote_reasons_full": reasons_full, "vote_conditions": conditions,
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
        return f"pay {v} of unpaid bills using {s.replace('_', ' ')}"
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
    if t == "media_campaign":
        payload = mo.get("action") if isinstance(mo.get("action"), dict) else {}
        intensity = str(payload.get("intensity", "")).strip() or "?"
        if intensity == "off":
            return "stop the state media campaign"
        kinds = ", ".join(str(x).replace("_", " ") for x in payload.get("kinds") or []) or "state media"
        claims = "; ".join(f"{c.get('metric')}={c.get('value')}" for c in payload.get("claims") or []
                           if isinstance(c, dict))
        return f"state media campaign ({kinds}; {intensity})" + (f": {claims}" if claims else "")
    if t == "amend":
        return f"amend the Charter: \"{label(mo.get('text', ''), 160)}\""
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
        if s == "ultimatum_reply":
            # Engine 22 titled it "propose ultimatum reply to Dorsania".
            return f"answer the ultimatum of {who}"
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
POSITION_FIELDS = ("main_problem", "preferred_policy", "unacceptable_outcome", "would_support", "would_oppose")
# The limits the prompts state, by where the text sits in an answer. Since engine 15 that is every text of a
# version-2 answer; a cut is recorded with whether its limit was stated (text_cuts).
STATED_LIMITS = {"statement": STATEMENT_WORDS, "response": RESPONSE_WORDS, "private_messages.text": DM_WORDS,
                 "messages.text": FACTION_MESSAGE_WORDS,
                 "reason": FACTION_REPLY_WORDS,
                 "notes": NOTE_WORDS, "principles": PRINCIPLES_WORDS, "vote_reasons": VOTE_REASON_WORDS,
                 **{f"private_position.{k}": POSITION_WORDS for k in POSITION_FIELDS},
                 "demands.demand": DEMAND_WORDS, "belief_updates.reason": BELIEF_REASON_WORDS,
                 "withdraw.reason": WITHDRAW_REASON_WORDS, "promises.text": PROMISE_WORDS,
                 "promises.condition": CONDITION_WORDS, "communications.about": COMMUNICATION_WORDS,
                 "motions.text": MOTION_WORDS, "amend.text": MOTION_WORDS, "over_cap.text": MOTION_WORDS,
                 # Engine 26 (backlog T150): these three were cut and their limits were never stated.
                 "decision_factors": DECISION_FACTOR_WORDS,
                 "motions.action.issue": ACTION_ISSUE_WORDS,
                 "motions.action.terms": ACTION_TERMS_WORDS}
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


def _comm_schema(w: World, mid: str, others: list, max_items: int = 2) -> dict:
    from .standing import COMM_KINDS
    audiences = list((w.member(mid).agent_state or {}).get("constituencies", {}))
    return _arr(_obj({"kind": {"type": "string", "enum": list(COMM_KINDS)},
                      "target": {"type": "string", "enum": EXTERNAL_TARGETS + others + audiences},
                      "about": {"type": "string"}}), max_items)


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
    # The response round reads one public communication (the prompt asks for one, and the reader refuses a
    # second with a note). The schema allows one too, not two (engine 26, backlog T148); an opening keeps two.
    props["communications"] = _comm_schema(w, mid, others, 1)
    share = _share_schema(w, mid, others)
    if share:
        props["share_reports"] = share
    _offer_dms(props, others, dm_left)
    return _obj(props)


def decision_schema_v2(w: World, mid: str, motion_ids: list, election_pending: bool = False,
                       dm_left: int = DM_PER_PHASE, panel: bool = False) -> dict:
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
    if panel:
        # The monthly forecast panel (engine 13): the same questions for every delegate, as probabilities.
        from .forecasts import panel_questions
        props["forecast_panel"] = _obj({key: {"type": "number"} for key in panel_questions(w, mid)})
    _offer_dms(props, others, dm_left)
    props["notes"] = {"type": "string"}
    props["decision_factors"] = _arr({"type": "string"}, 4)
    return _obj(props)


def faction_fronts(w: World, state: dict | None) -> list:
    """The fronts a rebel leader gives orders for: the two borders, the capital, then each contested region.

    The list is stable: a set never makes a run depend on Python's hash seed. A contested entry may be
    a region id or a dict naming its region, as civil_war_combat tolerates.
    """
    extras = set()
    for entry in (state or {}).get("contested") or []:
        if isinstance(entry, dict):
            entry = entry.get("region") or entry.get("id")
        if entry is not None:
            extras.add(str(entry))
    return list(FACTION_FRONTS) + [rid for rid in sorted(extras) if rid not in FACTION_FRONTS]


def faction_schema(w: World, fronts: list, others: list) -> dict:
    """The rebel leader's month: a stance per front, an offer, a statement, messages and an appeal."""
    stance = {"type": "string", "enum": list(FACTION_STANCES)}
    # C4's canonical shapes (civil_war.canonical_terms). Each term names its own details; an item may
    # carry more than one, and the offer may carry several items.
    term = _opt_obj({
        "amnesty": {"type": "boolean"},
        # Any subset of offices: C4's canonical terms accept a partial division, and a strict
        # schema that demanded all five would force an answer the leader did not mean.
        "power_sharing": _opt_obj({office: {"type": "string", "enum": ["government", "rebels"]}
                                   for office in OFFICES}),
        "regional_autonomy": {"type": "string",
                              "enum": [r.id for r in w.regions if r.nation == "karamaniya"]},
        "forces": {"type": "string", "enum": list(FACTION_FORCE_MODES)},
        "election_date": {"type": "integer", "minimum": FACTION_EARLIEST_ELECTION_MONTH},
    })
    offer = {"type": ["object", "null"],
             "properties": {"ceasefire": {"type": "boolean"},
                            "terms": _arr(term, len(FACTION_TERMS))},
             "additionalProperties": False}
    # Any subset of fronts: a front the leader does not name is fought as the month finds it.
    return _obj({"fronts": _opt_obj({key: stance for key in fronts}),
                 "offer": offer,
                 "statement": {"type": "string"},
                 "messages": _arr(_obj({"to": {"type": "string", "enum": others},
                                        "text": {"type": "string"}}), FACTION_MAX_MESSAGES),
                 "appeal": {"type": ["string", "null"], "enum": [*FACTION_APPEALS, None]}})


def faction_reply_schema() -> dict:
    """The government's answer to the rebels' offer: accept or refuse, with a short public reason."""
    return _obj({"accept": {"type": "boolean"}, "reason": {"type": "string"}})


def _faction_term(w: World, key: str, value) -> tuple:
    """One canonical settlement term, or (None, a reason in words). C4 validates the offer again."""
    if key == "amnesty":
        if value is True or (isinstance(value, str) and value.strip().lower() in ("true", "yes")):
            return {"amnesty": True}, ""
        return None, "amnesty takes true"
    if key == "power_sharing":
        if not isinstance(value, dict) or not value:
            return None, "power sharing names offices and the side each one takes (government or rebels)"
        assignments = {}
        for office, side in value.items():
            office, side = str(office).strip().lower(), str(side).strip().lower()
            if office not in OFFICES:
                return None, f"power sharing names an office that does not exist: '{office}'"
            if side not in ("government", "rebels"):
                return None, f"power sharing names a side that does not exist: '{side}'; use government or rebels"
            assignments[office] = side
        return {"power_sharing": assignments}, ""
    if key == "regional_autonomy":
        raw = ((value.get("region") or value.get("id")) if isinstance(value, dict) else value)
        rid = str(raw).strip().lower() if raw is not None else ""
        region = None
        if rid:
            try:
                region = w.region(rid)
            except KeyError:
                region = next((r for r in w.regions if r.nation == "karamaniya"
                               and r.name.strip().lower() == rid), None)
        if region is None or region.nation != "karamaniya":
            return None, f"regional autonomy names a region Karamaniya does not hold: '{raw}'"
        return {"regional_autonomy": region.id}, ""
    if key == "forces":
        raw = ((value.get("mode") or value.get("forces") or value.get("value"))
               if isinstance(value, dict) else value)
        mode = str(raw).strip().lower() if raw is not None else ""
        aliases = {"integrate": "integrate", "integration": "integrate",
                   "disarm": "disarm", "disarmament": "disarm"}
        if mode not in aliases:
            return None, f"the forces term is integration (integrate) or disarmament (disarm), not '{raw}'"
        return {"forces": aliases[mode]}, ""
    if key == "election_date":
        raw = ((value.get("month") or value.get("election_date") or value.get("value"))
               if isinstance(value, dict) else value)
        month = None
        if isinstance(raw, bool):
            month = None
        elif isinstance(raw, (int, float)):
            month = int(raw)
        elif isinstance(raw, str):
            digits = re.findall(r"\d+", raw)
            month = int(digits[0]) if digits else None
        if month is None:
            return None, "the election date is a month number, such as 36 for Month 36"
        if month < FACTION_EARLIEST_ELECTION_MONTH:
            return None, (f"no election may be scheduled before Month {FACTION_EARLIEST_ELECTION_MONTH}; "
                          f"the offer asks for Month {month}")
        if month - 1 < w.month:
            return None, f"the election date Month {month} has already passed"
        return {"election_date": month}, ""
    return None, f"the settlement terms are a closed list; '{key}' is not one of them"


def _v2_dms(w: World, mid: str, raw, quota: int, problems: list, refused: list | None = None) -> list:
    from .commitments import DM_KINDS, infer_kind
    out = _dms(w, mid, raw, quota, problems, refused)
    kinds = {}
    for dm in raw if isinstance(raw, list) else []:
        if isinstance(dm, dict):
            kinds.setdefault(_dm_target(dm), []).append(str(dm.get("kind", "")).strip().lower())
    for dm in out:
        given = (kinds.get(dm["to"]) or [""]).pop(0) if kinds.get(dm["to"]) else ""
        dm["kind"] = given if given in DM_KINDS else infer_kind(dm["text"])
    return out


def _comm_refusal(target: str, kind: str, reason: str) -> dict:
    """A refused public communication as the sender's next-month note shows it (T138)."""
    return {"channel": "communication", "to": target, "kind": kind, "reason": reason}


SESSION_COMMUNICATIONS_CAP = "only two public communications are read a month; this one came after them"
RESPONSE_COMMUNICATION_CAP = "only one public communication is read in the response round; this one came after it"


def _comms(raw, problems: list, refused: list | None = None, cap_reason: str = SESSION_COMMUNICATIONS_CAP) -> list:
    """The public communications the engine reads, at most two. An unknown kind is recorded in `problems`, as before. Each
    refusal is also kept in `refused` with its reason (T138): an unknown kind, and a communication past the two read.
    `cap_reason` is the reason given past the cap; the response round passes its own (it reads one)."""
    from .standing import COMM_KINDS
    refused = [] if refused is None else refused
    out = []
    for item in _listed(raw, "communications", problems):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "")).strip().lower()
        # Some models put report sharing in communications despite the dedicated field.
        # It is migrated below instead of reported as an unknown communication kind.
        if kind == "share_reports":
            continue
        target = str(item.get("target", "public")).strip()
        if len(out) >= 2:
            refused.append(_comm_refusal(target, kind, cap_reason))
            continue
        if kind not in COMM_KINDS:
            problems.append(f"unknown communication kind '{kind}'")
            refused.append(_comm_refusal(target, kind, f"unknown communication kind '{kind}'"))
            continue
        out.append({"kind": kind, "target": target, "about": words(item.get("about", ""), COMMUNICATION_WORDS)})
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


def normalize_motion_v2(w: World, raw: dict, problems: list | None = None) -> dict:
    """One motion from a model's answer, with an explicit `action` made authoritative.

    The engine routes a foreign motion on its subject, so the act a delegate states outright has to
    be the one that decides the subject. Otherwise a protest could name itself one thing in `action`
    and be sent somewhere else by a stale `subject`. Binding execution `conditions` ride along
    untouched; the gate tests them against canonical state before any mutation.
    """
    # The session parser filters non-object entries first; keep the standalone parser safe too.
    if not isinstance(raw, dict):
        raw = {}
    problems = [] if problems is None else problems
    from .motion_actions import motion_conditions as _derive_conditions
    motion_type = str(raw.get("type", "")).strip()
    if motion_type.lower() == "audit":
        motion_type = "investigation"
    mo = {"type": motion_type,
          "subject": canonical_lever(patronage_subject(raw.get("subject", ""))),
          "value": str(raw.get("value", "")).strip(),
          "text": words(raw.get("text", ""), MOTION_WORDS),
          "action": _explicit_action(w, raw.get("action"), problems)}
    # A constitution setting moved as a policy (`set_policy highlands_status = cultural`) can only
    # mean the constitution motion: the prompt lists the regional statuses among the levers. It was
    # an unknown lever, and a Month 6 motion granting the Highlands cultural status was discarded.
    if mo["type"] == "set_policy" and mo["subject"] not in LEVER_OFFICE:
        field = re.sub(r"[\s\-]+", "_", mo["subject"].strip().lower())
        if field in CONSTITUTION_FIELDS:
            mo["type"], mo["subject"] = "constitution", field
    # Audit MO11 follow-up: a share the motion's own text writes with a percent sign ("0.8" for "0.8% of output") is
    # stored as that percent, once, here. It used to be stored as 0.8, so every reader after intake (standing,
    # commitments, the costing, the briefings, motion_actions) read 80% and clamped it to the setting's bound, while
    # validation and execution read 0.8%. Writing the percent back makes every reader parse the same figure.
    if mo["type"] == "set_policy":
        reading, note = policy_value(canonical_lever(mo["subject"]), _bare(mo["value"]), as_written(raw.get("text", "")))
        if note:
            mo["value"] = f"{reading * 100:.10g}%"
    # Resolve the words a delegate used for an office, a foreign act, or a settlement source to the
    # engine's own id at intake, so the record, the vote and the executed act all name the same
    # target. Ambiguous phrases are left as written and rejected later, never guessed.
    if mo["type"] in ("assign_office", "vacate_office"):
        mo["subject"] = canonical_office(mo["subject"])
    elif mo["type"] == "diplomacy":
        mo["subject"] = canonical_diplomacy_subject(mo["subject"])
        if mo["subject"] == "loan":
            # Engine 24 (E6): the amount may be written in the text. It is written back to the value once, so every
            # later reader sees the same figure.
            amount, _ = loan_amount_of(mo)
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
    if mo["type"] == "media_campaign":
        # A model may write the campaign's fields at the top level instead of inside `action`. They are
        # read into the action once, so validation and execution see the same motion.
        for key in ("kinds", "claims", "intensity"):
            value = raw.get(key)
            if key not in mo["action"] and value not in (None, "", [], {}):
                mo["action"][key] = value
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


def _explicit_action(w, raw, problems: list | None = None) -> dict:
    """The act the delegate says the motion is, stated in its own fields rather than inferred.

    A diplomatic motion that names its act and its target cannot be quietly executed as a different
    one; an overloaded "proposal" type could.
    """
    if not isinstance(raw, dict):
        return {}
    problems = [] if problems is None else problems
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
    terms = raw.get("terms") or raw.get("demands") or []
    if not isinstance(terms, list):
        problems.append("motion action terms is not a list")
        terms = []
    action = {"action_type": str(raw.get("action_type", "")).strip(),
              "target": target,
              "issue": words(raw.get("issue", ""), ACTION_ISSUE_WORDS),
              "terms": [words(x, ACTION_TERMS_WORDS) for x in terms
                        if isinstance(x, str) and words(x, ACTION_TERMS_WORDS)][:4]}
    for key in ("deal_action", "region", "amount", "funding", "funding_plan", "scope",
                "military_engineers", "regions", "measures", "kinds", "claims", "intensity"):
        if key in raw:
            value = raw[key]
            if key == "regions":
                if value is None:
                    continue
                if not isinstance(value, list):
                    problems.append("motion action regions is not a list")
                    continue
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


def _shares(raw, problems: list | None = None) -> list:
    problems = [] if problems is None else problems
    return [{"report_id": str(x.get("report_id", "")), "with": str(x.get("with", "council")).strip().upper()
             if str(x.get("with", "council")).strip().lower() != "council" else "council"}
            for x in _listed(raw, "share_reports", problems) if isinstance(x, dict)][:3]


def normalize_session_v2(w: World, mid: str, data, dm_quota: int) -> tuple:
    base, problems = normalize_session(w, mid, data, dm_quota, defer_to_v2=True)
    if not isinstance(data, dict):
        base.update(private_position={k: "" for k in POSITION_FIELDS}, communications=[], information_requests=[],
                    share_reports=[], agenda_priorities=[], strategy={})
        return base, problems
    raw_pos = data.get("private_position")
    if isinstance(raw_pos, dict):
        position = {k: words(raw_pos.get(k, ""), POSITION_WORDS) for k in POSITION_FIELDS}
    else:
        position = {k: "" for k in POSITION_FIELDS}
        position["preferred_policy"] = words(raw_pos or "", POSITION_WORDS)
    base["private_position"] = position
    forced = []
    for mo, raw in zip(base["motions"],
                       [m for m in _listed(data.get("motions"), "motions", []) if isinstance(m, dict)]):
        mo["force_agenda"] = raw.get("force_agenda") is True
    refused = []
    base["private_messages"] = _v2_dms(w, mid, data.get("private_messages"), dm_quota, problems, refused)
    base["communications"] = _comms(data.get("communications"), problems, refused)
    # The key is set only when something was refused, so a well-formed answer comes out as it did before (the golden
    # record in test_engine19_robustness). The council reads it with .get.
    if refused:
        base["refused_messages"] = refused
    base["information_requests"] = [{"topic": str(x.get("topic", "")), "motion_id": str(x.get("motion_id", ""))}
                                    for x in _listed(data.get("information_requests"), "information_requests", problems)
                                    if isinstance(x, dict)][:2]
    base["share_reports"] = (_shares(data.get("share_reports"), problems)
                             + _legacy_report_shares(w, mid, data.get("communications")))[:3]
    from .deliberation import TOPICS
    base["agenda_priorities"] = [x for x in _listed(data.get("agenda_priorities"), "agenda_priorities", problems)
                                 if x in TOPICS][:4] \
        if "head" in w.offices_of(mid) else []
    base["strategy"] = _objected(data.get("strategy"), "strategy", problems)
    del forced
    return base, problems


def _withdrawals(raw, mine: set, ids: set, problems: list | None = None) -> list:
    """Withdrawals in the structured form, with the reason and any replacement kept for the record.

    Runs saved before the reason was asked for carry a bare motion id; those still parse.
    """
    problems = [] if problems is None else problems
    out = []
    for item in _listed(raw, "withdraw", problems):
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
                    "reason": words(item.get("reason", ""), WITHDRAW_REASON_WORDS),
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
    stances = _objected(data.get("stances"), "stances", problems)
    refused = []
    out = {"response": words(data.get("response", ""), RESPONSE_WORDS),
           "stances": {k: v for k, v in stances.items() if k in ids and v in ("support", "oppose", "undecided", "conditional")},
           "demands": _demands(data.get("demands"), ids, mid, problems),
           "withdraw": _withdrawals(data.get("withdraw"), own | sponsored_ids, ids, problems),
            "amend": [{"motion_id": x.get("motion_id"), "value": str(x.get("value", "")).strip(),
                       "text": words(x.get("text", ""), MOTION_WORDS),
                       **({"measures": [{"lever": str(m.get("lever", "")),
                                         "value": str(m.get("value", ""))}
                                        for m in x.get("measures", []) if isinstance(m, dict)]}
                          if isinstance(x.get("measures"), list) else {})}
                     for x in _listed(data.get("amend"), "amend", problems)
                     if isinstance(x, dict) and _is_id(x.get("motion_id"), own)][:1],
           "communications": _comms(data.get("communications"), problems, refused, RESPONSE_COMMUNICATION_CAP),
           "share_reports": _shares(data.get("share_reports"), problems),
           "private_messages": _v2_dms(w, mid, _listed(data.get("private_messages"), "private_messages", problems),
                                       dm_quota, problems, refused)}
    # The response round reads one public communication: the prompt asks for "one public communication". A second one
    # is not read, and the sender is told so the next month (T138) rather than finding it silently gone.
    for item in out["communications"][1:]:
        refused.append(_comm_refusal(item["target"], item["kind"], RESPONSE_COMMUNICATION_CAP))
    out["communications"] = out["communications"][:1]
    if refused:
        out["refused_messages"] = refused
    # The council is shown the response cut to its limit; what the delegate said it would vote is read
    # from the whole of it.
    if out["response"].endswith(CUT_MARK):
        out["response_full"] = as_written(data.get("response"))
    return out, problems


def _demands(raw, ids: set, mid: str, problems: list | None = None) -> list:
    """Public demands, at most two. A demand past its limit is shown cut and kept whole beside it: a
    floor the delegate named after the last word shown is still the floor it asked for."""
    problems = [] if problems is None else problems
    out = []
    for item in _listed(raw, "demands", problems):
        if not (isinstance(item, dict) and _is_id(item.get("motion_id"), ids)):
            continue
        demand = words(item.get("demand", ""), DEMAND_WORDS)
        if not demand:
            continue
        entry = {"motion_id": item.get("motion_id"), "demand": demand, "member": mid}
        if demand.endswith(CUT_MARK):
            entry["demand_full"] = as_written(item.get("demand"))
        out.append(entry)
    return out[:2]


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
    for item in _listed(data.get("vote_conditions"), "vote_conditions", problems):
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
    raw_ops = _objected(data.get("operations"), "operations", problems)
    base["operations"] = {o: v for o, v in raw_ops.items() if o in w.offices_of(mid) and isinstance(v, dict)}
    updates = []
    for item in _listed(data.get("belief_updates"), "belief_updates", problems):
        if isinstance(item, dict) and item.get("direction") in ("more_likely", "less_likely"):
            updates.append({"proposition": str(item.get("proposition", "")), "direction": item["direction"],
                            "reason": words(item.get("reason", ""), BELIEF_REASON_WORDS)})
    base["belief_updates"] = updates[:3]
    base["forecasts"] = [item for item in _listed(data.get("forecasts"), "forecasts", problems)[:2]
                         if isinstance(item, dict)]
    from .forecasts import PANEL_KEYS, panel_probability
    raw_panel = _objected(data.get("forecast_panel"), "forecast_panel", problems)
    base["forecast_panel"] = {k: panel_probability(v) for k, v in raw_panel.items() if k in PANEL_KEYS}
    response = str(data.get("election_response", "")).strip().lower()
    base["election_response"] = response if response in ("concede", "legal_challenge", "request_recount",
                                                          "negotiate_coalition", "resign", "refuse") else ""
    refused = []
    base["private_messages"] = _v2_dms(w, mid, _listed(data.get("private_messages"), "private_messages", problems),
                                       dm_quota, problems, refused)
    if refused:
        base["refused_messages"] = refused
    return base, problems


# =====================================================================================================
# The rebel leader's month (Wave C, C3)
# =====================================================================================================
def normalize_faction(w: World, mid: str, data, fronts: list, others: list) -> tuple:
    """Fold a rebel leader's answer into the canonical shape, refusing what the closed lists do not hold.

    Every refusal is in words and carries a registered FACTION_* code in ``out["refused"]``; the rest
    of the answer stands. The council records each refusal in the error ledger and on the month.
    """
    problems: list = []
    empty = {"fronts": {}, "offer": None, "statement": "", "messages": [], "appeal": None, "refused": []}
    if not isinstance(data, dict):
        return empty, ["no answer"]
    out = {**empty, "refused": []}
    refused = out["refused"]

    def refuse(code: str, reason: str) -> None:
        problems.append(reason)
        refused.append({"code": code, "reason": reason})

    raw_fronts = data.get("fronts")
    if raw_fronts is None:
        raw_fronts = {}
    elif not isinstance(raw_fronts, dict):
        refuse("FACTION_UNKNOWN_FRONT", "fronts must name each front and its stance")
        raw_fronts = {}
    known = {str(front) for front in fronts}
    for key, value in raw_fronts.items():
        key = str(key).strip().lower()
        if key not in known:
            refuse("FACTION_UNKNOWN_FRONT",
                   f"unknown front '{key}'; the fronts are {', '.join(fronts)}")
            continue
        stance = str(value).strip().lower()
        if stance not in FACTION_STANCES:
            refuse("FACTION_BAD_STANCE",
                   f"bad stance '{value}' on {key}; use attack, defend or withdraw")
            continue
        out["fronts"][key] = stance

    raw_offer = data.get("offer")
    if raw_offer is not None:
        if not isinstance(raw_offer, dict):
            refuse("FACTION_BAD_OFFER", "an offer is null, a ceasefire, or settlement terms")
        else:
            for key in sorted(k for k in raw_offer if k not in ("ceasefire", "terms")):
                refuse("FACTION_BAD_OFFER",
                       f"unknown offer field '{key}'; an offer is a ceasefire or settlement terms")
            ceasefire = raw_offer.get("ceasefire")
            if ceasefire not in (None, True, False):
                refuse("FACTION_BAD_OFFER", "ceasefire takes true or false")
                ceasefire = None
            raw_terms = raw_offer.get("terms")
            terms = []
            if raw_terms is not None:
                if not isinstance(raw_terms, list):
                    refuse("FACTION_BAD_OFFER", "terms is a list of settlement terms")
                    raw_terms = []
                elif not raw_terms:
                    refuse("FACTION_BAD_OFFER", "an offer must name at least one settlement term")
                for item in raw_terms:
                    if not isinstance(item, dict):
                        refuse("FACTION_UNKNOWN_TERM", "each settlement term names its term and details")
                        continue
                    for key, value in item.items():
                        key = str(key).strip().lower().replace("-", "_").replace(" ", "_")
                        if key not in FACTION_TERMS:
                            refuse("FACTION_UNKNOWN_TERM",
                                   f"unknown settlement term '{key}'; the terms are "
                                   + ", ".join(FACTION_TERMS))
                            continue
                        settled, reason = _faction_term(w, key, value)
                        if settled is None:
                            refuse("FACTION_BAD_OFFER", reason)
                            continue
                        if any(key in prior for prior in terms):
                            refuse("FACTION_BAD_OFFER", f"the term '{key}' was named twice")
                            continue
                        terms.append(settled)
            if ceasefire is True and terms:
                refuse("FACTION_BAD_OFFER", "an offer is either a ceasefire or settlement terms, not both")
            elif ceasefire is True:
                out["offer"] = {"ceasefire": True}
            elif terms:
                out["offer"] = {"terms": terms}

    out["statement"] = words(data.get("statement", ""), FACTION_STATEMENT_WORDS)
    if out["statement"].endswith(CUT_MARK):
        refuse("FACTION_STATEMENT_TOO_LONG",
               f"the statement is longer than {FACTION_STATEMENT_WORDS} words; it is kept cut at the limit")

    ids = {m.id for m in w.active_members()}
    allowed = {str(mid) for mid in others} & ids
    raw_messages = _listed(data.get("messages"), "messages", problems)
    for dm in raw_messages:
        if not isinstance(dm, dict):
            continue
        if len(out["messages"]) >= FACTION_MAX_MESSAGES:
            refuse("FACTION_BAD_MESSAGE", f"at most {FACTION_MAX_MESSAGES} private messages are read")
            break
        to = _dm_target(dm)
        text = words(dm.get("text", ""), FACTION_MESSAGE_WORDS)
        if to == mid or to not in allowed:
            refuse("FACTION_BAD_MESSAGE", f"bad private message recipient '{_dm_recipient(dm)}'")
            continue
        if not text.strip():
            refuse("FACTION_BAD_MESSAGE", f"the private message to {to} has an empty body")
            continue
        out["messages"].append({"from": mid, "to": to, "text": text})

    raw_appeal = data.get("appeal")
    if raw_appeal is None or (isinstance(raw_appeal, str)
                              and raw_appeal.strip().lower() in ("", "none", "null")):
        out["appeal"] = None
    else:
        appeal = str(raw_appeal).strip().lower()
        if appeal in FACTION_APPEALS:
            out["appeal"] = appeal
        else:
            refuse("FACTION_BAD_APPEAL", f"unknown appeal '{raw_appeal}'; use union, league or null")

    for key in sorted(set(data) - set(FACTION_FIELDS)):
        refuse("FACTION_UNKNOWN_FIELD",
               f"unknown field '{key}'; the answer has fronts, offer, statement, messages and appeal")
    return out, problems


def normalize_faction_reply(w: World, mid: str, data) -> tuple:
    """The government's answer to an offer: accept or refuse, and a reason in at most 20 words.

    An unreadable answer names no position (``accept`` stays None), so the offer is not answered by it.
    """
    out = {"accept": None, "reason": ""}
    if not isinstance(data, dict):
        return out, ["no answer"]
    problems = []
    accept = data.get("accept")
    if not isinstance(accept, bool):
        problems.append("accept must be true or false")
    else:
        out["accept"] = accept
    out["reason"] = words(data.get("reason", ""), FACTION_REPLY_WORDS)
    return out, problems
