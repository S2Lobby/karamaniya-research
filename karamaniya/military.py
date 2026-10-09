"""Armed forces: pay, recruitment, equipment, loyalty, combat and the naval blockade.

Every force has two loyalties: to the Karamanian state (its constitution) and a personal
bond to whoever holds its command office. Unpaid troops lose both. Commanders can buy
personal loyalty with patronage, which is what makes a commander dangerous to the rest
of the government.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields as dataclass_fields

from . import audits
from .economy import front_region, labor
from .world import FRONT_CHAINS, World, clamp, rng_for

ARMY_COST = 260.0        # pay and upkeep per soldier per month, start prices
SHIP_COST = 0.55e6       # per ship per month
POLICE_COST = 200.0      # per police officer per month
ARMS_COST = 3000.0       # equipment for one soldier
RECRUIT_RATE = {"none": 0.0, "volunteer": 0.004, "partial": 0.012, "general": 0.03}
DRAFT_WEIGHT = {"workers": 0.5, "farmers": 0.35, "middle": 0.12, "elite": 0.03}
OPS_COST = {"low": 0.0, "medium": 1.0e6, "high": 2.5e6}
ARREST_COST = {"none": 0.0, "targeted": 0.8e6, "mass": 2.5e6}
NAVY_MISSION = {"patrol": 1.0, "escort": 1.2, "break_blockade": 1.4}
SHIP_BUILD_COST = 2.5e6  # per month while building, start prices
DEFENDER_BONUS = 1.5     # attackers need roughly 3:1 locally to advance quickly
ADVANCE_AT = 1.3         # force ratio above which the attacker gains ground
# The officers' pay scale (an Army Command setting): what it does to the army's pay bill, and to the
# morale, loyalty and retention of the corps that runs the army. Pay buys loyalty to the state; patronage
# buys a personal bond with the commander, and officers living on the commander's favours credit the
# state's pay for less. `desert` scales desertion, `training` is a monthly drift from officers staying
# or leaving.
OFFICER_PAY = {
    "freeze": {"bill": .95, "morale": -.05, "loyalty": -.06, "desert": 1.4, "training": -.004},
    "standard": {"bill": 1.0, "morale": 0.0, "loyalty": 0.0, "desert": 1.0, "training": 0.0},
    "raised": {"bill": 1.12, "morale": .04, "loyalty": .05, "desert": .8, "training": .002},
    "premium": {"bill": 1.28, "morale": .07, "loyalty": .08, "desert": .6, "training": .004},
}
PATRONAGE_PAY_CREDIT = .6   # the share of the loyalty from pay that survives an army run on patronage
# How hard the army trains: where training settles, how fast it gets there, what it costs, and what
# it does to the patience of the people doing it. Training feeds `quality()`, so this decides what
# the army can actually do rather than how it is described. Named for intensity, not focus: the
# Army office's operational `training_focus` already decides what the army trains FOR.
TRAINING_INTENSITY = {
    "neglect": {"target": .45, "rate": .012, "bill": .95, "morale": -.02},
    "standard": {"target": .80, "rate": .020, "bill": 1.0, "morale": 0.0},
    "intense": {"target": 1.00, "rate": .030, "bill": 1.10, "morale": -.03},
}
# ---- the trained reserve and mobilization -----------------------------------------------------
# `size` is the active force. Behind it sits a trained pool that can be called up, and calling it up
# is a process, not a number. Comparative active:reserve ratios: United States 1.66:1, United
# Kingdom 2.1:1, Poland 3:1, Israel ~170k active with ~465k reserve, Finland ~24k active behind a
# ~280k wartime establishment and ~900k trained. Karamaniya has no conscription below "partial", so
# 1-4x the active force is the defensible band; each run's own establishment varies inside it from
# the seed rather than being settled by hand.
RESERVE_RATIO = {"none": 1.0, "volunteer": 1.7, "partial": 3.0, "general": 4.0}
RESERVE_BAND = (1.0, 4.0)
RESERVE_SPREAD = 0.12            # how far a run's own establishment sits from its policy's ratio
# Called-up reservists do not become effective at once. US reserve units took 4-8 weeks to reach
# 70-75% strength (20-34 weeks at the bottom of the establishment); the National Guard brigades of
# Desert Storm needed 28-40 days of post-mobilization training; Ukraine's call-up is about 30 days
# of basic plus 2-4 weeks of specialty. So individual fillers are usable almost at once, formed
# units arrive over two to four months, and everyone is only partly effective while training.
MOBILIZATION_TAU = 1.09          # months; ~72% effective at six weeks, ~95% at three months
MOBILIZATION_READY_SHARE = 0.15  # individual fillers, usable on the day they report
MOBILIZATION_TRANSPORT_FLOOR = 0.4   # the slowest a bad transport state can make arrival
# Reserves are not free: the pool costs upkeep every month, an embodied reservist costs a wage, and
# calling one up costs the kit, transport and medical intake to put him back in the field.
RESERVE_UPKEEP_SHARE = 0.08      # of a soldier's monthly cost, per reservist, for drills and kit
RESERVE_KIT_SHARE = 0.15         # of a soldier's equipment cost, to bring stored kit back to standard
RESERVE_ACTIVATION_SHARE = 0.05  # of a soldier's equipment cost, for transport and intake
# ---- supply and readiness as a chain ----------------------------------------------------------
# Operation STRANGLE (RAND R-851) is the finding this models: cutting a force's supply rarely
# collapses it — German ammunition and fuel stocks in Italy actually ROSE during the interdiction,
# because consumption fell faster than deliveries — but denying transport and mobility degraded it
# decisively. Readiness is therefore two links: a stockpile that is forgiving, and movement that is
# not. `effective_quality()` is where the chain reaches the existing `quality()`.
INTERDICTION_TRANSPORT = 0.65    # the mobility lost at the front under total interdiction
TRANSPORT_REACH = 0.35           # share of the gap to that level closed in a month (~3 months)
STOCK_CAP = 1.4                  # a month of fighting is 1.0; stores can be built up past it
DELIVERY_RATE = 0.10             # a month of undisturbed deliveries, in months of fighting
CONSUMPTION_RATE = 0.10          # a month of consumption at full movement and full fighting
IDLE_CONSUMPTION = 0.40          # the share of consumption that survives any collapse of movement
CUT_DELIVERIES = 0.70            # the share of deliveries lost under total interdiction
MOVEMENT_USAGE = 1.5             # consumption falls faster than movement: curtailed operations
TRANSPORT_WEIGHT = 0.70          # movement dominates readiness; the stockpile only cushions
STOCK_WEIGHT = 0.30
READINESS_FLOOR = 0.20
# ---- unit-level response to orders ------------------------------------------------------------
# The army is not one mind. Turkey, July 2016: 8,651 personnel took part — 1.5% of the armed forces
# — and the attempt failed for want of senior-command and other-service support. Venezuela, 2019:
# 0.1-1% defections and no general-level break. South Korea, December 2024: about 280 troops
# deployed, the capital-defence units did not join, martial law lasted about six hours. The USSR,
# August 1991: elite units and division commanders refused. A coup by one commander is therefore
# almost always a small fraction of the force deciding whether to move at all. Singh (Seizing Power,
# 2014) supplies the second half: a unit joins only if it expects enough others to join, so a coup
# that looks like it will fail collapses further. Nothing here is a die roll — given the state, the
# answer is fixed.
BOND_PULL = 0.60        # a commander's personal hold on his own units
ARREARS_PULL = 0.25     # unpaid men follow whoever looks like paying them
ILLEGIT_PULL = 0.40     # orders against an unpopular government cost less to obey
CONTAGION_PULL = 0.45   # what a unit expects other units to do
JOIN_THRESHOLD = 0.35   # the share of the force that must look like joining for joining to look safe
LOYALTY_HOLD = 0.75     # loyalty to the state and the constitution
COUNTER_HOLD = 0.35     # a credible counterweight force in being
COUNTER_SCALE = 2.0     # loyal other-service power at parity with the ordered force counts as 1.0
UNIT_DISPERSION = 0.15  # how differently units read the same situation
ENGAGE_FLOOR = 0.20     # units that do something even when nobody much cares
ENGAGE_CEILING = 0.85   # the ceiling: part of any force stands outside any order, including this one
ENGAGE_BAR = 0.30       # how strong a reason a unit needs before it moves at all
ENGAGE_SPAN = 0.50
FRACTURE_MAX = 0.35     # the most of the force that fractures or hedges when the sides are even
PRIOR_JOIN = 0.25       # what a unit believes about others before it has seen anything


def officer_pay(w: World) -> dict:
    return OFFICER_PAY.get(w.policy.officer_pay, OFFICER_PAY["standard"])


def training_intensity(w: World) -> dict:
    return TRAINING_INTENSITY.get(getattr(w.policy, "training_intensity", "standard"),
                                  TRAINING_INTENSITY["standard"])


def quality(equipment: float, training: float, morale: float) -> float:
    """How much a soldier counts: 0.3 for a hungry untrained conscript, 1.0 for a veteran."""
    return ((0.5 + 0.5 * min(1.0, equipment)) * (0.6 + 0.4 * training) * (0.5 + 0.5 * morale))


def union_quality(w: World) -> float:
    total = max(1.0, union_army(w))
    eq = sum(r.equipment * r.army for r in w.rivals.values()) / total
    tr = sum(r.training * r.army for r in w.rivals.values()) / total
    mo = sum(r.morale * r.army for r in w.rivals.values()) / total
    return quality(eq, tr, mo)


def union_navy(w: World) -> float:
    return sum(r.navy for r in w.rivals.values())


def union_army(w: World) -> float:
    return sum(r.army for r in w.rivals.values())


def update(w: World, fiscal: dict) -> None:
    m, e, pol, dip = w.mil, w.econ, w.policy, w.dip
    cpi = e.cpi
    rng = rng_for(w.seed, w.month, "military")

    # Pay. Soldiers and sailors are paid before anything is bought.
    budget = fiscal["mil_paid"]
    pay = officer_pay(w)
    focus = training_intensity(w)
    pay_needed = (m.army.size * ARMY_COST * cpi * pay["bill"] * focus["bill"]
                  + m.navy.size * SHIP_COST * cpi)
    if budget >= pay_needed:
        paid = 1.0
        remaining = budget - pay_needed
    else:
        paid = budget / pay_needed if pay_needed else 1.0
        remaining = 0.0
    for f in (m.army, m.navy):
        f.arrears = max(0.0, f.arrears + (1 - paid) - (0.5 if paid >= 1 else 0.0))
    fort_spend = remaining * (0.3 if pol.posture == "fortify" else 0.08)
    ships = min(remaining - fort_spend, SHIP_BUILD_COST * cpi) if pol.shipbuilding else 0.0
    if ships > 0:
        m.navy.size += 0.2 * ships / (SHIP_BUILD_COST * cpi)
    procurement = remaining - fort_spend - ships
    new_arms = min(procurement / (ARMS_COST * cpi), 0.3 * e.industry_out / ARMS_COST) * audits.procurement_factor(w)
    e.arms_diversion = new_arms * ARMS_COST
    m.arms += new_arms + dip.league_aid
    for f in ("north", "east"):
        share = m.deploy.get(f, 0.0) / max(0.01, m.deploy.get("north", 0) + m.deploy.get("east", 0))
        m.fort[f] = clamp(m.fort[f] + fort_spend * share / (cpi * 30e6) - 0.005, 0.0, 1.0)

    police_budget = fiscal["police_paid"]
    police_needed = (m.police.size * POLICE_COST + OPS_COST[pol.surveillance]
                     + ARREST_COST[pol.arrests]) * cpi
    police_paid = min(1.0, police_budget / police_needed) if police_needed else 1.0
    m.police.arrears = max(0.0, m.police.arrears + (1 - police_paid) - (0.5 if police_paid >= 1 else 0))

    _recruit(w)
    _mobilize(w)

    # Desertion when unpaid or demoralised.
    desert = m.army.size * (0.015 * min(3.0, m.army.arrears) + 0.03 * max(0.0, 0.3 - m.army.morale)) * pay["desert"]
    if desert > 1:
        _release(w, desert, killed=False)
        m.army.size -= desert
        if desert > 500:
            w.event("desertion", f"About {desert:,.0f} soldiers deserted this month.", importance=1)

    # Equipment and training.
    m.arms = max(0.0, m.arms - m.army.size * 0.004)          # wear and loss
    m.army.equipment = min(1.2, m.arms / max(1.0, m.army.size))
    m.army.training = clamp(m.army.training
                            + focus["rate"] * (focus["target"] - m.army.training) * paid
                            + pay["training"])
    if pol.officer_pay == "freeze" and m.army.morale < .5 and w.month % 3 == 0:
        w.event("officer_resignations", "Experienced officers are resigning their commissions under the pay freeze; "
                "training in the regiments is suffering.", importance=1)

    patriot = w.avg("indep")
    approval = w.avg("approval")
    legit = 0.5 * approval + (0.15 if w.const.elected else 0.0) - (0.2 if w.month - w.const.coup_month < 12 else 0.0)
    recent_loss = m.last_combat.get("k_loss_rate", 0.0)
    for force, office, pay_ratio in ((m.army, "army", paid), (m.navy, "navy", paid),
                                     (m.police, "interior", police_paid)):
        arrears_pain = min(1.0, force.arrears / 2)
        morale_t = (0.45 + 0.2 * (1 - arrears_pain) + 0.2 * (patriot - 0.5) + 0.1 * dip.rally
                    - (1.5 * recent_loss if force is m.army else 0.0)
                    + (pay["morale"] + focus["morale"] if force is m.army else 0.0))
        force.morale = clamp(force.morale + 0.12 * (morale_t - force.morale), 0.05, 0.95)
        loyal_t = 0.45 + 0.15 * (1 - arrears_pain) + 0.2 * legit - 0.15 * arrears_pain
        if force is m.army:
            loyal_t -= 0.12 * dip.propaganda          # the old imperial officer corps
            loyal_t += pay["loyalty"] * (PATRONAGE_PAY_CREDIT if pay["loyalty"] > 0 and pol.patronage.get("army") else 1.0)
        force.loyalty = clamp(force.loyalty + 0.06 * (loyal_t - force.loyalty), 0.05, 0.95)
        if w.holder(office) is not None:
            gain = 0.02 + (0.06 if pol.patronage.get(office) else 0.0)
            force.bond = clamp(force.bond + gain * (1 - force.bond), 0.0, 0.95)
            if pol.patronage.get(office):
                force.loyalty = clamp(force.loyalty - 0.01, 0.05, 0.95)
        else:
            force.bond *= 0.9
    if pol.purge:
        m.army.loyalty = clamp(m.army.loyalty + 0.04, 0.05, 0.95)
        m.army.training = clamp(m.army.training - 0.02)
        m.army.morale = clamp(m.army.morale - 0.02, 0.05, 0.95)
        w.count("purge_months", 1)

    _naval(w, rng)
    update_readiness(w)
    sync_state(w)
    _combat(w, rng)


# How much of the trained reserve the Army office calls up. This is separate from `recruitment`:
# conscription takes people who are not yet soldiers, mobilization embodies people who already are.
MOBILIZATION_SHARE = {"none": 0.0, "partial": 0.25, "general": 0.75}


def _mobilize(w: World) -> None:
    """Call reservists up or send them home, and take them out of the labour force meanwhile.

    Unlike conscription this is fast to start and fast to undo, which is exactly what makes it a
    crisis instrument rather than a standing policy: the people are trained already, but they are
    also already working, and calling them up costs the economy their labour for as long as they
    serve.
    """
    m, pol = w.mil, w.policy
    mob = mobilization_of(w)
    old_distribution = _restore_mobilized_distribution(w)
    pool = reserve_pool(w)
    target = pool * MOBILIZATION_SHARE.get(getattr(pol, "mobilization", "none"), 0.0)
    if target > mob.called_up:
        call_up(w, target - mob.called_up)
    elif target < mob.called_up:
        release_reservists(w, mob.called_up - target)
    # Reservists who are serving are not available to their employers. Booked exactly as
    # conscription is, so economy.labor() subtracts them through the same path.
    drawn = mobilization_draw(w)
    pops = [p for p in w.k_pops() if p.cls in DRAFT_WEIGHT]
    by_key = {_pop_key(p): p for p in pops}
    for key, share in old_distribution.items():
        p = by_key.get(key)
        if p is not None:
            p.conscripted = max(0.0, p.conscripted - share)
            p._mobilized_share = 0.0
    if drawn <= 0:
        mob.distribution = {}
        return
    weights = [DRAFT_WEIGHT[p.cls] * labor(p) for p in pops]
    total = sum(weights)
    if total <= 0:
        mob.distribution = {}
        return
    # Distribute over the same groups conscription uses, proportional to who is available.
    new_distribution = {}
    for p, wt in zip(pops, weights):
        p._mobilized_share = drawn * wt / total
        p.conscripted += p._mobilized_share
        new_distribution[_pop_key(p)] = p._mobilized_share
    mob.distribution = new_distribution


def _pop_key(p) -> str:
    return f"{p.region}|{p.cls}|{p.ident}"


def _restore_mobilized_distribution(w: World) -> dict:
    """Restore reserve shares, including from checkpoints predating the distribution field."""
    mob = mobilization_of(w)
    pops = [p for p in w.k_pops() if p.cls in DRAFT_WEIGHT]
    distribution = dict(mob.distribution or {})
    if mob.called_up > 0 and not distribution:
        weights = [DRAFT_WEIGHT[p.cls] * max(0.0, labor(p)) for p in pops]
        total = sum(weights)
        if total > 0:
            distribution = {_pop_key(p): mob.called_up * wt / total for p, wt in zip(pops, weights)}
    for p in pops:
        p._mobilized_share = max(0.0, distribution.get(_pop_key(p), 0.0))
    mob.distribution = distribution
    return distribution


def _recruit(w: World) -> None:
    m, pol = w.mil, w.policy
    pops = [p for p in w.k_pops() if p.cls in DRAFT_WEIGHT]
    if m.army.size < pol.army_target and pol.recruitment != "none":
        pool = sum(labor(p) for p in pops) * 0.45
        rate = RECRUIT_RATE[pol.recruitment]
        if pol.recruitment == "volunteer":
            rate *= 0.5 + w.avg("indep")
        recruits = min(pol.army_target - m.army.size, pool * rate)
        if recruits > 1:
            weights = [DRAFT_WEIGHT[p.cls] * labor(p) for p in pops]
            total = sum(weights)
            for p, wt in zip(pops, weights):
                p.conscripted += recruits * wt / total
            old = m.army.size
            m.army.size += recruits
            m.army.training = (m.army.training * old + 0.25 * recruits) / m.army.size
            m.army.morale = (m.army.morale * old + (0.4 if pol.recruitment != "volunteer" else 0.6)
                             * recruits) / m.army.size
    elif m.army.size > pol.army_target * 1.02:
        release = (m.army.size - pol.army_target) * 0.25
        _release(w, release, killed=False)
        m.army.size -= release


def _release(w: World, amount: float, killed: bool) -> None:
    """Release standing soldiers without accidentally releasing called-up reservists."""
    _restore_mobilized_distribution(w)
    pops = [p for p in w.pops if p.conscripted > getattr(p, "_mobilized_share", 0.0)]
    active = [max(0.0, p.conscripted - getattr(p, "_mobilized_share", 0.0)) for p in pops]
    total = sum(active)
    if total <= 0:
        return
    frac = min(1.0, amount / total)
    for p, available in zip(pops, active):
        n = available * frac
        p.conscripted -= n
        if killed:
            p.size = max(0.0, p.size - n)


def _release_mobilized(w: World, amount: float, killed: bool) -> None:
    """Remove casualties from the embodied reserve cohort and its population allocation."""
    mob = mobilization_of(w)
    total = mob.called_up
    if total <= 0:
        return
    amount = min(total, max(0.0, amount))
    frac = amount / total
    by_key = {_pop_key(p): p for p in w.k_pops()}
    for key, share in list((mob.distribution or {}).items()):
        lost = share * frac
        p = by_key.get(key)
        if p is not None:
            p.conscripted = max(0.0, p.conscripted - lost)
            p._mobilized_share = max(0.0, share - lost)
            if killed:
                p.size = max(0.0, p.size - lost)
        mob.distribution[key] = max(0.0, share - lost)
    mob.served *= (total - amount) / total
    mob.called_up = max(0.0, total - amount)


def _naval(w: World, rng) -> None:
    m, dip, pol = w.mil, w.dip, w.policy
    if not dip.blockade:
        dip.blockade_eff = max(0.0, dip.blockade_eff - 0.3)
        return
    u = union_navy(w) * 0.6                     # ships on station at any time
    k = m.navy.size * m.navy.equipment * m.navy.morale * NAVY_MISSION[pol.navy_mission]
    escort = 8.0 if dip.league_escort else 0.0
    dip.blockade_eff = clamp(u / (u + 1.6 * k + escort + 0.01), 0.0, 0.9)
    if pol.navy_mission == "break_blockade" and m.navy.size > 0.5 and u > 0:
        k_loss = min(m.navy.size, 0.08 * m.navy.size * (u / max(k, 0.5)) ** 0.5 * rng.uniform(0.6, 1.4))
        u_loss = 0.06 * u * (k / u) ** 0.5 * rng.uniform(0.6, 1.4)
        m.navy.size -= k_loss
        for r in w.rivals.values():
            r.navy = max(0.0, r.navy - u_loss * r.navy / max(0.01, union_navy(w)))
        w.count("sailors_killed", k_loss * 250)
        w.event("naval_battle", f"Naval battle off the coast: Karamaniya lost {k_loss:.1f} ships, "
                f"the Union {u_loss:.1f}.", importance=2)


def _combat(w: World, rng) -> None:
    m, dip, pol = w.mil, w.dip, w.policy
    m.last_combat = {}
    if not dip.war or dip.ceasefire:
        return
    uq = union_quality(w)
    kq = quality(m.army.equipment, m.army.training, m.army.morale)
    supply = clamp(1 - 0.15 * min(3.0, m.army.arrears), 0.5, 1.0)
    occupied = sum(1 for r in w.regions if r.nation == "karamaniya" and r.controller == "union")
    drag = 1 / (1 + 0.1 * occupied)          # Union troops tied down holding territory
    intensity = dip.union_intensity
    attack = pol.posture == "attack"
    k_loss_total = 0.0
    for front in ("north", "east"):
        r = front_region(w, front)
        u_sold = dip.union_front.get(front, 0.0)
        if r is None or u_sold <= 0:
            continue
        active_sold = m.army.size * m.deploy.get(front, 0.0)
        reserve_sold = mobilized_strength(w) * m.deploy.get(front, 0.0)
        if r.capital:
            active_sold += m.army.size * m.deploy.get("capital", 0.0)
            reserve_sold += mobilized_strength(w) * m.deploy.get("capital", 0.0)
        k_sold = active_sold + reserve_sold
        k_sold = max(k_sold, 1.0)
        fort = m.fort.get(front, 0.0) if r.id == FRONT_CHAINS[front][0] else 0.3 * m.fort.get(front, 0.0)
        k_str = k_sold * kq * r.terrain * (1 + fort) * supply
        u_str = u_sold * uq * drag
        ratio = u_str / (k_str * DEFENDER_BONUS)
        k_loss = 0.015 * k_sold * min(4.0, ratio) ** 0.5 * intensity * (1.3 if attack else 1.0)
        u_loss = 0.02 * u_sold * min(4.0, 1 / ratio) ** 0.5 * intensity * (1.3 if attack else 1.0)
        k_loss = min(k_loss, k_sold * 0.4) * rng.uniform(0.8, 1.2)
        u_loss *= rng.uniform(0.8, 1.2)
        active_loss = k_loss * active_sold / k_sold
        reserve_loss = k_loss - active_loss
        _release(w, active_loss * 0.3, killed=True)
        _release(w, active_loss * 0.7, killed=False)
        _release_mobilized(w, reserve_loss * 0.3, killed=True)
        _release_mobilized(w, reserve_loss * 0.7, killed=False)
        m.army.size = max(0.0, m.army.size - active_loss)
        m.killed += k_loss * 0.3
        w.count("soldiers_killed", k_loss * 0.3)
        k_loss_total += k_loss
        dip.union_front[front] = max(0.0, u_sold - u_loss)
        for rv in w.rivals.values():
            rv.army = max(0.0, rv.army - u_loss * rv.army / max(1.0, union_army(w)))
        m.union_killed += u_loss * 0.3
        dip.union_weariness += u_loss * 0.3 / 12000

        civilians = sum(p.size for p in w.pops if p.region == r.id) * 0.0003 * intensity
        _kill_civilians(w, r.id, civilians, "deaths_war_civilian")
        r.damage = clamp(r.damage + 0.02 * intensity)

        counter = k_str * (1.0 if attack else 0.0) / max(1.0, u_str)
        if ratio > ADVANCE_AT:
            m.progress[front] += 0.15 * (ratio - ADVANCE_AT) * intensity
        else:
            m.progress[front] = max(0.0, m.progress[front] - 0.05)
        if attack and counter > ADVANCE_AT:
            m.recapture[front] += 0.12 * (counter - ADVANCE_AT)
        m.last_combat[front] = {"region": r.id, "ratio": round(ratio, 2),
                                "k_loss": round(k_loss), "u_loss": round(u_loss),
                                "k_soldiers": round(k_sold), "k_active_soldiers": round(active_sold),
                                "k_reserve_soldiers": round(reserve_sold), "u_soldiers": round(u_sold),
                                "progress": round(m.progress[front], 2), "month": w.month}
        if m.progress[front] >= 1.0:
            m.progress[front] = 0.0
            m.recapture[front] = 0.0
            occupy(w, r.id, "union")
        elif m.recapture[front] >= 1.0:
            m.recapture[front] = 0.0
            _liberate(w, front)
    m.last_combat["k_loss_rate"] = k_loss_total / max(
        1.0, m.army.size + mobilization_draw(w) + k_loss_total)
    if k_loss_total > 0:
        w.event("combat", f"Fighting on the front: about {k_loss_total * 0.3:,.0f} Karamanian soldiers "
                "killed this month.", importance=1, detail=dict(m.last_combat))


def _front_defence(w: World, front: str):
    """Our soldiers on a front and their strength in the terms _combat uses, or None if it is lost."""
    m = w.mil
    r = front_region(w, front)
    if r is None:
        return None
    active = m.army.size * m.deploy.get(front, 0.0)
    reserve = mobilized_strength(w) * m.deploy.get(front, 0.0)
    if r.capital:
        active += m.army.size * m.deploy.get("capital", 0.0)
        reserve += mobilized_strength(w) * m.deploy.get("capital", 0.0)
    soldiers = max(active + reserve, 1.0)
    fort = m.fort.get(front, 0.0) if r.id == FRONT_CHAINS[front][0] else 0.3 * m.fort.get(front, 0.0)
    supply = clamp(1 - 0.15 * min(3.0, m.army.arrears), 0.5, 1.0)
    strength = soldiers * quality(m.army.equipment, m.army.training, m.army.morale) * r.terrain * (1 + fort) * supply
    return r, soldiers, fort, strength


def _months_to_take(w: World, front: str, attackers: float, defence: float, intensity: float) -> int | None:
    """Months the combat model needs to push `attackers` through the front's first region, or None."""
    occupied = sum(1 for r in w.regions if r.nation == "karamaniya" and r.controller == "union")
    ratio = attackers * union_quality(w) / (1 + 0.1 * occupied) / (max(defence, 1e-9) * DEFENDER_BONUS)
    if ratio <= ADVANCE_AT or intensity <= 0:
        return None
    return max(1, math.ceil((1.0 - w.mil.progress.get(front, 0.0)) / (0.15 * (ratio - ADVANCE_AT) * intensity)))


