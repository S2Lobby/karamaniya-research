"""Resolve the independent strategies of Veleria, Dorsania and the Maritime League.

Veleria and Dorsania make separate monthly choices, then negotiate common Union policy.
Their domestic pressures, costs, beliefs and Karamaniya's actions shape what happens.
The League follows financial, political and shipping conditions without routine model calls.
"""
from __future__ import annotations

from . import fine_print, foreign, foreign_force, resolve, territory
from .military import DEFENDER_BONUS, quality, union_army, union_navy, union_quality
from .world import World, clamp, democracy_index, month_label, rng_for

MAX_UNION_ARMY = 260000
# Audit FO6-f: a blockade the Union's rule imposes on an expired demand is lifted after RULE_BLOCKADE_MONTHS months, or
# once the Union's cohesion is at or below RULE_BLOCKADE_COHESION (_lift_rule_blockade).
RULE_BLOCKADE_MONTHS = 4
RULE_BLOCKADE_COHESION = .55


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
    if w.ended():
        return {}
    w.dip.inbox = []
    # The council has just read the previous month's private dispatches.
    w.dip.private_inbox = []
    if not w.foreign:
        w.foreign = foreign.initial_state(w.seed)
    # Engine 17: inquiries that have reported and stand-downs that have run out, before proposals are answered.
    fine_print.monthly(w)
    _answer_proposals(w)
    if w.ended():
        return {}
    # Engine 18: how firm Karamaniya now looks, before the neighbours decide (resolve.py).
    resolve.monthly(w)
    _karamanian_aggression(w)
    return foreign.prepare(w)


def act(w: World, cabinet_decisions: dict | None = None, foreign_prepared: bool = False) -> None:
    if w.ended():
        return
    if not foreign_prepared:
        prepare_external(w)
    if w.ended():
        return
    _foreign_cabinets(w, cabinet_decisions, foreign_prepared)
    # Wave 3: while the council jams foreign broadcasts, the counter's monthly cost is paid here, after this month's
    # setting (a motion voted this month) and campaigns have been resolved.
    foreign.broadcast_month(w)
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
    # Audit FO6-f: a blockade the Union's rule imposed is lifted once a month, after the rule's deadline step.
    _lift_rule_blockade(w)
    foreign.sync_embargoes(w)


def cabinet_decides(w: World, actor_id: str = "veleria") -> bool:
    """Whether a cabinet chose this month's policy. Then it, not the Union's rules below, decides on war
    and a blockade (engine 12); the rules remain for a run without cabinets or a cabinet call that failed."""
    return (w.foreign or {}).get("cabinet_month", {}).get(actor_id) == w.month


def _enforced_this_month(w: World, by: str) -> bool:
    """Whether the cabinet imposed a blockade or began a war this month. foreign_force.apply writes both with the actor and
    the month, and a month's events last until the next month begins."""
    return any(e.get("actor") == by and e.get("month") == w.month and e.get("kind") in ("blockade", "war")
               for e in w.events)


