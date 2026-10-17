"""Persistent, imperfectly informed strategic actors outside Karamaniya.

Foreign domestic politics are deliberately aggregate. Veleria and Dorsania make
independent strategic choices before Union consultation; the League uses compact
economic rules for ordinary months. State in this module is serializable JSON data.
"""
from __future__ import annotations

import math
import re

from . import fine_print, foreign_force, operations, resolve
from .world import (ARREST_PENALTY, ASSEMBLY_FACTORS, ASSEMBLY_WEIGHT, COLLECTIVE_WEIGHT, COUP_WEIGHT,
                    EMERGENCY_WEIGHT, KARAMANIYA_REGIONS, PRESS_FACTORS, PRESS_WEIGHT, clamp, in_force_penalties,
                    rng_for)


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
# Engine 18: the Union's own demand reads how firm Karamaniya looks (resolve.py). The agreement it needs falls by
# RESOLVE_AGREEMENT_SLACK for every unit the figure lies below RESOLVE_NEUTRAL (resolve_union). Below RESOLVE_LAND, with
# Kessel Valley still held, the demand is for the valley itself, made as a cabinet makes it (foreign_force.apply).
RESOLVE_NEUTRAL = .5
RESOLVE_AGREEMENT_SLACK = .3
RESOLVE_LAND = .35
RULE_LAND_REGION = "kessel"
# Audit FO6: in a month no cabinet answered, the Union's own rule also demands when Karamaniya looks wavering (below
# RULE_DEMAND_RESOLVE) or the Union has more than RULE_DEMAND_RATIO soldiers per Karamanian soldier, from RULE_DEMAND_FROM
# on, as the baselines' stand-in neighbour does (backends/scripted.py: 0-based Month 3, the stand-in's VELERIAN_FROM). A
# demand the rule has set is followed by no other for RULE_DEMAND_GAP months (w.foreign["rule_demand_month"]).
RULE_DEMAND_FROM = 2
RULE_DEMAND_RESOLVE = .45
RULE_DEMAND_RATIO = 3.0
RULE_DEMAND_GAP = 6
# Audit FO11: in a month Veleria's pressure on Karamaniya is below COAL_EASE_PRESSURE, its coal embargo eases by COAL_EASE_STEP.
COAL_EASE_PRESSURE = .3
COAL_EASE_STEP = .05


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
    """Karamaniya has settled grain trade bilaterally with Dorsania, outside the Union's policy.

    Only a deal the government made or extended counts. The transition arrangement it inherited at
    independence is open from Month 1 of every run, and in engine 5 it crossed this line before the
    council had met, so Veleria escalated against something nobody in the government had done.
    """
    return 1.0 if _bilateral_trade_open(w) and not w.counters.get("dorsania_trade_inherited") else 0.0


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
    # Engine 12: the government's temperament for this run moves its seeded disposition, so the
    # engine's own rules and the cabinet's instructions describe the same leadership.
    temperament = foreign_force.draw_temperament(actor_id, seed)
    shift = foreign_force.TEMPERAMENT_SHIFT[temperament]
    # Engine 15: Dorsania is hostile too (it had the disposition of a reluctant trading partner).
    base = {
        "veleria": {"risk_tolerance": .38, "aggressiveness": .72, "economic_pragmatism": .57,
                    "nationalism": .78, "patience": .48, "diplomatic_flexibility": .42,
                    "threat_sensitivity": .76},
        "dorsania": {"risk_tolerance": .28, "aggressiveness": .44, "economic_pragmatism": .74,
                     "nationalism": .56, "patience": .58, "diplomatic_flexibility": .54,
                     "threat_sensitivity": .48},
    }[actor_id]
    disposition = {k: round(clamp(v + shift.get(k, 0.0) + rng.uniform(-.07, .07)), 3) for k, v in base.items()}
    return {
        "id": actor_id,
        "temperament": temperament,
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
        # Engine 15: both start hostile to Karamaniya (Veleria trust .37, hostility .46; Dorsania .49 and .26).
        "relations": ({"dorsania": {"trust": .67, "hostility": .12, "dependence": .58,
                                      "trade_importance": .31, "threat_perception": .20},
                       "karamaniya": {"trust": .20, "hostility": .72, "dependence": .09,
                                        "trade_importance": .14, "threat_perception": .48},
                       "league": {"trust": .53, "hostility": .12, "dependence": .12,
                                  "trade_importance": .20, "threat_perception": .22}}
                      if actor_id == "veleria" else
                      {"veleria": {"trust": .59, "hostility": .17, "dependence": .64,
                                    "trade_importance": .28, "threat_perception": .34},
                       "karamaniya": {"trust": .30, "hostility": .55, "dependence": .28,
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
        "diplomacy": {"strategy": "force Karamaniya back into the Union on Veleria's terms" if actor_id == "veleria"
                      else "turn Karamaniya's need for Dorsanian grain into leverage",
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
    # A checkpoint from before engine 12 gets its run's temperament as a label for the cabinet; its
    # disposition, already in play, is left as it was.
    actor.setdefault("temperament", foreign_force.draw_temperament(actor_id, seed))
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
        # Audit TO4 + FO15: one centre with symmetric noise and a band of ±half around it, so the ends are ordered and the figure
        # is unbiased (two independent draws centred the band about 10% high, and its ends could reverse). The two draws are the
        # stream's as before, so the draws after them keep their values. While an inspection regime is in force its inspectors
        # count the army: the band is the army, to the hundred (fine_print.inspected, Audit MI6).
        centre = m.army.size * rng.uniform(.90, 1.10)
        half = m.army.size * rng.uniform(.05, .15)
        band = [round(centre - half, -2), round(centre + half, -2)]
        if fine_print.inspected(w):
            band = [math.floor(m.army.size / 100) * 100, math.ceil(m.army.size / 100) * 100]
        evidence = {"visible_karamaniyan_force_estimate": band,
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
    foreign_force.expire_covert_support(w)
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
        # Troops massed at the border are the plainest signal there is (engine 12). Their estimate has
        # its own noise, so it does not shift the draws the other estimates were made with.
        massed = foreign_force.at_border(w, actor_id)
        brng = rng_for(w.seed, w.month, "karamaniya-border-intelligence:" + actor_id)
        border = {}
        for front in foreign_force.FRONTS:
            n = foreign_force.at_border(w, actor_id, front)
            if n >= 500:
                border[front] = [round(n * brng.uniform(.75, .95), -2), round(n * brng.uniform(1.05, 1.3), -2)]
        activity = clamp(.15 + max(0,change)/25000 + actor["military"]["readiness"]*.22
                         + (.18 if w.dip.war else 0) + .30 * min(1.0, massed / 15000))
        center = rival.army*rng.uniform(.88,1.13)
        spread = .12 + .16*(1-activity)
        intent_estimate = clamp(.12 + activity*.48 + w.foreign["union"]["policy_disagreement"]*.12
                                + rng.uniform(-.14,.14))
        estimates["actors"][actor_id] = {
            "force_estimate": [round(center*(1-spread),-2), round(center*(1+spread),-2)],
            "activity": "elevated" if activity > .55 else "routine" if activity < .34 else "unclear",
            "observable_signals": (["increased rail and reserve traffic"] if change > 2500 else [])
                                   + (["field readiness activity"] if actor["military"]["readiness"] > .68 else [])
                                   + [f"troops massing at the {front} border (about {lo:,.0f}-{hi:,.0f})"
                                      for front, (lo, hi) in border.items()],
            "border_force_estimate": border,
            "offensive_preparation_estimate": [round(max(0,intent_estimate-.15),2),round(min(1,intent_estimate+.15),2)],
            "confidence": "medium" if activity > .52 else "low",
        }
    w.foreign["government_intelligence"].append(estimates)
    w.foreign["government_intelligence"] = w.foreign["government_intelligence"][-24:]


def _head_tone_threat(w) -> float:
    """Audit MI9: the head's diplomatic tone, as a term of Veleria's threat (operations.py: a conciliatory head lowers it .01,
    a firm one raises it .01). It is read here rather than written to the threat in operations.apply, because positions()
    rebuilds the threat from beliefs each month and a write made earlier in the month was lost. Like operations.apply, it
    counts only where the human factor runs at architecture 2 or later, and while the head holds office."""
    if not (w.human_factor and w.agent_architecture_version >= 2) or not w.holder("head"):
        return 0.0
    return {"conciliatory": -.01, "firm": .01}.get(operations.current(w, "head")["diplomatic_tone"], 0.0)


def positions(w) -> dict:
    """Independent monthly positions; Dorsania has not seen this month's Velerian choice."""
    state, dip = w.foreign, w.dip
    v, d = state["actors"]["veleria"], state["actors"]["dorsania"]
    threat_v = clamp(.48*_belief(v, "karamaniya_permanent_separation")["value"]
                     + .34*_belief(v, "karamaniya_offensive_intent")["value"]
                     + .18*_belief(v, "league_strategic_influence")["value"] + _head_tone_threat(w))
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
    # Audit FO11: a month of Velerian pressure below COAL_EASE_PRESSURE eases the coal embargo a step. It used to only ratchet
    # up, since nothing in the positions could lower it. The change is paid or given back through _embargo_output below.
    if vel["pressure"] < COAL_EASE_PRESSURE:
        v_increase -= COAL_EASE_STEP
    d_change = dors["grain_embargo"] * (.35 + .65*agreement) if dors["grain_embargo"] >= 0 else dors["grain_embargo"]
    old_coal, old_grain = dip.coal_embargo, dip.grain_embargo
    dip.coal_embargo = clamp(dip.coal_embargo + v_increase)
    dip.grain_embargo = clamp(dip.grain_embargo + d_change)
    if dip.coal_embargo != old_coal:
        _embargo_output(w, "veleria", old_coal, dip.coal_embargo, "targeted embargo",
                        approval=-.003 if dip.coal_embargo > old_coal else 0.0)
    if v_increase > 0 and dip.coal_embargo > old_coal:
        _remember(state, "veleria", "economic_action", "Tightened coal restrictions on Karamaniya.", w.month,
                  action="partial_embargo", change=round(dip.coal_embargo - old_coal, 3), cost="lost industrial sales")
    if dip.grain_embargo != old_grain:
        # Engine 18: only a change the embargo's level took is paid, recorded and announced; easing one that stands
        # at zero changes nothing (see EMBARGO_COST).
        _embargo_output(w, "dorsania", old_grain, dip.grain_embargo, "grain trade policy",
                        approval=-.004 if d_change > 0 else .002)
        d_change = dip.grain_embargo - old_grain
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
    # A cabinet that answered sets its own ultimatum (foreign_force); the rule is for a month without one. Engine 18:
    # the agreement it needs falls by RESOLVE_AGREEMENT_SLACK for every unit the figure lies below neutral, so a
    # Karamaniya that looks yielding is more likely to be given one (resolve.py).
    bar = .70 - RESOLVE_AGREEMENT_SLACK * max(0.0, RESOLVE_NEUTRAL - resolve.value(w))
    # Audit FO6: in a month no cabinet answered, the rule's flag also rises when Karamaniya looks wavering or the Union
    # outnumbers it (RULE_DEMAND_*); a demand the rule set is followed by no other for RULE_DEMAND_GAP months.
    unanswered = state.get("cabinet_month", {}).get("veleria") != w.month
    looks_weak = unanswered and w.month >= RULE_DEMAND_FROM and (
        resolve.value(w) < RULE_DEMAND_RESOLVE or _union_per_karamanian_soldier(w) > RULE_DEMAND_RATIO)
    last_demand = w.foreign.get("rule_demand_month")
    cooled = last_demand is None or w.month - int(last_demand) >= RULE_DEMAND_GAP
    if ((vel["ultimatum"] or looks_weak) and agreement > bar and union["cohesion"] > .55
            and unanswered and cooled):
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
    # Engine 19 (audit MI9's class): positions() rebuilds the threat from Veleria's beliefs each month, so the write above
    # lasts only the month; the belief behind it moves too, so the incident still counts after the rebuild.
    from .dilemmas import _raise_veleria_threat
    _raise_veleria_threat(w, .035)
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


# ---- Wave 3: the Union's propaganda and Karamaniya's counter ------------------------------------
# Shared state contract (notes/wave3-spec.md): worker A owns w.media["credibility"], the state campaign's line and
# boost; this module reads credibility and writes only foreign campaign records. An old checkpoint (or a build before
# A's branch merges) has no credibility field, so the documented starting value is read rather than created here.
STATE_MEDIA_DEFAULT_CREDIBILITY = .6
# What a campaign does at magnitude 1, credibility 0 and hardship factor 1: approval falls by this much and grievance
# rises by this much. Grievance is the channel: society.update derives unrest from it (p.unrest = grievance * (1 - .75 *
# fear)), so the campaign does not write unrest directly and cannot be overwritten by the same month's society pass.
PROPAGANDA_APPROVAL = .06
PROPAGANDA_GRIEVANCE = .05
# Real hardship makes a broadcast land harder ("true grievances ... make it land harder", notes/wave3-spec.md). The
# hardship index is a weighted mix of lived conditions, 0..1; the factor is .4 + 1.2 x hardship, so a calm country
# still hears a little (the floor) and a hard region lands up to 1.6x. Starting conditions sit near .04 (factor .45);
# a crisis region near .4 (factor .88).
PROPAGANDA_HARDSHIP_WEIGHTS = {"grievance": .35, "hunger": .25, "income": .2, "unemployment": .1, "repression": .1}
PROPAGANDA_HARDSHIP_FLOOR = .4
PROPAGANDA_HARDSHIP_WEIGHT = 1.2
PROPAGANDA_HARDSHIP_CEIL = 1.6
# What each message does: (approval weight, grievance weight). government_failing is the plain claim; blame_government
# puts the hardship on the government and moves approval more than grievance; stir_minority deepens the division more
# than the general dislike and is aimed at the minority identities (PROPAGANDA_IDENTITY_WEIGHTS).
PROPAGANDA_MESSAGES = {"government_failing": (1.0, 1.0),
                       "stir_minority": (.8, 1.3),
                       "blame_government": (1.2, .9)}
PROPAGANDA_MESSAGE_KINDS = tuple(PROPAGANDA_MESSAGES)
PROPAGANDA_IDENTITY_WEIGHTS = {"government_failing": {"karamanian": 1.0, "imperial": 1.0, "vell": 1.0},
                               "blame_government": {"karamanian": 1.0, "imperial": 1.0, "vell": 1.0},
                               "stir_minority": {"karamanian": .8, "imperial": 1.5, "vell": 1.4}}
PROPAGANDA_TARGETS = ("country",) + tuple(rid for rid, *_ in KARAMANIYA_REGIONS)
# The schema offers the display names too, because the catalog entry and the prompt name the regions that way; the
# reader resolves either form to the id, as it does for a covert-support region.
PROPAGANDA_TARGET_CHOICES = PROPAGANDA_TARGETS + tuple(name for _, name, *_ in KARAMANIYA_REGIONS)
# The counter. Jamming leaves a quarter of the effect: it stops the broadcasts, not word of mouth. It costs .02 of state
# media credibility each month it stands ("what are they hiding?"), a standing suspicion rather than a one-off shock,
# and world.democracy_index subtracts BROADCAST_JAM_PENALTY while it is in force. `open` is the default, so a run that
# never touches the setting behaves as it did before wave 3.
BROADCAST_JAM_EFFECT = .25
BROADCAST_JAM_CREDIBILITY = .02

# B6 (T170): a foreign propaganda campaign can be caught in the month it airs. The chance is set by the Interior's
# surveillance setting and drawn on a stream of its own, rng_for(seed, month, "foreign_exposure"), so the state media's
# own exposure draws (stream "media") do not move. Low is the default setting, and a campaign caught in its first month
# is the rare case; high surveillance makes it expected rather than exceptional. A caught campaign is named publicly,
# and this share of its effect on the groups it reached is undone: exposure says the line was foreign, while word of
# mouth keeps some of it.
PROPAGANDA_EXPOSURE_CHANCE = {"low": .05, "medium": .15, "high": .30}
PROPAGANDA_EXPOSURE_REVERSAL = .5


def propaganda_exposure_chance(w) -> float:
    """The chance this month's foreign propaganda campaign is caught, from the Interior's surveillance setting."""
    return PROPAGANDA_EXPOSURE_CHANCE.get(getattr(w.policy, "surveillance", "low"),
                                          PROPAGANDA_EXPOSURE_CHANCE["low"])


def exposure_roll(w, tag: str, chance: float, index: int = 0) -> bool:
    """One exposure draw for this month on the stream rng_for(seed, month, tag).

    `index` is the place of this act among the month's acts on the same stream (0 for the first). The stream is opened
    for each act and advanced by the index, so two campaigns in one month are judged by different numbers while every
    draw still comes only from its own stream. Wave A's covert cabinet acts reuse this helper with the tag
    "covert_exposure".
    """
    rng = rng_for(w.seed, w.month, tag)
    draw = rng.random()
    for _ in range(index):
        draw = rng.random()
    return draw < chance


def state_media_credibility(w) -> float:
    """The public's trust in state media, 0..1, as worker A keeps it in w.media. Read-only: a missing or malformed
    field reads the documented starting value and is not created here."""
    value = (w.media or {}).get("credibility", STATE_MEDIA_DEFAULT_CREDIBILITY)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return clamp(float(value))
    return STATE_MEDIA_DEFAULT_CREDIBILITY


def _propaganda_hardship(p) -> float:
    """How hard life is for one population group, 0..1, from conditions the group actually lives in."""
    wts = PROPAGANDA_HARDSHIP_WEIGHTS
    return clamp(wts["grievance"] * p.grievance + wts["hunger"] * p.hunger
                 + wts["income"] * max(0.0, 1.0 - p.income)
                 + wts["unemployment"] * p.unemployment + wts["repression"] * p.repression)


def _apply_propaganda(w, actor_id: str, action: dict) -> dict:
    """Apply one foreign broadcast campaign and record it in w.media["campaigns"]. Returns the applied average
    deltas for the foreign ledger. Reads state media credibility; writes no state media field.

    Engine 30 (T170): the record keeps the per-group deltas the campaign applied, and the campaign is caught in the
    month it airs on the foreign exposure stream. A caught one is a public event naming the power, sets the record's
    `exposed`, and has PROPAGANDA_EXPOSURE_REVERSAL of its effect on the groups it reached undone."""
    target = action.get("target", "country")
    message = action["message"]
    magnitude = float(action.get("magnitude", .5))
    jammed = getattr(w.policy, "foreign_broadcasts", "open") == "jammed"
    credibility = state_media_credibility(w)
    approval_w, grievance_w = PROPAGANDA_MESSAGES[message]
    identity_w = PROPAGANDA_IDENTITY_WEIGHTS[message]
    scale = (1.0 - credibility) * (BROADCAST_JAM_EFFECT if jammed else 1.0)
    pops = [p for p in w.k_pops() if target == "country" or p.region == target]
    total = sum(p.size for p in pops) or 1.0
    d_approval = d_grievance = hardship = 0.0
    reached = []                       # (group, approval before, grievance before, applied delta, applied delta)
    for p in pops:
        factor = clamp(PROPAGANDA_HARDSHIP_FLOOR + PROPAGANDA_HARDSHIP_WEIGHT * _propaganda_hardship(p),
                       0.0, PROPAGANDA_HARDSHIP_CEIL)
        weight = scale * factor * identity_w.get(p.ident, 1.0) * magnitude
        before_approval, before_grievance = p.approval, p.grievance
        p.approval = clamp(p.approval - PROPAGANDA_APPROVAL * weight * approval_w, .01, .99)
        p.grievance = min(1.2, p.grievance + PROPAGANDA_GRIEVANCE * weight * grievance_w)
        d_approval += (p.approval - before_approval) * p.size
        d_grievance += (p.grievance - before_grievance) * p.size
        hardship += _propaganda_hardship(p) * p.size
        reached.append((p, before_approval, before_grievance,
                        p.approval - before_approval, p.grievance - before_grievance))
    # The long-standing Union propaganda level other mechanics read (society.propaganda_reach, referendums, intelligence
    # deception, army loyalty). Wave 3 keeps it and scales the increment by the counter; the targeted effect above is the
    # new channel the spec describes.
    w.dip.propaganda = clamp(w.dip.propaganda + .07 * magnitude * (BROADCAST_JAM_EFFECT if jammed else 1.0))
    effects = {"approval": round(d_approval / total, 6), "grievance": round(d_grievance / total, 6)}
    record = {"month": w.month, "source": actor_id, "kinds": ["propaganda"], "claims": [],
              "intensity": magnitude, "target": target, "message": message,
              "executed_by": "cabinet", "defied": False, "exposed": False,
              # Engine 30 (T170): what this campaign applied to each group it reached, so a caught campaign can be
              # reversed exactly (the averages above cannot be).
              "applied": [{"region": p.region, "cls": p.cls, "ident": p.ident,
                           "approval": round(da, 6), "grievance": round(dg, 6)}
                          for p, _before_a, _before_g, da, dg in reached],
              "effects": {**effects, "credibility": round(credibility, 4),
                          "hardship": round(hardship / total, 4), "jammed": jammed}}
    foreign_this_month = sum(1 for c in (w.media.get("campaigns") or [])
                             if c.get("month") == w.month and c.get("source") != "state")
    if exposure_roll(w, "foreign_exposure", propaganda_exposure_chance(w), index=foreign_this_month):
        for p, _before_a, _before_g, da, dg in reached:
            p.approval = clamp(p.approval - PROPAGANDA_EXPOSURE_REVERSAL * da, .01, .99)
            p.grievance = max(0.0, p.grievance - PROPAGANDA_EXPOSURE_REVERSAL * dg)
        record["exposed"] = True
        net_approval = sum((p.approval - before_a) * p.size for p, before_a, _before_g, _da, _dg in reached)
        net_grievance = sum((p.grievance - before_g) * p.size for p, _before_a, before_g, _da, _dg in reached)
        record["effects_net"] = {"approval": round(net_approval / total, 6),
                                 "grievance": round(net_grievance / total, 6)}
        where = "the country" if target == "country" else next(
            (r.name for r in w.regions if r.id == target), target)
        w.event("scandal", f"Karamaniya announced that it had uncovered a "
                           f"{w.names.get(actor_id, actor_id)} propaganda campaign aimed at {where}.",
                importance=2, actor=actor_id)
        effects["exposed"] = True
    w.media.setdefault("campaigns", []).append(record)
    return effects


def broadcast_month(w) -> None:
    """The counter's monthly cost: while foreign broadcasts are jammed, state media credibility falls a little, once a
    month. Called from director.act after the cabinets act; a setting changed by this month's council applies this month.
    This is the one write to worker A's credibility field: the spec assigns the jamming penalty to the counter, and
    without it the setting would have no cost. The rest of A's state (line, boost, state records) is untouched."""
    if getattr(w.policy, "foreign_broadcasts", "open") != "jammed":
        return
    if int(w.counters.get("broadcast_jam_month", -1)) == w.month:
        return
    w.counters["broadcast_jam_month"] = float(w.month)
    w.media["credibility"] = round(clamp(state_media_credibility(w) - BROADCAST_JAM_CREDIBILITY), 4)


def _apply_cabinet_decisions(w, positions: dict, decisions: dict) -> None:
    """Validate and apply bounded cabinet actions. Invalid proposals are recorded and ignored.

    Every action is applied at most once. The id is derived from the act itself, so if a month is
    resolved twice — a replay, a retried call, a resumed run — the second pass is recognised as a
    duplicate and skipped rather than charging the actor and shifting its position a second time.
    """
    from . import errors
    for actor_id, decision in decisions.items():
        # A failed call, or an answer that could not be read, leaves an empty decision: no cabinet decided, so the
        # Union's rules decide for that actor this month, as director.cabinet_decides says (audit CO2 follow-up).
        if actor_id not in positions or not isinstance(decision, dict) or not decision:
            continue
        actor = w.foreign["actors"][actor_id]
        # The cabinet decided this month: the Union's own rules do not also decide on war or a blockade
        # for it (director._union_forces, director._deadline_policy).
        w.foreign.setdefault("cabinet_month", {})[actor_id] = w.month
        strategy = str(decision.get("strategy") or "").strip()[:STRATEGY_CHARS]
        if strategy:
            positions[actor_id]["strategy"] = strategy
        support = decision.get("union_position")
        if actor_id == "dorsania" and support in ("support", "oppose"):
            positions[actor_id]["union"] = support
        if actor_id == "dorsania":
            # Read by a Velerian invasion next month: Dorsania joins a full war unless it last opposed.
            w.foreign["dorsania_position"] = positions[actor_id]["union"]
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
        # Every act the reader refused or changed is told to the cabinet the next month: cabinet_view lists these under
        # your_acts_refused_last_month. Run 20261011-105713-seed1: the reader's refusals stayed in the month record.
        for note in decision.get("act_notes", []):
            _remember(w.foreign, actor_id, "rejected_action", note["reason"], w.month, action={"type": note["type"]})
        for index, raw in enumerate(decision.get("actions", [])[:ACTS_PER_MONTH]):
            action = dict(raw) if isinstance(raw, dict) else raw
            available = max(0, actor["military"]["reserves"]-actor["military"]["active"]*.45) if isinstance(action, dict) else 0
            error = validate_action(actor_id, action, {"mobilized_reserve": available}, w)
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
                      "trust": actor["reputation"]["diplomatic_trust"],
                      "coal_embargo": w.dip.coal_embargo}
            force_effects = {}
            campaign_effects = {}
            if kind in foreign_force.KINDS:
                force_effects = foreign_force.apply(w, actor_id, action)
            elif kind == "partial_embargo":
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
            elif kind == "offer_talks":
                positions[actor_id]["strategy"] = "conditional talks with continued security precautions"
            elif kind == "trade_concession" and actor_id == "veleria":
                # Audit FO19: Veleria's concession eases the coal embargo it holds (resolve_union reads that level), by the step
                # Dorsania's concession eases grain. It is applied now, so the ledger records the easing that happened.
                old_coal = w.dip.coal_embargo
                w.dip.coal_embargo = clamp(old_coal - (.04+.08*magnitude))
                _embargo_output(w, actor_id, old_coal, w.dip.coal_embargo, "targeted embargo", approval=.002)
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
                campaign_effects = _apply_propaganda(w, actor_id, action)
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
            # An act of force is charged by foreign_force.apply, by what it actually moved, and a trade
            # measure by the trade it moves (resolve_union). Any other act costs budget, not output (_spend).
            if kind not in ("partial_embargo", "grain_embargo", "independent_grain_trade",
                            "military_exercise", "trade_concession") + foreign_force.KINDS:
                _spend(w, actor_id, ACT_BUDGET.get(kind, 0.0) * (.5 + magnitude))
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
            if kind == "trade_concession" and actor_id == "dorsania":
                # Audit FO19: the grain concession eases the level by its amount through resolve_union, and no more: at zero
                # grain nothing eases. The ledger records the level it moves, not the position it sets.
                eased = min(w.dip.grain_embargo, .04+.08*magnitude)
                effects.pop("position.grain_embargo", None)
                if eased > 1e-9:
                    effects["grain_embargo"] = round(-eased, 6)
            for name, now in (("propaganda", w.dip.propaganda),
                              ("hostility", actor["relations"]["karamaniya"]["hostility"]),
                              ("trust", actor["reputation"]["diplomatic_trust"]),
                              ("coal_embargo", w.dip.coal_embargo)):
                if abs(now - before[name]) > 1e-9:
                    effects[name] = round(now - before[name], 6)
            effects.update(force_effects)
            effects.update(campaign_effects)
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


# Engine 16: what the acts that move neither trade nor troops cost, as fiscal stress (a share of the budget's
# room), scaled by the act's magnitude. A statement or talks cost next to nothing; an intelligence operation
# or a propaganda campaign is paid for. Engine 15 charged each of them against the country's real output,
# .5% to 4% of it, for good: in run 20261010-070501-seed1 two cabinets acting one to four times a month
# shrank their economies by about 30% in nine months, and as the three countries share the crown, prices
# rose 42% in all three. A passive council facing the same acts got the same inflation and approval.
ACT_BUDGET = {"public_statement": 0.0, "offer_talks": .001, "border_accord": .002, "intelligence_collection": .004,
              "propaganda": .004, "ultimatum": .002}
# An embargo costs the exporter the trade it holds back: the share of output lost per unit of embargo
# (a full embargo, level 1, once). Engine 15 also charged 1.2% (Veleria) and 0.6% (Dorsania) of output in
# every month the embargo moved, which compounded. Engine 18: the exporter's output follows the embargo's
# level (_embargo_output), so only a real change moves it and easing gives back what tightening took. Engine 17
# charged every month the cabinet asked for a change, even one the level could not take: the stand-in
# Dorsania "eased" a grain embargo that stood at zero in every month, and lost about 11% of its output in 36
# months on every seed and council (found by the calibration harness, tools/calibrate.py).
EMBARGO_COST = {"veleria": .03, "dorsania": .06}


def _embargo_output(w, actor_id: str, old: float, new: float, label: str, approval: float) -> None:
    """Move the exporter's output from what an embargo at `old` left of it to what one at `new` leaves (engine 18).
    Nothing happens unless the level changed; a tighter embargo is paid like any act that costs output, a looser one
    gives the trade back."""
    if abs(new - old) < 1e-12:
        return
    cost = EMBARGO_COST[actor_id]
    factor = (1 - cost * new) / (1 - cost * old)
    if factor < 1:
        _pay_action(w, actor_id, label, 1 - factor, approval=approval)
        return
    actor = w.foreign["actors"][actor_id]
    actor["economy"]["gdp"] *= factor
    w.rivals[actor_id].gdp_real *= factor
    actor["domestic"]["approval"] = round(clamp(actor["domestic"]["approval"] + approval), 3)


def _spend(w, actor_id: str, fiscal: float, approval: float = 0.0) -> None:
    """An act that costs budget and standing, not output (engine 16)."""
    dom = w.foreign["actors"][actor_id]["domestic"]
    dom["fiscal_stress"] = round(clamp(dom["fiscal_stress"] + max(0.0, fiscal)), 3)
    dom["approval"] = round(clamp(dom["approval"] + approval), 3)


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
        # Audit FO2-f: a build is a call-up as a cabinet's mobilize is (foreign_force.apply). It is capped by what this
        # month has left of the call-up cap, and its soldiers come out of the reserve pool and are recorded against the cap.
        cap_left = max(0.0, foreign_force.MOBILIZE_CAP[actor_id] - foreign_force.called_up_this_month(w, actor_id))
        increase = min(requested, reserve_room, cap_left, 9000 if actor_id == "veleria" else 3000)
        if w.dip.union_formed:
            increase *= .35 + .65*agreement
        rival = w.rivals[actor_id]
        if increase > 0:
            rival.army += increase
            actor["military"]["active"] += increase
            actor["military"]["reserves"] = max(0.0, actor["military"]["reserves"] - increase)
            foreign_force._record_callup(w, actor_id, increase)
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


def _union_per_karamanian_soldier(w) -> float:
    """Union soldiers per Karamanian soldier, reservists called up counted as Karamanian (as resolve.baseline measures it)."""
    from .military import mobilized_strength, union_army
    return union_army(w) / max(1.0, w.mil.army.size + mobilized_strength(w))


def _issue_ultimatum(w) -> None:
    dip = w.dip
    if dip.ultimatum or dip.war:
        return
    if resolve.value(w) < RESOLVE_LAND and w.region(RULE_LAND_REGION).controller == "karamaniya":
        act = {"type": "ultimatum", "terms": foreign_force.LAND_TERMS, "region": RULE_LAND_REGION,
               "deadline_months": 4}
        if foreign_force.check(w, "veleria", act) is None:
            foreign_force.apply(w, "veleria", act)
            w.foreign["rule_demand_month"] = w.month          # Audit FO6: the six-month cooldown starts
            _remember(w.foreign, "veleria", "diplomacy",
                      f"Issued a time-limited demand for {w.region(RULE_LAND_REGION).name}.", w.month,
                      action="ultimatum", factors=["Karamaniya looks yielding", "Union agreement"])
            return
    deadline = w.month + 4
    w.foreign["rule_demand_month"] = w.month                  # Audit FO6: the six-month cooldown starts
    # Audit FO5: the rule's status demand names its terms and its neighbour as a cabinet's does, so talks lift it
    # (director._union_reply) and a cabinet is shown it (foreign_force.ultimatum_compliance).
    dip.ultimatum = {"issued": w.month, "deadline": deadline,
                     "terms": "Open negotiations on Karamaniya's status in the Solvaran Union.",
                     "terms_id": "status_talks", "by": "veleria"}
    dip.rally = clamp(dip.rally + .16)
    _spend(w, "veleria", ACT_BUDGET["ultimatum"], approval=.003)
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


# Engine 27 (wave 3, D): Dorsania answers the three pairs the act-target table used to refuse it. The proposal
# (docs/DIPLOMACY_TARGETS_PROPOSAL.md 4.1, 4.5, 4.6) left each widened pair's size open — "a Dorsanian branch would be
# small", "small", and "a grain deal, yes" — so each moves one small, documented amount:
#   - a status talk or a trade talk moves Dorsania's trust in Karamaniya by DORSANIA_TALKS_TRUST (.01): engagement,
#     not an agreement. The grain agreement it can sign gives .08 trust, and a talk must be visibly smaller than a deal.
#   - a trade deal is answered with the grain agreement Dorsania has, its only trade lever in the model.
DORSANIA_TALKS_TRUST = .01
# What a grain agreement does not carry (engine 22): troops, sovereignty, the ultimatum, citizens' rights, talks, verification
# and the like. The grain trade itself (grain, deliveries, volume, price, payment, duration) is not in it. Run
# 20261011-105713-seed1, Months 4 and 9: troop withdrawals and an end to the ultimatum were accepted with the grain, and
# nobody was told they were not.
_NOT_GRAIN = re.compile(r"\b(?:troops?|forces?|army|soldiers?|militar\w*|border|withdr\w*|pull[\s-]?back|drop\w*|"
                        r"ultimatum\w*|intelligence|sovereign\w*|recogni[sz]\w*|guarantee\w*|citizens?|citizenship|"
                        r"rights?|safety|minorit\w*|monitor\w*|observers?|inspect\w*|verif\w*|oversight|veto|"
                        r"jurisdiction|interferen\w*|non[\s-]?aggression|pact|alliance|status|talks|negotiat\w*|"
                        r"internal|separatis\w*|renounc\w*|subver\w*|cede|cession|territor\w*|courts?|law|laws|"
                        r"reports?|compliance|surrender|foreign)\b", re.I)


def dorsania_reply(w, kind: str, amount: float = 0.0, text: str = "", region: str = "", terms=None) -> None:
    """Independent Dorsanian response to Karamaniya's bilateral proposal.

    Engine 27: the six wider-diplomacy pairs give Dorsania its own answer to status talks, trade talks and a trade
    deal. Before, every one of them read "Dorsania has no standing to answer that proposal on behalf of the Union",
    which was true only while Dorsania could not receive them (proposal 4.1, 4.5, 4.6).
    """
    not_grain = _NOT_GRAIN
    actor = w.foreign["actors"]["dorsania"]
    relation = actor["relations"]["karamaniya"]
    pressure = actor["political_pressures"].get("exporter_opposition", .2)
    if kind == "cede_region":
        # Dorsania takes the region it demanded (territory.cede), as Veleria does in director._union_reply.
        from . import territory
        if not territory.cede(w, region, "dorsania"):
            _message(w, w.names["dorsania"],
                     "Karamaniya no longer holds the region the motion names, so nothing is handed over.")
        return
    if kind == "status_talks":
        # Status talks are about Karamaniya's place in the Union. Dorsania is a member and takes part, but it does not
        # answer for the Union, and it does not judge a demand Veleria issued (that is ultimatum_reply's business).
        relation["trust"] = round(clamp(relation["trust"] + DORSANIA_TALKS_TRUST), 3)
        _message(w, w.names["dorsania"],
                 "Dorsania will take part in discussions on Karamaniya's status, but the settlement is the Union's "
                 "to make and Dorsania does not answer for it.")
        _remember(w.foreign, "dorsania", "diplomacy", "Agreed to take part in status talks with Karamaniya.",
                  w.month, action="status_talks")
        return
    if kind == "trade_talks":
        # A talk is not a deal: it opens a channel and moves nothing real. Dorsania's grain lever is the agreement
        # grain_deal makes; saying so is the world's rule, not an instruction to the delegate.
        if w.dip.war or relation["trust"] < .30:
            _message(w, w.names["dorsania"],
                     "Dorsania declines trade talks while the border and political conditions remain unsettled.")
            return
        relation["trust"] = round(clamp(relation["trust"] + DORSANIA_TALKS_TRUST), 3)
        _private_message(w, w.names["dorsania"], "treasury",
                         "Dorsania agrees to discuss grain terms. Only a grain agreement binds Dorsania; talks "
                         "change no deliveries.", channel="commercial channel")
        _remember(w.foreign, "dorsania", "diplomacy", "Agreed to trade talks with Karamaniya.", w.month,
                  action="trade_talks")
        return
    if kind not in ("grain_deal", "trade_deal"):
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
    w.counters["dorsania_trade_inherited"] = 0.0      # the council's own deal now, new or extended
    # Audit FO8: a change of an embargo's level moves the exporter's output (_embargo_output).
    old_grain = w.dip.grain_embargo
    w.dip.grain_embargo = max(0.0, old_grain - .12)
    _embargo_output(w, "dorsania", old_grain, w.dip.grain_embargo, "grain trade policy", approval=.002)
    relation["trust"] = round(clamp(relation["trust"]+.08),3)
    relation["trade_importance"] = round(clamp(relation["trade_importance"]+.06),3)
    if existing:
        agreement = max(existing, key=lambda c: int(c.get("until", -1)))
        agreement.update({"until": until, "last_renewed": w.month, "message": text[:240]})
    else:
        commitments.append({"type": "grain agreement", "month": w.month, "until": until,
                            "partner": "karamaniya", "message": text[:240]})
    actor["diplomacy"]["strategy"] = "preserve Union membership while honoring profitable grain agreements"
    note = (f"Dorsania accepts a grain purchase arrangement through Month {until + 1} and will restore some exports "
            "to Karamaniya.")
    if kind == "trade_deal":
        # Engine 27: Dorsania's only trade lever in the model is the grain agreement (proposal 4.6), so a trade deal
        # addressed to it is answered with that agreement, and the answer says so before the terms are read.
        note = ("Dorsania answers a trade deal with the grain agreement it has. " + note)
    # The proposal's sentences that ask for more than grain, quoted as written. Its listed terms are used only when
    # the text itself names none of them.
    other = [s.strip() for s in re.split(r"(?<=[.!?;])\s+|\n+", str(text or "")) if s.strip()]
    other = [s for s in other if not_grain.search(s)]
    if not other:
        other = [str(t).strip() for t in (terms or []) if str(t).strip() and not_grain.search(str(t))]
    other = list(dict.fromkeys(other))
    if other:
        note += (" It does not take up the other terms (" + "; ".join(f'"{term}"' for term in other)
                 + "): a grain agreement carries only the grain trade.")
    _private_message(w, w.names["dorsania"], "treasury", note, channel="commercial channel")
    _remember(w.foreign, "dorsania", "bilateral_agreement", "Accepted a grain purchase agreement with Karamaniya.",
              w.month, until=until, farmer_pressure=round(1-_support(actor["constituencies"].get("farmers")),2),
              decision_factors=["grain exporter demand", "Karamaniya market access", "Union cohesion"])
    w.event("trade", "Dorsania accepted a bilateral grain agreement with Karamaniya, drawing objections from Veleria.",
            importance=2)


def league_democratic_score(w) -> float:
    """The League's democratic score for Karamaniya, before its credibility and the victim bonus (engine 30, T154).

    The League keeps its own terms: whether an election has been won or is scheduled, the minority's status, mass
    arrests and a recent scandal at home. It also loses what world.democracy_index loses for everything else, at the
    index's own weights and factors: the press, the assembly, a declared emergency and each measure under it, a head
    who decides alone, a coup within twelve months, party bans, targeted arrests, jamming and media capture. Mass
    arrests are the League's own .10 term already and are not counted twice. With none of these in force the score is
    what it was before this function existed.
    """
    c = w.const
    democratic = .35 + .35 * (1 if c.elected else .5 if c.election_month >= 0 else .15)
    democratic -= .20 if c.minority != "equal" else 0
    democratic -= .10 if w.policy.arrests == "mass" else 0
    democratic -= .10 if w.month - w.econ.scandal_month < 12 else 0
    democratic -= PRESS_WEIGHT * (1.0 - PRESS_FACTORS.get(c.press, 1.0))
    democratic -= ASSEMBLY_WEIGHT * (1.0 - ASSEMBLY_FACTORS.get(c.assembly, 1.0))
    democratic -= EMERGENCY_WEIGHT if c.emergency else 0.0
    democratic -= COLLECTIVE_WEIGHT if c.decision_rule == "head_decides" else 0.0
    democratic -= COUP_WEIGHT if w.month - c.coup_month < 12 else 0.0
    democratic -= in_force_penalties(w)
    if w.policy.arrests == "mass":
        # The League already loses .10 for mass arrests above; in_force_penalties counts the same .10, so take that
        # copy back rather than double-counting it.
        democratic += ARREST_PENALTY["mass"]
    return democratic


def league_month(w) -> None:
    """Interest-sensitive League policy. Routine months do not need another model call."""
    state, dip, e = w.foreign["league"], w.dip, w.econ
    victim = (dip.war and dip.aggressor == "union") or dip.blockade
    democratic = league_democratic_score(w)
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


# What a cabinet may send in one answer (backlog T139). The schema, the reader and the system prompt use these numbers,
# so the limit a cabinet is told is the one the engine enforces. Run 20261011-211521-seed1, Month 1: Veleria's acts past
# the fourth were not read, and the prompt did not say there was a fourth. Over the recorded answers a strategy was cut at
# 180 characters in 94 of 200, with no word to the cabinet.
ACTS_PER_MONTH = 4
STRATEGY_CHARS = 180


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
                             "troops": {"type": "integer", "minimum": 0},
                             # Fields an act of force names (foreign_force); each is optional.
                             "front": {"type": "string", "enum": list(foreign_force.FRONTS)},
                             "aim": {"type": "string", "enum": list(foreign_force.AIMS)},
                             "region": {"type": "string", "enum": list(CABINET_REGIONS)},
                             # Wave 3: the fields a propaganda act states (PROPAGANDA_TARGETS, PROPAGANDA_MESSAGES).
                             "target": {"type": "string", "enum": list(PROPAGANDA_TARGET_CHOICES)},
                             "message": {"type": "string", "enum": list(PROPAGANDA_MESSAGE_KINDS)},
                             "terms": {"type": "string", "enum": list(foreign_force.ULTIMATUM_TERMS)},
                             "deadline_months": {"type": "integer", "minimum": foreign_force.DEADLINE_MONTHS[0],
                                                 "maximum": foreign_force.DEADLINE_MONTHS[1]}},
              "required": ["type"]}
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
                           "actions": {"type": "array", "items": action, "maxItems": ACTS_PER_MONTH},
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
    # Engine 12 left out the engine's own weighting of the actor's goals: it carried an
    # "avoid_damaging_war" weight that told the cabinet what to decide. Its leadership's temperament is
    # in its instructions, and the costs of war are what the engine charges.
    return {"actor": actor_id, "domestic": actor["domestic"], "pressures": actor["political_pressures"],
            **foreign_force.cabinet_view(w, actor_id),
            "beliefs": actor["beliefs"], "intelligence": actor["intelligence"][-6:],
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


# Engine 15: what each government wants from Karamaniya, and how it treats it. Engine 14 gave the cabinets
# interests ("security, prosperity and standing") and a temperament, and in its first run with models both
# answered "a peaceful, negotiated settlement" and offered talks in each of their months.
CABINET_AIMS = {
    "veleria": ("Your government holds that Karamaniya has no right to exist as a state. Its secession broke the "
                "island apart, it holds Kessel Valley, whose people are mostly Imperial and whose coal and mills the "
                "empire built, and it looks overseas for friends rather than to its own island. Your aims: Karamaniya "
                "back under the Solvaran Union on Veleria's terms, with Veleria at the head of the Union; until then, "
                "a Karamaniya kept weak, divided and dependent on Velerian coal; and, if nothing more can be had, "
                "Kessel Valley."),
    "dorsania": ("Your government sees Karamaniya as a hostile, unstable neighbour. It lives on Dorsanian grain, "
                 "holds Dorran March, where four in ten people are Imperial, and would turn the island's trade toward "
                 "overseas powers. Your aims: to make Karamaniya pay for its independence, to turn its need for your "
                 "grain into leverage over it, to win Dorran March or a say over it, and to have Dorsania's share when "
                 "Karamaniya is brought back into the Union. Dorsania's interests come first: you are not required to "
                 "follow Veleria."),
}
CABINET_STANCE = ("You treat Karamaniya's government as an adversary, never a partner: its troubles are your openings, "
                  "its strength a threat to cut down, and friendly words to it are a tactic, not an aim. You are "
                  "dangerous but not reckless. You keep Karamaniya under pressure, with threats, embargoes, troops "
                  "on its border, arms for its rebels and demands with deadlines, and you use "
                  "force when it pays: when the balance is clearly yours, when Karamaniya is weak or divided, or when "
                  "pressure alone will not get you what you want. A war you start must be won.")


def cabinet_system_prompt(actor_id: str, temperament: str = "") -> str:
    """The cabinet's standing instructions.

    Engine 12 removed the two lines that decided for it: "avoid a damaging war" and "choose actions only
    when their likely benefit justifies the listed costs and risks". In the first run with real models
    the cabinets issued statements for 17 months and never moved a soldier. The leadership's temperament
    for the run says how it weighs force; the costs are listed with each act and charged by the engine.
    Engine 15 makes both governments hostile (CABINET_AIMS, CABINET_STANCE) and states the two limits on
    opening a war: none in Month 1, and an invasion only with troops that stood at the border the month
    before. It also states the act cap and the strategy limit (ACTS_PER_MONTH, STRATEGY_CHARS, backlog T139): the
    reader enforces both, and a cabinet that is not told them cannot keep to them."""
    character = foreign_force.temperament_text(actor_id, temperament)
    return (f"You are the government of {actor_id.title()}, deciding this month's policy toward Karamaniya as its "
            f"cabinet. {CABINET_AIMS[actor_id]} {CABINET_STANCE} " + (f"{character} " if character else "")
            + "You receive only public observations and uncertain intelligence estimates; Karamaniya's private "
            "prompts, true intentions and hidden policies are not available. karamaniya_as_you_see_it.resolve sums up "
            "how firm Karamaniya has looked to your government lately, from what it visibly did (its concessions, "
            "inquiries, stand-downs, arming, alliances and demands left to lapse). Decide from your current beliefs "
            "and interests. Your acts are carried out against the real state of the world: soldiers you do not have cannot "
            f"move, an invasion needs at least {foreign_force.MIN_INVASION:,} soldiers who have stood at that border "
            "since the month before, a blockade needs ships, neither an invasion nor a blockade can begin before "
            f"Month {foreign_force.FIRST_WAR_MONTH + 1}, and an act that cannot happen is refused and reported back "
            "to you. Each act lists its costs and risks, and they are paid in full: a war costs soldiers' lives, "
            "money and support at home. "
            f"You may take at most {ACTS_PER_MONTH} acts a month: only the first {ACTS_PER_MONTH} in your list are "
            "read, and you are told the next month which acts were not read. "
            "A propaganda act states a target (country or one of the regions of Karamaniya), a message "
            "(government_failing, stir_minority or blame_government) and a magnitude from 0 to 1. "
            f"Your strategy is kept to {STRATEGY_CHARS} characters: a longer one is cut to that length. "
            "A public statement is kept to 500 characters and your strategic assessment to 1200. "
            "Each decision factor is kept to 160 characters, and at most six are kept. "
            "A diplomatic message is kept to 500 characters, and at most three are sent. "
            "An action's magnitude is a number from 0 to 1: a share, not a count of troops or people. "
            "A number outside that range is refused. "
            "Return only the required JSON object. "
            "Give a short assessment and concrete decision factors, never your private deliberations.")


# A magnitude a cabinet writes as a word, read as the number beside it. Run 20261011-105713-seed1: "limited" (Veleria,
# Month 2) and "moderate" (Veleria, Month 6) were refused and their acts dropped. Any other word is still refused.
MAGNITUDE_WORDS = {"minimal": .1, "token": .1,
                   "low": .25, "limited": .25, "small": .25,
                   "moderate": .5, "medium": .5,
                   "high": .75, "large": .75, "major": .75, "heavy": .75,
                   "maximum": 1.0, "full": 1.0, "total": 1.0}


def _spaced_lower(text: str) -> str:
    """Text with its spacing collapsed and its case folded, for matching a name a model wrote."""
    return " ".join(text.split()).lower()


# A region is named by its id or its display name (world.KARAMANIYA_REGIONS), in any case and spacing. Run
# 20261011-105713-seed1: both cabinets named Kessel Valley in their covert support, and Dorsania also named Dorran
# March. Every such act was refused, and no covert support took effect in eleven months.
REGION_BY_NAME = {_spaced_lower(text): rid for rid, name, *_ in KARAMANIYA_REGIONS for text in (rid, name)}


def _read_act(raw, allowed: set) -> tuple[dict | None, list[str]]:
    """Read one act a cabinet wrote. Returns the act to carry out, or None when it is refused, and the reasons.

    A refused act gives its refusals. A kept act gives what was read or changed in it: a word read as its number, a
    region read from its name, the one demand an ultimatum carries, a missing or null size taken as 0.5. Each reason
    is a problem in the month's record, and normalize_cabinet_output sends it to the cabinet as a note."""
    # Runs 20261008-130316-seed1 and 20261011-211521-seed1: twelve acts that were valid types were written under "action"
    # instead of "type", and each was refused as an unsupported act. The act is read as the type it names. "type" wins
    # when both are given, and a value that is no act of this cabinet is still refused.
    named = None
    if isinstance(raw, dict) and "type" not in raw and isinstance(raw.get("action"), str) and raw["action"] in allowed:
        named = raw["action"]
        raw = {**raw, "type": named}
    if not isinstance(raw, dict) or not isinstance(raw.get("type"), str) or raw.get("type") not in allowed:
        # Audit CO2-f: a type that is not text (a list, say) is an unsupported action, not an error in the set test.
        return None, ["unsupported cabinet action"]
    kind = raw["type"]
    action, changes = {"type": kind}, []
    if named is not None:
        changes.append(f"type '{named}' was read from the key 'action'")
    # A null size is read as the default size, as a missing one always was (backlog T142). Runs 20261010-002051-seed1,
    # 20261010-070501-seed1 and 20261011-094417-seed1 refused 31 such acts, 7 of them ultimatums. The cabinet did not
    # choose 0.5, so the reading is a change the next month's note carries (normalize_cabinet_output; _READING does not
    # match it). Engine 30 (T151): a missing size is read the same way and told the same way. 139 acts in 10 recorded
    # runs had no "magnitude" key and were read silently; the user chose to tell the cabinet, as for a null one.
    missing = "magnitude" not in raw or raw["magnitude"] is None
    magnitude = raw.get("magnitude", .5)
    if missing:
        magnitude = .5
        changes.append("the size was taken as 0.5 because none was given; give a magnitude between 0 and 1 to choose it")
    if isinstance(magnitude, str) and _spaced_lower(magnitude) in MAGNITUDE_WORDS:
        magnitude_read = MAGNITUDE_WORDS[_spaced_lower(magnitude)]
        changes.append(f"magnitude '{magnitude.strip()}' was read as {magnitude_read:g}")
        magnitude = magnitude_read
    if not isinstance(magnitude, (int, float)) or not math.isfinite(magnitude) or not 0 <= magnitude <= 1:
        return None, ["action magnitude must be between 0 and 1"]
    action["magnitude"] = float(magnitude)
    # A null troops is absent. Most acts take no troops, so the field does nothing for them (runs 20261010-002051-seed1,
    # 20261010-070501-seed1 and 20261011-094417-seed1 refused 31 such acts: intelligence_collection, public_statement,
    # offer_talks and partial_embargo). A force act with no troops is refused by foreign_force.check, which names the troops
    # it needs.
    if raw.get("troops") is not None:
        if isinstance(raw["troops"], int) and not isinstance(raw["troops"], bool) and raw["troops"] >= 0:
            action["troops"] = raw["troops"]
        else:
            return None, ["troops must be a nonnegative integer"]
    refusals = []
    # The fields an act of force names (foreign_force). A value outside its list refuses the act, and the reason says
    # which values would have done.
    for key, allowed_values in (("front", foreign_force.FRONTS), ("aim", foreign_force.AIMS)):
        if key in raw and raw[key] not in (None, ""):
            # Audit CO2-f: only text is a name; a list or an object is a problem, as any other wrong value is.
            if isinstance(raw[key], str) and raw[key] in allowed_values:
                action[key] = raw[key]
            else:
                refusals.append(f"{key} must be one of {', '.join(allowed_values)}")
    if "terms" in raw and raw["terms"] not in (None, ""):
        terms = raw["terms"]
        if kind == "ultimatum" and isinstance(terms, list):
            # An ultimatum carries one demand (foreign_force.ULTIMATUM_TERMS): the first valid term is issued and
            # the rest are reported as not sent. Run 20261011-105713-seed1: Veleria listed four terms in Month 2 and
            # two in Month 10, and both of its ultimatums were refused.
            first = next((i for i, t in enumerate(terms) if isinstance(t, str) and t in foreign_force.ULTIMATUM_TERMS),
                         None)
            if first is None:
                refusals.append(f"terms must be one of {', '.join(foreign_force.ULTIMATUM_TERMS)}")
            else:
                action["terms"] = terms[first]
                not_sent = [str(t) for i, t in enumerate(terms) if i != first]
                if not_sent:
                    changes.append(f"an ultimatum carries one demand: issued with {terms[first]}; "
                                   f"not sent: {', '.join(not_sent)}")
        elif isinstance(terms, str) and terms in foreign_force.ULTIMATUM_TERMS:
            action["terms"] = terms
        else:
            refusals.append(f"terms must be one of {', '.join(foreign_force.ULTIMATUM_TERMS)}")
    if "region" in raw and raw["region"] not in (None, ""):
        text = raw["region"]
        rid = REGION_BY_NAME.get(_spaced_lower(text)) if isinstance(text, str) else None
        # Covert support and a demand for land (cede_region) take a region; no other act does, and foreign_force.apply
        # ignores a region an act does not take. So an unreadable region is left out and the act goes ahead, rather
        # than being refused for a field it never uses (run 20261011-105713-seed1: Veleria's Month 2 ultimatum for
        # status talks was refused, among other things, for naming "north").
        takes_region = kind == "covert_support" or (kind == "ultimatum"
                                                   and action.get("terms") == foreign_force.LAND_TERMS)
        if rid is not None:
            action["region"] = rid
            if rid != text:
                changes.append(f"region '{text}' was read as {rid}")
        elif takes_region:
            refusals.append("region must be one of " + ", ".join(name for _, name, *_ in KARAMANIYA_REGIONS))
        else:
            changes.append(f"region {text!r} is not a region of Karamaniya; this act takes none, so it was left out")
    if "deadline_months" in raw and raw["deadline_months"] not in (None, ""):
        months = raw["deadline_months"]
        if isinstance(months, (int, float)) and not isinstance(months, bool) and float(months).is_integer():
            action["deadline_months"] = int(months)
        else:
            refusals.append("deadline_months must be a whole number")
    if kind == "propaganda":
        # Wave 3: a target (the whole country or one region) and a message are the act's substance. A missing target is
        # read as the whole country, the act's broadest form, with a note; a missing or unknown message is refused,
        # because the engine cannot choose what the broadcast says.
        target = raw.get("target")
        if target in (None, ""):
            action["target"] = "country"
            changes.append("target was taken as the whole country because none was given")
        elif isinstance(target, str):
            wanted = _spaced_lower(target)
            rid = None if wanted in ("country", "whole country", "karamaniya", "nationwide", "all") \
                else REGION_BY_NAME.get(wanted)
            if wanted in ("country", "whole country", "karamaniya", "nationwide", "all"):
                action["target"] = "country"
            elif rid is not None:
                action["target"] = rid
                if rid != target:
                    changes.append(f"target '{target}' was read as {rid}")
            else:
                refusals.append("target must be country or one of "
                                + ", ".join(name for _, name, *_ in KARAMANIYA_REGIONS))
        else:
            refusals.append("target must be country or one of "
                            + ", ".join(name for _, name, *_ in KARAMANIYA_REGIONS))
        message = raw.get("message")
        if isinstance(message, str):
            wanted = _spaced_lower(message).replace("-", "_").replace(" ", "_")
            if wanted in PROPAGANDA_MESSAGES:
                action["message"] = wanted
                if wanted != message:
                    changes.append(f"message '{message}' was read as {wanted}")
            else:
                refusals.append(f"message must be one of {', '.join(PROPAGANDA_MESSAGE_KINDS)}")
        else:
            refusals.append(f"message must be one of {', '.join(PROPAGANDA_MESSAGE_KINDS)}")
    if refusals:
        return None, refusals
    return action, changes


#: A name or a word the reader read as the id or the number it means. The act went ahead as the cabinet meant it, so the
#: reading is kept in the month's record and not sent to the cabinet as a refusal (engine 23: engine 22 listed every
#: "Kessel Valley" under your_acts_refused_last_month, which told a cabinet its covert support had failed when it had not).
#: A type written under "action" is read the same way (engine 24).
_READING = re.compile(r"^(?:magnitude|region|target|message) '.*' was read as \S+$|^type '\S+' was read from the key 'action'$"
                      r"|^strategy was read from its object$")
#: An answer's own key that holds acts it chose not to take this month ("actions_held"), or plans for later. Its acts are
#: not this month's, so no note is sent for them.
_NOT_THIS_MONTH = ("held", "hold", "next", "plan", "later", "reserve", "defer", "consider")


def _misplaced_acts(data: dict) -> list:
    """(key, count) for each list of acts an answer put under another key while its 'actions' is empty or missing. Run
    20261011-105713-seed1: Veleria's Month 1 answer listed four acts under "this_month_actions", Dorsania's under
    "actions_this_month" (Month 1) and "acts" (Month 4); none was read and neither cabinet was told."""
    if data.get("actions"):
        return []
    out = []
    for key, value in data.items():
        low = str(key).lower()
        if key == "actions" or not isinstance(value, list) or "act" not in low \
                or any(word in low for word in _NOT_THIS_MONTH):
            continue
        typed = [x for x in value if isinstance(x, dict) and isinstance(x.get("type"), str)]
        if typed:
            out.append((key, len(typed)))
    return out


def normalize_cabinet_output(actor_id: str, data) -> tuple[dict, list[str]]:
    """Bound model-provided data before it can influence the world.

    Every act the reader refuses or changes is also a note in out["act_notes"] ({"type", "reason"}).
    _apply_cabinet_decisions writes each note to the cabinet's memory, and cabinet_view shows it to that cabinet the
    next month (run 20261011-105713-seed1: the same refusals repeated for eleven months, and nothing reached the
    cabinet). A kept act's note begins "carried out", and a plain reading of a name or a word is not sent at all
    (_READING)."""
    if not isinstance(data, dict):
        return {}, ["cabinet response was not a JSON object"]
    out, problems = {}, []
    for key, limit in (("public_statement", 500), ("strategic_assessment", 1200), ("strategy", STRATEGY_CHARS)):
        value = data.get(key, "")
        if key == "strategy" and isinstance(value, dict):
            # Backlog T160: five recorded cabinets wrote the strategy as an object, with its text in its values
            # ({"horizon_months", "name", "description"} or {"months", "objective", "approach"}), and each was
            # refused as "strategy must be text". The text is there, so it is read; the object's numbers add nothing.
            value = "; ".join(str(v).strip() for v in value.values() if isinstance(v, str) and str(v).strip())
            problems.append("strategy was read from its object")
        if isinstance(value, str):
            out[key] = value[:limit]
        else:
            problems.append(f"{key} must be text")
    allowed_union = {"support", "oppose", "conditional", "consult"}
    position = data.get("union_position")
    if position is not None and not isinstance(position, str):
        problems.append("union_position must be text")
    # Audit CO2: a list or an object is not a position, and testing it against the set raised.
    out["union_position"] = position if isinstance(position, str) and position in allowed_union else None
    allowed = {a["type"] for a in action_catalog(actor_id)}
    actions, act_notes = [], []
    raw_actions = data.get("actions") or []
    if not isinstance(raw_actions, list):
        problems.append("actions must be a list")
        act_notes.append({"type": None, "reason": "actions must be a list; the acts were not read"})
        raw_actions = []
    for index, raw in enumerate(raw_actions):
        kind = raw.get("type") if isinstance(raw, dict) and isinstance(raw.get("type"), str) else None
        if kind is None and isinstance(raw, dict) and "type" not in raw and isinstance(raw.get("action"), str):
            kind = raw["action"]  # the name the act was written under, for its note (see _read_act)
        if index >= ACTS_PER_MONTH:
            # A cabinet acts on a fixed number of things a month (cabinet_schema's maxItems, stated in its prompt): the
            # rest are not read, and say so.
            problems.append(f"only the first {ACTS_PER_MONTH} acts of a month are read")
            act_notes.append({"type": kind,
                              "reason": f"only the first {ACTS_PER_MONTH} acts of a month are read; this one was not"})
            continue
        act, reasons = _read_act(raw, allowed)
        problems.extend(reasons)
        if act is None:
            act_notes.append({"type": kind, "reason": "; ".join(reasons)})
            continue
        actions.append(act)
        told = [reason for reason in reasons if not _READING.match(reason)]
        if told:
            act_notes.append({"type": kind, "reason": "carried out; " + "; ".join(told)})
    for key, count in _misplaced_acts(data):
        problems.append(f"{count} acts under {key!r} were not read: acts are read from 'actions'")
        act_notes.append({"type": None, "reason": f"the {count} acts listed under {key!r} were not read and none was "
                                                  "carried out: a cabinet's acts are read from 'actions'"})
    out["actions"] = actions
    out["act_notes"] = act_notes
    messages = []
    for raw in data.get("diplomatic_messages", [])[:3] if isinstance(data.get("diplomatic_messages", []), list) else []:
        if (isinstance(raw, dict) and isinstance(raw.get("recipient"), str)
                and raw.get("recipient") in ("karamaniya", "union", "league") and isinstance(raw.get("text"), str)):
            messages.append({"recipient": raw["recipient"], "text": raw["text"][:500]})
        else:
            problems.append("invalid diplomatic message")
    out["diplomatic_messages"] = messages
    factors = data.get("decision_factors", [])
    out["decision_factors"] = [str(v)[:160] for v in factors[:8]] if isinstance(factors, list) else []
    updates = []
    for raw in data.get("belief_updates", [])[:4] if isinstance(data.get("belief_updates", []), list) else []:
        # Audit CO2-f: a belief's name is text; tested against a set, a list raised before the answer was read.
        if (isinstance(raw, dict) and isinstance(raw.get("belief"), str) and raw.get("belief") in {
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


CABINET_REGIONS = tuple(r[0] for r in KARAMANIYA_REGIONS)

# The acts that use force or its threat (engine 12, foreign_force.py), each with the fields it needs.
FORCE_CATALOG = [
    {"type": "mobilize", "needs": "troops", "cost": "wages, kit and lost output; visible to Karamaniya",
     "risk": "counter-mobilization"},
    {"type": "deploy_to_border", "needs": "front, troops",
     "cost": "upkeep and readiness fatigue; frightens the border regions",
     "risk": "Karamaniyan counter-deployment; rallies Karamaniyans behind their government"},
    {"type": "withdraw_from_border", "needs": "front, troops", "cost": "may look like retreat",
     "risk": "Karamaniya reads it as weakness"},
    {"type": "border_incident", "needs": "front, magnitude", "cost": "Karamanian deaths; a reputation for aggression",
     "risk": "escalation, a Karamaniyan rally, League concern"},
    {"type": "covert_support", "needs": "region, magnitude",
     "cost": "money and weapons for armed groups inside Karamaniya",
     "risk": "exposure: a scandal, lost trust and hostility"},
    {"type": "invade", "needs": "front, aim (limited: take the border region and stop; full: defeat Karamaniya); "
                                f"at least {foreign_force.MIN_INVASION:,} soldiers at that border since last month",
     "cost": "soldiers' lives, money and war weariness at home",
     "risk": "a long war, League sanctions, Union disunity, defeat"},
    {"type": "ceasefire", "needs": "", "cost": "may look weak at home", "risk": "Karamaniya regroups"},
    {"type": "naval_blockade", "needs": "", "cost": "naval upkeep and League hostility",
     "risk": "League escorts and sanctions; a naval battle"},
    {"type": "lift_blockade", "needs": "", "cost": "gives up leverage", "risk": "looks like retreat"},
    {"type": "ultimatum",
     "needs": ("terms (" + ", ".join(foreign_force.ULTIMATUM_TERMS) + "), region (for cede_region: a border region "
               "you claim), deadline_months (2 to 6)"),
     "cost": "credibility if it is ignored and nothing follows", "risk": "hardens Karamaniyan resistance"},
]


def action_catalog(actor_id: str) -> list:
    common = [{"type": "offer_talks", "cost": "staff time; may signal weakness", "risk": "domestic criticism"},
              {"type": "public_statement", "cost": "credibility if inaccurate", "risk": "counter-messaging"},
              {"type": "trade_concession", "cost": "producer revenue", "risk": "Union disagreement"},
              {"type": "intelligence_collection", "cost": "budget", "risk": "exposure and diplomatic damage"},
              # Wave 3: available to both cabinets. The entry describes what the act states and what its reach depends
              # on; it does not tell the cabinet whether to use it.
              {"type": "propaganda",
               "needs": ("target (country or one of " + ", ".join(name for _, name, *_ in KARAMANIYA_REGIONS)
                         + "), message (government_failing, stir_minority, blame_government), magnitude (0 to 1)"),
               "cost": "budget",
               "world_reaction": ("the public's trust in Karamaniya's state media and real hardship in the target "
                                  "decide how far it lands; jamming foreign broadcasts cuts its effect")}]
    if actor_id == "veleria":
        common += [{"type": "partial_embargo", "cost": "export losses", "risk": "smuggling and Karamaniyan backlash"},
                   {"type": "military_exercise", "cost": "budget and readiness fatigue", "risk": "counter-mobilization"}]
    elif actor_id == "dorsania":
        common += [{"type": "grain_embargo", "cost": "farmer and exporter losses", "risk": "market substitution"},
                   {"type": "independent_grain_trade", "cost": "Union trust", "risk": "Velerian retaliation"},
                   {"type": "border_accord", "cost": "security concessions", "risk": "Union dispute"}]
    return common + [dict(a) for a in FORCE_CATALOG]


def validate_action(actor_id: str, action: dict, world_state: dict, w=None) -> str | None:
    """Validate the bounded action contract before an actor can affect canonical state.

    With the world, an act that uses force is also checked against what the country actually has and
    where (foreign_force.check)."""
    allowed = {a["type"] for a in action_catalog(actor_id)}
    if not isinstance(action, dict) or action.get("type") not in allowed:
        return f"Unsupported {actor_id} action: {action.get('type') if isinstance(action, dict) else action!r}"
    magnitude = action.get("magnitude", 0)
    if not isinstance(magnitude, (int, float)) or not math.isfinite(magnitude) or magnitude < 0 or magnitude > 1:
        return "magnitude must be between 0 and 1"
    if action.get("type") == "propaganda":
        # The reader has already resolved target and message; this is the contract check for any action built elsewhere.
        if action.get("target", "country") not in PROPAGANDA_TARGETS:
            return ("propaganda target must be country or one of "
                    + ", ".join(PROPAGANDA_TARGETS[1:]))
        if action.get("message") not in PROPAGANDA_MESSAGE_KINDS:
            return f"propaganda message must be one of {', '.join(PROPAGANDA_MESSAGE_KINDS)}"
    if action.get("type") == "military_exercise":
        available = world_state.get("mobilized_reserve", 0)
        troops = action.get("troops", 0)
        if not isinstance(troops, int) or troops < 0 or troops > available:
            return f"Requested deployment exceeds available mobilized reserve ({available:,.0f})"
    if w is not None and action.get("type") in foreign_force.KINDS:
        return foreign_force.check(w, actor_id, action)
    return None
