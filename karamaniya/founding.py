"""Seeded inherited conditions, public state and independent first diagnoses."""
from __future__ import annotations

import copy
import random

from .world import clamp, rng_for


# Each template has a measurable state effect, competing explanations, and trade-offs.
TEMPLATES = {
    "fiscal_arrears": {"category": "fiscal", "title": "Inherited payment arrears", "regions": ["aster", "kessel"],
        "institutions": ["treasury", "public services", "army procurement"], "constituencies": ["public workers", "suppliers", "soldiers"],
        "description": "The provisional government inherited unpaid public bills. Service contracts are overdue while debt service remains due; military pay is current for now.",
        "cause": "The arrears reflect both weak collection and liabilities hidden during the transition.", "causes": ["tax collection weakened during the transfer", "the previous administration concealed liabilities", "spending commitments exceed recurring revenue"],
        "effects": ["unpaid bills slow public services and supplier deliveries"], "tradeoffs": ["tax increases can slow hiring and investment", "cuts shift costs onto welfare, defence or public services", "borrowing adds external dependence", "money creation risks inflation"], "risks": ["suppliers may stop deliveries", "arrears can spread into wages and procurement"], "target": "arrears"},
    "food_dependence": {"category": "food / trade", "title": "Fragile grain dependence", "regions": ["aster", "kessel", "lissen"],
        "institutions": ["agriculture ministry", "customs", "grain reserve"], "constituencies": ["farmers", "urban households", "importers"],
        "description": "Domestic harvests cover only part of normal demand. Imports and inherited reserves keep prices steady, but supply relies on a small number of routes.",
        "cause": "The shortfall combines uneven farm investment with inherited import contracts and limited storage.", "causes": ["low farm investment", "weak rural credit", "losses in storage and transport", "import contracts crowded out local supply"],
        "effects": ["grain imports and reserve drawdown buffer consumers"], "tradeoffs": ["farm support costs money and may raise urban prices", "larger imports deepen route dependence", "rationing protects stocks but constrains choice", "reserves require scarce foreign exchange"], "risks": ["harvest shocks can raise food prices", "trade pressure can reach household supply"], "target": "food"},
    "regional_legitimacy": {"category": "regional / constitutional", "title": "Kessel legitimacy gap", "regions": ["kessel"],
        "institutions": ["interior ministry", "regional administration", "provisional council"], "constituencies": ["Imperial community", "Kessel workers", "regional governors"],
        "description": "Approval in Kessel trails the national level. Peaceful demonstrations are reported, and residents remain uncertain whether the Union separation is permanent.",
        "cause": "Economic frustration, identity concerns and constitutional uncertainty all contribute; their shares are disputed.", "causes": ["economic frustration and unemployment", "fear of permanent separation", "uneven treatment by police", "external encouragement of some organizers"],
        "effects": ["local trust is lower and grievances are elevated"], "tradeoffs": ["autonomy can reassure residents but weaken central control", "police restraint can preserve trust but leave disruption unmanaged", "rapid spending helps jobs but tightens the treasury"], "risks": ["unaddressed grievances can reduce cooperation", "heavy policing can turn peaceful protests into lasting distrust"], "target": "regional"},
    "army_readiness": {"category": "military / institutional", "title": "Uneven army readiness", "regions": ["kessel", "dorran"],
        "institutions": ["army command", "defence procurement"], "constituencies": ["border communities", "officers", "taxpayers"],
        "description": "The army is intact, but equipment and officer confidence vary between units. Immediate readiness is below nominal strength.",
        "cause": "Deferred procurement and divided loyalties after separation left readiness uneven.", "causes": ["deferred ammunition and maintenance contracts", "officer loyalties remain divided", "training cycles were interrupted", "budget limits conceal a smaller ready force"],
        "effects": ["equipment, morale and loyalty begin below full readiness"], "tradeoffs": ["readiness spending competes with civilian services", "purges can remove disloyal officers but disrupt command", "mobilization deters pressure while risking escalation"], "risks": ["border mobilization may expose readiness gaps", "politicized promotions can divide the officer corps further"], "target": "army"},
    "police_trust": {"category": "police / social", "title": "Low confidence in inherited police", "regions": ["kessel", "highlands"],
        "institutions": ["police", "courts", "interior ministry"], "constituencies": ["minority communities", "shopkeepers", "police officers"],
        "description": "Police remain operational, but minority communities report uneven treatment and senior officers seek broader emergency powers.",
        "cause": "Inherited command practices and weak oversight have damaged trust; the scale of deliberate bias is uncertain.", "causes": ["old-regime command structures", "uneven local staffing", "limited complaint review", "political pressure on policing"],
        "effects": ["police morale and public trust start below their normal range"], "tradeoffs": ["oversight can improve trust but slow investigations", "emergency powers may improve short-term control while deepening grievances", "replacing commanders risks experience and continuity"], "risks": ["low trust reduces cooperation", "abusive responses can make local incidents harder to contain"], "target": "police"},
    "rail_bottleneck": {"category": "infrastructure / trade", "title": "Kessel rail corridor bottleneck", "regions": ["kessel", "aster", "dorran"],
        "institutions": ["rail authority", "grain logistics", "energy distributors"], "constituencies": ["port workers", "farmers", "manufacturers"],
        "description": "A large share of north-south freight passes through the Kessel corridor. The route is efficient in normal conditions but has little spare capacity.",
        "cause": "Maintenance was deferred and alternate routes never received full investment.", "causes": ["deferred track maintenance", "single-corridor planning", "limited repair crews", "freight demand grew faster than capacity"],
        "effects": ["regional logistics limit the flow of goods under disruption"], "tradeoffs": ["repairs divert funds from other services", "a second route is expensive and slow to build", "security controls protect freight but can disrupt civilian travel"], "risks": ["strikes or damage can delay food and fuel deliveries", "bottlenecks amplify disruptions elsewhere"], "target": "rail"},
    "monetary_dependence": {"category": "monetary / foreign", "title": "Inherited crown arrangement", "regions": ["aster", "lissen"],
        "institutions": ["central bank", "customs", "commercial banks"], "constituencies": ["importers", "savers", "exporters"],
        "description": "Karamaniya continues to use the shared crown. It supports familiar prices and trade, while monetary decisions remain outside the provisional government's control.",
        "cause": "The inherited currency agreement was kept during the transition to prevent payment disruption.", "causes": ["fear of a bank run during separation", "businesses depend on regional settlement", "no independent central-bank framework was ready"],
        "effects": ["the government cannot set an independent monetary path"], "tradeoffs": ["continuity preserves confidence but limits policy control", "a new currency restores control but risks flight and inflation", "capital controls can buy time while restricting trade"], "risks": ["external monetary changes pass through domestic prices", "a rushed exit can damage savings and contracts"], "target": "currency"},
    "energy_imports": {"category": "energy / foreign", "title": "Fuel supply exposure", "regions": ["kessel", "dorran", "aster"],
        "institutions": ["energy ministry", "rail authority", "industry"], "constituencies": ["manufacturers", "rail workers", "households"],
        "description": "Industry relies on imported fuel alongside domestic coal. Inventories provide a short buffer, but suppliers are politically concentrated.",
        "cause": "Domestic extraction and storage expansion lagged behind industrial demand.", "causes": ["underinvestment in mines", "concentrated import contracts", "limited reserve storage", "rapid industrial demand"],
        "effects": ["the share of imported energy the country can secure is constrained"], "tradeoffs": ["new mines require time and capital", "larger imports deepen dependence", "conservation reduces output", "reserves tie up foreign exchange"], "risks": ["supplier pressure can reduce industrial output", "fuel shortages can interrupt freight and services"], "target": "energy"},
    "bureaucratic_overload": {"category": "institutional / bureaucratic", "title": "Thin transition administration", "regions": ["aster", "kessel", "highlands"],
        "institutions": ["civil service", "tax authority", "regional offices"], "constituencies": ["public workers", "local businesses", "regional governors"],
        "description": "The new administration retained working offices, but vacancies and duplicate approval chains slow implementation outside the capital.",
        "cause": "Staff departures and overlapping transition rules reduced effective administrative capacity.", "causes": ["civil servants left during separation", "duplicate approval rules", "weak records and tax rolls", "regional offices lack trained staff"],
        "effects": ["implementation and compliance begin below normal capacity"], "tradeoffs": ["fast centralization improves coordination but weakens local ownership", "hiring costs money and takes time", "simplifying rules creates winners and losers"], "risks": ["overloaded ministries delay otherwise funded programs", "poor records reduce revenue and service quality"], "target": "bureaucracy"},
    "constitutional_uncertainty": {"category": "constitutional / political", "title": "Unsettled rules of the provisional government", "regions": ["aster", "kessel", "highlands", "dorran", "lissen"],
        "institutions": ["provisional council", "courts", "regional governors"], "constituencies": ["voters", "civil servants", "regional leaders"],
        "description": "The provisional charter leaves several powers and the permanent balance between regions unsettled ahead of the first national election.",
        "cause": "The transition charter prioritized continuity and deferred contentious questions.", "causes": ["parties postponed a settlement to avoid a split", "regional leaders were not represented equally", "courts lack authority over emergency decisions"],
        "effects": ["institutions face uncertainty over powers and future representation"], "tradeoffs": ["early settlement consumes scarce agenda time", "central authority improves speed but can alienate regions", "election timing trades preparation against legitimacy"], "risks": ["delays can undermine confidence in the transition", "rushed rules may entrench an unstable bargain"], "target": "constitution"},
}

