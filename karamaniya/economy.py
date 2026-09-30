"""Money, prices, production, trade, food and the state budget of Karamaniya.

Prices follow a quantity-of-money model with Cagan-style money demand: when people
expect inflation they spend money faster, which feeds more inflation. All three
countries start inside the imperial crown, so whoever prints crowns pushes inflation
onto everyone who uses them. Karamaniya can leave by launching its own currency.
"""
from __future__ import annotations

import math

from . import regional
from .world import (FOOD_VALUE, K_FOOD, K_IND, K_SERV, LABOR_SHARE, World, annualize,
                    clamp)

ALPHA = 4.0          # how strongly expected inflation speeds up spending
THETA = 0.7          # how much interest paid on money offsets expected inflation
BASE_TERM = 0.003 - THETA * 0.06 / 12
PRICE_SPEED = 0.35   # share of the gap to the money-implied price level closed per month
CREDIT_GROWTH = 0.003  # normal monthly money growth from bank lending
ADMIN_SHARE = 0.03   # administration costs, share of GDP
REQUISITION = {"none": 0.0, "partial": 0.15, "heavy": 0.35}
FOOD_WEIGHT = {"elite": 4.0, "middle": 1.8, "workers": 1.0, "farmers": 1.0}
WORLD_FOOD_PRICE = 25.0   # gold per food unit on overseas markets
EXPORTS0 = 62e6           # overseas exports per month at start, gold


def labor(p) -> float:
    return max(0.0, p.size * LABOR_SHARE - p.conscripted - p.interned)


def front_region(w: World, front: str):
    from .world import FRONT_CHAINS
    for rid in FRONT_CHAINS[front]:
        r = w.region(rid)
        if r.controller == "karamaniya":
            return r
    return None


def expected_annual(w: World) -> float:
    if not w.zones:
        return annualize(0.003)
    return annualize(w.zone_of("karamaniya").exp_infl)


# ---- potential output and the output gap ------------------------------------------------
def frictionless(w: World) -> float:
    """What the labour force could produce with nothing in the way.

    Not "full employment" in the textbook sense: this is the same production function the economy
    actually runs, evaluated with normal weather, no strikes, no war damage, intact logistics, full
    energy and no credit or confidence constraint. The difference between this and what is actually
    produced is the output gap, and it is that difference — not output itself — that carries the
    demand pressure.

    Conscription, internment and emigration lower this, because they remove labour. That is the
    channel by which a war effort costs the economy output it never gets back.
    """
    food = industry = services = 0.0
    for r in w.k_regions():
        pops = [p for p in w.pops if p.region == r.id]
        farm = sum(labor(p) for p in pops if p.cls == "farmers")
        workers = sum(labor(p) for p in pops if p.cls == "workers")
        middle = sum(labor(p) for p in pops if p.cls == "middle")
        food += farm * r.land * K_FOOD
        industry += workers * 0.94 * r.industry * K_IND
        services += middle * 0.95 * r.services * K_SERV
    return food * FOOD_VALUE + industry + services


def update_potential(w: World, prod: dict) -> None:
    """Move potential output slowly, then read the gap off it.

    Potential is a *stock* that grows: it must not jump because this month's harvest was good.
    It grows with the world's structural productivity rate, less whatever permanent damage the
    war and the unrest have done. `e.productivity` is normalised at the founding so that the
    starting gap is the one the founding conditions actually imply, not zero by assumption.
    """
    from . import causality
    e = w.econ
    structural = causality.param(w, "productivity_growth")
    damage = sum(r.damage for r in w.k_regions()) / max(1, len(w.k_regions()))
    war_drag = 0.004 if w.dip.war else 0.0
    unrest_drag = 0.0015 * max(0.0, w.avg("unrest") - 0.15)
    e.productivity *= (1.0 + structural - 0.02 * damage - war_drag - unrest_drag)
    e.potential_output = frictionless(w) * e.productivity
    e.prev_output_gap = e.output_gap
    e.output_gap = (prod["gdp_real"] / e.potential_output - 1.0) if e.potential_output > 0 else 0.0


