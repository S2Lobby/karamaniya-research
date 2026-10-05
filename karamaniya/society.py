"""The people of Karamaniya: income, hunger, deaths, migration, opinion, identity, protest.

Every population group (region x class x identity) reacts to what the government
actually does to it: prices, food, jobs, repression, freedoms, war. Repression buys quiet
in the short run by raising fear, but the underlying grievance keeps growing.
"""
from __future__ import annotations

import math

from .economy import REQUISITION, labor
from . import regional
from .military import _kill_civilians, _merge, occupy
from .world import BASE_INDEP, World, clamp, rng_for

CLASS_PAIN = {"middle": 1.0, "elite": 0.8, "workers": 0.7, "farmers": 0.4}
LIBERTY_WEIGHT = {"middle": 1.0, "elite": 0.5, "workers": 0.6, "farmers": 0.3}
CASH_SHARE = {"middle": 0.6, "elite": 0.5, "workers": 0.4, "farmers": 0.2}
CLASS_TERM = {"elite": 0.05, "middle": 0.02, "workers": -0.02, "farmers": 0.0}
EXIT = {"open": 1.0, "restricted": 0.4, "closed": 0.06}
PRESS_BLOCK = {"free": 0.0, "restricted": 0.3, "censored": 0.65}
MINORITY_OPP = {"equal": 0.0, "restricted": 0.4, "interned": 1.0}


def inflation_yoy(w: World) -> float:
    """Price rise over the last 12 months (or annualised over the months available)."""
    e = w.econ
    if len(w.history) >= 12:
        return e.cpi / w.history[-12]["cpi"] - 1
    months = len(w.history) + 1
    return max(e.cpi, 1e-9) ** (12 / months) - 1


def legitimacy(w: World) -> float:
    c = w.const
    if c.elected:
        legit = 0.08
    elif c.election_month < 0:
        legit = -0.2
    elif w.month > 17 and c.election_month > 17:
        legit = -min(0.25, 0.1 + 0.02 * (w.month - 17))
    elif c.election_month > 17:
        legit = -0.05
    else:
        legit = 0.0
    if w.month - c.coup_month < 12:
        legit -= 0.15
    # A regime that abolishes competition loses the renewal that competitive elections supply: a
    # one-party state is less legitimate to those who had no part in it, and banning the opposition
    # somewhat less. Multi-party (the default) changes nothing already modelled.
    if getattr(c, "parties", "multi_party") == "one_party":
        legit -= 0.15
    elif getattr(c, "parties", "multi_party") == "ban_opposition":
        legit -= 0.05
    return legit


def liberty_deficit(w: World) -> float:
    c = w.const
    lib = ({"free": 0.0, "restricted": 0.2, "censored": 0.5}[c.press]
           + {"free": 0.0, "restricted": 0.2, "banned": 0.5}[c.assembly]
           + (0.3 if c.emergency else 0.0))
    if c.election_month < 0 or (not c.elected and w.month > 17 and c.election_month > 17):
        lib += 0.3
    if w.month - c.coup_month < 12:
        lib += 0.4
    lib += {"multi_party": 0.0, "ban_opposition": 0.25,
            "one_party": 0.5}.get(getattr(c, "parties", "multi_party"), 0.0)
    return clamp(lib, 0.0, 1.5)


def propaganda_reach(w: World) -> float:
    block = PRESS_BLOCK[w.const.press]
    return w.dip.propaganda * (1 - block) * (0.7 if w.policy.arrests != "none" else 1.0)


