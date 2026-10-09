"""What a foreign cabinet can do with force (engine 12).

Engine 11 gave the Velerian and Dorsanian cabinets statements, talks, embargoes and "exercises", and left
war to fixed thresholds in director.py. In the first engine-6 run with real models the two cabinets
issued 14 statements and 7 exercises in 17 months and never moved a soldier, while the engine's own war
machinery (fronts, combat, occupation, blockade) sat unused and the map never changed. Here a cabinet can
call up reserves, mass troops at a border and pull them back, stage an incident, arm rebels inside
Karamaniya, blockade its ports, set an ultimatum with terms and a deadline, invade for a limited
objective or to win, and stop.

Each act is checked against the real state before it happens: soldiers a country does not have cannot
move, an invasion needs troops already at that border, a blockade needs the ships. The costs are the
ones the engine already charges. The council sees what is visible (troops at the border, the incident,
the uprising, the warships), never the cabinet's reasons. A cabinet also leads a government with a
temperament drawn once per run, which the council never sees; it shapes the seeded disposition the
engine's own rules read and is told to the cabinet in plain words.
"""
from __future__ import annotations

from .world import FRONT_CHAINS, clamp, rng_for

FRONTS = ("north", "east")
# Which fronts a neighbour's border touches: Veleria reaches Kessel Valley and, through Irongate, Dorran
# March; Dorsania only Dorran March.
FRONTS_OF = {"veleria": ("north", "east"), "dorsania": ("east",)}
MOBILIZE_CAP = {"veleria": 12000, "dorsania": 6000}   # reservists one country can call up in a month
MIN_INVASION = 6000           # soldiers that must already stand at a border to invade across it
INCIDENT_MIN_FORCE = 1000     # soldiers at a border before an incident can be staged there
DEPLOYABLE = 0.85             # the share of an army that can be sent anywhere; the rest holds home
DEADLINE_MONTHS = (2, 6)
ULTIMATUM_TERMS = {
    "status_talks": "Open negotiations on Karamaniya's status in the Solvaran Union.",
    "cut_league_ties": "End military cooperation with the Maritime League.",
    "demilitarize_border": "Withdraw Karamaniyan forces from the regions on the border.",
    "protect_imperial_citizens": "Guarantee the rights and safety of Imperial citizens in Karamaniya.",
}
AIMS = ("limited", "full")
# The acts this module handles; foreign.py handles the rest of a cabinet's catalog.
KINDS = ("mobilize", "deploy_to_border", "withdraw_from_border", "border_incident", "covert_support",
         "invade", "ceasefire", "naval_blockade", "lift_blockade", "ultimatum")

TEMPERAMENTS = ("hawk", "opportunist", "cautious")
TEMPERAMENT_ODDS = {"veleria": (.40, .40, .20), "dorsania": (.15, .45, .40)}
# How a temperament moves the seeded disposition the engine's own rules read (foreign._actor).
TEMPERAMENT_SHIFT = {
    "hawk": {"aggressiveness": .14, "patience": -.12, "risk_tolerance": .14},
    "opportunist": {"aggressiveness": .04, "patience": -.04, "risk_tolerance": .08, "economic_pragmatism": .06},
    "cautious": {"aggressiveness": -.16, "patience": .12, "risk_tolerance": -.12},
}
TEMPERAMENT_TEXT = {
    "veleria": {
        "hawk": ("Your government is led by hard-line nationalists. They hold that Karamaniya's secession was "
                 "illegitimate and that firmness, including force, is what Karamaniya's leaders understand. They "
                 "accept risk when the odds look good."),
        "opportunist": ("Your government is led by pragmatists who press where the other side is weak and hold back "
                        "where it is strong. A moment of Karamaniyan weakness (an unpaid army, unrest, a government "
                        "in crisis) is an opening to them."),
        "cautious": ("Your government is led by cautious leaders who prefer economic and diplomatic means. They "
                     "will use force when they judge the threat grave or the cost of acting low."),
    },
    "dorsania": {
        "hawk": ("Your government is led by a security-minded faction that sees Karamaniya's eastern border as a "
                 "danger and wants it settled on Dorsania's terms, by pressure or by force."),
        "opportunist": ("Your government is led by pragmatists who press where the other side is weak and hold back "
                        "where it is strong. A Karamaniyan crisis is a chance to win better terms for Dorsania's "
                        "grain, border and standing in the Union."),
        "cautious": ("Your government is led by cautious leaders who prefer trade and quiet diplomacy. They will "
                     "use force to answer a direct threat."),
    },
}


