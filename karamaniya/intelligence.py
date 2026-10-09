"""The information layer (spec 18-20, 53, 67-69): true world -> office reports -> perceptions.

Each office's department produces reports every month: estimates with ranges and a stated
confidence. Some are wrong - from poor data, stale reporting, bureaucratic optimism, the
holder's own expectations, or deliberate deception by the Union - and nothing in the report
says so. The engine keeps the truth next to each report; delegates only see the report.

Delegates can ask a department for a report (it may arrive now, next month, or only in part),
choose to share their own reports with the council or with chosen colleagues, or sit on them.
Private messages, withheld reports and intercepts can leak.
"""
from __future__ import annotations

import hashlib

from . import tuning
from .world import OFFICE_TITLES, OFFICES, World, clamp, rng_for

CONFIDENCE_WIDTH = {"high": .08, "medium": .16, "low": .28}
UNION_SUBJECTS = {"union_intent", "union_strength", "union_fleet", "union_cohesion", "net_assessment"}
REQUEST_TOPICS = {
    "costing": "treasury", "reserves": "treasury", "forecast": "treasury",
    "unrest": "interior", "loyalty": "army", "police": "interior",
    "threat": "army", "convoy": "navy", "diplomatic": "head",
}
TOPIC_SUBJECTS = {
    "costing": "costing", "reserves": "reserves", "forecast": "inflation_forecast",
    "unrest": "unrest_outlook", "loyalty": "officer_loyalty", "police": "police_loyalty",
    "threat": "union_intent", "convoy": "shipping_risk", "diplomatic": "league_stance",
}


def state(w: World) -> dict:
    s = w.intel
    for key in ("reports", "requests", "deliveries", "shared", "leaks", "withheld"):
        s.setdefault(key, [])
    return s


# ---- hidden truth -------------------------------------------------------------------------
def union_offensive_risk(w: World) -> float:
    """The engine's own probability that the Union is preparing force. Never shown directly."""
    from .director import _power_ratio
    union = w.foreign.get("union", {}) if w.foreign else {}
    vel = w.foreign.get("actors", {}).get("veleria", {}) if w.foreign else {}
    threat = vel.get("threat_perception", {}).get("karamaniya", .45)
    risk_tol = vel.get("disposition", {}).get("risk_tolerance", .38)
    threshold = 2.0 + .55 * risk_tol
    ratio = _power_ratio(w) if w.mil else 1.0
    dip = w.dip
    if dip.war:
        return .97
    risk = (.06 + .45 * clamp(ratio / threshold) * union.get("cohesion", .7) + .3 * threat
            + (.18 if dip.ultimatum else 0) + (.08 if dip.blockade else 0) - (.12 if dip.nonaggression else 0)
            - (.08 if dip.league_alliance else 0) - .1 * dip.union_weariness)
    return round(clamp(risk, .02, .95), 3)


def _truths(w: World) -> dict:
    from .military import mobilized_strength, union_army, union_navy
    from .society import inflation_yoy
    e, m, dip = w.econ, w.mil, w.dip
    z = w.zone_of("karamaniya")
    expected = (1 + z.exp_infl) ** 12 - 1
    k_regions = sorted(w.k_regions(), key=lambda r: -r.unrest)
    union = w.foreign.get("union", {}) if w.foreign else {}
    unrest = w.avg("unrest") if w.k_pops() else 0.0
    protesters = sum(p.size * max(0.0, p.unrest - .25) * .08 for p in w.k_pops())
    return {
        "reserves": e.gold / 1e6,
        "inflation_forecast": clamp(.6 * expected + .4 * inflation_yoy(w), -.2, 50) * 100,
        "default_risk": clamp(e.arrears / max(e.gdp_nominal, 1) * 1.8 + max(0, .6 - e.confidence)
                              + (e.debt_for * max(e.fx, 1)) / max(24 * e.gdp_nominal, 1)) * 100,
        "lender_confidence": clamp(e.confidence) * 100,
        "hidden_budget_stress": e.arrears / 1e6,
        "unrest_outlook": clamp(unrest + .5 * max(0, w.avg("grievance") - unrest)) * 100 if w.k_pops() else 0,
        "protest_turnout": protesters,
        "police_loyalty": m.police.loyalty * 100,
        "foreign_backing": clamp(.15 + .45 * dip.propaganda + (.35 if dip.arms_smuggling else 0)) * 100,
        "union_strength": union_army(w),
        "union_intent": union_offensive_risk(w) * 100,
        "officer_loyalty": m.army.loyalty * 100,
        "readiness": clamp(m.army.morale * .5 + m.army.training * .3 + min(1, m.army.equipment) * .2) * 100,
        # Union soldiers for each of ours under arms (engine 13): what the net assessment is about.
        "net_assessment": union_army(w) / max(1.0, m.army.size + mobilized_strength(w)),
        "shipping_risk": clamp(dip.blockade_eff * .6 + (.2 if dip.blockade else 0) + .1 * float(dip.union_formed)
                               + (w.foreign.get("league", {}).get("shipping_security_concern", 0) * .3 if w.foreign else 0)) * 100,
        "union_fleet": union_navy(w),
        "fleet_readiness": clamp(m.navy.morale * .6 + m.navy.training * .4) * 100,
        "league_stance": clamp(dip.league_trust) * 100,
        "union_cohesion": union.get("cohesion", .7) * 100,
        "coalition_stability": _coalition_stability(w) * 100,
        "food_outlook": clamp(e.food_ratio, 0, 1.5) * 100,
        "worst_region": k_regions[0].name if k_regions else "",
    }