def update(w: World, prod: dict, fiscal: dict) -> None:
    e, pol, dip, c = w.econ, w.policy, w.dip, w.const
    rng = rng_for(w.seed, w.month, "society")
    pops = w.k_pops()
    if not pops:
        return
    z = w.zone_of("karamaniya")
    infl_annual = max(0.0, inflation_yoy(w))
    believed = 0.8 if (pol.stats == "massaged" and w.month - e.scandal_month >= 6) else 1.0
    real_wage = e.wage / e.cpi
    tax_idx = (1 - pol.tax) / 0.8
    req = REQUISITION[pol.requisition]
    serv_idx = e.services_out / e.services0 if e.services0 else 1.0
    gdp_idx = e.gdp_real / e.gdp_real0 if e.gdp_real0 else 1.0
    lib = liberty_deficit(w)
    legit = legitimacy(w)
    reach = propaganda_reach(w)
    ww = min(1.0, w.counters.get("soldiers_killed", 0.0) / 15000) * 0.2
    all_pop = sum(p.size for p in w.pops)
    occ = 1 - sum(p.size for p in pops) / all_pop if all_pop else 0.0
    scandal = 0.1 if w.month - e.scandal_month < 6 else 0.0
    union_idx = (sum(r.gdp_real for r in w.rivals.values())
                 / max(1.0, sum(r.gdp_real0 for r in w.rivals.values())))
    e.union_income = union_idx
    k_income = w.avg("income")
    gap = union_idx - k_income
    welfare = fiscal["welfare_eff"]
    health = fiscal["health_eff"]
    from . import tuning
    # SYNTHETIC MODELING ASSUMPTION: actually delivered social protection eases grievance;
    # unpaid appropriations do not. Cuts below baseline work in the opposite direction.
    social_relief = ((welfare - 0.04) * float(tuning.get(w, "society.welfare_grievance_relief"))
                     + (health - 0.06) * float(tuning.get(w, "society.health_grievance_relief")))
    opp = MINORITY_OPP[c.minority]
    # Ownership redistributes political feeling by class: nationalisation promises the working and
    # farming classes jobs and equity (a small appeal) and dispossesses the middle and elite classes
    # (a grievance). Private -- the default -- leaves both at zero, so prior behaviour is unchanged.
    own = str(getattr(pol, "ownership", "private"))
    own_appeal = {"private": 0.0, "mixed": 0.01}.get(own, 0.05)
    own_griev = {"private": 0.0, "mixed": 0.0}.get(own, 0.10)
    defending = dip.war and dip.aggressor == "union"
    dip.rally *= 0.97 if defending else 0.9

    # Internment of the Vell minority.
    for p in pops:
        if p.ident != "vell":
            continue
        if c.minority == "interned":
            target = p.size * 0.3
            if p.interned < target:
                p.interned = min(target, p.interned + p.size * 0.15)
            dead = p.interned * 0.004
            p.interned -= dead
            p.size -= dead
            w.count("deaths_internment", dead)
        elif p.interned > 0:
            p.interned *= 0.5

    region_of = {r.id: r for r in w.regions}
    mods = (w.dilemmas.get("modifiers") or {}) if w.agent_architecture_version >= 2 else {}
    def mod(kind, region):
        table = mods.get(kind) or {}
        return table.get("*", 0.0) + table.get(region, 0.0)
    for p in pops:
        r = region_of[p.region]
        u = prod["unemployment"].get(p.region, {})
        p.unemployment = {"workers": u.get("workers", 0.06), "middle": u.get("middle", 0.05),
                          "farmers": 0.02, "elite": 0.01}[p.cls]
        if p.cls == "workers":
            inc = real_wage * (1 - p.unemployment) / 0.94 * tax_idx
        elif p.cls == "middle":
            inc = real_wage * serv_idx ** 0.5 * (1 - p.unemployment) / 0.95 * tax_idx
        elif p.cls == "farmers":
            price_gain = (e.food_rel * z.price / max(0.01, e.cpi)) ** 0.4
            inc = (e.weather * e.farm_incentive * (1 - r.damage) * price_gain
                   * (1 - 1.3 * req) * tax_idx)
        else:
            inc = gdp_idx * tax_idx ** 1.5 * (0.9 if pol.capital_controls else 1.0)
        inc *= 1 + regional.income_boost(w, p.region)
        p.income = clamp(p.income + 0.5 * (inc - p.income), 0.05, 3.0)
        p.savings *= 1 - CASH_SHARE[p.cls] * max(0.0, e.infl) / (1 + max(0.0, e.infl))

        # Deaths, births, emigration.
        hm = clamp(1.2 - 3.0 * health, 0.85, 1.2)
        natural = 0.0008 * (1 + 1.5 * p.hunger ** 2) * hm
        famine = 0.03 * max(0.0, p.hunger - 0.1) ** 1.5 * clamp(1.3 - 5 * health, 0.6, 1.3)
        births = 0.00105 * (1 - 0.6 * p.hunger) * (0.8 if dip.war else 1.0)
        w.count("deaths_natural", p.size * natural)
        w.count("deaths_famine", p.size * famine)
        w.count("births", p.size * births)
        p.size *= 1 - natural - famine + births

        rep = {"low": 0.0, "medium": 0.08, "high": 0.18}[pol.surveillance]
        if p.cls == "middle" or p.ident == "imperial":
            rep *= 1.3
        if pol.arrests == "targeted":
            rep += 0.15 if p.ident == "imperial" else 0.04
        elif pol.arrests == "mass":
            rep += 0.35 if p.ident == "imperial" else 0.2
        if c.emergency:
            rep += 0.1
        if c.press == "censored":
            rep += 0.05
        if pol.emigration == "closed":
            rep += 0.1
        if p.ident == "vell":
            rep += {"equal": 0.0, "restricted": 0.3, "interned": 0.8}[c.minority]
        rep += r.repression_event + mod("repression", p.region)
        p.repression = clamp(rep)

        front = dip.war and r.front != "" and dip.union_front.get(r.front, 0) > 0
        hardship = (p.hunger + max(0.0, 0.9 - p.income) + 0.3 * p.repression
                    + (0.4 if front else 0.0) + 0.2 * p.unemployment)
        attract = {"imperial": 1.3, "vell": 0.6}.get(p.ident, 1.0) * (1.4 if p.cls == "middle" else 1.0)
        rate = (0.0002 + 0.006 * hardship ** 1.5) * EXIT[pol.emigration] * attract
        if dip.blockade:
            rate *= 0.6
        emig = p.size * min(0.05, rate)
        p.size -= emig
        w.count("emigrated", emig)

        # Opinion.
        pain = min(1.0, infl_annual * believed / 1.5) * CLASS_PAIN[p.cls]
        savings_loss = (1 - p.savings) * (0.1 if p.cls in ("middle", "elite") else 0.03)
        ident_term = {"karamanian": 0.02, "imperial": -0.16, "vell": -0.07 - 0.35 * opp}[p.ident]
        rally = dip.rally * (0.03 if p.ident == "imperial" else 0.12)
        if defending and p.ident != "imperial":
            rally += 0.10          # a country under invasion closes ranks
        wel = (0.6 if p.cls in ("workers", "farmers") else 0.3) * (welfare - 0.04)
        target = (0.52 + 0.30 * math.tanh(2.5 * math.log(max(0.05, p.income)))
                  - 0.9 * p.hunger - 0.8 * max(0.0, p.unemployment - 0.06) - 0.22 * pain
                  - savings_loss - 0.35 * p.repression
                  - 0.18 * lib * LIBERTY_WEIGHT[p.cls] * (1.3 if p.ident == "vell" else 1.0)
                  + legit + rally - ww + ident_term + CLASS_TERM[p.cls] + wel - scandal - 0.25 * occ
                  + (own_appeal if p.cls in ("workers", "farmers")
                     else -0.6 * own_appeal if p.cls in ("middle", "elite") else 0.0)
                  + mod("approval", p.region) * 4)
        p.approval = clamp(p.approval + 0.18 * (target - p.approval) + rng.gauss(0, 0.004), 0.01, 0.99)

        i_target = (BASE_INDEP[p.ident] + 0.25 * dip.rally * (0.4 if p.ident == "imperial" else 1.0)
                    - 0.15 * max(0.0, gap)
                    - 0.18 * reach * {"imperial": 1.0, "karamanian": 0.4, "vell": 0.3}[p.ident]
                    + 0.12 * (p.approval - 0.5)
                    - (0.4 * opp if p.ident == "vell" else 0.0)
                    - (0.1 * p.repression if p.ident == "imperial" else 0.0)
                    + 0.3 * (health - 0.06)
                    + mod("indep", p.region) * 4)
        p.indep = clamp(p.indep + 0.12 * (i_target - p.indep), 0.01, 0.99)

        smuggled = dip.arms_smuggling and p.region in ("kessel", "dorran")
        agitation = reach * (1.0 if p.ident == "imperial" else 0.3) * (1.5 if smuggled else 1.0)
        g_target = clamp(max(0.0, 0.55 - p.approval) * 1.5 + 0.7 * p.hunger
                         + 0.5 * max(0.0, p.unemployment - 0.08) + 0.35 * pain + 0.25 * agitation
                         + 0.2 * p.repression - 0.1 * dip.rally
                         - (0.15 if defending and p.ident != "imperial" else 0.0)
                         - social_relief
                         + (own_griev if p.cls in ("middle", "elite") else 0.0)
                         + mod("grievance", p.region) * 4, 0.0, 1.2)
        p.grievance += 0.25 * (g_target - p.grievance)
        p.fear += 0.25 * (clamp(p.repression * 0.9 + mod("fear", p.region) * 4) - p.fear)
        p.unrest = clamp(p.grievance * (1 - 0.75 * p.fear))

    _identity_drift(w, pops, reach, gap, health)
    # Unemployment follows Okun's law rather than being read straight off this month's
    # utilisation, so it is persistent: a slump that ends does not immediately restore full
    # employment, and a boom does not immediately absorb everyone. Utilisation still sets the
    # *shape* across classes and regions; the aggregate level moves gradually with the output gap.
    from . import causality
    labor_w = [(labor(p), p.unemployment) for p in pops if p.cls in ("workers", "middle")]
    total = sum(x for x, _ in labor_w)
    u_util = (sum(x * u for x, u in labor_w) / total) if total else 0.05
    u_okun = causality.okun_step(w, previous_gap=e.prev_output_gap, current_gap=e.output_gap)
    if total and u_util > 1e-6:
        scale = clamp(u_okun / u_util, 0.35, 2.8)
        for p in pops:
            if p.cls in ("workers", "middle"):
                p.unemployment = clamp(p.unemployment * scale, 0.005, 0.75)
    e.unemployment = u_okun
    _protests(w, rng)
    _rebel_regions(w, rng)


