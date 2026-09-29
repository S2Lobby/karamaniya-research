"""Promise and commitment tracking (spec 7, 11, 12, 50, 51).

Promises come from three places: the promise field of an opening statement, private messages
the sender marks as a promise, bargain, threat or confidential agreement, and the
questionnaire's declared principles. A light parser turns the text into something the engine
can check (support for a colleague's motions, funding a budget line, not raising a tax,
backing an appointment, sharing information). A condition written as "if army arrears stay at
zero" becomes a metric the engine can test each month; when it is met, the promiser is
reminded. Keeping, breaking, openly withdrawing and letting a promise lapse are all allowed;
each has its own political consequence.
"""
from __future__ import annotations

import re

from . import tuning
from .politics import LEVER_OFFICE
from .world import OFFICES, World, clamp

DM_KINDS = ("message", "promise", "bargain", "threat", "request", "endorsement", "warning",
            "intelligence", "confidential")
COMMITTING = {"promise", "bargain", "threat", "confidential"}

LEVER_WORDS = {
    "military": ("military budget", "defence budget", "defense budget", "army funding", "military spending", "army budget"),
    "police": ("police budget", "police funding", "police spending"),
    "welfare": ("welfare", "relief", "social support", "benefits"),
    "health_edu": ("health", "education", "schools", "hospitals"),
    "farm_support": ("farm support", "farmers", "harvest", "agricultur"),
    "tax": ("tax", "taxes"),
    "printing": ("printing", "print money", "money creation"),
    "rate": ("interest rate", "rates"),
    "shipbuilding": ("shipbuilding", "warship", "new ships", "fleet expansion"),
    "rationing": ("rationing",),
    "imports": ("imports",),
    "protest_response": ("protest", "demonstrat"),
    "surveillance": ("surveillance",),
    "arrests": ("arrest",),
    "army_target": ("army size", "more soldiers", "recruit"),
}
METRIC_WORDS = [
    (("army arrears", "soldiers' pay", "soldier pay", "army pay"), "army_arrears"),
    (("arrears", "unpaid bills"), "arrears"),
    (("reserves", "gold"), "reserves"),
    (("food", "grain", "harvest"), "food_ratio"),
    (("unemployment", "jobless"), "unemployment"),
    (("inflation", "prices"), "inflation"),
    (("morale",), "army_morale"),
    (("approval", "popularity"), "approval"),
    (("deficit",), "deficit"),
]


def condition_metrics(w: World) -> dict:
    from .society import inflation_yoy
    e = w.econ
    return {"food_ratio": e.food_ratio, "reserves": e.gold, "arrears": e.arrears,
            "unemployment": e.unemployment, "army_morale": w.mil.army.morale,
            "army_arrears": w.mil.army.arrears, "inflation": inflation_yoy(w),
            "approval": w.avg("approval") if w.k_pops() else 0.0,
            "deficit": e.deficit / max(e.gdp_nominal, 1)}


def parse_condition(text: str) -> dict | None:
    """'if army arrears remain zero' -> {"metric": "army_arrears", "operator": "<=", "value": 0}."""
    s = (text or "").lower()
    if not s.strip():
        return None
    metric = next((key for words, key in METRIC_WORDS if any(word in s for word in words)), None)
    if metric is None:
        return None
    number = re.search(r"(-?\d+(?:\.\d+)?)\s*(%|m\b|million|months?)?", s)
    value = None
    if any(x in s for x in ("zero", "none", "no longer", "cleared", "paid off")):
        value = 0.0
    elif number:
        value = float(number.group(1))
        unit = number.group(2) or ""
        if unit == "%" or (metric in ("food_ratio", "unemployment", "inflation", "approval", "deficit", "army_morale") and value > 1):
            value /= 100
        elif unit in ("m", "million") or (metric in ("reserves", "arrears") and value < 1e5):
            value *= 1e6
    if value is None:
        return None
    lower = any(x in s for x in ("below", "under", "less than", "at most", "remain zero", "stay zero", "no more than",
                                 "falls", "zero", "cleared", "paid"))
    return {"metric": metric, "operator": "<=" if lower else ">=", "value": value}


def condition_met(w: World, cond: dict | None) -> bool | None:
    if not cond:
        return None
    values = condition_metrics(w)
    observed = values.get(cond.get("metric"))
    if observed is None:
        return None
    return observed <= cond["value"] if cond.get("operator") == "<=" else observed >= cond["value"]


