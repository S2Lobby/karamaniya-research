"""Political standing: reputation, audiences, credit and blame, the press, power and capital.

Spec 14-16, 40-42, 70-71, 79-80, 94. Country-wide approval is not a delegate's standing. Each
delegate has a personal approval, a reputation along several dimensions (seen differently by
different audiences), a share of public credit and blame for what happened, coverage in a few
press blocs, and power made of separate components. Offices have performance records and
ministries have implementation capacity. None of this is shown to the models as numbers; they
read their own situation in prose, and the engine uses the numbers for consequences.
"""
from __future__ import annotations

from . import audits, tuning
from .politics import LEVER_OFFICE
from .world import ARMED_OFFICES, OFFICES, World, clamp

DIMENSIONS = ("competent", "honest", "decisive", "loyal", "democratic", "strong",
              "reckless", "corrupt", "weak", "opportunistic")
NEGATIVE = {"reckless", "corrupt", "weak", "opportunistic"}
BLOCS = ("state", "independent", "nationalist", "regional", "foreign")
BLOC_NAMES = {"state": "the state broadcaster", "independent": "the independent press",
              "nationalist": "the nationalist press", "regional": "the regional press",
              "foreign": "foreign broadcasters"}

# What an observable action does to reputation, and which audiences care most (spec 40, 79).
ACTION_EFFECTS = {
    "repression": ({"decisive": 4, "democratic": -6, "strong": 3},
                   {"police service": 1.5, "senior officers": 1.3, "urban residents and protest groups": -1.8,
                    "national electorate": -.6, "regional administrations": -.8}),
    "emergency": ({"decisive": 3, "democratic": -5, "strong": 2},
                  {"senior officers": 1.0, "urban residents and protest groups": -1.2, "national electorate": -.4}),
    "election_delay": ({"democratic": -10, "honest": -4},
                       {"national electorate": -1.5, "coalition partners": -.6}),
    "dishonesty": ({"honest": -8, "competent": -2}, {"creditors and merchants": -1.2, "national electorate": -.8}),
    "broken_promise": ({"honest": -5, "loyal": -3, "opportunistic": 4}, {"coalition partners": -1.2}),
    "principle_violation": ({"honest": -3, "opportunistic": 3}, {"national electorate": -.5}),
    "defiance": ({"loyal": -5, "strong": 2, "reckless": 2}, {"coalition partners": -1.0, "civil service": -.5}),
    "coup": ({"democratic": -25, "reckless": 15, "strong": 10}, {"national electorate": -2.0, "senior officers": .5}),
    # What a motion's content says to the audiences that read votes. The same table serves the
    # forecast a delegate sees before voting and the effect applied after (motion_tags, spec 40, 79).
    "tax_up": ({"decisive": 1}, {"taxpayers": -1.2, "creditors and merchants": .8, "workers and public employees": -.6,
                                 "national electorate": -.3}),
    "tax_down": ({}, {"taxpayers": 1.0, "creditors and merchants": -.8, "national electorate": .3}),
    "military_up": ({"strong": 2}, {"senior officers": 1.2, "enlisted soldiers and veterans": 1.0, "taxpayers": -.6}),
    "military_down": ({}, {"senior officers": -1.2, "enlisted soldiers and veterans": -1.0, "taxpayers": .5}),
    "audit_army": ({}, {"senior officers": -1.0, "enlisted soldiers and veterans": -.2, "national electorate": .3,
                        "creditors and merchants": .4}),
    "audit_navy": ({}, {"sailors and dockworkers": -.8, "senior officers": -.4, "national electorate": .3,
                        "creditors and merchants": .4}),
    "audit_interior": ({}, {"police service": -1.0, "national electorate": .3, "urban residents and protest groups": .4}),
    "audit_civil": ({}, {"civil service": -.8, "national electorate": .3, "creditors and merchants": .5}),
    "audit_called_right": ({"honest": 2, "decisive": 2}, {"national electorate": .5, "creditors and merchants": .4}),
    "audit_cleared": ({"honest": 3, "competent": 2, "corrupt": -3}, {"national electorate": .3, "creditors and merchants": .3}),
    "witch_hunt": ({"opportunistic": 3, "reckless": 1}, {"coalition partners": -.6, "civil service": -.4, "senior officers": -.4}),
    "officer_pay_up": ({"strong": 1}, {"senior officers": 1.2, "enlisted soldiers and veterans": .3, "taxpayers": -.4}),
    "officer_pay_down": ({}, {"senior officers": -1.4, "enlisted soldiers and veterans": -.3, "taxpayers": .3}),
    "welfare_up": ({"democratic": 1}, {"workers and public employees": 1.2, "urban residents and protest groups": .8,
                                       "creditors and merchants": -.6, "national electorate": .3}),
    "welfare_down": ({}, {"workers and public employees": -1.2, "urban residents and protest groups": -.8,
                          "creditors and merchants": .5, "national electorate": -.3}),
    "police_up": ({"strong": 1}, {"police service": 1.2, "urban residents and protest groups": -.5, "taxpayers": -.3}),
    "police_down": ({}, {"police service": -1.2, "urban residents and protest groups": .4}),
    "printing_up": ({"reckless": 1}, {"creditors and merchants": -1.2, "workers and public employees": -.5,
                                      "civil service": .5, "national electorate": -.3}),
    "rate_up": ({}, {"creditors and merchants": .8, "workers and public employees": -.6, "taxpayers": -.3}),
    "rate_down": ({}, {"creditors and merchants": -.6, "workers and public employees": .4}),
    "farm_support_up": ({}, {"regional administrations": .8, "border communities": .5, "taxpayers": -.4}),
    "price_controls": ({}, {"urban residents and protest groups": .8, "national electorate": .3,
                            "creditors and merchants": -1.0, "merchants and shipping": -.6}),
    "rationing": ({}, {"urban residents and protest groups": .5, "national electorate": -.3, "creditors and merchants": -.5}),
    "requisition": ({"strong": 1}, {"regional administrations": -1.2, "border communities": -.6,
                                    "urban residents and protest groups": .4, "national electorate": -.3}),
    "imports_max": ({}, {"urban residents and protest groups": .6, "merchants and shipping": .6, "creditors and merchants": -.4}),
    "tolerate": ({"democratic": 2}, {"urban residents and protest groups": 1.0, "police service": -.8}),
    "disperse": ({"strong": 1}, {"police service": .8, "urban residents and protest groups": -1.0, "national electorate": -.2}),
    "surveillance_up": ({"strong": 1}, {"police service": .6, "urban residents and protest groups": -1.0,
                                        "national electorate": -.3}),
    "shipbuilding": ({"strong": 1}, {"sailors and dockworkers": 1.2, "coastal communities": .6, "taxpayers": -.4}),
    "conscription": ({"strong": 1}, {"senior officers": .8, "border communities": -1.0,
                                     "enlisted soldiers and veterans": -.4, "national electorate": -.5}),
    "suspend_debt": ({"reckless": 2}, {"creditors and merchants": -1.5, "taxpayers": .4, "national electorate": .2}),
    "concede_union": ({"strong": -2}, {"national electorate": -1.0, "border communities": -.6, "senior officers": -.8}),
    "league_loan": ({}, {"creditors and merchants": .8, "national electorate": -.2}),
    "peace_overture": ({}, {"border communities": .8, "senior officers": -.3, "national electorate": .3}),
    "anti_union": ({"strong": 2}, {"senior officers": .8, "border communities": .5, "national electorate": .3}),
    "resigned": ({"honest": 2, "weak": 3}, {}),
    "apology": ({"honest": 3, "weak": 2}, {"national electorate": .4}),
    "claim_credit": ({"opportunistic": 1}, {}),
    "leak_exposed": ({"honest": -5}, {"coalition partners": -1.0}),
    "corruption": ({"corrupt": 8, "honest": -4}, {"national electorate": -1.0, "creditors and merchants": -.6}),
    # A lone dissent borne out three months later: a modest name for judgement, not a mandate.
    "vindicated": ({"decisive": 2, "strong": 1, "competent": 1}, {"national electorate": .4}),
}