def draw_temperament(actor_id: str, seed: int) -> str:
    """One temperament per actor per run, from the seed, never redrawn."""
    roll = rng_for(seed, 0, "foreign-temperament:" + actor_id).random()
    total = 0.0
    for name, odds in zip(TEMPERAMENTS, TEMPERAMENT_ODDS[actor_id]):
        total += odds
        if roll < total:
            return name
    return TEMPERAMENTS[-1]


# ---- what each country has where --------------------------------------------------------------
def at_border(w, actor_id: str, front: str | None = None) -> float:
    forces = (w.dip.border_forces or {}).get(actor_id) or {}
    if front is not None:
        return float(forces.get(front, 0.0))
    return float(sum(forces.get(f, 0.0) for f in FRONTS))


def war_fronts(w) -> tuple:
    """The fronts the Union is fighting on: a limited war's own front, otherwise both."""
    if not (w.dip.war and w.dip.aggressor == "union"):
        return ()
    aim = w.dip.war_aim or {}
    if aim.get("aim") == "limited" and aim.get("front") in FRONTS:
        return (aim["front"],)
    return FRONTS


def at_war_front(w, actor_id: str) -> float:
    """The part of the Union's front line that is this country's army, by its share of the armies at war
    (both neighbours' in a war the rules started, only the participants' in one a cabinet started)."""
    if not w.dip.war:
        return 0.0
    participants = (w.dip.war_aim or {}).get("participants") or list(w.rivals)
    if actor_id not in participants:
        return 0.0
    total = sum(w.rivals[p].army for p in participants) or 1.0
    return sum(w.dip.union_front.values()) * w.rivals[actor_id].army / total


def free_troops(w, actor_id: str) -> float:
    """Soldiers of the active army that can still be sent to a border or a front."""
    rival = w.rivals[actor_id]
    return max(0.0, rival.army * DEPLOYABLE - at_border(w, actor_id) - at_war_front(w, actor_id))


def reserve_room(w, actor_id: str) -> float:
    military = w.foreign["actors"][actor_id]["military"]
    return max(0.0, military["reserves"] - military["active"] * .45)


def navy_for_blockade(w, actor_id: str) -> float:
    """Ships a blockade can use: the whole Union fleet while the Union holds together, otherwise one's own."""
    union = (w.foreign or {}).get("union", {})
    if w.dip.union_formed and union.get("cohesion", 0) > .55:
        return sum(r.navy for r in w.rivals.values())
    return w.rivals[actor_id].navy