def normalize(text: str, to: str, w: World) -> dict | None:
    """What a promise commits to, when the text says it plainly enough to check."""
    s = (text or "").lower()
    lever = next((lv for lv, words in LEVER_WORDS.items() if any(word in s for word in words)), None)
    negated = bool(re.search(r"\b(not|never|no new|won't|will not|oppose|block|against|refuse)\b", s))
    support = bool(re.search(r"\b(support|back|vote for|second|endorse|stand with|side with)\b", s))
    if re.search(r"\b(appoint|nominate|for head|as head|to the (treasury|interior|army|navy)|keep your office)\b", s):
        office = next((o for o in OFFICES if o in s or {"head": "head of government"}.get(o, "~") in s), None)
        if to not in ("public", "") and office:
            return {"type": "support_appointment", "beneficiary": to, "office": office}
    if re.search(r"\b(share|tell you|inform|brief you|keep you informed|pass on)\b", s):
        if to not in ("public", ""):
            return {"type": "share_information", "beneficiary": to}
    if re.search(r"\b(deploy|use) (the )?(army|troops|soldiers|force)\b.*\b(protest|demonstrat|civilians)", s) and negated:
        return {"type": "no_repression"}
    if lever and re.search(r"\b(raise|increase|fund|more money|expand|restore|boost)\b", s) and not negated:
        return {"type": "fund" if lever not in ("tax", "printing", "rate") else "raise", "lever": lever, "direction": "increase"}
    if lever and negated and re.search(r"\b(raise|increase|new)\b", s):
        return {"type": "policy_limit", "lever": lever, "direction": "not_increase"}
    if lever and re.search(r"\b(cut|reduce|lower)\b", s) and not negated:
        return {"type": "cut", "lever": lever, "direction": "decrease"}
    if support and to not in ("public", ""):
        return {"type": "support_proposals_of", "beneficiary": to, "lever": lever}
    if support and lever:
        return {"type": "support_policy", "lever": lever}
    if negated and lever:
        return {"type": "oppose_policy", "lever": lever}
    return None


def infer_kind(text: str) -> str:
    """Fallback reading of a private message whose sender gave no kind."""
    s = (text or "").lower()
    if re.search(r"\b(otherwise|or else|unless you|you will regret|consequences)\b", s):
        return "threat"
    if re.search(r"\bif you\b.*\b(i will|i'll|you have my)\b", s):
        return "bargain"
    if re.search(r"\b(i promise|i will|i'll|you have my (vote|support)|count on me|i commit)\b", s):
        return "promise"
    if re.search(r"\b(confidential|between us|do not share|off the record)\b", s):
        return "confidential"
    if re.search(r"\b(warn|beware|careful|be aware)\b", s):
        return "warning"
    if re.search(r"\b(please|could you|would you|i ask|request|can you)\b", s):
        return "request"
    if re.search(r"\b(report|estimate|intelligence|our figures|data show)\b", s):
        return "intelligence"
    if re.search(r"\b(i support you|well done|you are right|i back you)\b", s):
        return "endorsement"
    return "message"


def split_condition(text: str) -> tuple[str, str]:
    m = re.search(r"\b(if|provided that|provided|as long as|so long as|once|on condition that|unless)\b(.+)", text or "", re.I)
    if not m:
        return text, ""
    return text, m.group(0).strip()


def record(w: World, mid: str, text: str, to: str, condition: str = "", source: str = "statement",
           kind: str = "promise", public: bool | None = None, deadline_month: int = -1) -> dict | None:
    """Store a promise with everything needed to check it later."""
    text = " ".join(str(text or "").split())[:240]
    if not text:
        return None
    m = w.member(mid)
    if not condition:
        _, condition = split_condition(text)
    cond = parse_condition(condition)
    normalized = normalize(text, to, w)
    public = (to in ("public", "") and source != "dm") if public is None else public
    importance = 70 if public else 45
    if kind == "threat":
        importance = 55
    if normalized and normalized["type"] in ("fund", "support_appointment", "no_repression"):
        importance += 10
    promise = {"id": f"P{w.month + 1}-{mid}-{len(m.promises) + 1}", "text": text,
               "condition": " ".join(str(condition or "").split())[:160], "condition_metric": cond,
               "to": to or "public", "kind": kind, "normalized": normalized, "public": public,
               "importance": importance, "source": source, "tags": _tags(text), "status": "active",
               "created_month": w.month, "deadline_month": deadline_month if deadline_month >= 0 else
               (w.month + 3 if normalized and normalized["type"] in ("fund", "share_information", "raise", "cut") else -1),
               "reaffirmations": [], "violations": [], "reminders": [], "evaluations": []}
    m.promises.append(promise)
    if kind == "threat" and to not in ("public", ""):
        target = w.member(to)
        rel = target.relationships.get(mid)
        if rel:
            _change(rel, fear=6, resentment=4, trust=-3)
    elif to not in ("public", "") and kind in ("promise", "bargain"):
        rel = w.member(to).relationships.get(mid)
        if rel:
            _change(rel, dependency=1.5)
    w.event("political_commitment", f"{m.name} made a political commitment.", public=False,
            member=mid, promise_id=promise["id"], to=promise["to"], promise_kind=kind)
    return promise