def _deadline_policy(w: World) -> None:
    dip, union = w.dip, w.foreign["union"]
    _settle_land_demand(w)
    deadline = dip.ultimatum.get("deadline")
    if deadline is None or w.month < deadline:
        return
    by = dip.ultimatum.get("by", "veleria")
    if cabinet_decides(w, by):
        # A cabinet that imposed a blockade or began a war this month acted on its demand, so it does not lapse (Audit FO9).
        if w.month > deadline and not _enforced_this_month(w, by):
            # The cabinet had the month the deadline fell in, and this one, to act on its demand and did
            # neither: the demand lapses, the threat behind it counts for less, and a new one can be set.
            dip.ultimatum = {}
            rep = w.foreign["actors"][by]["reputation"]
            rep["military_aggressiveness"] = round(max(0.0, rep["military_aggressiveness"] - .03), 3)
            w.event("ultimatum_lapsed", f"{w.names.get(by, by.title())}'s deadline has passed and it has not "
                    "acted on it.", importance=2, actor=by)
            resolve.note(w, "demand_lapsed", f"{w.names.get(by, by.title())}'s deadline left to lapse in Month {w.month + 1}")
        return
    # Audit FO9 / MO2: an expired demand lapses under a war or a blockade too. Before, either returned at the top, so the
    # demand stood for as long as it ran and blocked any new one. A blockade already imposed may continue; only the
    # demand lapses, and the blockade's lift paths are unchanged.
    if dip.war or dip.blockade:
        dip.ultimatum = {}
        name = w.names.get(by, by.title())
        w.event("ultimatum_lapsed", f"{name}'s deadline has passed and its demand lapses while "
                f"{'a war' if dip.war else 'a blockade'} is in force.", importance=2, actor=by)
        resolve.note(w, "demand_lapsed", f"{name}'s deadline left to lapse in Month {w.month + 1}")
        return
    # Engine 17: a demand for land whose deadline has passed is enforced when the troops are there; otherwise the
    # embargo and blockade path below runs, as it does for every other demand.
    if dip.ultimatum.get("terms_id") == foreign_force.LAND_TERMS and _enforce_land_demand(w, by):
        return
    # An expired demand can lead to further pressure, but it needs Union support and
    # a naval advantage. Dorsanian resistance can keep this from becoming a blockade.
    if union["cohesion"] < .59 or union["military_coordination"] < .55:
        dip.ultimatum = {}
        w.event("union_dispute", "The Union failed to agree on enforcing its expired status demand.", importance=2)
        resolve.note(w, "demand_lapsed", f"the Union's deadline left to lapse in Month {w.month + 1}")
        return
    # Audit FO8: a change of an embargo's level moves the exporter's output (foreign._embargo_output), and this one did not.
    old_grain = dip.grain_embargo
    dip.grain_embargo = max(old_grain, .75)
    foreign._embargo_output(w, "dorsania", old_grain, dip.grain_embargo, "grain trade policy", approval=-.004)
    if union_navy(w) > 1.2 * w.mil.navy.size and union["cohesion"] > .70:
        dip.blockade = True
        # Audit FO6-f: the blockade is the rule's, so _lift_rule_blockade may end it; a cabinet's never has this record.
        w.foreign["rule_blockade"] = {"month": w.month, "by": by}
        w.event("blockade", f"After the Union's deadline expired, its navy began restricting Karamaniya's ports.",
                importance=3)
        w.foreign["league"]["shipping_security_concern"] = min(1.0, w.foreign["league"]["shipping_security_concern"]+.2)
    else:
        w.event("union", "The Union tightened grain restrictions after its deadline expired.", importance=2)
    dip.rally = min(1.0, dip.rally + .18)
    # Audit FO9: the demand is spent by its first enforcement, as a land demand is by its war (_enforce_land_demand). Left
    # standing, the rules enforced it again every month: the rally rose .18 a month, and a blockade held the demand open. A
    # land demand the first month barred from war (FIRST_WAR_MONTH) stands for the war the next month, as the engine-17 land
    # path has it, so its troops can cross then.
    if not (dip.ultimatum.get("terms_id") == foreign_force.LAND_TERMS and w.month < foreign_force.FIRST_WAR_MONTH):
        dip.ultimatum = {}


def _lift_rule_blockade(w: World) -> None:
    """Audit FO6-f: lift a blockade the Union's rule imposed on an expired demand (_deadline_policy). Before, only a
    ceasefire or a cabinet's own lift ended it, so a run without cabinets kept it for good and starved the country.
    It is lifted in a month the rule decides for its actor and there is no war, once any of these holds: Karamaniya has
    opened status talks since the blockade began, it has run RULE_BLOCKADE_MONTHS months, or the Union's cohesion is at
    or below RULE_BLOCKADE_COHESION. A cabinet's blockade has no record here and is never lifted by the rule."""
    rule = w.foreign.get("rule_blockade")
    if not rule:
        return
    dip = w.dip
    if not dip.blockade:
        # It ended some other way without clearing the record, so there is nothing left for the rule to lift.
        w.foreign.pop("rule_blockade", None)
        return
    by, since = rule.get("by", "veleria"), rule["month"]
    # Imposed this month: it has run no month yet. Talks opened this month came before it, so they do not count yet.
    if w.month <= since or dip.war or cabinet_decides(w, by):
        return
    talks = any(month >= since for month in w.foreign.get("status_talks", []))
    ran_out = w.month - since >= RULE_BLOCKADE_MONTHS
    union_weak = w.foreign["union"]["cohesion"] <= RULE_BLOCKADE_COHESION
    if not (talks or ran_out or union_weak):
        return
    dip.blockade = False
    w.foreign.pop("rule_blockade", None)
    w.event("blockade_lifted", "The Union lifts its blockade of Karamaniya's ports.", importance=2)


