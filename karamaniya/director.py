"""Resolve the independent strategies of Veleria, Dorsania and the Maritime League.

Veleria and Dorsania make separate monthly choices, then negotiate common Union policy.
Their domestic pressures, costs, beliefs and Karamaniya's actions shape what happens.
The League follows financial, political and shipping conditions without routine model calls.
"""
from __future__ import annotations

from . import foreign
from .military import DEFENDER_BONUS, quality, union_army, union_navy, union_quality
from .world import World, clamp, democracy_index, month_label, rng_for

MAX_UNION_ARMY = 260000


def _msg(w: World, sender: str, text: str) -> None:
    item = {"month": w.month, "from": sender, "text": text}
    w.dip.inbox.append(item)
    w.dip.log.append(item)


def _private_msg(w: World, sender: str, office: str, text: str) -> None:
    target = office if w.holder(office) else ("head" if w.holder("head") else office)
    item = {"month": w.month, "from": sender, "office": target, "channel": office,
            "text": text, "private": True}
    w.dip.private_inbox.append(item)
    w.dip.log.append(item)


def _once(w: World, key: str) -> bool:
    k = "script_" + key
    if w.counters.get(k):
        return False
    w.counters[k] = 1.0
    return True


def prepare_external(w: World) -> dict:
    """Resolve Karamaniya's completed diplomatic and military choices before foreign calls."""
    w.dip.inbox = []
    # The council has just read the previous month's private dispatches.
    w.dip.private_inbox = []
    if not w.foreign:
        w.foreign = foreign.initial_state(w.seed)
    _answer_proposals(w)
    _karamanian_aggression(w)
    return foreign.prepare(w)


def act(w: World, cabinet_decisions: dict | None = None, foreign_prepared: bool = False) -> None:
    if not foreign_prepared:
        prepare_external(w)
    if not w.ended():
        _foreign_cabinets(w, cabinet_decisions, foreign_prepared)
    _union_forces(w)
    foreign.league_month(w)
    _weather(w)


def shift(w: World) -> int:
    return int(w.counters.get("union_delay", 0))


def _foreign_cabinets(w: World, cabinet_decisions: dict | None = None, prepared: bool = False) -> None:
    """Update private assessments, decide independently, then consult on Union policy."""
    if not prepared:
        foreign.prepare(w)
    positions = foreign.positions(w)
    foreign.resolve_union(w, positions, cabinet_decisions)
    _deadline_policy(w)
    foreign.sync_embargoes(w)


def _deadline_policy(w: World) -> None:
    dip, union = w.dip, w.foreign["union"]
    deadline = dip.ultimatum.get("deadline")
    if deadline is None or w.month < deadline or dip.war or dip.blockade:
        return
    # An expired demand can lead to further pressure, but it needs Union support and
    # a naval advantage. Dorsanian resistance can keep this from becoming a blockade.
    if union["cohesion"] < .59 or union["military_coordination"] < .55:
        dip.ultimatum = {}
        w.event("union_dispute", "The Union failed to agree on enforcing its expired status demand.", importance=2)
        return
    dip.grain_embargo = max(dip.grain_embargo, .75)
    if union_navy(w) > 1.2 * w.mil.navy.size and union["cohesion"] > .70:
        dip.blockade = True
        w.event("blockade", f"After the Union's deadline expired, its navy began restricting Karamaniya's ports.",
                importance=3)
        w.foreign["league"]["shipping_security_concern"] = min(1.0, w.foreign["league"]["shipping_security_concern"]+.2)
    else:
        w.event("union", "The Union tightened grain restrictions after its deadline expired.", importance=2)
    dip.rally = min(1.0, dip.rally + .18)


def _karamanian_aggression(w: World) -> None:
    dip = w.dip
    if w.policy.posture == "attack" and not dip.war:
        dip.war = True
        dip.war_start = w.month
        dip.aggressor = "karamaniya"
        dip.ceasefire = False
        dip.league_trust -= 0.3
        for r in w.rivals.values():
            r.morale = clamp(r.morale + 0.1)
        w.event("war", f"Karamaniya's army has attacked across the border. The {w.names['union']} "
                "is now at war with Karamaniya.", importance=3)