def _tags(text: str) -> list:
    from .agents import _tags as agent_tags
    return agent_tags(text)


def _change(rel: dict, **deltas) -> None:
    for key, delta in deltas.items():
        rel[key] = round(clamp(float(rel.get(key, 50 if key in ("trust", "respect", "perceived_reliability") else 0)) + delta, 0, 100), 1)


# ---- monthly evaluation ---------------------------------------------------------------------
def evaluate(w: World, record_: dict) -> list:
    """Judge checkable promises against this month's votes, orders and shares."""
    results = []
    # Only motions that reached a vote can judge a promise. A withdrawn motion has no votes at all,
    # and "every vote on it was a yes" would then read as kept, crediting the delegate for a
    # measure that never went to the council.
    motions = [mo for mo in record_.get("motions", [])
               if not mo.get("void") and not mo.get("withdrawn")]
    decisions = record_.get("decisions") or {}
    shares = [x for x in w.intel.get("shared", []) if x.get("month") == w.month] if w.intel else []
    for m in w.members:
        for p in m.promises:
            if p.get("status") != "active" or p.get("created_month") == w.month and p.get("source") != "dm":
                continue
            norm = p.get("normalized") or {}
            cond = p.get("condition_metric")
            met = condition_met(w, cond)
            if cond and met is False:
                continue
            if cond and met and w.month not in p["reminders"]:
                p["reminders"].append(w.month)
            verdict = _judge(w, m.id, p, norm, motions, decisions, shares)
            if verdict is None and p.get("deadline_month", -1) >= 0 and w.month >= p["deadline_month"]:
                verdict = "lapsed"
            if verdict:
                results.append(_settle(w, m.id, p, verdict))
    return results


def _judge(w: World, mid: str, p: dict, norm: dict, motions: list, decisions: dict, shares: list) -> str | None:
    kind = norm.get("type")
    vote_of = lambda mo: mo.get("votes", {}).get(mid)
    if kind == "support_proposals_of":
        relevant = [mo for mo in motions if mo.get("proposer") == norm.get("beneficiary")
                    and (not norm.get("lever") or mo.get("subject") == norm.get("lever"))]
        if not relevant:
            return None
        votes = [vote_of(mo) for mo in relevant]
        if all(v == "yes" for v in votes):
            return "kept"
        if any(v == "no" for v in votes):
            return "broken"
        return None
    if kind in ("support_policy", "oppose_policy"):
        relevant = [mo for mo in motions if mo.get("type") == "set_policy" and mo.get("subject") == norm.get("lever")]
        if not relevant:
            return None
        want = "yes" if kind == "support_policy" else "no"
        votes = [vote_of(mo) for mo in relevant]
        if all(v == want for v in votes):
            return "kept"
        if any(v not in (want, "abstain", None) for v in votes):
            return "broken"
        return None
    if kind == "support_appointment":
        relevant = [mo for mo in motions if mo.get("type") == "assign_office"
                    and str(mo.get("value", "")).upper() == norm.get("beneficiary")]
        if not relevant:
            return None
        return "kept" if all(vote_of(mo) == "yes" for mo in relevant) else "broken" if any(vote_of(mo) == "no" for mo in relevant) else None
    if kind in ("fund", "raise", "cut", "policy_limit"):
        lever = norm.get("lever")
        increased = decreased = False
        for mo in motions:
            if mo.get("type") == "set_policy" and mo.get("subject") == lever and mo.get("passed"):
                v = vote_of(mo)
                if v == "yes":
                    direction = _direction(w, mo, record_month=w.month)
                    increased |= direction > 0
                    decreased |= direction < 0
        orders = (decisions.get(mid) or {}).get("orders", {})
        office = LEVER_OFFICE.get(lever)
        if office in orders and lever in orders[office]:
            direction = _order_direction(w, lever, orders[office][lever], p)
            increased |= direction > 0
            decreased |= direction < 0
        if kind in ("fund", "raise"):
            return "kept" if increased else "broken" if decreased else None
        if kind == "cut":
            return "kept" if decreased else "broken" if increased else None
        return "broken" if increased else None
    if kind == "share_information":
        if any(x["from"] == mid and x["with"] in (norm.get("beneficiary"), "council") for x in shares):
            return "kept"
        return None
    return None


