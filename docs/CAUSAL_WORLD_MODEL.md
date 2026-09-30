# The Causal World Model

How Karamaniya's economy decides what happens, and why each relationship is shaped the way it is.

The goal is not to reproduce a real economy. It is a small number of consistent causal
relationships, accounting identities, state-dependent effects, lags and uncertainty — enough that
an intelligent agent can *govern* the country rather than move abstract sliders, and enough that
a reader can tell why something happened.

## Three kinds of rule, kept apart

The brief requires these never be blended into one score function, and they are not:

| Kind | Property | Where |
|---|---|---|
| **Accounting identities** | Exact. Reserves cannot appear from nowhere. | `economy.py` — `fiscal()`, `trade_and_food()` |
| **Empirical relationships** | Estimated, uncertain, parameterised per world. | `causality.py` |
| **Behavioural responses** | Stochastic and state-dependent. | `society.py`, `dilemmas.py`, `foreign.py` |

A test that checks an identity is checking arithmetic. A test that checks an empirical
relationship is checking a *direction* and a *bound*, not a coefficient.

## Time and units

The timestep is **one month**. Nothing mixes monthly and annual rates silently.

- `infl` is monthly. `annualize(x) = (1+x)^12 - 1`, never `x*12`.
- Output is in **base-price crowns**, monthly. `gdp_real * 12` is the annual figure.
- `gold` is foreign-currency reserves in gold (start-price crowns).
- Food is in **food units**: one person's food for one month.
- Wages and prices are indices, 1.0 at the founding.

## The flow of a month

```
dilemmas/audits/operations/standing   (v2 subsystems)
director.act                          foreign cabinets decide
rivals.monthly
economy.produce        -> output, potential output, output gap
economy.trade_and_food -> imports, food, reserves, capital flight
economy.fiscal         -> revenue, spending, deficit, borrowing, arrears
economy.money_and_prices -> prices, expectations, real wages, the causal trace
military.update / society.update / politics.monthly_checks
snapshot
```

---

## 1. Output and the output gap

**Identity.** Actual output is the production function, evaluated with the frictions the economy
is actually under:

```
gdp_real = Σ_regions [ farmers·land·K_FOOD·weather·farm_incentive·(1-damage)
                     + workers·0.94·industry·K_IND·util_ind
                     + middle·0.95·services·K_SERV·util_serv ] · productivity · logistics
```

**Potential output** is the same function with nothing in the way — normal weather, no strikes, no
war damage, intact logistics, full energy, no credit or confidence constraint:

```
potential_raw = Σ_regions [ farmers·land·K_FOOD + workers·0.94·industry·K_IND + middle·0.95·services·K_SERV ]
potential     = potential_raw · productivity
```

The gap is what is left over:

```
output_gap = gdp_real / potential - 1
```

**Productivity is applied to both.** This matters, and getting it wrong was a real bug: if
potential grows at the productivity rate while actual output does not, the gap drifts permanently
negative for no economic reason and every downstream signal inherits the error.

**Potential is a slow stock.** It grows at the world's structural productivity rate, less permanent
war and unrest damage, and does not jump because one harvest was bad.

| Parameter | Range (monthly) | Rationale |
|---|---|---|
| `productivity_growth` | 0.0008 – 0.0035 | Roughly 1–4% a year. Slow-moving by construction. |

**Limitation.** Output here is supply-determined. There is no demand-determined
`output = min(supply, demand)` closure, so fiscal policy moves output through utilisation
channels rather than through an explicit Keynesian demand block. This is a deliberate choice under
the brief's "avoid overcomplexity" rule, and it is the single largest structural simplification in
the model.

## 2. Unemployment — Okun's law

```
u_implied = u_natural - β_okun · output_gap        (u_natural = 5.5%)
u_t       = ρ · u_(t-1) + (1 - ρ) · u_implied + shock
β_okun    = 0.20 + 0.40 · labour_market_flexibility
ρ         = 0.72 + 0.22 · (1 - labour_market_flexibility)
```