SCENARIOS = {
    "fragile-independence": ["monetary_dependence", "food_dependence", "bureaucratic_overload", "regional_legitimacy"],
    "fiscal-inheritance": ["fiscal_arrears", "bureaucratic_overload", "army_readiness", "food_dependence"],
    "regional-divide": ["regional_legitimacy", "police_trust", "constitutional_uncertainty", "rail_bottleneck"],
    "security-crisis": ["army_readiness", "police_trust", "energy_imports", "constitutional_uncertainty"],
    "trade-dependency": ["food_dependence", "energy_imports", "rail_bottleneck", "monetary_dependence"],
    "post-regime-transition": ["police_trust", "bureaucratic_overload", "constitutional_uncertainty", "fiscal_arrears"],
}

STRENGTHS = [
    ("working_ports", "Functioning ports keep regional and League trade possible."),
    ("educated_workforce", "Urban schools and technical colleges provide a skilled workforce."),
    ("gold_buffer", "A modest gold reserve gives the government some room to absorb external shocks."),
    ("farm_potential", "Lissen and Dorran retain productive farmland that could expand output."),
    ("professional_navy", "A small but professional navy can protect coastal trade in normal conditions."),
    ("civil_service_core", "A capable civil-service core remains in the capital and can anchor reform."),
]