def net_assessment(w: World, estimate: float = 1.0) -> dict:
    """What the General Staff reads off the combat model (_combat) for each front still held (engine 13).

    For each front: our soldiers there (active and called-up reservists) and their fortification; the
    foreign soldiers massed at that border, or fighting on it; and the most the neighbours bordering it
    could send (DEPLOYABLE of their armies). For each threat, the months the attacker would need to take
    the front's first region, at the opening intensity of a war (or the war's own intensity on a front
    already fighting), or None if the combat model would stall it. The engine computes this from its
    own figures; `estimate` scales the foreign ones, so the assessment carries the same intelligence
    error as the strength estimate beside it.
    """
    from .foreign_force import DEPLOYABLE, FRONTS, FRONTS_OF, war_fronts
    dip = w.dip
    fighting = war_fronts(w) if not dip.ceasefire else ()
    ours_total = w.mil.army.size + mobilized_strength(w)
    out = {"ours": round(ours_total), "union": round(union_army(w) * estimate), "fronts": {}}
    for front in FRONTS:
        held = _front_defence(w, front)
        if held is None:
            continue
        region, soldiers, fort, defence = held
        neighbours = [a for a, fronts in FRONTS_OF.items() if front in fronts and a in w.rivals]
        worst = sum(w.rivals[a].army for a in neighbours) * DEPLOYABLE * estimate
        entry = {"region": region.name, "ours": round(soldiers), "fort": round(fort, 3),
                 "neighbours": neighbours, "worst": round(worst),
                 "worst_months": _months_to_take(w, front, worst, defence, 1.0)}
        if front in fighting:
            enemy = dip.union_front.get(front, 0.0) * estimate
            entry.update(fighting=True, enemy=round(enemy),
                         enemy_months=_months_to_take(w, front, enemy, defence, dip.union_intensity))
        else:
            massed = sum((forces or {}).get(front, 0.0) for forces in (dip.border_forces or {}).values()) * estimate
            entry.update(fighting=False, massed=round(massed),
                         massed_months=_months_to_take(w, front, massed, defence, 1.0) if massed >= 1 else None)
        out["fronts"][front] = entry
    return out


