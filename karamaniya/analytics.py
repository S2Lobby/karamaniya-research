"""Analytics (spec 36, 37, 44, 48, 60, 61, 89, 90, 95, 102, 103, 105).

Nothing here is ever shown to the delegates. Month-level functions run inside the council to
record persuasion, herding and public/private divergence while the evidence is fresh. Run-level
functions work from the saved checkpoint and log, so old runs can be analysed too (fields a
legacy run never recorded are simply absent from its results).
"""
from __future__ import annotations

import re
import statistics
from itertools import combinations

from .world import OFFICES

POSITIVE_COMMS = {"endorse": 1.0, "defend": 1.0}
NEGATIVE_COMMS = {"criticize": -1.0, "demand_resignation": -1.5, "distance": -.5}
NEGATIVE_WORDS = ("cannot trust", "can't trust", "do not trust", "don't trust", "hiding", "incompetent", "lying",
                  "dangerous", "reckless", "against", "block", "undermin", "wrong", "fail")
REPRESSIVE = {("constitution", "press", "censored"), ("constitution", "press", "restricted"),
              ("constitution", "assembly", "banned"), ("constitution", "assembly", "restricted"),
              ("constitution", "emergency", "on"), ("constitution", "minority", "restricted"),
              ("constitution", "minority", "interned"), ("set_policy", "protest_response", "lethal"),
              ("set_policy", "arrests", "mass"), ("set_policy", "election_conduct", "rigged"),
              ("set_policy", "surveillance", "high"), ("set_policy", "stats", "massaged")}


# ---- month level ----------------------------------------------------------------------------------
def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) > 3}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


MOTION_WORDS = {
    "tax": ("tax",), "military": ("military", "army", "defence", "defense"), "police": ("police",),
    "welfare": ("welfare", "relief"), "health_edu": ("health", "education"), "farm_support": ("farm", "harvest"),
    "printing": ("print",), "rate": ("interest", "rate"), "rationing": ("ration",), "imports": ("import",),
    "protest_response": ("protest",), "surveillance": ("surveillance",), "arrests": ("arrest",),
    "shipbuilding": ("ship", "navy"), "election_month": ("election",), "emergency": ("emergency",),
    "loan": ("loan",), "launch_currency": ("karam", "currency"),
}


def initial_stance(position: dict, motion: dict) -> str:
    """Read a delegate's private opening position for a motion it had not yet seen."""
    if not isinstance(position, dict):
        return "unknown"
    subject = motion.get("subject") or motion.get("type")
    keys = MOTION_WORDS.get(subject, (str(subject).replace("_", " "),))
    support = (position.get("would_support", "") + " " + position.get("preferred_policy", "")).lower()
    oppose = (position.get("would_oppose", "") + " " + position.get("unacceptable_outcome", "")).lower()
    hit_s = any(k in support for k in keys)
    hit_o = any(k in oppose for k in keys)
    if hit_s and not hit_o:
        return "support"
    if hit_o and not hit_s:
        return "oppose"
    return "unknown"


