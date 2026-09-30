# Second Shift: Realism Report

Substantial implementation work on simulation realism, on top of the reliability work of the first
shift. The integrity guarantees were preserved throughout: no pre-existing test was weakened or
deleted, and the suite grew from **560 to 757**.

---

## 1. Systems implemented

All six of the brief's priority areas, in its order. Each is integrated into the running
simulation, not merely defined.

| # | System | State |
|---|---|---|
| 1 | Macro transmission: rate → credit → demand, money → prices, import costs | integrated |
| 2 | Fiscal: arrears composition, debt service split, rollover, reserve adequacy | integrated |
| 3 | Food: post-harvest losses, regional distribution | integrated |
| 4 | Foreign: red lines, leadership confidence, constituency pressure | integrated |
| 5 | Forecasts: ledger, scoring, calibration | integrated |
| 6 | Military: mobilization, unit-level response, supply chain | integrated (unit response wired into coups; mobilization reachable as an Army lever) |
| 7 | Agent causal learning: beliefs about the world, held apart from the truth | integrated |

Delivered ahead of the brief's own priority floor, which was macro → fiscal → regional/food →
foreign; the forecast ledger and military realism were listed as "if runtime permits" and both are
done.

## 2. Files changed

```
karamaniya/economy.py        +396   arrears composition, food losses and distribution,
                                    debt service, rollover, capacity-based pricing
karamaniya/causality.py      +153   credit/demand/money/import transmission, resolve term
karamaniya/military.py       +415   mobilization, unit response, supply chain   [delegated]
karamaniya/foreign.py        +415   red lines, leadership, constituencies        [delegated]
karamaniya/forecasts.py      +219   forecast ledger and scoring                  [new]
karamaniya/world.py           +40   Economy and Military state
karamaniya/politics.py        +26   coup path reads the unit distribution; arrears settlement
karamaniya/actions.py         +18   forecast field in the decision schema
karamaniya/council.py         +11   forecasts recorded each month
karamaniya/backends/scripted.py +41  stand-ins emit forecastable claims
karamaniya/decision_context.py +8   a delegate's own forecast record
karamaniya/engine.py           +3   forecast resolution in the monthly pipeline
karamaniya/founding.py, scenarios.py +7  inherited arrears carry a composition
```

**195 new tests** in eight new files — `test_transmission.py` (29), `test_military_realism.py` (36,
delegated plus 8 for the central reconciliation), `test_forecasts.py` (27),
`test_review_regressions.py` (27), `test_scenarios_realism.py` (22), `test_foreign_strategy.py` (21,
delegated), `test_food_distribution.py` (17), `test_fiscal_structure.py` (16) — plus two added to
existing files, for **197 in total**.

## 3. Formulas added

Full derivations, units and ranges in `docs/CAUSAL_WORLD_MODEL.md` sections 10–17. In brief:

```
credit_conditions ← 0.72·credit + 0.28·(1 - 0.35·depth·max(0, real_rate - 0.04))
demand_pressure   ← 0.62·demand   + 0.38·output_gap
money_pressure    ← 0.55·money    + 0.45·(money_growth - output_growth - expected_inflation)
target_price      = scale · money · velocity / CAPACITY          [was / actual output]
credibility       = 0.38·low_infl + 0.30·no_monetisation + 0.17·reserves + 0.15·resolve
shortfall_i       = unpaid · (1 - protection_i)·bill_i / Σ (1 - protection_j)·bill_j
rollover_need     = debt_short_share · debt_dom / 12
food_loss         = 0.075 + 0.10·(1 - mean_logistics)
delivery_ceiling  = need · (0.55 + 0.45·logistics)
Brier             = mean((confidence - outcome)²)                [binomial 0-1 scale]
BS                = REL - RES + UNC                              [reconciles exactly]
```

## 4. Empirical grounding

Every parameter is cited with its source and range in the model document. Four research passes
were run, each instructed to mark anything it could not verify as NOT FOUND rather than estimate.

**Used, with ranges:** Okun's slope inside Ball/Leigh/Loungani's −0.14 to −0.85; fiscal multipliers
bracketing Auerbach–Gorodnichenko's 0–0.5 (expansion) and 1–1.5 (recession); consumer-price
pass-through inside the IMF's 0.02–0.58 range; cereal post-harvest losses at 10–20% (APHLIS/World
Bank); the three-month import-cover reserve floor; military pay arrears preceding coups in Côte
d'Ivoire 1999, the Gambia 1994, Guinea-Bissau 2004 and Sierra Leone 1992; civil-service strike
thresholds around two to three months; the 2012 Spanish payment episode on suppliers; coup
participation shares — Turkey 2016 at 1.5% of the force, Venezuela 2019 at 0.1–1%; Operation
STRANGLE (RAND R-851) on supply versus transport denial.