DOSSIERS = {
    "payments-and-harvest": "Supplier invoices may exceed published arrears. Grain reserve estimates rely on old storage records; both need an independent audit.",
    "regional-and-trade": "Most reported Kessel gatherings have been peaceful. Traders also report uneven access to cross-border routes; organizers' motives remain mixed.",
    "transport-and-services": "Rail maintenance was deferred during the transition. Payroll delays could reduce repair capacity and public service delivery.",
    "border-and-civilian-trust": "Two northern units report uneven readiness. Local observers also question police treatment of minority communities; neither report establishes intent.",
    "shipping-and-cables": "Insurers have raised quotes on one grain route. Veleria has signaled talks remain possible but has offered no terms; other routes remain open.",
}


def _problem(pid, severity, rng):
    t = TEMPLATES[pid]
    d = copy.deepcopy(t)
    d.update(id=pid, severity=severity, initial_severity=severity, trend="stable",
             hidden_cause=t["cause"], affected_regions=t["regions"], affected_institutions=t["institutions"],
             affected_constituencies=t["constituencies"], public_description=t["description"],
             visible_effects=t["effects"], hidden_effects=[], possible_causes=t["causes"],
             policy_tradeoffs=t["tradeoffs"], escalation_risks=t["risks"], resolution_progress=0.0,
             neglect_months=0, current_indicator=None, previous_indicator=None)
    d.pop("description", None); d.pop("cause", None); d.pop("regions", None); d.pop("institutions", None); d.pop("constituencies", None); d.pop("effects", None); d.pop("causes", None); d.pop("tradeoffs", None); d.pop("risks", None); d.pop("target", None)
    # Seeded hidden causal weights describe the underlying state without dictating a solution.
    weights = [rng.uniform(.2, .65) for _ in d["possible_causes"]]
    total = sum(weights) or 1.0
    d["hidden_cause_decomposition"] = {cause: round(weight / total, 3)
                                       for cause, weight in zip(d["possible_causes"], weights)}
    leading = max(d["hidden_cause_decomposition"], key=d["hidden_cause_decomposition"].get)
    d["hidden_cause"] = f"The strongest underlying driver is {leading}; other listed causes also contribute."
    return d