**Why not the brief's literal form.** The brief gives `u_t = u_(t-1) - β·Δgap`. That is the
growth-rate form of Okun's law, and it has no level anchor: a country stuck at a permanently
depressed output gap would drift toward *low* unemployment, because the gap stopped changing. The
level relation is used as the target instead, reached only gradually. A bounded `widening` term
keeps the content of the growth-rate form for a gap that is actively deteriorating.

**Empirical grounding.** Ball, Leigh and Loungani (2017) estimate the gap form across 21 advanced
OECD countries and report β from **−0.14 (Austria) to −0.85 (Spain)**. Cross-country studies put
the range at roughly **−0.07 to −1.1**, with structural (VAR) estimates systematically smaller
than reduced-form ones (~−0.1 vs ~−0.3 in the euro area). The model's β of 0.20–0.60 sits inside
that range, toward the smaller end, which suits a small economy with a large informal sector.

**Coefficient instability is real and is not modelled away.** The literature finds β varies across
countries, time, demographic groups and cycle phase, and is often larger in downturns (Knotek
2007). Here it varies only across worlds (via `labor_market_flexibility`), not over time.

## 3. Inflation

Inflation is **not** modelled as one thing. Each channel is separate and the decomposition is
recorded every month:

| Term | Meaning | Lag |
|---|---|---|
| `zone_price_level` | the money-market price level of the currency area | same month |
| `food_relative_price` | food prices relative to the general level | same month, moving average |
| `goods_relative_price` | consumer goods relative to supply | same month, moving average |
| `exchange_rate_passthrough` | depreciation reaching prices | **lagged, 1+ months** |
| `expectations` | the gap between credibility-anchored and adaptive expectations | same month |
| `excess_wage_growth` | wage growth in excess of inflation | same month |
| `demand_pressure` | the output gap | same month |
| `import_shortage` | how much of wanted imports could be paid for | same month |

The money channel itself remains the Cagan-style money-market relation the engine was built on:
velocity rises with expected inflation, so expected inflation speeds up spending and feeds more
inflation. That gives genuine persistence, and it means one month of tight policy cannot end an
inflation — which is the property the brief requires and which a naive `printing → inflation`
rule would fail.

**Expectations are hybrid and credibility-weighted:**

```
expected = [ w_anchor·credibility·anchor + (w_adaptive + w_anchor·(1-credibility))·last_inflation
           + w_currency·currency_signal + w_fiscal·money_financed_deficit ] / Σw
credibility = 0.45·(inflation has been low) + 0.35·(deficit not monetised) + 0.20·(reserves held)
```

Credibility is earned from the record, never asserted. Repeated money financing erodes it; that
erosion is what produces path dependence.

## 4. Exchange rate and pass-through

**Pressure is decomposed before anything acts on it:**

```
pressure = inflation_differential + fiscal_risk + reserve_pressure + political_risk
         + expected_money_creation - interest_rate_support - foreign_credit_support - export_strength
```

**Pass-through is a structural property, not a constant:**

```
pass_through = exchange_rate_pass_through · (0.6 + 0.8·import_dependency)
                · (0.4 under full price controls, 0.7 under food controls)
arriving_this_month = fx_change · pass_through · (1 - price_rigidity)
```

**Empirical grounding.** Consumer-price pass-through in emerging and small open economies is wide:
one central-bank study reports 12-month estimates of 0.02 (Czechia), 0.03 (Thailand), 0.22 (Peru),
0.38 (Colombia) and 0.58 (Mexico); a large emerging-market sample averages about 27% for a 10%
move. The model's realised range (roughly 0.11–0.48 depending on import dependence) sits inside
that. The literature also finds pass-through is nonlinear — larger moves pass through more — and
falls with lower inflation and better-anchored expectations; the first is partly captured by the
`price_rigidity` term, the second by the credibility anchor.

**Wiring.** The rate is the zone price relation (which carries the inflation differential) times a
confidence term. Reserves, scandal and war already moved that confidence; the pressure terms that
were previously absent — an unsustainable deficit, expected money creation, the interest rate paid
to hold the currency, and credit arriving from abroad — are now folded in, bounded and smoothed so
a single month's news moves the rate rather than repricing it:

```
target  = clamp(base_confidence - 1.5 · extra_pressure, 0.3, 1.1)
fx_conf = clamp(0.65 · fx_conf + 0.35 · target, 0.3, 1.1)
fx      = crown_price / karam_price · fx_conf
```

Verified live: a world with 6% monthly printing, a large welfare expansion and reserves run down
to 5M sees the karam fall to about a quarter of its value over nine months, while a calm world
holds above par. The currency-launch continuity guarantee still holds — the launch month moves the
CPI by under 0.1%, against a 5% bound.

**Limitation.** Pass-through is applied to the *change* in the rate, so a permanently weak currency
does not keep feeding inflation — only its movement does. That is correct for a flow-to-price
channel but means the model does not capture the sustained higher import costs of a permanently
depreciated currency.

## 5. Fiscal policy

**Identity.** Spending is financed by revenue, borrowing, arrears, money creation, reserve
conversion or foreign transfers — never by nothing:

```
deficit   = spending - revenue
need      = deficit - printed - foreign_loans_local
borrowed  = min(need, 0.02·gdp·confidence - arrears_bonds)      if need > 0
arrears  += need - borrowed
paid_share = 1 - unpaid / base
```

**State-dependent multiplier:**

```
multiplier = normal + (recession - normal) · slack - 0.6·(overheating term)
slack      = clamp(-output_gap / 0.08, 0, 1)
```

**Empirical grounding.** Auerbach and Gorodnichenko estimate **0–0.5 in expansions and 1–1.5 in
recessions**; subsequent work finds multipliers rise further when monetary policy is constrained,
and that distortionary tax financing magnifies the state-dependence. The model's bands
(`fiscal_multiplier_normal` 0.50–1.10, `fiscal_multiplier_recession` 0.90–1.80) bracket those
ranges. **This is the relationship that makes the same policy good or bad depending on the state
of the world rather than on the author's politics**, which is the brief's central requirement.

**The multiplier is live.** A material change in spending is scheduled across the fiscal lag
profile (half now, a third at three months, a fifth at nine) and the arriving instalments are
scaled by the multiplier into `fiscal_impulse`, which moves utilisation:

```
demand_support = clamp(1 + 0.8 · fiscal_impulse · multiplier, 0.85, 1.15)
```

Crucially the impulse is the **change** in spending as a share of output, not its level. A
government that has spent heavily for years is not adding demand this month; treating the level
as stimulus would leave every high-spending world permanently overheated. Verified live: the same
+0.03 impulse produces +3.3% demand support in deep slack and +0.6% when the economy is already
overheating.

**Limitation.** Demand support multiplies utilisation rather than entering a demand block, so it
cannot make the economy produce beyond its supply capacity — that is the intended bound, but it
also means a stimulus cannot be modelled as pulling idle *capital* into use, only idle labour.

## 6. Structural parameters

Drawn once per world from calibrated bands, then fixed:

| Parameter | Range | What it governs |
|---|---|---|
| `import_dependency` | 0.18 – 0.34 | pass-through; exposure to external shocks |
| `labor_market_flexibility` | 0.25 – 0.75 | Okun slope; unemployment persistence |
| `tax_compliance` | 0.62 – 0.90 | revenue at a given statutory rate |
| `bureaucratic_efficiency` | 0.45 – 0.85 | how much of a voted programme is delivered |
| `inflation_persistence` | 0.35 – 0.75 | how much past inflation carries forward |
| `exchange_rate_pass_through` | 0.15 – 0.55 | depreciation reaching consumer prices |
| `fiscal_multiplier_normal` | 0.50 – 1.10 | spending effectiveness at capacity |
| `fiscal_multiplier_recession` | 0.90 – 1.80 | spending effectiveness in slack |
| `financial_depth` | 0.25 – 0.70 | interest-rate transmission; FX response |
| `corruption_baseline` | 0.20 – 0.55 | procurement leakage |
| `food_storage_capacity` | 0.8M – 2.2M units | buffer against a bad harvest |
| `productivity_growth` | 0.0008 – 0.0035 | trend growth of potential output |
| `price_rigidity` | 0.25 – 0.65 | how much of a shock is not passed on at once |