# ---- production ------------------------------------------------------------------------
def produce(w: World) -> dict:
    from . import causality
    e, pol, dip = w.econ, w.policy, w.dip
    kessel = w.region("kessel")
    kessel_ok = 1.0 if kessel.controller == "karamaniya" else 0.0
    highlands_ok = 1.0 if w.region("highlands").controller == "karamaniya" else 0.0
    from .foreign import effective_embargo
    coal_restriction = effective_embargo(w, "veleria", "coal")
    union_coal = 0.0 if dip.war else 0.40 * (1 - coal_restriction)
    # Mines expand when coal from Veleria stops coming, over many months.
    shortfall = 0.40 - union_coal
    e.mining = clamp(e.mining + (0.02 if shortfall > 0.1 else -0.01), 0.0, min(0.25, shortfall))
    domestic = (0.40 * kessel_ok * (1 - kessel.strike) * (1 - kessel.damage)
                + e.mining * (0.5 * kessel_ok + 0.5 * highlands_ok))
    overseas = (0.5 if pol.imports == "max" else 0.2) * (1 - dip.blockade_eff) * e.import_scale * e.energy_import_capacity
    energy = clamp(domestic + union_coal + overseas, 0.05, 1.0)

    exp_annual = expected_annual(w)
    real_rate = pol.rate - exp_annual
    # Credit availability is a stock that moves toward what the rate implies, not a function of it.
    # This is what makes a rate rise take months to bite: the target moves at once, the quantity of
    # credit follows. Without the lag, monetary policy acted with a speed no bank has.
    credit = causality.credit_step(w, causality.rate_target(w, real_rate))
    unrest = w.avg("unrest")
    war = 1.0 if dip.war else 0.0
    uncertainty = clamp(1 - 0.12 * max(0.0, unrest - 0.1) - 0.06 * war - 0.05 * dip.blockade_eff
                        - 0.05 * clamp(exp_annual - 0.5, 0.0, 2.0), 0.6, 1.0)
    taxdrag = clamp(1 - 0.4 * max(0.0, pol.tax - 0.25), 0.75, 1.0)
    admin = clamp(0.9 + 0.1 * e.admin_capacity, 0.8, 1.0)
    capctl = 0.98 if pol.capital_controls else 1.0
    # Demand support from past spending changes, scaled by the state-dependent multiplier: the
    # same crown does more work when there is idle capacity to absorb it. Bounded, so this is a
    # nudge on utilisation rather than a lever that can make the economy produce anything.
    demand_support = clamp(1.0 + 0.8 * e.fiscal_impulse * causality.fiscal_multiplier(w), 0.85, 1.15)
    util_ind = min(energy ** 0.6, credit * uncertainty) * taxdrag * capctl * demand_support

    fronts = set()
    if dip.war:
        for f in ("north", "east"):
            r = front_region(w, f)
            if r is not None and dip.union_front.get(f, 0) > 0:
                fronts.add(r.id)

    food = industry = services = 0.0
    util = {}
    for r in w.k_regions():
        pops = [p for p in w.pops if p.region == r.id]
        d_farm = (1 - r.damage) * (0.8 if r.id in fronts else 1.0)   # farmers do not strike
        d = d_farm * (1 - r.strike)
        farm = sum(labor(p) for p in pops if p.cls == "farmers")
        workers = sum(labor(p) for p in pops if p.cls == "workers")
        middle = sum(labor(p) for p in pops if p.cls == "middle")
        util_serv = (credit * uncertainty * taxdrag * admin * capctl * demand_support
                     * (1 - 0.45 * dip.blockade_eff if r.coast else 1.0))
        # Productivity multiplies what the same labour can produce. It is applied to actual
        # output as well as to potential, so that the output gap measures frictions and demand
        # rather than being contaminated by the trend: without this, potential grows every month
        # and actual does not, and the gap drifts permanently negative for no economic reason.
        food += farm * r.land * K_FOOD * e.weather * e.farm_incentive * d_farm * r.logistics * e.productivity
        industry += workers * 0.94 * r.industry * K_IND * util_ind * d * r.logistics * e.productivity
        services += middle * 0.95 * r.services * K_SERV * util_serv * d * r.logistics * e.productivity
        util[r.id] = {
            "workers": clamp(1 - 0.94 * util_ind * (1 - 0.5 * r.damage), 0.03, 0.85),
            "middle": clamp(1 - 0.95 * util_serv * (1 - 0.5 * r.damage), 0.03, 0.85),
        }
    out = {"food": food, "industry": industry, "services": services,
           "gdp_real": food * FOOD_VALUE + industry + services, "energy": energy,
           "unemployment": util, "credit": credit, "uncertainty": uncertainty}
    # Once potential output has been established at the founding, keep it moving with it.
    if e.potential_output > 0:
        update_potential(w, out)
    return out


