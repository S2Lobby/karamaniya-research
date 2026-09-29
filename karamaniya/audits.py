"""Investigations: the council orders an audit of an office, and what the auditors find is public, and not always right.

An audit of an office takes two months. While it runs the office works under strain (its capacity falls) and,
for the armed services, equipment buying slows. Then the auditors report from what is actually true of that
office: how much of its spending goes astray (corruption builds in an armed office whose commander runs
patronage) and, when an allegation is live against its holder, whether it is true (the engine keeps that fact
hidden, as it does for every report). A stretched or obstructed audit team can come back unable to say, and a
small share of verdicts is simply wrong. Nothing in the report tells which.

What they find lands on people. A holder found out loses standing and the corruption is cut back; a holder
cleared gains standing, and the members who called the audit pay for a witch-hunt; an inconclusive audit
settles nothing and the office may be audited again soon. The findings end a live corruption or procurement
allegation about that office.
"""
from __future__ import annotations

import re

from . import tuning
from .world import OFFICE_TITLES, OFFICES, World, clamp, rng_for

OPEN_WORDS = {"", "open", "on", "start", "begin", "order", "launch", "yes", "true", "audit", "full"}
CLOSE_WORDS = {"close", "off", "end", "stop", "cancel", "withdraw", "halt", "drop", "abandon"}
ALIASES = {"police": "interior", "interior": "interior", "army": "army", "navy": "navy", "treasury": "treasury",
           "head": "head", "government": "head", "finance": "treasury", "ministry of finance": "treasury",
           "central bank": "treasury", "fleet": "navy", "military": "army", "defence": "army", "defense": "army"}
MATERIAL = .02              # a share of the office's spending that counts as going astray
STRAIN = .06                # capacity an office loses while it is audited
PROCUREMENT_DELAY = .8      # army and navy equipment bought in a month while an armed office is audited
CLEANUP = .4                # what is left of an office's corruption once it has been found out
AUDIT_TAGS = {"army": "audit_army", "navy": "audit_navy", "interior": "audit_interior",
              "treasury": "audit_civil", "head": "audit_civil"}


def active(w: World) -> bool:
    return w.agent_architecture_version >= 2


def state(w: World) -> dict:
    s = w.institutions.setdefault("audits", {})
    s.setdefault("open", [])
    s.setdefault("done", [])
    return s


def office_of(subject) -> str | None:
    """The office a delegate means: 'navy', 'the navy procurement office', 'police' all name one."""
    text = re.sub(r"[_-]+", " ", str(subject or "").strip().lower())
    if text in OFFICES:
        return text
    found = {office for word, office in ALIASES.items() if re.search(r"\b" + re.escape(word) + r"\b", text)}
    return found.pop() if len(found) == 1 else None


def parse_action(value) -> str | None:
    word = str(value or "").strip().lower()
    if word in CLOSE_WORDS:
        return "close"
    return "open" if word in OPEN_WORDS else None


def open_for(w: World, office: str) -> dict | None:
    return next((a for a in state(w)["open"] if a["office"] == office), None)


def last_done(w: World, office: str) -> dict | None:
    return next((r for r in reversed(state(w)["done"]) if r["office"] == office), None)


def report_for(w: World, target, month: int | None = None) -> dict | None:
    """The latest report on this holder's office (given a month, one delivered in that month)."""
    for r in reversed(state(w)["done"]):
        if r["target"] == target and (month is None or r["month"] == month):
            return r
    return None


def check(w: World, mo: dict) -> dict | None:
    """None if the motion may be tabled; otherwise the structured rejection a delegate can act on."""
    from .politics import _reject
    office = office_of(mo.get("subject"))
    if office is None:
        return _reject("UNKNOWN_OFFICE", f"an investigation examines one office ({', '.join(OFFICES)}); "
                       f"'{str(mo.get('subject', '')).strip()}' names none of them, or several", offices=list(OFFICES))
    action = parse_action(mo.get("value"))
    if action is None:
        return _reject("BAD_VALUE", "an investigation takes the value open or close", allowed=["open", "close"])
    current = open_for(w, office)
    if action == "close":
        if not current:
            return _reject("ALREADY_SET", f"no audit of the {office} is under way", office=office)
        return None
    if current:
        return _reject("ALREADY_SET", f"an audit of the {office} is already under way and reports after "
                       f"Month {current['due'] + 1}", office=office, due_month=current["due"] + 1)
    limit = int(tuning.get(w, "audits.max_open"))
    if len(state(w)["open"]) >= limit:
        return _reject("TOO_MANY_OPEN", f"the auditors can carry {limit} investigations at a time; "
                       "one has to report or be closed first", open=[a["office"] for a in state(w)["open"]])
    last = last_done(w, office)
    wait = int(tuning.get(w, "audits.cooldown")) if last and last["verdict"] != "inconclusive" else 2
    if last and w.month - last["month"] < wait:
        return _reject("RECENTLY_AUDITED", f"the {office} was audited and reported in Month {last['month'] + 1}"
                       + ("" if last["verdict"] == "inconclusive" else f" ({last['verdict'].replace('_', ' ')})")
                       + f"; another audit has to wait until Month {last['month'] + wait + 1}", office=office)
    return None


