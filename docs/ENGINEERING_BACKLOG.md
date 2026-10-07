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

### Phase 4 — governance actuators (evidence-driven)

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| A1 | `training_intensity` lever | high | VERIFIED | `military.py`, `politics.py`, `prompts.py` | `test_training_intensity.py` | Added because agents asked for it 12x and were refused; real effect on `quality()` with a cost |
| A2 | Lever alias resolution | medium | VERIFIED | `politics.py`, `actions.py` | `test_training_intensity.py` | Unambiguous phrasings resolve instead of being explained back |
| A3 | Collision guard | high | VERIFIED | `tests/` | `test_training_intensity.py` | No council lever may share a name with an operational setting |

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
| R6 | Agents refused levers the world needs | high | VERIFIED | `politics.py`, `military.py`, `world.py`, `prompts.py` | `test_training_intensity.py` | Mined 12,594 archived prompts: `army_training_focus` 12x, `army_recruitment_focus` 12x, `patronage` 24x. Added `training_intensity` as a typed Army lever with real tradeoffs, plus a narrow alias table |
| R7 | New lever would have collided with an operational setting | high | VERIFIED | `operations.py`, `military.py` | `test_training_intensity.py` | `training_focus` already meant what the army trains FOR. Renamed the new lever to `training_intensity`; a general guard now asserts no lever shares a name with an operational setting |
| R8 | Repair prompt printed "Motion None" at the model | low | VERIFIED | `motion_actions.py` | — | An untabled motion has no id; it now says "The motion you just wrote" |

### Standalone findings from the log scan

| Finding | Status |
|---|---|
| No unseeded random draws anywhere in the package | VERIFIED — every draw goes through `rng_for` or a fixed/seed-derived `random.Random` |
| Zero state faults across 962 simulated months and 11,260 calls (no NaN, no negative stocks, no counters running backwards, no unstatused motions) | VERIFIED |
| Regional logistics recover in a single month on dilemma resolution rather than ramping, producing a visible step in output | KNOWN LIMITATION — documented, not fixed |
| Archived runs carry infrastructure call errors (session limits, quotas) but no engine faults | OBSERVED |


---

# Second shift: realism

Both shifts share this register. Statuses as defined at the top of the file.

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| R1 | Macro transmission chain with lags | high | VERIFIED | `causality.py`, `economy.py` | `test_transmission.py` | Credit, demand, money and import-price stocks; target moves at once, credit converges over ~9 months |
| R2 | Money measured against capacity | high | VERIFIED | `economy.py` | `test_scenarios_realism.py` | Fixed a *stagflationary* rate rise; baseline inflation band tightened to -1.2%/+2.2% |
| R3 | Policy rate reaches expectations | high | VERIFIED | `causality.py` | `test_scenarios_realism.py` | Credibility had no route from the policy rate at all |
| R4 | Fiscal structure: arrears composition | high | VERIFIED | `economy.py`, `world.py` | `test_fiscal_structure.py` | Five categories with protection weights; army protected, not immune |
| R5 | Debt service split, rollover, reserve adequacy | medium | VERIFIED | `economy.py` | `test_fiscal_structure.py` | Gross issuance capacity; rollover genuinely crowds out |
| R6 | Post-harvest losses | medium | VERIFIED | `economy.py` | `test_food_distribution.py` | 7.5-17.5%, inside the APHLIS/World Bank 10-20% band |
| R7 | Regional food distribution | high | VERIFIED | `economy.py` | `test_food_distribution.py` | National surplus 1.07 with a region at 28% of need unmet |
| R8 | Foreign red lines and leadership | medium | VERIFIED | `foreign.py` | `test_foreign_strategy.py` | Delegated; trajectories verified byte-identical |
| R9 | Forecast ledger and scoring | high | VERIFIED | `forecasts.py` | `test_forecasts.py` | Brier, Murphy, Pesaran-Timmermann baseline; own record only |
| R10 | Military mobilization, unit response, supply chain | high | VERIFIED | `military.py`, `politics.py` | `test_military_realism.py` | Delegated; coup path now reads the distribution |
| R11 | Adversarial scenario suite | high | VERIFIED | `tests/` | `test_scenarios_realism.py` | 22 qualitative checks; found three structural bugs |
| R12 | Six defects from adversarial review | high | VERIFIED | see report | `test_review_regressions.py` | Four HIGH; all were one quantity computed in two places |
| R13 | Mobilization policy lever | high | VERIFIED | `world.py`, `politics.py`, `military.py`, `prompts.py` | `test_military_realism.py` | Army office calls up the reserve; costs money, labour and time |
| R14 | Agent causal learning from forecast errors | high | VERIFIED | `causal_beliefs.py` (new) | `test_causal_beliefs.py` | Per-delegate parameter beliefs, revised from errors; truth never read |
| R15 | Regime-dependent coefficients | low | DEFERRED | — | — | Persistence and multipliers are per-world, not per-regime |


---

# Third shift: token efficiency