**Deliberately NOT used.** The widely quoted 30–40% cereal loss figures, which the research showed
are unsupported for grain. A "3:1 rule" for combat force ratios, which the Dupuy databases do not
support (attackers win most historical battles even near parity). The Good Judgment Project's
0.25/0.37 Brier figures, which are on a 0–2 scale and are routinely misreported as 0–1.

The model document labels every relationship as an **accounting identity**, an **empirical
approximation** or a **synthetic assumption**, and states plainly that these are modelling choices
for a fictional island rather than measurements of any real country.

## 5. Behaviour-changing effects

These alter simulation output. Runs are not comparable across this boundary.

1. **A rate rise now reduces inflation.** It was *stagflationary*: the money relation divided by
   actual output, so a demand recession lowered the denominator and raised prices, and tightening
   under inflation raised expected inflation. Money is now measured against capacity.
2. **Unemployment, credit and money now move with lags** instead of adjusting within the month.
3. **Arrears have a composition**, with differentiated consequences, and paying them clears them.
4. **Food is lost between harvest and plate**, and does not reach a region whose roads have failed.
5. **A coup no longer carries the whole army**; a garrison can decline to pick a side.
6. **Forecasts are recorded and scored**, and a delegate sees its own calibration.
7. **The Army can call up the reserve**, at a cost in money, labour and time.
8. **Crossing a foreign red line** moves that actor's hostility and threat perception.
9. The calm baseline tightened: year-on-year inflation from a −1.0%/+3.9% band to −1.2%/+2.2%.

## 6. Migration notes

- New `Economy` fields (18) and `Military` fields (2), all with defaults. `Military` uses
  `_mk`, which tolerates missing keys, so **checkpoints from before this shift load unchanged** —
  asserted by tests in three separate files.
- New keys inside `World.institutions` (`forecasts`) and `World.foreign` (red lines, leadership,
  constituencies). Nothing was renamed or removed.
- `World.audit_errors` and the provenance store were added in the first shift and are unchanged.
- **`K_FOOD` 5.32 → 5.75.** The production constant now carries the post-harvest loss adjustment so
  the documented founding condition ("available domestic food about 74% of need") still holds.
  Founding output moves 6.53B → 6.63B annual crowns because lost food is still produced. The README
  says "74% after post-harvest losses" rather than quietly reporting the old figure.
- `WORLD_ENGINE` remains 3; this shift did not bump it again, so a run paused mid-shift and resumed
  would mix engine states. **This is worth doing if runs are resumed across the boundary.**

## 7. Test results

```
python -m unittest discover -s tests -t .
Ran 757 tests in 69s
OK
```

560 at the start of this shift → 757. No failures outstanding.

**Failures encountered during the shift, and what they were.** Roughly twenty, and the distinction
worth recording is between tests that were wrong and code that was wrong. My own test premises were
wrong in eight cases — asserting strict monotonicity where the target itself drifts, assuming a
crown world has a karam exchange rate, forgetting that output growth is part of the money
requirement, inverting a depth inequality. Code was wrong in the rest, including six HIGH-severity
defects found by adversarial review (§9).

## 8. Long-run stability

Every configuration below was run after the final commit.

| Check | Result |
|---|---|
| 25 seeds × 36 months, no policy | no non-finite, negative or inconsistent state |
| 20 seeds × 36 months, final build | same |
| Arrears composition vs total, throughout | reconciles within 2% |
| 3 × 36-month governed runs (scripted council) | outcomes voted_out / revolution / revolution; 42 motions, 29 contested; **0 engine errors, integrity clean** |
| Scenario pressure tests A–E | complete, including a democratic handover |
| Archived runs (96 runs, 1,022 simulated months) | 9 infrastructure call errors, all historical; **zero state faults** |

Baseline after the shift: inflation −1.2% to +2.2% year-on-year, food ratio 1.02–1.05, hunger
essentially zero, credit stable at 1.0 when rates are below neutral.

## 9. Defects found in this shift's own work

An adversarial reviewer was given the three commits of the shift with instructions to prove every
finding with a reproduction rather than assert it from reading. It found **four HIGH-severity bugs
in code that had been written, tested and committed**, plus two medium ones.

| Defect | Consequence before the fix |
|---|---|
| `arrears_months` divided a monthly bill by twelve | One month unpaid reported as twelve; a 1.75%-of-output shortfall destroyed administrative capacity in five months |
| The contractor bill and its divisor were different quantities | The premium loop was dormant under default policy, or reported eight months owed after one |
| Three writers reduced arrears without touching the composition | Paying every bill in full still left the administration destroyed and suppliers repricing |
| `e.fx` is crowns per karam, but two terms read a fall as appreciation | A 69% currency collapse was **deflationary**, contributing about −1.3% a month to the CPI |
| The declared 0/3/9 lag profile was really 1/4/10 | The immediate fiscal impulse was a month late |
| `rollover_need` was computed and never used | The rollover calendar was decorative |