**These are modelling assumptions calibrated to plausible published ranges for a small island
economy, not estimates of any real country.** Karamaniya is fictional; no source is being
presented as a measurement of it. What the ranges buy is that the same policy is not optimal in
every world — which is what makes the engine useful as a benchmark rather than as a puzzle with
one solution.

**True values are hidden from agents.** Only `calibration_view()` exposes them, and tests assert
they never reach a briefing or a prompt.

## 7. Lags

Every channel declares when its effect lands (months): `rate` (0, 3, 12), `money` (0, 2, 6),
`fx` (1, 3, 9), `fiscal` (0, 3, 9), `wage` (2, 6, 12), `supply` (0, 2, 5).

`schedule()` queues an effect and `due()` releases it exactly once; `engine.step` calls
`apply_lags()` before the month is produced, so a policy change announced months ago lands in the
month it was always going to land in. An effect can never fire twice, and tests assert both the
timing and the once-only property.

**Currently wired:** the `fiscal` channel (see §5). The `money`, `rate`, `fx`, `wage` and
`supply` profiles are declared and the registry is general, but those channels currently reach
prices through the existing partial-adjustment in `money_and_prices` rather than through explicit
scheduled instalments. The registry is not dead code, but it is only exercised by one channel.

## 8. Regimes

`NORMAL`, `SLOWDOWN`, `RECESSION`, `HIGH_INFLATION`, `BALANCE_OF_PAYMENTS_STRESS`,
`FISCAL_CRISIS`, `SUPPLY_CRISIS`.

Computed from state, descriptive only. **No regime is attached to a scripted policy response** —
that would be the engine playing the game rather than the agents doing so. Ordering matters: a
supply crisis is named ahead of the inflation it causes, because "prices are rising because money
is abundant" and "prices are rising because there is no food" are different governance problems.

## 9. The causal trace

Every month records why inflation moved, with named contributions, and `explain()` renders it:

```
Inflation this month: +1.8%
  +0.0060 exchange_rate_passthrough
  +0.0042 food_relative_price
  +0.0031 expectations
  ...
```

This is the artefact that lets a reader distinguish **model failure** from **world dynamics** from
**engine bug**. It is for research only and never reaches an agent; a delegate who could read the
decomposition would be reading the answer key.

---

## Stability

Long deterministic runs are checked for NaN, exploding variables, negative impossible quantities,
runaway oscillation and implausible sensitivity (`tests/test_causal_economy.py`). The
qualitative properties the brief specifies are each a test:

- a money-financed expansion in a capacity-constrained high-inflation economy creates more
  inflationary pressure than the same expansion in a deep recession;
- the same spending does different work in slack and at capacity;
- a rate rise does not abolish inflation in one month;
- depreciation matters more where import dependence is higher;
- a national food surplus does not guarantee every region is fed;
- high nominal wage growth is not rising real wages;
- an audit does not create money;
- passing a motion does not create physical goods.

## Known limitations

*This list describes the model after the first hardening shift. The second shift's additions,
below, resolve items 2, 7 and part of 1, and the superseded entries are marked.*

1. **Output is supply-determined.** Demand support moves utilisation, not capacity, so there is no
   explicit demand block and no `output = min(supply, demand)` closure. The multiplier is live
   through utilisation (§5), which is why this is a simplification rather than a gap — but it is
   still the largest one.
2. *(partly resolved — depreciation pressure now drives the rate; the helper below remains unused)*
   **`fx_step()` is still not called by the engine.** The depreciation *pressure* now drives
   `e.fx_conf` and therefore the rate (§4), but the separate `fx_step()` helper — which would move
   the rate by the raw pressure with market noise — remains unused. It is tested but not wired;
   the smoother path through confidence was used instead because it preserves the tested
   currency-launch continuity guarantee.
3. **Regime states do not modulate coefficients.** `inflation_persistence` and the multipliers are
   drawn per world, not per regime, so the model does not yet become more nonlinear in a crisis.
