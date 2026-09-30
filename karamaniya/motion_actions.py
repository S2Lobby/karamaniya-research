"""Motion prose against structured action, and one canonical status per motion (spec 111).

Two failures this module exists to prevent.

The first is a motion whose words and whose executable payload describe different acts. A delegate
wrote a formal protest to the Solvaran Union about merchant-vessel inspections; the structured
fields said `diplomacy / trade_deal`, which routes to the Maritime League, so the engine sent the
League a trade agreement and the Union never heard the protest. Political text, structured motion,
final vote and world-state execution have to describe the same action.

The second is status. A motion withdrawn by its proposer is not a defeat, and no reader - the floor,
the chronicle, Inspect, Compare, the vote table, the analytics or an export - should be able to
reach a different conclusion from any other. So the terminal state is worked out once, here, and
stored on the motion as `status`; everything downstream reads that field rather than re-deriving it
from "not passed".

Nothing here decides what a delegate may propose. It only refuses to execute an action that is not
the one the council was shown and voted on.
"""
from __future__ import annotations

import hashlib
import json
import re

# ---- the action vocabulary -------------------------------------------------------------------------
# Canonical actor ids. These are the vocabulary a structured target is written in, because "Union"
# is not an actor: it is a word that could mean the Solvaran Union, the Maritime League's members,
# or a customs arrangement, and a target that ambiguous cannot be checked against anything. Display
# names stay for prose and for the prompt; the engine keys on these.
SOLVARAN_UNION = "SOLVARAN_UNION"
MARITIME_LEAGUE = "MARITIME_LEAGUE"
DORSANIA = "DORSANIA"
VELERIA = "VELERIA"

ACTORS = (SOLVARAN_UNION, MARITIME_LEAGUE, DORSANIA, VELERIA)
ACTOR_NAMES = {SOLVARAN_UNION: "Solvaran Union", MARITIME_LEAGUE: "Maritime League",
               DORSANIA: "Dorsania", VELERIA: "Veleria"}
# The engine's older lowercase keys, and the party names the state model uses. A saved run, a
# recorded motion and a display name all have to keep resolving to the same actor.
ACTOR_ALIASES = {"union": SOLVARAN_UNION, "league": MARITIME_LEAGUE, "dorsania": DORSANIA,
                 "veleria": VELERIA, "solvaran union": SOLVARAN_UNION,
                 "solvaran_union": SOLVARAN_UNION, "maritime league": MARITIME_LEAGUE,
                 "maritime_league": MARITIME_LEAGUE}

#: What a motion actually does. Deliberately explicit: an overloaded "proposal" type is what let a
#: protest be filed as a trade deal.
DIPLOMATIC_ACTIONS = {
    "diplomatic_protest": SOLVARAN_UNION,
    "trade_talks": SOLVARAN_UNION, "non_aggression_pact": SOLVARAN_UNION,
    "federation": SOLVARAN_UNION, "join_union": SOLVARAN_UNION, "ceasefire": SOLVARAN_UNION,
    "alliance": MARITIME_LEAGUE, "loan_request": MARITIME_LEAGUE,
    "military_aid": MARITIME_LEAGUE, "trade_deal": MARITIME_LEAGUE,
    "grain_deal": DORSANIA,
}
#: The engine's own subject vocabulary, which the diplomatic action names map onto.
ACTION_TO_SUBJECT = {"diplomatic_protest": "diplomatic_protest", "non_aggression_pact": "non_aggression",
                     "loan_request": "loan"}
SUBJECT_TO_ACTION = {v: k for k, v in ACTION_TO_SUBJECT.items()}

#: Prose that names a foreign act, strongest signal first. Each entry is (action_type, patterns).
PROSE_ACTIONS = (
    ("diplomatic_protest", (r"\bprotest", r"\bcondemn", r"\bdenounce", r"\bdemand(?:s|ing)?\s+"
                            r"(?:the\s+)?(?:cessation|an?\s+end|that\s+\w+\s+(?:cease|stop|halt))",
                            r"\bcease\s+and\s+desist")),
    ("non_aggression_pact", (r"non[\s-]?aggression", r"\brenounce\s+force", r"\bnon[\s-]?aggression\s+pact")),
    ("ceasefire", (r"\bceasefire", r"\barmistice")),
    ("federation", (r"\bfederation", r"\bfederal\s+arrangement")),
    ("join_union", (r"\brejoin", r"\breunification", r"\bjoin\s+the\s+union")),
    ("alliance", (r"\balliance", r"\bdefensive\s+pact")),
    ("military_aid", (r"\bmilitary\s+(?:aid|equipment|supplies)", r"\barms\s+shipment")),
    ("loan_request", (r"\bloan", r"\bcredit\s+facility", r"\bline\s+of\s+credit")),
    ("grain_deal", (r"\bgrain\s+(?:deal|backstop|agreement|imports|purchase)", r"\bgrain\s+through")),
    ("trade_deal", (r"\btrade\s+(?:deal|arrangement|agreement|pact)", r"\btariff", r"\btrade\s+terms")),
    ("trade_talks", (r"\btrade\s+talks",)),
)

#: Words that name an actor. The island's own names come first so "Karamaniya" is never read as a
#: foreign target.
def _actor_patterns(w) -> dict:
    names = getattr(w, "names", {}) or {}
    return {
        SOLVARAN_UNION: [names.get("union", "Solvaran Union"), r"\bthe\s+Union\b", r"\bUnion\b"],
        MARITIME_LEAGUE: [names.get("league", "Maritime League"), r"\bthe\s+League\b",
                          r"\bMaritime\s+League\b"],
        DORSANIA: [names.get("dorsania", "Dorsania")],
        VELERIA: [names.get("veleria", "Veleria")],
    }


def _hits(text: str, patterns) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