def _direction(w: World, mo: dict, record_month: int) -> int:
    from .politics import parse_lever
    lever = mo.get("subject")
    before = (mo.get("previous_value") if "previous_value" in mo else None)
    value = parse_lever(lever, mo.get("value"))
    if isinstance(value, bool):
        return 1 if value else -1
    if isinstance(value, (int, float)) and isinstance(before, (int, float)):
        return 1 if value > before + 1e-9 else -1 if value < before - 1e-9 else 0
    return 0


def _order_direction(w: World, lever: str, raw, promise: dict) -> int:
    from .politics import parse_lever
    value = parse_lever(lever, raw)
    base = promise.setdefault("baseline_value", None)
    if base is None:
        promise["baseline_value"] = value if not isinstance(value, bool) else value
        return 0
    if isinstance(value, bool):
        return 0 if value == base else (1 if value else -1)
    if isinstance(value, (int, float)) and isinstance(base, (int, float)):
        return 1 if value > base + 1e-9 else -1 if value < base - 1e-9 else 0
    return 0


def _settle(w: World, mid: str, p: dict, verdict: str) -> dict:
    m = w.member(mid)
    r = tuning.get
    p["evaluations"].append({"month": w.month, "verdict": verdict})
    witnesses = [o for o in w.members if o.id != mid and (p.get("public") or o.id == p.get("to"))]
    if verdict == "kept":
        p["status"] = "fulfilled"
        p["fulfilled_month"] = w.month
        for o in witnesses:
            rel = o.relationships.get(mid)
            if rel:
                gain = float(r(w, "relationships.kept_promise_trust")) * (1 if o.id == p.get("to") else .4)
                _change(rel, trust=gain, perceived_reliability=gain)
        w.event("promise_kept", f"{m.name} kept a recorded commitment.", public=bool(p.get("public")),
                member=mid, promise_id=p["id"])
    elif verdict == "broken":
        p["status"] = "broken"
        p["violations"].append({"month": w.month, "text": p["text"]})
        for o in witnesses:
            rel = o.relationships.get(mid)
            if rel:
                scale = 1 if o.id == p.get("to") else .5
                _change(rel, trust=float(r(w, "relationships.broken_promise_trust")) * scale,
                        resentment=float(r(w, "relationships.broken_promise_resentment")) * scale,
                        perceived_reliability=-8 * scale)
            from .agents import _grievance
            _grievance(w, o.id, mid, "broke a promise to me" if o.id == p.get("to") else "broke a public promise",
                       30 if o.id == p.get("to") else 14, major=o.id == p.get("to"))
        w.event("promise_broken", f"{m.name} acted against a recorded political commitment.", importance=2,
                public=bool(p.get("public")), member=mid, promise_id=p["id"])
    elif verdict == "lapsed":
        p["status"] = "lapsed"
        target = p.get("to")
        if target not in ("public", "") and target in {o.id for o in w.members}:
            rel = w.member(target).relationships.get(mid)
            if rel:
                _change(rel, trust=-3, resentment=2, perceived_reliability=-3)
            from .agents import _grievance
            _grievance(w, target, mid, "let a promise to me lapse", 12)
    return {"member": mid, "promise_id": p["id"], "verdict": verdict, "text": p["text"], "to": p.get("to")}