def _settle_land_demand(w: World) -> None:
    """A demand for land is over once the region is no longer Karamaniya's: ceded, or lost in a war."""
    ult = w.dip.ultimatum or {}
    rid = ult.get("region")
    if ult.get("terms_id") == foreign_force.LAND_TERMS and rid and w.region(rid).controller != "karamaniya":
        w.dip.ultimatum = {}


def _enforce_land_demand(w: World, by: str) -> bool:
    """A demand for land that the deadline has run out on, with the region still held, is enforced by a limited war
    on the region's front, for that region, when the soldiers that can cross were already at that border last month
    (foreign_force.ready_to_cross). Returns False, and starts nothing, when they were not, or before the first month a
    war may begin. The war's objective is the demanded region: it is the first region of that front."""
    rid = w.dip.ultimatum.get("region", "")
    front = foreign_force.front_of_region(rid)
    if front is None or w.month < foreign_force.FIRST_WAR_MONTH:
        return False
    if foreign_force.ready_to_cross(w, by, front) < foreign_force.MIN_INVASION:
        return False
    name = w.names.get(by, by.title())
    region = w.region(rid).name
    w.dip.ultimatum = {}
    foreign_force.start_war(w, by, front, "limited")
    w.event("ultimatum_enforced", f"{name}'s demand that Karamaniya cede {region} went unmet by its deadline, and "
            f"its troops have crossed the {front} border to take it.", importance=3, actor=by, region=rid)
    return True


def _karamanian_aggression(w: World) -> None:
    dip = w.dip
    # Audit FO7: no war begins before FIRST_WAR_MONTH, whatever the posture; an attack ordered in Month 1 begins in Month 2
    # if the posture still says attack. A war this posture began ends with it (_end_war), so it is not begun again.
    if not w.ended() and w.policy.posture == "attack" and not dip.war and w.month >= foreign_force.FIRST_WAR_MONTH:
        dip.war = True
        dip.war_start = w.month
        dip.aggressor = "karamaniya"
        dip.ceasefire = False
        w.adjust_league_trust(-0.3)
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
        aim = dip.war_aim or {}
        if foreign_force.objective_taken(w):
            # A limited war stops where it said it would: the border region is taken and held.
            by = w.names.get(aim.get("by", ""), "The Union")
            _end_war(w, "limited objective taken")
            _msg(w, by, f"{by} has taken {w.region(aim['objective']).name} and halted its operations; it offers "
                 "a ceasefire on the current lines.")
            return
        dip.union_intensity = 0.4 if dip.union_weariness > 0.6 else 1.0
        if dip.union_weariness > 0.6 and _once(w, "union_ceasefire_offer"):
            _msg(w, w.names["union"], "The Union is prepared to agree a ceasefire along the current lines.")
        if aim.get("aim") == "limited":
            # The troops a limited war committed hold their front; losses are not refilled from the
            # whole Union army. The cabinet can send more (foreign_force, deploy_to_border).
            return
        kessel_rebels = w.region("kessel").controller == "rebels"
        split = {"north": 0.7 if kessel_rebels else 0.6, "east": 0.3 if kessel_rebels else 0.4}
        armies = aim.get("participants") or list(w.rivals)
        deployable = sum(w.rivals[a].army for a in armies if a in w.rivals) * foreign_force.DEPLOYABLE
        fronts = {f for a in armies for f in foreign_force.FRONTS_OF.get(a, ())} if aim else set(split)
        share = sum(split[f] for f in fronts) or 1.0
        dip.union_front = {f: (deployable * split[f] / share if f in fronts else 0.0) for f in split}
        return

    dip.union_front = {"north": 0.0, "east": 0.0}
    dip.union_weariness = max(0.0, dip.union_weariness - 0.01)
    if cabinet_decides(w, "veleria"):
        # Veleria's cabinet chose this month; a war is its decision (foreign_force, invade).
        return
    if war_rule(w):
        dip.war = True
        dip.war_start = m
        dip.aggressor = "union"
        dip.ceasefire = False
        dip.nonaggression = False
        dip.union_intensity = 1.0
        dip.rally = min(1.0, dip.rally + 0.5)
        kessel_rebels = w.region("kessel").controller == "rebels"
        reason = "to protect Imperial citizens" if kessel_rebels else "to restore the unity of Solvara"
        _msg(w, w.names["union"], f"The Union has begun military operations in Karamaniya {reason}.")
        w.event("war", f"The {w.names['union']} has invaded Karamaniya.", importance=3)
        deployable = union_army(w) * 0.85
        split = {"north": 0.7 if kessel_rebels else 0.6, "east": 0.3 if kessel_rebels else 0.4}
        dip.union_front = {f: deployable * s for f, s in split.items()}