# ---- the structured side ---------------------------------------------------------------------------
def structured_action(w, motion: dict) -> dict:
    """The executable act a motion encodes, in explicit terms.

    Built from the fields the engine routes on, plus any explicit `action` object the delegate
    supplied. This is the payload that would be executed.
    """
    kind = str(motion.get("type", ""))
    subject = str(motion.get("subject", ""))
    explicit = motion.get("action") if isinstance(motion.get("action"), dict) else {}
    action_type = str(explicit.get("action_type") or SUBJECT_TO_ACTION.get(subject) or subject).strip()
    target = str(explicit.get("target") or "").strip().lower() or None
    if target:
        target = _canonical_actor(w, target)
    if kind == "diplomacy":
        target = target or DIPLOMATIC_ACTIONS.get(action_type) or DIPLOMATIC_ACTIONS.get(subject)
        return {"action_type": action_type, "target": target, "policy": None,
                "value": motion.get("value"), "issue": str(explicit.get("issue") or "").strip(),
                "terms": explicit.get("terms") or explicit.get("demands") or [],
                "kind": kind, "subject": subject}
    if kind == "set_policy":
        return {"action_type": "directive", "target": None, "policy": subject,
                "value": motion.get("value"), "issue": "", "terms": [], "kind": kind, "subject": subject}
    if kind == "settle_arrears":
        return {"action_type": "settle_arrears", "target": None, "policy": subject,
                "value": motion.get("value"), "issue": "", "terms": [], "kind": kind, "subject": subject}
    if kind == "amend":
        return {"action_type": "charter_amendment", "target": None, "policy": None, "value": None,
                "issue": "", "terms": [], "kind": kind, "subject": subject,
                "text": str(motion.get("text", ""))}
    if kind in ("assign_office", "vacate_office"):
        return {"action_type": "appointment", "target": str(motion.get("value", "")).upper() or None,
                "policy": subject, "value": motion.get("value"), "issue": "", "terms": [],
                "kind": kind, "subject": subject}
    return {"action_type": action_type or kind, "target": target, "policy": subject,
            "value": motion.get("value"), "issue": "", "terms": [], "kind": kind, "subject": subject}


# ---- execution conditions ---------------------------------------------------------------------------
#: Metrics a binding execution condition may test. Deliberately the same vocabulary as
#: conditional votes, plus the arrears-payment safeguards the live run taught us.
CONDITION_METRICS = ("food_ratio", "reserves", "reserves_after_payment", "arrears", "unemployment",
                     "army_morale", "army_arrears", "inflation", "approval", "deficit",
                     "league_credit_received", "audited_register")
CONDITION_WORDS = (
    (("reserves", "reserve", "gold", "treasury balance"), "reserves"),
    (("arrears", "unpaid bills", "unpaid bill"), "arrears"),
    (("food", "grain", "harvest", "hunger"), "food_ratio"),
    (("unemployment", "jobless"), "unemployment"),
    (("morale",), "army_morale"),
    (("inflation", "prices"), "inflation"),
    (("approval", "popularity"), "approval"),
    (("deficit",), "deficit"),
    (("league credit", "league loan", "credit clears", "credit arrives", "loan tranche",
      "league tranche"), "league_credit_received"),
    (("audit", "audited", "register verified", "verified register"), "audited_register"),
)

_CONDITION_CLAUSE = re.compile(
    r"(?:only\s+if|provided\s+that|on\s+condition\s+that|subject\s+to|as\s+long\s+as|"
    r"after|once|when|if|unless|until|while|preserv\w*|remain\w*|keep\w*|above|below|"
    r"at\s+least|no\s+less\s+than|no\s+more\s+than|not\s+below|not\s+fall|floor|cap|"
    r"credit|audit|register|league)[^.;]*", re.IGNORECASE)


def parse_conditions(text: str, motion_type: str = "", subject: str = "") -> list:
    """Binding execution safeguards read from final motion prose.

    Never invents conditions: plain payment or policy wording yields []. A floor
    ("reserves remain >= 55M"), a sequencing gate ("only after League credit
    clears") or an audit gate ("audited register") yields a structured condition
    the engine must test before mutating state. Opinion yields nothing.
    """
    clauses = [c.strip() for c in _CONDITION_CLAUSE.findall(text or "") if c.strip()]
    if not clauses:
        return []
    joined = " ; ".join(clauses).lower()
    out: list = []
    seen = set()

    def add(metric: str, operator: str, value: float, source: str):
        key = (metric, operator, round(value, 6))
        if key in seen:
            return
        seen.add(key)
        out.append({"metric": metric, "operator": operator, "value": value, "source": source[:220]})

    floor_hit = re.search(r"(reserv\w*|gold|treasury)[^.;]{0,60}?(>=|at\s+least|no\s+less\s+than|"
                          r"not\s+below|remain\w*|stay\w*|preserv\w*|keep\w*|floor|above|minimum)"
                          r"[^0-9.;]{0,20}(\d+(?:\.\d+)?)\s*(m\b|million|bn\b|billion|k\b|%)?",
                          joined)
    if floor_hit:
        try:
            amount = float(floor_hit.group(3))
        except ValueError:
            amount = 0.0
        unit = (floor_hit.group(4) or "").strip()
        if unit in ("m", "million"):
            amount *= 1e6
        elif unit in ("bn", "billion"):
            amount *= 1e9
        elif unit in ("k",):
            amount *= 1e3
        elif unit == "%" and amount > 1:
            amount /= 100
        elif not unit and amount < 1e5:
            amount *= 1e6  # bare "55" next to reserves means 55M crowns
        add("reserves_after_payment", ">=", amount, floor_hit.group(0).strip())
    if re.search(r"leagu\w*[^.;]{0,40}(credit|loan|tranche)[^.;]{0,40}"
                 r"(clear|arriv|receiv|first|before|prior|condition|release|approv)", joined) or \
       re.search(r"(after|once|when)[^.;]{0,40}leagu\w*[^.;]{0,40}(credit|loan|tranche)", joined) or \
       re.search(r"only\s+(?:if|after|once)[^.;]*leagu", joined):
        add("league_credit_received", "==", 1.0, "league credit gate")
    if re.search(r"audit", joined) and re.search(r"register|verif|certif|reconcile", joined):
        add("audited_register", "==", 1.0, "audited register gate")
    return out


#: Money is written in whatever unit the briefing spoke in: "reserves about 97M" makes a delegate write
#: 50 for fifty million. The prose parser has always read a bare "55" beside reserves as 55M; the
#: structured path did not, so an explicit floor of 50 was a floor of fifty crowns, met by any reserves
#: there have ever been. (Conditional *votes* are a different instrument, tested at vote time, and are
#: not touched.)
MONEY_METRICS = ("reserves", "reserves_after_payment", "arrears")


def _money_units(metric: str, value: float) -> float:
    """A bare figure under 100,000 beside a money metric is a number of millions."""
    if metric in MONEY_METRICS and 0 < value < 1e5:
        return value * 1e6
    return value


def motion_conditions(motion: dict) -> list:
    """The binding conditions for one motion: explicit beats derived, never invented."""
    explicit = motion.get("conditions") or motion.get("execution_conditions") or []
    if isinstance(explicit, list) and explicit:
        clean = []
        for c in explicit:
            if not isinstance(c, dict) or c.get("metric") not in CONDITION_METRICS:
                continue
            if c.get("operator") not in (">=", "<=", "=="):
                continue
            try:
                value = float(c.get("value"))
            except (TypeError, ValueError):
                continue
            clean.append({"metric": c["metric"], "operator": c["operator"],
                          "value": _money_units(c["metric"], value),
                          "source": str(c.get("source", "explicit"))[:220]})
        if clean:
            return clean
    return parse_conditions(str(motion.get("text", "")),
                            str(motion.get("type", "")), str(motion.get("subject", "")))