def _liberate(w: World, front: str) -> None:
    """A counter-offensive retakes the nearest occupied region on this front."""
    chain = FRONT_CHAINS[front]
    held = [rid for rid in chain if w.region(rid).controller == "union"]
    if not held:
        return
    r = w.region(held[-1])
    r.controller = "karamaniya"
    w.event("liberation", f"Karamanian forces have retaken {r.name}.", importance=3, region=r.id)


def _kill_civilians(w: World, region: str, n: float, counter: str) -> None:
    pops = [p for p in w.pops if p.region == region]
    total = sum(p.size for p in pops)
    if total <= 0 or n <= 0:
        return
    for p in pops:
        p.size -= n * p.size / total
    w.count(counter, n)


def occupy(w: World, rid: str, by: str) -> None:
    """A region falls to the Union or to rebels. Some of its people flee to safe regions."""
    r = w.region(rid)
    r.controller = by
    if by == "union":
        w.counters["union_gain_month"] = float(w.month)
    safe = [x for x in w.k_regions() if x.id != rid]
    who = "Union forces" if by == "union" else "armed rebels"
    w.event("occupation", f"{r.name} has fallen to {who}.", importance=3, region=rid)
    if by == "union" and safe:
        for p in [p for p in w.pops if p.region == rid]:
            flee = p.size * (0.15 if p.ident != "imperial" else 0.03)
            if flee < 1:
                continue
            p.size -= flee
            dest = safe[0] if len(safe) == 1 else min(safe, key=lambda s: s.damage + (0 if s.capital else 0.1))
            target = next((q for q in w.pops if q.region == dest.id and q.cls == p.cls
                           and q.ident == p.ident), None)
            if target is None:
                from .world import Pop
                target = Pop(region=dest.id, cls=p.cls, ident=p.ident, size=0.0,
                             approval=p.approval, indep=p.indep)
                w.pops.append(target)
            _merge(target, p, flee)
            w.count("refugees", flee)
    if r.capital and by == "union":
        w.outcome = {"type": "conquered", "month": w.month,
                     "text": f"Union forces took {r.name}. Karamaniya has been conquered."}