# ---- trade and food --------------------------------------------------------------------
def trade_and_food(w: World, prod: dict) -> dict:
    e, pol, dip = w.econ, w.policy, w.dip
    from .foreign import effective_embargo
    grain_restriction = effective_embargo(w, "dorsania", "grain")
    coal_restriction = effective_embargo(w, "veleria", "coal")
    in_crown = e.currency == "crown"
    sea = 1 - dip.blockade_eff

    dors_route = 1.0 if (w.region("dorran").controller == "karamaniya" and not dip.war) else 0.0
    trade_bonus = (.14e6 if w.counters.get("dorsania_trade", 0) and w.month <= w.counters.get("dorsania_trade_until", -1) else 0.0)
    food_dors = (0.85e6 * (1 - grain_restriction) + trade_bonus) * dors_route * e.food_import_capacity
    maxed = pol.imports == "max"
    food_over_want = (1.2e6 if maxed else 0.37e6) * sea * e.food_import_capacity
    fuel_cost = (0.5 if maxed else 0.2) * sea * 60e6
    goods_want = (15e6 if maxed else 38e6) * sea
    union_cost = union_exports = 0.0
    if not in_crown and not dip.war:
        union_cost = food_dors * WORLD_FOOD_PRICE + 0.40 * (1 - coal_restriction) * 60e6
        union_exports = 45e6 * (1 - 0.5 * max(grain_restriction, coal_restriction))
    ind_ratio = prod["industry"] / e.industry0 if e.industry0 else 1.0
    exports = (EXPORTS0 * sea * clamp(ind_ratio, 0.2, 1.3) ** 0.8 * (0.7 if dip.war else 1.0)
               * (1.1 if w.counters.get("league_trade") else 1.0))
    loans = min(dip.league_loan_pending, 25e6)
    dip.league_loan_pending -= loans
    e.debt_for += loans
    if loans and w.foreign.get("league"):
        league = w.foreign["league"]
        league["loan"]["principal"] += loans
        league["financial_exposure"] = min(1.0, league["loan"]["principal"] / 300e6)

    exp_annual = expected_annual(w)
    flight_rate = (0.015 * clamp(exp_annual, 0.0, 2.0) + (0.03 if dip.war else 0.0)
                   + (0.06 if e.currency_launch >= 0 and in_crown else 0.0)
                   + 0.02 * max(0.0, w.avg("unrest") - 0.3))
    if pol.capital_controls:
        flight_rate *= 0.2
    flight = max(0.0, e.gold) * flight_rate
    spend_want = food_over_want * WORLD_FOOD_PRICE + fuel_cost + goods_want + union_cost
    available = max(0.0, e.gold - flight) + exports + union_exports + loans
    scale = 1.0 if spend_want <= available else available / spend_want
    e.import_scale = scale
    e.gold = e.gold - flight + exports + union_exports + loans - spend_want * scale
    food_over = food_over_want * scale
    e.goods_imports = goods_want * scale
    if union_cost > 0:
        food_dors *= scale

    # Food market.
    pops = w.k_pops()
    req_share = REQUISITION[pol.requisition]
    # Post-harvest losses, before anything is eaten or stored. The empirically supported figure for
    # cereals in weak-infrastructure economies is roughly 10-20% from harvest to market, and it is
    # concentrated in field drying, farm storage and market storage rather than in bulk transport.
    # The 30-40% figures sometimes quoted for grain are not supported and are not used here.
    loss = food_loss_rate(w)
    e.food_loss = loss
    harvest = prod["food"] * (1 - loss)
    farm_food = harvest * (1 - req_share)
    e.state_grain += harvest * req_share
    farmers = [p for p in pops if p.cls == "farmers"]
    others = [p for p in pops if p.cls != "farmers"]
    farmers_need = sum(p.size for p in farmers)
    need_nf = sum(p.size for p in others)
    farmer_eat = min(farmers_need, farm_food)
    market = farm_food - farmer_eat
    imports = food_dors + food_over
    gap = need_nf - (market + imports)
    release = min(e.state_grain, max(0.0, gap) * (0.8 if pol.rationing else 0.3))
    e.state_grain -= release
    gap -= release
    if gap > 0:
        draw = min(e.food_stock, gap * 0.6)
        e.food_stock -= draw
    else:
        draw = 0.0
        e.food_stock = min(4.0e6, e.food_stock + (-gap) * 0.5)
    supply = market + imports + release + draw
    if pol.price_controls in ("food", "all"):
        supply *= 0.92          # hoarding and black-market leakage

    # Who eats. Farmers feed themselves first.
    farmer_pc = farmer_eat / farmers_need if farmers_need else 1.0
    for p in farmers:
        p.hunger = clamp(1 - farmer_pc * 1.02, 0.0, 1.0)
    # Food reaches people region by region, and a region can only be supplied as fast as its
    # transport can move. This is why a country with a national surplus can still have a hungry
    # province: the surplus exists, and it is on the wrong side of a broken road. The literature
    # on spatial market integration puts it as an arbitrage band -- trade flows only when the price
    # gap exceeds the cost of moving the goods -- which is what `delivery_capacity` encodes.
    region_rows = []
    for r in w.k_regions():
        grp = [p for p in others if p.region == r.id]
        need_r = sum(p.size for p in grp)
        if need_r > 0:
            region_rows.append((r, grp, need_r))
    delivered = _deliver_to_regions(region_rows, supply)

    welfare_boost = 1 + 10 * max(0.0, pol.welfare * e.paid_share - 0.02)
    controls = 0.8 if pol.price_controls in ("food", "all") else 1.0
    if pol.rationing:
        # Rationing shares what actually arrived, so it equalises within a region but cannot
        # conjure food into one the roads did not reach.
        for r, grp, need_r in region_rows:
            ration = min(1.0, delivered.get(r.id, 0.0) * 0.96 / need_r) if need_r else 1.0
            for p in grp:
                p.hunger = clamp(1 - ration, 0.0, 1.0)
    else:
        for r, grp, need_r in region_rows:
            weights = {}
            for i, p in enumerate(grp):
                wt = FOOD_WEIGHT[p.cls] * (1 - 0.5 * p.unemployment)
                if p.cls == "workers":
                    wt *= welfare_boost * controls
                elif p.cls == "middle":
                    wt *= (0.5 + 0.5 * welfare_boost) * controls
                weights[i] = wt
            alloc = _water_fill([p.size for p in grp], weights, delivered.get(r.id, 0.0))
            for i, p in enumerate(grp):
                p.hunger = clamp(1 - alloc[i] / p.size, 0.0, 1.0) if p.size else 0.0

    # A region is short when less reached it than its people need. Recorded explicitly so the
    # national ratio and the regional reality can be read side by side -- the whole point is that
    # "food availability is 103%" and "Kessel is hungry" can both be true.
    e.food_short_regions = sorted(
        r.id for r, _grp, need_r in region_rows
        if need_r > 0 and delivered.get(r.id, 0.0) < need_r * 0.95)
    need = farmers_need + need_nf
    e.food_ratio = (supply + farmer_eat) / need if need else 1.0
    target_rel = clamp((need_nf / max(supply, 1.0)) ** 1.8, 0.6, 12.0)
    e.food_rel = 0.5 * e.food_rel + 0.5 * target_rel
    e.imports_food = imports
    return {"food_dors": food_dors, "food_over": food_over, "exports": exports,
            "loans": loans, "capital_flight": flight, "released": release}


# Post-harvest losses. A baseline for handling, drying and farm storage, plus a transport and
# market-storage component that scales with how bad the region's logistics are. Calibrated to the
# APHLIS / World Bank range of roughly 10-20% of grain lost from harvest to market in
# weak-infrastructure economies, with bulk transport a small part of it.
FOOD_LOSS_BASE = 0.075
FOOD_LOSS_TRANSPORT = 0.10