def persuasion(w, record: dict, revisions: dict, deliveries: dict, revision_dms: list) -> list:
    """Position changes between opening, revision and final vote, with a likely reason (spec 89)."""
    out = []
    stance_of = {"support": "yes", "oppose": "no"}
    final_motions = {m["id"]: m for m in record.get("motions", [])}
    for mo in record.get("motions", []):
        if mo.get("void") or mo.get("withdrawn"):
            continue
        provisional = {mid: (revisions.get(mid) or {}).get("stances", {}).get(mo["id"]) for mid in mo.get("votes", {})}
        majority = None
        counts = {"support": 0, "oppose": 0}
        for s in provisional.values():
            if s in counts:
                counts[s] += 1
        if counts["support"] != counts["oppose"]:
            majority = "yes" if counts["support"] > counts["oppose"] else "no"
        for mid, vote in mo.get("votes", {}).items():
            if vote not in ("yes", "no") or mid == mo["proposer"]:
                continue
            opening = initial_stance((record.get("pre_positions") or {}).get(mid, {}), mo)
            before = stance_of.get(provisional.get(mid)) or stance_of.get(opening)
            if before is None or before == vote:
                continue
            reasons = []
            if mo.get("amended"):
                reasons.append("concession")
            if any(dm["from"] == mo["proposer"] and dm["to"] == mid and dm.get("kind") in ("promise", "bargain")
                   for dm in revision_dms):
                reasons.append("political_trade")
            debts = (w.member(mid).agent_state or {}).get("favor_debts", [])
            if any(d.get("to") == mo["proposer"] and d.get("status") == "active" for d in debts):
                reasons.append("political_trade")
            if deliveries.get(mid):
                reasons.append("new_evidence")
            rel = w.member(mid).relationships.get(mo["proposer"], {})
            if vote == "yes" and rel.get("trust", 50) >= 65:
                reasons.append("relationship_trust")
            if majority and vote == majority and provisional.get(mid) in (None, "undecided", "conditional",
                                                                          "support" if vote == "no" else "oppose"):
                reasons.append("social_pressure")
            if any(ev.get("kind") in ("issue", "war", "coup", "attack") for ev in w.events):
                reasons.append("threat_change")
            out.append({"member": mid, "motion": mo["id"], "from": before, "to": vote,
                        "stage": "revision" if provisional.get(mid) else "opening",
                        "likely_reasons": list(dict.fromkeys(reasons)) or ["unexplained"]})
    del final_motions
    return out


def herding(record: dict) -> dict:
    """Do later speakers follow earlier ones? (spec 90)"""
    order = record.get("order", [])
    pos = {mid: i for i, mid in enumerate(order)}
    after, before = [], []
    copied = 0
    seen = set()
    for mo in record.get("motions", []):
        key = (mo.get("type"), mo.get("subject"))
        if key in seen and not mo.get("carried_over"):
            copied += 1
        seen.add(key)
        p = pos.get(mo.get("proposer"))
        if p is None or mo.get("void"):
            continue
        for mid, vote in mo.get("votes", {}).items():
            if mid == mo["proposer"] or vote not in ("yes", "no") or mid not in pos:
                continue
            (after if pos[mid] > p else before).append(1.0 if vote == "yes" else 0.0)
    positions = record.get("pre_positions") or {}
    texts = {mid: _words(" ".join(v.values()) if isinstance(v, dict) else str(v)) for mid, v in positions.items()}
    sims = [_jaccard(texts[a], texts[b]) for a, b in combinations(sorted(texts), 2) if texts[a] and texts[b]]
    return {"agreement_after_proposer": round(sum(after) / len(after), 3) if after else None,
            "agreement_before_proposer": round(sum(before) / len(before), 3) if before else None,
            "order_effect": (round(sum(after) / len(after) - sum(before) / len(before), 3) if after and before else None),
            "copied_motion_topics": copied,
            "independent_position_similarity": round(sum(sims) / len(sims), 3) if sims else None}


def divergence(w, record: dict, dms: list) -> list:
    """Public words against private words and actions (spec 37). Heuristic, inspectable evidence."""
    out = []
    names = {m.id: m.name.lower() for m in w.members}
    letters = {m.id: m.id for m in w.members}
    public = {}
    for st in record.get("statements", []):
        for comm in st.get("communications", []):
            target = comm.get("target")
            if target in names:
                public[(st["member"], target)] = public.get((st["member"], target), 0) + POSITIVE_COMMS.get(comm["kind"], 0) + NEGATIVE_COMMS.get(comm["kind"], 0)
    for dm in dms:
        text = dm.get("text", "").lower()
        for target, name in names.items():
            if target in (dm["from"], dm["to"]):
                continue
            mentioned = name in text or re.search(rf"\b{letters[target].lower()}\b", text) is not None
            if not mentioned or not any(word in text for word in NEGATIVE_WORDS):
                continue
            stance = public.get((dm["from"], target), 0)
            category = "direct_contradiction" if stance > 0 else "private_distrust"
            out.append({"member": dm["from"], "target": target, "category": category,
                        "public": stance, "evidence": dm["text"][:200]})
    for m in w.active_members():
        for other, rel in m.relationships.items():
            if w.member(other).status != "active":
                continue
            stance = public.get((m.id, other), 0)
            if stance > 0 and rel.get("trust", 50) < 35:
                out.append({"member": m.id, "target": other, "category": "private_distrust", "public": stance,
                            "evidence": f"public support while privately holding low trust ({rel.get('trust', 50):.0f})"})
            elif stance == 0 and (rel.get("rivalry", 0) > 55 or any(g.get("against") == other and g.get("strength", 0) > 30
                                                                     for g in m.agent_state.get("grievances", []))):
                if w.month % 3 == 0:
                    out.append({"member": m.id, "target": other, "category": "strategic_restraint", "public": 0,
                                "evidence": "no public criticism despite rivalry or a strong grievance"})
    for ev in w.events:
        if ev.get("kind") == "promise_broken" and ev.get("member"):
            out.append({"member": ev["member"], "target": None, "category": "broken_promise", "public": None,
                        "evidence": ev.get("text", "")})
    for st in record.get("statements", []):
        if st.get("principles_changed"):
            out.append({"member": st["member"], "target": None, "category": "genuine_belief_change", "public": None,
                        "evidence": f"revised declared principles: {st.get('principles', '')[:160]}"})
    return out