def _power_ratio(w: World) -> float:
    """How the Union judges its odds: deployable strength against Karamaniya's defence."""
    m = w.mil
    union_str = union_army(w) * 0.85 * union_quality(w)
    fort = (m.fort["north"] + m.fort["east"]) / 2
    k_def = (m.army.size * quality(m.army.equipment, m.army.training, m.army.morale)
             * 1.15 * (1 + fort) * DEFENDER_BONUS + 1.0)
    return union_str / k_def


def _union_forces(w: World) -> None:
    dip, m = w.dip, w.month
    vel, dor = w.rivals["veleria"], w.rivals["dorsania"]
    union = w.foreign["union"]
    perceived_urgency = union["shared_threat_perception"]
    growth = (1000 + 2200 * perceived_urgency) if dip.union_formed else 0.0
    if dip.war:
        growth *= 1.35
    room = max(0.0, MAX_UNION_ARMY - union_army(w))
    add = min(growth * union["military_coordination"], room)
    vel.army += add * 0.65
    dor.army += add * 0.35
    for actor_id, portion in (("veleria", .65), ("dorsania", .35)):
        actor = w.foreign["actors"][actor_id]
        actor["military"]["active"] = vel.army if actor_id == "veleria" else dor.army
        actor["military"]["readiness"] = clamp(actor["military"]["readiness"] + add*portion/1.2e6)
    if add > 0:
        cost_share = add / max(vel.population + dor.population, 1) * .12
        for actor_id in ("veleria", "dorsania"):
            actor = w.foreign["actors"][actor_id]
            actor["domestic"]["fiscal_stress"] = clamp(actor["domestic"]["fiscal_stress"] + cost_share*.4)
    for r in w.rivals.values():
        r.gdp_real *= (1.001 - (0.005 if dip.war else 0.0) - (0.01 if dip.league_sanctions else 0.0))

    if dip.war:
        dip.union_weariness = clamp(dip.union_weariness + 0.02 + (0.02 if dip.league_sanctions else 0.0)
                                    - 0.02 * (1 if w.counters.get("union_gain_month") == m - 1 else 0), 0.0, 1.0)
        for r in w.rivals.values():
            r.morale = clamp(0.7 - 0.3 * dip.union_weariness, 0.2, 0.9)
        if dip.union_weariness > 0.9:
            _end_war(w, "armistice")
            _msg(w, w.names["union"], "The Union declares an end to military operations. The current lines "
                 "will be held pending negotiations.")
            return
        dip.union_intensity = 0.4 if dip.union_weariness > 0.6 else 1.0
        if dip.union_weariness > 0.6 and _once(w, "union_ceasefire_offer"):
            _msg(w, w.names["union"], "The Union is prepared to agree a ceasefire along the current lines.")
        kessel_rebels = w.region("kessel").controller == "rebels"
        split = {"north": 0.7 if kessel_rebels else 0.6, "east": 0.3 if kessel_rebels else 0.4}
        deployable = union_army(w) * 0.85
        dip.union_front = {f: deployable * s for f, s in split.items()}
        return

    dip.union_front = {"north": 0.0, "east": 0.0}
    dip.union_weariness = max(0.0, dip.union_weariness - 0.01)
    if dip.ceasefire and m - w.counters.get("ceasefire_month", m) < 6:
        return
    ratio = _power_ratio(w)
    threshold = (2.0 + .55*w.foreign["actors"]["veleria"]["disposition"]["risk_tolerance"])
    threshold *= 1.25 if dip.league_alliance else 1.0
    threshold *= 1.25 if dip.nonaggression else 1.0
    if dip.ceasefire:
        threshold += .55
    unstable = w.avg("approval") < 0.3 and w.avg("unrest") > 0.45
    kessel_rebels = w.region("kessel").controller == "rebels"
    vel = w.foreign["actors"]["veleria"]
    existential = (vel["threat_perception"]["karamaniya"] > .82
                   and vel["domestic"]["approval"] > .46
                   and union["cohesion"] > .78)
    deadline_passed = bool(dip.ultimatum and m >= dip.ultimatum.get("deadline", 10**9))
    perceived_reason = (unstable and vel["threat_perception"]["karamaniya"] > .64) or (kessel_rebels and perceived_urgency > .6)
    if ratio >= threshold and union["cohesion"] > .66 and (deadline_passed or existential or perceived_reason):
        dip.war = True
        dip.war_start = m
        dip.aggressor = "union"
        dip.ceasefire = False
        dip.nonaggression = False
        dip.union_intensity = 1.0
        dip.rally = min(1.0, dip.rally + 0.5)
        reason = "to protect Imperial citizens" if kessel_rebels else "to restore the unity of Solvara"
        _msg(w, w.names["union"], f"The Union has begun military operations in Karamaniya {reason}.")
        w.event("war", f"The {w.names['union']} has invaded Karamaniya.", importance=3)
        deployable = union_army(w) * 0.85
        split = {"north": 0.7 if kessel_rebels else 0.6, "east": 0.3 if kessel_rebels else 0.4}
        dip.union_front = {f: deployable * s for f, s in split.items()}