# ---- checking an act against the real state -----------------------------------------------------
def check(w, actor_id: str, action: dict) -> str | None:
    """Why this act cannot happen now, or None. Recorded and shown to the cabinet the next month."""
    kind = action["type"]
    name = w.names.get(actor_id, actor_id.title())
    front = action.get("front")
    troops = action.get("troops", 0)
    if kind in ("deploy_to_border", "withdraw_from_border", "border_incident", "invade"):
        if front not in FRONTS_OF[actor_id]:
            fronts = " or ".join(FRONTS_OF[actor_id])
            return f"{name}'s border with Karamaniya is the {fronts} front; name one of them"
    if kind in ("mobilize", "deploy_to_border", "withdraw_from_border"):
        if not isinstance(troops, int) or isinstance(troops, bool) or troops <= 0:
            return "name how many soldiers (troops, a whole number above 0)"
    if kind == "mobilize":
        limit = min(reserve_room(w, actor_id), MOBILIZE_CAP[actor_id])
        if troops > limit:
            return f"at most {limit:,.0f} reservists can be called up this month"
    elif kind == "deploy_to_border":
        if troops > free_troops(w, actor_id):
            return f"only {free_troops(w, actor_id):,.0f} soldiers are free to send; call up reserves first"
    elif kind == "withdraw_from_border":
        if front in war_fronts(w):
            return f"the troops on the {front} front are fighting; a ceasefire comes first"
        if troops > at_border(w, actor_id, front):
            return f"only {at_border(w, actor_id, front):,.0f} soldiers stand at the {front} border"
    elif kind == "border_incident":
        if w.dip.war:
            return "the countries are already at war"
        if at_border(w, actor_id, front) < INCIDENT_MIN_FORCE:
            return f"an incident needs at least {INCIDENT_MIN_FORCE:,} soldiers already at the {front} border"
    elif kind == "covert_support":
        region = next((r for r in w.k_regions() if r.id == action.get("region")), None)
        if region is None:
            return "name a region of Karamaniya"
        if region.controller == "union":
            return f"{region.name} is already held by the Union"
        if region.controller != "rebels" and region.unrest < .30:
            return f"there is no unrest in {region.name} for weapons to feed"
    elif kind == "invade":
        if w.dip.war:
            return "the countries are already at war"
        if action.get("aim") not in AIMS:
            return "aim must be limited (take the border region and stop) or full (defeat Karamaniya)"
        if at_border(w, actor_id, front) < MIN_INVASION:
            return (f"an invasion across the {front} border needs at least {MIN_INVASION:,} soldiers already "
                    f"there; {at_border(w, actor_id, front):,.0f} are")
    elif kind == "ceasefire":
        if not w.dip.war or w.dip.aggressor != "union":
            return "there is no war of the Union's to stop"
    elif kind == "naval_blockade":
        if w.dip.blockade:
            return "a blockade is already in force"
        ships, theirs = navy_for_blockade(w, actor_id), w.mil.navy.size
        if ships <= 1.2 * theirs:
            return (f"a blockade needs a clear naval advantage: {ships:.0f} ships available against "
                    f"Karamaniya's {theirs:.0f}")
    elif kind == "lift_blockade":
        if not w.dip.blockade:
            return "there is no blockade to lift"
    elif kind == "ultimatum":
        if w.dip.ultimatum:
            return "an ultimatum is already running"
        if w.dip.war:
            return "the countries are already at war"
        if action.get("terms") not in ULTIMATUM_TERMS:
            return "terms must be one of: " + ", ".join(ULTIMATUM_TERMS)
        months = action.get("deadline_months")
        if (not isinstance(months, int) or isinstance(months, bool)
                or not DEADLINE_MONTHS[0] <= months <= DEADLINE_MONTHS[1]):
            return f"deadline_months must be a whole number from {DEADLINE_MONTHS[0]} to {DEADLINE_MONTHS[1]}"
    return None


# ---- carrying an act out ------------------------------------------------------------------------
def _front_region(w, front: str):
    return w.region(FRONT_CHAINS[front][0])


def _fear(w, region_id: str, amount: float) -> None:
    for p in w.pops:
        if p.region == region_id:
            p.fear = clamp(p.fear + amount)