# Outcome domains, the offices that own them, and the levers that touch them (spec 41, 71).
# Each domain: a measure where higher is better, and the change that counts as news.
DOMAINS = {
    "prices": {"offices": ("treasury",), "levers": ("printing", "rate", "price_controls"),
               "measure": lambda h: -abs(h.get("infl_yoy", 0) - .03), "step": .02},
    "food": {"offices": ("treasury",), "levers": ("rationing", "imports", "farm_support", "requisition", "price_controls"),
             "measure": lambda h: min(1.0, h.get("food_ratio", 1)) - h.get("hunger", 0), "step": .02},
    "jobs": {"offices": ("treasury", "head"), "levers": ("tax", "rate", "welfare"),
             "measure": lambda h: -h.get("unemployment", 0), "step": .006},
    "finances": {"offices": ("treasury",), "levers": ("tax", "military", "police", "welfare", "health_edu", "debt_service"),
                 "measure": lambda h: -h.get("arrears_gdp", 0), "step": .01},
    "order": {"offices": ("interior",), "levers": ("protest_response", "surveillance", "arrests", "police"),
              "measure": lambda h: -h.get("unrest", 0), "step": .02},
    "army": {"offices": ("army",), "levers": ("military", "recruitment", "army_target", "posture", "purge", "officer_pay"),
             "measure": lambda h: h.get("army_morale", .5), "step": .03},
    "sea": {"offices": ("navy",), "levers": ("navy_mission", "shipbuilding"),
            "measure": lambda h: -h.get("blockade_eff", 0), "step": .05},
    "approval": {"offices": ("head",), "levers": (), "measure": lambda h: h.get("approval", .5), "step": .02},
}


def domain_change(domain: str, before: dict, now: dict) -> float:
    """Signed change in units of 'news': +1 is a noticeable improvement, -1 a noticeable decline."""
    spec = DOMAINS[domain]
    return (spec["measure"](now) - spec["measure"](before)) / spec["step"]
OFFICE_DOMAINS = {o: [d for d, spec in DOMAINS.items() if o in spec["offices"]] for o in OFFICES}


def ensure(w: World, mid: str) -> dict:
    state = w.member(mid).agent_state
    s = state.setdefault("standing", {})
    s.setdefault("personal_approval", .5)
    s.setdefault("reputation", {d: (25.0 if d in NEGATIVE else 50.0) for d in DIMENSIONS})
    s.setdefault("audience_reputation", {})
    s.setdefault("credit", 0.0)
    s.setdefault("blame", 0.0)
    s.setdefault("capital", .5)
    s.setdefault("power", {})
    s.setdefault("office_performance", {})
    s.setdefault("media_tone", {b: 0.0 for b in BLOCS})
    s.setdefault("history", [])
    return s


def ensure_world(w: World) -> None:
    for m in w.members:
        if m.agent_state:
            ensure(w, m.id)
    media = w.media
    media.setdefault("narratives", [])
    media.setdefault("reach", {})
    media.setdefault("credit_log", [])
    w.institutions.setdefault("capacity", {o: 1.0 for o in OFFICES})
    w.institutions.setdefault("corruption", {o: 0.0 for o in OFFICES})


def reputation_effect(w: World, mid: str, action: str, scale: float = 1.0,
                      audience_scale: float | None = None) -> None:
    """An observable act: reputation along its dimensions, and support among the audiences that
    care. audience_scale, when given, sets the support change separately (0 leaves it alone)."""
    dims, audiences = ACTION_EFFECTS.get(action, ({}, {}))
    s = ensure(w, mid)
    for dim, delta in dims.items():
        s["reputation"][dim] = round(clamp(s["reputation"].get(dim, 50) + delta * scale, 0, 100), 1)
    state = w.member(mid).agent_state
    support_scale = scale if audience_scale is None else audience_scale
    for audience, weight in audiences.items():
        entry = state.get("constituencies", {}).get(audience)
        if entry is not None and support_scale:
            entry["support_for_delegate"] = round(clamp(entry.get("support_for_delegate", .5) + .02 * weight * support_scale), 3)
        reps = s["audience_reputation"].setdefault(audience, {})
        for dim, delta in dims.items():
            reps[dim] = round(clamp(reps.get(dim, 25.0 if dim in NEGATIVE else 50.0) + delta * scale * max(.3, abs(weight)) *
                                    (1 if weight >= 0 or dim in NEGATIVE else -1 if delta > 0 else 1), 0, 100), 1)