def condition_values(w) -> dict:
    """Canonical state one execution condition may test, in the units conditions use."""
    from .society import inflation_yoy
    e = w.econ
    league = (w.foreign or {}).get("league", {}) if getattr(w, "foreign", None) else {}
    loan = league.get("loan", {}) if isinstance(league, dict) else {}
    credit = 0.0
    try:
        if float(loan.get("principal", 0) or 0) > 0 or float(w.dip.league_loan_pending or 0) > 0 \
                or float(getattr(e, "loans_in", 0) or 0) > 0:
            credit = 1.0
    except (TypeError, ValueError):
        credit = 0.0
    audited = 0.0
    flags = getattr(w, "counters", {}) or {}
    for key in ("arrears_audited", "register_audited", "audit_complete"):
        try:
            if float(flags.get(key, 0) or 0) > 0:
                audited = 1.0
        except (TypeError, ValueError):
            continue
    return {"food_ratio": e.food_ratio, "reserves": e.gold, "reserves_after_payment": e.gold,
            "arrears": e.arrears, "unemployment": e.unemployment, "army_morale": w.mil.army.morale,
            "army_arrears": w.mil.army.arrears, "inflation": inflation_yoy(w),
            "approval": w.avg("approval") if w.k_pops() else 0.0,
            "deficit": e.deficit / max(e.gdp_nominal, 1),
            "league_credit_received": credit, "audited_register": audited}


def _reserve_floor_result(w, cond: dict, motion: dict, values: dict) -> dict:
    """A floor on reserves after a payment, tested the way it will be enforced: by sizing the payment.

    "Reserves stay at or above 50M" on a payment from reserves means pay what leaves them there. So the
    floor is met whenever some payment can be made above it, and the payment is limited to
    min(requested, reserves - floor); it fails only when there is no room at all (reserves already at
    or under the floor), and then nothing is paid. Reserves are gold and payments are crowns, so room
    and cost are both in gold here, the unit reserves are held in.
    """
    from .politics import settle_arrears_cost
    try:
        floor = float(cond.get("value"))
        reserves = float(values.get("reserves", 0))
        full = float(settle_arrears_cost(w, motion, floor=0.0))
    except (TypeError, ValueError):
        return {**cond, "met": False, "observed": None, "reason": "no canonical reading for reserves_after_payment"}
    allowed = min(full, max(0.0, reserves - floor))
    after = reserves - allowed
    no_room = full > 0 and allowed <= 0
    met = after >= floor and not no_room
    row = {**cond, "met": bool(met), "observed": after, "requested_cost": full, "allowed_cost": allowed,
           "capped": bool(met and full > 0 and allowed + 1e-6 < full)}
    if not met:
        row["reason"] = (f"reserves {reserves:,.0f} are already below the reserve floor of {floor:,.0f}"
                         if reserves < floor else
                         f"reserves {reserves:,.0f} leave no room for a payment above the reserve floor of {floor:,.0f}")
    return row


def evaluate_conditions(w, conditions: list, motion: dict | None = None) -> list:
    """Test every binding condition against current canonical state. Pure: no mutation."""
    values = condition_values(w)
    results = []
    for cond in conditions or []:
        metric = cond.get("metric")
        if metric == "reserves_after_payment" and motion is not None and cond.get("operator") == ">=":
            results.append(_reserve_floor_result(w, cond, motion, values))
            continue
        observed = values.get(metric)
        detail = ""
        if metric == "reserves_after_payment" and motion is not None:
            from .politics import settle_arrears_cost
            try:
                cost = float(settle_arrears_cost(w, motion, floor=0.0))
                observed = float(values.get("reserves", 0)) - cost
                detail = (f"reserves_after_payment would fall to {observed:,.0f} "
                          f"(floor {cond.get('value'):,.0f})")
            except (TypeError, ValueError):
                observed = None
        elif metric == "league_credit_received":
            detail = "league credit received" if observed else "no league credit received yet"
        elif metric == "audited_register":
            detail = "register audited" if observed else "register not yet audited"
        elif observed is not None:
            detail = f"observed {observed:,.4g}, required {cond.get('operator')} {cond.get('value'):,.4g}"
        if observed is None or metric not in values:
            results.append({**cond, "met": False, "observed": None,
                            "reason": f"no canonical reading for {metric}"})
            continue
        op, want = cond.get("operator"), cond.get("value")
        met = observed == want if op == "==" else (observed >= want if op == ">=" else observed <= want)
        row = {**cond, "met": bool(met), "observed": observed}
        if not met:
            row["reason"] = detail or f"condition {metric} {op} {want} not met (observed {observed})"
        results.append(row)
    return results


def condition_mismatch(w, motion: dict) -> dict | None:
    """Final text says 'only after X' but the stored conditions would run now: block."""
    text_conds = parse_conditions(str(motion.get("text", "")),
                                  str(motion.get("type", "")), str(motion.get("subject", "")))
    if not text_conds:
        return None
    stored = motion.get("conditions") or motion.get("execution_conditions") or []
    if not stored:
        return {"code": "MOTION_CONDITION_MISMATCH",
                "detail": ("the final motion text imposes execution conditions "
                           f"({'; '.join(c['metric'] + ' ' + c['operator'] + ' ' + str(c['value']) for c in text_conds)}) "
                           "but the motion carries no executable conditions; it would run unconditionally"),
                "final_conditions": text_conds, "stored_conditions": []}
    stored_metrics = {(c.get("metric"), c.get("operator")) for c in stored if isinstance(c, dict)}
    missing = [c for c in text_conds if (c["metric"], c["operator"]) not in stored_metrics]
    if not missing:
        return None
    return {"code": "MOTION_CONDITION_MISMATCH",
            "detail": ("the final motion text requires "
                       f"({'; '.join(c['metric'] + ' ' + c['operator'] + ' ' + str(c['value']) for c in missing)}) "
                       "which the stored executable conditions omit; it would run too early"),
            "final_conditions": text_conds, "stored_conditions": stored}


# ---- what the council accepted ----------------------------------------------------------------------
# A condition is binding when it is among the motion's executable conditions, and those come from its
# proposer: the structured `conditions` it filed, or a safeguard its own words state. But a motion is
# also shaped after it is tabled, by the delegates who vote it through: a co-sponsor who attached a
# safeguard of its own, and the demands the response round exists to collect ("cap the payment at the
# 50M reserve floor"). When the votes that carried a motion are votes that asked for the same floor,
# that floor is what the council agreed, and it has to reach execution whoever happened to table it.
#
# One kind of term is read back from free text: a floor on reserves, for a payment made from reserves.
# It is the one the record showed being lost, it is what such a vote is about (a payment the treasury
# cannot afford), and the constructions that state it are few. A demand that does not plainly state a
# floor states none; under-reading is the safe direction, because an unread demand leaves the engine
# exactly as it was.
_FIGURE = (r"(?P<num>\d[\d,]*(?:\.\d+)?)(?:\s*(?P<unit>bn|billion|mn|million|thousand|m|k)\b)?"
           r"(?!\s*(?:%|(?:percent|months?|weeks?|days?|years?|quarters?|troops?|soldiers?|men|people|persons?|"
           r"workers?|tonnes?|tons?|ships?|vessels?|units?|points?|hectares?)\b))")