def apply(w, actor_id: str, action: dict) -> dict:
    """Carry out an act that passed check(). Returns what it moved, for the effects ledger."""
    from . import foreign
    dip, kind = w.dip, action["type"]
    actor = w.foreign["actors"][actor_id]
    rival = w.rivals[actor_id]
    name = w.names.get(actor_id, actor_id.title())
    magnitude = float(action.get("magnitude", .5))
    front = action.get("front")
    troops = int(action.get("troops", 0) or 0)
    effects: dict = {}
    chain = w.foreign.setdefault("escalation_chains", [])

    if kind == "mobilize":
        rival.army += troops
        actor["military"]["active"] = rival.army
        actor["military"]["readiness"] = round(clamp(actor["military"]["readiness"] + troops / 150000), 3)
        foreign._pay_action(w, actor_id, "mobilization", troops / max(1.0, rival.population) * .9)
        effects["army"] = troops
        if troops >= 5000:
            w.event("foreign_mobilization", f"{name} is calling up reservists.", importance=1, actor=actor_id)
        chain.append({"month": w.month, "actor": actor_id, "signal": "mobilization", "magnitude": troops})

    elif kind == "deploy_to_border":
        region = _front_region(w, front)
        if front in war_fronts(w):
            # Troops sent to a front where the Union is fighting join the fighting; a neighbour that had
            # stayed out of the war is in it from now on.
            dip.union_front[front] = dip.union_front.get(front, 0.0) + troops
            effects[f"front.{front}"] = troops
            participants = (dip.war_aim or {}).get("participants")
            if participants is not None and actor_id not in participants:
                participants.append(actor_id)
                w.event("war", f"{name} has joined the war against Karamaniya.", importance=3, actor=actor_id)
            w.event("foreign_reinforcement", f"{name} is sending more troops to the fighting in {region.name}.",
                    importance=2, actor=actor_id, region=region.id)
        else:
            dip.border_forces.setdefault(actor_id, {f: 0.0 for f in FRONTS})
            dip.border_forces[actor_id][front] = at_border(w, actor_id, front) + troops
            effects[f"border.{front}"] = troops
            total = at_border(w, actor_id, front)
            w.event("foreign_massing", f"{name} is massing troops on the border near {region.name}.",
                    importance=2 if total >= MIN_INVASION else 1, actor=actor_id, region=region.id)
            _fear(w, region.id, .02 + .04 * min(1.0, total / 20000))
            dip.rally = clamp(dip.rally + .02)
        foreign._pay_action(w, actor_id, "troop deployment", troops / max(1.0, rival.population) * .3)
        chain.append({"month": w.month, "actor": actor_id, "signal": "border deployment", "front": front,
                      "magnitude": troops})

    elif kind == "withdraw_from_border":
        dip.border_forces[actor_id][front] = max(0.0, at_border(w, actor_id, front) - troops)
        effects[f"border.{front}"] = -troops
        region = _front_region(w, front)
        w.event("foreign_withdrawal", f"{name} has pulled troops back from the border near {region.name}.",
                importance=1, actor=actor_id, region=region.id)
        chain.append({"month": w.month, "actor": actor_id, "signal": "border withdrawal", "front": front,
                      "magnitude": troops})

    elif kind == "border_incident":
        rng = rng_for(w.seed, w.month, f"staged-incident:{actor_id}:{front}")
        region = _front_region(w, front)
        soldiers = max(1, round((4 + 26 * magnitude) * rng.uniform(.6, 1.4)))
        civilians = round(12 * magnitude * rng.uniform(0, 1)) if magnitude > .5 else 0
        w.mil.army.size = max(0.0, w.mil.army.size - soldiers)
        w.mil.killed += soldiers
        w.count("soldiers_killed", soldiers)
        if civilians:
            from .military import _kill_civilians
            _kill_civilians(w, region.id, civilians, "deaths_border_incidents")
        if magnitude > .5:
            text = (f"{name}'s troops crossed into {region.name} and fought a Karamanian border unit before "
                    f"pulling back: {soldiers} Karamanian soldiers" + (f" and {civilians} civilians" if civilians else "")
                    + f" were killed. {name} says its forces were fired on first.")
        else:
            text = (f"Shots were fired across the border near {region.name}; {soldiers} Karamanian soldiers were "
                    f"killed. {name} says its patrol was fired on first.")
        w.event("border_incident", text, importance=3 if soldiers + civilians >= 15 else 2,
                actor=actor_id, region=region.id, deliberate=True)
        _fear(w, region.id, .03 + .05 * magnitude)
        dip.rally = clamp(dip.rally + .05 + .10 * magnitude)
        relations = actor["relations"]["karamaniya"]
        relations["hostility"] = round(clamp(relations["hostility"] + .04 * magnitude), 3)
        actor["reputation"]["military_aggressiveness"] = round(
            clamp(actor["reputation"]["military_aggressiveness"] + .05 * magnitude), 3)
        league = w.foreign["league"]
        league["shipping_security_concern"] = round(clamp(league["shipping_security_concern"] + .03 * magnitude), 3)
        effects.update({"soldiers_killed": soldiers, "civilians_killed": civilians})
        chain.append({"month": w.month, "actor": actor_id, "signal": "staged border incident", "front": front,
                      "magnitude": round(magnitude, 2)})

    elif kind == "covert_support":
        region = w.region(action["region"])
        dip.arms_smuggling = True
        region.unrest = clamp(region.unrest + .04 + .08 * magnitude)
        w.foreign["covert_support"] = {"by": actor_id, "month": w.month, "region": region.id,
                                       "magnitude": round(magnitude, 2)}
        effects.update({"arms_smuggling": True, f"unrest.{region.id}": round(.04 + .08 * magnitude, 3)})
        rng = rng_for(w.seed, w.month, f"covert-support:{actor_id}")
        detection = (.10 + .20 * (w.policy.surveillance == "high") + .08 * (w.policy.surveillance == "medium")
                     + .12 * clamp(w.mil.police.loyalty - .5) * 2)
        if rng.random() < detection:
            w.event("scandal", f"Karamanian police seized weapons bound for Imperial Restoration militias in "
                    f"{region.name} and traced them to {name}.", importance=3, actor=actor_id, region=region.id)
            relations = actor["relations"]["karamaniya"]
            relations["hostility"] = round(clamp(relations["hostility"] + .06), 3)
            actor["reputation"]["diplomatic_trust"] = round(clamp(actor["reputation"]["diplomatic_trust"] - .06), 3)
            dip.rally = clamp(dip.rally + .08)
            effects["exposed"] = True
        chain.append({"month": w.month, "actor": actor_id, "signal": "covert support to rebels",
                      "region": region.id, "magnitude": round(magnitude, 2)})

    elif kind == "invade":
        start_war(w, actor_id, front, action["aim"])
        effects.update({"war": True, "aim": action["aim"], "front": front})

    elif kind == "ceasefire":
        from .director import _end_war
        _end_war(w, f"{name} stopped its offensive")
        effects["ceasefire"] = True

    elif kind == "naval_blockade":
        dip.blockade = True
        league = w.foreign["league"]
        league["shipping_security_concern"] = round(clamp(league["shipping_security_concern"] + .2), 3)
        league["fear_of_union_expansion"] = round(clamp(league["fear_of_union_expansion"] + .05), 3)
        w.event("blockade", f"{name}'s warships have begun stopping ships bound for Karamaniya's ports.",
                importance=3, actor=actor_id)
        dip.rally = clamp(dip.rally + .1)
        effects["blockade"] = True

    elif kind == "lift_blockade":
        dip.blockade = False
        w.event("blockade_lifted", f"{name} has lifted its blockade of Karamaniya's ports.", importance=2,
                actor=actor_id)
        effects["blockade"] = False

    elif kind == "ultimatum":
        months = int(action["deadline_months"])
        terms = ULTIMATUM_TERMS[action["terms"]]
        dip.ultimatum = {"issued": w.month, "deadline": w.month + months, "terms": terms,
                         "terms_id": action["terms"], "by": actor_id}
        dip.rally = clamp(dip.rally + .16)
        foreign._pay_action(w, actor_id, "ultimatum", .008, approval=.003)
        foreign._message(w, name, f"{name} demands: {terms} It expects an answer by Month {w.month + months + 1}.")
        w.event("ultimatum", f"{name} has set Karamaniya a deadline: {terms}", importance=2, actor=actor_id)
        effects["ultimatum"] = action["terms"]

    return effects