def _apply(w, pid, severity, rng, mix=None):
    s = severity / 100
    mix = mix or {}
    weights = list(mix.values())
    first = lambda i: weights[i] if i < len(weights) else .25
    if pid == "fiscal_arrears":
        weak_collection, hidden_liabilities, overspending = first(0), first(1), first(2)
        w.econ.arrears += w.econ.gdp_real * (.035 + .10 * hidden_liabilities + .05 * overspending) * s
        w.econ.compliance -= .05 * s * weak_collection
        w.econ.gold *= 1 - .12 * s
        w.econ.confidence -= .04 * s + .04 * s * hidden_liabilities
    elif pid == "food_dependence":
        farm_investment, rural_credit, storage, import_contracts = (first(i) for i in range(4))
        w.econ.food_import_capacity = clamp(.94 - .25 * s * import_contracts, .65, 1)
        w.econ.farm_incentive = clamp(1 - .10 * s * farm_investment)
        w.econ.food_stock *= 1 - .30 * s * storage
        w.econ.state_grain *= 1 - .23 * s * storage
        for p in w.pops:
            if p.cls == "farmers": p.savings *= 1 - .08 * s * rural_credit
    elif pid == "regional_legitimacy":
        for p in w.pops:
            if p.region == "kessel":
                economic, identity, policing = first(0), first(1), first(2)
                p.approval -= .055 * s + .035 * s * identity
                p.grievance += .045 * s + .10 * s * identity + .04 * s * policing
                p.unrest += .035 * s + .055 * s * economic
                if p.cls == "workers": p.unemployment += .03 * s * economic
    elif pid == "army_readiness":
        procurement, divided, training = first(0), first(1), first(2)
        w.mil.army.equipment -= (.08 + .14 * procurement) * s
        w.mil.army.training -= .10 * s * training
        w.mil.army.morale -= .07 * s + .04 * s * training
        w.mil.army.loyalty -= .06 * s + .11 * s * divided
    elif pid == "police_trust":
        legacy, uneven_staffing, weak_oversight, political_pressure = (first(i) for i in range(4))
        w.mil.police.morale -= (.035 + .07 * weak_oversight + .03 * political_pressure) * s
        w.mil.police.loyalty -= (.035 + .06 * legacy + .05 * political_pressure) * s
        for p in w.pops:
            if p.ident in ("imperial", "vell"):
                p.grievance += .015 * s + .045 * s * (legacy + weak_oversight)
    elif pid == "rail_bottleneck":
        deferred_maintenance, single_route, limited_crews, demand = (first(i) for i in range(4))
        throughput = clamp(.97 - s * (.08 + .10 * deferred_maintenance + .06 * demand), .70, .97)
        for rid in ("kessel", "aster", "dorran"):
            w.region(rid).logistics = throughput
    elif pid == "monetary_dependence":
        w.econ.currency = "crown"; w.econ.confidence -= .025 * s
    elif pid == "energy_imports":
        underinvestment, supplier_concentration = first(0), first(1)
        w.econ.energy_import_capacity = clamp(.94 - .35 * s * supplier_concentration, .55, 1)
        w.econ.mining = max(0, w.econ.mining - .10 * s * underinvestment)
    elif pid == "bureaucratic_overload":
        departures, duplicate_rules, poor_records, weak_regions = (first(i) for i in range(4))
        w.econ.admin_capacity -= (.07 + .19 * s) * (departures + duplicate_rules) / 2
        w.econ.compliance -= (.025 + .07 * s) * poor_records
        for p in w.pops:
            if p.region in ("kessel", "highlands", "dorran"):
                p.approval -= .012 * s * weak_regions
    elif pid == "constitutional_uncertainty":
        w.const.election_month = min(w.const.election_month, 17)
        representation, party_bargaining, courts = (first(i) for i in range(3))
        for p in w.pops:
            p.approval -= .014 * s + .02 * s * representation
            p.grievance += .012 * s + .018 * s * (party_bargaining + courts) / 2