def _coalition_stability(w: World) -> float:
    trusts = [rel.get("trust", 50) for m in w.active_members() for o, rel in m.relationships.items()
              if w.member(o).status == "active"]
    return clamp((sum(trusts) / len(trusts) / 100) if trusts else .5)


SUBJECTS = {
    "treasury": ("reserves", "inflation_forecast", "default_risk", "lender_confidence", "hidden_budget_stress"),
    "interior": ("unrest_outlook", "protest_turnout", "police_loyalty", "foreign_backing"),
    # The net assessment is last, so the four engine-12 reports keep their ids and their draws.
    "army": ("union_strength", "union_intent", "officer_loyalty", "readiness", "net_assessment"),
    "navy": ("shipping_risk", "union_fleet", "fleet_readiness"),
    "head": ("league_stance", "union_cohesion", "coalition_stability", "union_intent"),
}
BASE_CONFIDENCE = {
    "reserves": "high", "inflation_forecast": "medium", "default_risk": "low", "lender_confidence": "medium",
    "hidden_budget_stress": "high", "unrest_outlook": "medium", "protest_turnout": "low",
    "police_loyalty": "medium", "foreign_backing": "low", "union_strength": "medium", "union_intent": "low",
    "officer_loyalty": "medium", "readiness": "medium", "shipping_risk": "medium", "union_fleet": "high",
    "fleet_readiness": "high", "league_stance": "medium", "union_cohesion": "low", "coalition_stability": "medium",
    "net_assessment": "medium",
}
# Subjects where a report says something alarming, and the proposition it bears on.
PROPOSITION = {"union_intent": "union_attack_soon", "foreign_backing": "kessel_foreign_backed",
               "officer_loyalty": "army_obeys", "inflation_forecast": "economy_recovers",
               "league_stance": "league_reliable", "police_loyalty": "police_restraint_works",
               "default_risk": "economy_recovers", "food_outlook": "food_holds"}

# Subjects two departments read from different sources, and the way each one's method leans
# (+1 reads high, -1 reads low). Each month one of them is in dispute. Neither report is an
# error in the engine's sense: each is what that department's method honestly produces, and
# the truth stays hidden as it does for every report. Treasury is the usual second opinion
# because it pays for everything the others measure.
CONTESTED = {
    "unrest_outlook": {"interior": 1, "treasury": -1},
    "food_outlook": {"treasury": 1, "interior": -1},
    "readiness": {"army": 1, "treasury": -1},
    "union_intent": {"army": 1, "head": -1},
    "shipping_risk": {"navy": 1, "treasury": -1},
}
LENS_SOURCE = {
    ("unrest_outlook", "interior"): "Interior field reports (police district returns)",
    ("unrest_outlook", "treasury"): "Treasury regional tax offices (collections and strike returns)",
    ("food_outlook", "treasury"): "Treasury grain board (stock and delivery returns)",
    ("food_outlook", "interior"): "Interior market watch (police reports on queues and prices)",
    ("readiness", "army"): "Army readiness inspection (training, equipment and morale)",
    ("readiness", "treasury"): "Treasury audit of military spending",
    ("union_intent", "army"): "Army intelligence (border observation posts)",
    ("union_intent", "head"): "Diplomatic cables (embassy reporting)",
    ("shipping_risk", "navy"): "Naval staff (patrol reports)",
    ("shipping_risk", "treasury"): "Treasury, from marine insurance rates",
}
LENS_TEXT = {
    "unrest_outlook": "national unrest next month assessed at {lo:.0f}-{hi:.0f}/100",
    "food_outlook": "food supply next month expected to cover {lo:.0f}-{hi:.0f}% of needs",
    "readiness": "{lo:.0f}-{hi:.0f}/100 of nominal combat readiness, the army's own condition and not its strength against the {union}",
    "union_intent": "a {lo:.0f}-{hi:.0f}% probability that {union} deployments are preparation for force rather than posture",
    "shipping_risk": "shipping-interdiction risk {lo:.0f}-{hi:.0f}/100 on the grain routes",
}
DEPARTMENT = {"head": "diplomatic service", "treasury": "Treasury", "interior": "Interior ministry",
              "army": "Army staff", "navy": "Naval staff"}


def _error(w: World, rng, subject: str, holder_state: dict) -> str:
    rate = float(tuning.get(w, "intelligence.error_rate"))
    repression = w.avg("repression") if w.k_pops() else 0.0
    rate *= (1 + (1 - w.econ.admin_capacity)) * (1 + .5 * repression) * (1.3 if w.dip.war else 1.0)
    if subject in ("reserves", "fleet_readiness", "hidden_budget_stress"):
        rate *= .35            # a department knows its own books better than the world
    deception = float(tuning.get(w, "intelligence.deception_rate")) * (w.dip.propaganda + .3) if subject in UNION_SUBJECTS else 0.0
    stale = float(tuning.get(w, "intelligence.stale_rate"))
    roll = rng.random()
    if roll < deception:
        return "deception"
    if roll < deception + stale:
        return "stale"
    if roll < deception + stale + rate:
        return rng.choice(("bureaucratic", "confirmation", "measurement"))
    return "none"