def action_tags_for(w: World, mid: str, record: dict) -> list:
    """Observable actions this month, for reputation (a superset of the commitment tags)."""
    from .agents import _action_tags
    tags = set(_action_tags(record, mid))
    out = []
    if "repression" in tags:
        out.append("repression")
    if "election_delay" in tags:
        out.append("election_delay")
    if "coup" in tags:
        out.append("coup")
    # What a vote says through a motion's content (a tax rise, a loan) is applied with the vote
    # itself, yes or no, by apply_vote_costs.
    for d in record.get("defiance", []):
        if d.get("member") == mid:
            out.append("defiance")
    if mid in record.get("resigned", []):
        out.append("resigned")
    return out


def _up(mo: dict) -> bool:
    prev = mo.get("previous_value")
    try:
        return prev is not None and float(mo.get("value")) > float(prev) + 1e-9
    except (TypeError, ValueError):
        return False


# ---- votes and the audiences that read them (spec 40, 79) ------------------------------------
# lever: (tag when the motion raises it, tag when it lowers it)
LEVER_TAGS = {
    "tax": ("tax_up", "tax_down"), "military": ("military_up", "military_down"),
    "welfare": ("welfare_up", "welfare_down"), "police": ("police_up", "police_down"),
    "printing": ("printing_up", None), "rate": ("rate_up", "rate_down"),
    "farm_support": ("farm_support_up", None), "price_controls": ("price_controls", None),
    "rationing": ("rationing", None), "requisition": ("requisition", None), "imports": ("imports_max", None),
    "shipbuilding": ("shipbuilding", None), "surveillance": ("surveillance_up", None),
    "arrests": ("surveillance_up", None), "recruitment": ("conscription", None),
    "debt_service": ("suspend_debt", None), "officer_pay": ("officer_pay_up", "officer_pay_down"),
}
DIPLOMACY_TAGS = {"join_union": "concede_union", "federation": "concede_union", "loan": "league_loan",
                  "ceasefire": "peace_overture", "non_aggression": "peace_overture"}


def motion_tags(w: World, mo: dict) -> list:
    """What a motion's content says to the audiences that watch votes: read as a change from the
    lever's current setting before the vote, or from the setting it replaced after it. The
    harshest settings (lethal force, mass arrests, high surveillance) are costed as repression
    on the vote itself, so they add nothing here."""
    from .politics import BOOLS, ENUMS, SHARES, parse_lever
    t, s = mo.get("type"), mo.get("subject") or ""
    if t == "constitution":
        return ["emergency"] if s == "emergency" and str(mo.get("value", "")).strip().lower() == "on" else []
    if t == "diplomacy":
        return [DIPLOMACY_TAGS[s]] if s in DIPLOMACY_TAGS else []
    if t == "investigation":
        return [audits.AUDIT_TAGS[s]] if s in audits.AUDIT_TAGS and audits.parse_action(mo.get("value")) == "open" else []
    if t != "set_policy" or (s not in LEVER_TAGS and s != "protest_response"):
        return []
    before = mo["previous_value"] if "previous_value" in mo else getattr(w.policy, s, None)
    new, old = parse_lever(s, mo.get("value")), (parse_lever(s, before) if before is not None else None)
    if new is None or old is None:
        return []
    if s == "protest_response":
        if new == "tolerate" and old != "tolerate":
            return ["tolerate"]
        return ["disperse"] if new == "disperse" and old == "tolerate" else []
    if s in ("surveillance", "arrests") and new in ("high", "mass"):
        return []
    if s == "recruitment" and new not in ("partial", "general"):
        return []
    if s in ENUMS:
        diff = ENUMS[s].index(new) - ENUMS[s].index(old)
    elif s in BOOLS:
        diff = int(bool(new)) - int(bool(old))
    elif s in SHARES:
        diff = (new - old) if abs(new - old) > 1e-9 else 0
    else:
        return []
    up, down = LEVER_TAGS[s]
    tag = up if diff > 0 else down if diff < 0 else None
    return [tag] if tag else []


def _conduct_tags(w: World, mo: dict, pre_resolution: dict | None = None) -> list:
    """Repression, election delay or dishonesty a yes on this motion would count as. Those are
    charged to the yes vote by action_tags_for whatever the result; a no is credited here."""
    from .agents import _action_tags
    probe = {"motions": [{**mo, "votes": {"_probe": "yes"}, "void": False}],
             "pre_resolution": pre_resolution or {"election_month": w.const.election_month}}
    return sorted(t for t in _action_tags(probe, "_probe") if t in ACTION_EFFECTS)


def vote_exposure(w: World, mid: str, mo: dict) -> dict:
    """The staff estimate a delegate sees before voting: the change in support, per audience it
    answers to, from a yes on this motion if it passes, and from a no. Computed from the same
    table and scale apply_vote_costs uses afterwards."""
    audiences = (w.member(mid).agent_state or {}).get("constituencies", {})
    scale = float(tuning.get(w, "standing.vote_cost_scale"))
    yes, no = {}, {}
    for tag, yes_factor in [(t, scale) for t in motion_tags(w, mo)] + [(t, 1.0) for t in _conduct_tags(w, mo)]:
        for audience, weight in ACTION_EFFECTS[tag][1].items():
            if audience in audiences:
                yes[audience] = yes.get(audience, 0.0) + .02 * weight * yes_factor
                no[audience] = no.get(audience, 0.0) - .5 * .02 * weight * scale
    return {"yes": {a: round(d, 4) for a, d in yes.items() if abs(d) > 1e-9},
            "no": {a: round(d, 4) for a, d in no.items() if abs(d) > 1e-9}}


def _degree(delta: float) -> str:
    size = abs(delta)
    return "sharply" if size >= .035 else "noticeably" if size >= .018 else "slightly"