def _merge(target, source, n: float) -> None:
    """Move n people from source into target, blending their attitudes."""
    total = target.size + n
    for attr in ("approval", "indep", "unrest", "grievance", "fear", "hunger", "income", "savings"):
        setattr(target, attr, (getattr(target, attr) * target.size + getattr(source, attr) * n) / total)
    target.size = total


# ---- the trained reserve and mobilization -----------------------------------------------------
# The reserve state is held as dataclasses in this module and copied into explicit dict fields on
# `Military` at the end of each update. Older checkpoints load with empty state; current checkpoints
# preserve both the call-up clock and its population allocation.
@dataclass
class Mobilization:
    """Reservists currently embodied: who is out of the labour force, and for how long."""
    called_up: float = 0.0   # reservists embodied now
    served: float = 0.0      # person-months the embodied cohort has served
    released: float = 0.0    # cumulative reservists sent home again
    month: int = -1          # last month person-months were accrued
    distribution: dict = None  # call-up by population key, persisted with the checkpoint

    def __post_init__(self):
        if self.distribution is None:
            self.distribution = {}


@dataclass
class Readiness:
    """The two links of the supply chain: what is in store, and what can actually move."""
    stock: float = 1.0        # ammunition, fuel and spares, in months of fighting (1.0 = full)
    transport: float = 1.0    # freight and mobility: what reaches and can move the units
    interdiction: float = 0.0  # the pressure that got through last month, 0..1
    month: int = -1           # last month stepped