def _report(w: World, rng, office: str, subject: str, truths: dict, prev_truths: dict, holder_state: dict,
            index: int, basis: dict | None = None) -> dict:
    truth = truths[subject]
    if basis is not None:
        # The net assessment works from the strength report beside it, so the two give the same Union
        # army, and the assessment carries that estimate's error, planted or honest. Drawn on its own,
        # it once put the Union at 119,909 next to a strength report of 82,037-113,289.
        kind = basis["error"]
        strength = float(truths.get("union_strength") or 0.0)
        central = truth * (basis["estimate"] / strength) if strength > 1e-9 else truth
    else:
        kind = _error(w, rng, subject, holder_state)
        lo_shift, hi_shift = tuning.get(w, "intelligence.wrong_shift")
        central = truth
        if kind == "stale":
            central = prev_truths.get(subject, truth)
        elif kind != "none":
            magnitude = rng.uniform(lo_shift, hi_shift)
            if kind == "bureaucratic":
                sign = -1 if subject in ("default_risk", "unrest_outlook", "protest_turnout", "hidden_budget_stress",
                                         "foreign_backing", "shipping_risk", "union_intent") else 1
            elif kind == "confirmation":
                props = holder_state.get("propositions", {})
                prop = PROPOSITION.get(subject)
                believed = props.get(prop, {}).get("confidence", 50) if prop else 50
                sign = 1 if believed >= 50 else -1
                if subject in ("officer_loyalty", "police_loyalty", "league_stance"):
                    sign = 1 if believed >= 50 else -1
            else:
                sign = rng.choice((-1, 1))
            central = truth * (1 + sign * magnitude) if abs(truth) > 1e-9 else sign * magnitude * 10
        central += central * rng.gauss(0, .04)
    confidence = BASE_CONFIDENCE.get(subject, "medium")
    if kind == "deception" and rng.random() < .5:
        confidence = "medium"      # a planted report can look solid
    width = CONFIDENCE_WIDTH[confidence] * (1.4 if w.dip.war else 1.0)
    low, high = central * (1 - width), central * (1 + width)
    if subject == "inflation_forecast":
        spread = max(2.0, abs(central) * width)
        low, high = central - spread, central + spread
    if subject in ("union_intent", "default_risk", "foreign_backing", "officer_loyalty", "police_loyalty",
                   "unrest_outlook", "shipping_risk", "lender_confidence", "readiness", "fleet_readiness",
                   "league_stance", "union_cohesion", "coalition_stability"):
        spread = {"high": 6, "medium": 12, "low": 20}[confidence]
        low, high = clamp(central - spread, 0, 100), clamp(central + spread, 0, 100)
        central = clamp(central, 0, 100)
    accurate = min(low, high) - 1e-9 <= truth <= max(low, high) + 1e-9
    alarming = _alarming(subject, central)
    report = {"id": f"R{w.month + 1}-{office[:3].upper()}{index}", "month": w.month, "office": office,
              "subject": subject, "estimate": round(central, 2), "low": round(min(low, high), 2),
              "high": round(max(low, high), 2), "confidence": confidence,
              "proposition": PROPOSITION.get(subject), "alarming": alarming,
              "truth": round(truth, 2), "accurate": accurate, "error": kind,
              "shared_with": [], "requested_by": []}
    if subject == "net_assessment":
        # The assessment's foreign figures carry this report's error, planted or honest.
        report["factor"] = round(central / truth, 4) if truth > 1e-9 else 1.0
        report["alarming"] = assessment_alarming(w, report["factor"])
    report["text"] = render(w, report, truths)
    return report


URGENT_MONTHS = 6


def assessment_alarming(w: World, factor: float = 1.0) -> bool:
    """The net assessment is urgent when the troops massed at a border, or fighting on it, would take the
    front's first region within URGENT_MONTHS at these strengths. The Union's standing superiority (over
    three to one in a new world) is the situation, not news: engine 13 marked the assessment urgent whenever
    it held, from Month 1 on, so the Army office had to share it every month or have it recorded as
    withheld, where it could leak and cost the holder its colleagues' trust."""
    from .military import net_assessment
    for front in net_assessment(w, factor)["fronts"].values():
        months = front.get("enemy_months") if front.get("fighting") else front.get("massed_months")
        if months is not None and months <= URGENT_MONTHS:
            return True
    return False


def _alarming(subject: str, central: float) -> bool:
    return ((subject == "union_intent" and central >= 50) or (subject == "default_risk" and central >= 45)
            or (subject == "officer_loyalty" and central <= 45) or (subject == "foreign_backing" and central >= 55)
            or (subject == "protest_turnout" and central >= 40000) or (subject == "shipping_risk" and central >= 55)
            or (subject == "food_outlook" and central < 85))