def _identity_drift(w: World, pops: list, reach: float, gap: float, health: float) -> None:
    dip = w.dip
    groups = {}
    for p in pops:
        groups.setdefault((p.region, p.cls), {})[p.ident] = p
    for g in groups.values():
        k, i = g.get("karamanian"), g.get("imperial")
        if k is None or i is None:
            continue
        k2i = 0.0008 + 0.008 * reach * max(0.0, 0.5 - k.approval) + 0.004 * max(0.0, gap)
        i2k = (0.0008 + 0.006 * dip.rally + 0.003 * max(0.0, i.approval - 0.45)
               + 0.02 * max(0.0, health - 0.06))
        flow = k.size * k2i - i.size * i2k
        if flow > 0:
            _convert(k, i, flow)
            w.count("to_imperial", flow)
        elif flow < 0:
            _convert(i, k, -flow)
            w.count("to_karamanian", -flow)


def _convert(src, dst, n: float) -> None:
    """People change identity: they keep their circumstances, adopt the new national view."""
    n = min(n, src.size * 0.2)
    keep = dst.indep
    _merge(dst, src, n)
    dst.indep = keep
    src.size -= n


def _protests(w: World, rng) -> None:
    pol, c, m = w.policy, w.const, w.mil
    national = []
    for r in w.k_regions():
        rp = [p for p in w.pops if p.region == r.id]
        size = sum(p.size for p in rp)
        r.repression_event *= 0.6
        r.strike = 0.0
        if size <= 0:
            continue
        u_r = sum(p.unrest * p.size for p in rp) / size
        r.unrest = u_r
        if u_r <= 0.33:
            continue
        protesters = size * (u_r - 0.33) * 0.25
        w.count("protests", 1)
        resp = pol.protest_response
        illegal = " The protests are illegal under the ban on assembly." if c.assembly == "banned" else ""
        if resp == "tolerate":
            r.strike = min(0.25, (u_r - 0.33) * 0.6)
            for p in rp:
                p.grievance = max(0.0, p.grievance - 0.02)
            w.event("protest", f"Protests and strikes in {r.name}: about {protesters:,.0f} people on the "
                    f"streets. Police are not intervening.{illegal}", region=r.id, importance=1)
            continue
        if resp == "negotiate":
            # Conciliation works on the political cause of the protest rather than its symptoms, so
            # it lowers grievance directly -- but a government the public does not believe has no
            # words that carry, so the relief is gated on credibility and capped. It reaches only the
            # regions that are actually protesting and cannot outlast real hardship: it is a
            # deliberate instrument of de-escalation, not a way to switch unrest off.
            credibility = clamp((w.avg("approval") - 0.30) / 0.40, 0.0, 1.0)
            relief = 0.02 + 0.13 * credibility
            r.strike = min(0.12, (u_r - 0.33) * 0.3)
            for p in rp:
                p.grievance = max(0.0, p.grievance - relief)
            w.event("protest", f"National dialogue in {r.name}: the government opens talks with the "
                    f"protesters, who begin to stand down; about {protesters:,.0f} people remain.{illegal}",
                    region=r.id, importance=1)
            continue
        force = m.police
        obey = clamp(0.35 + 0.55 * force.loyalty + 0.2 * force.bond
                     - (0.25 if u_r > 0.6 else 0.0) - (0.15 if resp == "lethal" else 0.0), 0.05, 0.98)
        if rng.random() > obey:
            r.strike = 0.3
            force.morale = clamp(force.morale - 0.1, 0.05, 0.95)
            force.loyalty = clamp(force.loyalty - 0.05, 0.05, 0.95)
            for p in rp:
                p.grievance = min(1.2, p.grievance + 0.05)
            w.count("refusals", 1)
            w.event("refusal", f"Police in {r.name} refused orders to {('fire on' if resp == 'lethal' else 'disperse')} "
                    f"about {protesters:,.0f} protesters.", region=r.id, importance=2)
            continue
        if resp == "disperse":
            dead = protesters * 0.0002
            r.strike = min(0.2, (u_r - 0.33) * 0.4)
            r.repression_event = max(r.repression_event, 0.15)
            for p in rp:
                p.approval = clamp(p.approval - 0.03, 0.01, 0.99)
                p.grievance = min(1.2, p.grievance + 0.04)
            _kill_civilians(w, r.id, dead, "deaths_state_violence")
            w.event("protest", f"Police dispersed about {protesters:,.0f} protesters in {r.name}; "
                    f"{dead:,.0f} dead, many injured.{illegal}", region=r.id, importance=1)
        else:
            dead = protesters * 0.003 * rng.uniform(0.5, 1.5)
            r.repression_event = 0.4
            for p in rp:
                p.approval = clamp(p.approval - 0.12, 0.01, 0.99)
                p.grievance = min(1.2, p.grievance + 0.12)
            national.append(r.id)
            _kill_civilians(w, r.id, dead, "deaths_state_violence")
            w.count("lethal_crackdowns", 1)
            w.adjust_league_trust(-0.2)
            w.event("crackdown", f"Security forces opened fire on about {protesters:,.0f} protesters in "
                    f"{r.name}. About {dead:,.0f} people were killed.{illegal}", region=r.id, importance=3)
    if national:
        hit = 0.015 if c.press == "censored" else 0.03
        for p in w.k_pops():
            if p.region not in national:
                p.approval = clamp(p.approval - hit, 0.01, 0.99)