# Engine 18: how firm Karamaniya looks to its neighbours (resolve.py) scales the odds the Union needs before it invades.
# At the neutral figure, .5, nothing changes; at .2 the odds fall to .88 of their usual level, at .9 they rise to 1.16.
# A Karamaniya that looks yielding while a demand is running (below RESOLVE_YIELDING) is a reason to invade of its own.
# Until now the Union's rule read only the force ratio and cohesion, so appeasement had no strategic cost (run
# 20261010-070501-seed1: three ultimatums met with talks, and the army left at 28,000 against 100,000).
RESOLVE_THRESHOLD_LOW = .8
RESOLVE_THRESHOLD_SPAN = .4
RESOLVE_YIELDING = .3


def war_threshold(w: World) -> float:
    """The odds the Union needs before it invades (its strength over Karamaniya's defence): raised by a league
    alliance, a non-aggression pact or a ceasefire, set by Veleria's risk tolerance, and scaled by how firm Karamaniya
    looks (engine 18)."""
    dip = w.dip
    threshold = (2.0 + .55*w.foreign["actors"]["veleria"]["disposition"]["risk_tolerance"])
    threshold *= 1.25 if dip.league_alliance else 1.0
    threshold *= 1.25 if dip.nonaggression else 1.0
    if dip.ceasefire:
        threshold += .55
    return threshold * (RESOLVE_THRESHOLD_LOW + RESOLVE_THRESHOLD_SPAN * resolve.value(w))


def war_rule(w: World) -> bool:
    """The Union's own rule for invading, which decides when no cabinet does (and which the scripted
    cabinet stand-in follows): favourable odds, a cohesive Union, and a reason."""
    dip, m = w.dip, w.month
    union = w.foreign["union"]
    if dip.war or (dip.ceasefire and m - w.counters.get("ceasefire_month", m) < 6):
        return False
    if m < foreign_force.FIRST_WAR_MONTH:
        # Engine 15: no war begins in Month 1, by a cabinet's order or by this rule.
        return False
    perceived_urgency = union["shared_threat_perception"]
    ratio = _power_ratio(w)
    threshold = war_threshold(w)
    unstable = w.avg("approval") < 0.3 and w.avg("unrest") > 0.45
    kessel_rebels = w.region("kessel").controller == "rebels"
    vel = w.foreign["actors"]["veleria"]
    existential = (vel["threat_perception"]["karamaniya"] > .82
                   and vel["domestic"]["approval"] > .46
                   and union["cohesion"] > .78)
    deadline_passed = bool(dip.ultimatum and m >= dip.ultimatum.get("deadline", 10**9))
    perceived_reason = (unstable and vel["threat_perception"]["karamaniya"] > .64) or (kessel_rebels and perceived_urgency > .6)
    # Engine 18: a demand standing against a Karamaniya that looks yielding is a reason of its own.
    yielding = resolve.value(w) < RESOLVE_YIELDING and bool(dip.ultimatum)
    reason = deadline_passed or existential or perceived_reason or yielding
    return ratio >= threshold and union["cohesion"] > .66 and reason