4. **Corruption and bureaucratic capacity** are tracked and feed implementation, but their
   economic channels (procurement cost inflation, quality loss) are thin.
5. **Regional logistics recover on dilemma resolution in a single month** rather than ramping,
   which produces a visible step in output.
6. **No sectoral input-output structure.** Agriculture, industry and services exist but do not
   purchase from one another.
7. *(resolved — see section 16)* **Agent forecasts.** The structured-claim machinery exists
   in spirit but the prompt surface was not changed.

---

# Second shift additions

Everything above describes the model as it stood after the first hardening shift. The sections
below are what the realism shift added, and they supersede the corresponding limitations listed at
the end of that part.

## 10. Transmission: rate → credit → demand, and money → prices

Each channel is a **stock that lags its target**. That lag is the entire content of a transmission
channel: a central bank changes a rate today and the economy answers over following months, because
lending relationships, investment plans and price lists are not re-decided instantly.

```
target_credit   = 1 - 0.35 · depth · max(0, real_rate - 0.04)      depth = 0.55 + 1.1·financial_depth
credit_conditions ← 0.72 · credit_conditions + 0.28 · target_credit
demand_pressure   ← 0.62 · demand_pressure   + 0.38 · output_gap
required_money    = output_growth + expected_inflation
money_pressure    ← 0.55 · money_pressure    + 0.45 · (money_growth - required_money)
```

**Verified behaviour.** After a hike from 6% to 25%, the target moves at once (1.000 → 0.939) while
actual credit takes about nine months to converge (1.000 → 0.942). Calibrated so a rate change is
mostly through the system in one to two quarters, which is the common finding in the monetary
transmission literature.

**Two mistakes corrected here, both worth recording.**

`financial_depth` originally scaled the *level* of credit rather than the strength of transmission.
Every deep-financial-system world simply had more credit, credit could exceed the ceiling the rest
of the model assumes, and a drought produced a **positive** output gap. Depth now scales the
target's sensitivity to the rate.

Excess money growth originally double-subtracted output growth, so money growth of exactly expected
inflation read as strongly deflationary. The Cagan real-balance effect is deliberately **not**
modelled here because it already lives in the money-market velocity term; including it in both
places would double-count one behaviour.

## 11. Money is measured against capacity, not output

This is the most consequential correction of the shift.

```
target_price = scale · money · velocity / capacity          [was: / actual output]
```

Dividing by *actual* output made the quantity relation supply-driven: a demand recession lowered
the denominator and mechanically raised prices. The supply channel swamped the demand channel, and
the consequence was that **a rate rise was stagflationary** — tightening under inflation *raised*
expected inflation, which is the opposite of the brief's required chain.

`capacity` is potential output where it has been established (see section 1), so money chases what
the economy can produce rather than what it happened to produce this month. Demand reaches prices
through velocity, the demand-pressure term and the output gap.

As a side effect the calm baseline tightened: year-on-year inflation fell from a −1.0%/+3.9% band
to −1.2%/+2.2%.

## 12. Expectations now see the policy rate

Credibility had been built only from realised inflation, monetisation and reserves, which meant a
central bank could triple its rate under 20% inflation and expected inflation would not move.

```
resolve  = clamp(0.5 + (policy_rate - 0.06) / 0.20, 0, 1)
credibility = 0.38·low_inflation + 0.30·no_monetisation + 0.17·reserves + 0.15·resolve
```

Centred on the neutral rate, so an ordinary world is unchanged and only a genuine tightening or a
real capitulation moves the anchor. **Modelling assumption**, not an estimated relationship: the
weight is chosen so that resolve is a tie-breaker rather than the dominant term.

## 13. Fiscal structure: who the government owes

An aggregate arrears figure cannot express the thing that matters. The historical record is
specific, and the consequences are differentiated accordingly.