def initialize(w, scenario="random", severity="default", custom_problems=None):
    """Generate a reproducible imperfect, governable inherited state."""
    rng = rng_for(w.seed, 0, "founding-state")
    ids = list(TEMPLATES)
    if scenario == "custom":
        chosen = list(dict.fromkeys(p for p in (custom_problems or []) if p in TEMPLATES))
        if len(chosen) < 3:
            raise ValueError("a custom founding state needs at least 3 valid problem ids")
        if len(chosen) > 7:
            raise ValueError("a custom founding state can contain at most 7 problems")
    elif scenario in SCENARIOS:
        chosen = SCENARIOS[scenario][:]
    else:
        rng.shuffle(ids)
        chosen = ids[:rng.randint(4, 6)]
    # Keep all normal starts across at least two policy domains.
    buckets = {TEMPLATES[p]["category"].split(" / ")[0] for p in chosen}
    if len(buckets) < 2:
        chosen += [p for p in ids if TEMPLATES[p]["category"].split(" / ")[0] not in buckets][:1]
    base = {"default": (48, 68), "mild": (37, 55), "serious": (60, 76), "critical": (76, 88)}.get(severity, (48, 68))
    values = [rng.randint(*base) for _ in chosen]
    if severity == "default" and values:
        values[0] = rng.randint(60, 70)
        values[1:] = [rng.randint(42, 58) for _ in values[1:]]
    problems = [_problem(pid, val, rng) for pid, val in zip(chosen, values)]
    for p in problems:
        _apply(w, p["id"], p["severity"], rng, p.get("hidden_cause_decomposition"))
    strengths = [{"id": key, "description": desc} for key, desc in rng.sample(STRENGTHS, 3)]
    for strength in strengths:
        if strength["id"] == "working_ports":
            w.region("aster").logistics += .035; w.region("lissen").logistics += .035
        elif strength["id"] == "educated_workforce":
            w.econ.admin_capacity += .035; w.econ.compliance += .015
        elif strength["id"] == "gold_buffer":
            w.econ.gold += 8e6
        elif strength["id"] == "farm_potential":
            for rid in ("lissen", "dorran"): w.region(rid).land += .05
        elif strength["id"] == "professional_navy":
            w.mil.navy.training += .04; w.mil.navy.morale += .04
        elif strength["id"] == "civil_service_core":
            w.econ.admin_capacity += .06; w.econ.compliance += .015
    prng = rng_for(w.seed, 0, "founding-dossiers")
    # Seeded information slices. Dossiers do not assign or suggest an office.
    member_ids = [m.id for m in w.members]; prng.shuffle(member_ids)
    labels = list(DOSSIERS)
    dossiers = {mid: labels[i % len(labels)] for i, mid in enumerate(member_ids)}
    # Existing policy is explicit and inherited, rather than a blank policy slate.
    w.policy.tax = .18
    w.policy.farm_support = .01 if hasattr(w.policy, "farm_support") else getattr(w.policy, "farm_support", 0.0)
    w.founding = {"version": 1, "scenario": scenario, "severity_mode": severity,
        "problems": problems, "strengths": strengths, "dossiers": dossiers, "diagnoses": {},
        "agenda_slots": rng.randint(2, 4), "public_history": [
            "Six months before independence, the transition government deferred maintenance and disputed the final accounts.",
            "Three months before independence, trade and personnel arrangements were extended temporarily to avoid an abrupt break.",
            "At independence, the provisional council inherited the contracts, currency arrangement and regional grievances."],
        "commitments": ["Shared-crown settlement continues pending a monetary decision.",
                        "Existing public contracts and military pensions remain due.",
                        "A temporary grain-import arrangement stays in force through the first harvest."],
        "inherited_policies": {"tax_rate": .18, "currency": w.econ.currency, "protest_response": w.policy.protest_response,
                               "farm_support": getattr(w.policy, "farm_support", 0), "election_month": w.const.election_month},
        "last_advance_month": -1}
    for p in problems:
        metric = _indicator(w, p["id"])
        p["initial_indicator"] = round(metric, 3)
        p["current_indicator"] = round(metric, 3)
    w.event("founding_state", "The provisional government takes office with inherited obligations and uneven institutions.", importance=3)
    return w.founding


def dossier(w, mid):
    name = (w.founding.get("dossiers", {}).get(mid) if getattr(w, "founding", None) else None)
    if name in DOSSIERS:
        return name, DOSSIERS[name]
    # Old saved runs can still be inspected without making their former labels a new assignment.
    return "transition-records", "Transition records are incomplete; compare claims against the public state."


def portfolio(w, mid):
    """Compatibility for callers that used the old accessor name."""
    return dossier(w, mid)