def food_loss_rate(w: World) -> float:
    """Share of the harvest lost before it can be eaten, from storage and from moving it."""
    regions = w.k_regions()
    if not regions:
        return FOOD_LOSS_BASE
    logistics = sum(r.logistics for r in regions) / len(regions)
    return clamp(FOOD_LOSS_BASE + FOOD_LOSS_TRANSPORT * (1.0 - logistics), 0.02, 0.30)


def delivery_capacity(region) -> float:
    """Multiple of a region's need that its transport can actually move to it.

    At intact logistics this is above one, so nothing is constrained. As logistics degrade the
    ceiling falls, and a region can be short of food that exists elsewhere in the country.
    """
    return 0.55 + 0.45 * clamp(region.logistics, 0.0, 1.2)


def _deliver_to_regions(rows: list, supply: float) -> dict:
    """Move national supply out to the regions, subject to how much each can receive.

    Water-fills by need, then re-offers whatever the constrained regions could not absorb to the
    ones with headroom left under their ceiling. Iterated a few times so a single broken corridor
    does not strand the surplus; bounded, because each pass can only move food toward capacity.
    """
    delivered = {r.id: 0.0 for r, _grp, _need in rows}
    if not rows or supply <= 0:
        return delivered
    heads = {r.id: need * delivery_capacity(r) for r, _grp, need in rows}
    remaining = supply
    for _ in range(6):
        if remaining <= 1e-6:
            break
        open_rows = [(r, need) for r, _grp, need in rows if delivered[r.id] < heads[r.id] - 1e-6]
        if not open_rows:
            break
        # Share the remainder by each region's remaining need, never above its delivery ceiling.
        wants = {r.id: max(0.0, need - delivered[r.id]) for r, need in open_rows}
        total_want = sum(wants.values())
        if total_want <= 1e-6:
            break
        moved = 0.0
        for r, _need in open_rows:
            give = min(remaining * (wants[r.id] / total_want), heads[r.id] - delivered[r.id])
            delivered[r.id] += give
            moved += give
        if moved <= 1e-9:
            break
        remaining -= moved
    return delivered


def _water_fill(sizes: list, weights: dict, supply: float) -> list:
    """Split food by purchasing power, never giving anyone more than they need."""
    alloc = [0.0] * len(sizes)
    open_ = set(range(len(sizes)))
    left = supply
    for _ in range(12):
        if left <= 1e-6 or not open_:
            break
        total_w = sum(weights[i] * sizes[i] for i in open_)
        if total_w <= 0:
            break
        capped = set()
        spent = 0.0
        for i in open_:
            give = left * weights[i] * sizes[i] / total_w
            room = sizes[i] - alloc[i]
            if give >= room:
                give = room
                capped.add(i)
            alloc[i] += give
            spent += give
        left -= spent
        open_ -= capped
        if not capped:
            break
    return alloc


# ---- who the government owes -----------------------------------------------------------
# When the budget cannot be met, the shortfall lands on categories in proportion to their share
# of the bills. What matters politically is not the total but the composition: the historical
# record shows military pay arrears immediately preceding coups in Côte d'Ivoire (1999), the
# Gambia (1994), Guinea-Bissau (2004) and Sierra Leone (1992); civil-service arrears turning into
# strikes after roughly two to three months; and contractors who have been left unpaid bidding
# higher or declining to bid at all.
# The share of monthly output the debt market will absorb in gross issuance. Calibrated so that
# at the founding the rollover calendar consumes most of it and net new borrowing is the 2% of
# monthly output the model used before the rollover channel existed.
GROSS_BORROWING_CAPACITY = 0.10
ARREARS_CATEGORIES = ("army", "police", "civil_service", "contractors", "foreign_debt")
CIVIL_SERVICE_STRIKE_MONTHS = 2.5   # months of unpaid wages before the service starts to break
PROCUREMENT_PREMIUM_CAP = 0.35      # most contractors will add when they are owed a lot
# Not all of the military line is pay: some of it buys things, and the firms that sell them are
# contractors. Without this the contractor category is dormant under default policy, because the
# military budget is almost the whole of government procurement.
CONTRACTOR_MILITARY_SHARE = 0.40


def budget_bills(w: World) -> dict:
    """The monthly bill owed to each category, in domestic currency.

    ONE source of truth. Accrual and `arrears_months` both read this, because when they were
    computed separately they disagreed: the accrual used a full monthly bill while the month
    converter divided that same bill by twelve, so a single month of unpaid wages reported as a
    full year owed. Every differentiated consequence downstream fired twelve times too early.
    """
    e, pol = w.econ, w.policy
    gdp = max(1.0, e.gdp_nominal)
    return {
        "army": pol.military * (1.0 - CONTRACTOR_MILITARY_SHARE) * gdp,
        "police": pol.police * gdp,
        "civil_service": (pol.health_edu + pol.welfare + ADMIN_SHARE) * gdp,
        "contractors": (pol.military * CONTRACTOR_MILITARY_SHARE + pol.farm_support
                        + regional.spending(w)) * gdp,
        "foreign_debt": max(1.0, e.interest_for),
    }


# The order in which a government stops paying when it runs out of money. Soldiers and police are
# paid first — this is not a moral claim but the historical record: military pay arrears preceded
# coups in Côte d'Ivoire (1999), the Gambia (1994), Guinea-Bissau (2004) and Sierra Leone (1992),
# and governments behaved accordingly. Suppliers and civil servants are where the shortfall lands.
ARREARS_PRIORITY = ("army", "police", "civil_service", "contractors", "foreign_debt")