```
bills = { army:          military · 0.35 · gdp        (the pay portion; see below)
          police:        police · gdp
          civil_service: (health_edu + welfare + admin) · gdp
          contractors:   military · 0.65 + farm_support + regional · gdp
          foreign_debt:  interest_for }

shortfall_i = unpaid · (1 - protection_i) · bill_i / Σ (1 - protection_j) · bill_j
protection  = army 0.85, police 0.80, foreign_debt 0.70, civil_service 0.35, contractors 0.15
```

**Why these weights, and why not an order of payment.** The record: military pay arrears
immediately preceded coups in Cote d'Ivoire (1999, over unpaid peacekeeping bonuses, about 230
soldiers), the Gambia (1994, roughly three months unpaid), Guinea-Bissau (2004, 600 troops over
unpaid UN mission payments) and Sierra Leone (1992, explicitly over unpaid salaries); civil servants
turn to strikes after roughly **two to three months** (Gimpelson and Treisman on Russian arrears as
fiscal bargaining, where public employees were described as a reserve of hostages); and contractors
who are owed money bid higher or stop bidding (the 2012 Spanish accelerated-payment episode: firms
holding unpaid public bills were about 22% less likely to take new public work).

A **lexicographic** order — soldiers always first — was tried first and deleted the mechanism, since
the army could then never go unpaid no matter how broke the state was. Protection is therefore
**relative**: the army absorbs a shortfall last and least, but a large enough one still reaches it,
which is what happened in every case above.

The army's bill is its **pay**, not the whole military line, because `military.update` genuinely
pays soldiers before anything is bought. Treating the whole line as the army's bill made the
composition claim the army was five months behind while the military module correctly reported it
paid in full; the unpaid part was owed to the firms supplying the army.

**Consequences, in order of how well grounded they are:** contractor arrears raise a procurement
premium (grounded, capped at +35%, because eventually suppliers stop bidding); civil-service arrears
beyond 2.5 months damage administrative capacity (grounded in direction, threshold from the
qualitative pattern); army arrears drive morale, loyalty and desertion through the existing
`Force.arrears`.

**Rollover.** The market absorbs a certain amount of **gross** issuance each month and maturing debt
is served from it first:

```
borrowed      = min(need, max(0, 0.10 · gdp_nom · confidence - rollover_need - arrears_bonds))
rollover_need = debt_short_share · debt_dom / 12
```

Gross capacity is calibrated so that at the founding — 40% of annual output in debt, 20% of it
inside a year — gross minus rollover reproduces the 2% of monthly output the model used before the
rollover channel existed. Modelling it as *net* capacity minus rollover made the figure negative and
the default government borrowed nothing.

**Reserve adequacy** is reported in months of imports (`e.reserve_months`). The conventional floor is
three months, though the IMF notes the rule has no firm theoretical basis.

**Note on an existing mechanism, verified not rebuilt:** spending reserves on a *domestic* obligation
already required an explicit conversion — `settle_arrears` with funding source `reserves` converts
at the exchange rate. That satisfies the brief's requirement, and it was verified rather than
reimplemented.

## 14. Food: losses and regional access

**Post-harvest losses.** Nothing was previously lost between harvest and plate.

```
loss = 0.075 + 0.10 · (1 - mean_logistics)        bounded to [0.02, 0.30]
```

**Empirical grounding.** APHLIS and World Bank work puts cereal losses from harvest to market at
roughly **10-20%** in weak-infrastructure economies, concentrated in field drying, farm storage and
market storage (farm storage 2-5%, transport to market 1-2%, market storage 2-4%) rather than in
bulk transport. The widely quoted 30-40% figures are **not supported for cereals** and are
deliberately not used. The baseline is a **synthetic** assumption placed at the low end of the
supported range, with the transport component scaling to the top of it.

**Regional distribution.** National supply moves out to regions subject to each one's delivery
ceiling, which falls as logistics degrade:

```
delivery_ceiling(region) = need · (0.55 + 0.45 · logistics)
```

This encodes the arbitrage-band result from the spatial market-integration literature — goods move
only when the gap justifies the cost (Baulch et al. on Vietnamese rice markets; Bangladesh 1974,
where inter-district movement restrictions depressed prices in surplus districts and raised them in
deficit districts). Whatever a constrained region cannot absorb is re-offered to regions with
headroom, so one broken corridor does not strand the surplus.