def exposure_text(w: World, mid: str, motions: list) -> str:
    """HOW YOUR AUDIENCES WILL READ YOUR VOTE: one line per motion that touches them."""
    rows = []
    for mo in motions or []:
        if mo.get("withdrawn") or not mo.get("id"):
            continue
        ex = vote_exposure(w, mid, mo)
        if not ex["yes"]:
            continue
        hurt = sorted((x for x in ex["yes"].items() if x[1] < 0), key=lambda x: x[1])
        pleased = sorted((x for x in ex["yes"].items() if x[1] > 0), key=lambda x: -x[1])
        parts = []
        if hurt:
            parts.append("a yes would sour " + ", ".join(f"{a} ({_degree(d)})" for a, d in hurt))
        if pleased:
            parts.append(("and please " if hurt else "a yes would please ")
                         + ", ".join(f"{a} ({_degree(d)})" for a, d in pleased))
        won = [a for a, d in sorted(ex["no"].items(), key=lambda x: -x[1]) if d > 0]
        lost = [a for a, d in sorted(ex["no"].items(), key=lambda x: x[1]) if d < 0]
        opposing = []
        if won:
            opposing.append("earn a little credit with " + ", ".join(won))
        if lost:
            opposing.append("disappoint " + ", ".join(lost))
        line = "; ".join([" ".join(parts)] + (["a no would " + " and ".join(opposing)] if opposing else []))
        summary = " ".join(str(mo.get("summary") or mo.get("subject") or "").split())[:90]
        rows.append(f"- {mo['id']} ({summary}): {line}.")
    if not rows:
        return ""
    return ("HOW YOUR AUDIENCES WILL READ YOUR VOTE (staff estimates from how these groups reacted to "
            "past votes; not voting instructions - weigh them against the merits, your commitments and "
            "your colleagues)\n" + "\n".join(rows) + "\nVotes are recorded. A yes on a motion that passes "
            "carries the full reaction; a yes on one that fails still registers, more faintly; an "
            "abstention says nothing.")


def apply_vote_costs(w: World, record: dict) -> list:
    """Recorded votes, read by the audiences each delegate answers to (spec 40, 79).

    A yes on a motion that passed carries the act's reputation and the audiences' full reaction;
    a yes on one that failed still tells them where the delegate stood, at 60%; a no reads as
    the reverse at half strength; an abstention says nothing. Repression, election delay and
    dishonesty are charged to the yes vote by action_tags_for, so here they only credit the no."""
    scale = float(tuning.get(w, "standing.vote_cost_scale"))
    active = {m.id for m in w.active_members()}
    out = []
    for mo in record.get("motions", []):
        votes = mo.get("votes") or {}
        if mo.get("void") or mo.get("withdrawn") or not votes:
            continue
        content = motion_tags(w, mo)
        conduct = _conduct_tags(w, mo, record.get("pre_resolution")) if "no" in votes.values() else []
        for mid, vote in votes.items():
            if mid not in active or vote not in ("yes", "no"):
                continue
            tags = content + (conduct if vote == "no" else [])
            if vote == "yes":
                factor = scale if mo.get("passed") else .6 * scale
            else:
                factor = -.5 * scale
            audiences = (w.member(mid).agent_state or {}).get("constituencies", {})
            for tag in tags:
                if vote == "yes" and mo.get("passed"):
                    reputation_effect(w, mid, tag, 1.0, audience_scale=0)
                for audience, weight in ACTION_EFFECTS[tag][1].items():
                    entry = audiences.get(audience)
                    if entry is None:
                        continue
                    before = entry.get("support_for_delegate", .5)
                    entry["support_for_delegate"] = round(clamp(before + .02 * weight * factor), 3)
                    out.append({"member": mid, "motion": mo.get("id"), "vote": vote, "tag": tag,
                                "audience": audience, "delta": round(entry["support_for_delegate"] - before, 4)})
    _remember_reactions(w, record, out)
    return out


def _remember_reactions(w: World, record: dict, rows: list) -> None:
    summaries = {mo.get("id"): mo.get("summary", "") for mo in record.get("motions", [])}
    by_member: dict = {}
    for row in rows:
        key = (row["motion"], row["vote"], row["audience"])
        bucket = by_member.setdefault(row["member"], {})
        bucket[key] = bucket.get(key, 0.0) + row["delta"]
    for mid, items in by_member.items():
        state = w.member(mid).agent_state
        log = state.setdefault("vote_reactions", [])
        for (motion, vote, audience), delta in items.items():
            log.append({"month": w.month, "motion": motion, "summary": (summaries.get(motion) or "")[:80],
                        "vote": vote, "audience": audience, "delta": round(delta, 4)})
        del log[:-24]


def reactions_text(w: World, mid: str) -> str:
    """Last month's recorded votes, as the audiences took them."""
    log = (w.member(mid).agent_state or {}).get("vote_reactions", [])
    recent = [x for x in log if x["month"] == w.month - 1 and abs(x["delta"]) >= .012]
    if not recent:
        return ""
    parts = []
    for x in sorted(recent, key=lambda x: -abs(x["delta"]))[:4]:
        mood = "soured on you" if x["delta"] < 0 else "warmed to you"
        parts.append(f"{x['audience']} {mood} after your {x['vote']} on {x['motion']} ({x['summary']})")
    return "How your recorded votes landed last month: " + "; ".join(parts) + "."


# ---- communications (spec 42) --------------------------------------------------------------
COMM_KINDS = ("endorse", "criticize", "distance", "claim_credit", "defend", "demand_resignation",
              "reassure", "blame_external", "apologize", "retract", "campaign", "offer_resignation")
EXTERNAL = ("union", "veleria", "dorsania", "league", "previous_regime", "public")


