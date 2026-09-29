"""Political memory (spec 38, 39, 74, 85, 86): summarized, salience-weighted, never a transcript.

The engine writes short memory entries for each delegate from what actually happened: its own
proposals and their fate, promises made and broken, betrayals, elections, coups, resignations,
leaks, important private messages. Each entry has a salience. Minor entries fade; betrayals,
public promises, constitutional acts, deaths, coups, election interference and dismissals do
not. A call receives recent memory plus older entries retrieved for relevance to what is on the
table now. Memory can be simplified; the canonical state block remains the authority on facts.
"""
from __future__ import annotations

from . import tuning
from .world import World

SALIENCE = {
    "coup": 95, "election": 90, "war": 90, "massacre": 88, "election_interference": 90,
    "betrayal": 80, "dismissal": 75, "resignation": 70, "emergency": 70, "recession": 65,
    "promise_made_public": 55, "promise_made_private": 45, "promise_to_me": 45, "principle_changed": 50,
    "leak": 60, "grievance": 50, "favor": 40, "motion_failed": 32, "motion_passed": 25,
    "outvoted": 30, "lesson": 45, "dm_commitment": 45, "dm": 18, "intel_shared": 30,
    "strategy": 40, "appointment": 55, "criticized": 40, "defended": 40, "credit_theft": 50,
    "vindicated": 62, "minority_stand": 38, "ignored_warning": 40, "minority_mistaken": 34,
    "defiance": 55, "compliance_restored": 42, "audit_report": 52,
}
# What kind of claim a memory is. The engine's memory is never the state of the world now: it is a dated
# past event, a private estimate, or the delegate's own judgement, each true as of its month.
CLAIM_TYPES = {"intel_shared": "PRIVATE_ESTIMATE", "dm": "PRIVATE_ESTIMATE", "dm_commitment": "PRIVATE_ESTIMATE",
               "lesson": "BELIEF", "strategy": "BELIEF", "principle_changed": "BELIEF", "minority_mistaken": "BELIEF"}
SOURCES = {"defiance": "council record", "compliance_restored": "council record", "coup": "public record",
           "audit_report": "an audit",
           "election": "public record", "war": "public record", "leak": "the press", "intel_shared": "a colleague's report",
           "dm": "a private message", "dm_commitment": "a private message", "lesson": "your own judgement",
           "strategy": "your own plan", "motion_passed": "council record", "motion_failed": "council record",
           "outvoted": "council record"}
CLAIM_WORDS = {"PRIVATE_ESTIMATE": "private estimate", "BELIEF": "your own judgement"}
PROTECTED = {"coup", "election", "war", "massacre", "election_interference", "betrayal", "dismissal",
             "emergency", "promise_made_public", "principle_changed", "vindicated", "defiance"}


def _mem(state: dict) -> list:
    return state.setdefault("memory", [])


def add(w: World, mid: str, kind: str, text: str, tags=(), actors=(), salience: float | None = None,
        source: str = "", written_phase: str = "", execution_status: str = "",
        provenance: dict | None = None) -> None:
    state = w.member(mid).agent_state
    if not state:
        return
    items = _mem(state)
    key = (w.month, kind, text[:80])
    if any((x["month"], x["kind"], x["text"][:80]) == key for x in items):
        return
    entry = {"month": w.month, "observed_month": w.month, "kind": kind, "text": " ".join(text.split())[:220],
             "claim": CLAIM_TYPES.get(kind, "PAST_EVENT"), "source": source or SOURCES.get(kind, ""),
             "salience": float(SALIENCE.get(kind, 30) if salience is None else salience),
             "tags": sorted({t for t in tags if t}), "actors": sorted({a for a in actors if a}),
             "protected": kind in PROTECTED}
    if written_phase in ("PRE_VOTE", "POST_VOTE_PRE_EXECUTION", "POST_EXECUTION"):
        entry["written_phase"] = written_phase
    elif kind in ("motion_passed", "motion_failed", "outvoted", "minority_stand", "vindicated",
                  "defiance", "compliance_restored", "audit_report"):
        entry["written_phase"] = "POST_EXECUTION"
    else:
        entry["written_phase"] = "POST_VOTE_PRE_EXECUTION"
    if execution_status:
        entry["execution_status"] = execution_status
    if isinstance(provenance, dict) and provenance:
        entry["provenance"] = {k: provenance[k] for k in
                               ("layer", "source", "confidence", "verification_status",
                                "who_knows_it", "interpretation_history") if k in provenance}
    items.append(entry)
    if len(items) > 80:
        items.sort(key=lambda x: (x["protected"], x["salience"], x["month"]))
        del items[:len(items) - 80]