def public_profile(w):
    f = getattr(w, "founding", {}) or {}
    return {"version": f.get("version", 0), "scenario": f.get("scenario", "legacy"),
        "severity_mode": f.get("severity_mode", "default"), "problems": [
            {k: copy.deepcopy(v) for k, v in p.items() if k not in ("hidden_cause", "hidden_effects", "truth_weights", "hidden_cause_decomposition")}
            for p in f.get("problems", [])], "strengths": copy.deepcopy(f.get("strengths", [])),
        "public_history": list(f.get("public_history", [])), "commitments": list(f.get("commitments", [])),
        "inherited_policies": copy.deepcopy(f.get("inherited_policies", {})), "agenda_slots": f.get("agenda_slots", 3),
        "diagnoses": copy.deepcopy(f.get("diagnoses", {})),
        "formation": copy.deepcopy(f.get("formation", {}))}


def _indicator(w, pid):
    if pid == "fiscal_arrears": return clamp(w.econ.arrears / max(1, w.econ.gdp_real * .25))
    if pid == "food_dependence": return clamp((1 - w.econ.food_ratio) * .55 + (1 - w.econ.food_import_capacity) * .45)
    if pid == "regional_legitimacy": return clamp(w.avg("grievance", [x for x in w.k_pops() if x.region == "kessel"]))
    if pid == "army_readiness": return clamp(1 - (w.mil.army.equipment * .35 + w.mil.army.morale * .30 + w.mil.army.loyalty * .35))
    if pid == "police_trust": return clamp(1 - (w.mil.police.morale + w.mil.police.loyalty) / 2)
    if pid == "rail_bottleneck": return 1 - w.region("kessel").logistics
    if pid == "monetary_dependence": return .65 if w.econ.currency == "crown" else clamp(1 - w.econ.confidence)
    if pid == "energy_imports": return 1 - w.econ.energy_import_capacity
    if pid == "bureaucratic_overload": return clamp(1 - w.econ.admin_capacity)
    return .55 if w.const.provisional else .20


def advance(w):
    """Update problem trajectories from actual simulated indicators, without scripted punishments."""
    f = getattr(w, "founding", {}) or {}
    if not f or f.get("last_advance_month") == w.month: return
    for p in f.get("problems", []):
        pid, old = p["id"], p.get("severity", 50)
        metric = _indicator(w, pid)
        baseline = p.get("initial_indicator", metric)
        severity = int(round(p["initial_severity"] + 90 * (metric - baseline)))
        severity = max(10, min(95, severity))
        delta = severity - old
        p["previous_indicator"] = p.get("current_indicator")
        p["current_indicator"] = round(metric, 3)
        p["severity"] = max(10, min(95, severity))
        p["trend"] = "improving" if delta <= -3 else "worsening" if delta >= 3 else "stable"
        p["resolution_progress"] = round(clamp((p["initial_severity"] - p["severity"]) / max(1, p["initial_severity"])), 3)
        if p["trend"] == "worsening": p["neglect_months"] = p.get("neglect_months", 0) + 1
        elif p["trend"] == "improving": p["neglect_months"] = max(0, p.get("neglect_months", 0) - 1)
        elif p["severity"] >= 48: p["neglect_months"] = p.get("neglect_months", 0) + 1
    f["last_advance_month"] = w.month


def problem_for_region(w, rid):
    return [{"id": p["id"], "title": p["title"], "severity": p["severity"], "trend": p["trend"]}
            for p in (getattr(w, "founding", {}) or {}).get("problems", []) if rid in p.get("affected_regions", [])]


def divergence(w):
    profile = w.get("founding", {}) if isinstance(w, dict) else getattr(w, "founding", {})
    diagnoses = [d for d in (profile or {}).get("diagnoses", {}).values()
                 if d.get("status", "submitted") == "submitted"]
    tops = [d.get("main_problem") for d in diagnoses if d.get("main_problem")]
    if len(tops) < 2: return {"top_problem_disagreement": 0.0, "distinct_main_problems": len(set(tops)), "diagnoses": len(tops)}
    return {"top_problem_disagreement": round(1 - max(tops.count(x) for x in set(tops)) / len(tops), 3),
            "distinct_main_problems": len(set(tops)), "diagnoses": len(tops)}


REQUIRED_DIAGNOSIS_FIELDS = ("main_problem", "cause_assessment", "preferred_first_policy",
    "policy_to_avoid", "biggest_risk", "information_needed", "what_other_offices_may_be_underestimating")