def open_audit(w: World, office: str, proposer: str, text: str = "", votes: dict | None = None) -> str:
    from . import standing
    months = int(tuning.get(w, "audits.months"))
    holder = w.holder(office)
    audit = {"id": f"A{w.month + 1}-{office}", "office": office, "target": holder.id if holder else None,
             "by": proposer, "text": " ".join(str(text).split())[:160], "opened": w.month,
             "due": w.month + months - 1,
             "supporters": sorted(mid for mid, vote in (votes or {}).items() if vote == "yes")}
    state(w)["open"].append(audit)
    if proposer in {m.id for m in w.active_members()}:
        standing.spend_capital(w, proposer, float(tuning.get(w, "audits.capital_cost")))
    if holder is not None and proposer != holder.id and holder.agent_state:
        _relate(w, holder.id, proposer, trust=-4, resentment=4)
    w.event("audit_opened", f"An audit of the {OFFICE_TITLES[office]} was ordered; the auditors report after "
            f"Month {audit['due'] + 1}.", importance=2, office=office, member=audit["target"])
    return f"an audit of the {OFFICE_TITLES[office]} is under way; the auditors report after Month {audit['due'] + 1}"


def close_audit(w: World, office: str, proposer: str) -> str:
    audit = open_for(w, office)
    if audit is None:
        return "no effect"
    state(w)["open"].remove(audit)
    holder = w.holder(office)
    if holder is not None and audit["by"] in {m.id for m in w.active_members()} and holder.id != audit["by"]:
        _relate(w, holder.id, audit["by"], trust=1)
    w.event("audit_closed", f"The audit of the {OFFICE_TITLES[office]} was closed before it reported.", importance=2,
            office=office, member=audit["target"])
    return f"the audit of the {OFFICE_TITLES[office]} was closed before it reported"


def capacity_penalty(w: World, office: str) -> float:
    """What an audit under way takes from the office it examines."""
    return STRAIN if active(w) and open_for(w, office) else 0.0


def procurement_factor(w: World) -> float:
    if active(w) and any(open_for(w, o) for o in ("army", "navy")):
        return PROCUREMENT_DELAY
    return 1.0


def apply_ongoing(w: World) -> None:
    """Each month an audit is open its office's holder feels it."""
    if not active(w):
        return
    for audit in state(w)["open"]:
        holder = w.holder(audit["office"])
        if holder is not None and holder.agent_state:
            stress = holder.agent_state.setdefault("stress", {})
            stress["institutional"] = round(clamp(stress.get("institutional", 10) + 4, 0, 100), 1)


# ---- the findings -----------------------------------------------------------------------------
def _truth(w: World, audit: dict) -> tuple:
    """(wrongdoing, share of the office's spending that goes astray, whether a live allegation is true)."""
    from . import dilemmas
    office, target = audit["office"], audit["target"]
    corruption = float((w.institutions.get("corruption") or {}).get(office, 0.0))
    guilty = None
    live = list(dilemmas.state(w)["active"]) + [d for d in dilemmas.state(w)["history"]
                                                 if w.month - d.get("ended_month", -99) <= 3]
    for issue in live:
        if issue["kind"] in ("corruption_ally", "procurement_scandal") and target and issue.get("target") == target \
                and "true" in (issue.get("truth") or {}):
            guilty = bool(issue["truth"]["true"])
    size = corruption + (.03 if guilty else 0.0)
    return (size >= MATERIAL or bool(guilty)), size, guilty


def _auditor_capacity(w: World, office: str) -> float:
    cap = w.institutions.get("capacity") or {}
    return float(cap.get("head" if office == "treasury" else "treasury", .6))


def _relate(w: World, holder: str, other: str, **deltas) -> None:
    from .agents import _change, _relationship
    member = w.member(holder)
    if not member.agent_state or other not in {m.id for m in w.members} or not w.member(other).agent_state:
        return
    rel = member.relationships.setdefault(other, _relationship(w, holder, other))
    _change(rel, **deltas)


def deliver(w: World) -> list:
    """Reports from the audits that are due. Runs at the end of the month, before issues are reviewed."""
    if not active(w):
        return []
    s = state(w)
    reports = []
    for audit in [a for a in s["open"] if a["due"] <= w.month]:
        s["open"].remove(audit)
        report = _report(w, audit)
        s["done"].append(report)
        reports.append(report)
        _consequences(w, audit, report)
    s["done"] = s["done"][-12:]
    return reports


