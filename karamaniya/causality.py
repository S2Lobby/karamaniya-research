"""The causal world model: structural parameters, lags, regimes, expectations and the trace.

Three kinds of rule live in Karamaniya's economy, and the whole point of this module is to keep
them apart rather than blending them into one score function:

    ACCOUNTING IDENTITIES   exact by construction. Reserves cannot appear from nowhere.
    EMPIRICAL RELATIONSHIPS estimated and uncertain. Okun's law, the Phillips curve, pass-through.
    BEHAVIOURAL RESPONSES   stochastic and state-dependent. Confidence, protest, flight.

Everything here is in the second and third families. The identities stay in economy.py where they
can be checked by arithmetic.

**Parameter uncertainty is the point.** The engine holds *true* structural parameters. Agents are
never shown them. The Treasury may estimate pass-through at 0.25-0.55 with medium confidence while
the true value sits at 0.42. That gap — objective causality versus the model of it that an agent
carries — is what makes governing a matter of learning rather than of reading a manual. A country
whose true parameters were printed on the wall would reward memorising, not governing.

**Nothing here scripts an outcome.** Regimes are descriptive labels computed from state. They are
never instructions, and no policy response is attached to one.
"""
from __future__ import annotations

import math

from .world import World, annualize, clamp, rng_for

# ---------------------------------------------------------------------------------------------
# Structural parameters
# ---------------------------------------------------------------------------------------------
# Each entry is (low, high, unit, rationale). Ranges are deliberately wide enough that the same
# policy is not optimal in every world, and narrow enough to stay plausible for a small island
# economy with an industrial north, a farming interior and a young central bank.
#
# Sources are recorded in docs/CAUSAL_WORLD_MODEL.md. These are *modelling assumptions calibrated
# to a plausible range*, not point estimates of any real country's economy.
STRUCTURAL_PARAMETERS = {
    "import_dependency": (
        0.18, 0.34, "share of consumer supply met from abroad",
        "Island economies with limited arable land and no fuel run import-heavy; the wide band "
        "reflects how much the founding conditions matter."),
    "labor_market_flexibility": (
        0.25, 0.75, "0 rigid .. 1 flexible",
        "Sets how fast unemployment closes an output gap. Rigid labour markets adjust slowly."),
    "tax_compliance": (
        0.62, 0.90, "share of statutory tax actually collected",
        "Pre-modern fiscal capacity. Low compliance is why a high statutory rate need not raise "
        "much revenue."),
    "bureaucratic_efficiency": (
        0.45, 0.85, "share of a voted programme actually delivered",
        "Implementation capacity. The binding constraint on simultaneous reform."),
    "inflation_persistence": (
        0.35, 0.75, "weight on last month's inflation in this month's",
        "How much of past inflation carries forward. High values mean one month of tight policy "
        "cannot end an inflation."),
    "exchange_rate_pass_through": (
        0.15, 0.55, "share of a depreciation reaching consumer prices",
        "Higher where imports dominate the consumption basket and contracts are short."),
    "fiscal_multiplier_normal": (
        0.50, 1.10, "crowns of output per crown of spending, slack-free economy",
        "Below one when the economy is near capacity and demand leaks into imports."),
    "fiscal_multiplier_recession": (
        0.90, 1.80, "crowns of output per crown of spending, deep slump",
        "Larger when idle capacity and unemployed labour exist to be drawn in."),
    "financial_depth": (
        0.25, 0.70, "credit to the private sector relative to output",
        "A shallow financial system blunts interest-rate transmission."),
    "corruption_baseline": (
        0.20, 0.55, "share of procurement value lost at baseline",
        "Latent, not an event. Rises with opacity and discretion."),
    "food_storage_capacity": (
        0.8e6, 2.2e6, "food units held in private storage at capacity",
        "Buffer against a bad harvest. Small for a poor island."),
    "productivity_growth": (
        0.0008, 0.0035, "monthly growth of output per worker",
        "Slow-moving. Roughly one to four percent a year."),
    "price_rigidity": (
        0.25, 0.65, "share of a price shock not passed on within the month",
        "Menu costs and administered prices. Higher means stickier inflation."),
}