_AROUND = r"(?:about\s+|roughly\s+|around\s+)?"
_UNIT_SCALE = {"bn": 1e9, "billion": 1e9, "mn": 1e6, "million": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}
_RESERVE_WORD = re.compile(r"\b(?:reserves?|gold|treasury)\b", re.I)
_FLOOR_PATTERNS = tuple(re.compile(p, re.I) for p in (
    # "do not let reserves fall below 60M", "reserves never fall below 50,000,000", "should not drop under 1.5bn",
    # "no payment that reduces reserves below 55M", "must not push reserves below roughly 50M"
    r"\b(?:not|never|n't|no|without|avoid\w*|prevent\w*|prohibit\w*|forbid\w*)\b[^.;]{0,40}?"
    r"\b(?:fall\w*|fell|drop\w*|dip\w*|sink\w*|slip\w*|go(?:es|ing)?|declin\w*|reduc\w*|push\w*|pull\w*|tak\w*|"
    r"bring\w*|draw\w*|drain\w*|deplet\w*)\b[^.;]{0,15}?"
    r"\b(?:below|under|beneath)\s+" + _AROUND + _FIGURE,
    # "reserves remain at or above 50M", "hold reserves at least 55 million", "stay >= 50M"
    r"\b(?:stay|stays|staying|remain|remains|remaining|keep|keeps|keeping|kept|hold|holds|holding|held|"
    r"maintain\w*|preserv\w*|retain\w*|leave|leaves|leaving|be)\b[^.;]{0,50}?"
    r"(?:>=|≥|\bat\s+or\s+above\b|\bat\s+least\b|\bno\s+(?:less|lower)\s+than\b|\bnot\s+below\b|\babove\b|"
    r"\bover\b|\bminimum\s+of\b)\s*" + _AROUND + _FIGURE,
    # "the 50M reserve floor", "a 45M reserve floor", "50M minimum"
    _FIGURE + r"\s*(?:gold\s+|crowns?\s+)?(?:(?:reserve|reserves)\s+)?(?:floor|minimum|buffer|threshold)\b",
    # "reserve floor of 50M", "a floor at 50M"
    r"\b(?:floor|minimum|buffer|threshold)\s+(?:of|at|to)\s+" + _AROUND + _FIGURE,
    # "at least 50M in reserves", ">= 50M of gold"
    r"(?:>=|≥|\bat\s+least\b|\bno\s+less\s+than\b)\s*" + _FIGURE +
    r"\s*(?:gold\s+|crowns?\s+)?(?:in|of)\s+(?:the\s+)?(?:foreign\s+)?(?:reserves?|gold)\b",
))


_MONEY_TAIL = re.compile(r"\s*(?:gold|crowns?|karams?)\b|\s*(?:gold\s+|crowns?\s+)?(?:reserves?\s+)?"
                         r"(?:floor|minimum|buffer|threshold)\b", re.I)


def _figure_value(match, clause: str) -> float | None:
    """The amount a figure names, in the units reserves are held in, or None if it is not money.

    "50M", "50 million" and "1.5bn" say what they are. A bare figure is money only when it is already
    a full amount (50,000,000) or is written as one ("50 gold", "a 50 reserve floor"): "28,000" in the
    same sentence as "reserves" is a troop count."""
    try:
        number = float(match.group("num").replace(",", ""))
    except ValueError:
        return None
    unit = (match.group("unit") or "").lower()
    if unit:
        return number * _UNIT_SCALE[unit]
    if number >= 1e5:
        return number
    return _money_units("reserves_after_payment", number) if _MONEY_TAIL.match(clause, match.end("num")) else None


def floor_from_demand(text: str) -> float | None:
    """The reserve floor a piece of response-round prose states, or None.

    "Ensure reserves do not fall below 50M gold" and "cap payment at the 50M reserve floor" state one.
    "Reserves are above 97M", "pay 47M now" and "cap payment at 47M" state a fact or an amount, not a
    floor, and a figure that is not next to floor wording is never read as one. Where one demand states
    several, the highest is taken: a delegate who asks for 60M and for not going under 50M has asked
    for 60M.
    """
    found = []
    for clause in re.split(r";|(?<=[A-Za-z0-9)])\.(?=\s)", str(text or "")):
        for pattern in _FLOOR_PATTERNS:
            for match in pattern.finditer(clause):
                # The floor has to be about reserves: the word is in the phrase, just before it, or
                # straight after the figure ("55M gold").
                if not _RESERVE_WORD.search(clause[max(0, match.start() - 60):match.end() + 12]):
                    continue
                value = _figure_value(match, clause)
                if value and value > 0:
                    found.append(value)
    return max(found) if found else None


def _is_reserve_floor(cond) -> bool:
    return isinstance(cond, dict) and cond.get("metric") == "reserves_after_payment" and cond.get("operator") == ">="


def _says_at_least(have: dict, want: dict) -> bool:
    """Whether a condition the motion already carries says everything `want` says."""
    if have.get("metric") != want.get("metric") or have.get("operator") != want.get("operator"):
        return False
    try:
        held, asked = float(have["value"]), float(want["value"])
    except (KeyError, TypeError, ValueError):
        return False
    op = want["operator"]
    return held >= asked if op == ">=" else (held <= asked if op == "<=" else held == asked)


def accepted_conditions(w, motion: dict, votes: dict) -> list:
    """The reserve floor the coalition that carried an arrears payment from reserves asked for.

    Each yes-voter's stated floor is the highest one it put on the table: a demand in the response
    round, or a safeguard it attached as a co-sponsor. The floor the council accepted is the highest
    F for which the yes-voters who asked for at least F would, alone, carry the motion under the
    decision rule in force: a floor one delegate wants is that delegate's, and a floor a winning
    coalition wants is the council's. Nothing is invented: no stated floor, or none with a winning
    coalition behind it, yields [].
    """
    if str(motion.get("type", "")) != "settle_arrears" or str(motion.get("subject", "")) != "reserves":
        return []
    from .politics import passes
    asked: dict = {}
    for demand in motion.get("demands") or []:
        if isinstance(demand, dict) and demand.get("member"):
            floor = floor_from_demand(str(demand.get("demand", "")))
            if floor:
                asked[demand["member"]] = max(asked.get(demand["member"], 0.0), floor)
    for member, conds in (motion.get("sponsor_conditions") or {}).items():
        for cond in conds or []:
            if _is_reserve_floor(cond):
                try:
                    asked[member] = max(asked.get(member, 0.0), float(cond["value"]))
                except (KeyError, TypeError, ValueError):
                    continue
    yes = {member for member, vote in votes.items() if vote == "yes"}
    for floor in sorted({f for member, f in asked.items() if member in yes}, reverse=True):
        backers = sorted(member for member, f in asked.items() if member in yes and f >= floor)
        if passes(w, {member: ("yes" if member in backers else "abstain") for member in votes}):
            return [{"metric": "reserves_after_payment", "operator": ">=", "value": floor,
                     "source": f"accepted by {', '.join(backers)}: a reserve floor stated in the response "
                               f"round or as a co-sponsor's safeguard",
                     "accepted_by": backers}]
    return []