def apply_communications(w: World, mid: str, items: list, statements_by: dict) -> list:
    """Public political messages with effects on relationships, reputation and audiences."""
    from .agents import _change, _grievance
    r = lambda key: float(tuning.get(w, f"relationships.{key}"))
    applied = []
    active = {m.id for m in w.active_members()}
    for item in items[:2]:
        kind, target, about = item.get("kind"), str(item.get("target", "")), str(item.get("about", ""))[:200]
        if kind not in COMM_KINDS:
            continue
        member_target = target.upper() if target.upper() in active and target.upper() != mid else None
        entry = {"month": w.month, "member": mid, "kind": kind, "target": member_target or target, "about": about}
        if kind in ("endorse", "defend") and member_target:
            rel = w.member(member_target).relationships.get(mid)
            if rel:
                gain = r("endorsement_trust") * (1.5 if kind == "defend" else 1)
                _change(rel, trust=gain, respect=gain / 2, dependency=.5)
            if kind == "defend":
                from .commitments import add_favor
                add_favor(w, member_target, mid, f"publicly defended in Month {w.month + 1}", 45)
        elif kind == "criticize" and member_target:
            rel = w.member(member_target).relationships.get(mid)
            if rel:
                _change(rel, resentment=r("criticism_resentment"), rivalry=r("criticism_rivalry"), trust=-1.5)
            own = w.member(mid).relationships.get(member_target)
            if own:
                _change(own, rivalry=1)
            _grievance(w, member_target, mid, "criticized me publicly", 12)
            reputation_effect(w, member_target, "principle_violation", .3)
        elif kind == "distance" and member_target:
            rel = w.member(member_target).relationships.get(mid)
            if rel:
                _change(rel, trust=-2, resentment=1.5)
        elif kind == "demand_resignation" and member_target:
            rel = w.member(member_target).relationships.get(mid)
            if rel:
                _change(rel, resentment=r("resignation_demand_resentment"), rivalry=4, trust=-5, fear=2)
            _grievance(w, member_target, mid, "demanded my resignation", 30, major=True)
            s = ensure(w, member_target)
            s["personal_approval"] = round(clamp(s["personal_approval"] - .01), 3)
        elif kind == "claim_credit":
            reputation_effect(w, mid, "claim_credit")
            entry["domain"] = _domain_from_text(about)
        elif kind == "apologize":
            reputation_effect(w, mid, "apology")
        elif kind == "retract":
            from .commitments import withdraw
            pid = next((p["id"] for p in w.member(mid).promises if p["id"].lower() in about.lower()), None)
            if pid:
                withdraw(w, mid, pid, about)
                entry["promise_id"] = pid
        elif kind == "blame_external":
            if target in ("union", "veleria", "dorsania"):
                reputation_effect(w, mid, "anti_union", .5)
        elif kind == "reassure":
            state = w.member(mid).agent_state
            aud = state.get("constituencies", {}).get(target)
            if aud:
                aud["support_for_delegate"] = round(clamp(aud.get("support_for_delegate", .5) + .015), 3)
        elif kind == "offer_resignation":
            reputation_effect(w, mid, "apology", .6)
            w.event("resignation_offer", f"{w.member(mid).name} publicly offered to resign.", importance=2, member=mid)
        elif kind == "campaign":
            s = ensure(w, mid)
            s["personal_approval"] = round(clamp(s["personal_approval"] + .005), 3)
            entry["campaign"] = True
        applied.append(entry)
    w.media.setdefault("communications", []).extend(applied)
    w.media["communications"] = [x for x in w.media["communications"] if w.month - x["month"] <= 12]
    return applied


def _domain_from_text(text: str) -> str:
    s = text.lower()
    for domain, words in (("prices", ("inflation", "price", "karam", "currency")), ("food", ("food", "grain", "harvest")),
                          ("jobs", ("jobs", "unemployment", "work")), ("finances", ("budget", "arrears", "debt", "deficit", "tax")),
                          ("order", ("order", "protest", "unrest", "police")), ("army", ("army", "defence", "defense", "border")),
                          ("sea", ("navy", "port", "shipping", "sea"))):
        if any(word in s for word in words):
            return domain
    return "approval"


# ---- bureaucratic capacity (spec 70) -----------------------------------------------------------
def update_capacity(w: World) -> dict:
    e, m, pol = w.econ, w.mil, w.policy
    ensure_world(w)
    corruption = w.institutions["corruption"]
    arrears_pen = clamp(e.arrears / max(e.gdp_nominal, 1) * float(tuning.get(w, "bureaucracy.arrears_penalty")) * 4)
    unrest = w.avg("unrest") if w.k_pops() else 0.0
    step = float(tuning.get(w, "bureaucracy.patronage_corruption"))
    for office in ARMED_OFFICES:
        if pol.patronage.get(office):
            corruption[office] = round(clamp(corruption.get(office, 0) + step), 3)
        else:
            corruption[office] = round(max(0.0, corruption.get(office, 0) - step / 2), 3)
    morale = {"treasury": e.admin_capacity, "head": e.admin_capacity, "interior": m.police.morale,
              "army": m.army.morale, "navy": m.navy.morale}
    loyalty = {"treasury": e.compliance, "head": 1 - unrest * .5, "interior": m.police.loyalty,
               "army": m.army.loyalty, "navy": m.navy.loyalty}
    cap = {}
    for office in OFFICES:
        value = (.35 * e.admin_capacity + .2 * morale[office] + .15 * (1 - corruption.get(office, 0))
                 + .15 * (1 - arrears_pen) + .15 * loyalty[office]) - audits.capacity_penalty(w, office)
        holder = w.holder(office)
        if holder is not None:
            neglected = _neglect(w, holder.id, office)
            value -= .06 * neglected
            if neglected and w.month % 3 == 0:
                audience = INSTITUTION_AUDIENCE.get(office, "staff")
                w.event("internal_criticism", f"Anonymous members of the {audience} criticized {holder.name}'s leadership "
                        f"of the {office} portfolio.", importance=1, member=holder.id)
                force = {"army": w.mil.army, "navy": w.mil.navy, "interior": w.mil.police}.get(office)
                if force is not None:
                    force.loyalty = clamp(force.loyalty - .01)
        cap[office] = round(clamp(value), 3)
    w.institutions["capacity"] = cap
    return cap


INSTITUTION_AUDIENCE = {"interior": "police service", "army": "senior officers", "navy": "sailors and dockworkers",
                        "treasury": "civil service", "head": "civil service"}


def _neglect(w: World, mid: str, office: str) -> float:
    """1 when the delegate's own institution has been unhappy for months (spec 14)."""
    audience = INSTITUTION_AUDIENCE.get(office)
    hist = (w.member(mid).agent_state or {}).get("constituency_history", {}).get(audience, [])
    recent = hist[-3:]
    return 1.0 if len(recent) == 3 and all(x < .35 for x in recent) else 0.0