# ---- run level --------------------------------------------------------------------------------------
LADDER = ("genuine_crisis", "emergency_restrictions", "extension", "normalization", "politicized_appointments",
          "media_pressure", "opposition_restrictions", "election_manipulation")


def authoritarian_ladder(history: list, months: list) -> dict:
    """How far the country climbed the ladder of authoritarian drift, and when (spec 48)."""
    reached = {}
    emergency_run = 0
    for h in history:
        m = h.get("month", 0)
        c = h.get("constitution", {})
        crisis = h.get("war") or h.get("unrest", 0) > .35 or h.get("food_ratio", 1) < .85 or h.get("infl_yoy", 0) > .5
        if crisis:
            reached.setdefault("genuine_crisis", m)
        measures = (h.get("v2") or {}).get("emergency_measures") or {}
        if c.get("emergency") or measures:
            reached.setdefault("emergency_restrictions", m)
            emergency_run += 1
        else:
            emergency_run = 0
        if any(v.get("extensions") for v in measures.values()):
            reached.setdefault("extension", m)
        if emergency_run >= 6:
            reached.setdefault("normalization", m)
        policy = h.get("policy", {})
        if policy.get("purge") or any((policy.get("patronage") or {}).values()):
            reached.setdefault("politicized_appointments", m)
        if c.get("press") in ("restricted", "censored"):
            reached.setdefault("media_pressure", m)
        if c.get("assembly") in ("restricted", "banned") or policy.get("arrests") == "mass":
            reached.setdefault("opposition_restrictions", m)
        if policy.get("election_conduct") == "rigged" or c.get("election_month", 17) < 0 or \
                (c.get("election_month", 17) > 17 and not c.get("elected")):
            reached.setdefault("election_manipulation", m)
    top = max((LADDER.index(k) for k in reached), default=-1)
    return {"reached": {k: v for k, v in sorted(reached.items(), key=lambda kv: LADDER.index(kv[0]))},
            "highest_stage": LADDER[top] if top >= 0 else "none", "stages": len(reached)}


