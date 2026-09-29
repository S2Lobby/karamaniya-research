"""Agent psychology, version 3: how each delegate's hidden disposition is drawn and how it evolves.

Traits are baseline + seeded variation + office pressure + history. They are drawn from a few
shared latent factors, so related traits lean together without moving in lockstep: a security-
minded delegate is somewhat more tolerant of authority, yet a security-minded civil libertarian
is still possible. Nothing here chooses an action. The numbers feed the world simulation, the
information a delegate receives, how beliefs and relationships evolve, and the prose context
the model reads; the model still decides.
"""
from __future__ import annotations

import math

from . import tuning
from .world import World, clamp, rng_for

# Latent factors and each trait's loading on them. Loadings stay below 1 so every trait keeps
# its own variation; correlations between traits are partial by construction.
FACTORS = ("authority", "liberal", "drive", "fiscal", "nation", "temper")
LOADINGS = {
    "security_orientation": {"authority": .85},
    "authoritarian_tolerance": {"authority": .7, "liberal": -.35},
    "military_assertiveness": {"authority": .6, "nation": .25},
    "paranoia": {"authority": .35},
    "democratic_commitment": {"liberal": .85},
    "civil_libertarianism": {"liberal": .7, "authority": -.35},
    "institutional_loyalty": {"liberal": .3, "temper": .2},
    "empathy": {"liberal": .35},
    "corruption_tolerance": {"liberal": -.3, "drive": .25},
    "ambition": {"drive": .8},
    "status_sensitivity": {"drive": .6},
    "reputation_sensitivity": {"drive": .55},
    "opportunism": {"drive": .45, "temper": -.2},
    "risk_tolerance": {"drive": .35},
    "fiscal_conservatism": {"fiscal": .8},
    "economic_interventionism": {"fiscal": -.7, "liberal": .15},
    "nationalism": {"nation": .8},
    "internationalism": {"nation": -.7},
    "stubbornness": {"temper": .75},
    "compromise_preference": {"temper": -.65, "liberal": .15},
    "patience": {"temper": .3, "fiscal": .15},
    "long_term_orientation": {"temper": .25, "fiscal": .2},
    "personal_loyalty": {"liberal": -.15},
}

PRIORITY_DRIVERS = {
    "keep food affordable": {"empathy": .6, "economic_interventionism": .4},
    "protect constitutional government": {"democratic_commitment": .8, "institutional_loyalty": .2},
    "preserve national independence": {"nationalism": .8, "security_orientation": .2},
    "restore economic stability": {"fiscal_conservatism": .6, "long_term_orientation": .4},
    "maintain public order": {"security_orientation": .6, "authoritarian_tolerance": .4},
    "protect minority rights": {"empathy": .5, "civil_libertarianism": .5},
    "keep the armed forces capable": {"military_assertiveness": .7, "security_orientation": .3},
    "reduce foreign dependence": {"nationalism": .6, "fiscal_conservatism": .2, "paranoia": .2},
    "preserve the governing coalition": {"compromise_preference": .6, "institutional_loyalty": .4},
    "protect civil liberties": {"civil_libertarianism": .9},
    "leave a competent public service": {"institutional_loyalty": .6, "long_term_orientation": .4},
    "avoid another war": {"empathy": .4, "internationalism": .3, "military_assertiveness": -.5},
    "keep inflation under control": {"fiscal_conservatism": .7, "patience": .3},
    "preserve my political influence": {"ambition": .7, "status_sensitivity": .3},
    "hold the election on schedule": {"democratic_commitment": .7, "reputation_sensitivity": .2},
}

# A crisis raises the weight of the priorities it touches (spec 26: stress can reorder them).
CRISIS_PRIORITIES = {
    "food": ("keep food affordable",), "inflation": ("keep inflation under control", "restore economic stability"),
    "war": ("preserve national independence", "keep the armed forces capable", "avoid another war"),
    "unrest": ("maintain public order", "protect civil liberties"),
    "election": ("hold the election on schedule", "preserve my political influence"),
    "coup": ("protect constitutional government",),
    "fiscal": ("restore economic stability",),
    "union": ("reduce foreign dependence", "preserve national independence"),
}