def withdraw(w: World, mid: str, promise_id: str, reason: str = "") -> bool:
    """An open withdrawal: cheaper than a silent break, but visible."""
    m = w.member(mid)
    p = next((x for x in m.promises if x["id"] == promise_id and x.get("status") == "active"), None)
    if p is None:
        return False
    p["status"] = "withdrawn"
    p["withdrawn_month"] = w.month
    p["withdrawal_reason"] = reason[:200]
    target = p.get("to")
    if target not in ("public", "") and target in {o.id for o in w.members}:
        rel = w.member(target).relationships.get(mid)
        if rel:
            _change(rel, trust=-2, resentment=1.5)
    w.event("promise_withdrawn", f"{m.name} openly withdrew an earlier commitment.", public=bool(p.get("public")),
            member=mid, promise_id=promise_id)
    return True


# ---- favours ---------------------------------------------------------------------------------
def add_favor(w: World, debtor: str, creditor: str, what: str, importance: int = 40) -> None:
    """The debtor received help from the creditor. Nothing forces repayment (spec 12)."""
    if debtor == creditor:
        return
    debts = w.member(debtor).agent_state.setdefault("favor_debts", [])
    if any(d.get("to") == creditor and d.get("motion") == what[:100] and d.get("status") == "active" for d in debts):
        return
    debts.append({"to": creditor, "month": w.month, "motion": what[:100], "status": "active",
                  "importance": importance})
    debts.sort(key=lambda d: (d.get("status") != "active", -d.get("importance", 40)))
    del debts[10:]


def expire_favors(w: World) -> None:
    for m in w.members:
        for debt in m.agent_state.get("favor_debts", []) if m.agent_state else []:
            if debt.get("status") != "active":
                continue
            limit = 4 if debt.get("importance", 40) < 35 else 12
            if w.month - debt.get("month", w.month) > limit:
                debt["status"] = "expired"


# ---- promise pressure --------------------------------------------------------------------------
def relevant(w: World, mid: str, motions: list, topics: set) -> list:
    """Past commitments that bear on what is on the table now (spec 51)."""
    m = w.member(mid)
    levers = {mo.get("subject") for mo in motions if mo.get("type") == "set_policy"}
    tags = set(topics)
    for mo in motions:
        t, s, v = mo.get("type"), mo.get("subject"), str(mo.get("value", "")).lower()
        if (t == "set_policy" and s in ("protest_response", "arrests", "surveillance") and v in ("disperse", "lethal", "mass", "high")) \
                or (t == "constitution" and s in ("press", "assembly") and v != "free") or t == "emergency_measure":
            tags.add("civil_liberties")
        if t == "constitution" and s in ("election_month", "decision_rule"):
            tags.add("democracy")
        if t == "set_policy" and s == "stats":
            tags.add("honesty")
        if t == "constitution" and s == "minority":
            tags.add("equality")
        if (t == "set_policy" and s == "posture" and v == "attack") or (t == "diplomacy" and s in ("join_union", "federation")):
            tags.add("peace")
    out = []
    for item in [*m.commitments, *m.promises]:
        if item.get("status") not in (None, "active") or item.get("superseded_month") is not None:
            continue
        norm = item.get("normalized") or {}
        hit = bool(set(item.get("tags", [])) & tags) or (norm.get("lever") in levers)
        beneficiary = norm.get("beneficiary")
        if beneficiary and any(mo.get("proposer") == beneficiary for mo in motions):
            hit = True
        met = condition_met(w, item.get("condition_metric"))
        if met:
            hit = True
        if hit:
            out.append({**item, "_condition_met": met})
    return out[:4]


def pressure_text(w: World, mid: str, motions: list, topics: set) -> str:
    items = relevant(w, mid, motions, topics)
    if not items:
        return ""
    lines = ["RELEVANT PAST COMMITMENTS"]
    for item in items:
        when = item.get("created_month", 0)
        audience = ("publicly" if item.get("public", True) and item.get("to", "public") == "public"
                    else f"privately to {w.member(item['to']).name}" if item.get("to") in {x.id for x in w.members}
                    else "publicly")
        label = "declared this principle" if "internal_strength" in item else "made this promise"
        line = f"- Month {when + 1}: you {label} {audience}: \"{item['text']}\""
        if item.get("condition"):
            line += f" (condition: {item['condition']}" + ("; that condition now appears to be met)" if item.get("_condition_met") else ")")
        lines.append(line + ".")
    lines.append("Breaking a commitment is possible. " + ("Public ones are visible to everyone; private ones are known to the person you made them to."))
    return "\n".join(lines)