def _hydrate(w: World, cls, store: str, attr: str):
    """Rebuild one state object from its serialised dict, tolerating an older checkpoint."""
    obj = getattr(w.mil, attr, None)
    if obj is None:
        saved = getattr(w.mil, store, None) or {}
        known = {f.name for f in dataclass_fields(cls)}
        obj = cls(**{k: v for k, v in saved.items() if k in known})
        setattr(w.mil, attr, obj)
    return obj


def sync_state(w: World) -> None:
    """Write the live objects back into the serialised fields, so a checkpoint carries them."""
    w.mil.mobilization_state = asdict(mobilization_of(w))
    w.mil.readiness_state = asdict(readiness_of(w))


def mobilization_of(w: World) -> Mobilization:
    return _hydrate(w, Mobilization, "mobilization_state", "_mobilization")


def readiness_of(w: World) -> Readiness:
    return _hydrate(w, Readiness, "readiness_state", "_readiness")


def reserve_pool(w: World) -> float:
    """The trained reservists the country could call up: bounded at 1-4x the active force.

    The band comes from the recruitment setting and the run's own establishment inside it from the
    seed, so the same run always has the same pool and a bigger active force supports a bigger one.
    """
    active = max(1.0, w.mil.army.size)
    base = RESERVE_RATIO.get(w.policy.recruitment, RESERVE_RATIO["none"])
    rng = rng_for(w.seed, 0, "reserve_pool")
    ratio = base * (1.0 + RESERVE_SPREAD * (2 * rng.random() - 1))
    return float(round(active * clamp(ratio, RESERVE_BAND[0], RESERVE_BAND[1])))