def bind_conditions(stored: list, accepted: list) -> list:
    """The conditions a motion executes under: what it carries, plus what the council accepted that it
    does not already carry. A stricter condition already carried is kept as it is."""
    bound = [c for c in (stored or [])]
    for want in accepted or []:
        if not any(_says_at_least(have, want) for have in bound):
            bound.append(dict(want))
    return bound


def condition_execution_mismatch(w, motion: dict, accepted: list, stored: list) -> dict | None:
    """An accepted condition the motion did not carry, and whether executing it as recorded breaks it.

    None when everything the council accepted was already among the motion's own conditions. The cost
    is what the motion would have spent under the conditions it DID carry (none, for the motion that
    was lost on run 20260930-173547-seed1), so `would_violate` is an honest answer to "what would the
    engine have done before this was attached".
    """
    stored = [c for c in (stored or []) if isinstance(c, dict)]
    missing = [c for c in (accepted or []) if not any(_says_at_least(have, c) for have in stored)]
    if not missing:
        return None
    from .politics import settle_arrears_cost
    carried_floor = max((float(c["value"]) for c in stored if _is_reserve_floor(c)), default=0.0)
    reserves = float(w.econ.gold)
    cost = float(settle_arrears_cost(w, motion, floor=carried_floor))
    after = reserves - cost
    violations = [{"metric": c["metric"], "operator": c["operator"], "value": c["value"],
                   "reserves_before": reserves, "requested_cost": cost, "reserves_after_unconstrained": after,
                   "short_by": float(c["value"]) - after}
                  for c in missing if _is_reserve_floor(c) and after < float(c["value"]) - 1e-6]
    asked = "; ".join(f"{c['metric']} {c['operator']} {c['value']:,.0f} (accepted by {', '.join(c.get('accepted_by', []))})"
                      for c in missing)
    return {"code": "CONDITION_EXECUTION_MISMATCH",
            "detail": (f"the council accepted {asked}, but the motion it voted on did not carry it; executed as "
                       + (f"recorded it would have left reserves at {after:,.0f}" if violations else
                          "recorded it would still have respected it")),
            "accepted_conditions": list(accepted), "stored_conditions": stored, "missing": missing,
            "would_violate": bool(violations), "violations": violations}