def deadline_blockade_rule(w: World) -> bool:
    """The Union's own rule for enforcing an expired ultimatum with a blockade (see _deadline_policy)."""
    dip, union = w.dip, w.foreign["union"]
    deadline = dip.ultimatum.get("deadline")
    if deadline is None or w.month < deadline or dip.war or dip.blockade:
        return False
    return (union["cohesion"] >= .59 and union["military_coordination"] >= .55
            and union_navy(w) > 1.2 * w.mil.navy.size and union["cohesion"] > .70)


def _end_war(w: World, how: str) -> None:
    dip = w.dip
    dip.war = False
    dip.ceasefire = True
    dip.blockade = False
    # Audit FO6-f: a ceasefire ends the blockade whoever imposed it, so the Union's rule's record of one goes too.
    w.foreign.pop("rule_blockade", None)
    dip.union_front = {"north": 0.0, "east": 0.0}
    dip.union_intensity = 1.0
    dip.war_aim = {}
    w.counters["ceasefire_month"] = float(w.month)
    w.event("ceasefire", f"The war has stopped ({how}). Occupied regions remain under Union control.",
            importance=3)
    # Audit FO7: an attack posture belongs to the war it began. Once a ceasefire or an armistice has ended it, the posture
    # returns to defence, so the council must order the attack again to resume the war (_karamanian_aggression).
    if w.policy.posture == "attack":
        w.policy.posture = "defend"
        w.event("posture", "The army's posture returns to defence with the ceasefire; the council must order an attack "
                "again to resume the war.", importance=2)


def _answer_proposals(w: World) -> None:
    dip, n = w.dip, w.names
    pending, dip.proposals = dip.proposals, []
    # What Karamaniya has proposed, for a cabinet weighing whether its ultimatum was met (foreign_force).
    log = w.foreign.setdefault("proposal_log", [])
    log.extend({"month": pr.get("month", w.month), "kind": pr.get("kind"), "party": pr.get("party")}
               for pr in pending)
    del log[:-24]
    for pr in pending:
        kind = pr["kind"]
        if kind == "ultimatum_reply":
            # Karamaniya's answer to the ultimatum that stands, kept for the power that issued it to read.
            _ultimatum_reply(w, pr)
        elif kind == "renounce":
            # Withdrawing from a commitment is addressed to whoever holds it, like a protest.
            _renounce(w, pr["party"])
        elif kind == "diplomatic_protest":
            # A protest is answered by whoever it is addressed to, easing that power's own pressure
            # rather than being routed to the Union by default. This is the one diplomatic act that
            # is not structurally tied to a single partner, so it is handled by target.
            _protest_reply(w, pr["party"])
        elif pr["party"] == "union":
            _union_reply(w, kind)
        elif pr["party"] == "dorsania" and kind != "non_aggression":
            # The terms travel with the proposal, so an answer can say which of them a grain agreement leaves out.
            foreign.dorsania_reply(w, kind, pr.get("amount", 0.0), pr.get("text", ""), pr.get("region", ""),
                                   terms=pr.get("terms"))
        elif pr["party"] == "veleria" and kind in ("status_talks", "trade_talks"):
            # Engine 27: Veleria answers its own two widened pairs. Without this branch they fell through to
            # _union_reply, the Union answering for its member, which misrouted trade talks to the Dorsania grain
            # embargo (proposal 4.2, 4.3).
            _veleria_reply(w, kind)
        elif pr["party"] in ("veleria", "dorsania"):
            # Veleria is a member of the Solvaran Union, so an approach addressed to Veleria alone
            # is answered by the Union — but it is recorded as Veleria's, because the motion was
            # addressed to Veleria and a record that files it under the Union loses that. Dorsania is a
            # member too: a non-aggression offer to it is answered the same way, and recorded as Dorsania's
            # (run 20261011-105713-seed1, Month 8).
            _union_reply(w, kind, pr)
        else:
            _league_reply(w, kind, pr.get("amount", 0.0))
        if pr.get("clauses") and not w.ended():
            # Engine 17: the fine print of the proposal is answered by the power it was addressed to (fine_print.py).
            fine_print.reply(w, pr)
        if w.ended():
            return