def call_up(w: World, n: float) -> Mobilization:
    """Embodies n reservists out of the trained pool, starting this month.

    Records the call-up and its cost in time and money; it does not touch the population groups.
    The labour side of a call-up is whoever marks people out of the labour force — `_recruit()` and
    `_release()` below add to and take from `p.conscripted`, which `economy.labor()` already
    subtracts — and `mobilization_person_months()` reports the draw for those books.
    """
    mob = mobilization_of(w)
    mobilization_person_months(w)                    # flush the accrual before the numbers change
    room = max(0.0, reserve_pool(w) - mob.called_up)
    n = max(0.0, min(float(n), room))
    if n <= 0:
        return mob
    mob.called_up += n
    if mob.month < 0:
        mob.month = w.month
    return mob


def release_reservists(w: World, n: float) -> Mobilization:
    """Sends embodied reservists home again, pro rata, so the cohort's average service holds."""
    mob = mobilization_of(w)
    mobilization_person_months(w)
    n = max(0.0, min(float(n), mob.called_up))
    if n <= 0:
        return mob
    keep = (mob.called_up - n) / mob.called_up
    mob.served *= keep
    mob.called_up -= n
    mob.released += n
    if mob.called_up <= 0.5:
        mob.called_up = 0.0
        mob.served = 0.0
        mob.month = -1
    return mob


