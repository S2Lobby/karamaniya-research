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

1. **Output is supply-determined.** Demand support moves utilisation, not capacity, so there is no
   explicit demand block and no `output = min(supply, demand)` closure. The multiplier is live
   through utilisation (§5), which is why this is a simplification rather than a gap — but it is
   still the largest one.
2. **`fx_step()` is still not called by the engine.** The depreciation *pressure* now drives
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
7. **Agent forecasts (§37 of the brief) are not implemented.** The structured-claim machinery
   exists in spirit but the prompt surface was not changed.

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