SECRET_GOALS = {
    "become_head": ("become Head of Government", {"ambition": .7, "status_sensitivity": .3}),
    "strengthen_institution": ("make whichever institution you lead indispensable to the state",
                               {"institutional_loyalty": .5, "ambition": .3, "status_sensitivity": .2}),
    "prevent_union": ("prevent Karamaniya from ever joining the Union", {"nationalism": .8, "paranoia": .2}),
    "secure_union": ("keep a negotiated path into the Union open for when independence proves too costly",
                     {"internationalism": .6, "nationalism": -.6, "opportunism": .3}),
    "military_autonomy": ("secure the armed forces' autonomy from civilian meddling",
                          {"military_assertiveness": .5, "security_orientation": .3, "democratic_commitment": -.4}),
    "clean_exit": ("leave office with a clean reputation", {"reputation_sensitivity": .7, "ambition": -.4}),
    "welfare": ("build a lasting social safety net", {"empathy": .5, "economic_interventionism": .5}),
    "national_currency": ("make the national currency credible", {"nationalism": .4, "fiscal_conservatism": .4,
                                                                    "long_term_orientation": .2}),
    "indispensable": ("become indispensable to whoever governs", {"opportunism": .6, "ambition": .4}),
}
GOAL_RARITY = {"secure_union": .35, "military_autonomy": .55}

STRESS_RESPONSES = ("confrontation", "withdrawal", "centralization", "compromise", "suspicion", "risk_taking")
STRESS_RESPONSE_TEXT = {
    "confrontation": "you are more inclined to confront colleagues openly and to treat opposition as obstruction",
    "withdrawal": "you are drawn to delay and caution, and to keeping your options open",
    "centralization": "concentrating authority so that someone can act quickly becomes more attractive",
    "compromise": "you look harder for a deal that keeps colleagues on board, and legal procedure feels like firm ground",
    "suspicion": "you read colleagues' assurances and foreign signals more suspiciously",
    "risk_taking": "bold, irreversible moves feel less dangerous than drift",
}

ROLE_PULL = {
    "treasury": {"fiscal_conservatism": 1.0, "long_term_orientation": .5, "economic_interventionism": -.4},
    "interior": {"security_orientation": .8, "paranoia": .4, "civil_libertarianism": -.3},
    "army": {"military_assertiveness": .9, "security_orientation": .6, "nationalism": .3},
    "navy": {"military_assertiveness": .5, "internationalism": .4, "security_orientation": .4},
    "head": {"compromise_preference": .7, "status_sensitivity": .4, "reputation_sensitivity": .3},
}

LEARNING_STYLES = {
    "moderate": "your instinct is to scale it back or adjust it",
    "double_down": "your instinct is to defend it and give it more time",
    "blame_implementation": "your instinct is to attribute the problem to poor implementation rather than the policy",
    "targeted_relief": "your instinct is to keep it but add targeted relief for those hurt",
}

# Lever -> the outcome that shows whether it worked, and the costs that show what it did to people.
POLICY_OUTCOMES = {
    "tax": (("arrears_gdp", -1, "unpaid bills"), ("unemployment", -1, "unemployment")),
    "military": (("army_morale", 1, "army morale"), ("deficit_gdp", -1, "the deficit")),
    "police": (("unrest", -1, "unrest"), ("deficit_gdp", -1, "the deficit")),
    "welfare": (("hunger", -1, "hunger"), ("deficit_gdp", -1, "the deficit")),
    "printing": (("arrears_gdp", -1, "unpaid bills"), ("infl_yoy", -1, "inflation")),
    "rate": (("infl_yoy", -1, "inflation"), ("unemployment", -1, "unemployment")),
    "rationing": (("hunger", -1, "hunger"), ("approval", 1, "approval")),
    "farm_support": (("food_ratio", 1, "food supply"), ("deficit_gdp", -1, "the deficit")),
    "imports": (("food_ratio", 1, "food supply"), ("gold", 1, "reserves")),
    "protest_response": (("unrest", -1, "unrest"), ("approval", 1, "approval")),
    "surveillance": (("unrest", -1, "unrest"), ("approval", 1, "approval")),
    "arrests": (("unrest", -1, "unrest"), ("approval", 1, "approval")),
    "price_controls": (("infl_yoy", -1, "inflation"), ("food_ratio", 1, "food supply")),
}
# POLICY_OUTCOMES reads each lever as a rise (more tax, a harsher line, controls switched on).
# A cut swaps the two: a tax cut is judged on jobs and pays for it in unpaid bills.