# Small worlds get parameters drawn near the middle of the band; wider markets allow more spread.
_DRAW_SPREAD = 0.42


def generate(seed: int) -> dict:
    """Draw one world's true structural parameters. Deterministic for a seed."""
    rng = rng_for(seed, 0, "structural-parameters")
    out = {}
    for name, (low, high, _unit, _why) in STRUCTURAL_PARAMETERS.items():
        mid = (low + high) / 2.0
        half = (high - low) / 2.0
        # Draw across the central band, then clamp: extreme corners are possible but rare, which
        # keeps most worlds governable without making every world the same.
        value = mid + half * _DRAW_SPREAD * (rng.random() * 2 - 1)
        out[name] = round(clamp(value, low, high), 6)
    return out


def ensure(w: World) -> dict:
    """The world's structural parameters, generated on first use and kept thereafter."""
    if not w.institutions.get("structural"):
        w.institutions["structural"] = generate(w.seed)
    return w.institutions["structural"]


def param(w: World, name: str) -> float:
    """One true parameter. **Never** call this from a prompt path or a briefing."""
    return ensure(w).get(name, (STRUCTURAL_PARAMETERS.get(name, (0.5, 0.5, "", ""))[0] +
                                STRUCTURAL_PARAMETERS.get(name, (0.5, 0.5, "", ""))[1]) / 2.0)


# ---------------------------------------------------------------------------------------------
# Lags
# ---------------------------------------------------------------------------------------------
# Every major policy effect is delivered over time rather than at once. The tuple is the month
# offsets at which the bulk of each channel lands: immediate, one-to-three, three-to-twelve.
CHANNEL_LAGS = {
    "rate": (0, 3, 12),
    "money": (0, 2, 6),
    "fx": (1, 3, 9),
    "fiscal": (0, 3, 9),
    "wage": (2, 6, 12),
    "supply": (0, 2, 5),
}

MAX_PENDING = 200


def schedule(w: World, channel: str, months_ahead: int, magnitude: float, *, source: str = "",
             note: str = "") -> dict:
    """Queue one lagged effect. `months_ahead` 0 means it lands this month."""
    pending = w.institutions.setdefault("pending_effects", [])
    entry = {"id": f"L{len(pending) + 1}-{w.month}", "channel": channel,
             "created_month": w.month, "due_month": w.month + max(0, int(months_ahead)),
             "magnitude": float(magnitude), "source": source, "note": note, "applied": False}
    pending.append(entry)
    if len(pending) > MAX_PENDING:
        del pending[:len(pending) - MAX_PENDING]
    return entry


def due(w: World) -> list:
    """Effects whose month has arrived, marked applied. Never returns the same effect twice."""
    out = []
    for entry in w.institutions.get("pending_effects", []):
        if not entry.get("applied") and entry.get("due_month", 0) <= w.month:
            entry["applied"] = True
            entry["applied_month"] = w.month
            out.append(entry)
    return out


def pending(w: World) -> list:
    return [e for e in w.institutions.get("pending_effects", []) if not e.get("applied")]


# How a change in spending reaches demand: half at once, then a third, then a fifth. The shape
# is the point — a programme announced this month is not fully felt this month, and the later
# instalments are what make the effect persist after the announcement is forgotten.
FISCAL_IMPULSE_SHARES = (0.50, 0.30, 0.20)
FISCAL_IMPULSE_FLOOR = 0.002       # ignore changes smaller than this share of output
FISCAL_IMPULSE_DECAY = 0.75        # how fast last month's demand support fades
FISCAL_IMPULSE_CAP = 0.06          # bounded: demand support is not an unbounded lever