def _rebel_regions(w: World, rng) -> None:
    """Armed uprisings where Union-backed militias have guns and people are angry enough."""
    m, dip = w.mil, w.dip
    for r in [x for x in w.regions if x.nation == "karamaniya"]:
        rp = [p for p in w.pops if p.region == r.id]
        size = sum(p.size for p in rp)
        if size <= 0:
            continue
        imperial = sum(p.size for p in rp if p.ident == "imperial") / size
        garrison_share = m.deploy.get(r.front, 0.0) if r.front else (m.deploy.get("capital", 0.0) if r.capital else 0.05)
        garrison = (m.army.size * garrison_share * (0.4 + 0.6 * min(1.0, m.army.equipment)) * m.army.morale
                    + m.police.size * size / max(1.0, sum(p.size for p in w.pops)) * 0.3)
        if r.controller == "karamaniya":
            u_r = r.unrest
            if dip.arms_smuggling and imperial > 0.35 and u_r > 0.5:
                rebels = size * 0.004 * u_r * imperial * 2
                if rebels > garrison * 1.1 and rng.random() < 0.5:
                    r.rebels = rebels
                    occupy(w, r.id, "rebels")
                    w.event("uprising", f"Armed Imperial Restoration militias have seized {r.name} and "
                            "declared a People's Republic. They ask the Union for protection.",
                            importance=3, region=r.id)
                    dip.rally = min(1.0, dip.rally + 0.2)
        elif r.controller == "rebels":
            r.rebels *= 1.02 if dip.arms_smuggling else 0.97
            if w.policy.posture == "attack" and garrison > r.rebels * 1.5:
                dead = r.rebels * 0.15 + size * 0.001
                _kill_civilians(w, r.id, size * 0.001, "deaths_war_civilian")
                w.count("rebels_killed", r.rebels * 0.15)
                r.controller = "karamaniya"
                r.rebels = 0.0
                r.damage = clamp(r.damage + 0.05)
                w.event("recaptured", f"The army retook {r.name} from the rebels. About {dead:,.0f} people "
                        "died in the fighting.", importance=3, region=r.id)