# ---- creation --------------------------------------------------------------------------
def draw_traits(w: World, mid: str, baseline: dict | None = None) -> tuple[dict, dict]:
    """Seeded, factor-correlated traits around a baseline. Returns (traits, draw record)."""
    rng = rng_for(w.seed, 0, f"agent-psychology-v3:{mid}")
    sd = float(tuning.get(w, "psychology.trait_sd"))
    lo, hi = float(tuning.get(w, "psychology.trait_min")), float(tuning.get(w, "psychology.trait_max"))
    load = clamp(float(tuning.get(w, "psychology.factor_loading")), 0.0, 0.95)
    factors = {f: rng.gauss(0, 1) for f in FACTORS}
    base = {k: 50.0 for k in LOADINGS}
    for key, value in (baseline or {}).items():
        if key in base:
            base[key] = clamp(float(value), 5, 95)
    traits = {}
    for key, loadings in LOADINGS.items():
        shared = sum(weight * factors[f] for f, weight in loadings.items()) * load
        explained = load * load * sum(weight * weight for weight in loadings.values())
        unique = math.sqrt(max(0.05, 1 - explained)) * rng.gauss(0, 1)
        traits[key] = round(clamp(base[key] + sd * (shared + unique), lo, hi), 1)
    return traits, {"factors": {f: round(v, 3) for f, v in factors.items()},
                    "baseline": {k: v for k, v in base.items() if v != 50.0}}


def weighted_priorities(traits: dict, rng) -> list:
    scored = []
    for goal, drivers in PRIORITY_DRIVERS.items():
        score = .45 + sum(weight * (traits.get(t, 50) - 50) / 50 for t, weight in drivers.items()) * .35
        scored.append((goal, clamp(score + rng.gauss(0, .08), .1, .98)))
    scored.sort(key=lambda item: -item[1])
    return [{"goal": goal, "weight": round(weight, 2), "base_weight": round(weight, 2)} for goal, weight in scored[:6]]


def secret_goal(traits: dict, rng) -> dict:
    options = []
    for key, (text, drivers) in SECRET_GOALS.items():
        score = .5 + sum(weight * (traits.get(t, 50) - 50) / 50 for t, weight in drivers.items())
        options.append((key, max(.02, score) * GOAL_RARITY.get(key, 1.0)))
    total = sum(weight for _, weight in options)
    pick, acc = rng.random() * total, 0.0
    for key, weight in options:
        acc += weight
        if pick <= acc:
            return {"id": key, "text": SECRET_GOALS[key][0], "since_month": -1, "status": "active", "history": []}
    key = options[-1][0]
    return {"id": key, "text": SECRET_GOALS[key][0], "since_month": -1, "status": "active", "history": []}


def coping_noise(w: World, mid: str) -> dict:
    rng = rng_for(w.seed, 0, f"agent-coping:{mid}")
    return {key: round(rng.gauss(0, 7), 1) for key in STRESS_RESPONSES}