def schedule_fiscal_impulse(w: World) -> dict | None:
    """Turn a material change in government spending into lagged demand support.

    Called once a month after the budget resolves. The impulse is the *change* in spending as a
    share of output, not its level: a government that has been spending heavily for years is not
    adding demand this month, and treating the level as stimulus would make every high-spending
    world permanently overheated.
    """
    e = w.econ
    gdp = max(1.0, e.gdp_nominal)
    previous = e.spending_prev
    e.spending_prev = e.spending
    if previous <= 0:
        return None
    change = (e.spending - previous) / gdp
    if abs(change) < FISCAL_IMPULSE_FLOOR:
        return None
    total = clamp(change, -0.10, 0.10)
    offsets = CHANNEL_LAGS["fiscal"]
    # The immediate instalment is applied here rather than queued. `apply_lags` has already run by
    # the time the budget resolves, so an effect scheduled with zero months to wait would sit in
    # the queue for a full month and the declared 0/3/9 profile would really be 1/4/10.
    immediate = total * FISCAL_IMPULSE_SHARES[0]
    e.fiscal_impulse = clamp(e.fiscal_impulse + immediate, -FISCAL_IMPULSE_CAP, FISCAL_IMPULSE_CAP)
    for share, offset in zip(FISCAL_IMPULSE_SHARES[1:], offsets[1:]):
        schedule(w, "fiscal", offset, total * share, source="spending change",
                 note=f"spending moved {change:+.2%} of output")
    return {"change": round(change, 6), "scheduled": list(offsets),
            "immediate": round(immediate, 6)}


def apply_lags(w: World) -> dict:
    """Release this month's matured effects. Returns what arrived, for the trace.

    Only the fiscal channel is wired to a consumer. Other channels are collected into
    `e.lagged_effects` rather than written over live fields: an earlier version assigned the money
    channel to `e.money_growth`, which `money_and_prices` overwrites later in the same month, so
    the effect vanished and the assignment read as though it worked.
    """
    arrived = due(w)
    fiscal = sum(e["magnitude"] for e in arrived if e["channel"] == "fiscal")
    e = w.econ
    e.fiscal_impulse = clamp(e.fiscal_impulse * FISCAL_IMPULSE_DECAY + fiscal,
                             -FISCAL_IMPULSE_CAP, FISCAL_IMPULSE_CAP)
    for entry in arrived:
        if entry["channel"] != "fiscal":
            e.lagged_effects[entry["channel"]] = (e.lagged_effects.get(entry["channel"], 0.0)
                                                  + entry["magnitude"])
    if arrived:
        trace(w, "lagged_effects", fiscal,
              {f"arrived_{e_['channel']}": e_["magnitude"] for e_ in arrived},
              note=f"{len(arrived)} scheduled effect(s) matured")
    return {"arrived": arrived, "fiscal": fiscal, "impulse": e.fiscal_impulse}


# ---------------------------------------------------------------------------------------------
# Regimes
# ---------------------------------------------------------------------------------------------
NORMAL = "NORMAL"
SLOWDOWN = "SLOWDOWN"
RECESSION = "RECESSION"
HIGH_INFLATION = "HIGH_INFLATION"
BALANCE_OF_PAYMENTS_STRESS = "BALANCE_OF_PAYMENTS_STRESS"
FISCAL_CRISIS = "FISCAL_CRISIS"
SUPPLY_CRISIS = "SUPPLY_CRISIS"
REGIMES = (NORMAL, SLOWDOWN, RECESSION, HIGH_INFLATION, BALANCE_OF_PAYMENTS_STRESS,
           FISCAL_CRISIS, SUPPLY_CRISIS)

HIGH_INFLATION_ANNUAL = 0.40
RECESSION_GAP = -0.04
SLOWDOWN_GAP = -0.01
RESERVE_MONTHS_CRITICAL = 1.0
DEFICIT_GDP_CRISIS = 0.12


def regime(w: World) -> str:
    """A descriptive label for the state the economy is in. Never an instruction.

    Order matters: a supply crisis is named ahead of the inflation it causes, because the
    difference between "prices are rising because money is abundant" and "prices are rising
    because there is no food" is the whole governance problem.
    """
    e = w.econ
    infl_a = annualize(e.infl)
    gap = getattr(e, "output_gap", 0.0)
    gdp_m = max(e.gdp_nominal, 1.0)
    deficit_ratio = e.deficit / gdp_m
    reserve_months = e.gold / max(1.0, 0.10 * gdp_m) if e.gold >= 0 else 0.0
    if e.food_ratio < 0.88 or e.energy < 0.70:
        return SUPPLY_CRISIS
    if infl_a >= HIGH_INFLATION_ANNUAL or infl_a <= -0.10:
        return HIGH_INFLATION
    if e.confidence < 0.35 and (e.arrears > 0.05 * gdp_m or deficit_ratio > DEFICIT_GDP_CRISIS):
        return FISCAL_CRISIS
    if reserve_months < RESERVE_MONTHS_CRITICAL or (e.import_scale < 0.75 and e.debt_for > 0):
        return BALANCE_OF_PAYMENTS_STRESS
    if gap <= RECESSION_GAP:
        return RECESSION
    if gap <= SLOWDOWN_GAP:
        return SLOWDOWN
    return NORMAL