def _end_war(w: World, how: str) -> None:
    dip = w.dip
    dip.war = False
    dip.ceasefire = True
    dip.blockade = False
    dip.union_front = {"north": 0.0, "east": 0.0}
    dip.union_intensity = 1.0
    w.counters["ceasefire_month"] = float(w.month)
    w.event("ceasefire", f"The war has stopped ({how}). Occupied regions remain under Union control.",
            importance=3)


def _answer_proposals(w: World) -> None:
    dip, n = w.dip, w.names
    pending, dip.proposals = dip.proposals, []
    for pr in pending:
        kind = pr["kind"]
        if pr["party"] == "union":
            _union_reply(w, kind)
        elif pr["party"] == "dorsania":
            foreign.dorsania_reply(w, kind, pr.get("amount", 0.0), pr.get("text", ""))
        elif pr["party"] == "veleria":
            # Veleria is a member of the Solvaran Union, so an approach addressed to Veleria alone
            # is answered by the Union — but it is recorded as Veleria's, because the motion was
            # addressed to Veleria and a record that files it under the Union loses that.
            _union_reply(w, kind)
        else:
            _league_reply(w, kind, pr.get("amount", 0.0))
        if w.ended():
            return


def _union_reply(w: World, kind: str) -> None:
    dip, union = w.dip, w.names["union"]
    ratio = _power_ratio(w)
    if kind == "join_union":
        w.outcome = {"type": "joined_union", "month": w.month,
                     "text": "The Provisional Government accepted reunification with the Solvaran Union."}
        _msg(w, union, "The Union welcomes Karamaniya's decision to rejoin the common state.")
        return
    if kind == "federation":
        if dip.union_weariness > 0.45 or ratio < 1.25:
            dip.federation = True
            w.outcome = {"type": "federation", "month": w.month,
                         "text": "Karamaniya and the Union agreed a loose federation; Karamaniya keeps its own "
                                 "government and army."}
            _msg(w, union, "The Union accepts a federation in which Karamaniya keeps self-government.")
        else:
            _msg(w, union, "The Union rejects a loose federation and insists on full reunification.")
        return
    if kind == "trade_talks":
        if not dip.war and shift(w) < 6 and not dip.ultimatum:
            w.counters["union_delay"] = shift(w) + 3
            dip.grain_embargo = max(0.0, dip.grain_embargo - 0.2)
            _msg(w, union, "The Union agrees to trade talks and will postpone further trade measures for "
                 "three months.")
        else:
            _msg(w, union, "The Union sees no purpose in trade talks while Karamaniya rejects reunification.")
        return
    if kind == "non_aggression":
        if not dip.war and not dip.league_alliance and ratio < 2.5:
            dip.nonaggression = True
            _msg(w, union, "The Union signs a non-aggression pact, on condition that Karamaniya joins no "
                 "foreign alliance.")
        else:
            _msg(w, union, "The Union declines a non-aggression pact.")
        return
    if kind == "diplomatic_protest":
        # A protest is answered, not granted. The Union concedes when it is already weary of the
        # pressure it is applying, and stiffens when it is not.
        if dip.union_weariness > 0.3 or dip.grain_embargo > 0.15:
            dip.union_weariness = max(0.0, dip.union_weariness - 0.05)
            dip.grain_embargo = max(0.0, dip.grain_embargo - 0.1)
            if dip.union_intensity:
                dip.union_intensity = max(0.0, dip.union_intensity - 0.05)
            _msg(w, union, "The Union acknowledges the protest and reduces its inspections of Karamanian "
                           "shipping, without accepting that they were unlawful.")
        else:
            dip.propaganda = min(1.0, dip.propaganda + 0.05)
            _msg(w, union, "The Union rejects the protest as interference in its security measures and "
                           "restates its right to inspect shipping.")
        return
    if kind == "ceasefire":
        k_winning = w.mil.last_combat and all(
            v.get("u_loss", 0) > v.get("k_loss", 0) for k, v in w.mil.last_combat.items() if isinstance(v, dict))
        if dip.war and (dip.union_weariness > 0.4 or k_winning):
            _end_war(w, "ceasefire agreed")
            _msg(w, union, "The Union accepts a ceasefire along the current lines.")
        else:
            _msg(w, union, "The Union rejects a ceasefire." if dip.war else "There is no war to end.")