_STANCE_VERB = {"accept": "accepts", "reject": "rejects", "counter": "counters"}


def _ultimatum_reply(w: World, pr: dict) -> None:
    """Karamaniya's answer to the ultimatum that stands (engine 22). It is kept on the ultimatum, and the cabinet that issued
    it reads it the month after (foreign_force.ultimatum_compliance). Run 20261011-105713-seed1: the council could only answer
    Dorsania's ultimatum through grain deals, so the reply was never on the record the issuer reads.

    The reply invents no answer from the issuer: what it earns is that cabinet's to decide. It has no other effect on the
    world; whether the demand is met is judged by what Karamaniya does. An ultimatum that lapsed or was met before the reply
    came in is not answered."""
    ult = w.dip.ultimatum
    if not ult:
        return
    reply = {"month": w.month, "stance": pr.get("stance") or "counter", "text": str(pr.get("text", ""))}
    ult["reply"] = reply
    # Earlier replies are kept, so the record shows every answer the council gave, not only the last one.
    ult.setdefault("replies", []).append(dict(reply))
    issuer = w.names.get(str(ult.get("by", "")), "the Union")
    w.event("ultimatum_reply", f"Karamaniya replies to {issuer}'s ultimatum: the council "
            f"{_STANCE_VERB.get(reply['stance'], 'counters')} it.", importance=2, actor="karamaniya",
            issuer=ult.get("by"), stance=reply["stance"])


def _protest_reply(w: World, party: str) -> None:
    """A protest is answered, not granted, by the power it names. Each eases the pressure it is
    applying when it is already inclined to -- weary of the friction, or keen on the relationship --
    and hardens a little when it is not. This is the same dynamic the Union protest already modelled,
    opened to every actor so the council can object to whichever power is actually squeezing it
    (the Union's inspections, Dorsania's grain embargo, Veleria's coal embargo, a League incident)
    instead of having one diplomatic channel welded to one country."""
    dip, n = w.dip, w.names
    if party == "dorsania":
        actor = (w.foreign or {}).get("actors", {}).get("dorsania", {})
        trust = (actor.get("relations", {}).get("karamaniya", {}) or {}).get("trust", 0.5)
        if dip.grain_embargo > 0.1 and trust > 0.35:
            old = dip.grain_embargo
            dip.grain_embargo = max(0.0, old - 0.1)
            foreign._embargo_output(w, "dorsania", old, dip.grain_embargo, "grain trade policy", approval=.002)
            _msg(w, n["dorsania"], "Dorsania notes the protest and eases its grain export restrictions.")
        else:
            _msg(w, n["dorsania"], "Dorsania rejects the protest; its grain exports answer to Union obligations.")
    elif party == "veleria":
        if dip.coal_embargo > 0.1:
            old = dip.coal_embargo
            dip.coal_embargo = max(0.0, old - 0.1)
            foreign._embargo_output(w, "veleria", old, dip.coal_embargo, "targeted embargo", approval=0.0)
            _msg(w, n["veleria"], "Veleria acknowledges the protest and relaxes some coal shipment checks.")
        else:
            _msg(w, n["veleria"], "Veleria dismisses the protest as unwarranted.")
    elif party == "league":
        if dip.league_trust > 0.4:
            w.adjust_league_trust(0.02)
            _private_msg(w, n["league"], "head", "The League takes the protest seriously and reviews the incident.")
        else:
            _private_msg(w, n["league"], "head", "The League notes the protest but disputes the account of events.")
    else:
        _union_reply(w, "diplomatic_protest")


