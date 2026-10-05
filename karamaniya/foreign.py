"""Persistent, imperfectly informed strategic actors outside Karamaniya.

Foreign domestic politics are deliberately aggregate. Veleria and Dorsania make
independent strategic choices before Union consultation; the League uses compact
economic rules for ordinary months. State in this module is serializable JSON data.
"""
from __future__ import annotations

import math

from .world import clamp, rng_for


# ---- red lines, leadership confidence and domestic constituencies -------------------------------
# Three things the actors lacked: conditions they will not accept, a leadership whose standing
# depends on results, and domestic groups with a view on how Karamaniya should be handled. All
# three are engine-side model state. None of it is written into a Karamaniyan prompt: the council
# only ever sees the behaviour that follows.

# What each constituency wants from its own government's policy toward Karamaniya, on one axis:
# +1 maximum firmness, -1 maximum accommodation, 0 for a group with no posture of its own.
# `weight` is the group's weight in that argument, and the weighted groups of an actor sum to 1;
# a group with no preference carries no weight and never generates posture pressure. `support` is
# the group's standing with its government, rewritten every month by _domestic() from the same
# formulas as before this feature existed.
CONSTITUENCIES = {
    "veleria": {
        "industrial_elites": {"preference": -.45, "weight": .36, "support": .62},
        "workers": {"preference": 0.0, "weight": 0.0, "support": .66},
        "army": {"preference": 0.0, "weight": 0.0, "support": .68},
        "nationalists": {"preference": .85, "weight": .38, "support": .77},
        "commercial_sector": {"preference": -.65, "weight": .26, "support": .65},
        "bureaucracy": {"preference": 0.0, "weight": 0.0, "support": .64},
    },
    "dorsania": {
        "farmers": {"preference": 0.0, "weight": 0.0, "support": .70},
        "grain_exporters": {"preference": -.80, "weight": .40, "support": .74},
        "army": {"preference": .45, "weight": .26, "support": .61},
        "regional_elites": {"preference": 0.0, "weight": 0.0, "support": .61},
        "merchants": {"preference": -.60, "weight": .34, "support": .65},
        "union_supporters": {"preference": 0.0, "weight": 0.0, "support": .61},
        "union_skeptics": {"preference": 0.0, "weight": 0.0, "support": .43},
    },
}

# Cabinet actions that count as visible economic pressure on Karamaniya.
COERCIVE_ACTIONS = ("partial_embargo", "grain_embargo", "ultimatum")


def _bilateral_trade_open(w) -> bool:
    """Karamaniya and Dorsania are inside the grain agreement the economy already counts."""
    return bool(w.counters.get("dorsania_trade", 0)) and w.month <= w.counters.get("dorsania_trade_until", -1)


def _measure_league_alignment(w) -> float:
    """Karamaniya has taken the League's military weight: a formal alliance or equipment deliveries."""
    if w.dip.league_alliance:
        return 1.0
    return .6 if w.dip.league_aid > 0 else 0.0


def _measure_league_escorts(w) -> float:
    """League warships are escorting convoys in waters the actor treats as its own."""
    return 1.0 if w.dip.league_escort else 0.0


def _measure_bilateral_trade(w) -> float:
    """Karamaniya has settled grain trade bilaterally with Dorsania, outside the Union's policy."""
    return 1.0 if _bilateral_trade_open(w) else 0.0


def _measure_blockade(w) -> float:
    """The sea lanes are closed: a blockade is running, weighted by how much of the trade it stops."""
    if not w.dip.blockade:
        return 0.0
    return clamp(.6 + .4 * clamp(w.dip.blockade_eff))


def _measure_karamaniyan_attack(w) -> float:
    """Karamaniya is the aggressor in an open war."""
    return 1.0 if (w.dip.war and w.dip.aggressor == "karamaniya") else 0.0


def _measure_league_default(w) -> float:
    """Karamaniya has suspended service on League credit that is still outstanding."""
    loan = w.foreign.get("league", {}).get("loan", {})
    return 1.0 if (w.policy.debt_service == "suspend" and loan.get("principal", 0.0) > 0) else 0.0


# Each condition is a measurement of state the engine already tracks, on a 0..1 scale, so a red
# line is a claim about something Karamaniya actually did rather than about a label. A line is
# crossed when its condition reaches the line's threshold.
RED_LINE_CONDITIONS = {
    "karamaniya_league_alignment": _measure_league_alignment,
    "league_escorts_in_solvaran_waters": _measure_league_escorts,
    "bilateral_trade_split": _measure_bilateral_trade,
    "blockade_of_shipping": _measure_blockade,
    "karamaniyan_offensive_war": _measure_karamaniyan_attack,
    "default_on_league_debt": _measure_league_default,
}

# Seeded per actor, never drawn at random per month. Severity scales the consequence of a crossing.
RED_LINES = {
    "veleria": (
        {"id": "league_military_ties", "condition": "karamaniya_league_alignment",
         "threshold": .55, "severity": .85},
        {"id": "league_escorts_admitted", "condition": "league_escorts_in_solvaran_waters",
         "threshold": .5, "severity": .55},
        {"id": "bilateral_split_of_the_union", "condition": "bilateral_trade_split",
         "threshold": .5, "severity": .60},
    ),
    "dorsania": (
        {"id": "sea_lanes_closed", "condition": "blockade_of_shipping",
         "threshold": .6, "severity": .70},
        {"id": "karamaniyan_attack_across_the_border", "condition": "karamaniyan_offensive_war",
         "threshold": .5, "severity": .80},
        {"id": "default_on_league_debt", "condition": "default_on_league_debt",
         "threshold": .5, "severity": .45},
    ),
}

# How an actor answers a crossed line, by disposition: (hostility, threat, offensive-intent belief).
# Bounded and deterministic, and no response is a war or an attack: they move perceptions only.
RED_LINE_RESPONSES = {
    "protest": (.05, .05, .05),
    "bluster": (.07, .06, .04),
    "mobilize": (.10, .08, .08),
    "escalate": (.18, .14, .12),
}


def _red_lines(actor_id: str) -> list:
    return [{"id": line["id"], "condition": line["condition"], "threshold": line["threshold"],
             "severity": line["severity"], "crossed_month": -1, "response": ""}
            for line in RED_LINES.get(actor_id, ())]


def _leadership_state(actor_id: str, seed: int) -> dict:
    """A leadership starts with a standing and a tenure it had before the run began."""
    rng = rng_for(seed, 0, "foreign-leadership:" + actor_id)
    return {"confidence": round(rng.uniform(.62, .78), 3), "domestic_pressure": 0.0,
            "months_in_office": 6 + rng.randrange(24)}


def _tenure_opening(actor_id: str, seed: int) -> int:
    """Months the leadership had already served when the run opened, from the same seeded draw."""
    return int(_leadership_state(actor_id, seed)["months_in_office"])


def _support(group, default: float = .6) -> float:
    """One constituency's standing with its government. Tolerates entries saved before this feature."""
    value = group.get("support", default) if isinstance(group, dict) else group
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _set_support(groups: dict, support: dict) -> None:
    """Record this month's standing for each group, creating an entry for a checkpoint that lacks one."""
    for name, value in support.items():
        group = groups.get(name)
        if not isinstance(group, dict):
            group = groups[name] = {"preference": 0.0, "weight": 0.0}
        group["support"] = value


def _red_line_response(disposition: dict) -> str:
    """How an actor answers a crossed line: bold actors escalate, cautious ones protest.

    Reads only the seeded dispositions, so the same actor always answers the same way and a
    crossing cannot become a war by itself.
    """
    if disposition["aggressiveness"] >= .55:
        return "escalate" if disposition["patience"] < .60 else "mobilize"
    if disposition["risk_tolerance"] >= .45:
        return "mobilize"
    return "protest" if disposition["patience"] >= .55 else "bluster"