# ---------------------------------------------------------------------------------------------
# Transmission: rate -> credit -> demand, and money -> prices
# ---------------------------------------------------------------------------------------------
# Each of these is a *stock* that moves toward a target rather than jumping to it. That is the
# whole content of a transmission channel: a central bank changes its rate today and the economy
# answers over the following months, because lending relationships, investment plans and price
# lists are not re-decided instantly.
#
# The speeds are calibrated so a rate change is most of the way through the system in roughly a
# quarter to two quarters, which is the common finding in the monetary transmission literature.
CREDIT_PERSISTENCE = 0.72        # share of last month's credit conditions carried forward
DEMAND_PERSISTENCE = 0.62        # how long a gap in demand keeps pressuring prices
MONEY_PERSISTENCE = 0.55         # how long excess money growth keeps pressuring prices
# Weight on persistent demand pressure in the price equation. Small: the output gap already enters
# through the money-market relation via output, so this is the *additional* pull from demand that
# has been sustained rather than a second full Phillips curve.
DEMAND_PRICE_WEIGHT = 0.055
MONEY_PRICE_WEIGHT = 0.035


def credit_step(w: World, target: float) -> float:
    """Move credit conditions toward their target. The lag is the point of the channel.

    A tighter policy rate does not withdraw credit in the month it is announced. Banks reprice
    existing facilities at rollover, borrowers delay projects, and only then does the quantity of
    credit actually fall. That delay is what the persistence term delivers.

    Note what `financial_depth` scales: the *sensitivity of the target to the rate*, not the level
    of credit. Scaling the level would mean every world with a deep financial system simply had
    more credit than one with a shallow system, which is not what depth means and would let
    utilisation rise above the ceiling the rest of the model assumes.
    """
    e = w.econ
    target = clamp(target, 0.35, 1.0)
    e.credit_target = target
    e.credit_conditions = clamp(
        CREDIT_PERSISTENCE * e.credit_conditions + (1 - CREDIT_PERSISTENCE) * target, 0.30, 1.0)
    return e.credit_conditions


def rate_target(w: World, real_rate: float) -> float:
    """What the real policy rate implies for credit availability, at this world's transmission
    strength. In a shallow financial system most activity is not intermediated, so the same rate
    change reaches less of it; a deeper system transmits more."""
    depth = 0.55 + 1.1 * param(w, "financial_depth")
    return clamp(1 - 0.35 * depth * max(0.0, real_rate - 0.04), 0.80, 1.0)


def demand_step(w: World, gap: float) -> float:
    """Sustained demand pressure. A one-month blip should not move prices much; a slump that
    persists should keep doing so. This is the persistent component the price equation reads."""
    e = w.econ
    e.demand_pressure = clamp(
        DEMAND_PERSISTENCE * e.demand_pressure + (1 - DEMAND_PERSISTENCE) * gap, -0.25, 0.25)
    return e.demand_pressure


def money_step(w: World, money_growth: float, output_growth: float) -> float:
    """Excess money growth: what is created beyond what the economy needs to transact at stable
    prices.

    The required growth rate is real output growth plus the inflation people already expect, because
    the demand for *nominal* balances rises with both. Money growth that merely matches those two
    is accommodating, not inflationary — which is why this is the requirement rather than a
    one-for-one mapping from money to prices.

        required = output_growth + expected_inflation
        excess   = money_growth - required

    Deliberately NOT included here: the Cagan effect by which higher expected inflation reduces the
    real balances people choose to hold. That effect already lives in the money-market velocity term
    in `economy.money_and_prices`, and adding it again would double-count the same behaviour.
    """
    e = w.econ
    required = output_growth + max(0.0, e.expected_infl)
    excess = money_growth - required
    e.excess_money_growth = clamp(excess, -0.20, 0.40)
    e.money_pressure = clamp(
        MONEY_PERSISTENCE * e.money_pressure + (1 - MONEY_PERSISTENCE) * e.excess_money_growth,
        -0.15, 0.30)
    return e.money_pressure