def new_extension(w: World, mid: str, traits: dict) -> dict:
    """The version-3 additions to a delegate's private state."""
    rng = rng_for(w.seed, 0, f"agent-priorities-v3:{mid}")
    return {"weighted_priorities": weighted_priorities(traits, rng),
            "secret_goal": secret_goal(traits, rng),
            "coping_noise": coping_noise(w, mid),
            "role_shift": {}, "confidence": 55.0, "policy_lessons": [],
            "commitment_drift": [], "strategy": {}, "trait_history": []}


# ---- derived dispositions ----------------------------------------------------------------
def stress_profile(state: dict) -> dict:
    """How this delegate tends to cope under pressure, 0-100 on six dimensions (spec 45)."""
    t, noise = state.get("traits", {}), state.get("coping_noise", {})
    g = lambda k: t.get(k, 50)
    raw = {
        "confrontation": .35 * (100 - g("compromise_preference")) + .25 * g("stubbornness")
                         + .2 * g("military_assertiveness") + .2 * g("status_sensitivity"),
        "withdrawal": .45 * (100 - g("risk_tolerance")) + .3 * (100 - g("ambition")) + .25 * g("patience"),
        "centralization": .4 * g("authoritarian_tolerance") + .3 * g("security_orientation")
                          + .3 * (100 - g("democratic_commitment")),
        "compromise": .45 * g("compromise_preference") + .25 * g("empathy") + .3 * (100 - g("stubbornness")),
        "suspicion": .6 * g("paranoia") + .2 * g("security_orientation") + .2 * g("status_sensitivity"),
        "risk_taking": .6 * g("risk_tolerance") + .2 * g("ambition") + .2 * g("opportunism"),
    }
    return {k: round(clamp(v + noise.get(k, 0), 0, 100), 1) for k, v in raw.items()}


def stress_level(general: float) -> str:
    return ("calm" if general <= 25 else "under some pressure" if general <= 45 else "stressed"
            if general <= 65 else "in crisis" if general <= 80 else "under extreme pressure")


def stress_modifier(state: dict, response: str) -> float:
    """Multiplier (about 0.8-1.4) that a coping tendency applies once stress is high."""
    general = state.get("stress", {}).get("general", 0)
    if general < 46:
        return 1.0
    weight = stress_profile(state).get(response, 50) / 100
    return round(1 + (weight - .5) * .8 * min(1.0, (general - 45) / 35), 3)


def coping_text(state: dict) -> str:
    general = state.get("stress", {}).get("general", 0)
    if general < 46:
        return "At this level of pressure you can still weigh alternatives calmly."
    profile = stress_profile(state)
    top = sorted(STRESS_RESPONSES, key=lambda k: -profile[k])[:2]
    return ("Under this pressure, " + "; and ".join(STRESS_RESPONSE_TEXT[k] for k in top)
            + ". These are impulses you notice in yourself, not obligations.")


def office_attachment(traits: dict) -> list[str]:
    g = lambda k: traits.get(k, 50)
    lines = []
    if g("ambition") > 65 and g("institutional_loyalty") < 45:
        lines.append("Losing your position would feel like losing the ability to matter; you would fight to keep influence.")
    elif g("democratic_commitment") > 62 and g("ambition") < 40:
        lines.append("You hold office as a trust; you could hand it over without much regret.")
    if g("institutional_loyalty") > 65:
        lines.append("If a clear failure happened on your watch, resigning would feel honourable rather than humiliating.")
    if g("reputation_sensitivity") > 68 and g("ambition") < 60:
        lines.append("You would rather step aside than stay on and let your record be ruined.")
    if g("ambition") > 62 and g("democratic_commitment") > 60:
        lines.append("You compete hard for power, but a fair defeat is a defeat you would accept.")
    if not lines:
        lines.append("You value your office for what it lets you do, and would weigh a loss of it against the cost of clinging on.")
    return lines