def _accrue_arrears(w: World, e, unpaid: float) -> None:
    """Push a shortfall onto the least-protected bills first.

    Proportional accrual would make every category report the same number of months behind, which
    carries no information the aggregate did not already have. Paying in priority order is both
    more realistic and what makes the composition worth tracking: a government that is short of
    money is one that has stopped paying its suppliers, not one that has halved everyone's wages.
    """
    bills = budget_bills(w)
    remaining = unpaid
    for name in reversed(ARREARS_PRIORITY):
        if remaining <= 0:
            break
        owed_this_month = bills.get(name, 0.0)
        if owed_this_month <= 0:
            continue
        take = min(remaining, owed_this_month)
        e.arrears_by[name] = e.arrears_by.get(name, 0.0) + take
        remaining -= take
    if remaining > 1e-6:
        # Everything this month is already unpaid; the remainder falls on suppliers.
        e.arrears_by["contractors"] = e.arrears_by.get("contractors", 0.0) + remaining


def settle_arrears(w: World, amount: float) -> float:
    """Pay down arrears, keeping the composition in step with the total.

    Every path that reduces `e.arrears` must come through here. Three of them used to write the
    total directly — a council motion funded from reserves or bonds, and the seeded inherited
    liabilities — which left the composition describing debts that had already been paid: settling
    everything in full still left the administration destroyed and suppliers still repricing.
    """
    e = w.econ
    owed = sum(max(0.0, e.arrears_by.get(name, 0.0)) for name in ARREARS_CATEGORIES)
    paid = max(0.0, min(amount, max(e.arrears, owed)))
    if paid <= 0:
        return 0.0
    if owed > 0:
        scale = min(1.0, paid / owed)
        for name in ARREARS_CATEGORIES:
            e.arrears_by[name] = max(0.0, e.arrears_by.get(name, 0.0) * (1.0 - scale))
    e.arrears = max(0.0, e.arrears - paid)
    return paid


def seed_arrears(w: World, amount: float) -> None:
    """Record inherited unpaid bills with a composition, not just a total."""
    if amount <= 0:
        return
    e = w.econ
    bills = budget_bills(w)
    total = sum(bills.values())
    if total <= 0:
        e.arrears_by["civil_service"] = e.arrears_by.get("civil_service", 0.0) + amount
    else:
        for name, bill in bills.items():
            e.arrears_by[name] = e.arrears_by.get(name, 0.0) + amount * (bill / total)
    e.arrears += amount


def arrears_months(w: World) -> dict:
    """How many months of pay or payment each category is owed.

    A stock in crowns says little on its own; the number of months behind says everything, and it
    is what the historical triggers are actually stated in. The bills come from `budget_bills`,
    the same function the accrual uses, so the two cannot drift apart again.
    """
    e = w.econ
    bills = budget_bills(w)
    return {name: (e.arrears_by.get(name, 0.0) / bills[name] if bills[name] > 0 else 0.0)
            for name in ARREARS_CATEGORIES}


def procurement_premium(w: World) -> float:
    """What contractors add to their price because the government already owes them money.

    Grounded in the 2012 Spanish accelerated-payment episode: firms holding unpaid public bills
    were markedly less likely to take new public work and bid differently when they did. The
    premium is capped, because eventually suppliers simply stop bidding.
    """
    e = w.econ
    months = arrears_months(w)["contractors"]
    premium = 1.0 + clamp(0.06 * months, 0.0, PROCUREMENT_PREMIUM_CAP)
    e.procurement_premium = premium
    return premium


