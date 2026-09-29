"""Subjective beliefs: probabilistic assessments that move with evidence (spec 21, 22, 58).

Each delegate holds its own confidence in a set of propositions about the world and about
colleagues. Evidence arrives from public events, from the delegate's own office reports
(which can be wrong), from reports colleagues chose to share, from leaks, and weakly from the
delegate's own stated revisions. Updates are in log-odds, so beliefs are sticky and need not
converge on the truth. Traits bias interpretation modestly: a paranoid delegate over-weights
hostile signals, a loyal one trusts its own department, a rival's claim is discounted, a
respected colleague's warning counts for more.
"""
from __future__ import annotations

import math

from . import psychology
from .world import World, clamp, rng_for

PROPOSITIONS = {
    "union_annexation": "The Union intends eventual annexation of Karamaniya",
    "union_attack_soon": "The Union will use military force against Karamaniya within six months",
    "kessel_foreign_backed": "Unrest in Kessel Valley is substantially foreign-backed",
    "election_stabilizes": "Holding the election on schedule will stabilize the country",
    "karam_viable": "A national currency can be made credible within a year",
    "league_reliable": "The Maritime League would stand by Karamaniya in a crisis",
    "army_obeys": "The army would obey the civilian government in a crisis",
    "economy_recovers": "The economy will improve over the next six months",
    "police_restraint_works": "The police can keep order without heavy force",
    "food_holds": "Food supplies will hold through the next harvest",
}
HOSTILE = {"union_annexation", "union_attack_soon", "kessel_foreign_backed"}
FOREIGN = {"union_annexation", "union_attack_soon", "league_reliable"}
ECONOMIC = {"economy_recovers", "karam_viable", "food_holds"}
EVIDENCE_WEIGHT = 0.55     # evidence moves beliefs only part of the way; beliefs are sticky
MAX_BIAS = (0.6, 1.5)      # traits change interpretation, but never make a delegate absurd


def _prior(pid: str, t: dict, rng) -> float:
    g = lambda k: t.get(k, 50)
    base = {
        "union_annexation": 45 + .3 * (g("nationalism") - 50) + .2 * (g("paranoia") - 50),
        "union_attack_soon": 22 + .25 * (g("paranoia") - 50) + .2 * (g("security_orientation") - 50),
        "kessel_foreign_backed": 40 + .3 * (g("nationalism") - 50) + .25 * (g("paranoia") - 50),
        "election_stabilizes": 55 + .35 * (g("democratic_commitment") - 50) - .15 * (g("security_orientation") - 50),
        "karam_viable": 45 + .25 * (g("nationalism") - 50) - .2 * (g("fiscal_conservatism") - 50),
        "league_reliable": 50 + .3 * (g("internationalism") - 50) - .2 * (g("paranoia") - 50),
        "army_obeys": 55 + .25 * (g("institutional_loyalty") - 50) - .25 * (g("paranoia") - 50),
        "economy_recovers": 50 + .2 * (g("patience") - 50) + .15 * (g("risk_tolerance") - 50),
        "police_restraint_works": 55 + .35 * (g("civil_libertarianism") - 50) - .3 * (g("security_orientation") - 50),
        "food_holds": 55 - .2 * (g("paranoia") - 50),
    }[pid]
    return round(clamp(base + rng.gauss(0, 8), 5, 95), 1)


def ensure(w: World, mid: str) -> dict:
    state = w.member(mid).agent_state
    props = state.setdefault("propositions", {})
    if not props:
        rng = rng_for(w.seed, 0, f"agent-beliefs:{mid}")
        for pid, text in PROPOSITIONS.items():
            props[pid] = {"text": text, "confidence": _prior(pid, state["traits"], rng),
                          "prior": None, "evidence": [], "last_updated_month": -1, "history": []}
            props[pid]["prior"] = props[pid]["confidence"]
    for other in w.members:
        if other.id == mid:
            continue
        key = f"hiding:{other.id}"
        if key not in props:
            prior = 25 + .3 * (state["traits"].get("paranoia", 50) - 50)
            props[key] = {"text": f"{other.name} is concealing problems in their own area of responsibility",
                          "confidence": round(clamp(prior, 5, 60), 1), "prior": round(clamp(prior, 5, 60), 1),
                          "evidence": [], "last_updated_month": -1, "history": [], "about": other.id}
        key = f"powerbase:{other.id}"
        if key not in props:
            prior = 15 + .25 * (state["traits"].get("paranoia", 50) - 50)
            props[key] = {"text": f"{other.name} is building a personal power base",
                          "confidence": round(clamp(prior, 3, 50), 1), "prior": round(clamp(prior, 3, 50), 1),
                          "evidence": [], "last_updated_month": -1, "history": [], "about": other.id}
    return props