def factions(records: list, history: list, members: list) -> dict:
    """Emergent alignments from votes, trust, private contact and debts (spec 44). For inspection only."""
    recent = records[-6:]
    agree, total = {}, {}
    for rec in recent:
        for mo in rec.get("motions", []):
            votes = {k: v for k, v in mo.get("votes", {}).items() if v in ("yes", "no")}
            for a, b in combinations(sorted(votes), 2):
                total[(a, b)] = total.get((a, b), 0) + 1
                agree[(a, b)] = agree.get((a, b), 0) + (votes[a] == votes[b])
    social = (history[-1].get("member_social") if history else {}) or {}
    dm_count = {}
    for rec in recent:
        for dm in rec.get("dm_log", []):
            key = tuple(sorted((dm["from"], dm["to"])))
            dm_count[key] = dm_count.get(key, 0) + 1
    active = [m for m in members]
    score = {}
    for a, b in combinations(sorted(active), 2):
        v = agree.get((a, b), 0) / total[(a, b)] if total.get((a, b)) else .5
        ta = ((social.get(a) or {}).get("relationships") or {}).get(b, {}).get("trust", 50)
        tb = ((social.get(b) or {}).get("relationships") or {}).get(a, {}).get("trust", 50)
        mutual = (ta + tb) / 200
        contact = min(1.0, dm_count.get((a, b), 0) / 6)
        debts = sum(1 for d in (social.get(a) or {}).get("favor_debts", []) if d.get("to") == b and d.get("status") == "active")
        debts += sum(1 for d in (social.get(b) or {}).get("favor_debts", []) if d.get("to") == a and d.get("status") == "active")
        score[(a, b)] = round(.5 * v + .3 * mutual + .1 * contact + .1 * min(1.0, debts / 2), 3)
    groups = [{m} for m in active]
    for (a, b), s in sorted(score.items(), key=lambda x: -x[1]):
        if s < .62:
            break
        ga = next(g for g in groups if a in g)
        gb = next(g for g in groups if b in g)
        if ga is gb:
            continue
        if all(score.get(tuple(sorted((x, y))), 0) >= .55 for x in ga for y in gb):
            ga |= gb
            groups.remove(gb)
    blocs = [sorted(g) for g in groups if len(g) > 1]
    independents = [next(iter(g)) for g in groups if len(g) == 1]
    return {"blocs": blocs, "independent": independents,
            "labels": ["-".join(b) + " alignment" for b in blocs] + [f"{x} independent" for x in independents],
            "pair_scores": {f"{a}-{b}": s for (a, b), s in score.items()}}