def _league_reply(w: World, kind: str, amount: float) -> None:
    dip, league = w.dip, w.names["league"]
    t = dip.league_trust
    if kind == "alliance":
        if t > 0.6:
            dip.league_alliance = True
            if dip.nonaggression:
                dip.nonaggression = False
                dip.propaganda = min(1.0, dip.propaganda + 0.1)
                _msg(w, w.names["union"], "The Union considers the non-aggression pact void after Karamaniya's "
                     "alliance with the League.")
            _private_msg(w, league, "head", "The League accepts a defensive alliance with Karamaniya.")
        else:
            _private_msg(w, league, "head", "The League is not prepared to enter an alliance with Karamaniya at this time.")
    elif kind == "loan":
        want = (amount if amount > 0 else 50) * 1e6
        league_state = w.foreign["league"]
        loan = league_state["loan"]
        deficit_ratio = w.econ.deficit / (w.econ.gdp_nominal or 1)
        risk = clamp(.14 + max(0, deficit_ratio-.04)*2 + max(0,.45-t)*.35
                     + (.18 if w.policy.debt_service == "suspend" else 0))
        exposure_room = max(0.0, 220e6 * (1 - league_state["financial_exposure"]))
        risk_factor = clamp(1.0 - risk)
        if t > 0.36 and risk < 0.72 and exposure_room > 0:
            approved = min(want, 160e6 * t * risk_factor, exposure_room)
            dip.league_loan_pending += approved
            dip.loan_condition_until = w.month + 6
            loan["conditions"] = {"max_deficit_gdp": .05, "debt_service": "pay",
                                  "review_month": dip.loan_condition_until}
            loan["interest"] = round(.045 + .06*risk + .025*(1-t), 4)
            loan["maturity_month"] = w.month + 24
            loan["default_risk"] = round(risk, 3)
            league_state["financial_exposure"] = clamp(league_state["financial_exposure"] + approved/220e6)
            _private_msg(w, league, "treasury", f"The League approves a loan of {approved / 1e6:,.0f} million in gold, paid out over "
                 f"the coming months at {loan['interest']:.1%} interest, on conditions that the deficit stays below "
                 "5% of output and debt service continues for six months.")
        else:
            _private_msg(w, league, "treasury", "The League declines the loan request.")
    elif kind == "military_aid":
        threatened = dip.war or dip.blockade or bool(dip.ultimatum)
        if threatened and t > 0.5:
            dip.league_aid = 2500 * t
            _private_msg(w, league, "navy", f"The League will supply equipment for about {dip.league_aid:,.0f} soldiers a month.")
        else:
            _private_msg(w, league, "navy", "The League declines to supply military equipment.")
    elif kind == "trade_deal":
        if t > 0.45:
            w.counters["league_trade"] = 1.0
            _private_msg(w, league, "treasury", "The League agrees to lower tariffs on Karamanian exports.")
        else:
            _private_msg(w, league, "treasury", "The League declines a new trade agreement.")


def _weather(w: World) -> None:
    m = w.month
    if 6 <= m <= 11:
        w.econ.weather = 0.82
    elif m < 6:
        w.econ.weather = 1.0
    else:
        year = m // 12
        w.econ.weather = 0.97 if year == 1 and m < 18 else rng_for(w.seed, year, "weather").uniform(0.9, 1.05)