# ---- the state budget ------------------------------------------------------------------
def fiscal(w: World, prod: dict, trade: dict) -> dict:
    e, pol, dip = w.econ, w.policy, w.dip
    z = w.zone_of("karamaniya")
    gdp_nom = prod["gdp_real"] * e.cpi
    e.gdp_nominal = gdp_nom
    unrest = w.avg("unrest")
    exp_annual = annualize(z.exp_infl)

    e.compliance = clamp(0.88 - 0.35 * max(0.0, unrest - 0.08) - 0.1 * (1 - e.admin_capacity),
                         0.3, 0.95)
    olivera_tanzi = 1 / (1 + 1.5 * max(0.0, e.infl))
    revenue = (pol.tax * gdp_nom * e.compliance * olivera_tanzi
               + 0.02 * gdp_nom * (1 - dip.blockade_eff) * (0.5 if dip.war else 1.0)
               + 0.01 * gdp_nom)

    gold_to_local = z.price / (e.fx_conf if e.currency == "karam" else 1.0)
    debt_ratio = (e.debt_dom + e.debt_for * gold_to_local) / max(1.0, 12 * gdp_nom)
    risk = clamp(0.5 * max(0.0, debt_ratio - 0.6) + 0.5 * max(0.0, exp_annual - 0.2), 0.0, 0.4)
    league_loan = w.foreign.get("league", {}).get("loan", {})
    league_principal = max(0.0, league_loan.get("principal", 0.0))
    league_rate = league_loan.get("interest", .05)
    league_share = clamp(league_principal / e.debt_for) if e.debt_for > 0 else 0.0
    foreign_rate = .05 * (1 - league_share) + league_rate * league_share
    # Domestic and foreign interest are kept apart: they behave differently. Domestic interest is
    # paid in the country's own money and can in principle be met by issuance; foreign interest is
    # a claim in someone else's money and can only be met from reserves, exports or new borrowing
    # abroad. Only the domestic rate reprices as the policy rate moves, because only the maturing
    # slice of the stock is refinanced each month.
    e.interest_dom = e.debt_dom * (pol.rate + 0.02 + risk) / 12
    e.interest_for = e.debt_for * foreign_rate / 12 * gold_to_local
    interest = e.interest_dom + e.interest_for
    e.rollover_need = e.debt_short_share * e.debt_dom / 12.0
    if pol.debt_service == "suspend":
        interest = 0.0
        e.default_months += 1
    patronage = sum(1 for v in pol.patronage.values() if v) * 0.002 * gdp_nom
    # Contractors who are owed money bid higher for new work, so the same programme costs more.
    # This is the feedback that turns a payment problem into a permanent one: arrears raise the
    # cost of the spending that would have cleared them.
    premium = procurement_premium(w)
    base_programs = (pol.military + pol.police + pol.welfare + pol.health_edu + pol.farm_support
                     + ADMIN_SHARE + regional.spending(w))
    # Only the procurement-heavy slice reprices. Wages do not rise because suppliers are unpaid.
    procurement_heavy = pol.military + regional.spending(w)
    programs = (base_programs + procurement_heavy * (premium - 1.0)) * gdp_nom
    spending = programs + patronage + interest

    scandal = 1.0 if w.month - e.scandal_month < 6 else 0.0
    e.confidence = clamp(1 - 1.5 * clamp(exp_annual - 0.1, 0.0, 1.0) - 0.4 * max(0.0, unrest - 0.15)
                         - 0.25 * (1.0 if dip.war else 0.0) - 0.3 * scandal
                         - (0.6 if pol.debt_service == "suspend" else 0.0), 0.05, 1.0)
    money_k = z.money["karamaniya"]
    printed = pol.printing * money_k
    z.money["karamaniya"] = money_k + printed
    loans_local = trade["loans"] * gold_to_local
    deficit = spending - revenue
    need = deficit - printed - loans_local
    borrowed = unpaid = 0.0
    if need > 0:
        issued = w.institutions.get("arrears_bonds") or {}
        arrears_bonds = issued.get("amount", 0.0) if issued.get("month") == w.month else 0.0
        # Rolling over maturing debt consumes the same market capacity as fresh borrowing, so a
        # heavy rollover calendar crowds out new issuance rather than sitting outside the budget.
        # The market absorbs a certain amount of GROSS issuance each month, and maturing debt is
        # served from it before anything new is lent. Modelling this as a net-capacity figure
        # minus the rollover calendar double-counts: the earlier constant of 2% of monthly output
        # was calibrated as *new* borrowing, and subtracting a fully-grown rollover need from it
        # made the figure negative, so the default government could borrow nothing and drifted
        # into permanent arrears.
        #
        # Gross capacity is set so that at the founding — 40% of annual output in debt, 20% of it
        # inside a year — gross minus rollover reproduces the original 2% of monthly output. The
        # rollover calendar now genuinely crowds out new issuance without changing the baseline.
        gross = GROSS_BORROWING_CAPACITY * gdp_nom * e.confidence
        capacity = max(0.0, gross - e.rollover_need - arrears_bonds)
        borrowed = min(need, capacity)
        unpaid = need - borrowed
    else:
        surplus = -need
        repay = settle_arrears(w, min(e.arrears, surplus))
        e.debt_dom = max(0.0, e.debt_dom - (surplus - repay))
    e.debt_dom += borrowed
    if unpaid > 0:
        e.arrears += unpaid
        _accrue_arrears(w, e, unpaid)
    base = programs + patronage + interest
    e.paid_share = clamp(1 - unpaid / base, 0.0, 1.0) if base > 0 else 1.0
    e.admin_capacity += 0.15 * ((1 - 1.5 * (1 - e.paid_share)) - e.admin_capacity)
    # Unpaid civil servants break the administration itself, and the historical record puts the
    # threshold near two to three months. Below it, arrears are an irritation; above it, the
    # service starts to stop.
    cs_months = arrears_months(w)["civil_service"]
    e.admin_capacity -= 0.06 * max(0.0, cs_months - CIVIL_SERVICE_STRIKE_MONTHS)
    # Farm output responds to subsidies and falls under requisition, over several months.
    target = (1 + 3.0 * min(0.05, pol.farm_support) * e.paid_share - {"none": 0.0, "partial": 0.25,
              "heavy": 0.45}[pol.requisition] - (0.1 if pol.price_controls in ("food", "all") else 0.0))
    e.farm_incentive += 0.15 * (target - e.farm_incentive)
    e.admin_capacity = clamp(e.admin_capacity, 0.2, 1.0)
    # Reserve adequacy: how many months of imports the reserves could pay for. This is the metric
    # the outside world reads, and the one that decides whether draining them is prudence or a
    # currency crisis. The conventional floor is three months, though the IMF notes the rule has
    # no firm theoretical basis and that countries conventionally hold more.
    monthly_imports = max(1.0, (e.goods_imports + e.imports_food * WORLD_FOOD_PRICE) * gold_to_local)
    e.reserve_months = max(0.0, e.gold * gold_to_local / monthly_imports)
    e.revenue, e.spending, e.deficit = revenue, spending, deficit
    e.printed, e.borrowed, e.loans_in = printed, borrowed, loans_local

    statistics(w)
    from . import causality
    causality.schedule_fiscal_impulse(w)
    paid = e.paid_share
    return {"gdp_nominal": gdp_nom, "revenue": revenue, "spending": spending,
            "deficit": deficit, "printed": printed, "borrowed": borrowed,
            "unpaid": unpaid, "paid_share": paid,
            "mil_paid": pol.military * gdp_nom * paid,
            "police_paid": pol.police * gdp_nom * paid,
            "welfare_eff": pol.welfare * paid, "health_eff": pol.health_edu * paid}


