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
| I1 | Foreign action idempotency ledger | high | VERIFIED | `foreign.py` | `test_foreign_idempotency.py` | `action_id` + `effects_applied` ledger; duplicate application refused |
| I2 | Leak/media provenance layering | high | VERIFIED | `provenance.py` (new), `intelligence.py` | `test_provenance.py` | RAW_SOURCE never overwritten by PRESS_INTERPRETATION or AGENT_BELIEF |
| I3 | Structured error taxonomy | medium | VERIFIED | `errors.py` (new) | `test_errors.py` | Missing codes (`STALE_AUTHORITY`, `MEMORY_PHASE_MISMATCH`, `FOREIGN_ACTION_DUPLICATE`, `CONDITION_UNRESOLVED`, `MOTION_SEMANTIC_MISMATCH`) recorded not raised |

### Phase 2/3 — causality, reproducibility

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| C1 | Structural parameters per seed | high | VERIFIED | `causality.py` (new) | `test_causality.py` | Bounded, seeded, recorded in manifest, hidden from agents |
| C2 | Lag / scheduled-effect registry | high | VERIFIED | `causality.py` | `test_causality.py` | Policies schedule effects at 0/1–3/3–12 month horizons |
| C3 | Output gap and potential output | high | VERIFIED | `economy.py`, `causality.py` | `test_causal_economy.py` | `output_gap`, `potential_output`, slow-moving potential |
| C4 | Okun-style unemployment with persistence | high | VERIFIED | `society.py`, `causality.py` | `test_causal_economy.py` | Unemployment no longer read straight off utilisation |
| C5 | Multi-cause inflation + expectations | high | VERIFIED | `economy.py` | `test_causal_economy.py` | Persistence, expectations, demand, FX pass-through, food/energy, wage, money |
| C6 | Exchange-rate pressure model | medium | IMPLEMENTED | `economy.py` | `test_causal_economy.py` | Depreciation from pressure, not an identity |
| C7 | State-dependent fiscal multipliers | medium | VERIFIED | `causality.py`, `economy.py` | `test_causal_economy.py` | Larger in slack, smaller when capacity-constrained |
| C8 | Real wages tracked separately | medium | VERIFIED | `economy.py` | `test_causal_economy.py` | Nominal raise under higher inflation is a real cut |
| C9 | Regime states | medium | VERIFIED | `causality.py` | `test_causality.py` | Descriptive only; never scripted responses |
| C10 | Calibration mode + causal trace | high | VERIFIED | `calibration.py` (new) | `test_calibration.py` | "Why did this change?" decomposition, hidden from agents |
| C11 | Agent forecasts as structured claims | low | DEFERRED | — | — | Needs prompt-surface changes; deliberately not attempted mid-shift |
| C12 | Reproducibility manifest | high | VERIFIED | `manifest.py` (new) | `test_manifest.py` | seeds, models, versions, parameters, prompt version |
| C13 | `docs/CAUSAL_WORLD_MODEL.md` | high | VERIFIED | `docs/` | — | Equation, units, ranges, rationale, lags, limitations |

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


## Added during the shift (found by inspecting archived runs)

The mission asked for the existing run logs to be mined for problems that had never been spotted.
`tools/scan_runs.py` was written for that and is now part of the repo.

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| R1 | Cline seats aborting the run over prompt length | high | VERIFIED | `decision_context.py`, `cline_cli.py` | `test_prompt_budget.py` | `compose` could not always reach its budget (200-char floor, single-section truncation); connector now trims rather than aborting |
| R2 | `prompt_budget` advertising room that did not exist | medium | VERIFIED | `cline_cli.py` | `test_prompt_budget.py` | The 4000-char floor could exceed the real command-line room |
| R3 | Hedged warning recorded as a coup plot | high | VERIFIED | `provenance.py`, `council.py` | `test_provenance.py`, `test_leak_provenance.py` | `"may cause a coup"` matched a substring test for `coup`; fired `plot_exposed`, stripped trust, branded the speaker |
| R4 | Productivity raised potential but not actual output | high | VERIFIED | `economy.py` | `test_causal_economy.py` | Output gap drifted permanently negative from trend growth alone |
| R5 | Codex `invalid_json_schema` | — | CLOSED | `codex_cli.py` | — | Investigated: already fixed in this tree (`strict_schema` rewrites `required`). No change needed |

### Standalone findings from the log scan

| Finding | Status |
|---|---|
| No unseeded random draws anywhere in the package | VERIFIED — every draw goes through `rng_for` or a fixed/seed-derived `random.Random` |
| Zero state faults across 962 simulated months and 11,260 calls (no NaN, no negative stocks, no counters running backwards, no unstatused motions) | VERIFIED |
| Regional logistics recover in a single month on dilemma resolution rather than ramping, producing a visible step in output | KNOWN LIMITATION — documented, not fixed |
| Archived runs carry infrastructure call errors (session limits, quotas) but no engine faults | OBSERVED |