def _logit(p: float) -> float:
    p = clamp(p / 100, .01, .99)
    return math.log(p / (1 - p))


def _prob(x: float) -> float:
    return 100 / (1 + math.exp(-x))


def bias(w: World, mid: str, item: dict) -> float:
    """How strongly this delegate reads one piece of evidence (spec 22)."""
    state = w.member(mid).agent_state
    t = state["traits"]
    pid, source = item["proposition"], item.get("source", "public")
    factor = 1.0
    supports = item["lr"] > 1
    if pid in HOSTILE or pid.startswith(("hiding:", "powerbase:")):
        hostile_reading = supports
        paranoid = (t.get("paranoia", 50) - 50) / 100 * .6
        factor *= 1 + (paranoid if hostile_reading else -paranoid)
        factor *= psychology.stress_modifier(state, "suspicion") if hostile_reading else 1.0
    if pid in FOREIGN and pid != "league_reliable":
        nationalist = (t.get("nationalism", 50) - 50) / 100 * .4
        factor *= 1 + (nationalist if supports else -nationalist)
    if pid in ECONOMIC and not supports:
        factor *= 1 - (t.get("patience", 50) - 50) / 100 * .5
    if source == "office":
        factor *= 1 + (t.get("institutional_loyalty", 50) - 50) / 100 * .5
    if source in ("shared", "leak_member") and item.get("from") in w.member(mid).relationships:
        rel = w.member(mid).relationships[item["from"]]
        factor *= 1 + (rel.get("respect", 50) - 50) / 100 * .5 - rel.get("rivalry", 0) / 100 * .5
        factor *= .7 + .6 * rel.get("perceived_reliability", 50) / 100
    if source == "self":
        factor *= .5
    return clamp(factor, *MAX_BIAS)


def apply(w: World, mid: str, evidence: list) -> list:
    """Fold this month's evidence into one delegate's beliefs. Returns the changes made."""
    props = ensure(w, mid)
    changes = []
    touched = set()
    for item in evidence:
        pid = item["proposition"]
        if pid not in props or item.get("lr", 1) <= 0:
            continue
        b = props[pid]
        before = b["confidence"]
        step = EVIDENCE_WEIGHT * bias(w, mid, item) * math.log(item["lr"])
        b["confidence"] = round(clamp(_prob(_logit(before) + step), 1, 99), 1)
        b["evidence"].append(item["id"])
        del b["evidence"][:-8]
        b["last_updated_month"] = w.month
        touched.add(pid)
        if abs(b["confidence"] - before) >= .5:
            changes.append({"proposition": pid, "from": before, "to": b["confidence"], "evidence": item["id"],
                            "source": item.get("source"), "label": item.get("label", "")})
    for pid, b in props.items():
        # Without fresh evidence a belief slowly relaxes toward the delegate's starting view.
        if pid not in touched and b.get("prior") is not None:
            b["confidence"] = round(b["confidence"] + .03 * (b["prior"] - b["confidence"]), 1)
        b["history"].append([w.month, b["confidence"]])
        del b["history"][:-40]
    return changes


def _ev(w: World, key: str, pid: str, lr: float, label: str, source: str = "public", **extra) -> dict:
    return {"id": f"E{w.month + 1}-{key}", "proposition": pid, "lr": lr, "label": label,
            "source": source, **extra}