def statistics(w: World) -> None:
    """Published statistics can be massaged. A free press makes a scandal more likely."""
    e, pol, c = w.econ, w.policy, w.const
    if pol.stats != "massaged":
        e.stats_gap = max(0.0, e.stats_gap - 0.25)
        return
    e.stats_gap = 0.5
    press = {"free": 1.0, "restricted": 0.4, "censored": 0.1}[c.press]
    true_annual = annualize(e.infl)
    p = 0.04 + 0.08 * press + 0.1 * clamp(true_annual - 0.3, 0.0, 1.0)
    from .world import rng_for
    if rng_for(w.seed, w.month, "stats").random() < p:
        e.scandal_month = w.month
        z = w.zone_of("karamaniya")
        if e.currency == "karam":
            z.exp_infl += 0.01
        w.dip.league_trust -= 0.25
        w.event("stats_scandal", "Independent economists and journalists show that the official "
                "inflation and output figures have been understated. Public trust in government "
                "statistics has collapsed.", importance=2)
        w.count("stats_scandals", 1)


# ---- money and prices ------------------------------------------------------------------
def money_and_prices(w: World, prod: dict) -> None:
    from . import causality
    e, pol = w.econ, w.policy
    launch_currency_if_due(w)
    for z in w.zones:
        for nid in z.members:
            growth = CREDIT_GROWTH + (w.rivals[nid].printing if nid in w.rivals else 0.0)
            z.money[nid] *= 1 + growth
        y = sum((w.rivals[n].gdp_real if n in w.rivals else _trend_gdp(w, prod)) for n in z.members)
        m = sum(z.money.values())
        rates = {n: (w.rivals[n].rate if n in w.rivals else pol.rate) for n in z.members}
        rate = sum(rates[n] * z.money[n] for n in z.members) / m
        v = math.exp(ALPHA * ((z.exp_infl - THETA * rate / 12) - BASE_TERM))
        target = z.scale * m * v / max(y, 1.0)
        new_p = z.price * (target / z.price) ** PRICE_SPEED
        z.infl = new_p / z.price - 1
        z.price = new_p
        z.exp_infl = clamp(z.exp_infl + 0.25 * (z.infl - z.exp_infl), -0.02, 1.5)

    z = w.zone_of("karamaniya")
    if e.currency == "karam":
        crown = w.zone_of("veleria")
        scandal = 1.0 if w.month - e.scandal_month < 6 else 0.0
        # Reserves, scandal and war already moved confidence; so did the price ratio, which is the
        # inflation differential. What the currency did not yet respond to was the rest of the
        # pressure it is under: an unsustainable deficit, expected money creation, the interest
        # rate paid to hold it, and credit arriving from abroad. Those are added here, bounded and
        # smoothed, so the rate responds continuously rather than jumping on a single month.
        pressure = causality.depreciation_pressure(w)
        e.fx_pressure = pressure["total"]
        extra = (pressure["terms"]["fiscal_risk"] + pressure["terms"]["expected_money_creation"]
                 + pressure["terms"]["interest_rate_support"] + pressure["terms"]["foreign_credit_support"])
        base = (0.6 + 0.4 * min(1.0, e.gold / e.gold0) - 0.15 * scandal
                - (0.1 if w.dip.war else 0.0))
        target = clamp(base - 1.5 * extra, 0.3, 1.1)
        e.fx_conf = clamp(0.65 * e.fx_conf + 0.35 * target, 0.3, 1.1)
        e.fx = crown.price / z.price * e.fx_conf
    imp = 1.0 if e.currency == "crown" else 1.0 / max(0.3, e.fx_conf)

    e.consumer_goods = max(1.0, prod["industry"] - e.arms_diversion + e.goods_imports)
    goods_target = clamp((e.consumer_goods0 / e.consumer_goods) ** 1.1, 0.8, 5.0)
    e.goods_rel = 0.5 * e.goods_rel + 0.5 * goods_target
    food_official = min(e.food_rel, 1.25) if pol.price_controls in ("food", "all") else e.food_rel
    goods_official = min(e.goods_rel, 1.2) if pol.price_controls == "all" else e.goods_rel

    # Import prices in domestic currency: how the rate moved and how world prices moved. A currency
    # crisis becomes a cost-of-living crisis through this index, not directly through the exchange
    # rate, because what households pay depends on the landed cost of what is bought abroad.
    causality.import_price_step(w)
    # Depreciation reaches consumer prices gradually, and how much of it arrives at all is a
    # structural property of the economy rather than a constant. A single month's move does not
    # land in full; the remainder is carried by `e.fx_prev` and arrives over the following months.
    # `e.fx` is crowns per karam, so a FALLING rate is a depreciation and must raise prices.
    fx_change = causality.depreciation(w)
    passthrough = causality.pass_through(w) if e.currency == "karam" else 0.0
    lagged_fx = clamp(fx_change * passthrough * (1.0 - causality.param(w, "price_rigidity")), -0.15, 0.15)
    # Imported input costs reach the consumer basket at the economy's import share, independent of
    # whether the currency itself is the country's own.
    import_cost = clamp(causality.param(w, "import_dependency") * e.import_price_infl, -0.10, 0.12)

    # Persistent demand and money pressure. Small weights: the output gap and the money stock
    # already reach prices through the money-market relation, so these carry only the extra pull
    # from pressure that has been *sustained* rather than a second full Phillips curve.
    urgency = causality.price_pressures(w)
    extra = clamp(1.0 + lagged_fx + import_cost + urgency["demand_pressure"]
                  + urgency["money_pressure"], 0.5, 3.0)

    new_cpi = z.price * (0.40 * e.food_rel * (0.8 + 0.2 * imp)
                         + 0.35 * e.goods_rel * (0.75 + 0.25 * imp) + 0.25) * extra
    e.cpi_official = z.price * (0.40 * food_official * (0.8 + 0.2 * imp)
                                + 0.35 * goods_official * (0.75 + 0.25 * imp) + 0.25) * extra
    e.infl = new_cpi / e.cpi - 1
    e.cpi = new_cpi
    e.infl_history = (e.infl_history + [e.infl])[-12:]
    e.gdp_trend = (e.gdp_trend + [prod["gdp_real"]])[-6:]

    # Expectations: partly anchored on credibility, partly on lived inflation, partly on the
    # currency and the budget. Recorded beside the zone's adaptive expectation, which continues to
    # drive the shared crown price level.
    e.expected_infl = causality.expected_inflation(w)

    productivity = prod["gdp_real"] / e.gdp_real0 if e.gdp_real0 else 1.0
    wage_target = (0.6 * z.price + 0.4 * e.cpi) * (0.85 + 0.15 * productivity)
    e.wage += 0.25 * (1 - e.unemployment) * (wage_target - e.wage)
    # Nominal wage growth is not real wage growth. A raise that trails inflation is a cut, and
    # this is the number that reaches soldiers, civil servants and workers.
    e.wage_prev = e.wage_prev if e.wage_prev > 0 else e.wage
    wage_growth = e.wage / e.wage_prev - 1.0 if e.wage_prev > 0 else 0.0
    e.wage_prev = e.wage
    e.real_wage = e.wage / e.cpi if e.cpi > 0 else 1.0
    e.fx_prev = e.fx

    # Why prices moved, with each channel named. Kept for research and debugging; agents never
    # see it, because a delegate who could read the decomposition would be reading the answer key.
    excess_wage = wage_growth - e.infl
    # Note there is no separate `expectations` line. Expectations reach prices through the
    # money-market velocity of the zone, so they are already inside `zone_price_level`; listing
    # them again would report a contributor that did not independently move anything.
    contributions = {
        "zone_price_level": z.infl * 0.75,
        "food_relative_price": (e.food_rel - 1.0) * 0.04,
        "goods_relative_price": (e.goods_rel - 1.0) * 0.03,
        "exchange_rate_passthrough": lagged_fx,
        "import_cost": import_cost,
        "excess_wage_growth": clamp(excess_wage, -0.05, 0.05) * 0.15,
        "demand_pressure": urgency["demand_pressure"],
        "money_pressure": urgency["money_pressure"],
        "import_shortage": (e.import_scale - 1.0) * -0.03,
    }
    causality.trace(w, "inflation", e.infl, contributions)
    # Output growth feeds real money demand, so it is measured before prices are set next month.
    e.output_growth = (prod["gdp_real"] / e.gdp_prev - 1.0) if e.gdp_prev > 0 else 0.0
    e.gdp_prev = prod["gdp_real"]
    money_growth = (z.money["karamaniya"] / max(1.0, e.money_stock_prev) - 1.0) if e.money_stock_prev > 0 else 0.0
    e.money_stock_prev = z.money["karamaniya"]
    e.money_growth = money_growth
    causality.demand_step(w, e.output_gap)
    causality.money_step(w, money_growth, e.output_growth)
    e.regime = causality.regime(w)
    e.gdp_real = prod["gdp_real"]
    e.food_out, e.industry_out, e.services_out = prod["food"], prod["industry"], prod["services"]
    e.energy = prod["energy"]