def record_month(w: World, record: dict) -> None:
    """Write this month's memories for every delegate from the resolved record and events."""
    active = {m.id for m in w.members}
    names = {m.id: m.name for m in w.members}
    for mo in record.get("motions", []):
        proposer = mo.get("proposer")
        tags = [mo.get("type"), mo.get("subject")]
        if proposer in active:
            from . import convergence as _convergence
            state = _convergence.motion_status(mo)
            exec_status = str(mo.get("execution_status") or "")
            if state == "WITHDRAWN":
                kind, verb = "motion_failed", "were withdrawn"
            elif mo.get("passed") and state == "EXECUTION_BLOCKED":
                # S5: a blocked motion must never be remembered as executed.
                kind, verb = "motion_passed", "passed but execution was blocked"
            elif mo.get("passed") and (state == "PASSED_CONDITIONALLY" or mo.get("conditions")):
                kind, verb = "motion_passed", "passed conditionally"
            elif mo.get("passed"):
                kind, verb = "motion_passed", "passed"
            else:
                kind, verb = "motion_failed", "failed"
            text = f"Your motion {mo.get('summary', '')} {verb} {mo.get('tally', '')}."
            if kind == "motion_passed" and not mo.get("passed") is False and "block" in verb:
                text += " Compliance status was decided after the vote; it is not evidence of implementation."
            add(w, proposer, kind, text, tags, [proposer],
                written_phase="POST_EXECUTION", execution_status=exec_status or state)
        votes = mo.get("votes", {})
        yes = sum(v == "yes" for v in votes.values())
        no = sum(v == "no" for v in votes.values())
        if yes and no:
            for voter, vote in votes.items():
                if voter not in active or vote not in ("yes", "no"):
                    continue
                on_losing = (vote == "yes") != bool(mo.get("passed"))
                if on_losing:
                    add(w, voter, "outvoted", f"You were outvoted on {mo.get('summary', '')} ({yes}-{no}).", tags,
                        [voter, proposer], written_phase="POST_EXECUTION",
                        execution_status=str(mo.get("execution_status") or ""))
            # A lone holdout is worth remembering by itself: it is the seed a later
            # vindication grows from, even before any outcome is known.
            from .psychology import lone_dissenter
            lone = lone_dissenter(mo)
            if lone in active:
                add(w, lone, "minority_stand",
                    f"You stood alone against {mo.get('summary', '')} ({yes}-{no}) in Month {w.month + 1}.",
                    tags, [lone, proposer], written_phase="POST_EXECUTION",
                    execution_status=str(mo.get("execution_status") or ""))
    for ev in w.events:
        kind = ev.get("kind")
        member = ev.get("member")
        if kind in ("coup", "officers_coup"):
            for mid in active:
                add(w, mid, "coup", ev.get("text", "")[:200], ["coup", "army"], [])
        elif kind in ("election", "defeat", "mandate", "fraud"):
            for mid in active:
                add(w, mid, "election" if kind != "fraud" else "election_interference", ev.get("text", "")[:200], ["election"], [])
        elif kind == "war":
            for mid in active:
                add(w, mid, "war", ev.get("text", "")[:200], ["war", "union"], [])
        elif kind in ("massacre", "crackdown"):
            for mid in active:
                add(w, mid, "massacre" if kind == "massacre" else "emergency", ev.get("text", "")[:200],
                    ["civil_liberties", "protest_response"], [])
        elif kind == "resignation":
            for mid in active:
                add(w, mid, "resignation", ev.get("text", "")[:200], ["office"], [member] if member else [])
        elif kind == "promise_broken" and member:
            promise = next((p for p in w.member(member).promises if p["id"] == ev.get("promise_id")), None)
            if promise:
                to = promise.get("to")
                if to in active:
                    add(w, to, "betrayal", f"{names[member]} broke a promise to you: \"{promise['text'][:120]}\".",
                        promise.get("tags", []) + [(promise.get("normalized") or {}).get("lever")], [member])
                elif promise.get("public"):
                    for mid in active - {member}:
                        add(w, mid, "grievance", f"{names[member]} broke a public promise: \"{promise['text'][:120]}\".",
                            promise.get("tags", []), [member], salience=45)
        elif kind == "leak":
            for mid in active:
                # S4: keep RAW_SOURCE / PRESS_INTERPRETATION / AGENT_BELIEF / CANONICAL_FACT apart.
                # The canonical engine knows only that a leak was published; anything the press
                # added stays an allegation until evidence establishes it.
                add(w, mid, "leak", ev.get("text", "")[:200], ["leak"], [ev.get("from")] if ev.get("from") else [],
                    written_phase="POST_EXECUTION",
                    provenance={"layer": "PRESS_INTERPRETATION", "source": ev.get("headline", "the press"),
                                "confidence": "unverified", "verification_status": "UNVERIFIED",
                                "who_knows_it": sorted(active),
                                "interpretation_history": [str(ev.get("headline", "published"))[:120]]})
    # A violation of a directive is public and stays on the member's record after they comply.
    # S2: directive vs order vs actual are three different facts; S6: streak fields preserved.
    from .politics import fmt_value
    for d in record.get("defiance", []):
        for mid in active:
            who = "You" if mid == d["member"] else names.get(d["member"], d["member"])
            add(w, mid, "defiance", f"{who} ordered {d['lever']} {fmt_value(d['value'])} against the council's "
                f"{fmt_value(d['directive'])} directive (council directive {fmt_value(d['directive'])}; "
                f"current office order {fmt_value(d['value'])}; actual world state pending execution).",
                [d["lever"], "defiance", d.get("office")], [d["member"]],
                written_phase="POST_EXECUTION",
                provenance={"layer": "CANONICAL_FACT", "source": "council record",
                            "confidence": "recorded", "verification_status": "VERIFIED",
                            "who_knows_it": sorted(active), "interpretation_history": []})
    for r in record.get("compliance_restored", []):
        for mid in active:
            who = "You" if mid == r["member"] else names.get(r["member"], r["member"])
            how = {"complied": f"{who} {'are' if who == 'You' else 'is'} now ordering {r['lever']} {r['now_text']}, in line with "
                               f"the {r['directive_text']} directive",
                   "directive lifted": f"the {r['lever']} directive was lifted",
                   "office changed hands": f"the office that held {r['lever']} changed hands"}.get(r["ended"], "the matter ended")
            add(w, mid, "compliance_restored", f"{how}; the {_months_word(r['months'])} violation remains on the record.",
                [r["lever"], "defiance"], [r["member"]], written_phase="POST_EXECUTION",
                provenance={"layer": "CANONICAL_FACT", "source": "council record",
                            "confidence": "recorded", "verification_status": "VERIFIED",
                            "who_knows_it": sorted(active), "interpretation_history": []})
    for mid in record.get("resigned", []):
        if mid in active:
            add(w, mid, "resignation", "You resigned from the government.", ["office"], [mid])
    before = (record.get("pre_resolution") or {}).get("offices", {})
    for office, holder in before.items():
        now = w.const.offices.get(office)
        if holder and holder != now and holder in active:
            add(w, holder, "dismissal", f"You lost the {office} portfolio in Month {w.month + 1}.", [office, "office"],
                [holder, now] if now else [holder])
        if now and now != holder and now in active:
            add(w, now, "appointment", f"You took the {office} portfolio in Month {w.month + 1}.", [office, "office"], [now])
    for promise in record.get("commitments_added", []):
        mid = promise.get("member")
        if mid in active:
            public = promise.get("to") in ("public", "", None)
            add(w, mid, "promise_made_public" if public else "promise_made_private",
                f"You promised{'' if public else ' ' + names.get(promise.get('to'), '')}: \"{promise.get('text', '')[:140]}\"",
                promise.get("tags", []) + [(promise.get("normalized") or {}).get("lever")], [promise.get("to")])
            if not public and promise.get("to") in active:
                add(w, promise["to"], "promise_to_me", f"{names[mid]} promised you: \"{promise.get('text', '')[:140]}\"",
                    promise.get("tags", []) + [(promise.get("normalized") or {}).get("lever")], [mid])
    for comm in record.get("communications", []):
        target, mid = comm.get("target"), comm.get("member")
        if target in active and comm.get("kind") in ("criticize", "demand_resignation"):
            add(w, target, "criticized", f"{names[mid]} {'demanded your resignation' if comm['kind'] == 'demand_resignation' else 'criticized you publicly'}: {comm.get('about', '')[:100]}",
                ["criticism"], [mid])
        if target in active and comm.get("kind") == "defend":
            add(w, target, "defended", f"{names[mid]} defended you publicly.", ["support"], [mid])