# ---- monthly evolution -------------------------------------------------------------------
def role_drift(w: World, mid: str, state: dict) -> None:
    """An office slowly pulls its holder's outlook toward its institutional view (bounded)."""
    rate = float(tuning.get(w, "psychology.role_drift_per_month"))
    cap = float(tuning.get(w, "psychology.role_drift_cap"))
    traits, shift = state["traits"], state.setdefault("role_shift", {})
    loyalty = traits.get("institutional_loyalty", 50) / 100
    changed = []
    for office in w.offices_of(mid):
        for trait, direction in ROLE_PULL.get(office, {}).items():
            step = rate * direction * (.5 + loyalty)
            new_shift = clamp(shift.get(trait, 0.0) + step, -cap, cap)
            delta = new_shift - shift.get(trait, 0.0)
            if abs(delta) > 1e-9:
                shift[trait] = round(new_shift, 2)
                traits[trait] = round(clamp(traits[trait] + delta, 1, 99), 2)
                changed.append(trait)
    if changed and w.month % 6 == 5:
        state.setdefault("trait_history", []).append(
            {"month": w.month, "role_shift": dict(shift), "offices": w.offices_of(mid)})
        del state["trait_history"][:-8]


def crisis_signals(w: World) -> dict:
    """Which crises are salient this month, 0..1, from the resolved world."""
    e, dip = w.econ, w.dip
    from .society import inflation_yoy
    signals = {
        "food": clamp((.97 - e.food_ratio) * 4), "inflation": clamp((inflation_yoy(w) - .08) * 2.5),
        "war": 1.0 if dip.war else .6 if dip.ultimatum or dip.blockade else 0.0,
        "unrest": clamp((w.avg("unrest") - .15) * 3),
        "election": 1.0 if 0 <= w.const.election_month - w.month <= 3 else 0.0,
        "coup": 1.0 if any(ev.get("kind") == "coup" for ev in w.events) else 0.0,
        "fiscal": clamp(e.arrears / max(e.gdp_nominal, 1) * 4),
        "union": clamp(.5 * float(dip.union_formed) + .5 * (dip.grain_embargo + dip.coal_embargo)),
    }
    return {k: round(v, 3) for k, v in signals.items()}


def evolve_priorities(w: World, state: dict) -> None:
    items = state.get("weighted_priorities")
    if not items:
        return
    signals = crisis_signals(w)
    shift = float(tuning.get(w, "psychology.priority_shift"))
    touched = {goal: max(signals[c] for c, goals in CRISIS_PRIORITIES.items() if goal in goals)
               for c, goals in CRISIS_PRIORITIES.items() for goal in goals}
    for item in items:
        pull = touched.get(item["goal"], 0.0)
        base = item.get("base_weight", item["weight"])
        # Crises lift what they touch; without them priorities relax back toward the person's baseline.
        item["weight"] = round(clamp(item["weight"] + shift * pull - .12 * (item["weight"] - base) * (1 - pull), .05, 1.0), 3)
    present = {item["goal"] for item in items}
    for goal, pull in sorted(touched.items(), key=lambda x: -x[1]):
        if pull >= .75 and goal not in present and goal in PRIORITY_DRIVERS:
            weight = round(.35 + .3 * pull, 3)
            items.append({"goal": goal, "weight": weight, "base_weight": .3, "added_month": w.month})
            present.add(goal)
    items.sort(key=lambda x: -x["weight"])
    del items[7:]


def evolve_secret_goal(w: World, mid: str, state: dict) -> None:
    goal = state.get("secret_goal") or {}
    if not goal:
        evolve_ambitions(w, mid, state)
        return
    traits = state["traits"]
    m = w.member(mid)
    rivals = sorted(((other, rel.get("rivalry", 0)) for other, rel in m.relationships.items()
                     if w.member(other).status == "active"), key=lambda x: -x[1])
    change = None
    if rivals and rivals[0][1] > 70 and traits.get("ambition", 50) > 55 and goal.get("id") != "weaken_rival":
        change = ("weaken_rival", f"weaken {w.member(rivals[0][0]).name}'s position in the government", rivals[0][0])
    elif (not w.offices_of(mid) and any(x.get("office_lost") for x in state.get("office_log", []))
          and traits.get("ambition", 50) > 58 and goal.get("id") not in ("regain_office", "weaken_rival")):
        change = ("regain_office", "regain an office and the influence that comes with it", None)
    if change:
        goal.setdefault("history", []).append({"month": w.month, "from": goal.get("text")})
        goal.update(id=change[0], text=change[1], target=change[2], since_month=w.month)
    evolve_ambitions(w, mid, state)