def render(w: World, r: dict, truths: dict | None = None) -> str:
    s, lo, hi, est, conf = r["subject"], r["low"], r["high"], r["estimate"], r["confidence"]
    union = w.names.get("union", "Union")
    if r.get("contested") and s in LENS_TEXT:
        note = (f" Staff note: the {DEPARTMENT.get(r.get('rival_office'), r.get('rival_office'))} puts this "
                f"{r['rival_reads']}, working from different sources." if r.get("rival_reads") else "")
        return f"{r['source']}: {LENS_TEXT[s].format(lo=lo, hi=hi, union=union)}.{note} Confidence: {conf}."
    if s == "net_assessment":
        from .decision_context import net_assessment_text
        return net_assessment_text(w, r.get("factor", 1.0)) + f" Confidence: {conf}."
    texts = {
        "reserves": f"Treasury cash desk: foreign reserves about {est:,.0f}M gold ({lo:,.0f}-{hi:,.0f}M).",
        "inflation_forecast": f"Treasury forecast: annual inflation over the next six months, central estimate {est:.0f}%, plausible range {lo:.0f}-{hi:.0f}%.",
        "default_risk": f"Treasury risk desk: {lo:.0f}-{hi:.0f}% probability of a payment crisis within six months.",
        "lender_confidence": f"Treasury market desk: lenders' confidence assessed at {lo:.0f}-{hi:.0f}/100.",
        "hidden_budget_stress": f"Treasury ledger: unpaid bills including late-reported liabilities about {est:,.0f}M crowns ({lo:,.0f}-{hi:,.0f}M).",
        "unrest_outlook": f"Interior field reports: national unrest next month assessed at {lo:.0f}-{hi:.0f}/100.",
        "protest_turnout": f"Interior believes {max(0, lo):,.0f}-{max(0, hi):,.0f} people may join demonstrations next month.",
        "police_loyalty": f"Interior command review: police loyalty to the state assessed at {lo:.0f}-{hi:.0f}/100.",
        "foreign_backing": f"Interior special branch: {lo:.0f}-{hi:.0f}% probability that Kessel unrest is substantially foreign-backed.",
        "union_strength": f"Army intelligence estimates {union} field strength at {lo:,.0f}-{hi:,.0f} troops.",
        "union_intent": f"Intelligence assesses a {lo:.0f}-{hi:.0f}% probability that {union} deployments are preparation for force rather than posture.",
        "officer_loyalty": f"Army staff survey: officer loyalty to the constitutional government assessed at {lo:.0f}-{hi:.0f}/100.",
        "readiness": f"Army readiness inspection: {lo:.0f}-{hi:.0f}/100 of nominal combat readiness (training, equipment and "
                     f"morale: the army's own condition, not its strength against the {union}).",
        "shipping_risk": f"Naval staff: shipping-interdiction risk {lo:.0f}-{hi:.0f}/100 on the grain routes.",
        "union_fleet": f"Naval intelligence counts about {est:.0f} {union} warships ({lo:.0f}-{hi:.0f}).",
        "fleet_readiness": f"Fleet readiness report: {lo:.0f}-{hi:.0f}/100.",
        "league_stance": f"Diplomatic cables: the Maritime League's willingness to back Karamaniya assessed at {lo:.0f}-{hi:.0f}/100.",
        "union_cohesion": f"Diplomatic cables: {union} cohesion assessed at {lo:.0f}-{hi:.0f}/100.",
        "coalition_stability": f"Cabinet secretariat: council working trust assessed at {lo:.0f}-{hi:.0f}/100.",
        "food_outlook": f"Grain board forecast: food supply next month expected to cover {lo:.0f}-{hi:.0f}% of needs.",
        "costing": r.get("costing_text", ""),
    }
    return texts.get(s, f"{s}: {lo}-{hi}") + f" Confidence: {conf}."


def generate(w: World) -> list:
    """This month's office reports (Phase 1: information distribution)."""
    s = state(w)
    if any(r["month"] == w.month for r in s["reports"]):
        return [r for r in s["reports"] if r["month"] == w.month]
    truths = _truths(w)
    prev = s.get("last_truths", {}) or truths
    new = []
    for office in OFFICES:
        holder = w.holder(office)
        if holder is None:
            continue
        rng = rng_for(w.seed, w.month, f"intel-v2:{office}")
        holder_state = holder.agent_state or {}
        for i, subject in enumerate(SUBJECTS[office], 1):
            # The General Staff reads its net assessment off Army intelligence's estimate of Union strength.
            basis = (next((r for r in new if r["office"] == office and r["subject"] == "union_strength"), None)
                     if subject == "net_assessment" else None)
            new.append(_report(w, rng, office, subject, truths, prev, holder_state, i, basis))
    contest = _contest(w, truths, new)
    s["reports"] = [r for r in s["reports"] if w.month - r["month"] < int(tuning.get(w, "intelligence.report_months_kept"))] + new
    s["last_truths"] = {k: v for k, v in truths.items() if isinstance(v, (int, float))}
    if contest:
        s["contested"] = [x for x in s.get("contested", []) if w.month - x["month"] < 24] + [contest]
    return new