def depreciation(w: World) -> float:
    """How much the karam lost against the crown, as a positive number.

    `e.fx` is quoted in **crowns per karam**, so a FALLING rate is a depreciation. Getting this
    backwards is easy and expensive: it makes a currency collapse cheapen imports and turn
    deflationary, which is the opposite of what happens to a country that buys its fuel abroad.
    """
    if e_fx := w.econ.fx:
        return (w.econ.fx_prev / e_fx - 1.0) if w.econ.fx_prev > 0 else 0.0
    return 0.0


def import_price_step(w: World) -> float:
    """Inflation in the price of what Karamaniya buys abroad, in domestic currency.

    Two inputs: how the currency moved, and how world prices moved. Depreciation raises the local
    cost of imports even when world prices are flat, which is the channel by which a currency
    crisis becomes a cost-of-living crisis.
    """
    e = w.econ
    fx_change = depreciation(w)
    world = getattr(e, "world_price_infl", 0.0)
    e.import_price_infl = clamp(fx_change * 0.85 + world, -0.25, 0.40)
    return e.import_price_infl


def price_pressures(w: World) -> dict:
    """The persistent demand and money pressure terms that reach consumer prices."""
    e = w.econ
    return {"demand_pressure": DEMAND_PRICE_WEIGHT * e.demand_pressure,
            "money_pressure": MONEY_PRICE_WEIGHT * e.money_pressure}


# ---------------------------------------------------------------------------------------------
# Expectations
# ---------------------------------------------------------------------------------------------
# Weights on the three things people look at: a stated anchor, what has actually happened, and
# what the currency and the budget are doing. Normalised, so they always sum to one.
EXPECTATION_WEIGHTS = {"anchor": 0.25, "adaptive": 0.45, "currency": 0.15, "fiscal": 0.15}


def credit_anchor(w: World) -> float:
    """How much an anchor is believed, 0..1, from the record rather than from a claim.

    Credibility is earned the only way it can be: by inflation having been low, by the central
    bank not having monetised the deficit, and by there being money in the reserve account.
    """
    e = w.econ
    z = w.zone_of("karamaniya")
    low_inflation = clamp(1 - max(0.0, annualize(z.exp_infl)) / 0.25)
    no_monetisation = clamp(1 - e.printed / max(1.0, e.spending) * 3.0)
    reserves = clamp(e.gold / max(1.0, e.gold0 * 0.5))
    return clamp(0.45 * low_inflation + 0.35 * no_monetisation + 0.20 * reserves)


def expected_inflation(w: World) -> float:
    """A hybrid expectation: partly anchored, partly adaptive, partly currency- and budget-driven."""
    z = w.zone_of("karamaniya")
    e = w.econ
    weights = EXPECTATION_WEIGHTS
    anchor = 0.003 if e.currency == "crown" else 0.002
    credibility = credit_anchor(w)
    # The weaker the anchor, the more weight falls on lived experience.
    anchor_weight = weights["anchor"] * credibility
    adaptive_weight = weights["adaptive"] + weights["anchor"] * (1 - credibility)
    currency_weight = weights["currency"]
    fiscal_weight = weights["fiscal"]
    total = anchor_weight + adaptive_weight + currency_weight + fiscal_weight
    currency = max(0.0, (e.fx_conf - 1.0)) * -0.02 if e.currency == "karam" else 0.0
    fiscal = clamp(e.printed / max(1.0, e.gdp_nominal) * 0.9, 0.0, 0.05)
    value = (anchor_weight * anchor + adaptive_weight * z.infl
             + currency_weight * currency + fiscal_weight * fiscal) / total
    return clamp(value, -0.02, 1.5)