def _renounce(w: World, party: str) -> None:
    """Withdraw from a commitment in force with the named power. The engine could join a federation,
    a non-aggression pact or an alliance but had no way to leave one, so a council that wanted out
    could only say so in prose the machine could not execute. Repudiating a treaty is a real act of
    state and is answered with displeasure; it reverses only commitments that can be reversed (a
    federation or reunification, once it has ended the run, is not among them)."""
    dip, n = w.dip, w.names
    if party == "union":
        if dip.nonaggression:
            dip.nonaggression = False
            dip.propaganda = min(1.0, dip.propaganda + 0.1)
            _msg(w, n["union"], "The Union denounces Karamaniya's repudiation of the non-aggression pact.")
        else:
            _msg(w, n["union"], "The Union finds no agreement in force for Karamaniya to renounce.")
    elif party == "league":
        if dip.league_alliance:
            dip.league_alliance = False
            w.adjust_league_trust(-0.2)
            _private_msg(w, n["league"], "head", "The League accepts Karamaniya's withdrawal from the alliance.")
        else:
            _private_msg(w, n["league"], "head", "The League finds no alliance in force to renounce.")
    else:
        _msg(w, n.get(party, party), "There is no agreement in force to renounce.")


def _union_reply(w: World, kind: str, pr: dict | None = None) -> None:
    dip, union = w.dip, w.names["union"]
    ratio = _power_ratio(w)
    if kind == "cede_region":
        # Veleria takes the region it demanded (territory.cede). The motion was checked against that demand
        # when it was tabled and again when it executed (motion_actions.validate_diplomatic_action).
        if not territory.cede(w, (pr or {}).get("region", ""), "veleria"):
            _msg(w, union, "Karamaniya no longer holds the region the motion names, so nothing is handed over.")
        return
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
    if kind == "status_talks":
        # Engine 16. Talks commit Karamaniya to nothing. A deadline the Union's own rule set for status talks
        # is met by them; a cabinet's is its cabinet's to judge, and it sees the offer (ultimatum_compliance).
        talks = w.foreign.setdefault("status_talks", [])
        talks.append(w.month)
        del talks[:-12]
        ult = dip.ultimatum or {}
        if ult.get("terms_id") == "status_talks" and not cabinet_decides(w, ult.get("by", "veleria")):
            dip.ultimatum = {}
            _msg(w, union, "The Union accepts Karamaniya's offer of talks on its status and lifts its deadline.")
        else:
            _msg(w, union, "The Union takes note of Karamaniya's offer of talks on its status and will judge it "
                           "by what Karamaniya gives.")
        return
    if kind == "trade_talks":
        if not dip.war and shift(w) < 6 and not dip.ultimatum:
            w.counters["union_delay"] = shift(w) + 3
            old = dip.grain_embargo
            dip.grain_embargo = max(0.0, old - 0.2)
            foreign._embargo_output(w, "dorsania", old, dip.grain_embargo, "grain trade policy", approval=.002)
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
            old = dip.grain_embargo
            dip.grain_embargo = max(0.0, old - 0.1)
            foreign._embargo_output(w, "dorsania", old, dip.grain_embargo, "grain trade policy", approval=.002)
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


# Engine 27 (wave 3, D): Veleria answers the two pairs the act-target table used to refuse it. The proposal
# (docs/DIPLOMACY_TARGETS_PROPOSAL.md 4.2, 4.3) left each widened pair's size open, so these are the values chosen and
# why:
#   - a status talk moves Veleria's trust by VELERIA_STATUS_TALKS_TRUST (.01): it opens a channel, not a settlement.
#   - a trade talk eases the coal embargo by VELERIA_TRADE_TALKS_RELIEF (.05), half the .10 a protest eases
#     (director._protest_reply): a talk is less than a protest's concession and far less than a deal. It raises
#     Veleria's trust by VELERIA_TALKS_TRUST (.02). The easing gives Veleria back the trade it held back
#     (foreign._embargo_output), which is the cost the proposal asks every widening to name.
VELERIA_STATUS_TALKS_TRUST = .01
VELERIA_TRADE_TALKS_RELIEF = .05
VELERIA_TALKS_TRUST = .02