def record_stand_verdict(w: World, mid: str, stand: dict) -> None:
    """Three months after a lone dissent: what followed, in the dissenter's memory and, when the
    dissent was borne out, in the memory of those who overrode it."""
    what = stand.get("summary") or stand.get("subject", "")
    when = f"Month {stand.get('month', 0) + 1}"
    tags = ["set_policy", stand.get("subject"), "vindicated" if stand.get("verdict") == "failed" else "minority"]
    if stand.get("verdict") == "failed":
        add(w, mid, "vindicated",
            f"You stood alone against {what} in {when} ({stand.get('tally', '')}); three months on, "
            f"{stand.get('target')} is worse. It failed as you warned.", tags, [mid, stand.get("proposer")])
        active = {m.id for m in w.active_members()}
        name = w.member(mid).name
        for other in stand.get("supporters", []):
            if other in active and other != mid:
                add(w, other, "ignored_warning",
                    f"{name} alone voted against {what} in {when}; three months on, {stand.get('target')} "
                    f"is worse.", tags, [mid, other])
    elif stand.get("verdict") == "worked":
        cost = (f", though {stand.get('side')} got worse" if (stand.get("side_change") or 0) < -.02 else "")
        add(w, mid, "minority_mistaken",
            f"You stood alone against {what} in {when}; three months on, {stand.get('target')} has "
            f"improved{cost}.", tags, [mid, stand.get("proposer")])