# ---------------------------------------------------------------------------------------------
# Demand, output gap and the multiplier
# ---------------------------------------------------------------------------------------------
def fiscal_multiplier(w: World) -> float:
    """State-dependent. Large in slack, small when the economy is already at capacity.

    This is the relationship that makes austerity and stimulus conditional rather than good or
    bad in themselves: the same crown of spending does different work depending on how much
    idle capacity and unemployed labour is available to absorb it.
    """
    gap = clamp(getattr(w.econ, "output_gap", 0.0), -0.15, 0.10)
    normal = param(w, "fiscal_multiplier_normal")
    recession = param(w, "fiscal_multiplier_recession")
    # At a zero gap the multiplier sits near `normal`; as the gap goes negative it rises toward
    # the recession value, and as the economy overheats it falls away below one.
    slack = clamp(-gap / 0.08, 0.0, 1.0)
    base = normal + (recession - normal) * slack
    if gap > 0:
        base -= 0.6 * clamp(gap / 0.04, 0.0, 1.0)
    return round(max(0.15, base), 4)


NATURAL_UNEMPLOYMENT = 0.055


def okun_step(w: World, previous_gap: float = 0.0, current_gap: float = 0.0,
              labour_supply_shock: float = 0.0) -> float:
    """Unemployment follows an Okun level relation, reached only gradually.

        u_implied = u_natural - beta * gap          (the level relation)
        u_t       = rho * u_(t-1) + (1 - rho) * u_implied + shock

    The brief's literal form (`u_t = u_(t-1) - beta * change_in_gap`) is a growth-rate relation
    with no level anchor: a country stuck at a permanently depressed output gap would drift to
    *low* unemployment, because the gap stopped changing. Anchoring the target to the level of the
    gap keeps Okun's content while making the steady state sensible. `previous_gap` is accepted so
    callers can pass the gap history the growth-rate form would use, and is retained in the trace.

    Okun's coefficient is country-specific and scaled by labour-market flexibility: a rigid market
    sheds fewer jobs for a given fall in output, but the unemployment that appears lasts longer.
    """
    flex = param(w, "labor_market_flexibility")
    beta_okun = 0.20 + 0.40 * flex
    persistence = 0.72 + 0.22 * (1.0 - flex)
    u_implied = NATURAL_UNEMPLOYMENT - beta_okun * current_gap
    # A gap that is widening hits harder than one that is merely wide, which is what the
    # growth-rate form was reaching for; it is folded in here as a bounded extra term.
    widening = clamp((previous_gap - current_gap) * 0.5, -0.05, 0.05)
    u_implied = clamp(u_implied + widening, 0.010, 0.55)
    new = persistence * w.econ.unemployment + (1 - persistence) * u_implied + labour_supply_shock
    return clamp(new, 0.005, 0.60)


# ---------------------------------------------------------------------------------------------
# Exchange rate
# ---------------------------------------------------------------------------------------------
def depreciation_pressure(w: World) -> dict:
    """Why the karam would move, before anything decides whether it does.

    Every term is observable in principle. The engine keeps them separate so a report can say
    *why* the currency moved rather than asserting that it did.
    """
    e = w.econ
    z = w.zone_of("karamaniya")
    infl_diff = z.infl - 0.003
    fiscal_risk = clamp(e.deficit / max(1.0, e.gdp_nominal) - 0.03, -0.05, 0.25)
    reserve_ratio = clamp(e.gold / max(1.0, e.gold0), 0.0, 2.0)
    reserve_pressure = clamp(0.5 - reserve_ratio * 0.5, -0.15, 0.35)
    political_risk = clamp(w.avg("unrest") - 0.10, 0.0, 0.5) * 0.4
    expected_money = clamp(e.printed / max(1.0, e.gdp_nominal), 0.0, 0.30)
    rate_support = w.policy.rate / 12.0 * 0.5 * param(w, "financial_depth")
    credit_support = clamp(e.loans_in / max(1.0, e.gdp_nominal) * 2.0, 0.0, 0.15)
    export_strength = clamp((w.econ.import_scale - 0.8) * 0.2, -0.05, 0.10)
    terms = {"inflation_differential": infl_diff, "fiscal_risk": fiscal_risk,
             "reserve_pressure": reserve_pressure, "political_risk": political_risk,
             "expected_money_creation": expected_money,
             "interest_rate_support": -rate_support, "foreign_credit_support": -credit_support,
             "export_strength": -export_strength}
    return {"terms": {k: round(v, 5) for k, v in terms.items()}, "total": round(sum(terms.values()), 5)}