def condition_execution_violation(w, conditions: list) -> list:
    """Reserve floors the state is under once a payment has run. Empty when every floor held.

    Execution sizes the payment to the floor, so this should always be empty; it is here so a path
    that does not (a payment made some other way) is recorded instead of trusted."""
    reserves = float(w.econ.gold)
    out = []
    for cond in conditions or []:
        if _is_reserve_floor(cond):
            try:
                floor = float(cond["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if reserves < floor - 1e-3:
                out.append({**cond, "observed": reserves})
    return out


def _canonical_actor(w, raw: str) -> str | None:
    """Map a delegate's spelling of an actor onto the canonical ids the engine knows.

    Accepts the canonical id, the display name, and the older lowercase keys that recorded runs and
    saved state still carry, so a motion written under any of them resolves to one actor.
    """
    text = str(raw).casefold()
    if text.strip() in ACTOR_ALIASES:
        return ACTOR_ALIASES[text.strip()]
    for actor, patterns in _actor_patterns(w).items():
        for p in patterns:
            if re.fullmatch(p.replace(r"\b", "").strip(), text, re.I) or re.search(p, text, re.I):
                return actor
    return None


def party_of(actor: str | None) -> str | None:
    """The state model's name for a canonical actor, for routing a proposal."""
    return {SOLVARAN_UNION: "union", MARITIME_LEAGUE: "league", DORSANIA: "dorsania",
            VELERIA: "veleria"}.get(actor)


# An actor named as the pressure a motion answers ("against Union pressure", "despite Union threats")
# is not the actor the motion is addressed to. Only these cues count, and only next to the name:
# "from" is deliberately absent, because "a loan from the League" names the counterparty and
# "protection from the Union" names the adversary, and the words alone cannot tell them apart.
_CONTEXT_BEFORE = re.compile(
    r"(?:against|despite|amid|versus|vs\.?|facing|about|regarding|concerning|because\s+of|countering|"
    r"counter|deter(?:ring)?|resist(?:ing)?|pressure\s+from|threats?\s+from)\s+(?:the\s+|a\s+|an\s+)?(?:\w+\s+){0,2}$",
    re.I)
_CONTEXT_AFTER = re.compile(
    r"^\W{0,2}(?:'s\s+)?(?:pressure|threats?|aggression|invasion|annexation|ultimatums?|blockade|embargo|"
    r"sanctions|ambitions?|demands?)\b", re.I)


def _mention_spans(w, text: str) -> dict:
    """actor -> the (start, end) of every place the text names it."""
    out = {}
    for actor, patterns in _actor_patterns(w).items():
        spans = [(m.start(), m.end()) for p in patterns for m in re.finditer(p, text, re.I)]
        if spans:
            out[actor] = spans
    return out


def _as_context(text: str, start: int, end: int) -> bool:
    return bool(_CONTEXT_BEFORE.search(text[max(0, start - 40):start]) or _CONTEXT_AFTER.match(text[end:end + 30]))


def prose_intent(w, text: str) -> dict:
    """What a motion's words say it does: which foreign actors it names, and which act.

    A high-precision read. It reports what the prose names, and nothing about what it might imply.
    `actors` is every actor named. `addressed` is the ones the motion is aimed at: where several are
    named, an actor that appears only as the pressure being answered ("against Union pressure") is
    left out, so a text that names the Union as its adversary is not mistaken for one addressed to it.
    Where only one actor is named it is the addressee whatever its context, as it always was.
    """
    body = str(text or "")
    mentions = _mention_spans(w, body)
    actors = sorted(mentions)
    actions = [a for a, pats in PROSE_ACTIONS if _hits(body, pats)]
    addressed = actors if len(actors) <= 1 else sorted(
        a for a, spans in mentions.items() if any(not _as_context(body, s, e) for s, e in spans))
    return {"actors": actors, "addressed": addressed, "actions": actions,
            "negates_force": bool(re.search(r"\brenounce\s+force|no\s+recourse\s+to\s+force", body, re.I))}


# ---- the consistency check --------------------------------------------------------------------------
def conflict(w, motion: dict) -> dict | None:
    """Where a motion's words and its executable payload disagree, or None.

    Only foreign actions are judged this way, and only on evidence the prose actually states: an
    actor it addresses that the payload does not, an act it names that the payload is not, or an act
    that the payload's own target does not receive. A motion whose words address several actors, or
    none, is left alone. The actor a text is aimed at is judged, not every actor it mentions: one named
    only as the pressure being answered is context.
    """
    action = structured_action(w, motion)
    if action["kind"] != "diplomacy":
        return None
    text = str(motion.get("text", ""))
    intent = prose_intent(w, text)
    reasons = []
    named = intent["addressed"]
    if len(named) == 1 and action.get("target") and named[0] != action["target"]:
        reasons.append({"code": "FOREIGN_TARGET_MISMATCH", "prose_actor": named[0],
                        "action_actor": action["target"],
                        "detail": f"the text addresses the {ACTOR_NAMES[named[0]]}, but the structured "
                                  f"action is sent to the {ACTOR_NAMES.get(action['target'], action['target'])}"})
    # The motion's value is a second place the counterparty can be named ("DORSANIA, 2.0M gold ...").
    valued = prose_intent(w, str(motion.get("value") or ""))["actors"]
    if len(valued) == 1 and action.get("target") and valued[0] != action["target"] \
            and not any(r["prose_actor"] == valued[0] for r in reasons):
        reasons.append({"code": "FOREIGN_TARGET_MISMATCH", "prose_actor": valued[0],
                        "action_actor": action["target"], "source": "value",
                        "detail": f"the motion's value names the {ACTOR_NAMES[valued[0]]}, but the structured "
                                  f"action is sent to the {ACTOR_NAMES.get(action['target'], action['target'])}"})
    # An act goes to the actor that receives it. This was checked only when the motion tried to
    # execute, so the council voted on a trade deal "with Dorsania" that could never run.
    expected = DIPLOMATIC_ACTIONS.get(action["action_type"])
    if expected and action.get("target") in ACTORS and expected != action["target"]:
        reasons.append({"code": "ACTION_NOT_VALID_FOR_TARGET", "action_type": action["action_type"],
                        "action_actor": action["target"], "expected_actor": expected,
                        "detail": f"a {action['action_type']} is addressed to the {ACTOR_NAMES[expected]}, "
                                  f"not the {ACTOR_NAMES[action['target']]}"})
    declared = motion.get("declared_subject")
    if declared and motion.get("subject") and declared not in (motion.get("subject"), action["action_type"]):
        reasons.append({"code": "DECLARED_SUBJECT_CONTRADICTS_ACTION", "declared": declared,
                        "action_type": action["action_type"],
                        "detail": f"the motion's own subject says {declared}, but its action says "
                                  f"{action['action_type'].replace('_', ' ')}"})
    said = intent["actions"]
    if said and action["action_type"] not in said:
        # "protest" and "trade deal" are different acts even when both are sent abroad.
        closest = _most_specific(said)
        reasons.append({"code": "ACTION_MISMATCH", "prose_action": closest,
                        "action_type": action["action_type"],
                        "detail": f"the text describes a {closest.replace('_', ' ')}, but the structured "
                                  f"action is a {action['action_type'].replace('_', ' ')}"})
    if not reasons:
        return None
    return {"code": "MOTION_ACTION_MISMATCH", "motion": motion.get("id"), "prose": text,
            "structured_action": action, "prose_intent": intent, "reasons": reasons}


def _most_specific(actions: list) -> str:
    """The act the prose is really describing when it mentions several."""
    order = [a for a, _ in PROSE_ACTIONS]
    return sorted(actions, key=lambda a: order.index(a))[0]


def repair_request(w, c: dict) -> str:
    """The targeted repair sent back to the same delegate for the one malformed motion."""
    action = c["structured_action"]
    # A motion held back before it is tabled has no id yet, and printing "Motion None" at a model
    # is both sloppy and confusing about which motion is meant.
    motion_id = c.get("motion")
    named = f"Motion {motion_id}" if motion_id else "The motion you just wrote"
    lines = ["MOTION_ACTION_MISMATCH",
             f"{named} in this round cannot be executed because its text and its structured "
             "action describe different things."]
    lines.append(f"Your motion text: \"{c['prose'][:400]}\"")
    target = action.get("target")
    described = ", ".join(f"{r['detail']}" for r in c["reasons"])
    lines.append(f"Your structured action: {action['action_type'].replace('_', ' ')}"
                 + (f" to the {ACTOR_NAMES.get(target, target)}" if target else "")
                 + (f", policy {action['policy']} = {action['value']}" if action.get("policy") else ""))
    lines.append(f"Detected conflict: {described}.")
    # Say what the actor can actually receive, so the one repair is not spent guessing. Only actors the
    # conflict itself names are listed, and only from the engine's own action vocabulary.
    for actor in dict.fromkeys(r.get(key) for r in c["reasons"] for key in ("prose_actor", "action_actor")
                               if r.get(key) in ACTORS):
        acts = [act for act, receiver in DIPLOMATIC_ACTIONS.items() if receiver == actor]
        if acts:
            lines.append(f"Acts the engine can address to the {ACTOR_NAMES[actor]}: {', '.join(acts)}.")
    lines.append("Correct either the structured action or the motion text so they describe the same motion, "
                 "then resubmit that motion only. The rest of your answer stands.")
    return "\n".join(lines)


# ---- numeric grounding: what a delegate may claim -------------------------------------------
#: Important numeric claims and where the engine looks for a supporting source.
#: Tolerances are generous: briefing figures carry noise and office reports carry ranges.
#: What is refused is a precise statistic with no available source at all.
GROUNDING_SPECS = (
    ("food_ratio", ("food coverage", "food availability", "food supply", "food shortage",
                    "grain supply", "short of food"),
     "food_ratio", {"abs": 0.10, "rel": 0.25}),
    ("hunger", ("hunger", "hungry", "starving", "food shortage"),
     "hunger", {"abs": 0.06, "rel": 0.6}),
    ("inflation", ("inflation", "price rise", "prices rising", "cpi"),
     "inflation", {"abs": 0.05, "rel": 0.6}),
    ("reserves", ("reserves", "gold reserve", "treasury gold", "foreign reserve"),
     "reserves", {"abs": 15e6, "rel": 0.4}),
    ("arrears", ("arrears", "unpaid bill", "payment backlog"),
     "arrears", {"abs": 15e6, "rel": 0.4}),
    ("unemployment", ("unemployment", "jobless", "out of work"),
     "unemployment", {"abs": 0.04, "rel": 0.6}),
    ("approval", ("approval", "popularity", "support for the government", "poll"),
     "approval", {"abs": 0.12, "rel": 0.6}),
    ("unrest", ("unrest", "protest", "riot", "disorder"),
     "unrest", {"abs": 0.12, "rel": 0.6}),
    ("army_size", ("army size", "soldiers", "troops", "army strength"),
     "army_size", {"abs": 6000.0, "rel": 0.3}),
    ("army_readiness", ("readiness", "morale", "loyalty", "equipment"),
     "army_readiness", {"abs": 0.2, "rel": 0.6}),
    ("union_forces", ("union force", "union army", "union soldier", "veleria",
                      "dorsania", "enemy force"),
     "union_forces", {"abs": 20000.0, "rel": 0.5}),
)

_GROUNDING_NUMBER = re.compile(
    r"(\d+(?:\.\d+)?)\s*(%|percent|percentage|million|M\b|bn\b|billion|thousand|k\b)?"
    r"\s*(shortage|shortfall|hunger|hungry|starving|coverage|availability|inflation|unemployment|"
    r"approval|unrest|reserves?|gold|arrears|deficit|budget|spending|revenue|"
    r"soldiers?|troops?|warships?|ships?)?", re.IGNORECASE)
_OPINION_GUARD = re.compile(
    r"\b(dangerously|unacceptabl\w*|weak|strong|alarming|worrying|concern\w*|fragile|"
    r"risky|unsustainable|healthy|reassuring|adequate|inadequate)\b", re.IGNORECASE)


def _grounding_truth(w, key: str) -> float:
    if key == "food_ratio":
        return float(w.econ.food_ratio)
    if key == "hunger":
        return (sum(p.size for p in w.k_pops() if p.hunger > 0.1) / max(1.0, w.population())) if w.k_pops() else 0.0
    if key == "inflation":
        from .society import inflation_yoy
        return float(inflation_yoy(w))
    if key == "reserves":
        return float(w.econ.gold)
    if key == "arrears":
        return float(w.econ.arrears)
    if key == "unemployment":
        return float(w.econ.unemployment)
    if key == "approval":
        return float(w.avg("approval")) if w.k_pops() else 0.0
    if key == "unrest":
        return float(w.avg("unrest")) if w.k_pops() else 0.0
    if key == "army_size":
        return float(w.mil.army.size)
    if key == "army_readiness":
        return float((w.mil.army.morale + w.mil.army.loyalty) / 2)
    if key == "union_forces":
        from .military import union_army
        return float(union_army(w))
    return 0.0


def information_available_to(w, mid: str) -> list:
    """Every number this delegate could legitimately be citing: briefing + own reports."""
    from . import briefing as _briefing
    from . import intelligence as _intel
    sources = []
    try:
        sources.append({"label": "public briefing", "text": _briefing.public_v2(w, None)})
    except Exception:
        pass
    try:
        # The decision-phase view: own reports, and everything shared this month up to the vote.
        office_text = _intel.office_context(w, mid, "decision")
    except Exception:
        office_text = ""
    if office_text.strip():
        sources.append({"label": "your office reports", "text": office_text})
    try:
        intel_text = _intel.reports_for(w, mid)
    except Exception:
        intel_text = ""
    if not isinstance(intel_text, str):
        intel_text = ""
    if intel_text.strip() and intel_text.strip() != (office_text or "").strip():
        sources.append({"label": "shared intelligence", "text": intel_text})
    return sources


def _numbers_in(text: str) -> list:
    out = []
    for raw, unit, noun in _GROUNDING_NUMBER.findall(text or ""):
        try:
            value = float(raw)
        except ValueError:
            continue
        unit = (unit or "").lower()
        noun = (noun or "").lower()
        if unit in ("%", "percent", "percentage"):
            value /= 100
        elif unit in ("million", "m"):
            value *= 1e6
        elif unit in ("billion", "bn"):
            value *= 1e9
        elif unit in ("thousand", "k"):
            value *= 1e3
        out.append({"value": value, "unit": unit, "noun": noun,
                    "raw": " ".join(x for x in (raw, unit, noun) if x).strip()})
    return out


_SOURCE_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|\u2013|to)\s*(\d+(?:\.\d+)?)\s*(%|/100)")
_SOURCE_SCALED = re.compile(r"(\d+(?:\.\d+)?)\s*(%|/100)")
# The words a source sentence must contain for its 0-100 figures to count for a metric.
_RATIO_CONTEXT = {
    "food_ratio": ("food", "grain"), "hunger": ("food", "grain", "hunger", "hungry"),
    "inflation": ("inflation", "prices"), "unemployment": ("unemploy", "jobless", "out of work"),
    "approval": ("approval", "popularity"), "unrest": ("unrest", "protest", "disorder", "riot"),
    "army_readiness": ("readiness", "morale", "loyalty"),
}


def _source_ratios(texts: list, words: tuple) -> list:
    """Figures sources state on a 0-100 scale ('58-72/100', '84-88%', '35%') in sentences about
    this metric, as ratio ranges. A figure elsewhere in the same briefing does not count."""
    out = []
    for text in texts:
        for sentence in re.split(r"\n|(?<=[.;])\s+", text or ""):
            low = sentence.lower()
            if not any(word in low for word in words):
                continue
            for a, b, _unit in _SOURCE_RANGE.findall(sentence):
                out.append(tuple(sorted((float(a) / 100, float(b) / 100))))
            for a, _unit in _SOURCE_SCALED.findall(sentence):
                out.append((float(a) / 100, float(a) / 100))
    return out


def check_numeric_grounding(w, mid: str, text: str) -> dict | None:
    """A precise statistic with no available source is sent back, not silently kept."""
    if not text or not text.strip():
        return None
    lowered = text.lower()
    hits = [spec for spec in GROUNDING_SPECS if any(p in lowered for p in spec[1])]
    if not hits:
        return None
    numbers = _numbers_in(text)
    if not numbers:
        return None
    if _OPINION_GUARD.search(text) and not any(n["noun"] in ("shortage", "shortfall") for n in numbers):
        if not [n for n in numbers if n["noun"]]:
            return None
    sources = information_available_to(w, mid)
    source_numbers = []
    for src in sources:
        source_numbers += _numbers_in(src["text"])
    source_texts = [src["text"] for src in sources]
    shortage_talk = any(word in lowered for word in ("shortage", "shortfall", "short of food"))
    for key, _patterns, _truth_key, tol in hits:
        try:
            truth = float(_grounding_truth(w, key))
        except Exception:
            continue
        band = max(tol["abs"], abs(truth) * tol["rel"])
        for claim in numbers:
            money = claim["value"] >= 1e3 or claim["unit"] in ("million", "m", "billion", "bn", "thousand", "k")
            ratio = (not money and claim["value"] <= 1.5) or claim["unit"] in ("%", "percent", "percentage")
            if key in ("reserves", "arrears") and not money:
                continue
            if key in ("army_size", "union_forces") and (ratio or claim["value"] < 100):
                continue
            if key in ("food_ratio", "hunger", "inflation", "unemployment", "approval",
                       "unrest", "army_readiness") and not ratio:
                continue
            if abs(claim["value"] - truth) <= band:
                continue
            shortage = ratio and key in ("food_ratio", "hunger") and (
                shortage_talk or claim["noun"] in ("shortage", "shortfall"))
            if shortage and abs(claim["value"] - max(0.0, 1 - float(w.econ.food_ratio))) <= max(.03, band * .5):
                continue        # a shortage stated as what coverage falls short of 100%
            supported = any(claim["unit"] == seen["unit"]
                            and abs(claim["value"] - seen["value"]) <= max(band * 0.5, 1e-9)
                            for seen in source_numbers)
            if ratio and not supported:
                slack = max(band * 0.5, .01)
                values = [claim["value"]] + ([1 - claim["value"]] if shortage else [])
                ranges = _source_ratios(source_texts, _RATIO_CONTEXT.get(key, ()))
                supported = any(lo - slack <= v <= hi + slack for v in values for lo, hi in ranges)
            if supported:
                continue
            hunger_now = _grounding_truth(w, "hunger")
            if key in ("hunger", "food_ratio") and claim["noun"] in ("shortage", "shortfall"):
                repair = (f"Your available reports show food coverage near {w.econ.food_ratio:.0%} "
                          f"and hunger near {hunger_now:.1%}. "
                          f"No source available to you supports a {claim['raw']} food shortage. "
                          f"Correct the figure or identify the report you are relying on.")
            else:
                labels = {"food_ratio": f"food coverage near {truth:.0%}",
                          "hunger": f"hunger near {truth:.1%}",
                          "inflation": f"inflation near {truth:.1%}",
                          "reserves": f"reserves near {truth:,.0f}",
                          "arrears": f"unpaid bills near {truth:,.0f}",
                          "unemployment": f"unemployment near {truth:.1%}",
                          "approval": f"approval near {truth:.0%}",
                          "unrest": f"unrest near {truth:.0%}",
                          "army_size": f"army strength near {truth:,.0f}",
                          "army_readiness": f"readiness near {truth:.0%}",
                          "union_forces": f"Union forces near {truth:,.0f}"}.get(key, str(truth))
                repair = (f"Your available reports show {labels}. "
                          f"No source available to you supports '{claim['raw']}'. "
                          f"Correct the figure or identify the report you are relying on.")
            return {"code": "NUMERIC_GROUNDING_ERROR", "metric": key, "claimed": claim["value"],
                    "observed": truth, "claim_text": claim["raw"],
                    "sources": [s["label"] for s in sources],
                    "detail": f"unsupported numeric claim about {key}: '{claim['raw']}'",
                    "repair": repair}
    return None


# ---- execution --------------------------------------------------------------------------------------
def execution_key(w, motion: dict) -> str:
    """A semantic key for one action, used to stop the same act being sent twice in a cycle.

    Two motions that ask for the same thing to the same actor produce the same key; two genuinely
    different diplomatic actions, even aimed at the same country, do not.
    """
    action = structured_action(w, motion)
    payload = {"action_type": action["action_type"], "target": action.get("target"),
               "policy": action.get("policy"), "value": str(action.get("value") or ""),
               "issue": _normalise(action.get("issue") or ""), "month": int(getattr(w, "month", 0))}
    if action["action_type"] == "charter_amendment":
        payload["text"] = _normalise(action.get("text") or "")[:400]
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _normalise(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text).casefold()))