def _contest(w: World, truths: dict, new: list) -> dict | None:
    """This month's disputed subject: two departments, two honest methods, two readings.

    It draws from its own seeded stream, so the ordinary reports are unchanged by it. A department
    that already reports on the subject has that report replaced by its own reading; the other
    department's reading is added. Each report notes that the other department reads it
    differently, and which way, but never gives the other's figure."""
    if not tuning.get(w, "intelligence.contested"):
        return None
    rng = rng_for(w.seed, w.month, "intel-contested")
    if rng.random() >= float(tuning.get(w, "intelligence.contested_rate")):
        return None
    options = []
    for subject, lenses in CONTESTED.items():
        holders = [w.holder(o) for o in lenses]
        if any(h is None for h in holders):
            continue
        options.append((subject, 3.0 if len({h.id for h in holders}) > 1 else 1.0))
    if not options:
        return None
    pick = rng.random() * sum(weight for _, weight in options)
    for subject, weight in options:
        pick -= weight
        if pick <= 0:
            break
    truth = truths[subject]
    top = 150.0 if subject == "food_outlook" else 100.0
    lo_bias, hi_bias = tuning.get(w, "intelligence.contested_bias")
    lenses = CONTESTED[subject]
    lean = {office: rng.uniform(float(lo_bias), float(hi_bias)) for office in lenses}
    gap = float(tuning.get(w, "intelligence.contested_min_gap"))
    if sum(lean.values()) < gap:
        lean = {office: x * gap / sum(lean.values()) for office, x in lean.items()}
    readings = {}
    for office, sign in lenses.items():
        central = clamp(truth + sign * lean[office] + rng.gauss(0, 1.5), 0, top)
        own_turf = subject in SUBJECTS.get(office, ())
        half = 5.0 if own_turf else 7.0
        readings[office] = (central, clamp(central - half, 0, top), clamp(central + half, 0, top),
                            "high" if own_turf and subject != "union_intent" else "medium")
    offices = list(lenses)
    entry = {"month": w.month, "subject": subject, "truth": round(truth, 2), "reports": {}}
    for office in offices:
        rival = next(o for o in offices if o != office)
        central, low, high, confidence = readings[office]
        existing = next((r for r in new if r["office"] == office and r["subject"] == subject), None)
        if existing is None:
            index = sum(1 for r in new if r["office"] == office) + 1
            existing = {"id": f"R{w.month + 1}-{office[:3].upper()}{index}", "month": w.month, "office": office,
                        "subject": subject, "shared_with": [], "requested_by": []}
            new.append(existing)
        existing.update({"estimate": round(central, 2), "low": round(low, 2), "high": round(high, 2),
                         "confidence": confidence, "proposition": PROPOSITION.get(subject),
                         "alarming": _alarming(subject, central), "truth": round(truth, 2),
                         "accurate": low - 1e-9 <= truth <= high + 1e-9, "error": "lens",
                         "contested": True, "lens": "reads high" if lenses[office] > 0 else "reads low",
                         "source": LENS_SOURCE[(subject, office)], "rival_office": rival,
                         "rival_reads": "higher" if readings[rival][0] > central else "lower"})
        existing["text"] = render(w, existing, truths)
        entry["reports"][office] = {"id": existing["id"], "estimate": existing["estimate"],
                                    "low": existing["low"], "high": existing["high"],
                                    "accurate": existing["accurate"]}
    entry["closer"] = min(offices, key=lambda o: abs(readings[o][0] - truth))
    return entry


def reports_for(w: World, mid: str, month: int | None = None) -> list:
    month = w.month if month is None else month
    offices = set(w.offices_of(mid))
    return [r for r in state(w)["reports"] if r["month"] == month and r["office"] in offices]


def own_report_ids(w: World, mid: str) -> list:
    return [r["id"] for r in reports_for(w, mid)]


def shared_with(w: World, mid: str, month: int | None = None) -> list:
    month = w.month if month is None else month
    out = []
    for item in state(w)["shared"]:
        if item["month"] == month and item["from"] != mid and (item["with"] == "council" or item["with"] == mid):
            out.append(item)
    return out


def deliveries_for(w: World, mid: str) -> list:
    return [d for d in state(w)["deliveries"] if d["to"] == mid and d["deliver_month"] == w.month
            and d.get("phase_ready", "session") in ("session", "revision", "decision")]


