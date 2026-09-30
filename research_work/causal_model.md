# Causal model summary (Task 7-source; Task-0004 remainder)

Source: `docs/CAUSAL_WORLD_MODEL.md` + `karamaniya/economy.py` + `karamaniya/causality.py`.
HEAD `e4c27f7`. Read-only summary; no behavior claims beyond the doc.

## Relationship table (abridged; full equations in the doc)

| # | Relationship | Doc section | Class |
|---|---|---|---|
| 1 | Output / output gap (production fn, potential as slow stock) | 1 | ACCOUNTING_IDENTITY + SYNTHETIC_ASSUMPTION (supply-determined; no demand closure — doc's largest simplification) |
| 2 | Unemployment (Okun level-target, β 0.20-0.60 via flexibility) | 2 | EMPIRICAL_APPROXIMATION |
| 3 | Inflation decomposition (money Cagan + food/goods/FX/expectations/wages/gap/shortage) | 3 | EMPIRICAL_APPROXIMATION (money core) + ACCOUNTING (decomp) |
| 4 | FX pressure + pass-through (0.11-0.48 realized) | 4 | EMPIRICAL_APPROXIMATION |
| 5 | Fiscal identity (spending = revenue+borrowing+arrears+printing+reserves+transfers) | 5 | ACCOUNTING_IDENTITY |
| 6 | Arrears accrual/settlement, premium on borrowing | 5/economy.py:418-556 | ACCOUNTING_IDENTITY (settlement keeps composition, e4c27f7) |
| 7 | Credit/demand/money, multiplier (state-dependent), fiscal impulse | causality.py:161-198,290-327 | EMPIRICAL_APPROXIMATION |
| 8 | Expectations (credibility-weighted hybrid; earned from record) | 3 (cred formula) | SYNTHETIC_ASSUMPTION (weights) w/ empirical shape |
| 9 | Food production/import dependence, storage losses, regional delivery | economy.py:169-367 | ACCOUNTING_IDENTITY (stocks) + EMPIRICAL_APPROXIMATION (loss params) |
| 10 | Military readiness/loyalty, policing/unrest, foreign responses | military.py/society.py/foreign.py | SYNTHETIC_ASSUMPTION (behavioral, stochastic) |

## Hidden structural parameters (agents cannot see)

`import_dependency, labor_market_flexibility, tax_compliance,
bureaucratic_efficiency, inflation_persistence, exchange_rate_pass_through,
fiscal_multiplier_normal/recession, financial_depth, corruption_baseline,
food_storage_capacity, productivity_growth, price_rigidity`
(recorded per-run in manifest `structural_parameters`, e.g. final-gov-seed1;
seeded via `rng_for` streams `manifest.py:31-43`).

## Why the same policy is not optimal across seeds

Coefficients above vary per world (seeded); credibility/path dependence makes
identical levers act differently given history; foreign dispositions + dilemmas
are seeded per run. Same vote, different world → different consequence.