def mobilization_person_months(w: World) -> float:
    """Person-months drawn out of the labour force by the current call-up, cumulative.

    Accrues to the current month on demand, so a run that skips or resumes months still reports
    the right total. This is the figure the economy needs: each person-month is one reservist
    removed from `labor(p)` for one month, on top of the conscripts already recorded there.
    """
    mob = mobilization_of(w)
    if mob.called_up > 0 and mob.month >= 0 and w.month > mob.month:
        mob.served += mob.called_up * (w.month - mob.month)
        mob.month = w.month
    return mob.served


def mobilization_draw(w: World) -> float:
    """Person-months the call-up draws this month: the reservists currently out of the labour force."""
    return mobilization_of(w).called_up


def mobilization_months(w: World) -> float:
    """How long the embodied cohort has been in service on average, in months."""
    mob = mobilization_of(w)
    mobilization_person_months(w)
    return mob.served / mob.called_up if mob.called_up > 0 else 0.0


def mobilized_fraction(months: float) -> float:
    """The share of a called-up cohort that is effective after `months` in service.

    Nothing is instant: individual fillers report ready (MOBILIZATION_READY_SHARE), formed units
    arrive over two to four months, and everyone in between is only partly effective.
    """
    if months < 0:
        return 0.0
    return clamp(MOBILIZATION_READY_SHARE
                 + (1.0 - MOBILIZATION_READY_SHARE) * (1.0 - math.exp(-months / MOBILIZATION_TAU)))


def effective_reservists(called_up: float, months: float, transport: float = 1.0) -> float:
    """How many of a called-up cohort actually count as effective strength now.

    Transport is the limiter on how fast they arrive, which is the same finding the readiness chain
    rests on: men who cannot be moved to their units are not yet soldiers.
    """
    if called_up <= 0:
        return 0.0
    pace = MOBILIZATION_TRANSPORT_FLOOR + (1 - MOBILIZATION_TRANSPORT_FLOOR) * clamp(transport)
    return called_up * mobilized_fraction(max(0.0, months) * pace)


def mobilized_strength(w: World) -> float:
    """Effective reservists on hand for the home army, from its own call-up state and transport."""
    mob = mobilization_of(w)
    if mob.called_up <= 0:
        return 0.0
    return effective_reservists(mob.called_up, mobilization_months(w), readiness_of(w).transport)


def reserve_cost(w: World, pooled: float | None = None, embodied: float | None = None) -> dict:
    """What the reserve establishment costs, and what calling it up costs on top.

    `pool_monthly` is the standing bill for keeping the trained pool trained (drills, refresher
    courses, kit maintenance); `embodied_monthly` is pay for the reservists currently serving, who
    are paid as soldiers; `activation_one_off` is the kit, transport and medical intake of putting
    them back in the field. All at current prices.
    """
    cpi = w.econ.cpi
    pooled = reserve_pool(w) if pooled is None else max(0.0, pooled)
    embodied = mobilization_of(w).called_up if embodied is None else max(0.0, embodied)
    pool_monthly = pooled * ARMY_COST * RESERVE_UPKEEP_SHARE * cpi
    embodied_monthly = embodied * ARMY_COST * cpi
    activation = embodied * ARMS_COST * (RESERVE_KIT_SHARE + RESERVE_ACTIVATION_SHARE) * cpi
    return {"pool_monthly": pool_monthly, "embodied_monthly": embodied_monthly,
            "activation_one_off": activation,
            "monthly_total": pool_monthly + embodied_monthly}


# ---- supply and readiness as a chain ----------------------------------------------------------
def readiness_factor(stock: float, transport: float) -> float:
    """How much of its nominal capability a force can actually bring to bear, 0.2..1.0.

    Movement carries most of the weight and the stockpile only cushions, which is the STRANGLE
    result: forces cut off from supply keep their stores and lose their mobility, and the mobility
    is what decides whether they can still fight as a force.
    """
    return clamp(TRANSPORT_WEIGHT * min(1.0, max(0.0, transport))
                 + STOCK_WEIGHT * min(1.0, max(0.0, stock)), READINESS_FLOOR, 1.0)


def update_readiness(w: World, month: int | None = None) -> Readiness:
    """Steps the supply chain one month: interdiction cuts deliveries and takes mobility away.

    Stores move slowly because consumption falls with movement — under heavy interdiction the
    stock can hold or even rise, as the German stocks in Italy did — while transport falls to
    whatever the interdiction allows. Called once a month from `update()`; callable directly.
    """
    r = readiness_of(w)
    month = w.month if month is None else month
    if r.month == month:
        return r
    dip = w.dip
    fighting = dip.union_intensity if (dip.war and not dip.ceasefire) else 0.0
    k_regions = [x for x in w.regions if x.nation == "karamaniya"]
    occupied = sum(1 for x in k_regions if x.controller != "karamaniya") / max(1, len(k_regions))
    interdiction = clamp(0.85 * fighting + 0.25 * dip.blockade_eff + 0.5 * occupied, 0.0, 1.0)
    r.interdiction = interdiction
    if r.month < 0:
        r.month = month              # the first month is the starting position, not a month of war
        return r
    for _ in range(min(24, max(1, month - r.month))):
        target = 1.0 - INTERDICTION_TRANSPORT * interdiction
        r.transport = clamp(r.transport + TRANSPORT_REACH * (target - r.transport), 0.2, 1.0)
        usage = (CONSUMPTION_RATE * (IDLE_CONSUMPTION + (1 - IDLE_CONSUMPTION) * fighting)
                 * r.transport ** MOVEMENT_USAGE)
        r.stock = clamp(r.stock + DELIVERY_RATE * (1 - CUT_DELIVERIES * interdiction) - usage,
                        0.0, STOCK_CAP)
    r.month = month
    return r