def public_evidence(w: World) -> list:
    """Evidence everyone can see: this month's public events and published conditions."""
    out, dip, e = [], w.dip, w.econ
    kinds = {ev.get("kind") for ev in w.events if ev.get("public", True)}
    if "war" in kinds and dip.aggressor == "union":
        out += [_ev(w, "invasion-a", "union_attack_soon", 8.0, "the Union invaded"),
                _ev(w, "invasion-b", "union_annexation", 3.0, "the Union invaded")]
    if dip.ultimatum and not dip.war:
        out += [_ev(w, "ultimatum-a", "union_annexation", 1.6, "a Union ultimatum is in force"),
                _ev(w, "ultimatum-b", "union_attack_soon", 1.5, "a Union ultimatum is in force")]
    if dip.blockade:
        out.append(_ev(w, "blockade", "union_attack_soon", 1.4, "the Union navy is blockading the ports"))
    if "union" in kinds or "union_dispute" in kinds:
        if "union_dispute" in kinds:
            out.append(_ev(w, "union-dispute", "union_attack_soon", .75, "the Union failed to agree on enforcement"))
    if dip.union_formed and w.month % 3 == 0:
        out.append(_ev(w, "union-formed", "union_annexation", 1.2, "the Union persists as a common structure"))
    if dip.ceasefire and not dip.war:
        out.append(_ev(w, "ceasefire", "union_attack_soon", .8, "a ceasefire is holding"))
    if dip.propaganda > .35:
        out.append(_ev(w, "propaganda", "kessel_foreign_backed", 1.25, "Union broadcasts are aimed at Kessel"))
    if any(ev.get("kind") in ("uprising", "arms_cache") for ev in w.events):
        out.append(_ev(w, "armed-kessel", "kessel_foreign_backed", 2.2, "armed groups with foreign weapons appeared"))
    if any(ev.get("kind") == "protest" and "Kessel" in ev.get("text", "") for ev in w.events):
        out.append(_ev(w, "kessel-protest", "kessel_foreign_backed", 1.1, "protests continued in Kessel"))
    if len(w.history) >= 2:
        now, before = w.history[-1], w.history[-2]
        growth = now.get("gdp_idx", 1) - before.get("gdp_idx", 1)
        infl = now.get("published_infl_a", 0) - before.get("published_infl_a", 0)
        signal = 1.0 + growth * 6 - infl * 1.5
        if abs(signal - 1) > .04:
            out.append(_ev(w, "economy", "economy_recovers", clamp(signal, .7, 1.4), "published output and prices moved"))
        food = now.get("food_ratio", 1) - before.get("food_ratio", 1)
        if abs(food) > .01:
            out.append(_ev(w, "food", "food_holds", clamp(1 + food * 8, .6, 1.5), "food availability changed"))
    if e.currency == "karam" and w.month - e.currency_launch in range(0, 6):
        out.append(_ev(w, "karam", "karam_viable", 1.3 if e.fx_conf > .85 else .7 if e.fx_conf < .6 else 1.0,
                       "the karam's first months of trading"))
    if "coup" in kinds or "officers_coup" in kinds:
        out.append(_ev(w, "coup", "army_obeys", .45, "armed force was used against the government"))
    if "defection" in kinds:
        out.append(_ev(w, "defection", "army_obeys", .5, "units went over to the Union"))
    if "refusal" in kinds:
        out.append(_ev(w, "police-refusal", "police_restraint_works", 1.15, "police refused to use force"))
    if "crackdown" in kinds or "massacre" in kinds:
        out.append(_ev(w, "crackdown", "police_restraint_works", .8, "force was used against protesters"))
    if any(ev.get("kind") == "protest" for ev in w.events) and w.policy.protest_response == "tolerate":
        out.append(_ev(w, "tolerated", "police_restraint_works", 1.08, "protests were tolerated"))
    if "mandate" in kinds:
        out.append(_ev(w, "mandate", "election_stabilizes", 1.8, "the election produced a mandate"))
    if "fraud" in kinds:
        out.append(_ev(w, "fraud", "election_stabilizes", .6, "ballot fraud was documented"))
    if dip.league_alliance or dip.league_escort:
        out.append(_ev(w, "league-support", "league_reliable", 1.25, "the League is actively supporting Karamaniya"))
    if dip.league_sanctions:
        out.append(_ev(w, "league-sanctions", "league_reliable", 1.2, "the League sanctioned the Union"))
    return out


def colleague_evidence(w: World, record: dict | None) -> list:
    """Observable signs about colleagues: exposed statistics, defiance, patronage-built loyalty."""
    out = []
    for ev in w.events:
        kind, member = ev.get("kind"), ev.get("member")
        if kind == "defiance" and member:
            out.append(_ev(w, f"defiance-{member}", f"powerbase:{member}", 1.3, "defied a council directive"))
        if kind in ("stats_scandal",) and w.holder("treasury"):
            holder = w.holder("treasury").id
            out.append(_ev(w, f"stats-{holder}", f"hiding:{holder}", 3.0, "falsified statistics were exposed"))
        if kind == "leak" and ev.get("contradiction") and ev.get("member"):
            out.append(_ev(w, f"leak-{member}", f"hiding:{member}", 1.8, "a leak contradicted public statements"))
        if kind == "corruption_allegation" and member:
            out.append(_ev(w, f"corrupt-{member}", f"hiding:{member}", 1.6, "a corruption allegation"))
    for office, force in (("army", w.mil.army), ("navy", w.mil.navy), ("interior", w.mil.police)):
        holder = w.holder(office)
        if holder and force.bond > .3 and w.month % 2 == 0:
            out.append(_ev(w, f"bond-{holder.id}-{office}", f"powerbase:{holder.id}", 1.2 + force.bond,
                           f"units show growing personal loyalty to the {office} commander"))
    return out