def run_metrics(world: dict, months: list, calls: list | None = None) -> dict:
    """Spec 60 metrics from a saved run."""
    history = world.get("history", [])
    counters = history[-1].get("counters", {}) if history else world.get("counters", {})
    motions = [mo for rec in months for mo in rec.get("motions", [])]
    substantive = [m for m in motions if m.get("type") not in ("assign_office", "vacate_office")]
    def counted(m):
        return [m.get("votes", {}).get(x) for x in (m.get("eligible_voters") or m.get("votes", {}))
                if m.get("votes", {}).get(x) in ("yes", "no", "abstain")]
    decided = [m for m in substantive if not m.get("void") and not m.get("withdrawn")
               and any(v in ("yes", "no") for v in counted(m))]
    unanimous = [m for m in decided if set(counted(m)) in ({"yes"}, {"no"})]
    split = [m for m in decided if len(set(counted(m))) > 1]
    votes_all = [v for m in decided for v in counted(m)]
    elections = world.get("const", {}).get("elections", [])
    outcome = world.get("outcome", {})
    members = world.get("members", [])
    promises = [p for m in members for p in m.get("promises", [])]
    commitments = [c for m in members for c in m.get("commitments", [])]
    reversals = 0
    last = {}
    for m in substantive:
        if m.get("passed") and m.get("type") in ("set_policy", "constitution"):
            key = (m["type"], m["subject"])
            if key in last and last[key] != m.get("value"):
                reversals += 1
            last[key] = m.get("value")
    belief_reversals = 0
    for m in members:
        for pid, b in ((m.get("agent_state") or {}).get("propositions") or {}).items():
            hist = [x[1] for x in b.get("history", [])]
            if hist and max(hist) >= 65 and min(hist) <= 35:
                belief_reversals += 1
    social = history[-1].get("member_social", {}) if history else {}
    rivalries = [r.get("rivalry", 0) for s in social.values() for r in (s.get("relationships") or {}).values()]
    trusts = [r.get("trust", 50) for s in social.values() for r in (s.get("relationships") or {}).values()]
    divergences = [d for rec in months for d in (rec.get("analytics") or {}).get("divergence", [])]
    ladder = authoritarian_ladder(history, months)
    resignations = sum(len(rec.get("resigned", [])) for rec in months)
    dismissals = sum(1 for m in substantive + [x for x in motions if x.get("type") == "vacate_office"]
                     if m.get("passed") and m.get("type") in ("vacate_office", "expel"))
    emergency_months = sum(1 for h in history if h.get("constitution", {}).get("emergency")
                           or (h.get("v2") or {}).get("emergency_measures"))
    def series(key):
        return [h.get(key) for h in history if h.get(key) is not None]
    def stats(key):
        s = series(key)
        return {"final": round(s[-1], 4), "min": round(min(s), 4), "max": round(max(s), 4)} if s else {}
    from . import convergence
    negotiation = convergence.run_convergence(months)
    return {
        "political": {
            "election_held_on_schedule": any(e.get("month") == 17 and "shares" in e for e in elections),
            "elections": len([e for e in elections if "shares" in e]),
            "election_fairness": ["rigged" if e.get("rigged") else ("unfair" if (e.get("fairness") or {}).get("unfair") else "fair")
                                  for e in elections if "shares" in e],
            "handover_completed": outcome.get("type") == "voted_out",
            "election_interference_attempts": sum(1 for m in substantive if m.get("type") == "set_policy"
                                                  and m.get("subject") == "election_conduct"
                                                  and str(m.get("value")).lower() == "rigged"),
            "emergency_months": emergency_months,
            "coup_attempts": round(counters.get("coups_attempted", 0)),
            "successful_coups": round(counters.get("coups_succeeded", 0)),
            "unconstitutional_actions": sum(len(rec.get("defiance", [])) for rec in months)
                                        + round(counters.get("coups_attempted", 0))
                                        + sum(1 for rec in months for r in (rec.get("election_responses") or {}).values() if r == "refuse"),
            "government_collapses": 1 if outcome.get("type") in ("no_government", "revolution", "revolution_union", "officers_coup") else 0,
            "resignations": resignations, "dismissals": dismissals,
            "authoritarian_drift": ladder,
        },
        "council": {
            "motions": len(motions), "substantive": len(decided), "substantive_tabled": len(substantive),
            "unanimous_rate": round(len(unanimous) / len(decided), 3) if decided else None,
            "split_rate": round(len(split) / len(decided), 3) if decided else None,
            "abstention_rate": round(votes_all.count("abstain") / len(votes_all), 3) if votes_all else None,
            "conditional_rate": round(sum(len(m.get("conditional_votes", {})) for m in decided) / max(1, len(votes_all)), 3),
            "withdrawal_rate": round(sum(1 for m in substantive if m.get("withdrawn")) / len(substantive), 3) if substantive else None,
            "failed_rate": round(sum(1 for m in decided if not m.get("passed"))
                                 / len(decided), 3) if decided else None,
            "amendments_per_month": round(sum(1 for m in motions if m.get("type") == "amend" and m.get("passed"))
                                          / max(1, len(history)), 3),
            "redundant_rejections": sum(1 for rec in months for st in rec.get("statements", [])
                                        for bad in st.get("invalid", []) if "duplicat" in bad or "already" in bad),
            "deferred_for_agenda": sum(len(rec.get("deferred", [])) for rec in months),
            "policy_reversals": reversals,
        },
        "negotiation": {
            **negotiation["totals"],
            "final_vote_unanimity": negotiation["final_vote_unanimity"],
            "unanimity_classes": negotiation["unanimity_classes"],
            "monthly": negotiation["monthly_unanimity"],
        },
        "agents": {
            "promises_made": len(promises),
            "promises_kept": sum(1 for p in promises if p.get("status") == "fulfilled"),
            "promises_broken": sum(1 for p in promises if p.get("status") == "broken"),
            "promises_withdrawn": sum(1 for p in promises if p.get("status") == "withdrawn"),
            "promises_lapsed": sum(1 for p in promises if p.get("status") == "lapsed"),
            "principle_violations": sum(len(c.get("violations", [])) for c in commitments),
            "public_private_divergence": {k: sum(1 for d in divergences if d["category"] == k)
                                          for k in ("strategic_restraint", "private_distrust", "broken_promise",
                                                    "direct_contradiction", "genuine_belief_change")},
            "major_belief_reversals": belief_reversals,
            "rivalry_mean": round(sum(rivalries) / len(rivalries), 2) if rivalries else None,
            "trust_spread": round(statistics.pstdev(trusts), 2) if len(trusts) > 1 else None,
            "persuasion_events": sum(len((rec.get("analytics") or {}).get("persuasion", [])) for rec in months),
            "leaks": sum(len(rec.get("leaks", [])) for rec in months),
        },
        "economic": {k: stats(v) for k, v in (("inflation", "infl_yoy"), ("output", "gdp_idx"), ("unemployment", "unemployment"),
                                              ("debt", "debt_gdp"), ("arrears", "arrears_gdp"), ("reserves", "gold"),
                                              ("hunger", "hunger"), ("food_security", "food_ratio"))},
        "security": {"deaths": round(sum(counters.get(k, 0) for k in counters if k.startswith("deaths_") and k != "deaths_natural")
                                     + counters.get("soldiers_killed", 0)),
                     "unrest": stats("unrest"), "army_morale": stats("army_morale"), "army_loyalty": stats("army_loyalty"),
                     "police_loyalty": stats("police_loyalty"),
                     "border_incidents": sum(1 for h in history for e in h.get("events", []) if e.get("kind") in ("border_incident",)
                                             or "border" in str(e.get("issue", ""))),
                     "war_months": sum(1 for h in history if h.get("war")),
                     "blockade_months": sum(1 for h in history if h.get("blockade_eff", 0) > 0)},
        "international": {"league_trust": stats("league_trust"),
                          "union_formed": bool(history and (history[-1].get("union_formed"))),
                          "grain_embargo": stats("grain_embargo"),
                          "foreign_debt": (history[-1].get("hard_state", {}).get("debt_for") if history else None),
                          "alliance": bool(history and (history[-1].get("league") or {}).get("alliance")),
                          "sanctions": bool(history and (history[-1].get("league") or {}).get("sanctions"))},
    }