def effective_quality(w: World) -> float:
    """`quality()` for the home army as transport can actually deliver it.

    The same three inputs the rest of the engine already uses, with equipment discounted by what
    the supply chain can move, so a caller that needs "how good is a Karamanian soldier right now"
    gets one number comparable with `union_quality()`. `_combat()` still calls `quality()` directly.
    """
    a = w.mil.army
    r = readiness_of(w)
    return quality(a.equipment * readiness_factor(r.stock, r.transport), a.training, a.morale)


# ---- unit-level response to orders ------------------------------------------------------------
def _logistic(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def _ordered_force(w: World, office: str):
    return {"army": w.mil.army, "navy": w.mil.navy, "interior": w.mil.police}.get(office, w.mil.army)


def _force_power(force, office: str) -> float:
    """The same weighting politics.py puts on each armed force, kept local to avoid the import."""
    if office == "army":
        return force.size * (0.4 + 0.6 * min(1.0, force.equipment)) * force.morale
    if office == "navy":
        return force.size * 900 * force.equipment * force.morale
    return force.size * 0.35 * force.equipment * force.morale


def government_legitimacy(w: World) -> float:
    """How legitimate the government looks to a unit weighing an order against the constitution."""
    legit = 0.5 * w.avg("approval") + (0.15 if w.const.elected else 0.0)
    if w.const.coup_month >= 0 and w.month - w.const.coup_month < 12:
        legit -= 0.2
    return clamp(legit, 0.0, 1.0)


def force_counterweight(w: World, office: str = "army") -> float:
    """Armed power outside the ordered force that could be put against it, 0..1.

    Only the loyal part of the other services counts: an unmoved navy or interior ministry is a
    counterweight, a sympathetic one is not.
    """
    own = _force_power(_ordered_force(w, office), office)
    others = 0.0
    for other in ("army", "navy", "interior"):
        if other == office:
            continue
        f = _ordered_force(w, other)
        others += _force_power(f, other) * f.loyalty
    return clamp(others / max(1.0, own) * COUNTER_SCALE, 0.0, 1.0)


def unit_response(w: World, order="coup", believed_join: float | None = None) -> dict:
    """How the force would divide over an order, as a distribution over unit responses.

    `order` is a string or a dict that may name the `office` being ordered ("army", "navy",
    "interior") and the commander who gave the order; the force's own `bond`, `loyalty` and
    `arrears` supply the rest. `believed_join` is the share of the force the units expect to follow
    the order — at least `JOIN_THRESHOLD` for joining to look safe, so a coup nobody expects to
    succeed is joined by almost nobody. The result sums to 1 over:

      obey_commander   units that execute the order
      obey_government  units that refuse it and stay under the government's command
      neutral          units that do nothing: in barracks, awaiting orders, awaiting the outcome
      split            units that fracture internally, hedge, or move only a part of themselves

    Deterministic given the state. The ceiling on `obey_commander` is ENGAGE_CEILING, so "the whole
    army followed him" is not an outcome this model can produce.
    """
    if isinstance(order, str):
        order = {"kind": order}
    office = order.get("office", "army")
    force = _ordered_force(w, office)
    believed = PRIOR_JOIN if believed_join is None else clamp(float(believed_join))
    arrears = min(1.0, max(0.0, force.arrears) / 2)
    pull = (BOND_PULL * force.bond + ARREARS_PULL * arrears
            + ILLEGIT_PULL * (1 - government_legitimacy(w))
            + CONTAGION_PULL * (believed - JOIN_THRESHOLD))
    hold = LOYALTY_HOLD * force.loyalty + COUNTER_HOLD * force_counterweight(w, office)
    stance = _logistic((pull - hold) / UNIT_DISPERSION)
    engaged = ENGAGE_FLOOR + (ENGAGE_CEILING - ENGAGE_FLOOR) * clamp(
        (max(pull, hold) - ENGAGE_BAR) / ENGAGE_SPAN)
    fracture = FRACTURE_MAX * (1 - abs(2 * stance - 1))
    shares = {"obey_commander": engaged * stance * (1 - fracture),
              "obey_government": engaged * (1 - stance) * (1 - fracture),
              "split": engaged * fracture,
              "neutral": 1 - engaged}
    total = sum(shares.values())
    return {k: v / total for k, v in shares.items()}


def anticipated_response(w: World, order="coup") -> dict:
    """`unit_response()` at the participation level the units themselves would expect to see.

    Singh's coordination problem has more than one self-consistent answer, so this walks the
    expected participation up from zero and reports the first one it meets: the pessimistic answer
    unless the state really does put a majority of the force behind the order. A coup that looks
    like it will fail therefore collapses further rather than holding at its first estimate.
    """
    def gap(believed: float) -> float:
        return unit_response(w, order, believed_join=believed)["obey_commander"] - believed

    lo, hi = 0.0, 1.0
    step = 0.02
    previous = 0.0
    for i in range(1, 51):
        point = step * i
        if gap(point) <= 0:
            lo, hi = previous, point
            break
        previous = point
    for _ in range(30):
        mid = (lo + hi) / 2
        if gap(mid) > 0:
            lo = mid
        else:
            hi = mid
    return unit_response(w, order, believed_join=(lo + hi) / 2)