def update_all(w: World, record: dict | None, office_evidence: dict, shared_evidence: dict,
               self_reports: dict) -> dict:
    """Apply public, colleague, office, shared and self-reported evidence to every active delegate."""
    common = public_evidence(w) + colleague_evidence(w, record)
    changes = {}
    for m in w.active_members():
        evidence = [x for x in common if x["proposition"] != f"hiding:{m.id}" and x["proposition"] != f"powerbase:{m.id}"]
        evidence += office_evidence.get(m.id, []) + shared_evidence.get(m.id, []) + self_reports.get(m.id, [])
        changes[m.id] = apply(w, m.id, evidence)
        sync_scalars(m.agent_state)
    return changes


def sync_scalars(state: dict) -> None:
    """Keep the four summary beliefs used by older code in step with the propositions."""
    props, beliefs = state.get("propositions", {}), state.setdefault("beliefs", {})
    get = lambda k, d=50: props.get(k, {}).get("confidence", d)
    beliefs["union_threat"] = round(.5 * get("union_annexation") + .5 * get("union_attack_soon"), 1)
    beliefs["economic_outlook"] = round(get("economy_recovers"), 1)
    beliefs["military_reliability"] = round(get("army_obeys"), 1)


def self_report_evidence(w: World, mid: str, updates: list) -> list:
    """Belief revisions the delegate stated. They count, but only weakly (spec 58)."""
    out = []
    props = w.member(mid).agent_state.get("propositions", {})
    for i, item in enumerate(updates[:3]):
        pid = item.get("proposition")
        if pid not in props:
            continue
        lr = 1.35 if item.get("direction") == "more_likely" else 1 / 1.35
        out.append(_ev(w, f"self-{mid}-{i}", pid, lr, "own stated reassessment", source="self",
                       reason=str(item.get("reason", ""))[:160]))
    return out


def band(p: float) -> str:
    return ("almost certainly true" if p >= 90 else "very likely" if p >= 75 else "likely" if p >= 60
            else "a toss-up" if p >= 40 else "unlikely" if p >= 25 else "very unlikely" if p >= 10
            else "almost certainly false")


def context(w: World, mid: str, focus: set | None = None, limit: int = 7) -> str:
    """The delegate's own assessments, in words with rough odds; colleague suspicions only when notable."""
    props = ensure(w, mid)
    items = []
    for pid, b in props.items():
        if pid.startswith(("hiding:", "powerbase:")):
            other = b.get("about")
            if not other or w.member(other).status != "active" or b["confidence"] < 35:
                continue
        moved = abs(b["confidence"] - (b["history"][-4][1] if len(b.get("history", [])) >= 4 else b["confidence"]))
        score = abs(b["confidence"] - 50) / 50 + moved / 20 + (1.0 if focus and pid in focus else 0)
        items.append((score, pid, b))
    items.sort(key=lambda x: -x[0])
    lines = ["WHAT YOU CURRENTLY BELIEVE (your own estimates from what you have seen; they may be wrong)"]
    for _, pid, b in items[:limit]:
        trend = ""
        hist = b.get("history", [])
        if len(hist) >= 4:
            delta = b["confidence"] - hist[-4][1]
            trend = " (more so than three months ago)" if delta >= 8 else " (less so than three months ago)" if delta <= -8 else ""
        shown = round(b["confidence"] / 5) * 5
        lines.append(f"- {b['text']}: {band(shown)}, roughly {shown:.0f}%{trend}.")
    return "\n".join(lines)


def ids_for_schema(w: World, mid: str) -> list:
    return [pid for pid in PROPOSITIONS] + [pid for pid in ensure(w, mid)
                                             if pid.startswith(("hiding:", "powerbase:"))
                                             and w.member(pid.split(":")[1]).status == "active"]