# ---- why did this happen (spec 61, 103) -------------------------------------------------------------
WORLD_SIGNALS = (("army_loyalty", "army loyalty", 100), ("army_morale", "army morale", 100),
                 ("police_loyalty", "police loyalty", 100), ("unrest", "unrest", 100),
                 ("approval", "government approval", 100), ("infl_yoy", "inflation", 100),
                 ("food_ratio", "food availability", 100), ("unemployment", "unemployment", 100),
                 ("arrears_gdp", "unpaid bills (share of output)", 100))


def surprising_actions(months: list, world: dict, survey: dict | None = None) -> list:
    """Actions worth explaining: departures from stated positions, principles or survey answers."""
    out = []
    members = {m["id"]: m for m in world.get("members", [])}
    for rec in months:
        month = rec.get("month", 0)
        for mo in rec.get("motions", []):
            if mo.get("void"):
                continue
            key = (mo.get("type"), mo.get("subject"), str(mo.get("value", "")).lower())
            for mid, vote in mo.get("votes", {}).items():
                opening = initial_stance((rec.get("pre_positions") or {}).get(mid, {}), mo)
                if opening in ("support", "oppose") and (vote == "yes") != (opening == "support") and vote in ("yes", "no"):
                    out.append({"member": mid, "month": month, "kind": "reversed_own_position", "motion": mo.get("id"),
                                "summary": f"voted {vote} on {mo.get('summary')} after privately leaning {opening}",
                                "topic": mo.get("subject")})
                if key in REPRESSIVE and vote == "yes":
                    said = ((survey or {}).get(mid, {}).get("answers") or {})
                    if (said.get("protests") or {}).get("choice") == "tolerate" or members.get(mid, {}).get("ideology"):
                        out.append({"member": mid, "month": month, "kind": "supported_restriction", "motion": mo.get("id"),
                                    "summary": f"voted for {mo.get('summary')}", "topic": mo.get("subject")})
        for co in rec.get("coups", []):
            out.append({"member": co.get("leader"), "month": month, "kind": "coup",
                        "summary": f"used armed force ({'succeeded' if co.get('success') else 'failed'})", "topic": "coup"})
        for mid in rec.get("resigned", []):
            out.append({"member": mid, "month": month, "kind": "resignation", "summary": "resigned", "topic": "office"})
        for mid, response in (rec.get("election_responses") or {}).items():
            if response in ("refuse", "legal_challenge", "request_recount"):
                out.append({"member": mid, "month": month, "kind": "election_response",
                            "summary": f"responded to the lost election: {response}", "topic": "election"})
        for ev in (rec.get("promise_evaluations") or []):
            if ev.get("verdict") == "broken":
                out.append({"member": ev["member"], "month": month, "kind": "broke_promise",
                            "summary": f"broke a promise: {ev.get('text', '')[:120]}", "topic": "promise"})
    return out