def office_context(w: World, mid: str, phase: str = "session") -> str:
    """Private office reports, colleague-shared reports and answered requests for one delegate."""
    lines = []
    own = reports_for(w, mid)
    if own:
        lines.append("PRIVATE OFFICE INFORMATION (your departments' reports; estimates can be wrong and do not say when they are)")
        for r in own:
            lines.append(f"- [{r['id']}] {r['text']}" + (" (Marked urgent by staff.)" if r["alarming"] else ""))
        lines.append("You decide whether to share these reports with the council, with chosen colleagues, or not at all.")
    else:
        lines.append("PRIVATE OFFICE INFORMATION\nYou hold no office, so you receive no departmental reports. "
                     "You know only what is published, what colleagues share, what you request, and what leaks.")
    shared = shared_with(w, mid)
    if phase in ("revision", "decision"):
        shared += [x for x in state(w)["shared"] if x["month"] == w.month and x.get("phase") == "revision"
                   and x not in shared and x["from"] != mid and x["with"] in ("council", mid)]
    earlier = [x for x in state(w)["shared"] if x["month"] == w.month - 1 and x.get("phase") == "decision"
               and x["from"] != mid and x["with"] in ("council", mid)]
    items = [x for x in shared + earlier]
    if items:
        lines.append("REPORTS SHARED WITH YOU")
        for item in items[:6]:
            who = w.member(item["from"]).name
            scope = "with the whole council" if item["with"] == "council" else "with you privately"
            lines.append(f"- {who} shared {scope}: {item['text']}")
    delivered = deliveries_for(w, mid)
    if delivered:
        lines.append("ANSWERS TO YOUR INFORMATION REQUESTS")
        for d in delivered:
            lines.append(f"- {d['text']}")
    pending = [q for q in state(w)["requests"] if q["from"] == mid and q["status"] == "pending"]
    if pending:
        lines.append("Still awaited: " + "; ".join(f"{q['topic']} from {OFFICE_TITLES.get(q['office'], q['office'])}" for q in pending) + ".")
    incoming = [q for q in state(w)["requests"] if q["office"] in w.offices_of(mid) and q["month"] == w.month - 1
                or (q["office"] in w.offices_of(mid) and q["month"] == w.month and phase != "session")]
    if incoming:
        lines.append("Your departments were asked for: " + "; ".join(
            f"{q['topic']} by {w.member(q['from']).name}" for q in incoming[:4]) + ".")
    return "\n".join(lines)


# ---- sharing ----------------------------------------------------------------------------
def share(w: World, mid: str, items: list, phase: str) -> list:
    """Record reports a delegate chose to pass on. Returns the shares accepted."""
    s = state(w)
    own = {r["id"]: r for r in reports_for(w, mid)}
    accepted = []
    for item in items[:3]:
        rid, target = item.get("report_id"), item.get("with", "council")
        if rid not in own:
            continue
        if target != "council" and (target not in {m.id for m in w.active_members()} or target == mid):
            continue
        r = own[rid]
        if target in r["shared_with"]:
            continue
        r["shared_with"].append(target)
        entry = {"month": w.month, "phase": phase, "from": mid, "with": target, "report_id": rid,
                 "text": r["text"], "proposition": r.get("proposition"), "estimate": r["estimate"],
                 "subject": r["subject"], "accurate": r["accurate"]}
        s["shared"].append(entry)
        accepted.append(entry)
    s["shared"] = [x for x in s["shared"] if w.month - x["month"] <= 6]
    return accepted


def flag_withheld(w: World) -> list:
    """Alarming reports the holder did not pass to the council this month."""
    s = state(w)
    flagged = []
    for r in s["reports"]:
        if r["month"] == w.month and r["alarming"] and "council" not in r["shared_with"]:
            holder = w.holder(r["office"])
            if holder is None:
                continue
            entry = {"month": w.month, "report_id": r["id"], "holder": holder.id, "subject": r["subject"],
                     "text": r["text"], "revealed": False}
            s["withheld"].append(entry)
            flagged.append(entry)
    s["withheld"] = [x for x in s["withheld"] if w.month - x["month"] <= 12]
    return flagged


# ---- requests ---------------------------------------------------------------------------
def request(w: World, mid: str, items: list, phase: str, motions: list) -> list:
    s = state(w)
    accepted = []
    for item in items[:2]:
        topic = item.get("topic")
        if topic not in REQUEST_TOPICS:
            continue
        office = REQUEST_TOPICS[topic]
        motion_id = str(item.get("motion_id", "") or "")
        motion = next((m for m in motions if m.get("id") == motion_id), None)
        entry = {"id": f"Q{w.month + 1}-{mid}-{len(s['requests']) + 1}", "month": w.month, "phase": phase,
                 "from": mid, "office": office, "topic": topic, "motion_id": motion_id if motion else "",
                 "status": "pending"}
        s["requests"].append(entry)
        accepted.append(entry)
    return accepted


def answer_requests(w: World, capacity: dict, motions: list, phase: str) -> list:
    """Ministries answer what they can; quality and timing follow their capacity (spec 69, 70)."""
    s = state(w)
    per_office = {}
    delivered = []
    rng = rng_for(w.seed, w.month, f"intel-requests:{phase}")
    truths = None
    for q in s["requests"]:
        if q["status"] != "pending":
            continue
        office = q["office"]
        used = per_office.get(office, 0)
        cap = capacity.get(office, .6)
        limit = int(tuning.get(w, "intelligence.request_capacity"))
        if used >= limit or w.holder(office) is None and office != "treasury":
            continue
        per_office[office] = used + 1
        same_month = phase == "session" and q["month"] == w.month and cap >= .55 and rng.random() < .35 + .6 * cap
        if q["month"] == w.month and not same_month:
            continue            # it will be answered next month
        truths = truths or _truths(w)
        partial = cap < .45 or rng.random() > .5 + .5 * cap
        text = _answer_text(w, q, truths, partial, motions, rng)
        q["status"] = "answered"
        entry = {"request_id": q["id"], "to": q["from"], "deliver_month": w.month,
                 "phase_ready": "revision" if same_month else "session", "text": text, "partial": partial,
                 "office": office, "topic": q["topic"]}
        s["deliveries"].append(entry)
        delivered.append(entry)
    for q in s["requests"]:
        if q["status"] == "pending" and w.month - q["month"] >= 2:
            q["status"] = "lapsed"
    s["deliveries"] = [d for d in s["deliveries"] if w.month - d["deliver_month"] <= 3]
    s["requests"] = [q for q in s["requests"] if w.month - q["month"] <= 6]
    return delivered