def _report(w: World, audit: dict) -> dict:
    office = audit["office"]
    wrongdoing, size, guilty = _truth(w, audit)
    rng = rng_for(w.seed, w.month, f"audit:{audit['id']}")
    corruption = float((w.institutions.get("corruption") or {}).get(office, 0.0))
    cap = _auditor_capacity(w, office)
    blur = clamp(.08 + .5 * (1 - cap) + 1.0 * corruption, .05, .6)        # missing records, obstructed staff
    if rng.random() < blur:
        verdict, accurate = "inconclusive", None
    else:
        wrong = rng.random() < float(tuning.get(w, "audits.error_rate"))
        seen = wrongdoing != wrong
        verdict = "irregularities" if seen else "clean"
        accurate = seen == wrongdoing
    title = OFFICE_TITLES[office]
    confidence = "high" if cap >= .75 else "medium" if cap >= .5 else "low"
    lo = hi = 0.0
    head = f"Audit of the {title} (ordered in Month {audit['opened'] + 1}, reported in Month {w.month + 1}): "
    if verdict == "irregularities":
        centre = max(.01, (size or MATERIAL) * (1 + rng.gauss(0, .25)))
        lo, hi = centre * .75, centre * 1.25
        who = f", pointing to the office of {w.member(audit['target']).name}" if audit["target"] else ""
        text = (head + f"irregularities found. Roughly {lo * 100:.0f}-{hi * 100:.0f}% of its spending cannot be "
                f"accounted for{who}. Auditors' confidence: {confidence}.")
    elif verdict == "clean":
        text = (head + "no material irregularities. Some waste from hurried procurement and poor record-keeping, "
                f"none traced to misconduct. Auditors' confidence: {confidence}.")
    else:
        text = (head + "inconclusive. Records were incomplete and some officials did not cooperate; the auditors "
                "could neither confirm nor rule out wrongdoing.")
    return {"id": audit["id"], "office": office, "target": audit["target"], "by": audit["by"],
            "opened": audit["opened"], "month": w.month, "verdict": verdict, "low": round(lo, 4), "high": round(hi, 4),
            "confidence": confidence, "text": text, "accurate": accurate,
            "truth": {"wrongdoing": wrongdoing, "size": round(size, 4), "allegation_true": guilty}}


def _consequences(w: World, audit: dict, report: dict) -> None:
    from . import memory, standing
    office, verdict = audit["office"], report["verdict"]
    active_ids = {m.id for m in w.active_members()}
    holder = w.holder(office)
    target = audit["target"]
    same = holder is not None and holder.id == target
    proposer = audit["by"] if audit["by"] in active_ids else None
    force = {"army": w.mil.army, "navy": w.mil.navy, "interior": w.mil.police}.get(office)
    corruption = w.institutions.setdefault("corruption", {o: 0.0 for o in OFFICES})
    if verdict == "irregularities":
        corruption[office] = round(float(corruption.get(office, 0.0)) * CLEANUP, 3)
        if same:
            standing.reputation_effect(w, holder.id, "corruption", 1.0)
        if proposer and proposer != target:
            standing.reputation_effect(w, proposer, "audit_called_right", .8)
        if force is not None:
            force.bond = max(0.0, force.bond * .85)
            force.morale = clamp(force.morale - .01)
        w.dip.league_trust = clamp(w.dip.league_trust + .02)
        if target:
            for mid in active_ids - {target}:
                _relate(w, mid, target, trust=-3)
    elif verdict == "clean":
        if same:
            standing.reputation_effect(w, holder.id, "audit_cleared", 1.0)
        if proposer and proposer != target:
            standing.reputation_effect(w, proposer, "witch_hunt", .8)
            if target and target in active_ids:
                from .agents import _grievance
                _grievance(w, target, proposer, "called an audit of your office that found nothing", 18)
                _relate(w, target, proposer, trust=-6, resentment=8)
        if force is not None:
            force.morale = clamp(force.morale - .005)
    w.event("audit_report", report["text"], importance=2, office=office, member=target, verdict=verdict)
    for mid in active_ids:
        memory.add(w, mid, "audit_report", report["text"], [office, "corruption"], [target or ""])


# ---- what delegates see -----------------------------------------------------------------------
def text(w: World) -> str:
    """The canonical-state lines: audits under way and the findings of the last three months."""
    if not active(w):
        return ""
    s = state(w)
    lines = []
    if s["open"]:
        lines.append("Investigations under way: " + "; ".join(
            f"an audit of the {OFFICE_TITLES[a['office']]}, ordered in Month {a['opened'] + 1} by "
            f"{w.member(a['by']).name}, reports after Month {a['due'] + 1} (the office is under strain meanwhile)"
            for a in s["open"]) + ".")
    recent = [r for r in s["done"] if w.month - r["month"] <= 3]
    if recent:
        lines.append("Audit findings (public; auditors can be wrong or unable to say): "
                     + " | ".join(r["text"] for r in recent))
    return "\n".join(lines)


def motion_detail(w: World, mo: dict) -> str:
    office = office_of(mo.get("subject")) or str(mo.get("subject"))
    if parse_action(mo.get("value")) == "close":
        return f"ends the audit of the {office} before it reports"
    months = int(tuning.get(w, "audits.months"))
    return (f"an audit of the {office}: reports after {months} months; the office runs under strain meanwhile"
            + ("; army and navy equipment buying slows" if office in ("army", "navy") else "")
            + "; the findings are public and can condemn or clear its holder, and cost whoever called it if it "
            "finds nothing")