def _number(value, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _caution(actor: dict) -> float:
    """How far a low-confidence leadership pulls its punches: 1.0 at ordinary confidence, .60 at none.

    This is a modulation of decisions the actor already makes, not a decision of its own.
    """
    leadership = actor.get("leadership")
    confidence = _number(leadership.get("confidence"), .70) if isinstance(leadership, dict) else .70
    return clamp(.60 + .60 * confidence)


def _actor(actor_id: str, seed: int) -> dict:
    rng = rng_for(seed, 0, "foreign-disposition:" + actor_id)
    base = {
        "veleria": {"risk_tolerance": .38, "aggressiveness": .72, "economic_pragmatism": .57,
                    "nationalism": .78, "patience": .48, "diplomatic_flexibility": .42,
                    "threat_sensitivity": .76},
        "dorsania": {"risk_tolerance": .28, "aggressiveness": .32, "economic_pragmatism": .79,
                     "nationalism": .47, "patience": .64, "diplomatic_flexibility": .68,
                     "threat_sensitivity": .48},
    }[actor_id]
    disposition = {k: round(clamp(v + rng.uniform(-.07, .07)), 3) for k, v in base.items()}
    return {
        "id": actor_id,
        "domestic": {"approval": .61 if actor_id == "veleria" else .66,
                     "economic_growth": .015, "inflation": .03, "unemployment": .06,
                     "fiscal_stress": .18, "war_weariness": 0.0},
        "political_pressures": {},
        "constituencies": {name: dict(spec) for name, spec in CONSTITUENCIES[actor_id].items()},
        "strategic_goals": {},
        "disposition": disposition,
        "red_lines": _red_lines(actor_id),
        "leadership": _leadership_state(actor_id, seed),
        "beliefs": {
            "karamaniya_permanent_separation": {"value": .57, "confidence": .28},
            "karamaniya_offensive_intent": {"value": .18, "confidence": .20},
            "league_strategic_influence": {"value": .25, "confidence": .24},
            "dorsania_resists_escalation": {"value": .42, "confidence": .25},
            "economic_pressure_effectiveness": {"value": .52, "confidence": .28},
        },
        "intelligence": [],
        "relations": ({"dorsania": {"trust": .67, "hostility": .12, "dependence": .58,
                                      "trade_importance": .31, "threat_perception": .20},
                       "karamaniya": {"trust": .37, "hostility": .46, "dependence": .09,
                                        "trade_importance": .14, "threat_perception": .48},
                       "league": {"trust": .53, "hostility": .12, "dependence": .12,
                                  "trade_importance": .20, "threat_perception": .22}}
                      if actor_id == "veleria" else
                      {"veleria": {"trust": .59, "hostility": .17, "dependence": .64,
                                    "trade_importance": .28, "threat_perception": .34},
                       "karamaniya": {"trust": .49, "hostility": .26, "dependence": .28,
                                        "trade_importance": .68, "threat_perception": .31},
                       "league": {"trust": .52, "hostility": .10, "dependence": .18,
                                  "trade_importance": .31, "threat_perception": .15}}),
        "threat_perception": {"karamaniya": .48, "league": .22, "dorsania": .20 if actor_id == "veleria" else .34},
        "military": {"active": 65000 if actor_id == "veleria" else 30000,
                     "reserves": 90000 if actor_id == "veleria" else 42000,
                     "readiness": .58 if actor_id == "veleria" else .47,
                     "fortification": .36 if actor_id == "veleria" else .24,
                     "supply": .85, "front_allocations": {"north": 0.0, "east": 0.0}},
        "economy": {"gdp": 13.44e9 if actor_id == "veleria" else 6.60e9,
                    "growth": .015, "inflation": .03, "trade_exposure": .25 if actor_id == "veleria" else .62,
                    "karamaniya_trade_share": .06 if actor_id == "veleria" else .24},
        "diplomacy": {"strategy": "conditional union leadership" if actor_id == "veleria"
                      else "protect trade while preserving Union membership",
                      "strategy_history": [], "last_actions": [], "commitments": []},
        "reputation": {"treaty_reliability": .68, "commercial_reliability": .72,
                       "military_aggressiveness": .35, "financial_credibility": .70,
                       "diplomatic_trust": .52},
        "memory": [],
    }


def initial_state(seed: int) -> dict:
    return {
        "actors": {aid: _actor(aid, seed) for aid in ("veleria", "dorsania")},
        "union": {"cohesion": .73, "military_coordination": .62, "economic_integration": .71,
                  "political_trust": .62, "shared_threat_perception": .49, "history": [],
                  "policy_disagreement": 0.0},
        "league": {"commercial_interest": .71, "financial_exposure": .12,
                   "risk_tolerance": .40, "trust_in_karamaniya": .55,
                   "fear_of_union_expansion": .34, "shipping_security_concern": .18,
                   "political_tolerance": .56, "loan": {"principal": 0.0, "interest": .05,
                   "maturity_month": -1, "conditions": {}, "default_risk": .16},
                   "shipping": {"insurance_cost": .025, "routes_open": True, "escorts": 0},
                   "strategy": "support commercial stability without a formal defense commitment",
                   "history": []},
        "embargoes": {},
        "government_intelligence": [],
        "escalation_chains": [],
        "decision_log": [],
    }


def _ensure_actor_shape(actor: dict, actor_id: str, seed: int) -> None:
    """Add anything a checkpoint saved before red lines, leadership and groups existed is missing.

    Old state is upgraded in place rather than re-derived, so a resumed run keeps the standing its
    constituencies already had. Nothing here raises on a partial or old actor.
    """
    leadership = actor.get("leadership")
    if not isinstance(leadership, dict):
        leadership = actor["leadership"] = _leadership_state(actor_id, seed)
    else:
        opening = _leadership_state(actor_id, seed)
        for key, value in opening.items():
            leadership.setdefault(key, value)
    red_lines = actor.get("red_lines")
    if not isinstance(red_lines, list) or not red_lines:
        actor["red_lines"] = _red_lines(actor_id)
    groups = actor.get("constituencies")
    if not isinstance(groups, dict):
        groups = actor["constituencies"] = {}
    for name, spec in CONSTITUENCIES.get(actor_id, {}).items():
        group = groups.get(name)
        if isinstance(group, dict):
            group.setdefault("preference", spec["preference"])
            group.setdefault("weight", spec["weight"])
            group.setdefault("support", spec["support"])
        else:
            groups[name] = {"preference": spec["preference"], "weight": spec["weight"],
                            "support": _support(group, spec["support"])}
    # A group an older checkpoint tracked but this version does not know keeps its standing and
    # carries no posture of its own, rather than being dropped or crashing the reader.
    for name, group in list(groups.items()):
        if not isinstance(group, dict):
            groups[name] = {"preference": 0.0, "weight": 0.0, "support": _support(group, .6)}


def posture_toward_karamaniya(w, actor_id: str) -> float:
    """Where an actor's actual policy toward Karamaniya sits: -1 accommodation, +1 confrontation.

    Read from instruments the engine already moves — embargoes, a war, an ultimatum, a signed pact,
    settled trade — so a constituency's grievance is a statement about real policy, not a label.
    """
    dip = w.dip
    if actor_id == "veleria":
        confrontation = clamp(.75 * clamp(dip.coal_embargo / .40) + (.25 if dip.war else 0.0)
                              + (.15 if dip.ultimatum else 0.0))
        accommodation = clamp(.35 * (1.0 if dip.nonaggression else 0.0)
                              + .35 * (1.0 if dip.federation else 0.0))
    else:
        confrontation = clamp(.70 * clamp(dip.grain_embargo / .35) + (.30 if dip.war else 0.0))
        accommodation = clamp(.55 * clamp(-dip.grain_embargo / .12)
                              + .30 * (1.0 if _bilateral_trade_open(w) else 0.0))
    return clamp(confrontation - accommodation, -1.0, 1.0)


def _constituency_pressures(w) -> None:
    """Rewrite each weighted constituency's grievance over the actor's current posture.

    A group that is getting the policy it wants carries no grievance; one whose preference is being
    ignored carries pressure proportional to its weight and to how loud domestic politics is.
    """
    for actor_id, actor in w.foreign["actors"].items():
        groups, d = actor["constituencies"], actor["domestic"]
        posture = posture_toward_karamaniya(w, actor_id)
        tension = clamp(.5 * (1 - d["approval"]) + 1.5 * d["inflation"] + .3 * d["war_weariness"])
        for name, group in groups.items():
            key = f"{name}_grievance"
            weight = _number(group.get("weight"), 0.0) if isinstance(group, dict) else 0.0
            if weight <= 0:
                actor["political_pressures"].pop(key, None)
                continue
            preference = _number(group.get("preference"), 0.0)
            ignored = clamp(abs(posture - preference) / 2.0)
            actor["political_pressures"][key] = round(clamp(weight * ignored * (.80 + .40 * tension)), 3)


def _coercing(w, actor_id: str, actor: dict) -> bool:
    """Whether the actor is visibly applying economic pressure on Karamaniya this month."""
    embargo = w.dip.coal_embargo if actor_id == "veleria" else max(0.0, w.dip.grain_embargo)
    recent = any(action.get("type") in COERCIVE_ACTIONS and w.month - action.get("month", -99) <= 2
                 for action in actor["diplomacy"].get("last_actions", []))
    return embargo >= .05 or recent


def _strategy_failure(w, actor_id: str, actor: dict) -> float:
    """How visibly the actor's pressure on Karamaniya is failing, 0..1.

    Only counted while the actor is actually coercing: an actor that is not applying pressure
    cannot be seen to fail at it. The verdict comes from the belief the engine already updates
    from observed outcomes, so a revival of independence support after coercion reads as failure.
    """
    if not _coercing(w, actor_id, actor):
        return 0.0
    effectiveness = _belief(actor, "economic_pressure_effectiveness")["value"]
    return clamp((.48 - effectiveness) / .36)


def _leadership(w) -> None:
    """Move each leadership's confidence toward what its domestic position and results justify.

    Confidence falls faster than it recovers, so a bad year is not undone by one quiet month.
    """
    for actor_id, actor in w.foreign["actors"].items():
        lead, d = actor["leadership"], actor["domestic"]
        grievance = sum(value for key, value in actor["political_pressures"].items()
                        if key.endswith("_grievance"))
        pressure = clamp(.38 * (1 - d["approval"]) + 1.6 * d["inflation"] + .35 * d["war_weariness"]
                         + .55 * d["fiscal_stress"] + .45 * grievance)
        lead["domestic_pressure"] = round(pressure, 3)
        target = clamp(.70 - .55 * pressure - .30 * _strategy_failure(w, actor_id, actor))
        rate = .12 if target < lead["confidence"] else .04
        lead["confidence"] = round(clamp(lead["confidence"] + rate * (target - lead["confidence"])), 3)
        # Tenure follows the calendar, so resolving a month twice does not age a government twice.
        lead["months_in_office"] = _tenure_opening(actor_id, w.seed) + w.month


def red_line_measurements(w, actor_id: str) -> dict:
    """This month's reading for every condition the actor's red lines are written against."""
    return {line["condition"]: float(RED_LINE_CONDITIONS[line["condition"]](w))
            for line in w.foreign["actors"][actor_id].get("red_lines", [])
            if line.get("condition") in RED_LINE_CONDITIONS}


def _cross_red_line(w, actor: dict, line: dict, response: str) -> None:
    """A crossed line: it hardens the actor's view of Karamaniya. It never starts a war or an attack."""
    severity = clamp(_number(line.get("severity"), .5))
    hostilities, threat, belief_move = RED_LINE_RESPONSES.get(response, RED_LINE_RESPONSES["protest"])
    relations = actor["relations"]["karamaniya"]
    relations["hostility"] = round(clamp(relations["hostility"] + hostilities * severity), 3)
    relations["threat_perception"] = round(clamp(relations["threat_perception"] + threat * severity), 3)
    perceived = actor["threat_perception"]
    perceived["karamaniya"] = round(clamp(_number(perceived.get("karamaniya"), relations["threat_perception"])
                                          + threat * severity), 3)
    intent = _belief(actor, "karamaniya_offensive_intent")
    intent["value"] = round(clamp(intent["value"] + belief_move * severity), 3)
    intent["confidence"] = round(clamp(intent["confidence"] + .06 * severity), 3)
    if response == "escalate":
        disposition = actor["disposition"]
        disposition["aggressiveness"] = round(clamp(disposition["aggressiveness"] + .02 * severity), 3)
        disposition["patience"] = round(clamp(disposition["patience"] - .02 * severity), 3)
    _remember(w.foreign, actor["id"], "red_line",
              f"Karamaniya crossed the {line['id'].replace('_', ' ')} line; the government chose to {response}.",
              w.month, red_line=line["id"], severity=severity, response=response)


def evaluate_red_lines(w) -> None:
    """Test every actor's lines against observable state and record the first crossing of each.

    A crossing is one-way: a line that stays breached keeps the month it was first crossed and is
    never re-triggered, so a standing condition cannot ratchet hostility month after month.
    """
    for actor in w.foreign["actors"].values():
        for line in actor.get("red_lines", []):
            if _number(line.get("crossed_month"), -1) >= 0:
                continue
            measure = RED_LINE_CONDITIONS.get(line.get("condition"))
            if measure is None or measure(w) < _number(line.get("threshold"), 1.0):
                continue
            response = _red_line_response(actor["disposition"])
            line["crossed_month"] = w.month
            line["response"] = response
            _cross_red_line(w, actor, line, response)


def _belief(actor: dict, key: str) -> dict:
    return actor["beliefs"].setdefault(key, {"value": .5, "confidence": .1})


def _update_belief(actor: dict, key: str, evidence: float, reliability: float) -> None:
    belief = _belief(actor, key)
    weight = clamp(reliability * (.30 + .45 * belief["confidence"]), .04, .38)
    belief["value"] = round(clamp(belief["value"] * (1 - weight) + evidence * weight), 3)
    belief["confidence"] = round(clamp(belief["confidence"] + .025 * reliability), 3)


def _remember(state: dict, actor_id: str, kind: str, text: str, month: int, **details) -> None:
    entry = {"month": month, "actor": actor_id, "kind": kind, "text": text, **details}
    actor = state["actors"].get(actor_id)
    if actor is not None:
        actor["memory"].append(entry)
        actor["memory"] = actor["memory"][-48:]
    state["decision_log"].append(entry)
    state["decision_log"] = state["decision_log"][-120:]


def _signal_intelligence(w) -> None:
    """Update estimates from public signals only; never copy private Karamaniya state."""
    state = w.foreign
    rng = rng_for(w.seed, w.month, "foreign-intelligence")
    m = w.mil
    # Visible force totals and fort works are evidence, but they do not reveal intent.
    army_signal = clamp((m.army.size - 28000) / 70000 + .18)
    fort_signal = clamp((m.fort.get("north", 0) + m.fort.get("east", 0)) / 1.2)
    mobilization_signal = clamp(.12 + army_signal * .50 + fort_signal * .22
                                + (.28 if w.dip.war and w.dip.aggressor == "karamaniya" else 0.0))
    poll_estimate = clamp(w.avg("indep") + rng.uniform(-.18, .18))
    approval_estimate = clamp(w.avg("approval") + rng.uniform(-.16, .16))
    separation_signal = .16 + .48 * poll_estimate + (.22 if w.econ.currency == "karam" else 0.0)
    separation_signal += .22 if w.dip.nonaggression or w.dip.federation else 0.0
    separation_signal -= .24 if w.dip.union_formed and not w.dip.war else 0.0
    for actor_id, actor in state["actors"].items():
        reliability = .60 + rng.uniform(-.13, .13)
        observed_mobilization = clamp(mobilization_signal + rng.uniform(-.20, .20))
        observed_separation = clamp(separation_signal + rng.uniform(-.16, .16))
        _update_belief(actor, "karamaniya_offensive_intent", observed_mobilization, reliability)
        _update_belief(actor, "karamaniya_permanent_separation", observed_separation, reliability * .75)
        _update_belief(actor, "karamaniya_government_instability",
                       clamp(1-approval_estimate+rng.uniform(-.12,.12)), .48)
        league_signal = .2 + (.34 if w.dip.league_alliance else 0.0) + (.18 if w.dip.league_aid else 0.0)
        _update_belief(actor, "league_strategic_influence", clamp(league_signal + rng.uniform(-.16, .16)), .55)
        if actor_id == "veleria":
            _update_belief(actor, "dorsania_resists_escalation",
                           clamp(.25 + .60 * (1 - state["union"]["cohesion"]) + rng.uniform(-.10, .10)), .55)
        evidence = {"visible_karamaniyan_force_estimate": [round(m.army.size * rng.uniform(.83, 1.17), -2),
                                                            round(m.army.size * rng.uniform(1.12, 1.30), -2)],
                    "visible_fortification": round((m.fort.get("north", 0) + m.fort.get("east", 0)) / 2, 2),
                    "poll_estimates": {"independence_support": round(poll_estimate, 2),
                                       "government_approval": round(approval_estimate, 2)},
                    "currency_observed": w.econ.currency,
                    "confidence": "medium" if reliability > .58 else "low"}
        actor["intelligence"].append({"month": w.month, **evidence})
        actor["intelligence"] = actor["intelligence"][-18:]
        _learn_from_intelligence(actor, poll_estimate, w.month)


def _learn_from_intelligence(actor: dict, current_poll: float, month: int) -> None:
    """Update confidence in coercion from observed outcomes, with room to double down."""
    if len(actor["intelligence"]) < 2:
        return
    prior = actor["intelligence"][-2].get("poll_estimates", {}).get("independence_support")
    actions = actor["diplomacy"].get("last_actions", [])
    coercion = any(a.get("month") == month-1 and a.get("type") in
                   ("partial_embargo", "grain_embargo", "ultimatum") for a in actions)
    if prior is None or not coercion:
        return
    delta = current_poll-prior
    belief = _belief(actor, "economic_pressure_effectiveness")
    if delta > .08:
        belief["value"] = round(clamp(belief["value"]-.06),3)
        belief["confidence"] = round(clamp(belief["confidence"]+.035),3)
        actor["memory"].append({"month": month, "actor": actor["id"], "kind": "policy_learning",
                                "text": "Karamaniyan independence support rose after economic pressure.",
                                "observation": round(delta,3), "coercion_belief": belief["value"]})
        actor["memory"] = actor["memory"][-48:]
    elif delta < -.08:
        belief["value"] = round(clamp(belief["value"]+.035),3)
        belief["confidence"] = round(clamp(belief["confidence"]+.02),3)


def _domestic(w) -> None:
    state, dip = w.foreign, w.dip
    for actor_id, actor in state["actors"].items():
        d, p, c, e = actor["domestic"], actor["political_pressures"], actor["constituencies"], actor["economy"]
        rival = w.rivals[actor_id]
        inflation = clamp(.025 + rival.printing * 1.8 + max(0.0, .04 - rival.rate) * .15)
        e["inflation"] = round(.85 * e.get("inflation", .03) + .15 * inflation, 4)
        e["growth"] = round(clamp((rival.gdp_real / (rival.gdp_real0 or rival.gdp_real) - 1) / max(1, w.month), -.1, .1), 4)
        d["inflation"] = e["inflation"]
        d["economic_growth"] = e["growth"]
        if actor_id == "veleria":
            support = {"industrial_elites": clamp(.62 - .9 * dip.coal_embargo - .5 * dip.war),
                       "workers": clamp(.68 - 1.4 * e["inflation"] - .18 * dip.war),
                       "army": clamp(.68 + .22 * actor["threat_perception"]["karamaniya"]),
                       "nationalists": clamp(.55 + .38 * _belief(actor, "karamaniya_permanent_separation")["value"]),
                       "commercial_sector": clamp(.65 - .55 * dip.war - .35 * dip.blockade),
                       "bureaucracy": clamp(.66 - .24 * state["union"]["policy_disagreement"])}
            _set_support(c, support)
            p.update({"industrial_disruption": 1 - support["industrial_elites"],
                      "worker_price_pressure": 1 - support["workers"],
                      "nationalist_demand": support["nationalists"],
                      "army_readiness_lobby": support["army"]})
        else:
            support = {"farmers": clamp(.70 - .85 * dip.grain_embargo - .30 * dip.war),
                       "grain_exporters": clamp(.74 - .80 * dip.grain_embargo - .42 * dip.war),
                       "army": clamp(.61 + .18 * actor["threat_perception"]["karamaniya"]),
                       "regional_elites": clamp(.61 - .22 * (1-state["union"]["cohesion"])),
                       "merchants": clamp(.65 - .48 * dip.war - .62 * dip.grain_embargo),
                       "union_supporters": clamp(.61 - .16 * (1-state["union"]["cohesion"])),
                       "union_skeptics": clamp(.28 + .55 * (1-state["union"]["cohesion"]))}
            _set_support(c, support)
            p.update({"farm_income_pressure": 1 - support["farmers"],
                      "exporter_opposition": 1 - support["grain_exporters"],
                      "regional_autonomy_demand": support["union_skeptics"]})
        economic_stress = clamp(e["inflation"] * 2.5 + max(0, -.01-e["growth"])*3
                                + d["war_weariness"] * .25)
        approval = clamp(d["approval"] + .012 * (1-economic_stress) - .010 * economic_stress
                         + .004 * (sum(_support(group) for group in c.values())/max(1,len(c))-.5))
        d["approval"] = round(approval, 3)
        d["fiscal_stress"] = round(clamp(.72*d.get("fiscal_stress", .18) + .28*economic_stress), 3)
        actor["strategic_goals"] = ({"union_leadership": .72, "prevent_hostile_alignment": .48 + .38*_belief(actor, "league_strategic_influence")["value"],
                                     "avoid_damaging_war": .66 + .20*d["fiscal_stress"], "industrial_growth": .77,
                                     "domestic_legitimacy": .65, "prevent_separation": .55 + .42*_belief(actor, "karamaniya_permanent_separation")["value"]}
                                    if actor_id == "veleria" else
                                    {"grain_exports": .65 + .32*(1-support["grain_exporters"]), "border_stability": .77,
                                     "union_security": .55 + .2*state["union"]["shared_threat_perception"],
                                     "avoid_war": .82, "trade_access": .80,
                                     "independent_judgment": .51+support["union_skeptics"]*.22})
        if economic_stress > .35:
            label = "inflation protest" if e["inflation"] > .12 else "economic slowdown"
            if w.month % 3 == 0:
                w.event("foreign_domestic", f"A {label} puts pressure on the {w.names[actor_id]} government.",
                        importance=1, actor=actor_id)


def prepare(w) -> dict:
    """Advance aggregate domestic pressures and intelligence before cabinet calls."""
    if not w.foreign:
        w.foreign = initial_state(w.seed)
    # Keep old and new checkpoints compatible, while canonical unit counts remain Rival.army.
    for actor_id, actor in w.foreign["actors"].items():
        _ensure_actor_shape(actor, actor_id, w.seed)
        actor["military"]["active"] = w.rivals[actor_id].army
    _domestic(w)
    _constituency_pressures(w)
    _leadership(w)
    _signal_intelligence(w)
    # A crossing hardens what the actor believes after this month's signals have been read in, so
    # its effect on next month's assessment is not washed out by the same month's evidence.
    evaluate_red_lines(w)
    _government_estimates(w)
    return {actor_id: cabinet_context(w, actor_id) for actor_id in ("veleria", "dorsania")}


def _government_estimates(w) -> None:
    """Create noisy Karamaniyan estimates from observable foreign deployments and activity."""
    rng = rng_for(w.seed, w.month, "karamaniya-foreign-intelligence")
    estimates = {"month": w.month, "actors": {}}
    for actor_id, actor in w.foreign["actors"].items():
        rival = w.rivals[actor_id]
        previous = next((x for x in reversed(w.foreign["government_intelligence"])
                         if actor_id in x.get("actors", {})), None)
        prior_mid = (previous or {}).get("actors", {}).get(actor_id, {}).get("force_estimate", [0,0])
        prior = sum(prior_mid)/2 if prior_mid and prior_mid[1] else rival.army
        change = rival.army-prior
        activity = clamp(.15 + max(0,change)/25000 + actor["military"]["readiness"]*.22
                         + (.18 if w.dip.war else 0))
        center = rival.army*rng.uniform(.88,1.13)
        spread = .12 + .16*(1-activity)
        intent_estimate = clamp(.12 + activity*.48 + w.foreign["union"]["policy_disagreement"]*.12
                                + rng.uniform(-.14,.14))
        estimates["actors"][actor_id] = {
            "force_estimate": [round(center*(1-spread),-2), round(center*(1+spread),-2)],
            "activity": "elevated" if activity > .55 else "routine" if activity < .34 else "unclear",
            "observable_signals": (["increased rail and reserve traffic"] if change > 2500 else [])
                                   + (["field readiness activity"] if actor["military"]["readiness"] > .68 else []),
            "offensive_preparation_estimate": [round(max(0,intent_estimate-.15),2),round(min(1,intent_estimate+.15),2)],
            "confidence": "medium" if activity > .52 else "low",
        }
    w.foreign["government_intelligence"].append(estimates)
    w.foreign["government_intelligence"] = w.foreign["government_intelligence"][-24:]


def positions(w) -> dict:
    """Independent monthly positions; Dorsania has not seen this month's Velerian choice."""
    state, dip = w.foreign, w.dip
    v, d = state["actors"]["veleria"], state["actors"]["dorsania"]
    threat_v = clamp(.48*_belief(v, "karamaniya_permanent_separation")["value"]
                     + .34*_belief(v, "karamaniya_offensive_intent")["value"]
                     + .18*_belief(v, "league_strategic_influence")["value"])
    threat_d = clamp(.60*_belief(d, "karamaniya_offensive_intent")["value"]
                     + .20*_belief(d, "karamaniya_permanent_separation")["value"]
                     + .20*(1-state["union"]["cohesion"]))
    v["threat_perception"]["karamaniya"] = round(threat_v, 3)
    d["threat_perception"]["karamaniya"] = round(threat_d, 3)
    vp, dp = v["disposition"], d["disposition"]
    # A leadership that has lost domestic confidence does not spend what it has left on a fight.
    caution_v, caution_d = _caution(v), _caution(d)
    # A cost-aware Veleria generally prefers dependency and pressure to war.
    pressure_v = clamp((.52*threat_v + .32*v["political_pressures"].get("nationalist_demand", .4)
                        - .19*v["political_pressures"].get("industrial_disruption", .2)
                        - .18*v["domestic"]["fiscal_stress"]
                        + .14*(_belief(v,"economic_pressure_effectiveness")["value"]-.5)) * caution_v)
    vel = {"pressure": pressure_v, "grain_embargo": 0.0, "coal_embargo": 0.0,
           "military_build": 0.0, "ultimatum": False, "union": "consult"}
    if not dip.union_formed and w.month >= 3 and state["union"]["cohesion"] > .42:
        vel["union"] = "found"
    if pressure_v > .40:
        vel["coal_embargo"] = clamp((pressure_v-.34)*.58, 0, .22)
    vel["military_build"] = clamp(((threat_v-.48)*9000 + (9000 if dip.war else 0)) * caution_v, 0, 9000)
    instability = _belief(v, "karamaniya_government_instability")["value"]
    if pressure_v > .52 and (threat_v > .58 or instability > .72) and v["domestic"]["approval"] > .36 and not dip.ultimatum and not dip.war:
        vel["ultimatum"] = True
    coercion_effect = _belief(v, "economic_pressure_effectiveness")["value"]
    if coercion_effect < .34 and vp["economic_pragmatism"] > vp["nationalism"]*.82:
        vel["pressure"] *= .62
        vel["coal_embargo"] *= .55
        vel["strategy"] = "conditional normalization after ineffective economic pressure"
    elif coercion_effect < .34 and vp["nationalism"] > vp["economic_pragmatism"]:
        vel["pressure"] = clamp(vel["pressure"]+.06)
        vel["strategy"] = "sustain pressure despite costly backlash"
    else:
        vel["strategy"] = ("economic containment without direct war" if pressure_v > .43 else
                           "conditional normalization and Union consultation")

    grain_interest = d["political_pressures"].get("exporter_opposition", .2)
    union_pressure = .38*threat_d + .24*(1-state["union"]["cohesion"]) + .18*dp["nationalism"]
    dor_pressure = clamp(union_pressure - .42*grain_interest - .20*d["domestic"]["fiscal_stress"]) * caution_d
    dors = {"pressure": dor_pressure, "grain_embargo": 0.0, "military_build": 0.0,
            "union": "support", "independent_trade": False}
    if dor_pressure > .38:
        dors["grain_embargo"] = clamp((dor_pressure-.32)*.55, 0, .16)
    elif grain_interest > .42:
        dors["grain_embargo"] = -clamp(grain_interest*.08, 0, .09)
        dors["independent_trade"] = True
        dors["union"] = "oppose"
    if threat_d > .58:
        dors["military_build"] = clamp((threat_d-.5)*4800, 0, 3000) * caution_d
    dors["strategy"] = ("security coordination with protected grain trade" if dors["union"] == "oppose"
                        else "preserve Union security while limiting trade losses")
    return {"veleria": vel, "dorsania": dors}


def _strategy_change(w, actor_id: str, strategy: str, trigger: str) -> None:
    actor = w.foreign["actors"][actor_id]
    old = actor["diplomacy"]["strategy"]
    if old == strategy:
        return
    actor["diplomacy"]["strategy"] = strategy
    entry = {"month": w.month, "from": old, "to": strategy, "trigger": trigger}
    actor["diplomacy"]["strategy_history"].append(entry)
    _remember(w.foreign, actor_id, "strategy_change", f"Strategy changed to {strategy}: {trigger}", w.month,
              previous=old, strategy=strategy, trigger=trigger)


def resolve_union(w, positions: dict, cabinet_decisions: dict | None = None) -> None:
    state, union, dip = w.foreign, w.foreign["union"], w.dip
    vel, dors = positions["veleria"], positions["dorsania"]
    cabinet_decisions = cabinet_decisions or {}
    _apply_cabinet_decisions(w, positions, cabinet_decisions)
    cohesion = union["cohesion"]
    common_threat = .5 * (vel["pressure"] + dors["pressure"])
    alignment = 1.0 if dors["union"] == "support" else .25
    agreement = clamp(.5 + .5*(alignment - .5) - .30*max(0, vel["coal_embargo"] + max(0, dors["grain_embargo"]) - .22))
    union["policy_disagreement"] = round(1-agreement, 3)
    union["shared_threat_perception"] = round(.8*union["shared_threat_perception"]+.2*common_threat, 3)
    union["political_trust"] = round(clamp(union["political_trust"] + .018*(agreement-.5)
                                          - .022*(1-agreement)), 3)
    union["cohesion"] = round(clamp(cohesion + .018*(common_threat-.45) + .018*(agreement-.5)
                                   - .014*max(0, .65-w.rivals["dorsania"].gdp_real/w.rivals["dorsania"].gdp_real0)
                                   - .008*(vel["military_build"] > 5000 and dors["military_build"] < 1000)), 3)
    union["military_coordination"] = round(clamp(.82*union["military_coordination"]+.18*(.35+.65*agreement)), 3)
    union["economic_integration"] = round(clamp(union["economic_integration"]+.02*(.6-agreement)
                                                - .01*max(0, vel["coal_embargo"]+max(0,dors["grain_embargo"])-.2)), 3)
    v_rel = state["actors"]["veleria"]["relations"]["dorsania"]
    d_rel = state["actors"]["dorsania"]["relations"]["veleria"]
    v_rel["trust"] = round(clamp(v_rel["trust"] + .025*(agreement-.5)),3)
    d_rel["trust"] = round(clamp(d_rel["trust"] + .025*(agreement-.5)
                                 - .025*(dors["union"] == "oppose")),3)
    for actor_id in ("veleria", "dorsania"):
        actor = state["actors"][actor_id]
        rel = actor["relations"]["karamaniya"]
        pressure = vel["coal_embargo"] if actor_id == "veleria" else max(0,dors["grain_embargo"])
        rel["hostility"] = round(clamp(rel["hostility"] + .025*pressure + (.08 if dip.war else 0)),3)
        rel["trust"] = round(clamp(rel["trust"] - .012*pressure + (.025 if dip.nonaggression else 0)),3)
    union["history"].append({"month": w.month, "cohesion": union["cohesion"], "agreement": round(agreement,3),
                             "veleria": vel["union"], "dorsania": dors["union"]})
    union["history"] = union["history"][-120:]
    if not dip.union_formed and vel["union"] == "found" and dors["union"] != "oppose" and union["cohesion"] > .52:
        dip.union_formed = True
        _remember(state, "veleria", "union", "Veleria proposed a common Union pact; Dorsania joined after consultation.", w.month)
        w.event("union", f"{w.names['veleria']} and {w.names['dorsania']} formed the {w.names['union']} after consultations.", importance=2)
        _message(w, w.names["union"], f"The {w.names['union']} invites Karamaniya to discuss a common settlement.")
    if 1-union["cohesion"] > .48 and w.month % 3 == 0:
        w.event("union_dispute", f"Public disagreement over policy has strained cohesion inside the {w.names['union']}.",
                importance=1, cohesion=union["cohesion"])

    _strategy_change(w, "veleria", vel["strategy"], "threat and domestic cost assessment")
    _strategy_change(w, "dorsania", dors["strategy"], "farm and exporter pressure")
    v, d = state["actors"]["veleria"], state["actors"]["dorsania"]
    v_increase = vel["coal_embargo"] * (0.55 + .45*agreement)
    d_change = dors["grain_embargo"] * (.35 + .65*agreement) if dors["grain_embargo"] >= 0 else dors["grain_embargo"]
    old_coal, old_grain = dip.coal_embargo, dip.grain_embargo
    dip.coal_embargo = clamp(dip.coal_embargo + v_increase)
    dip.grain_embargo = clamp(dip.grain_embargo + d_change)
    if v_increase > 0:
        _pay_action(w, "veleria", "targeted embargo", .012 + .055*v_increase, approval=-.003)
        _remember(state, "veleria", "economic_action", "Tightened coal restrictions on Karamaniya.", w.month,
                  action="partial_embargo", change=round(v_increase,3), cost="lost industrial sales")
    if d_change != 0:
        cost = .006 + abs(d_change)*.08
        _pay_action(w, "dorsania", "grain trade policy", cost, approval=-.004 if d_change > 0 else .002)
        label = "tightened" if d_change > 0 else "eased"
        _remember(state, "dorsania", "economic_action", f"{label.capitalize()} grain export restrictions.", w.month,
                  action="partial_embargo" if d_change > 0 else "trade_concession", change=round(d_change,3),
                  cost="farmer and exporter pressure" if d_change > 0 else "Union policy disagreement")
        if d_change < 0:
            _message(w, w.names["dorsania"], "Dorsania proposes restoring some grain trade and opening a bilateral trade discussion.")
    if (old_coal < .25 <= dip.coal_embargo or old_grain < .25 <= dip.grain_embargo) and w.month % 3 == 0:
        w.event("union", "The Union has expanded economic restrictions on Karamaniya.", importance=2)
    elif d_change < 0 and old_grain > dip.grain_embargo:
        w.event("trade", "Dorsania has eased its grain restrictions despite Velerian objections.", importance=2)
    if vel["union"] == "oppose" or dors["union"] == "oppose":
        _remember(state, "dorsania", "union_dissent", "Dorsania resisted Velerian pressure in Union consultation.", w.month,
                  cohesion=union["cohesion"])
    if vel["ultimatum"] and agreement > .70 and union["cohesion"] > .55:
        _issue_ultimatum(w)
    sync_embargoes(w)
    _build_forces(w, vel, dors, agreement)
    _incident(w, agreement)


def _incident(w, agreement: float) -> None:
    if w.dip.war or w.month < 5:
        return
    vel = w.foreign["actors"]["veleria"]
    relations = vel["relations"]["karamaniya"]
    tension = vel["threat_perception"]["karamaniya"]
    readiness = vel["military"]["readiness"]
    chance = .004 + .11*relations["hostility"]*tension*readiness + .025*(1-agreement)
    rng = rng_for(w.seed, w.month, "solvara-border-incident")
    if rng.random() >= chance:
        return
    incidents = ("warning shots were exchanged after a patrol lost radio contact",
                 "a border patrol briefly crossed the line during a night movement",
                 "a misidentified supply convoy was held at a crossing for several hours")
    text = incidents[rng.randrange(len(incidents))]
    w.event("border_incident", f"Near the Kessel frontier, {text}. Both governments disputed responsibility.",
            importance=2)
    vel["threat_perception"]["karamaniya"] = round(clamp(tension+.035),3)
    vel["relations"]["karamaniya"]["hostility"] = round(clamp(relations["hostility"]+.025),3)
    w.foreign["escalation_chains"].append({"month": w.month, "actor": "veleria", "signal": "border incident",
                                            "threat_belief": vel["threat_perception"]["karamaniya"]})
    w.foreign["escalation_chains"] = w.foreign["escalation_chains"][-120:]


def sync_embargoes(w) -> None:
    union = w.foreign["union"]
    for issuer, commodity, severity in (("veleria", "coal", w.dip.coal_embargo),
                                        ("dorsania", "grain", w.dip.grain_embargo)):
        key = f"{issuer}:{commodity}"
        old = w.foreign["embargoes"].get(key, {})
        if severity <= 0:
            w.foreign["embargoes"].pop(key, None)
            continue
        obj = {"issuer": issuer, "target": "karamaniya", "commodity": commodity,
               "severity": round(severity, 3), "start_month": old.get("start_month", w.month),
               "enforcement": round(clamp(.48 + .28*union["cohesion"] + .16*union["military_coordination"]),3),
               "leakage": round(clamp(.18 + .23*w.foreign["league"]["commercial_interest"]
                                       + (.12 if w.counters.get("league_trade") else 0)
                                       + (.15 if commodity == "grain" else 0)),3)}
        w.foreign["embargoes"][key] = obj


def effective_embargo(w, issuer: str, commodity: str) -> float:
    obj = w.foreign.get("embargoes", {}).get(f"{issuer}:{commodity}")
    if not obj:
        fallback = w.dip.grain_embargo if commodity == "grain" else w.dip.coal_embargo
        return clamp(fallback)
    return clamp(obj["severity"] * obj["enforcement"] * (1-obj["leakage"]))


LEDGER_CAP = 240


def action_id(actor_id: str, month: int, kind: str, index: int) -> str:
    """Stable identity for one cabinet action: same actor, month, kind and slot is the same act.

    Deterministic rather than random on purpose. A month that is replayed after a pause must
    derive the *same* id for the same act, or a duplicate would get a fresh id and apply twice.
    """
    return f"{month}:{actor_id}:{kind}:{index}"


def _ledger(w) -> dict:
    return w.foreign.setdefault("effects_ledger", {})


def applied_effects(w) -> list:
    """Every cabinet action whose effects have been applied, oldest first."""
    return sorted(_ledger(w).values(), key=lambda e: (e.get("executed_month", 0), e.get("action_id", "")))


def _effects_applied(w, aid: str) -> dict | None:
    return _ledger(w).get(aid)


def _mark_applied(w, aid: str, actor_id: str, kind: str, effects: dict) -> None:
    from . import errors
    ledger = _ledger(w)
    ledger[aid] = {"action_id": aid, "actor": actor_id, "target": "karamaniya", "action": kind,
                   "created_month": w.month, "executed_month": w.month, "status": "APPLIED",
                   "effects_applied": effects}
    if len(ledger) > LEDGER_CAP:
        for key in sorted(ledger, key=lambda k: ledger[k].get("executed_month", 0))[:len(ledger) - LEDGER_CAP]:
            ledger.pop(key, None)


def _apply_cabinet_decisions(w, positions: dict, decisions: dict) -> None:
    """Validate and apply bounded cabinet actions. Invalid proposals are recorded and ignored.

    Every action is applied at most once. The id is derived from the act itself, so if a month is
    resolved twice — a replay, a retried call, a resumed run — the second pass is recognised as a
    duplicate and skipped rather than charging the actor and shifting its position a second time.
    """
    from . import errors
    for actor_id, decision in decisions.items():
        if actor_id not in positions or not isinstance(decision, dict):
            continue
        actor = w.foreign["actors"][actor_id]
        strategy = str(decision.get("strategy") or "").strip()[:180]
        if strategy:
            positions[actor_id]["strategy"] = strategy
        support = decision.get("union_position")
        if actor_id == "dorsania" and support in ("support", "oppose"):
            positions[actor_id]["union"] = support
        # Statements are observable and can shift reputations; LLM assessment text is not stored.
        statement = str(decision.get("public_statement") or "").strip()[:500]
        if statement:
            _remember(w.foreign, actor_id, "public_statement", statement, w.month,
                      decision_factors=list(decision.get("decision_factors") or [])[:6])
            if actor_id == "dorsania" and positions[actor_id]["union"] == "oppose":
                w.event("diplomacy", f"Dorsania publicly dissented from Veleria's proposed Union policy.",
                        importance=2)
            elif w.month % 4 == 0:
                w.event("diplomacy", f"{w.names[actor_id]} issued a statement on Karamaniya and regional policy.",
                        importance=1)
        for index, raw in enumerate(decision.get("actions", [])[:4]):
            action = dict(raw) if isinstance(raw, dict) else raw
            available = max(0, actor["military"]["reserves"]-actor["military"]["active"]*.45) if isinstance(action, dict) else 0
            error = validate_action(actor_id, action, {"mobilized_reserve": available})
            if error:
                _remember(w.foreign, actor_id, "rejected_action", error, w.month, action=action)
                errors.record(w, "FOREIGN_ACTION_INVALID", error, actor=actor_id)
                continue
            kind = action["type"]
            # Past validation the action is a dict with a known type, so the id is well defined.
            aid = action_id(actor_id, w.month, kind, index)
            if _effects_applied(w, aid) is not None:
                errors.record(w, "FOREIGN_ACTION_DUPLICATE",
                              f"{actor_id} {kind} was already applied this month; effects not repeated",
                              actor=actor_id, action=kind)
                continue
            magnitude = float(action.get("magnitude", .5))
            # What this action moves, captured before and after so the ledger records the real
            # delta rather than a description of one.
            pos_before = {k: v for k, v in positions[actor_id].items() if isinstance(v, (int, float, bool))}
            before = {"propaganda": w.dip.propaganda,
                      "hostility": actor["relations"]["karamaniya"]["hostility"],
                      "trust": actor["reputation"]["diplomatic_trust"]}
            if kind == "partial_embargo":
                positions[actor_id]["coal_embargo"] = max(positions[actor_id].get("coal_embargo", 0), .06+.16*magnitude)
            elif kind == "grain_embargo":
                positions[actor_id]["grain_embargo"] = max(positions[actor_id].get("grain_embargo", 0), .05+.14*magnitude)
            elif kind == "independent_grain_trade":
                positions[actor_id]["grain_embargo"] = -(.04+.08*magnitude)
                positions[actor_id]["independent_trade"] = True
                positions[actor_id]["union"] = "oppose"
            elif kind == "military_exercise":
                positions[actor_id]["military_build"] = min(9000 if actor_id == "veleria" else 3000,
                                                               max(positions[actor_id].get("military_build", 0),
                                                                   int(action.get("troops", 0))))
            elif kind == "ultimatum" and actor_id == "veleria":
                positions[actor_id]["ultimatum"] = True
            elif kind == "offer_talks":
                positions[actor_id]["strategy"] = "conditional talks with continued security precautions"
            elif kind == "trade_concession":
                positions[actor_id]["grain_embargo"] = -(.04+.08*magnitude)
                positions[actor_id]["independent_trade"] = True
                positions[actor_id]["union"] = "oppose"
            elif kind == "border_accord":
                positions[actor_id]["strategy"] = "bilateral border stability and protected trade"
                positions[actor_id]["grain_embargo"] = -.05
                positions[actor_id]["independent_trade"] = True
                positions[actor_id]["union"] = "oppose"
            elif kind == "propaganda":
                w.dip.propaganda = clamp(w.dip.propaganda + .07*magnitude)
                if w.const.press == "free":
                    actor["reputation"]["diplomatic_trust"] = clamp(actor["reputation"]["diplomatic_trust"]-.015*magnitude)
            elif kind == "intelligence_collection":
                rng = rng_for(w.seed, w.month, "foreign-intel-op:"+actor_id)
                belief = actor["beliefs"]["karamaniya_offensive_intent"]
                belief["confidence"] = round(clamp(belief["confidence"]+.035*magnitude),3)
                detection = .04 + .22*(w.policy.surveillance == "high") + .12*(w.const.press == "free")
                if rng.random() < detection:
                    actor["relations"]["karamaniya"]["hostility"] = clamp(actor["relations"]["karamaniya"]["hostility"]+.05)
                    w.event("scandal", f"Karamaniya announced that it had uncovered a {w.names[actor_id]} intelligence operation.",
                            importance=2)
            elif kind in ("public_statement", "intelligence_collection"):
                pass
            cost = .005 + .035*magnitude
            if kind in ("offer_talks", "trade_concession", "border_accord"):
                cost = .006 + .015*magnitude
            if kind not in ("partial_embargo", "grain_embargo", "independent_grain_trade",
                            "military_exercise", "ultimatum", "trade_concession"):
                _pay_action(w, actor_id, kind.replace("_", " "), cost)
            actor["diplomacy"]["last_actions"].append({"month": w.month, "type": kind,
                                                         "magnitude": magnitude,
                                                         "decision_factors": list(decision.get("decision_factors") or [])[:6]})
            actor["diplomacy"]["last_actions"] = actor["diplomacy"]["last_actions"][-24:]
            _remember(w.foreign, actor_id, "cabinet_action", f"Chose {kind.replace('_', ' ')}.", w.month,
                      action=kind, magnitude=magnitude,
                      decision_factors=list(decision.get("decision_factors") or [])[:6])
            effects = {f"position.{k}": round(v - pos_before.get(k, 0.0), 6)
                       for k, v in positions[actor_id].items()
                       if isinstance(v, (int, float)) and not isinstance(v, bool)
                       and abs(v - pos_before.get(k, 0.0)) > 1e-9}
            for name, now in (("propaganda", w.dip.propaganda),
                              ("hostility", actor["relations"]["karamaniya"]["hostility"]),
                              ("trust", actor["reputation"]["diplomatic_trust"])):
                if abs(now - before[name]) > 1e-9:
                    effects[name] = round(now - before[name], 6)
            _mark_applied(w, aid, actor_id, kind, effects or {"note": "no canonical state moved"})
        for update in decision.get("belief_updates", [])[:4]:
            key = update.get("belief") if isinstance(update, dict) else None
            if key not in actor["beliefs"]:
                continue
            belief = actor["beliefs"][key]
            proposed = float(update["value"])
            belief["value"] = round(clamp(belief["value"]+max(-.12,min(.12, proposed-belief["value"]))),3)
            confidence = float(update["confidence"])
            belief["confidence"] = round(clamp(belief["confidence"]+max(0,min(.05,confidence-belief["confidence"]))),3)
        for message in decision.get("diplomatic_messages", [])[:3]:
            if not isinstance(message, dict) or message.get("recipient") not in ("karamaniya", "union", "league"):
                continue
            text = str(message.get("text") or "").strip()[:500]
            if text:
                recipient = message["recipient"]
                if recipient == "karamaniya":
                    office = "treasury" if actor_id == "dorsania" else "head"
                    _private_message(w, w.names.get(actor_id, actor_id), office, text,
                                     channel="commercial channel" if office == "treasury" else "private diplomatic channel")
                else:
                    w.dip.log.append({"month": w.month, "from": w.names.get(actor_id, actor_id),
                                      "to": recipient, "text": text, "private": True})
                _remember(w.foreign, actor_id, "diplomatic_message", text, w.month,
                          recipient=recipient)


def _pay_action(w, actor_id: str, label: str, gdp_share: float, approval: float = 0.0) -> None:
    actor = w.foreign["actors"][actor_id]
    cost = max(0.0, gdp_share)
    actor["economy"]["gdp"] *= 1 - cost
    w.rivals[actor_id].gdp_real *= 1 - cost
    actor["domestic"]["fiscal_stress"] = round(clamp(actor["domestic"]["fiscal_stress"] + cost*.8),3)
    actor["domestic"]["approval"] = round(clamp(actor["domestic"]["approval"] + approval),3)
    if cost:
        _remember(w.foreign, actor_id, "action_cost", f"{label} imposed domestic economic costs.", w.month,
                  gdp_share=round(cost,4))


def _build_forces(w, vel, dors, agreement: float) -> None:
    for actor_id, position in (("veleria", vel), ("dorsania", dors)):
        actor = w.foreign["actors"][actor_id]
        requested = max(0.0, position["military_build"])
        reserve_room = max(0.0, actor["military"]["reserves"] - actor["military"]["active"]*.45)
        increase = min(requested, reserve_room, 9000 if actor_id == "veleria" else 3000)
        if w.dip.union_formed:
            increase *= .35 + .65*agreement
        rival = w.rivals[actor_id]
        if increase > 0:
            rival.army += increase
            actor["military"]["active"] += increase
            actor["military"]["readiness"] = round(clamp(actor["military"]["readiness"] + increase/150000),3)
            _pay_action(w, actor_id, "readiness and deployment", increase/(rival.population)*.18, approval=.002)
            w.foreign["escalation_chains"].append({"month": w.month, "actor": actor_id,
                                                    "signal": "force buildup", "magnitude": round(increase),
                                                    "threat_belief": actor["threat_perception"]["karamaniya"]})
    # Threat perceptions can rise after visible rival deployments; intent remains uncertain.
    if w.dip.war:
        for actor in w.foreign["actors"].values():
            actor["domestic"]["war_weariness"] = round(clamp(actor["domestic"]["war_weariness"]+.018),3)
            actor["military"]["front_allocations"] = dict(w.dip.union_front)
    else:
        for actor in w.foreign["actors"].values():
            actor["domestic"]["war_weariness"] = round(max(0, actor["domestic"]["war_weariness"]-.004),3)


def _issue_ultimatum(w) -> None:
    dip = w.dip
    if dip.ultimatum or dip.war:
        return
    deadline = w.month + 4
    dip.ultimatum = {"issued": w.month, "deadline": deadline,
                     "terms": "Open negotiations on Karamaniya's status in the Solvaran Union."}
    dip.rally = clamp(dip.rally + .16)
    _pay_action(w, "veleria", "ultimatum", .008, approval=.003)
    _message(w, w.names["union"], f"The {w.names['union']} requests a settlement on Karamaniya's status by {w.month+4}; talks remain open.")
    w.event("ultimatum", f"The {w.names['union']} has set a deadline for negotiations on Karamaniya's status.", importance=2)
    _remember(w.foreign, "veleria", "diplomacy", "Issued a time-limited status demand.", w.month,
              action="ultimatum", factors=["separation belief", "domestic nationalist pressure", "Union agreement"])


def _message(w, sender: str, text: str) -> None:
    item = {"month": w.month, "from": sender, "text": text}
    w.dip.inbox.append(item)
    w.dip.log.append(item)


def _private_message(w, sender: str, office: str, text: str, channel: str | None = None) -> None:
    target = office if w.holder(office) else ("head" if w.holder("head") else office)
    item = {"month": w.month, "from": sender, "office": target, "channel": channel or target,
            "text": text, "private": True}
    w.dip.private_inbox.append(item)
    w.dip.log.append(item)


def dorsania_reply(w, kind: str, amount: float = 0.0, text: str = "") -> None:
    """Independent Dorsanian response to Karamaniya's bilateral trade proposal."""
    actor = w.foreign["actors"]["dorsania"]
    relation = actor["relations"]["karamaniya"]
    pressure = actor["political_pressures"].get("exporter_opposition", .2)
    if kind != "grain_deal":
        _message(w, w.names["dorsania"], "Dorsania has no standing to answer that proposal on behalf of the Union.")
        return
    if w.dip.war or w.region("dorran").controller != "karamaniya" or relation["trust"] < .30:
        _message(w, w.names["dorsania"], "Dorsania declines a grain agreement while the border and political conditions remain unsettled.")
        return
    duration = 6 if pressure < .55 else 9
    commitments = actor["diplomacy"].setdefault("commitments", [])
    existing = [c for c in commitments if isinstance(c, dict) and c.get("partner") == "karamaniya"
                and c.get("type") == "grain agreement" and c.get("until", -1) >= w.month]
    prior_until = max((int(c.get("until", w.month - 1)) for c in existing), default=w.month - 1)
    until = prior_until + duration
    w.counters["dorsania_trade"] = 1.0
    w.counters["dorsania_trade_until"] = float(until)
    w.dip.grain_embargo = max(0.0, w.dip.grain_embargo-.12)
    relation["trust"] = round(clamp(relation["trust"]+.08),3)
    relation["trade_importance"] = round(clamp(relation["trade_importance"]+.06),3)
    if existing:
        agreement = max(existing, key=lambda c: int(c.get("until", -1)))
        agreement.update({"until": until, "last_renewed": w.month, "message": text[:240]})
    else:
        commitments.append({"type": "grain agreement", "month": w.month, "until": until,
                            "partner": "karamaniya", "message": text[:240]})
    actor["diplomacy"]["strategy"] = "preserve Union membership while honoring profitable grain agreements"
    _private_message(w, w.names["dorsania"], "treasury",
                     f"Dorsania accepts a grain purchase arrangement through Month {until + 1} and will restore some exports to Karamaniya.",
                     channel="commercial channel")
    _remember(w.foreign, "dorsania", "bilateral_agreement", "Accepted a grain purchase agreement with Karamaniya.",
              w.month, until=until, farmer_pressure=round(1-_support(actor["constituencies"].get("farmers")),2),
              decision_factors=["grain exporter demand", "Karamaniya market access", "Union cohesion"])
    w.event("trade", "Dorsania accepted a bilateral grain agreement with Karamaniya, drawing objections from Veleria.",
            importance=2)


def league_month(w) -> None:
    """Interest-sensitive League policy. Routine months do not need another model call."""
    state, dip, e = w.foreign["league"], w.dip, w.econ
    victim = (dip.war and dip.aggressor == "union") or dip.blockade
    democratic = .35 + .35 * (1 if w.const.elected else .5 if w.const.election_month >= 0 else .15)
    democratic -= .20 if w.const.minority != "equal" else 0
    democratic -= .10 if w.policy.arrests == "mass" else 0
    democratic -= .10 if w.month - e.scandal_month < 12 else 0
    credible = .50 if w.policy.debt_service == "suspend" else 1.0
    target = clamp(democratic * credible + (.10 if victim else 0))
    w.set_league_trust(.88*state["trust_in_karamaniya"]+.12*target)
    loan = state["loan"]
    loan["default_risk"] = round(clamp(.14 + max(0,e.deficit/(e.gdp_nominal or 1)-.04)*2
                                        + max(0,.45-dip.league_trust)*.35
                                        + (.18 if w.policy.debt_service == "suspend" else 0)),3)
    state["shipping_security_concern"] = round(clamp(.70*state["shipping_security_concern"]
                                                     + .30*(.60*dip.blockade_eff + .28*dip.war + .12*dip.grain_embargo)),3)
    state["shipping"]["insurance_cost"] = round(.025 + .20*state["shipping_security_concern"],4)
    state["shipping"]["routes_open"] = not (dip.blockade and dip.blockade_eff > .8 and not dip.league_escort)

    # New tranches are released only if financial and political conditions remain credible.
    deficit_ratio = e.deficit / (e.gdp_nominal or 1)
    conditions_met = deficit_ratio <= .05 and w.policy.debt_service == "pay" and dip.league_trust > .38
    if dip.league_loan_pending > 0:
        if not conditions_met and loan["default_risk"] > .42:
            dip.league_loan_pending = 0.0
            # Credit approved but never disbursed is not outstanding exposure. If earlier
            # tranches were already paid, retain only the principal still owed.
            state["financial_exposure"] = round(clamp(loan["principal"] / 300e6), 3)
            _private_message(w, w.names["league"], "treasury",
                             "The League has frozen the remaining loan tranches after its fiscal review.",
                             channel="credit review")
            _remember(w.foreign, "league", "loan_review", "Frozen disbursement as fiscal conditions failed.", w.month,
                      default_risk=loan["default_risk"])
    if loan["principal"] > 0 and loan["maturity_month"] >= 0 and w.month > loan["maturity_month"]:
        installment = min(loan["principal"], loan["principal"] * .08)
        payment = min(installment, max(0.0, e.gold))
        if payment >= installment * .8:
            e.gold -= payment
            e.debt_for = max(0.0, e.debt_for-payment)
            loan["principal"] = max(0.0, loan["principal"]-payment)
            state["financial_exposure"] = round(clamp(loan["principal"]/300e6),3)
        else:
            loan["default_risk"] = round(clamp(loan["default_risk"]+.08),3)
            w.adjust_league_trust(-.025)
            if w.month % 3 == 0:
                _private_message(w, w.names["league"], "treasury",
                                 "The League has raised concerns about overdue loan repayment.",
                                 channel="credit review")
    if victim and dip.league_trust > .48 and not dip.league_sanctions:
        dip.league_sanctions = True
        state["strategy"] = "contain Union expansion while protecting commercial routes"
        _message(w, w.names["league"], "The League has imposed limited commercial sanctions on the Union.")
    if dip.blockade:
        state["fear_of_union_expansion"] = round(clamp(state["fear_of_union_expansion"]+.035),3)
        if dip.league_trust > .50 and state["shipping_security_concern"] > .28 and not dip.league_escort:
            dip.league_escort = True
            state["shipping"]["escorts"] = 2
            _message(w, w.names["league"], "League escorts will accompany insured merchant convoys near Karamaniya.")
    if dip.league_trust < .34 and dip.league_aid > 0:
        dip.league_aid = 0.0
        _private_message(w, w.names["league"], "navy",
                         "The League has stopped military deliveries after its political review.",
                         channel="aid review")
    state["history"].append({"month": w.month, "trust": dip.league_trust,
                             "exposure": state["financial_exposure"], "shipping_risk": state["shipping_security_concern"],
                             "default_risk": loan["default_risk"], "strategy": state["strategy"]})
    state["history"] = state["history"][-120:]


# Optional cabinet adapters can use this contract without adding delegate seats.
def cabinet_schema(actor_id: str | None = None) -> dict:
    """The reply contract for one cabinet: its own actions only. Without an actor, the union of
    both catalogs. Either way each action appears once: strict validators (the Claude CLI's
    --json-schema) reject an enum with duplicate items, and the two catalogs share four actions."""
    catalog = action_catalog(actor_id) if actor_id else action_catalog("veleria") + action_catalog("dorsania")
    kinds = list(dict.fromkeys(a["type"] for a in catalog))
    action = {"type": "object", "additionalProperties": False,
              "properties": {"type": {"type": "string", "enum": kinds},
                             "magnitude": {"type": "number", "minimum": 0, "maximum": 1},
                             "troops": {"type": "integer", "minimum": 0}}, "required": ["type"]}
    message = {"type": "object", "additionalProperties": False,
               "properties": {"recipient": {"type": "string", "enum": ["karamaniya", "union", "league"]},
                              "text": {"type": "string"}}, "required": ["recipient", "text"]}
    belief_update = {"type": "object", "additionalProperties": False,
                     "properties": {"belief": {"type": "string"}, "value": {"type": "number", "minimum": 0, "maximum": 1},
                                    "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
                     "required": ["belief", "value", "confidence"]}
    return {"type": "object", "additionalProperties": False,
            "properties": {"public_statement": {"type": "string"},
                           "strategic_assessment": {"type": "string"},
                           "strategy": {"type": "string"},
                           "actions": {"type": "array", "items": action, "maxItems": 4},
                           "diplomatic_messages": {"type": "array", "items": message, "maxItems": 3},
                           "union_position": {"type": ["string", "null"]},
                           "belief_updates": {"type": "array", "items": belief_update, "maxItems": 4},
                           "decision_factors": {"type": "array", "items": {"type": "string"}}},
            "required": ["public_statement", "strategic_assessment", "strategy", "actions",
                         "diplomatic_messages", "union_position", "belief_updates", "decision_factors"]}


def cabinet_context(w, actor_id: str) -> dict:
    """Bounded, actor-specific inputs for a future configured cabinet model."""
    from .founding import public_profile
    inherited = public_profile(w)
    actor = w.foreign["actors"][actor_id]
    return {"actor": actor_id, "domestic": actor["domestic"], "pressures": actor["political_pressures"],
            "goals": actor["strategic_goals"], "beliefs": actor["beliefs"], "intelligence": actor["intelligence"][-6:],
            "relations": actor["relations"], "strategy": actor["diplomacy"]["strategy"],
            "commitments": actor["diplomacy"].get("commitments", [])[-8:],
            "recent_memory": actor["memory"][-8:], "union": w.foreign["union"],
            "current_diplomacy": [{"from": item.get("from"), "text": item.get("text", "")}
                                  for item in w.dip.inbox[-6:]],
            "public_karamaniya": {"currency": w.econ.currency, "war": w.dip.war,
                                  "public_vulnerabilities": [{"id": p["id"], "category": p["category"],
                                      "severity": p["severity"], "description": p["public_description"]}
                                      for p in inherited.get("problems", [])],
                                  "visible_force_estimate": actor["intelligence"][-1].get("visible_karamaniyan_force_estimate")
                                  if actor["intelligence"] else None},
            "available_mobilized_reserve": max(0, actor["military"]["reserves"]-actor["military"]["active"]*.45),
            "available_actions": action_catalog(actor_id)}


def cabinet_system_prompt(actor_id: str) -> str:
    goals = ("Veleria's security, prosperity, domestic legitimacy and leadership in the Solvaran Union. "
             "Union leadership, regional influence and preventing permanent separation matter, but avoid a damaging war.")
    if actor_id == "dorsania":
        goals = ("Dorsanian security, prosperity and independent judgment. Protect grain trade, farmers, border stability "
                 "and Union benefits. You are not required to follow Veleria.")
    return (f"You are the single strategic cabinet actor for {actor_id.title()}. Protect {goals} "
            "You receive only public observations and uncertain intelligence estimates; Karamaniya's private prompts, "
            "true intentions and hidden policies are not available. Decide from your current beliefs and interests. "
            "Choose actions only when their likely benefit justifies the listed costs and risks. Strategic actions have "
            "canonical validation and may be rejected. Keep statements and messages concise. Return only the required "
            "JSON object. Give a short assessment and concrete decision factors, never private chain-of-thought.")


def normalize_cabinet_output(actor_id: str, data) -> tuple[dict, list[str]]:
    """Bound model-provided data before it can influence the world."""
    if not isinstance(data, dict):
        return {}, ["cabinet response was not a JSON object"]
    out, problems = {}, []
    for key, limit in (("public_statement", 500), ("strategic_assessment", 1200), ("strategy", 180)):
        value = data.get(key, "")
        if isinstance(value, str):
            out[key] = value[:limit]
        else:
            problems.append(f"{key} must be text")
    allowed_union = {"support", "oppose", "conditional", "consult"}
    position = data.get("union_position")
    out["union_position"] = position if position in allowed_union else None
    allowed = {a["type"] for a in action_catalog(actor_id)}
    actions = []
    for raw in data.get("actions", [])[:4] if isinstance(data.get("actions", []), list) else []:
        if not isinstance(raw, dict) or raw.get("type") not in allowed:
            problems.append("unsupported cabinet action")
            continue
        action = {"type": raw["type"]}
        magnitude = raw.get("magnitude", .5)
        if not isinstance(magnitude, (int, float)) or not math.isfinite(magnitude) or not 0 <= magnitude <= 1:
            problems.append("action magnitude must be between 0 and 1")
            continue
        action["magnitude"] = float(magnitude)
        if "troops" in raw:
            if isinstance(raw["troops"], int) and raw["troops"] >= 0:
                action["troops"] = raw["troops"]
            else:
                problems.append("troops must be a nonnegative integer")
                continue
        actions.append(action)
    out["actions"] = actions
    messages = []
    for raw in data.get("diplomatic_messages", [])[:3] if isinstance(data.get("diplomatic_messages", []), list) else []:
        if isinstance(raw, dict) and raw.get("recipient") in ("karamaniya", "union", "league") and isinstance(raw.get("text"), str):
            messages.append({"recipient": raw["recipient"], "text": raw["text"][:500]})
        else:
            problems.append("invalid diplomatic message")
    out["diplomatic_messages"] = messages
    factors = data.get("decision_factors", [])
    out["decision_factors"] = [str(v)[:160] for v in factors[:8]] if isinstance(factors, list) else []
    updates = []
    for raw in data.get("belief_updates", [])[:4] if isinstance(data.get("belief_updates", []), list) else []:
        if (isinstance(raw, dict) and raw.get("belief") in {
                "karamaniya_permanent_separation", "karamaniya_offensive_intent",
                "league_strategic_influence", "dorsania_resists_escalation",
                "economic_pressure_effectiveness", "karamaniya_government_instability"}
                and isinstance(raw.get("value"), (int, float)) and math.isfinite(raw["value"])
                and isinstance(raw.get("confidence"), (int, float)) and math.isfinite(raw["confidence"])):
            updates.append({"belief": raw["belief"], "value": clamp(raw["value"]),
                            "confidence": clamp(raw["confidence"])})
        else:
            problems.append("invalid belief update")
    out["belief_updates"] = updates
    return out, problems


def action_catalog(actor_id: str) -> list:
    common = [{"type": "offer_talks", "cost": "staff time; may signal weakness", "risk": "domestic criticism"},
              {"type": "public_statement", "cost": "credibility if inaccurate", "risk": "counter-messaging"},
              {"type": "trade_concession", "cost": "producer revenue", "risk": "Union disagreement"},
              {"type": "intelligence_collection", "cost": "budget", "risk": "exposure and diplomatic damage"}]
    if actor_id == "veleria":
        common += [{"type": "partial_embargo", "cost": "export losses", "risk": "smuggling and Karamaniyan backlash"},
                   {"type": "military_exercise", "cost": "budget and readiness fatigue", "risk": "counter-mobilization"},
                   {"type": "ultimatum", "cost": "credibility if ignored", "risk": "hardens Karamaniyan resistance"},
                   {"type": "propaganda", "cost": "credibility", "risk": "counter-propaganda and backlash"}]
    elif actor_id == "dorsania":
        common += [{"type": "grain_embargo", "cost": "farmer and exporter losses", "risk": "market substitution"},
                   {"type": "independent_grain_trade", "cost": "Union trust", "risk": "Velerian retaliation"},
                   {"type": "border_accord", "cost": "security concessions", "risk": "Union dispute"}]
    return common


def validate_action(actor_id: str, action: dict, world_state: dict) -> str | None:
    """Validate the bounded action contract before an actor can affect canonical state."""
    allowed = {a["type"] for a in action_catalog(actor_id)}
    if not isinstance(action, dict) or action.get("type") not in allowed:
        return f"Unsupported {actor_id} action: {action.get('type') if isinstance(action, dict) else action!r}"
    magnitude = action.get("magnitude", 0)
    if not isinstance(magnitude, (int, float)) or not math.isfinite(magnitude) or magnitude < 0 or magnitude > 1:
        return "magnitude must be between 0 and 1"
    if action.get("type") == "military_exercise":
        available = world_state.get("mobilized_reserve", 0)
        troops = action.get("troops", 0)
        if not isinstance(troops, int) or troops < 0 or troops > available:
            return f"Requested deployment exceeds available mobilized reserve ({available:,.0f})"
    return None