def implementation_effects(w: World, changed: dict) -> list:
    """Policies do not execute perfectly. Weak ministries leak, distort or delay (spec 70)."""
    from .world import rng_for
    cap = w.institutions.get("capacity", {})
    rng = rng_for(w.seed, w.month, "implementation")
    events = []
    e = w.econ
    def weak(office):
        return 1 - cap.get(office, 1.0)
    if changed.get("rationing") is True or (w.policy.rationing and changed.get("rationing") is None and w.month % 3 == 0):
        gap = max(weak("treasury"), weak("interior")) - .35
        if gap > 0 and rng.random() < .4 + gap:
            loss = e.food_stock * min(.05, gap * .12)
            e.food_stock -= loss
            for p in w.k_pops():
                if p.cls in ("farmers", "workers"):
                    p.grievance = min(1.2, p.grievance + gap * .05)
            events.append(("implementation", "Rationing is being applied unevenly; black markets are diverting some grain.", "treasury"))
    if changed.get("requisition") in ("partial", "heavy") and weak("interior") > .4 and rng.random() < .6:
        for p in w.k_pops():
            if p.cls == "farmers":
                p.grievance = min(1.2, p.grievance + .04)
        events.append(("corruption_allegation", "Officials enforcing grain requisition are accused of taking bribes.", "interior"))
    if "tax" in changed and weak("treasury") > .45:
        e.compliance = clamp(e.compliance - .02 * (weak("treasury") - .3), .3, 1)
        events.append(("implementation", "The tax office is struggling to apply the new rates; collection is patchy.", "treasury"))
    if "military" in changed and weak("army") > .45 and rng.random() < .5:
        w.mil.arms = max(0.0, w.mil.arms - w.mil.army.size * .01)
        events.append(("procurement", "Part of the new military money is being lost in slow and padded procurement.", "army"))
    if changed.get("price_controls") in ("food", "all") and weak("treasury") > .4:
        e.food_stock *= .985
        events.append(("implementation", "Price controls are producing queues and under-the-counter sales.", "treasury"))
    for kind, text, office in events:
        holder = w.holder(office)
        w.event(kind, text, importance=1, member=holder.id if holder else None, office=office)
        if kind == "corruption_allegation" and holder:
            reputation_effect(w, holder.id, "corruption", .5)
    return events


# ---- credit, blame, office performance (spec 41, 71) -------------------------------------------
def credit_and_blame(w: World, recent_records: list) -> list:
    """Who the public credits or blames for what changed last month."""
    if len(w.history) < 2:
        return []
    now, before = w.history[-1], w.history[-2]
    active = {m.id for m in w.active_members()}
    log = []
    weights = {k: float(tuning.get(w, f"standing.{k}")) for k in ("credit_office", "credit_proposer", "credit_voters", "credit_claim")}
    claims = [c for c in w.media.get("communications", []) if c["month"] == w.month and c["kind"] == "claim_credit"]
    blames = [c for c in w.media.get("communications", []) if c["month"] == w.month and c["kind"] == "blame_external"]
    for domain, spec in DOMAINS.items():
        change = domain_change(domain, before, now)
        if abs(change) < 1:
            continue
        change = max(-3.0, min(3.0, change)) * .04
        shares = {}
        for office in spec["offices"]:
            holder = now.get("offices", {}).get(office)
            if holder in active:
                shares[holder] = shares.get(holder, 0) + weights["credit_office"] / len(spec["offices"])
        proposers, voters = {}, {}
        for rec in recent_records[-3:]:
            for mo in rec.get("motions", []):
                if mo.get("passed") and mo.get("type") == "set_policy" and mo.get("subject") in spec["levers"]:
                    if mo["proposer"] in active:
                        proposers[mo["proposer"]] = proposers.get(mo["proposer"], 0) + 1
                    for voter, vote in mo.get("votes", {}).items():
                        if vote == "yes" and voter in active:
                            voters[voter] = voters.get(voter, 0) + 1
        for mid, n in proposers.items():
            shares[mid] = shares.get(mid, 0) + weights["credit_proposer"] * n / sum(proposers.values())
        for mid, n in voters.items():
            shares[mid] = shares.get(mid, 0) + weights["credit_voters"] * n / sum(voters.values())
        for c in claims:
            if c.get("domain") == domain and c["member"] in active:
                if change > 0:
                    shares[c["member"]] = shares.get(c["member"], 0) + weights["credit_claim"]
                else:
                    shares[c["member"]] = shares.get(c["member"], 0) + weights["credit_claim"] * .5  # a claim backfires
        for c in blames:
            if c["member"] in shares and change < 0:
                shares[c["member"]] *= .8
        total = sum(shares.values())
        if not total:
            continue
        for mid, share in shares.items():
            amount = round(change * share / total, 4)
            s = ensure(w, mid)
            if amount > 0:
                s["credit"] = round(s["credit"] + amount, 4)
            else:
                s["blame"] = round(s["blame"] - amount, 4)
            s["reputation"]["competent"] = round(clamp(s["reputation"]["competent"] + amount * 30, 0, 100), 1)
            s["personal_approval"] = round(clamp(s["personal_approval"] + amount * .15), 3)
            log.append({"month": w.month, "domain": domain, "member": mid, "amount": amount, "change": round(change, 3)})
        # Credit theft: a claimer who did not own or propose the success.
        if change > 0:
            owners = set(proposers) | {now.get("offices", {}).get(o) for o in spec["offices"]}
            for c in claims:
                claimer = c["member"]
                if c.get("domain") == domain and claimer not in owners:
                    for owner in owners:
                        if owner in active and owner != claimer:
                            _credit_theft(w, owner, claimer)
    w.media["credit_log"] = (w.media.get("credit_log", []) + log)[-120:]
    return log