def start_war(w, actor_id: str, front: str, aim: str) -> None:
    """An invasion a cabinet ordered: the troops at that border become the front."""
    from . import foreign
    dip = w.dip
    name = w.names.get(actor_id, actor_id.title())
    region = _front_region(w, front)
    participants = [actor_id]
    union = w.foreign.get("union", {})
    if (actor_id == "veleria" and aim == "full" and dip.union_formed and union.get("cohesion", 0) > .6
            and w.foreign.get("dorsania_position") != "oppose"):
        participants.append("dorsania")
    dip.war, dip.war_start, dip.aggressor, dip.ceasefire = True, w.month, "union", False
    dip.nonaggression = False
    dip.union_intensity = 1.0
    dip.rally = clamp(dip.rally + .5)
    dip.union_front = {f: 0.0 for f in FRONTS}
    fronts = (front,) if aim == "limited" else tuple(FRONTS)
    for p in participants:
        for f in fronts:
            dip.union_front[f] = dip.union_front.get(f, 0.0) + at_border(w, p, f)
            dip.border_forces.setdefault(p, {x: 0.0 for x in FRONTS})[f] = 0.0
    dip.war_aim = {"by": actor_id, "aim": aim, "front": front, "objective": region.id,
                   "participants": participants, "month": w.month}
    actor = w.foreign["actors"][actor_id]
    actor["relations"]["karamaniya"]["hostility"] = round(clamp(actor["relations"]["karamaniya"]["hostility"] + .15), 3)
    actor["reputation"]["military_aggressiveness"] = round(
        clamp(actor["reputation"]["military_aggressiveness"] + .2), 3)
    if aim == "limited":
        text = f"{name} has invaded Karamaniya across the {front} border, into {region.name}."
    else:
        text = f"{name} has launched a war against Karamaniya."
    if "dorsania" in participants and actor_id == "veleria":
        text += f" {w.names.get('dorsania', 'Dorsania')} has joined the operations."
    foreign._message(w, name, f"{name} has begun military operations in Karamaniya.")
    w.event("war", text, importance=3, actor=actor_id, region=region.id, aim=aim)