def _answer_text(w: World, q: dict, truths: dict, partial: bool, motions: list, rng) -> str:
    office = OFFICE_TITLES.get(q["office"], q["office"])
    width = .35 if partial else .15
    note = " Only part of the data was available; treat it as indicative." if partial else ""
    if q["topic"] == "costing":
        motion = next((m for m in motions if m.get("id") == q.get("motion_id")), None)
        if motion is None:
            motion = next((m for m in motions if m.get("type") == "set_policy"), None)
        cost = costing(w, motion) if motion else None
        if cost is None:
            return f"{office}: no costable proposal was identified in the request.{note}"
        central = cost * (1 + rng.gauss(0, width / 2))
        lo, hi = central * (1 - width), central * (1 + width)
        verb = "costs" if central >= 0 else "saves"
        return (f"{office} costing of {motion.get('id')} ({motion.get('summary', motion.get('subject'))}): it {verb} about "
                f"{abs(lo) / 1e6:,.0f}-{abs(hi) / 1e6:,.0f}M crowns a month at current output.{note}")
    subject = TOPIC_SUBJECTS[q["topic"]]
    truth = truths.get(subject, 0)
    central = truth * (1 + rng.gauss(0, width / 2))
    lo, hi = central * (1 - width), central * (1 + width)
    fake = {"subject": subject, "low": round(min(lo, hi), 1), "high": round(max(lo, hi), 1),
            "estimate": round(central, 1), "confidence": "low" if partial else "medium"}
    if subject in ("union_intent", "officer_loyalty", "police_loyalty", "unrest_outlook", "shipping_risk", "league_stance"):
        fake["low"], fake["high"] = round(clamp(central - 100 * width / 2, 0, 100)), round(clamp(central + 100 * width / 2, 0, 100))
    return f"Requested from {office}: " + render(w, fake) + note


def costing(w: World, motion: dict | None) -> float | None:
    """Monthly fiscal effect of a policy motion at current output (positive = costs money)."""
    from .politics import parse_lever
    if not motion or motion.get("type") != "set_policy":
        return None
    lever = motion.get("subject")
    value = parse_lever(lever, motion.get("value"))
    current = getattr(w.policy, lever, None)
    if value is None or current is None or isinstance(value, (bool, str)):
        if lever == "officer_pay" and isinstance(value, str):
            from .military import ARMY_COST, OFFICER_PAY
            bill = w.mil.army.size * ARMY_COST * w.econ.cpi
            return (OFFICER_PAY[value]["bill"] - OFFICER_PAY.get(current, OFFICER_PAY["standard"])["bill"]) * bill
        if lever == "regional_fund" and isinstance(value, str):
            from .regional import FUND_COST, REGIONS
            count = lambda fund: len(REGIONS) if fund == "both" else 1 if fund in REGIONS else 0
            return (count(value) - count(current)) * FUND_COST * w.econ.gdp_nominal
        if lever == "rationing":
            return .004 * w.econ.gdp_nominal if value else -.004 * w.econ.gdp_nominal
        if lever == "shipbuilding":
            return .003 * w.econ.gdp_nominal if value else -.003 * w.econ.gdp_nominal
        if lever == "imports" and value == "max":
            return .01 * w.econ.gdp_nominal
        return None
    gdp = w.econ.gdp_nominal
    if lever in ("military", "police", "welfare", "health_edu", "farm_support"):
        return (value - current) * gdp
    if lever == "tax":
        return -(value - current) * gdp * w.econ.compliance
    if lever == "army_target":
        return (value - w.mil.army.size) * 900
    return None


# ---- evidence for beliefs ------------------------------------------------------------------
def office_evidence(w: World) -> tuple[dict, dict]:
    """Evidence each delegate draws from its own reports, and from reports shared with it."""
    own, shared, shared_ids = {}, {}, {}
    for m in w.active_members():
        for r in reports_for(w, m.id):
            ev = _report_evidence(w, r, "office")
            if ev:
                own.setdefault(m.id, []).append(ev)
    for item in state(w)["shared"]:
        if item["month"] != w.month or not item.get("proposition"):
            continue
        targets = [m.id for m in w.active_members() if m.id != item["from"]] if item["with"] == "council" else [item["with"]]
        for mid in targets:
            ev = _report_evidence(w, {"id": item["report_id"] + f"-{mid}", "proposition": item["proposition"],
                                      "estimate": item["estimate"], "subject": item["subject"]}, "shared")
            if ev:
                # A council share already reaches every colleague. If the sender also shared the
                # same report privately with one of them, count that report only once.
                seen = shared_ids.setdefault(mid, set())
                if ev["id"] in seen:
                    continue
                seen.add(ev["id"])
                ev["from"] = item["from"]
                shared.setdefault(mid, []).append(ev)
    return own, shared