def _trend_gdp(w: World, prod: dict) -> float:
    """Prices respond to output over the last six months, not to every monthly swing."""
    trend = w.econ.gdp_trend[-5:]
    return (sum(trend) + prod["gdp_real"]) / (len(trend) + 1)


def launch_currency_if_due(w: World) -> None:
    e = w.econ
    if e.currency != "crown" or e.currency_launch < 0 or w.month < e.currency_launch:
        return
    crown = w.zone_of("karamaniya")
    money = crown.money.pop("karamaniya")
    crown.members.remove("karamaniya")
    y = e.gdp_real
    v = math.exp(ALPHA * ((crown.exp_infl * 0.7 - THETA * w.policy.rate / 12) - BASE_TERM))
    karam = type(crown)(id="karam", name=w.names["karam"], members=["karamaniya"],
                        money={"karamaniya": money}, price=crown.price,
                        exp_infl=crown.exp_infl * 0.7, infl=crown.infl)
    karam.scale = crown.price * y / max(1.0, money * v)
    # Keep the crown's price level continuous for the countries that still use it.
    crown_y = sum(w.rivals[n].gdp_real for n in crown.members)
    crown_v = math.exp(ALPHA * ((crown.exp_infl - THETA * 0.06 / 12) - BASE_TERM))
    crown.scale = crown.price * crown_y / max(1.0, sum(crown.money.values()) * crown_v)
    w.zones.append(karam)
    e.currency = "karam"
    e.fx = 1.0
    w.event("currency", f"The {w.names['karam']} replaces the {w.names['crown']} as Karamaniya's "
            "currency. Crowns are converted one to one.", importance=2)