**Demonstrated.** With Kessel Valley's rail at logistics 0.33 and a national food ratio of 0.98,
every other region has **zero** hunger and Kessel has 27%. Under a genuine national surplus (ratio
1.07) Kessel still has 28%. The engine names the regions the roads did not reach
(`econ.food_short_regions`) rather than leaving it implicit in the hunger numbers.

The brief's requirement — that a national surplus must not imply uniform regional access — is
tested directly.

**Calibration note.** The production constants were set before losses existed, so adding them moved
the founding food balance from about 1.02 to 0.99 and introduced chronic hunger in an ordinary year.
`K_FOOD` now carries the loss adjustment, so the documented starting condition still holds and the
loss mechanism bites where it should: when logistics fail.

## 15. Foreign actors: red lines and leadership

Foreign actors already had dispositions, beliefs with confidence, directional relations, military
and economic state, strategic goals and memory. Added:

- **Red lines**: three per actor, each a condition the engine can genuinely evaluate — League
  alignment, League escorts, a bilateral trade split, blockade of the shipping lanes, Karamaniyan
  aggression, default on League debt. No condition was invented that no world state backs. Crossing
  one moves hostility, threat perception and the offensive-intent belief by severity times a
  disposition-chosen response.
- **Leadership confidence**, falling under domestic stress and visibly failed strategy.
- **Constituency preferences**, generating political pressure when a group's preference is ignored.

**Do not script hostility, verified:** crossing a red line moves Veleria's hostility 0.46 to 0.61
and its threat perception, and does **not** trigger war, attack, blockade or ultimatum. A test
asserts this.

## 16. Forecasts

Delegates may make checkable predictions — metric, direction, threshold, horizon, confidence — and
the engine scores them months later against a state their author could not see.

**Scoring, and the conventions that matter:**

```
Brier (binomial, 0-1)   BS = mean((confidence - outcome)^2)
Murphy decomposition    BS = REL - RES + UNC          (reconciles exactly)
No-skill baseline       max(event_rate, 1 - event_rate)
```

The **Brier scale is stated on every score**, because two conventions circulate differing by a
factor of two and the Good Judgment Project's widely quoted 0.25/0.37 figures are on the 0-2 scale
while being routinely misreported as if they were 0-1. On the 0-1 scale those are 0.125/0.185, and
always answering 50% scores 0.25.

Directional accuracy is reported beside a no-skill baseline that is **not 50%** — it is the
frequency of always predicting whichever direction turned out to be more common, which is the
Pesaran-Timmermann point.

A delegate sees its own record, because a forecaster told it is overconfident can correct. It does
not see anyone else's, and a test asserts the boundary.

**Bug found while building it:** `correct` was defined as "the event happened" rather than "the
forecast was right", so a forecast of "probably not" that did not occur scored as a miss.

## 17. Corrections found by adversarial review

An independent reviewer, instructed to prove every finding with a reproduction, ran against this
shift's own commits and found four HIGH-severity defects in code that had been written, tested and
committed. All are fixed and carry regressions in `tests/test_review_regressions.py`.

| Defect | Consequence before the fix |
|---|---|
| `arrears_months` divided a monthly bill by twelve | One month unpaid reported as twelve; every differentiated consequence fired 12× too early, and a 1.75%-of-output shortfall destroyed administrative capacity in five months |
| The contractor bill and its divisor were different quantities | The premium feedback loop was dormant under default policy, or reported eight months owed after one |
| Three writers reduced arrears without touching the composition | Paying every bill in full still left the administration destroyed and suppliers repricing |
| `e.fx` is crowns per karam, but two terms read a fall as an appreciation | A 69% currency collapse was **deflationary**, contributing about −1.3% a month to the CPI |

Also corrected: the declared 0/3/9 lag profile was really 1/4/10 (`apply_lags` runs before the
budget resolves, so a share queued at zero months waited a full month); `rollover_need` was
computed and never used; and the inflation trace listed an `expectations` contributor that never
independently moved prices, so `explain()` could name a cause that was not one.