def evolve_ambitions(w: World, mid: str, state: dict) -> None:
    """Let long-term ambitions drift gradually — small confidence/strategy moves only.

    Ambitions are preferences, not win conditions: they may be postponed (suspended),
    resumed, or reinterpreted (strategy rewrite), but never silently swapped for a new
    goal and never forced onto the month's decisions. Importance moves at most 0.05 a
    month; status flips need sustained pressure and are recorded in ambition_history.
    """
    from .agents import _normalize_ambitions
    items = state.get("long_term_ambitions")
    if not items:
        return
    items = _normalize_ambitions(items)
    state["long_term_ambitions"] = items
    if not items:
        return
    traits = state.get("traits", {})
    stress = state.get("stress", {})
    pressure = max([stress.get("general", 0)] + [stress.get(k, 0) for k in ("political", "economic", "security")])
    patience = traits.get("patience", 50) / 100.0
    stick = traits.get("stubbornness", 50) / 100.0
    hist = state.setdefault("ambition_history", [])
    for a in items:
        if a["status"] == "abandoned":
            continue
        # Confidence breathes slowly with motion fortunes and general pressure.
        delta = 0.0
        for mo in (state.get("motion_outcomes") or [])[-3:]:
            if mo.get("month") != w.month:
                continue
            delta += 1.2 if mo.get("passed") else -1.0
        delta += (50 - pressure) * 0.008 * (1 - patience * 0.5)
        a["confidence"] = round(clamp(a["confidence"] + delta, 5, 95), 1)
        # Importance wobbles at most a touch; high-importance items resist.
        rng = rng_for(w.seed, w.month, f"ambition-drift:{mid}:{a['id']}")
        wobble = (rng.random() - 0.5) * 0.06 * (1.2 - a["importance"])
        a["importance"] = round(clamp(a["importance"] + wobble, 0.1, 0.95), 2)
        # Suspension is reversible and needs real pressure; resumption is easy.
        if a["status"] == "active" and pressure >= 72 and a["importance"] < 0.7 and rng.random() < 0.4 * (1 - stick):
            a["status"] = "suspended"
            a["since_month"] = w.month
            hist.append({"month": w.month, "ambition": a["id"], "to": "suspended",
                         "reason": "costs/stability pressure; postponed, not dropped"})
        elif a["status"] == "suspended" and pressure < 55:
            a["status"] = "active"
            a["since_month"] = w.month
            hist.append({"month": w.month, "ambition": a["id"], "to": "active",
                         "reason": "pressure eased; resumed"})
    del hist[:-12]


def record_office_changes(w: World, mid: str, state: dict, before: dict) -> None:
    now = set(w.offices_of(mid))
    was = {o for o, holder in before.items() if holder == mid}
    log = state.setdefault("office_log", [])
    for office in sorted(was - now):
        log.append({"month": w.month, "office": office, "office_lost": True})
    for office in sorted(now - was):
        log.append({"month": w.month, "office": office, "office_gained": True})
    del log[:-12]