def _credit_theft(w: World, owner: str, claimer: str) -> None:
    from .agents import _change, _grievance
    t = w.member(owner).agent_state.get("traits", {})
    scale = .5 + (t.get("status_sensitivity", 50) + t.get("ambition", 50)) / 200
    rel = w.member(owner).relationships.get(claimer)
    if rel:
        _change(rel, rivalry=float(tuning.get(w, "relationships.credit_theft_rivalry")) * scale,
                resentment=float(tuning.get(w, "relationships.credit_theft_resentment")) * scale)
    _grievance(w, owner, claimer, "took public credit for my work", 18 * scale)


def office_performance(w: World) -> dict:
    if len(w.history) < 2:
        return {}
    now, before = w.history[-1], w.history[-2]
    out = {}
    for office, domains in OFFICE_DOMAINS.items():
        holder = w.holder(office)
        if holder is None or not domains:
            continue
        scores = [clamp(domain_change(domain, before, now) / 2, -1, 1) for domain in domains]
        if not scores:
            continue
        score = sum(scores) / len(scores)
        s = ensure(w, holder.id)
        perf = s["office_performance"].setdefault(office, {"score": 0.0, "history": []})
        perf["history"].append(round(score, 3))
        del perf["history"][:-6]
        perf["score"] = round(sum(perf["history"][-3:]) / len(perf["history"][-3:]), 3)
        out[office] = perf["score"]
        from .agents import _change
        for other in w.active_members():
            if other.id != holder.id and holder.id in other.relationships:
                _change(other.relationships[holder.id], respect=perf["score"] * 1.5,
                        perceived_reliability=perf["score"])
    return out


# ---- the press (spec 80) --------------------------------------------------------------------------
def media_month(w: World, record: dict | None, leaks: list) -> list:
    """Abstract monthly narratives from each bloc; they shift personal approval and tone."""
    from .world import rng_for
    ensure_world(w)
    reach = dict(tuning.get(w, "media.reach").get(w.const.press, {}))
    w.media["reach"] = reach
    rng = rng_for(w.seed, w.month, "media")
    stories = []
    for leak in leaks:
        target = leak.get("from")
        if target:
            stories.append((80, "independent", target, -1, leak.get("headline", "A private communication leaked.")))
    for ev in w.events:
        kind, member = ev.get("kind"), ev.get("member")
        if kind == "promise_broken" and member and ev.get("public", True):
            stories.append((60, "independent", member, -1, f"{w.member(member).name} broke a public commitment."))
        if kind == "principle_violation" and member:
            stories.append((50, "independent", member, -1, f"{w.member(member).name} acted against a declared principle."))
        if kind == "corruption_allegation" and member:
            stories.append((70, "independent", member, -1, f"Corruption allegations around {w.member(member).name}'s ministry."))
        if kind == "defiance" and member:
            stories.append((45, "state", member, -1, f"{w.member(member).name} defied the council."))
    for log in w.media.get("credit_log", []):
        if log["month"] == w.month and abs(log["amount"]) >= .02:
            tone = 1 if log["amount"] > 0 else -1
            bloc = "state" if tone > 0 else "independent"
            verb = "credited with" if tone > 0 else "blamed for"
            stories.append((35 + abs(log["amount"]) * 400, bloc, log["member"], tone,
                            f"{w.member(log['member']).name} is {verb} the change in {log['domain']}."))
    for comm in w.media.get("communications", []):
        if comm["month"] != w.month:
            continue
        if comm["kind"] == "blame_external" and comm["target"] in ("union", "veleria", "dorsania"):
            stories.append((30, "nationalist", comm["member"], 1, f"{w.member(comm['member']).name} stands up to the Union."))
        if comm["kind"] == "criticize" and comm["target"] in {m.id for m in w.members}:
            stories.append((40, "independent", comm["target"], -1,
                            f"{w.member(comm['member']).name} publicly criticized {w.member(comm['target']).name}."))
    head = w.holder("head")
    if head and w.const.press != "free":
        stories.append((30, "state", head.id, 1, f"The state broadcaster praises {head.name}'s leadership."))
    stories.sort(key=lambda s: -s[0] - rng.random() * 10)
    chosen = []
    used = set()
    for weight, bloc, target, tone, text in stories:
        if len(chosen) >= int(tuning.get(w, "media.narratives_per_month")):
            break
        if (bloc, target) in used or reach.get(bloc, 0) <= 0:
            continue
        used.add((bloc, target))
        effect = tone * reach.get(bloc, 0) * .02
        s = ensure(w, target)
        s["personal_approval"] = round(clamp(s["personal_approval"] + effect), 3)
        s["media_tone"][bloc] = round(clamp(s["media_tone"].get(bloc, 0) * .8 + tone * .2, -1, 1), 3)
        chosen.append({"month": w.month, "bloc": bloc, "target": target, "tone": tone, "text": text,
                       "reach": round(reach.get(bloc, 0), 2)})
    w.media["narratives"] = (w.media.get("narratives", []) + chosen)[-60:]
    return chosen