## 18. What the agents believe, as distinct from what is true

This is the distinction the brief calls mandatory, and it is now enforced by construction rather
than by intention.

    TRUE (engine)     exchange_rate_pass_through = 0.39
    B (treasury)      0.36, confidence 0.08 after 18 observations
    C (army)          not held; an army commander does not model the exchange rate

Each delegate carries estimates of the relationships its office bears on, each with a value, a
range and a confidence. The rules:

```
prior       ~ delegate's own seeded stream around a POPULATION midpoint, never the true value
surprise     = max(0, brier - 0.25)   signed by where the world landed relative to the threshold
revision     = value + 0.22·(1 - 0.5·confidence)·tanh(2·surprise)      bounded per relationship
confidence  *= 0.90 on a miss, +0.01 on a hit
```

**Synthetic** throughout. There is no empirical literature on how a language model should revise a
belief about an exchange-rate pass-through, and this does not pretend there is. What it is designed
to make measurable is whether a delegate's model of the world improves as it governs.

Two properties matter and are tested. Priors are drawn around a population midpoint rather than
from the truth, so a delegate starts plausibly wrong and learning is a real task. And no function in
the belief path reads `causality.param` — the only place the truth is ever touched is
`compare_to_truth`, which is research-only and never reaches a prompt.

**Deliberately modest.** This is a belief store with an update rule, not a learning algorithm. The
benchmark question it exists to answer is narrow: does a model that governs this economy come to
understand it better than one that does not, and can we tell.

## Sources

Cited for the *shape and range* of relationships, not as measurements of Karamaniya:

- Ball, L., Leigh, D. and Loungani, P. (2017), "Okun's Law: Fit at 50?", *Journal of Money,
  Credit and Banking* — gap-version Okun coefficients, −0.14 to −0.85.
- Auerbach, A. and Gorodnichenko, Y. (2012, 2013), fiscal multipliers in recession vs expansion,
  0–0.5 vs 1–1.5; and the subsequent ZLB literature finding larger recession multipliers.
- IMF *Exchange Rate Pass-Through in Emerging Markets* and the associated working-paper
  literature — consumer-price pass-through estimates and their decline.
- Knotek, E. (2007), on the cyclical asymmetry of Okun's coefficient.
- Olivera-Tanzi effect, on real revenue falling with inflation — implemented in `fiscal()`.
- Cagan, P. (1956), on money demand under expected inflation — the basis of the existing price
  relation.
- World Bank / FAO material on island food-import vulnerability, referenced in the README.

Added by the second shift:

- APHLIS / JRC and World Bank, *Missing Food* — cereal post-harvest loss by stage, 10-20% for
  weak-infrastructure economies, with the 30-40% figures shown to be unsupported for grain.
- FAO, *Strategic Grain Reserves* (Bulletin 126), and the FAO safe stock-to-use norm of 17-18%,
  about two months of consumption; the conventional three-month import-cover floor, which the IMF
  itself notes has no firm theoretical basis.
- Baulch et al. (2008), on spatial market integration and the arbitrage band; Sen (1981) and the
  Bangladesh 1974 famine literature on entitlement failure and inter-district movement restrictions.
- Manasse, Roubini and Schimmelpennig (IMF WP/05/42 and JIE 2009) — crisis danger zones: external
  debt/GDP above 50%, short-term debt to reserves above 130%, public debt to revenues above 215%.
- Rodrik and Velasco (NBER WP 7364) on short-term debt and capital-flow reversal.
- Gimpelson and Treisman on Russian public-sector arrears; the 2012 Spanish accelerated-payment
  natural experiment on suppliers holding unpaid public bills.
- The coup and mutiny case literature: Cote d'Ivoire 1999, the Gambia 1994, Guinea-Bissau 2004,
  Sierra Leone 1992, Georgia 2001; Singh, *Seizing Power* (2014) on coups as coordination games.
- Operation STRANGLE (RAND R-851) — supply denial rarely collapses a force, transport denial does.