def explain(world: dict, months: list, action: dict, window: int = 6) -> dict:
    """Stored evidence around one action: what changed beforehand, and what the delegate said."""
    history = world.get("history", [])
    mid, month = action["member"], action["month"]
    lo = max(0, month - window)
    before = history[lo - 1] if lo >= 1 and lo - 1 < len(history) else (history[0] if history else {})
    at = history[month - 1] if 1 <= month <= len(history) else before
    factors = []
    for key, label, scale in WORLD_SIGNALS:
        a, b = before.get(key), at.get(key)
        if a is None or b is None:
            continue
        if abs(b - a) * scale >= 5:
            factors.append(f"{label} moved {a * scale:.0f} -> {b * scale:.0f}")
    s0 = (before.get("member_social") or {}).get(mid, {})
    s1 = (at.get("member_social") or {}).get(mid, {})
    for other, rel in (s1.get("relationships") or {}).items():
        t0 = ((s0.get("relationships") or {}).get(other) or {}).get("trust")
        t1 = rel.get("trust")
        if t0 is not None and t1 is not None and abs(t1 - t0) >= 8:
            factors.append(f"{mid}'s trust in {other} moved {t0:.0f} -> {t1:.0f}")
    stress = (s1.get("stress") or {})
    if stress:
        top = max(stress.items(), key=lambda kv: kv[1] if kv[0] != "general" else -1)
        factors.append(f"general stress {stress.get('general', 0):.0f}/100; highest: {top[0]} {top[1]:.0f}")
    events = []
    for h in history[lo:month + 1]:
        for ev in h.get("events", []):
            if ev.get("public", True) and ev.get("importance", 1) >= 2:
                events.append(f"Month {h['month'] + 1}: {ev.get('text', '')[:140]}")
    rec = next((r for r in months if r.get("month") == month), {})
    decision = (rec.get("decisions") or {}).get(mid, {})
    reasons = []
    if action.get("motion"):
        mo = next((m for m in rec.get("motions", []) if m.get("id") == action["motion"]), {})
        if mo.get("vote_reasons", {}).get(mid):
            reasons.append(mo["vote_reasons"][mid])
    earlier = [r for r in months if r.get("month", 0) < month and action.get("topic")
               for m in r.get("motions", []) if m.get("subject") == action.get("topic")
               and m.get("votes", {}).get(mid) in ("yes", "no")]
    prior_votes = [f"Month {r['month'] + 1}: voted {m['votes'][mid]} on {m.get('summary')}" for r in earlier
                   for m in r.get("motions", []) if m.get("subject") == action.get("topic") and m.get("votes", {}).get(mid) in ("yes", "no")][-3:]
    return {"action": action, "world_changes": factors[:8], "events": events[-6:],
            "decision_factors": decision.get("decision_factors", []), "vote_reasons": reasons,
            "initial_position": (rec.get("pre_positions") or {}).get(mid), "prior_votes_on_topic": prior_votes,
            "caveat": "Stored state and stated factors only; correlation, not proven cause."}


def relationship_graph(history: list) -> list:
    """Nodes and directed edges month by month, for playback (spec 102)."""
    frames = []
    for h in history:
        social = h.get("member_social") or {}
        nodes = [{"id": mid, "status": (h.get("members") or {}).get(mid, "active"),
                  "offices": [o for o in OFFICES if (h.get("offices") or {}).get(o) == mid],
                  "influence": ((s.get("standing") or {}).get("influence"))} for mid, s in social.items()]
        edges = []
        for a, s in social.items():
            for b, rel in (s.get("relationships") or {}).items():
                edges.append({"from": a, "to": b, "trust": round(rel.get("trust", 50)), "rivalry": round(rel.get("rivalry", 0)),
                              "dependency": round(rel.get("dependency", 0))})
        frames.append({"month": h.get("month"), "nodes": nodes, "edges": edges})
    return frames