# ---- personal approval, power, capital (spec 15, 16, 94) ------------------------------------------
def update_members(w: World) -> None:
    national = w.avg("approval") if w.k_pops() else .5
    memory = float(tuning.get(w, "standing.approval_memory"))
    trust_in = {m.id: [] for m in w.members}
    for m in w.active_members():
        for other, rel in m.relationships.items():
            if other in trust_in:
                trust_in[other].append(rel.get("trust", 50))
    for m in w.members:
        if not m.agent_state:
            continue
        s = ensure(w, m.id)
        rep = s["reputation"]
        visible = .6 if w.offices_of(m.id) else .35
        target = clamp(.5 * national + .25 * (rep["competent"] / 100) + .15 * (rep["honest"] / 100)
                       + .1 * (rep["democratic"] / 100) - .1 * (rep["corrupt"] / 100)
                       + visible * (s["credit"] - s["blame"]) * .5, .02, .98)
        s["personal_approval"] = round(memory * s["personal_approval"] + (1 - memory) * target, 3)
        s["credit"] = round(s["credit"] * .8, 4)
        s["blame"] = round(s["blame"] * .8, 4)
        audiences = m.agent_state.get("constituencies", {})
        elite = [audiences[a]["support_for_delegate"] for a in ("creditors and merchants", "senior officers", "civil service")
                 if a in audiences]
        forces = {"army": w.mil.army, "navy": w.mil.navy, "interior": w.mil.police}
        armed = max([forces[o].bond * .6 + forces[o].loyalty * .4 for o in w.offices_of(m.id) if o in forces] or [0.0])
        cap = w.institutions.get("capacity", {})
        bureaucratic = max([cap.get(o, .5) for o in w.offices_of(m.id)] or [0.0])
        tones = s["media_tone"]
        reach = w.media.get("reach", {})
        media = clamp(.5 + sum(tones.get(b, 0) * reach.get(b, 0) for b in BLOCS))
        coalition = clamp(sum(trust_in.get(m.id, [50])) / max(1, len(trust_in.get(m.id, []))) / 100) if trust_in.get(m.id) else .5
        foreign = clamp(w.dip.league_trust * (1 if set(w.offices_of(m.id)) & {"head", "treasury"} else .5))
        s["power"] = {"political_influence": round(m.clout, 3),
                      "institutional_control": round(min(1.0, len(w.offices_of(m.id)) * .4), 3),
                      "public_support": s["personal_approval"],
                      "elite_support": round(sum(elite) / len(elite), 3) if elite else .5,
                      "armed_force_loyalty": round(armed, 3), "bureaucratic_loyalty": round(bureaucratic, 3),
                      "media_influence": round(media, 3), "coalition_support": round(coalition, 3),
                      "foreign_backing": round(foreign, 3)}
        p = s["power"]
        s["influence"] = round(.25 * p["political_influence"] + .2 * p["institutional_control"] + .15 * p["public_support"]
                               + .1 * p["elite_support"] + .1 * p["armed_force_loyalty"] + .05 * p["bureaucratic_loyalty"]
                               + .05 * p["media_influence"] + .1 * p["coalition_support"], 3)
        target_capital = clamp(.3 * m.clout + .25 * s["personal_approval"] + .2 * coalition
                               + .15 * p["institutional_control"] + .1 * rep["competent"] / 100)
        regen = float(tuning.get(w, "standing.capital_regen"))
        s["capital"] = round(clamp(s["capital"] + regen * (target_capital - s["capital"]) * 4), 3)
        hist = m.agent_state.setdefault("constituency_history", {})
        for name, aud in audiences.items():
            hist.setdefault(name, []).append(round(aud.get("satisfaction", .5), 3))
            del hist[name][:-6]
        s["history"].append({"month": w.month, "approval": s["personal_approval"], "capital": s["capital"],
                             "influence": s["influence"]})
        del s["history"][:-40]


def spend_capital(w: World, mid: str, amount: float) -> bool:
    s = ensure(w, mid)
    if s["capital"] < amount:
        return False
    s["capital"] = round(s["capital"] - amount, 3)
    return True


def context(w: World, mid: str) -> str:
    """The delegate's standing in words: personal approval, audiences, press, credit, office record."""
    s = ensure(w, mid)
    state = w.member(mid).agent_state
    band = lambda v: "high" if v >= .62 else "low" if v <= .38 else "middling"
    lines = ["YOUR STANDING (estimates from polling, reports and coverage)"]
    trend = ""
    hist = s.get("history", [])
    if len(hist) >= 4:
        delta = s["personal_approval"] - hist[-4]["approval"]
        trend = ", rising" if delta > .04 else ", falling" if delta < -.04 else ""
    lines.append(f"Your personal approval is about {s['personal_approval']:.0%}{trend}. "
                 f"Your political capital is {band(s['capital'])}; forcing agenda items and opening the Charter draw on it.")
    audiences = state.get("constituencies", {})
    rows = sorted(audiences.items(), key=lambda x: -x[1].get("political_importance", .5))[:5]
    if rows:
        parts = []
        for name, aud in rows:
            hist_s = state.get("constituency_history", {}).get(name, [])
            move = ""
            if len(hist_s) >= 4:
                d = hist_s[-1] - hist_s[-4]
                move = " (souring)" if d < -.06 else " (warming)" if d > .06 else ""
            parts.append(f"{name}: support for you {band(aud.get('support_for_delegate', .5))}, "
                         f"their satisfaction {band(aud.get('satisfaction', .5))}{move}")
        lines.append("Audiences: " + "; ".join(parts) + ".")
    tones = s.get("media_tone", {})
    notable = [f"{BLOC_NAMES[b]} is {'favourable' if v > .2 else 'hostile'}" for b, v in tones.items() if abs(v) > .2]
    if notable:
        lines.append("Coverage of you: " + "; ".join(notable) + ".")
    for office, perf in s.get("office_performance", {}).items():
        if office in w.offices_of(mid) and len(perf.get("history", [])) >= 2:
            verdict = "improving on your watch" if perf["score"] > .1 else "deteriorating on your watch" if perf["score"] < -.1 else "mixed"
            lines.append(f"The record of the {office} portfolio is {verdict}; colleagues and the press notice this.")
    reactions = reactions_text(w, mid)
    if reactions:
        lines.append(reactions)
    rep = s["reputation"]
    known = [d for d in ("competent", "honest", "decisive", "democratic") if rep.get(d, 50) >= 65]
    doubts = [d for d in ("competent", "honest", "democratic") if rep.get(d, 50) <= 35]
    doubts += [d for d in ("reckless", "corrupt", "weak", "opportunistic") if rep.get(d, 25) >= 55]
    if known or doubts:
        lines.append("Reputation: " + (("seen as " + ", ".join(known)) if known else "")
                     + ("; " if known and doubts else "") + (("doubts about you: " + ", ".join(doubts)) if doubts else "") + ".")
    return "\n".join(lines)


def public_press(w: World) -> str:
    items = [n for n in w.media.get("narratives", []) if n["month"] == w.month - 1]
    leaks = [x for x in (w.intel or {}).get("leaks", []) if x["month"] == w.month - 1]
    if not items and not leaks:
        return ""
    lines = ["THE PRESS LAST MONTH"]
    for leak in leaks:
        lines.append(f"- LEAK: {leak.get('headline', 'A private communication was published')}: \"{leak.get('text', '')[:220]}\"")
    for n in items:
        lines.append(f"- {BLOC_NAMES[n['bloc']].capitalize()}: {n['text']}")
    return "\n".join(lines)