def objective_taken(w) -> bool:
    """A limited war whose objective has fallen: the attacker stops there (director._union_forces)."""
    aim = w.dip.war_aim or {}
    return (w.dip.war and aim.get("aim") == "limited"
            and w.region(aim.get("objective", "")).controller == "union")


def expire_covert_support(w) -> None:
    """Weapons a cabinet stopped sending run out after three months; the Interior can also cut them off."""
    covert = (w.foreign or {}).get("covert_support")
    if covert and w.dip.arms_smuggling and w.month - covert.get("month", w.month) >= 3:
        w.dip.arms_smuggling = False
        w.foreign["covert_support"] = None


# ---- what the council sees ------------------------------------------------------------------------
def massing_text(w) -> str:
    """Which borders have foreign troops massed on them, as the public knows it (no numbers: those are
    the Army Command's intelligence estimates)."""
    seen = [f"{front} border ({w.names.get(actor, actor.title())})"
            for actor, forces in (w.dip.border_forces or {}).items()
            for front, n in forces.items() if n >= 500]
    return ", ".join(seen)


def ultimatum_text(w) -> str:
    ult = w.dip.ultimatum or {}
    if not ult:
        return ""
    by = w.names.get(ult.get("by", ""), "the Union")
    terms = ult.get("terms") or "a settlement on Karamaniya's status"
    return f"{by} demands: {terms} Deadline Month {ult.get('deadline', w.month) + 1}."


# ---- what a cabinet sees ------------------------------------------------------------------------
def ultimatum_compliance(w) -> dict | None:
    """The facts a cabinet weighs about its own ultimatum: what it asked for and what Karamaniya did."""
    ult = w.dip.ultimatum or {}
    terms = ult.get("terms_id")
    if not terms:
        return None
    m = w.mil
    talks = [p["kind"] for p in (w.foreign or {}).get("proposal_log", [])
             if p.get("month", -1) >= ult["issued"] and p.get("party") in ("union", "veleria")
             and p.get("kind") in ("trade_talks", "federation", "join_union", "non_aggression")]
    facts = {"status_talks": {"karamaniyan_proposals_since_the_ultimatum": talks},
             "cut_league_ties": {"league_alliance": w.dip.league_alliance, "league_military_aid": w.dip.league_aid > 0},
             "demilitarize_border": {"share_of_army_on_the_north_border": round(m.deploy.get("north", 0.0), 2),
                                     "share_of_army_on_the_east_border": round(m.deploy.get("east", 0.0), 2)},
             "protect_imperial_citizens": {"minority_policy": w.const.minority,
                                           "police_response": w.policy.protest_response}}[terms]
    return {"by": ult.get("by", "veleria"), "terms": ult.get("terms"), "deadline_month": ult["deadline"] + 1,
            "expired": w.month >= ult["deadline"], "observed": facts}