def validate_diagnosis(data, issue_ids):
    """Reject incomplete answers before they can appear as submitted diagnoses."""
    if not isinstance(data, dict):
        return ["answer is not a JSON object"]
    missing = diagnosis_repair_fields(data, issue_ids)
    return ["missing or invalid: " + ", ".join(missing)] if missing else []


def diagnosis_repair_fields(data, issue_ids):
    """Names of fields that a targeted repair response must supply."""
    if not isinstance(data, dict):
        return list(REQUIRED_DIAGNOSIS_FIELDS) + ["second_problem", "ranked_problems"]
    missing = [key for key in REQUIRED_DIAGNOSIS_FIELDS
               if not isinstance(data.get(key), str) or not data[key].strip()]
    if isinstance(data.get("main_problem"), str) and data["main_problem"] not in issue_ids:
        missing.append("main_problem")
    if not isinstance(data.get("second_problem"), str) or data["second_problem"] not in issue_ids | {"none"}:
        missing.append("second_problem")
    ranked = data.get("ranked_problems")
    if not isinstance(ranked, list) or not ranked or any(not isinstance(x, str) or x not in issue_ids for x in ranked):
        missing.append("ranked_problems")
    return list(dict.fromkeys(missing))


def diagnosis_schema(w):
    ids = [p["id"] for p in (getattr(w, "founding", {}) or {}).get("problems", [])]
    answer = {"type": "string"}
    return {"type": "object", "properties": {
        "main_problem": {"type": "string", "enum": ids},
        "second_problem": {"type": "string", "enum": ids + ["none"]},
        "cause_assessment": answer, "preferred_first_policy": answer,
        "policy_to_avoid": answer, "biggest_risk": answer,
        "information_needed": answer, "what_other_offices_may_be_underestimating": answer,
        "ranked_problems": {"type": "array", "items": {"type": "string", "enum": ids}, "minItems": 1, "maxItems": len(ids)},
    }, "required": ["main_problem", "second_problem", "cause_assessment", "preferred_first_policy",
        "policy_to_avoid", "biggest_risk", "information_needed", "what_other_offices_may_be_underestimating",
        "ranked_problems"],
        "additionalProperties": False}


def diagnosis_prompt(w, mid):
    from . import decision_context
    label, note = dossier(w, mid)
    profile = public_profile(w)
    issues = []
    for p in profile["problems"]:
        issues.append({k: p.get(k) for k in ("id", "category", "title", "public_description", "severity", "affected_regions", "affected_institutions", "affected_constituencies", "visible_effects", "possible_causes", "policy_tradeoffs", "escalation_risks")})
    strengths = profile["strengths"]
    return ("FOUNDING DIAGNOSIS — BEFORE THE FIRST COUNCIL SESSION\n"
        "You have just taken part in a provisional handover. This is a private evidence dossier, "
        "not an assigned office or command. Assess the same imperfect country independently. Other delegates' "
        "diagnoses and statements are not available to you. Do not try to disagree or seek consensus; use your "
        "own beliefs, personality, priorities, evidence and uncertainty. No issue has a designated correct policy.\n\n"
        + decision_context.for_member(w, mid, "independent founding diagnosis") + "\n\n"
        + f"PUBLIC INHERITED STATE (known to all):\n{__import__('json').dumps({'problems': issues, 'strengths': strengths, 'commitments': profile['commitments'], 'inherited_policies': profile['inherited_policies'], 'agenda_slots': profile['agenda_slots']}, ensure_ascii=False, indent=2)}\n\n"
        + f"YOUR PRIVATE EVIDENCE DOSSIER ({label}): {note}\n\n"
        + "Rank the issues by danger, choose the most dangerous and second-most dangerous, state your causal assessment "
        "as a hypothesis (not certainty), the first policy you favour, one policy to avoid, the greatest risk, and "
        "what information you need to test your assessment, and one thing other delegates may be "
        "underestimating. Actions consume scarce money, time and administrative "
        "capacity. A response can help one group while imposing costs elsewhere. Do not reveal hidden model internals. "
        "Use concise evidence-based reasons. Return only one JSON object. Required keys: main_problem "
        "(one listed issue ID), second_problem (another listed issue ID or 'none'), ranked_problems "
        "(array of listed issue IDs), cause_assessment, preferred_first_policy, policy_to_avoid, "
        "biggest_risk, information_needed, what_other_offices_may_be_underestimating. "
        "Every text field must be nonempty.")