def _months_word(months: list) -> str:
    months = sorted(set(months))
    return f"Month {months[0] + 1}" if len(months) == 1 else f"Month {months[0] + 1} to {months[-1] + 1}"


def decay(w: World) -> None:
    rate = float(tuning.get(w, "memory.minor_decay"))
    floor = float(tuning.get(w, "memory.salience_floor"))
    for m in w.members:
        items = (m.agent_state or {}).get("memory")
        if not items:
            continue
        for x in items:
            if not x["protected"] and x["month"] < w.month:
                x["salience"] = round(x["salience"] * rate, 2)
        m.agent_state["memory"] = [x for x in items if x["protected"] or x["salience"] >= floor]


def context(w: World, mid: str, topics: set) -> str:
    """Recent memory plus older memories relevant to what is on the table (spec 38, 84)."""
    items = (w.member(mid).agent_state or {}).get("memory", [])
    if not items:
        return ""
    recent_months = int(tuning.get(w, "memory.recent_months"))
    recent = sorted((x for x in items if w.month - x["month"] <= recent_months and x["month"] < w.month),
                    key=lambda x: (-x["salience"], -x["month"]))[:6]
    older = [x for x in items if w.month - x["month"] > recent_months]
    scored = []
    for x in older:
        overlap = len(set(x.get("tags", [])) & topics)
        score = x["salience"] * (1 + overlap) + (40 if x["protected"] else 0)
        if overlap or x["protected"] or x["salience"] >= 60:
            scored.append((score, x))
    scored.sort(key=lambda s: -s[0])
    retrieved = [x for _, x in scored[:int(tuning.get(w, "memory.retrieved_items"))]]
    if not recent and not retrieved:
        return ""
    lines = ["YOUR POLITICAL MEMORY (dated past events and your own past judgements; each was true as of its month "
             "and may have changed since; the canonical state is authoritative on what is true now)"]
    for x in sorted(retrieved, key=lambda x: x["month"]) + sorted(recent, key=lambda x: x["month"]):
        tag = CLAIM_WORDS.get(x.get("claim"), "") or x.get("source", "")
        phase = x.get("written_phase", "")
        suffix = ""
        if phase == "PRE_VOTE":
            suffix = " (noted before the vote; compliance status pending execution)"
        elif phase == "POST_VOTE_PRE_EXECUTION":
            suffix = " (noted after the vote, before execution; compliance status pending execution)"
        lines.append(f"- Month {x['month'] + 1}" + (f" ({tag})" if tag else "") + f": {x['text']}{suffix}")
    return "\n".join(lines)


def set_strategy(w: World, mid: str, raw: dict | None) -> None:
    """A private multi-month plan the delegate chose (spec 74). Plans can fail or change."""
    if not isinstance(raw, dict):
        return
    goal = " ".join(str(raw.get("goal", "")).split())[:200]
    if not goal:
        return
    state = w.member(mid).agent_state
    current = state.get("strategy") or {}
    if goal.lower() in ("none", "abandon", "no plan"):
        if current.get("goal"):
            current.setdefault("history", []).append({"month": w.month, "goal": current["goal"], "status": "abandoned"})
            current.update(goal="", status="abandoned")
        return
    try:
        by = int(raw.get("by_month") or 0)
    except (TypeError, ValueError):
        by = 0
    if current.get("goal") == goal:
        return
    if current.get("goal"):
        current.setdefault("history", []).append({"month": w.month, "goal": current["goal"], "status": "revised"})
    state["strategy"] = {"goal": goal, "set_month": w.month, "by_month": by - 1 if by > 0 else -1,
                         "status": "active", "history": current.get("history", [])[-5:]}
    add(w, mid, "strategy", f"You set yourself a private plan: {goal}", ["strategy"], [mid])


def strategy_text(w: World, mid: str) -> str:
    s = (w.member(mid).agent_state or {}).get("strategy") or {}
    if not s.get("goal") or s.get("status") != "active":
        return ""
    when = f" by Month {s['by_month'] + 1}" if s.get("by_month", -1) >= 0 else ""
    left = ""
    if s.get("by_month", -1) >= 0:
        remaining = s["by_month"] - w.month
        left = f" ({remaining} month{'s' if remaining != 1 else ''} left)" if remaining >= 0 else " (the date has passed)"
    return f"Your private plan since Month {s['set_month'] + 1}: {s['goal']}{when}{left}. You may keep, revise or drop it."