def _report_evidence(w: World, r: dict, source: str) -> dict | None:
    pid = r.get("proposition")
    if not pid:
        return None
    est = r["estimate"]
    subject = r["subject"]
    if subject in ("union_intent", "foreign_backing"):
        p = clamp(est / 100, .03, .97)
        lr = clamp((p / (1 - p)) ** .5, .4, 2.5)
    elif subject in ("officer_loyalty", "police_loyalty", "league_stance"):
        lr = clamp(1 + (est - 55) / 60, .5, 1.8)
    elif subject == "inflation_forecast":
        lr = clamp(1 - (est - 10) / 80, .6, 1.3)
    elif subject == "default_risk":
        lr = clamp(1 - (est - 25) / 100, .6, 1.2)
    elif subject == "food_outlook":
        lr = clamp(1 + (est - 95) / 40, .6, 1.5)
    else:
        return None
    return {"id": f"E{w.month + 1}-{r['id']}", "proposition": pid, "lr": lr, "source": source,
            "label": f"{source} report {r['id']}"}


# ---- leaks ----------------------------------------------------------------------------------
def leaks(w: World, dms: list, intercepts: list) -> list:
    """Seeded, circumstance-driven leaks at month end (spec 67). Nothing leaks by default rule."""
    s = state(w)
    rng = rng_for(w.seed, w.month, "leaks-v2")
    base = float(tuning.get(w, "leaks.base"))
    press = tuning.get(w, "leaks.press").get(w.const.press, 1.0)
    admin = 1 + (1 - w.econ.admin_capacity)
    cap = int(tuning.get(w, "leaks.max_per_month"))
    candidates = []
    # Each leak records the chance it had and what made it: the record only said that it happened.
    common = {"base": base, "press": press, "admin": round(admin, 4)}
    for dm in dms:
        leaker = w.member(dm["to"]) if dm["to"] in {m.id for m in w.members} else None
        if leaker is None:
            continue
        person = _person_factor(w, leaker.id, dm["from"])
        kind = 1.3 if dm.get("kind") == "confidential" else 1.0
        p = base * press * admin * person * kind
        candidates.append((p, {"kind": "dm", "item": dm, "suspect": leaker.id},
                           {**common, "person": round(person, 4), "kind": kind}))
    for dm in intercepts:
        interior = w.holder("interior")
        person = _person_factor(w, interior.id, dm["from"]) if interior else 1
        p = base * press * admin * 1.4 * person
        candidates.append((p, {"kind": "intercept", "item": dm, "suspect": interior.id if interior else None},
                           {**common, "person": round(person, 4), "kind": 1.4}))
    for item in s["withheld"]:
        if item["month"] == w.month and not item["revealed"]:
            p = base * press * admin * 1.6
            candidates.append((p, {"kind": "withheld_report", "item": item, "suspect": None}, {**common, "kind": 1.6}))
    out = []
    for p, cand, factors in candidates:
        if len(out) >= cap:
            break
        if rng.random() < clamp(p, 0, .5):
            record = {"month": w.month, "kind": cand["kind"], "suspect": cand["suspect"], **_leak_payload(w, cand),
                      "probability": round(clamp(p, 0, .5), 4), "factors": factors}
            s["leaks"].append(record)
            out.append(record)
            if cand["kind"] == "withheld_report":
                cand["item"]["revealed"] = True
    s["leaks"] = [x for x in s["leaks"] if w.month - x["month"] <= 12]
    return out


def _person_factor(w: World, leaker: str, sender: str) -> float:
    member = w.member(leaker)
    t = (member.agent_state or {}).get("traits", {})
    stress = (member.agent_state or {}).get("stress", {}).get("general", 20)
    rel = member.relationships.get(sender, {})
    factor = (1 + float(tuning.get(w, "leaks.stress_weight")) * stress / 100)
    factor *= 1.2 - t.get("institutional_loyalty", 50) / 125
    factor *= .7 + t.get("corruption_tolerance", 50) / 100 * .6 + t.get("opportunism", 50) / 100 * .4
    if rel.get("rivalry", 0) > 45 or rel.get("trust", 50) < 35:
        factor *= float(tuning.get(w, "leaks.rival_multiplier"))
    return factor


def _leak_payload(w: World, cand: dict) -> dict:
    item = cand["item"]
    if cand["kind"] in ("dm", "intercept"):
        text = str(item.get("text", ""))
        fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
        message_id = item.get("message_id") or f"DM{w.month + 1}-{item['from']}{item['to']}-{fingerprint}"
        return {"message_id": message_id, "from": item["from"], "to": item["to"], "text": text,
                "headline": f"A private message from {w.member(item['from']).name} to {w.member(item['to']).name} was published"}
    holder = item["holder"]
    return {"from": holder, "report_id": item["report_id"], "text": item["text"],
            "headline": f"Press obtained a {item['subject'].replace('_', ' ')} report that {w.member(holder).name}'s office had not shared with the council"}
