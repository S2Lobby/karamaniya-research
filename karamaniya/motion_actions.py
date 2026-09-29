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
#: What a motion actually does. Deliberately explicit: an overloaded "proposal" type is what let a
#: protest be filed as a trade deal.
DIPLOMATIC_ACTIONS = {
    "diplomatic_protest": "union",
    "trade_talks": "union", "non_aggression_pact": "union", "federation": "union",
    "join_union": "union", "ceasefire": "union",
    "alliance": "league", "loan_request": "league", "military_aid": "league", "trade_deal": "league",
    "grain_deal": "dorsania",
}
#: The engine's own subject vocabulary, which the diplomatic action names map onto.
ACTION_TO_SUBJECT = {"diplomatic_protest": "diplomatic_protest", "non_aggression_pact": "non_aggression",
                     "loan_request": "loan"}
SUBJECT_TO_ACTION = {v: k for k, v in ACTION_TO_SUBJECT.items()}
ACTORS = ("union", "league", "dorsania")
ACTOR_NAMES = {"union": "Solvaran Union", "league": "Maritime League", "dorsania": "Dorsania"}

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
        "union": [names.get("union", "Solvaran Union"), r"\bthe\s+Union\b", r"\bUnion\b"],
        "league": [names.get("league", "Maritime League"), r"\bthe\s+League\b", r"\bMaritime\s+League\b"],
        "dorsania": [names.get("dorsania", "Dorsania")],
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
            clean.append({"metric": c["metric"], "operator": c["operator"], "value": value,
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


def evaluate_conditions(w, conditions: list, motion: dict | None = None) -> list:
    """Test every binding condition against current canonical state. Pure: no mutation."""
    values = condition_values(w)
    results = []
    for cond in conditions or []:
        metric = cond.get("metric")
        observed = values.get(metric)
        detail = ""
        if metric == "reserves_after_payment" and motion is not None:
            from .politics import settle_arrears_cost
            try:
                cost = float(settle_arrears_cost(w, motion))
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


def _canonical_actor(w, raw: str) -> str | None:
    """Map a delegate's spelling of an actor onto the three the engine knows."""
    text = str(raw).casefold()
    for actor, patterns in _actor_patterns(w).items():
        for p in patterns:
            if re.fullmatch(p.replace(r"\b", "").strip(), text, re.I) or re.search(p, text, re.I):
                return actor
    return None


def prose_intent(w, text: str) -> dict:
    """What a motion's words say it does: which foreign actors it names, and which act.

    A high-precision read. It reports what the prose names, and nothing about what it might imply.
    """
    body = str(text or "")
    actors = sorted(a for a, pats in _actor_patterns(w).items() if _hits(body, pats))
    actions = [a for a, pats in PROSE_ACTIONS if _hits(body, pats)]
    return {"actors": actors, "actions": actions,
            "negates_force": bool(re.search(r"\brenounce\s+force|no\s+recourse\s+to\s+force", body, re.I))}


# ---- the consistency check --------------------------------------------------------------------------
def conflict(w, motion: dict) -> dict | None:
    """Where a motion's words and its executable payload disagree, or None.

    Only foreign actions are judged this way, and only on evidence the prose actually states: an
    actor it names that the payload does not address, or an act it names that the payload is not.
    A motion whose words name several actors, or none, is left alone.
    """
    action = structured_action(w, motion)
    if action["kind"] != "diplomacy":
        return None
    text = str(motion.get("text", ""))
    intent = prose_intent(w, text)
    reasons = []
    named = intent["actors"]
    if len(named) == 1 and action.get("target") and named[0] != action["target"]:
        reasons.append({"code": "TARGET_MISMATCH", "prose_actor": named[0],
                        "action_actor": action["target"],
                        "detail": f"the text addresses the {ACTOR_NAMES[named[0]]}, but the structured "
                                  f"action is sent to the {ACTOR_NAMES.get(action['target'], action['target'])}"})
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
    lines = ["MOTION_ACTION_MISMATCH",
             f"Motion {c.get('motion')} in this round cannot be executed because its text and its structured "
             "action describe different things."]
    lines.append(f"Your motion text: \"{c['prose'][:400]}\"")
    target = action.get("target")
    described = ", ".join(f"{r['detail']}" for r in c["reasons"])
    lines.append(f"Your structured action: {action['action_type'].replace('_', ' ')}"
                 + (f" to the {ACTOR_NAMES.get(target, target)}" if target else "")
                 + (f", policy {action['policy']} = {action['value']}" if action.get("policy") else ""))
    lines.append(f"Detected conflict: {described}.")
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