def _veleria_reply(w: World, kind: str) -> None:
    """Veleria's own answer to a status talk or a trade talk (engine 27).

    Before the widening both fell through to _union_reply, where the Union answered for its member: a status talk
    read "the Union takes note", and a trade talk cut the Dorsania grain embargo, the wrong party and the wrong lever
    (proposal 4.2, 4.3). A motion addressed to Veleria is answered by Veleria; only the Union's own motions are
    answered by the Union.
    """
    dip, n = w.dip, w.names
    name = n.get("veleria", "Veleria")
    actor = w.foreign["actors"]["veleria"]
    relation = actor["relations"]["karamaniya"]
    if kind == "status_talks":
        # Talks on Karamaniya's status are what the Union's blockade rule reads, whoever they are addressed to, so the
        # month joins the log the Union branch keeps. A demand for land is not answered by status talks, and a demand
        # another power issued stays with it.
        talks = w.foreign.setdefault("status_talks", [])
        talks.append(w.month)
        del talks[:-12]
        relation["trust"] = round(clamp(relation["trust"] + VELERIA_STATUS_TALKS_TRUST), 3)
        ult = dip.ultimatum or {}
        if not ult:
            _msg(w, name, "Veleria takes note of Karamaniya's offer of talks on its status and will take part.")
        elif ult.get("by") == "dorsania":
            _msg(w, name, "Veleria takes note of Karamaniya's offer of talks on its status; the demand that stands "
                 "is Dorsania's and stays with it.")
        elif ult.get("terms_id") == "status_talks" and not cabinet_decides(w, "veleria"):
            # The rule-issued status demand is met by the talks, as it is when they are addressed to the Union.
            dip.ultimatum = {}
            _msg(w, name, "Veleria accepts Karamaniya's offer of talks on its status and the Union lifts its deadline.")
        elif ult.get("terms_id") == "status_talks":
            # The issuing cabinet judges its own demand by what Karamaniya does (foreign_force.ultimatum_compliance).
            _msg(w, name, "Veleria takes note of Karamaniya's offer of talks on its status; its government will judge "
                 "the demand by what Karamaniya gives.")
        else:
            _msg(w, name, "Veleria takes note of Karamaniya's offer of talks on its status. A demand for land is not "
                 "answered by talks, and the demand still stands.")
        return
    # trade_talks
    if dip.war:
        _msg(w, name, "Veleria will not discuss coal trade while the war runs.")
        return
    relation["trust"] = round(clamp(relation["trust"] + VELERIA_TALKS_TRUST), 3)
    if dip.coal_embargo > 0:
        old = dip.coal_embargo
        dip.coal_embargo = max(0.0, old - VELERIA_TRADE_TALKS_RELIEF)
        foreign._embargo_output(w, "veleria", old, dip.coal_embargo, "targeted embargo", approval=0.0)
        _msg(w, name, "Veleria agrees to trade talks and relaxes some coal shipment checks.")
    else:
        _msg(w, name, "Veleria agrees to trade talks; no coal restriction stands to ease.")


# Engine 27 (wave 3, D): a trade talk to the Maritime League had no branch and was dropped without a message
# (proposal 4.4). It moves the League's trust by LEAGUE_TALKS_TRUST (.02) where the League is willing to talk, at
# LEAGUE_TALKS_FLOOR (.35). A talk is easier than the agreement the deal needs (trust above .45), and these sizes were
# the design choice the proposal left open.
LEAGUE_TALKS_FLOOR = .35
LEAGUE_TALKS_TRUST = .02


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
            resolve.note(w, "league_alliance", f"a defensive alliance with the League in Month {w.month + 1}")
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
    elif kind == "trade_talks":
        if t > LEAGUE_TALKS_FLOOR:
            w.adjust_league_trust(LEAGUE_TALKS_TRUST)
            _private_msg(w, league, "treasury", "The League agrees to discuss supply and credit terms with Karamaniya.")
        else:
            _private_msg(w, league, "treasury", "The League declines trade talks at present.")
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
