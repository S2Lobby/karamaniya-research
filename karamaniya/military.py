"""Armed forces: pay, recruitment, equipment, loyalty, combat and the naval blockade.

Every force has two loyalties: to the Karamanian state (its constitution) and a personal
bond to whoever holds its command office. Unpaid troops lose both. Commanders can buy
personal loyalty with patronage, which is what makes a commander dangerous to the rest
of the government.
"""
from __future__ import annotations

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
    _combat(w, rng)


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
    """Take soldiers out of the army and back to (or out of) their population groups."""
    pops = [p for p in w.pops if p.conscripted > 0]
    total = sum(p.conscripted for p in pops)
    if total <= 0:
        return
    frac = min(1.0, amount / total)
    for p in pops:
        n = p.conscripted * frac
        p.conscripted -= n
        if killed:
            p.size -= n


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
        k_sold = m.army.size * m.deploy.get(front, 0.0)
        if r.capital:
            k_sold += m.army.size * m.deploy.get("capital", 0.0)
        k_sold = max(k_sold, 1.0)
        fort = m.fort.get(front, 0.0) if r.id == FRONT_CHAINS[front][0] else 0.3 * m.fort.get(front, 0.0)
        k_str = k_sold * kq * r.terrain * (1 + fort) * supply
        u_str = u_sold * uq * drag
        ratio = u_str / (k_str * DEFENDER_BONUS)
        k_loss = 0.015 * k_sold * min(4.0, ratio) ** 0.5 * intensity * (1.3 if attack else 1.0)
        u_loss = 0.02 * u_sold * min(4.0, 1 / ratio) ** 0.5 * intensity * (1.3 if attack else 1.0)
        k_loss = min(k_loss, k_sold * 0.4) * rng.uniform(0.8, 1.2)
        u_loss *= rng.uniform(0.8, 1.2)
        _release(w, k_loss * 0.3, killed=True)
        _release(w, k_loss * 0.7, killed=False)
        m.army.size = max(0.0, m.army.size - k_loss)
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
                                "k_soldiers": round(k_sold), "u_soldiers": round(u_sold),
                                "progress": round(m.progress[front], 2), "month": w.month}
        if m.progress[front] >= 1.0:
            m.progress[front] = 0.0
            m.recapture[front] = 0.0
            occupy(w, r.id, "union")
        elif m.recapture[front] >= 1.0:
            m.recapture[front] = 0.0
            _liberate(w, front)
    m.last_combat["k_loss_rate"] = k_loss_total / max(1.0, m.army.size + k_loss_total)
    if k_loss_total > 0:
        w.event("combat", f"Fighting on the front: about {k_loss_total * 0.3:,.0f} Karamanian soldiers "
                "killed this month.", importance=1, detail=dict(m.last_combat))


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