Measure where a run's tokens go, then offer ways to send fewer of them without changing a default run.
Ground rule for the shift: every feature is opt-in, recorded in `config.json` and the manifest when on,
and a default run must send byte for byte the prompts the published engine-5 code sends.
`docs/TOKEN_EFFICIENCY.md` has the measurements and their limits.

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| T1 | Prompt freeze against the engine-5 tag | high | VERIFIED | `tests/fixtures/prompt_freeze_engine5.json`, `tools/prompt_freeze.py` | `test_prompt_freeze.py` | A default 4-month run reproduces the sha256 of the system prompt and of all 78 prompts the engine-5 tag sends |
| T2 | Token ledger and prefix-cache simulation | high | VERIFIED | `tokens.py` (new), `__main__.py` | `test_token_saving.py` | `python -m karamaniya tokens`: input and output by phase, seat and prompt section, provider counts, and the share a cache could reuse per phase/month/run. No model calls |
| T3 | Every call paired across log and prompt files | medium | VERIFIED | `council.py` | `test_token_saving.py` | `call_id` (`month.n`) in both records; older runs are paired by month, phase and member |
| T4 | Provider cache and reasoning counts | medium | VERIFIED | `backends/*.py` | `test_backends.py`, `test_cli_backends.py`, `test_copilot_cli.py` | Cache reads, cache writes and reasoning tokens recorded apart from the totals, which keep their engine-5 meaning |
| T5 | Cache prices | low | VERIFIED | `backends/base.py` | `test_backends.py`, `test_token_saving.py` | `price_cache_read` / `price_cache_write`; without them every input token costs `price_in`, as before |
| T6 | Cache-friendly prompt layout | high | VERIFIED | `decision_context.py`, `anthropic_api.py` | `test_prompt_freeze.py`, `test_backends.py` | Same words, reordered by how widely they are shared; month reuse 21% to 41%; cache points become Anthropic `cache_control` breakpoints |
| T7 | Compact schema hint | low | VERIFIED | `actions.py`, `council.py` | `test_token_saving.py` | Every field and allowed value kept; schema text -24%, input -2%; `auto` only where the connector enforces the schema |
| T8 | Briefing on demand | medium | VERIFIED | `token_saving.py`, `council.py` | `test_token_saving.py` | Headlines for all, full sections for whoever asked; up to -4% input; what each model asks to read is recorded |
| T9 | Quiet months | high | VERIFIED | `token_saving.py`, `council.py`, `briefing.py` | `test_token_saving.py` | Skipped only when every delegate stands by and no wake condition holds; never in an election or handover month, in war, after a coup or a departure, or with a new issue, a major public event, a proposal, a deferred motion or a private message waiting; up to -39% calls |
| T10 | A fixed model for the foreign cabinets | medium | VERIFIED | `council.py`, `config.py` | `test_token_saving.py` | Both cabinets on one backend, no council seat borrowed |
| T11 | Effort by phase | medium | IMPLEMENTED | `backends/*.py`, `token_saving.py` | `test_token_saving.py`, `test_backends.py`, `test_cli_backends.py`, `test_copilot_cli.py` | Each connector sends the phase's effort and each call records it. What it saves is unmeasured: that needs real seats |
| T12 | Report header printed "null" | low | IMPLEMENTED | `report_template.html` | — | Checked in a browser; the template has no automated test |
| T13 | Memory re-sent as prose | — | CLOSED | — | — | Measured: engine 5 already sends dated, engine-written memory items (1.2% of input). Nothing built |
| T15 | Codex reasoning tokens counted twice | medium | VERIFIED | `backends/codex_cli.py` | `test_cli_backends.py` | Engine 5 added `reasoning_output_tokens` to `output_tokens`, which already includes them: codex-rs fills both from the Responses API usage, and its own test has output 10 with reasoning 5 and total = input + output. Codex output is now recorded once; `cache_write_input_tokens` is read too. Codex output counts in engine-5 runs are overstated by their reasoning |
| T16 | Cost per month, per seat and across runs | medium | VERIFIED | `tokens.py`, `__main__.py` | `test_token_saving.py` | Setup calls apart from the monthly rate; each seat's characters per provider-counted token; several runs combine into a rate and a projection (`--months`). On a real 19-month council the Codex CLI seats counted 2.5-2.75 characters per token against 4.0-4.4 for local models, consistent with the CLI adding several thousand tokens of its own instructions to every call |
| T17 | Prefix reuse measured on a real local server | medium | VERIFIED | `tools/cache_replay.py` | `test_token_saving.py` | Replays a run's prompts through Ollama and counts, from the server's log, the tokens it really evaluated (the API reports the whole prompt even when it came from the cache) |

### Open, deliberately

| ID | Title | Reason |
|---|---|---|
| T14 | Each feature on real models, on and off, same seeds | Needs paid or subscription seats. The behaviour-dependent savings (briefing on demand, quiet months, effort by phase) are upper bounds until then |