def cabinet_view(w, actor_id: str) -> dict:
    """Forces, Karamaniya's visible condition and the state of any confrontation, for one cabinet."""
    rival, dip, c = w.rivals[actor_id], w.dip, w.const
    actor = w.foreign["actors"][actor_id]
    intel = actor["intelligence"][-1] if actor["intelligence"] else {}
    arrears = w.mil.army.arrears
    unrest = {r.name: ("held by rebels" if r.controller == "rebels" else
                       "occupied by the Union" if r.controller == "union" else
                       "uprising" if r.unrest >= .6 else "protests" if r.unrest >= .35 else "tense")
              for r in w.k_regions() if r.unrest >= .2 or r.controller != "karamaniya"}
    if c.handover_month >= w.month:
        government = f"lost the election; must hand power to the new Assembly in Month {c.handover_month + 1}"
    elif "handover_blocked_month" in w.counters:
        government = "lost the election and kept power by force"
    elif c.elected:
        government = "elected"
    elif c.election_month < 0:
        government = "provisional; elections cancelled"
    else:
        government = f"provisional; election due in Month {c.election_month + 1}"
    rejected = [{"action": (m.get("action") or {}).get("type") if isinstance(m.get("action"), dict) else None,
                 "reason": m.get("text", "")}
                for m in actor.get("memory", []) if m.get("kind") == "rejected_action"
                and m.get("month") == w.month - 1]
    aim = dip.war_aim or {}
    return {
        "your_temperament": actor.get("temperament", ""),
        "your_forces": {"active_army": round(rival.army, -2), "reservists_you_can_call_up": round(reserve_room(w, actor_id), -2),
                        "free_to_send": round(free_troops(w, actor_id), -2),
                        "at_the_border": {f: round(at_border(w, actor_id, f), -2) for f in FRONTS_OF[actor_id]},
                        "warships": round(rival.navy, 1),
                        "warships_for_a_blockade": round(navy_for_blockade(w, actor_id), 1),
                        "your_borders_with_karamaniya": list(FRONTS_OF[actor_id])},
        "karamaniya_as_you_see_it": {
            "army_estimate": intel.get("visible_karamaniyan_force_estimate"),
            "army_pay": (f"reports that soldiers have gone unpaid for about {arrears:.0f} months"
                         if arrears >= 1 else "no reports of unpaid soldiers"),
            "warships": round(w.mil.navy.size, 1),
            "fortification": intel.get("visible_fortification"),
            "government": government,
            "approval_estimate": (intel.get("poll_estimates") or {}).get("government_approval"),
            "unrest": unrest or "no serious unrest reported",
            "league_ties": {"alliance": dip.league_alliance, "military_aid": dip.league_aid > 0,
                            "escorts": dip.league_escort},
        },
        "confrontation": {
            "war": dip.war, "you_started_it": bool(dip.war and aim.get("by") == actor_id),
            "war_aim": aim.get("aim") if dip.war else None,
            "fronts": {f: {"union_soldiers": round(dip.union_front.get(f, 0.0), -2),
                           "advance": round(w.mil.progress.get(f, 0.0), 2)} for f in FRONTS} if dip.war else None,
            "occupied_regions": [r.name for r in w.k_regions() if r.controller == "union"],
            "ceasefire": dip.ceasefire, "blockade": dip.blockade,
            "ultimatum": ultimatum_compliance(w),
            "other_neighbour_at_the_border": {o: round(at_border(w, o), -2) for o in FRONTS_OF if o != actor_id},
        },
        "your_acts_refused_last_month": rejected,
    }