All fixed, with 27 regressions in `tests/test_review_regressions.py`, one per defect and per
property.

**The pattern worth naming:** four of the six were the same mistake in different clothes — two
places computing what should have been one quantity and drifting apart (the bill and its divisor,
the arrears total and its composition, two readings of the exchange rate, two lag profiles). The fix
in each case was to make one function the source of truth and have every consumer read it.

## 10. Unresolved limitations

1. **Output remains supply-determined.** Demand support moves utilisation, not capacity; there is no
   `output = min(supply, demand)` closure.
2. **Regime states do not modulate coefficients.** Persistence and the multipliers are drawn per
   world, not per regime, so the model does not become more nonlinear in a crisis.
3. **Only the fiscal lag channel is wired.** The registry is general; the other five profiles are
   declared but those channels reach prices through existing partial adjustment.
4. *(resolved)* **Mobilization now has a policy lever.** The Army office can order
   `mobilization` (none | partial | general): reservists are embodied over about three months,
   cost money to keep embodied, and are drawn one-for-one out of the labour force while they
   serve.
5. **Corruption's economic channels are thin** — tracked and fed into implementation, but
   procurement cost inflation and quality loss are not modelled.
6. **No sectoral input-output structure.**
7. **Regional logistics still recover in a single month** on dilemma resolution rather than ramping,
   producing a visible step in output. Pre-existing, confirmed identical in the baseline commit.
8. **`fx_step()` remains unused** — depreciation pressure now drives the rate through confidence,
   but the separate helper is still not called.

## 11. Deferred work

- **A learning algorithm rather than a belief store.** Delegates now revise estimates of causal
  relationships from their forecast errors, but the update rule is a fixed heuristic, not
  inference. Whether a model can do better than it is not testable while the engine supplies the
  rule.
- **Regime-dependent coefficients** (§23), which would close limitation 2.
- **The mobilization lever**, which would make the military system reachable by a council.
- **Reserve-adequacy as a decision input** rather than a reported metric.

## 12. Benchmark implications

The point of this shift was to make the engine worth benchmarking on. Four consequences:

**The same policy is no longer optimal everywhere.** Structural parameters are drawn per world from
calibrated bands, so a fiscal expansion does different work in different worlds: measured live, the
same impulse yields +3.3% demand support in deep slack and +0.6% when already overheating.

**There is now something to measure besides votes.** The forecast ledger scores whether a model's
beliefs about how the economy works were borne out, against a no-skill baseline that is not 50%.
That is a different and more interesting question than whether it voted the way the engine's author
would have. A model that cannot beat a trend-following stand-in — which scores a Brier of 0.227 and
exactly matches the no-skill baseline — is not adding anything.

**Agents cannot see the answer key.** True structural parameters, the causal trace, red lines and
leadership confidence are all hidden, and tests assert they do not reach a prompt. Discovering the
world is a task, not a lookup.

**Runs are interpretable after the fact.** The manifest records the seed, every seeded stream, the
prompt and engine versions, the structural parameters and the model that *actually* served each
seat, and `divergences()` names the axis on which two runs differ. A 10-seed batch is comparable
without guesswork.

## 13. Commits

```
60ee2fd  feat: complete the macro transmission chain with lags
1a71343  feat: fiscal structure - who the government owes, and what that costs it
dc2c069  feat: post-harvest losses and regional food distribution
e838787  fix: six defects found by adversarial review of this shift's own code
a2917af  feat: foreign red lines and leadership confidence; agent forecast ledger
666beec  feat: adversarial scenario suite, and three structural fixes it forced
6614e38  docs: causal model sections 10-17, limitations resolved, empirical sources
117753d  feat: scripted stand-ins emit forecasts, so the ledger is usable without spending calls
af96ad6  feat: wire unit-level coup response, and make military state survive a checkpoint
```

## 14. On the use of subagents

Four research passes and two implementation tasks were delegated. One implementation task was
rejected in outline before it began: an early plan had a subagent rewriting the coup logic, which
would have collided with the migration work in `politics.py`; it was scoped down to pure functions
and the wiring was done centrally instead.

Neither implementation was accepted on report. The foreign work was verified by running four seeds
over twenty months against the committed version and comparing foreign state, inflation and output
— **byte-identical**, confirming its claim that no existing trajectory moved. The military work was
verified by independently reproducing its headline numbers: an unpopular plotter carrying 1.4% of
the force against Turkey 2016's 1.5%, and the STRANGLE result where stockpiles *rise* under
interdiction while transport decays.

Both subagents reported their own limitations accurately, including one that flagged a persistence
gap caused by its own file-ownership constraint — which was then fixed centrally rather than left.