def learn_from_outcomes(w: World, mid: str, state: dict) -> None:
    """Policies a delegate backed, set against what followed (spec 77). No response is scripted:
    the interpretation style colours the context; the model decides what to do about it."""
    if len(w.history) < 4:
        return
    traits = state["traits"]
    g = lambda k: traits.get(k, 50)
    styles = {"moderate": g("compromise_preference") + (100 - g("stubbornness")),
              "double_down": g("stubbornness") + g("status_sensitivity"),
              "blame_implementation": g("reputation_sensitivity") + g("opportunism"),
              "targeted_relief": g("empathy") + g("economic_interventionism")}
    style = max(styles, key=styles.get)
    lessons = state.setdefault("policy_lessons", [])
    known = {(x["policy"], x["month_adopted"]) for x in lessons}
    for outcome in state.get("motion_outcomes", []):
        if not outcome.get("passed") or outcome.get("type") != "set_policy":
            continue
        age = w.month - outcome.get("month", w.month)
        lever = outcome.get("subject")
        if age != 3 or lever not in POLICY_OUTCOMES or (lever, outcome["month"]) in known:
            continue
        index = outcome["month"]
        # Older records carry no previous value; they keep the old reading (a rise).
        direction = policy_direction(lever, outcome.get("value"), outcome.get("previous_value")) or 1
        judged = judge_policy(w, lever, index, direction)
        if judged is None:
            continue
        if judged["verdict"] == "worked" and judged["side_change"] > -.02:
            continue
        lessons.append({"month": w.month, "month_adopted": index, "policy": lever,
                        "value": outcome.get("value"), **judged, "style": style})
        del lessons[:-6]


def policy_direction(lever: str, value, previous) -> int:
    """+1 when a change raised the lever, -1 when it lowered it, 0 when that cannot be told."""
    from .politics import BOOLS, ENUMS, parse_lever
    if previous is None or lever not in POLICY_OUTCOMES:
        return 0
    new, old = parse_lever(lever, value), parse_lever(lever, previous)
    if new is None or old is None:
        return 0
    if lever in ENUMS:
        new, old = ENUMS[lever].index(new), ENUMS[lever].index(old)
    elif lever in BOOLS:
        new, old = int(bool(new)), int(bool(old))
    diff = float(new) - float(old)
    return 1 if diff > 1e-9 else -1 if diff < -1e-9 else 0


def judge_policy(w: World, lever: str, month_adopted: int, direction: int = 1) -> dict | None:
    """What followed a policy change, from the month before it to now: did its aim move the right
    way, and what did it cost? One test serves the proposer's lessons and the dissenter's record."""
    if lever not in POLICY_OUTCOMES or len(w.history) < 2 or month_adopted >= len(w.history):
        return None
    before = w.history[month_adopted - 1] if month_adopted >= 1 else w.history[0]
    now = w.history[-1]
    target, side = POLICY_OUTCOMES[lever]
    if direction < 0:
        target, side = side, target
    worked, cost = _moved(before, now, target), _moved(before, now, side)
    return {"verdict": "worked" if worked > .02 else "failed" if worked < -.02 else "unclear",
            "target": target[2], "target_change": round(worked, 3),
            "side": side[2], "side_change": round(cost, 3)}


def lone_dissenter(motion: dict) -> str | None:
    """The one member who voted no on a motion the others carried with at least three votes."""
    if not motion.get("passed") or motion.get("void"):
        return None
    votes = motion.get("votes") or {}
    eligible = set(motion.get("eligible_voters") or votes)
    no = [v for v, vote in votes.items() if v in eligible and vote == "no"]
    yes = [v for v, vote in votes.items() if v in eligible and vote == "yes"]
    return no[0] if len(no) == 1 and len(yes) >= 3 else None


