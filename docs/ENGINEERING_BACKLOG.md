# Karamaniya Engineering Backlog

Live task register for the engine-hardening shift. Statuses: `TODO`, `IN_PROGRESS`,
`IMPLEMENTED`, `VERIFIED`, `DEFERRED`, `BLOCKED`.

`IMPLEMENTED` means code exists. `VERIFIED` means a regression test exercises it and the
suite passes. Nothing is marked `VERIFIED` on the strength of reading the diff.

## Reconnaissance result

The repository was already well past the state the mission brief assumes. These items from
the brief were **already implemented and tested** before this shift began, so they were not
rebuilt:

| Brief item | Where it already lives |
|---|---|
| A. Canonical directive violation history | `freshness.py` — `defiance_log`, `_streak`, `restored_month`, "prior violations are never erased" |
| B. Memory phase timing | `memory.py` — phase tagging, `POST_EXECUTION` |
| C. Directive vs order vs actual world state | `freshness.py` — `current_setting`, `directive_since`, `actual_text` |
| D. Office vacancy and removal authority | `vacancy.py` — `vacant_since`, `PRE_REMOVAL_ORDER` |
| G. Motion execution status | `convergence.py`, `council.py` — one canonical status per motion |
| I. Amendment → final executable payload | `motion_actions.py` — `MOTION_ACTION_MISMATCH`, `EXECUTION_BLOCKED` |
| J. Numeric grounding | `council.py`, `motion_actions.py` — `NUMERIC_GROUNDING` |
| K. Stale memory / fact freshness | `freshness.py` |
| M. UNKNOWN_LEVER audit | `politics.py` — `UNKNOWN_LEVER` rejection |

Genuinely open items were confirmed by grep, not assumed.

## Open work

### Phase 1 — engine integrity

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| I1 | Foreign action idempotency ledger | high | TODO | `foreign.py` | `test_foreign_idempotency.py` | `action_id` + `effects_applied` ledger; duplicate application refused |
| I2 | Leak/media provenance layering | high | TODO | `provenance.py` (new), `intelligence.py` | `test_provenance.py` | RAW_SOURCE never overwritten by PRESS_INTERPRETATION or AGENT_BELIEF |
| I3 | Structured error taxonomy | medium | TODO | `errors.py` (new) | `test_errors.py` | Missing codes (`STALE_AUTHORITY`, `MEMORY_PHASE_MISMATCH`, `FOREIGN_ACTION_DUPLICATE`, `CONDITION_UNRESOLVED`, `MOTION_SEMANTIC_MISMATCH`) recorded not raised |

### Phase 2/3 — causality, reproducibility

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| C1 | Structural parameters per seed | high | TODO | `causality.py` (new) | `test_causality.py` | Bounded, seeded, recorded in manifest, hidden from agents |
| C2 | Lag / scheduled-effect registry | high | TODO | `causality.py` | `test_causality.py` | Policies schedule effects at 0/1–3/3–12 month horizons |
| C3 | Output gap and potential output | high | TODO | `economy.py`, `causality.py` | `test_causal_economy.py` | `output_gap`, `potential_output`, slow-moving potential |
| C4 | Okun-style unemployment with persistence | high | TODO | `society.py`, `causality.py` | `test_causal_economy.py` | Unemployment no longer read straight off utilisation |
| C5 | Multi-cause inflation + expectations | high | TODO | `economy.py` | `test_causal_economy.py` | Persistence, expectations, demand, FX pass-through, food/energy, wage, money |
| C6 | Exchange-rate pressure model | medium | TODO | `economy.py` | `test_causal_economy.py` | Depreciation from pressure, not an identity |
| C7 | State-dependent fiscal multipliers | medium | TODO | `causality.py`, `economy.py` | `test_causal_economy.py` | Larger in slack, smaller when capacity-constrained |
| C8 | Real wages tracked separately | medium | TODO | `economy.py` | `test_causal_economy.py` | Nominal raise under higher inflation is a real cut |
| C9 | Regime states | medium | TODO | `causality.py` | `test_causality.py` | Descriptive only; never scripted responses |
| C10 | Calibration mode + causal trace | high | TODO | `calibration.py` (new) | `test_calibration.py` | "Why did this change?" decomposition, hidden from agents |
| C11 | Agent forecasts as structured claims | low | DEFERRED | — | — | Needs prompt-surface changes; see report |
| C12 | Reproducibility manifest | high | TODO | `manifest.py` (new) | `test_manifest.py` | seeds, models, versions, parameters, prompt version |
| C13 | `docs/CAUSAL_WORLD_MODEL.md` | high | TODO | `docs/` | — | Equation, units, ranges, rationale, lags, limitations |

### Not started, deliberately

| ID | Title | Reason |
|---|---|---|
| X1 | Full sectoral CGE / DSGE | Brief §40 forbids; not supported by architecture |
| X2 | Per-region full economic simulation | Regions keep a bounded subset, per brief §5D |

## Ground rules held during this shift

- Never manufacture conflict, unanimity, coups or scandals. §NO BEHAVIORAL CHEATING.
- Never let a passed motion imply an executed one.
- Never let an agent see a true structural parameter or a causal decomposition.
- Accounting identities exact; empirical relations parameterised and sourced; behavioural
  responses stochastic and state-dependent. Never blended into one score.
- 358 pre-existing tests must keep passing throughout.