def fx_step(w: World) -> float:
    """Move the currency by the pressure it is under, bounded, plus seeded market noise.

    Intervention can hold the rate for a month, but it spends reserves to do it, so it is not a
    free option and it does not guarantee success.
    """
    e = w.econ
    if e.currency != "karam":
        return 0.0
    pressure = depreciation_pressure(w)
    depth = param(w, "financial_depth")
    rng = rng_for(w.seed, w.month, "fx-market")
    noise = (rng.random() - 0.5) * 0.012
    response = 0.55 / max(0.25, depth)
    change = clamp(pressure["total"] * response + noise, -0.10, 0.18)
    e.fx_pressure = pressure["total"]
    e.fx = clamp(e.fx * (1.0 + change), 0.05, 20.0)
    return change


def pass_through(w: World) -> float:
    """The true share of a depreciation that reaches consumer prices this month."""
    base = param(w, "exchange_rate_pass_through")
    # Price controls and long contracts slow it; a competitive import-heavy market speeds it up.
    if w.policy.price_controls == "all":
        base *= 0.4
    elif w.policy.price_controls == "food":
        base *= 0.7
    base *= 0.6 + 0.8 * param(w, "import_dependency")
    return clamp(base, 0.02, 0.7)


# ---------------------------------------------------------------------------------------------
# The causal trace
# ---------------------------------------------------------------------------------------------
# What moved this month, and by how much. Kept for debugging and research, never shown to agents:
# a delegate that could read the decomposition would be reading the answer key.
TRACE_CAP = 60


def trace(w: World, variable: str, total: float, contributions: dict, *, note: str = "") -> dict:
    """Record why one variable changed, as named contributing terms."""
    entries = w.institutions.setdefault("causal_trace", [])
    clean = {k: round(float(v), 6) for k, v in contributions.items() if abs(float(v)) > 1e-9}
    entry = {"month": w.month, "variable": variable, "total": round(float(total), 6),
             "contributions": clean, "note": note}
    entries.append(entry)
    if len(entries) > TRACE_CAP:
        del entries[:len(entries) - TRACE_CAP]
    return entry


def trace_for(w: World, variable: str, month: int | None = None) -> dict | None:
    entries = w.institutions.get("causal_trace", [])
    for entry in reversed(entries):
        if entry["variable"] == variable and (month is None or entry["month"] == month):
            return entry
    return None


def explain(w: World, variable: str, month: int | None = None) -> str:
    """A human answer to "why did this change?", for the calibration view."""
    entry = trace_for(w, variable, month)
    if entry is None:
        return f"no recorded causal trace for {variable}"
    parts = [f"{name} {value:+.4f}" for name, value in
             sorted(entry["contributions"].items(), key=lambda kv: -abs(kv[1]))]
    return (f"{variable} moved {entry['total']:+.4f} in month {entry['month'] + 1}"
            + (f" ({entry['note']})" if entry["note"] else "")
            + (": " + ", ".join(parts) if parts else " with no recorded contributor"))


# ---------------------------------------------------------------------------------------------
# Calibration view
# ---------------------------------------------------------------------------------------------
def calibration_view(w: World) -> dict:
    """Everything a researcher may see and an agent may not."""
    e = w.econ
    return {
        "structural_parameters": ensure(w),
        "regime": regime(w),
        "output_gap": round(getattr(e, "output_gap", 0.0), 5),
        "potential_output": round(getattr(e, "potential_output", 0.0), 1),
        "fiscal_multiplier": fiscal_multiplier(w),
        "pass_through": round(pass_through(w), 4),
        "credit_anchor": round(credit_anchor(w), 4),
        "expected_inflation_annual": round(annualize(expected_inflation(w)), 5),
        "depreciation_pressure": depreciation_pressure(w),
        "pending_effects": pending(w),
        "trace": list(w.institutions.get("causal_trace", [])),
    }