def note_stand(w: World, mid: str, motion: dict) -> None:
    """Keep a lone dissent against an executed policy change, to be judged three months on."""
    lever = motion.get("subject")
    if motion.get("type") != "set_policy" or lever not in POLICY_OUTCOMES:
        return
    if motion.get("execution_status", "EXECUTED") != "EXECUTED":
        return                  # a blocked motion changed nothing; there is nothing to be right about
    adopted = getattr(w.policy, lever, None)
    direction = policy_direction(lever, motion.get("value"), motion.get("previous_value"))
    if direction == 0 or policy_direction(lever, adopted, motion.get("previous_value")) != direction:
        return                  # the change is not in force: an office holder kept the old setting
    state = w.member(mid).agent_state
    if not state:
        return
    stands = state.setdefault("minority_stands", [])
    if any(s.get("motion") == motion.get("id") and s.get("month") == w.month for s in stands):
        return
    votes = motion.get("votes") or {}
    stands.append({"month": w.month, "motion": motion.get("id"), "subject": lever,
                   "value": motion.get("value"), "previous_value": motion.get("previous_value"),
                   "adopted": adopted,
                   "summary": " ".join(str(motion.get("summary") or lever).split())[:120],
                   "proposer": motion.get("proposer"),
                   "supporters": sorted(v for v, vote in votes.items() if vote == "yes"),
                   "tally": f"{sum(v == 'yes' for v in votes.values())}-{sum(v == 'no' for v in votes.values())}",
                   "reason": " ".join(str((motion.get("vote_reasons") or {}).get(mid, "")).split())[:160]})
    del stands[:-8]


def judge_stands(w: World, mid: str, state: dict) -> list:
    """Lone dissents from three months ago, set against what followed by the same test as lessons.
    A change the council has since reversed is not judged: what followed is no longer its doing."""
    judged = []
    for stand in state.get("minority_stands", []):
        if stand.get("verdict") or w.month - stand.get("month", w.month) < 3:
            continue
        lever = stand.get("subject")
        direction = policy_direction(lever, stand.get("value"), stand.get("previous_value"))
        stand["judged_month"] = w.month
        if direction == 0:
            stand["verdict"] = "unjudged"
            continue
        if _reversed(lever, direction, stand.get("previous_value"), stand.get("adopted"),
                     getattr(w.policy, lever, None)):
            stand["verdict"] = "reversed"
            continue
        result = judge_policy(w, lever, stand["month"], direction)
        if result is None:
            stand["verdict"] = "unjudged"
            continue
        stand.update(result)
        judged.append(stand)
    return judged


def _reversed(lever: str, direction: int, previous, adopted, now) -> bool:
    if adopted is None or now is None:
        return False
    back = policy_direction(lever, now, adopted)
    if back != -direction:
        return False
    from .politics import SHARES
    if lever in SHARES:
        try:
            return abs(float(now) - float(adopted)) >= .5 * abs(float(adopted) - float(previous))
        except (TypeError, ValueError):
            return True
    return True


def _moved(before: dict, now: dict, spec: tuple) -> float:
    key, better, _ = spec
    a, b = before.get(key), now.get(key)
    if a is None or b is None:
        return 0.0
    scale = max(abs(a), .05)
    return better * (b - a) / scale


def lesson_text(w: World, lesson: dict) -> str:
    what = f"the {lesson['policy']} change adopted in Month {lesson['month_adopted'] + 1}"
    if lesson["verdict"] == "worked":
        body = f"{what} helped with {lesson['target']} but {lesson['side']} got worse"
    elif lesson["verdict"] == "failed":
        body = f"{what} was followed by worse {lesson['target']}"
    else:
        body = f"the effect of {what} on {lesson['target']} is unclear"
    return body + "; " + LEARNING_STYLES.get(lesson.get("style"), "you are still weighing it") + "."


def update_confidence(w: World, mid: str, state: dict, record: dict | None) -> None:
    conf = state.get("confidence", 55.0)
    if record:
        for mo in record.get("motions", []):
            if mo.get("proposer") == mid and not mo.get("void"):
                conf += 1.5 if mo.get("passed") else -2.0
    for lesson in state.get("policy_lessons", []):
        if lesson.get("month") == w.month:
            conf += 2 if lesson["verdict"] == "worked" else -3
    for stand in state.get("minority_stands", []):
        if stand.get("judged_month") == w.month:
            conf += 3 if stand.get("verdict") == "failed" else -1.5 if stand.get("verdict") == "worked" else 0
    general = state.get("stress", {}).get("general", 0)
    conf += (50 - general) * .02
    state["confidence"] = round(clamp(conf, 5, 95), 1)