def validate_execution(w, motion: dict, executed: dict | None = None) -> dict | None:
    """Everything that must hold before a motion is allowed to change canonical state.

    Returns None when the motion may execute, or {code, detail} saying why it may not. A refusal
    here must never be worked around by guessing what the delegate meant. Binding execution
    conditions are evaluated last, against current canonical state: a conditional motion that
    carried politically but whose floor is not met returns EXECUTION_BLOCKED_CONDITION with
    per-condition results, never a silent unconditional run.
    """
    status = str(motion.get("status") or "")
    if status in ("WITHDRAWN", "SUPERSEDED"):
        return {"code": "MOTION_WITHDRAWN", "detail": "the proposer withdrew this motion; it cannot execute"}
    if status in ("DEFERRED", "AGENDA_BLOCKED", "LAPSED"):
        return {"code": "MOTION_NOT_HEARD", "detail": f"the council never reached this motion ({status})"}
    if motion.get("void"):
        return {"code": "SESSION_VOID", "detail": "the session was ended by force; nothing it passed is executed"}
    if not motion.get("passed"):
        return {"code": "NOT_PASSED", "detail": "the motion did not carry"}
    mismatch = condition_mismatch(w, motion)
    if mismatch:
        return {**mismatch, "condition_results": [],
                "blocking_reason": mismatch["detail"]}
    action = structured_action(w, motion)
    if not action.get("action_type"):
        return {"code": "NO_STRUCTURED_ACTION", "detail": "the motion carries no executable action"}
    if action["kind"] == "diplomacy":
        if not action.get("target"):
            return {"code": "NO_TARGET",
                    "detail": f"a {action['action_type']} does not name a country or institution to address"}
        if action["target"] not in ACTORS:
            return {"code": "UNKNOWN_TARGET", "detail": f"unknown target {action['target']!r}"}
        expected = DIPLOMATIC_ACTIONS.get(action["action_type"])
        if expected is None:
            return {"code": "UNKNOWN_ACTION_TYPE", "detail": f"unknown diplomatic action {action['action_type']!r}"}
        if expected != action["target"]:
            return {"code": "ACTION_NOT_VALID_FOR_TARGET",
                    "detail": f"a {action['action_type']} is addressed to the {ACTOR_NAMES[expected]}, "
                              f"not the {ACTOR_NAMES[action['target']]}"}
    if executed is not None:
        key = execution_key(w, motion)
        if key in executed:
            return {"code": "DUPLICATE_ACTION", "detail": "an equivalent action already executed this month",
                    "duplicate_of": executed[key]}
    conditions = motion_conditions(motion)
    if conditions:
        results = evaluate_conditions(w, conditions, motion)
        failed = [r for r in results if not r.get("met")]
        if failed:
            first = failed[0]
            return {"code": "EXECUTION_BLOCKED_CONDITION",
                    "detail": (f"Council vote: PASSED_CONDITIONALLY. Reason execution paused: "
                               f"{first.get('reason') or (first['metric'] + ' not met')}"),
                    "condition_results": results,
                    "blocking_reason": "; ".join(r.get("reason") or r["metric"] for r in failed)}
    return None
