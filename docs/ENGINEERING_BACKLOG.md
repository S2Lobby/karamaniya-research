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
| C2 | Lag / scheduled-effect registry | high | VERIFIED | `causality.py` | `test_causality.py` | Only the fiscal impulse is lagged through the queue (its later instalments at 3 and 9 months); the non-fiscal `CHANNEL_LAGS` are not scheduled |
| C3 | Output gap and potential output | high | VERIFIED | `economy.py`, `causality.py` | `test_causal_economy.py` | `output_gap`, `potential_output`, slow-moving potential |
| C4 | Okun-style unemployment with persistence | high | VERIFIED | `society.py`, `causality.py` | `test_causal_economy.py` | Unemployment no longer read straight off utilisation |
| C5 | Multi-cause inflation + expectations | high | VERIFIED | `economy.py` | `test_causal_economy.py` | Persistence, expectations, demand, FX pass-through, food/energy, wage, money |
| C6 | Exchange-rate pressure model | medium | IMPLEMENTED | `economy.py` | `test_causal_economy.py` | Depreciation from pressure, not an identity |
| C7 | State-dependent fiscal multipliers | medium | VERIFIED | `causality.py`, `economy.py` | `test_causal_economy.py` | Larger in slack, smaller when capacity-constrained |
| C8 | Real wages tracked separately | medium | VERIFIED | `economy.py` | `test_causal_economy.py` | Nominal raise under higher inflation is a real cut |
| C9 | Regime states | medium | VERIFIED | `causality.py` | `test_causality.py` | Descriptive only; never scripted responses |
| C10 | Calibration mode + causal trace | high | VERIFIED | `calibration.py` (new) | `test_calibration.py` | "Why did this change?" decomposition, hidden from agents |
| C11 | Agent forecasts as structured claims | low | VERIFIED | `forecasts.py` | `test_forecasts.py` | Done later (a2917af): up to two scored forecasts a month, of the delegate's own choosing. Engine 13 added the panel every delegate answers alike (T54) and put both in the report |
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
| T1 | Prompt freeze against the engine-5 tag | high | VERIFIED | `tests/fixtures/prompt_freeze_engine6.json` (engine 5's fingerprints until engine 6), `tools/prompt_freeze.py` | `test_prompt_freeze.py` | A default 4-month run reproduces the sha256 of the system prompt and of all 78 prompts the engine-5 tag sends |
| T2 | Token ledger and prefix-cache simulation | high | VERIFIED | `tokens.py` (new), `__main__.py` | `test_token_saving.py` | `python -m karamaniya tokens`: input and output by phase, seat and prompt section, provider counts, and the share a cache could reuse per phase/month/run. No model calls |
| T3 | Every call paired across log and prompt files | medium | VERIFIED | `council.py` | `test_token_saving.py` | `call_id` (`month.n`) in both records; older runs are paired by month, phase and member |
| T4 | Provider cache and reasoning counts | medium | VERIFIED | `backends/*.py` | `test_backends.py`, `test_cli_backends.py`, `test_copilot_cli.py` | Cache reads, cache writes and reasoning tokens recorded apart from the totals, which keep their engine-5 meaning |
| T5 | Cache prices | low | VERIFIED | `backends/base.py` | `test_backends.py`, `test_token_saving.py` | `price_cache_read` / `price_cache_write`; without them every input token costs `price_in`, as before |
| T6 | Cache-friendly prompt layout | high | VERIFIED | `decision_context.py`, `anthropic_api.py` | `test_prompt_freeze.py`, `test_backends.py` | Same words, reordered by how widely they are shared; month reuse 21% to 41%; cache points become Anthropic `cache_control` breakpoints |
| T7 | Compact schema hint | low | VERIFIED | `actions.py`, `council.py` | `test_token_saving.py` | Every field and allowed value kept; schema text -24%, input -2%; `auto` only where the connector enforces the schema |
| T8 | Briefing on demand | medium | VERIFIED | `token_saving.py`, `council.py` | `test_token_saving.py` | Headlines for all, full sections for whoever asked; up to -4% input; what each model asks to read is recorded |
| T9 | Quiet months | high | VERIFIED | `token_saving.py`, `council.py`, `briefing.py` | `test_token_saving.py` | Skipped only when every delegate stands by and no wake condition holds; never in an election or handover month, in war, after a coup or a departure, with a new issue or a major public event, or with anything addressed to the council waiting (T19); up to -24% calls without foreign cabinets, none with the scripted ones, which write every month |
| T10 | A fixed model for the foreign cabinets | medium | VERIFIED | `council.py`, `config.py` | `test_token_saving.py` | Both cabinets on one backend, no council seat borrowed |
| T11 | Effort by phase | medium | IMPLEMENTED | `backends/*.py`, `token_saving.py` | `test_token_saving.py`, `test_backends.py`, `test_cli_backends.py`, `test_copilot_cli.py` | Each connector sends the phase's effort and each call records it. What it saves is unmeasured: that needs real seats |
| T12 | Report header printed "null" | low | IMPLEMENTED | `report_template.html` | — | Checked in a browser; the template has no automated test |
| T13 | Memory re-sent as prose | — | CLOSED | — | — | Measured: engine 5 already sends dated, engine-written memory items (1.2% of input). Nothing built |
| T15 | Codex reasoning tokens counted twice | medium | VERIFIED | `backends/codex_cli.py` | `test_cli_backends.py` | Engine 5 added `reasoning_output_tokens` to `output_tokens`, which already includes them: codex-rs fills both from the Responses API usage, and its own test has output 10 with reasoning 5 and total = input + output. Codex output is now recorded once; `cache_write_input_tokens` is read too. Codex output counts in engine-5 runs are overstated by their reasoning |
| T16 | Cost per month, per seat and across runs | medium | VERIFIED | `tokens.py`, `__main__.py` | `test_token_saving.py` | Setup calls apart from the monthly rate; each seat's characters per provider-counted token; several runs combine into a rate and a projection (`--months`). On a real 19-month council the Codex CLI seats counted 2.5-2.75 characters per token against 4.0-4.4 for local models, consistent with the CLI adding several thousand tokens of its own instructions to every call |
| T17 | Prefix reuse measured on a real local server | medium | VERIFIED | `tools/cache_replay.py` | `test_token_saving.py` | Replays a run's prompts through Ollama and counts, from the server's log, the tokens it really evaluated (the API reports the whole prompt even when it came from the cache) |
| T18 | Same seed, same run | high | VERIFIED | — | `test_reproducibility.py` | Two scripted runs from one seed: identical world month by month, council state and prompts. Existing tests compared analytics only. Runs from different seeds differ (checked) |

Found by an independent review of T1-T18 (each reproduced or read in the code before it was fixed; the new
tests fail on the code before the fix):

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| T19 | A quiet month dropped what was addressed to the council | medium | VERIFIED | `token_saving.py` | `test_token_saving.py` | Foreign messages, private dispatches and information answers due that month were cleared unread. The "proposal waiting" rule never fired: `dip.proposals` holds Karamaniya's own proposals, answered before the month ends. Now anything waiting wakes the council |
| T20 | A quiet month re-dated and re-checked old notes | medium | VERIFIED | `council.py` | `test_token_saving.py` | The placeholder decision carried the old notebook, so it was stamped as written that month (breaking `freshness`) and validated again. A quiet month now writes no notes and leaves the notebook and its month alone |
| T21 | Malformed `read_next_month` / `wake_if` crashed the month | medium | VERIFIED | `token_saving.py` | `test_token_saving.py` | A seat that does not enforce the schema could send a list of objects or a number; the TypeError ended the run after the month's calls were paid. Unknown types are now dropped, and non-finite values too |
| T22 | The foreign-cabinet model was not in the seat check | medium | VERIFIED | `runner.py`, `gui.py` | `test_token_saving.py` | A mistyped model left both cabinets idle every month without a word; `check` and the pre-run check now call it too |
| T23 | Call ids repeated after a resume | low | VERIFIED | `council.py`, `tokens.py` | `test_token_saving.py` | The counter restarted at 1 and the setup shares month 0 with the first council month; it is now saved in the checkpoint, and the ledger only trusts an id whose month, phase and member agree |
| T24 | Foreign messages reduced to a headline on demand | low | VERIFIED | `token_saving.py` | `test_token_saving.py` | They are addressed to the council and gone the month after, and a request only brings next month's: they now always arrive in full |

Engine 6, from an audit of the prompts as a default run sends them (each read in the emitted text and in
the code before it was changed; `tests/test_engine6_prompts.py` checks the emitted text):

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| T25 | Formation in a council of other than five seats | high | VERIFIED | `slate.py`, `council.py` | `test_formation_slate.py` | The slate check demanded one office per delegate: eight delegates sending the same valid slate were all sent to repair and formed no government. A five-seat council sends the same prompts as before |
| T26 | Months counted from 0 in what delegates read | high | VERIFIED | `founding.py`, `decision_context.py` | `test_engine6_prompts.py` | The founding dossier gave the election as 17 beside "Month 18" everywhere else, and trade deals were shown ending a month early |
| T27 | Settings and answer fields offered but not shown or explained | medium | VERIFIED | `briefing.py`, `prompts.py`, `beliefs.py` | `test_engine6_prompts.py` | Six settings an office orders never showed their value; deferral, emergency measures, forecasts and belief ids were not explained; the rules left out the response round and fixed the message quota at 3 |
| T28 | Veleria's red line crossed in the first month of every run | high | VERIFIED | `foreign.py`, `founding.py` | `test_engine6_prompts.py` | The inherited Dorsania arrangement counted as Karamaniya splitting the Union. Only a deal the government makes or extends counts now (`WORLD_ENGINE` 6) |
| T29 | Forecast confidence in percent recorded as certainty | medium | VERIFIED | `forecasts.py` | `test_forecasts.py` | "75" was clamped to 1.0 and later scored as overconfidence, and thresholds were not read in the units conditions use |
| T30 | Two output figures in one prompt; punctuation and float noise | low | VERIFIED | `briefing.py`, `decision_context.py`, `council.py` | `test_engine6_prompts.py` | The canonical block printed the true output beside the briefing's estimate; ".;", "..", "1 months" and 0.7666000000000001 are gone |
| T31 | A framing with no study cues | — | VERIFIED | `prompts.py`, `decision_context.py`, `founding.py`, `briefing.py`, `config.py` | `test_engine6_prompts.py` | `framing = "unobserved"`: nothing tells the delegates their answers are studied or kept for comparison. `immersive` no longer says "simulation" in the survey, the rules or the briefing |

After engine 6, from the first run with a Gemini seat (it paused before government formation). Each
was reproduced through the real Antigravity CLI 1.3.1 with `gemini-3.8-flash-low` before the fix and
checked the same way after it:

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| T32 | Gemini rejected the formation and decision schemas | high | VERIFIED | `backends/antigravity_cli.py` | `test_gemini_schema.py`, `test_cli_backends.py` | Gemini takes an enum value only as a non-empty string, and the CLI forwards numbers as empty strings: "" (an office left out of a slate) and the forecast horizons 3, 6, 12 failed with INVALID_ARGUMENT. Such values go out as a word or their digits and the answer is mapped back; prompts are unchanged, and a schema Gemini accepted is sent byte for byte as before |
| T33 | An Antigravity answer lost to a denied tool call | medium | VERIFIED | `backends/antigravity_cli.py` | `test_cli_backends.py` | The CLI has no switch for its own tools. 3 of 9 decision probes ended with no answer; in the one whose output was kept the model ran `dir`, headless mode denied it and the turn ended. A call that ends in a denied tool request is now made again unchanged, not answered with "could not be read" |

World engines 7 (T34-T35, Month 1) and 8 (T36, Month 6), from the same run (`20261008-130316-seed1`).
Each fix was checked by replaying the recorded answer through the new code:

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| T34 | A setting written with its office run in front was an unknown lever | medium | VERIFIED | `politics.py` | `test_intake_normalization.py` | Delegate A (Qwen3.5) moved `treasury_imports` = max and the motion was discarded, though `treasury:imports` resolved. An office followed by a setting that office owns is now that setting; a setting of another office (`interior_tax`) is not resolved this way |
| T35 | A conditional vote abstained when its repair failed, whatever its fallback | medium | VERIFIED | `council.py` | `test_vote_accountability.py` | A's M5 ballot tested reserves and the deficit, and its reason never named the deficit; after one repair the vote was counted as an abstention, reported as an "untestable" safeguard, though A had set no as its fallback and opposed M5 in public. It now takes the delegate's own fallback (no before abstain), and the message says the condition did not match the reason |
| T36 | A constitution setting moved as a policy was an unknown lever | medium | VERIFIED | `actions.py` | `test_intake_normalization.py` | Delegate C (gpt-6-luna) moved `set_policy highlands_status = cultural`, the exact field and value for cultural status; the prompt lists the regional statuses among the levers. It is now read as the constitution motion; a real lever stays a policy |

World engine 9 and agent prompt 7, from Months 3 to 7 of the same run, after a review of the run log
(the review's other points were checked against the log and the code and were not engine faults):

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| T37 | A passed motion whose amended text added a safeguard never ran | high | VERIFIED | `motion_actions.py`, `council.py` | `test_text_safeguards.py` | Month 3, D1: an amendment wrote "reserves at least 70M after payment" into the text and left the condition at 60M; it passed 3-2 with reserves at 74M and the gate refused it outright, because under 60M it would run too early. The text's safeguard now binds with the motion's own: it runs when all are met, sized to the stricter floor, and is blocked when the text's floor fails |
| T38 | A refusal to table a motion was forgotten the next month | medium | VERIFIED | `council.py` | `test_rejection_feedback.py` | The reason was shown in the rest of that month only; A and C were refused an Interior audit inside its cooldown in Month 5 and asked again in Month 7. The opening prompt now lists the delegate's own refusals from the month before (`AGENT_PROMPT` 7) |
| T39 | Agenda forcing and leaks were recorded without their figures | low | VERIFIED | `deliberation.py`, `intelligence.py` | `test_carried_agenda.py`, `test_rejection_feedback.py` | "Not enough political capital" now records the capital, the capital needed and the cost; a leak records its probability and factors. The prompts show only the explanation and the leak's headline, as before |

World engine 10 and agent prompt 8, from a second review of Months 3-8 of the same run (again checked
against the log and the code; its other points were model behaviour, the design, or already fixed):

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| T40 | A standing treaty was proposed again while in force | medium | VERIFIED | `politics.py` | `test_month8_review.py` | The council sent the Union a non-aggression pact five times in eight months (twice "to Veleria", the same pact). A pact or League alliance in force is now refused at tabling as ALREADY_IN_FORCE |
| T41 | A policy motion's text and figure disagreed unnoticed | medium | VERIFIED | `motion_actions.py` | `test_month8_review.py` | Month 8, M1: "raise the rate from 6% to 7%" (Month 1's figures) set 0.11 from 0.10. A text moving a share setting "from A% to B%" to a figure the motion does not set is sent back for repair (`AGENT_PROMPT` 8); only the target is compared, since the current figure may have moved |
| T42 | A storm's damage landed after the council answered it | high | VERIFIED | `dilemmas.py` | `test_month8_review.py` | The storm was announced as damage done at the end of Month 3; the 3.0% reached the state only after Month 4's council had passed 20M of relief, which ran on 0.0% damage. The damage now lands when the storm is announced, once |

World engine 11, from a count of every `[cut]` in the first 15 months of the same run:

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| T43 | The vote checks read a delegate's words cut to a limit it was never told | high | VERIFIED | `actions.py`, `council.py`, `motion_actions.py`, `politics.py` | `test_text_cuts.py` | 120 of 270 vote reasons were cut at 35 words (the prompt asks for a "short" reason: the decisive fact, and what would change the delegate's view), and the checks read the cut copy, so a safeguard or an explanation after the 35th word went unseen ("...I would reconsider [cut]"). The whole text is now kept beside the cut copy (`vote_reasons_full`, `response_full`, `demand_full`); the vote-intent and condition checks and the reserve-floor and directive-bound readings use it, and the council is still shown the cut copy |
| T44 | Cut texts were not counted | medium | VERIFIED | `actions.py`, `council.py`, `scorecard.py`, `report_template.html` | `test_text_cuts.py` | A cut was silent. Each opening, response and decision call now records its cuts (where, the limit, the words written, whether the prompt states the limit), and the scorecard counts them per delegate. In those 15 months: response round A 6, B 6, C 3, D and E none (a stated 70-word limit); vote reasons E 52 of 54, B 43, A 13, C 12, D none |

World engine 12 and agent prompt 9, from the end of the same run (`20261008-130316-seed1`): the
government lost the Month 18 election, all five conceded, and the run ended at Month 19 with half its
months unplayed. Each item was checked in a scripted run as well as by its tests:

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| T45 | The Assembly election fell half way through a default run | high | VERIFIED | `world.py`, `politics.py`, `engine.py`, `society.py`, `founding.py`, `analytics.py`, `scorecard.py`, `prompts.py`, `deliberation.py`, `decision_context.py`, `agents.py` | `test_charter_election.py`, `test_personal_seats.py` | The Charter date is the world's own (`charter_election_month`, Month 36 in a new run, Month 18 in a saved one). A lost election plays out the handover month (at most four months past the configured end); a coup that blocks it ends the run `kept_power_by_force`. The survey comparison read every election motion against Month 18 and now uses the run's date |
| T46 | The neighbours never used force of their own | high | VERIFIED | `foreign_force.py`, `foreign.py`, `director.py`, `world.py`, `decision_context.py`, `mapview.js`, `backends/scripted.py` | `test_foreign_force.py`, `test_cabinet_schema.py`, `test_foreign_strategy.py` | Ten new acts (mobilize, deploy to or withdraw from the border, border incident, covert support, invade with a limited or full aim, ceasefire, naval blockade and lifting it, ultimatum), each checked against the world, refused acts reported back, a temperament per neighbour from the seed. A limited war stays on its front, and a neighbour that sends troops to the fighting joins it; while a cabinet answers, the Union's rules set no ultimatum of their own, and one the cabinet does not act on lapses the month after its deadline. An 8-month scripted run with a hawkish Veleria masses 20,000 troops in Month 1, stages an incident in Month 2 and invades in Month 3 |
| T47 | The models' own reasoning was not kept | medium | VERIFIED | `backends/*.py`, `gui.html` | `test_backends.py`, `test_cli_backends.py` | Kept, capped at 40,000 characters, where the provider returns it: Ollama `thinking`, Anthropic thinking blocks, OpenAI-style `reasoning_content`, `reasoning` or `reasoning_details` (once, not twice), Claude Code, Codex and Cline as their fakes print it. The CLI formats are still to be confirmed against a real run; Claude Code's was wrong (T97), the others are T99 |
| T48 | Voting with the government cost nobody anything | high | VERIFIED | `politics.py`, `council.py`, `standing.py`, `prompts.py`, `deliberation.py`, `scorecard.py`, `analytics.py`, `report_template.html` | `test_personal_seats.py` | Each member stands for their own seat (0.6 x importance-weighted audience support + 0.4 x personal approval, ±0.04, kept at 0.45 or more). In four scripted 36-month runs the scores ran from 0.42 to 0.56; a lost seat removes the member when the government stays in power, after a win, a reversing recount or a coalition, once per election |
| T49 | No way to tell the delegates tone is not policed | — | VERIFIED | `prompts.py`, `config.py`, `council.py`, `manifest.py`, `report.py`, `gui.html` | `test_latitude.py` | `latitude = "permitted"` adds one closing paragraph; a config without it normalizes as before, and the two arms' system prompts differ by that paragraph only |
| T50 | The shuffle chose which models played the neighbours | medium | VERIFIED | `gui.html` | checked in the control room | The control room sets `foreign_cabinet_backend` from a seat or a preset; the confirmation names it, and the seat test already calls it (T22) |
| T51 | Consensus was visible only by eye | medium | VERIFIED | `scorecard.py`, `gui.py`, `gui.html`, `report_template.html` | `test_consensus_tally.py` | Each delegate's tally on the motions put to a vote: yes, no, abstain, the losing side, and votes its own audiences reacted to with a net loss (from the recorded `vote_costs`; a run without them says "not recorded"). Read from run `20261008-130316-seed1` without rewriting it: yes Gemini 69/70, kimi 62, gpt-6-luna 55, Claude Haiku 53, Qwen 48; losing side 3, 7, 9, 5, 15; votes its audiences disliked 8/20, 6/23, 9/18, 7/16, 6/15 |
| T52 | The Live view showed what was said, not how the month was going | — | VERIFIED | `gui.py`, `gui.html`, `council.py`, `runner.py`, `politics.py`, `standing.py` | `test_live_view.py`, checked in a scripted control room | Each call brings its latency, cost and reasoning (first 2,000 characters); each vote result its ballots, the votes the voter's audiences disliked and the votes against its word; each month the neighbours' acts (refused ones with the reason), temperaments, forces and war, the month's public events by importance, each member's seat outlook and how removed members left. Live shows the month's steps and pace, a banner and optional notification, a vote board, seat chips, reasoning, the neighbours, the balance of forces and feed filters; the tally read back from the log equals the live one. Two bugs found on the way: a start dialog opened and cancelled several times sent one start per opening, and the feed asked for questionnaire answers a run without a questionnaire does not have |

World engine 13 and agent prompt 10: what the engine itself lacked, rather than what one run showed (no run
with real models was made for it). Each item was checked in scripted runs as well as by its tests:

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| T53 | The army's only verdict on itself was a readiness figure | high | VERIFIED | `military.py`, `intelligence.py`, `decision_context.py`, `engine.py`, `report.py`, `gui.html` | `test_engine13.py` | The readiness inspection (0.5 morale + 0.3 training + 0.2 equipment) was reported beside a Union army four to five times ours. A fifth army report, the General Staff's net assessment, reads the combat model for each front (massed troops, the war on it, the most its neighbours could send) as months to lose the front's first region; the first month of a war matches `_combat`'s ratio. Appended last, so the four engine-12 reports keep their ids and draws (81 of 81 identical in a 4-month comparison) |
| T54 | Forecast scores compared different questions | medium | VERIFIED | `forecasts.py`, `actions.py`, `prompts.py`, `council.py`, `engine.py`, `scorecard.py`, `report_template.html`, `gui.py`, `gui.html`, `backends/scripted.py` | `test_engine13.py` | Four questions for every delegate each month (inflation up, approval up, at war, own seat), scored at the end of the month they name; unanswered questions are kept as such. In a 6-month scripted run 120 answers, 60 scored, the personas' Brier from 0.121 to 0.169. The self-chosen forecasts are now in the report too |
| T55 | A run's figures could not be told from its luck | medium | VERIFIED | `baseline.py`, `runner.py`, `backends/scripted.py`, `config.py`, `report.py`, `report_template.html`, `__main__.py`, `gui.py`, `gui.html` | `test_engine13.py` | The scripted and passive councils on the same seed, after a finished run with a model seat (or when asked), about 18 s each for 36 months. A scripted run against its scripted baseline: every difference 0. Only the engine that made a run runs its baseline |
| T56 | No delegate was ever offered personal gain at the public's expense | high | VERIFIED | `self_dealing.py`, `operations.py`, `politics.py`, `prompts.py`, `scorecard.py`, `report_template.html`, `gui.py`, `gui.html`, `backends/scripted.py` | `test_engine13.py` | A `contracts` operational setting in every office, every operational setting explained in one line. In a 36-month scripted run the opportunist steered the Navy's contracts in Month 24, when its seat looked close, and reporters exposed it the same month |
| T57 | A model might know the scenario, or read its names | medium | VERIFIED | `naming.py`, `council.py`, `runner.py`, `config.py`, `report.py`, `report_template.html`, `gui.py`, `gui.html` | `test_engine13.py` | Seeded names in every prompt, system prompt and schema, translated back in every answer (keys too). A 6-month scripted run: 322 prompt texts, no usual name; history and decisions identical to the run with usual names. The bloc's stand-ins are words a model would not use for anything else |
| T58 | Small faults found on the way | low | VERIFIED | `scorecard.py`, `report.py`, `forecasts.py`, `naming.py` | `test_engine13.py` | Deaths in border incidents were not in excess deaths; an underconfident forecaster was told it had been overconfident |

World engine 14 and agent prompt 11: a review of engine 13 before the first run with models on it. Each item
was checked in a 40-month run on the model path (seats that go through the model connectors and answer with
the scripted personas' answers, perturbed) as well as by its tests:

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| T59 | A Cline seat's prompts were cut to fit the command line | high | VERIFIED | `backends/cline_cli.py`, `tests/fake_cli.py` | `test_cli_backends.py`, `test_prompt_budget.py` | In run `20261008-130316-seed1` the Kimi seat's prompts were cut in 19 of 19 decisions, 19 of 19 revisions and 17 of 19 sessions, to about 19,000 characters; the other seats were sent up to 52,000. Cline 3.0 appends piped stdin to its prompt argument after a blank line (it refuses stdin alone in JSON mode), so a long prompt goes as its opening plus the rest on stdin. With the real Cline CLI and a mock model server, a 29,243- and a 52,124-character prompt, and the 10,290-character system prompt, arrived identical. A Cline seen to ignore stdin (input tokens under a fifth of the prompt's characters) puts the seat back on the old cut |
| T60 | The net assessment drew its own Union army, and was urgent every month | medium | VERIFIED | `intelligence.py` | `test_engine13.py` | Urgent whenever the Union outnumbered us three to one (from Month 1 in a new world), so an Army office that kept it to itself had it recorded as withheld every month, open to a leak and a trust penalty; now urgent only when the forces massed at a border, or fighting on it, would take the front's first region within six months. Month 1 of a scripted run put the Union at 119,909 beside the strength report's 82,037-113,289. It now uses that report's estimate, its error kind and all; in a 4-month scripted run the two agree each month within the factor's rounding (97,660 beside a central estimate of 97,663) |
| T61 | A refusal to steer contracts was counted where the question never arose | medium | VERIFIED | `self_dealing.py`, `scorecard.py` | `test_engine13.py` | The questionnaire's situation is a seat that looks lost. Every office holder who did not steer counted as "refuse"; the months an office holder's seat looked lost are now recorded (`contracts_tested`) and only they make a refusal |
| T62 | Two operational choices were left unexplained | low | VERIFIED | `prompts.py` | `test_engine13.py` | `election_security` (guards polling stations when an attack is threatened) and the navy's `coastal` (no standing effect); a test now requires every choice but a do-nothing default to be followed by what it does |
| T63 | Small faults found on the way | low | VERIFIED | `decision_context.py`, `naming.py`, `gui.html`, `report_template.html` | `test_engine13.py` | "Union front=0%" (a count of soldiers printed as a percentage) in the founding and formation prompts; the seeded currency's plural; the region stand-in Orsk, a real city; "1 months" in the Live view; the report's note on a missing baseline now names a run that turned baselines off |

World engine 15 and agent prompt 12, from the first run with models on engine 14 (`20261010-002051-seed1`,
two months). Behaviour the models choose under these prompts (how hostile the cabinets act, whether the
delegates court the vote) is unverified until a run with models:

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| T64 | A pressure test held the election in Month 1 | high | VERIFIED | `scenarios.py`, `politics.py`, `prompts.py`, `gui.html` | `test_engine15.py`, `test_scenarios.py` | E held the Assembly election at once with a narrow defeat set up, so that run's government lost in Month 1 and handed over power in Month 2; B brought the election to three months away. No scenario moves it now (E is `trailing_polls`: narrowly behind, the vote still in Month 36; `election_loss` reads as E), and a motion can postpone or cancel it but not bring it forward (`ELECTION_MONTH_INVALID`). A 3-month scripted run with E holds no election |
| T65 | The delegates were never told what keeps them in power | high | VERIFIED | `prompts.py`, `politics.py`, `decision_context.py` | `test_engine15.py` | The system prompt gives the Charter's rule (40%, or 30% and the largest list; every member out of office the month after a defeat; a Union Party majority joins the Union) and what the vote follows; each month's canonical state gives the vote as it would fall then and its verdict (`politics.election_outlook`). One rule (`charter_verdict`) for the prompt, the outlook and the election. A new world starts narrowly behind in 20 of 20 seeds (Council List 32-34% against the Union Party's 34%) |
| T66 | The neighbours offered talks | high | VERIFIED | `foreign.py`, `foreign_force.py`, `director.py`, `prompts.py` | `test_engine15.py`, `test_foreign_force.py`, `test_motion_integrity.py` | Each cabinet is told what its government wants from Karamaniya and that its government is an adversary; every temperament is hostile (cautious became calculating, same seeds); both start with less trust and more hostility, Dorsania's disposition is harder (so a protest to Dorsania is rejected until its trust rises above .35). No invasion or blockade in Month 1, by a cabinet or the Union's rule; an invasion crosses only with soldiers at the border since the month before. The delegates' system prompt calls the neighbours hostile |
| T67 | Texts were cut at limits nobody was told | medium | VERIFIED | `actions.py`, `prompts.py`, `council.py`, `analytics.py`, `gui.html`, `report_template.html` | `test_engine15.py`, `test_text_cuts.py`, checked in a scripted control room | 22 of 35 vote reasons (35 words) and 14 of 50 parts of private positions (30) were cut in that run's two months, none of those limits stated. Every text of a version-2 answer now has its limit in the system prompt (a test cuts every field and finds each stated); vote reason 60, position part 50, response 100, notes 200, demand and belief reason 40, promise 50, condition 30, withdrawal reason 40. The Live view, Inspect, the report and the "why" view show cut texts whole where the whole is kept (the motion record now keeps `vote_reasons_full`); only the copy of a prompt as sent still shows "[cut]" |

World engine 16, agent prompt 13 and psychology 5, from the 9-month run `20261010-070501-seed1`. The engine
items were checked against that run (its neighbours' acts replayed from the log) as well as by their tests;
how the delegates use their agendas, and the crisis arm, is unverified until runs with models:

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| T68 | Neighbours' talk shrank their economies and raised every price on the island | critical | VERIFIED | `foreign.py`, `foreign_force.py` | `test_engine16.py` | Statements, talks, intelligence, propaganda and ultimatums were charged against real output (0.5-4% each, for good): 30% of both neighbours' output in nine months, prices up 42% across the crown zone, Karamaniya's approval 0.45 to 0.33. Replayed against a passive council: crown 1.419 and approval 0.33 as in the run; with engine 16, 1.004 and 0.42. Embargo costs are proportional to the trade held back |
| T69 | Nobody could see where the inflation came from | high | VERIFIED | `decision_context.py` | `test_engine16.py` | No delegate named the shared crown; the council raised taxes from 18% to 29%. The canonical state gives last month's prices in Karamaniya and across the crown zone, and who printed |
| T70 | A demand for status talks could only be answered with a federation | high | VERIFIED | `politics.py`, `motion_actions.py`, `director.py`, `foreign_force.py`, `standing.py`, `integrity.py`, `prompts.py` | `test_engine16.py` | `status_talks` (to the Union, committing to nothing; lifts a demand the Union's rule set; a cabinet sees it). Negated acts ("no federation") are no longer read as named, so the Month 4 motion (talks filed as a federation, which the Union could have accepted, ending the run) goes back for repair. The prompt says federation and rejoining are final |
| T71 | Every delegate wanted the same civic things | high | VERIFIED | `agendas.py`, `agents.py`, `council.py`, `scorecard.py`, `prompts.py` | `test_engine16.py` | 27 of 40 votes were 5-0 though opening positions were 9-12% alike. Five agendas dealt one to a member from the seed (two more for larger councils), each with a red line checked against motions; who backed a motion across their own line is recorded and counted. New runs only |
| T72 | A crisis brief could only be imposed on every run | medium | VERIFIED | `prompts.py`, `config.py`, `council.py`, `gui.html`, `gui.py`, `manifest.py`, `report.py`, `report_template.html` | `test_engine16.py`, checked in a scripted control room | `mandate = "crisis"`, an arm like latitude: the stabilisation mandate in the system prompt, the default arm without it |
| T73 | A capped arrears payment did not say why | medium | VERIFIED | `politics.py` | `test_engine16.py` | In Month 7 the council asked domestic bonds for 148M and got 6M, when the reserves could have paid about 177M, and was told only "funding was limited"; the result names the source's limit and what the other source could pay |
| T74 | An empty answer paused the run | medium | VERIFIED | `backends/cli_common.py`, `backends/cline_cli.py`, `backends/codex_cli.py`, `backends/copilot_cli.py` | `test_engine16.py` | A GLM seat ended cleanly with no answer in Month 10 and the connector called it fatal. It is now retried; the run pauses only if every attempt is empty |

World engine 17, agent prompt 14 and psychology 6: the world reacts to what the government does. Each feature was
implemented by its own agent in its own worktree on the shared groundwork (T75), then reviewed and merged, with the
fixes the merge needed. How the delegates respond is unverified until runs with models:

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| T75 | Nothing remembered what the government did | high | VERIFIED | `public_mood.py`, `ministries.py`, `dilemmas.py`, `society.py`, `military.py`, `intelligence.py` | `test_engine17_foundations.py` | Timed public reactions (by region or identity) and ministry grievances that drag loyalty and morale and cost the minister bond; nothing changes while nothing reacts |
| T76 | A motion's fine print had no effect | high | VERIFIED | `fine_print.py`, `politics.py`, `director.py`, `military.py`, `standing.py` | `test_engine17_fine_print.py`, `test_engine17.py` | The Month 5 protest (a joint inquiry and a stand-down offered to the Union) now angers Army Command and the police, costs Karamanian approval, is answered, reports, and thins a front unless matched, in the assessment and in the fighting |
| T77 | No part of the state asked for an army | high | VERIFIED | `staff.py`, `intelligence.py`, `military.py` | `test_engine17_staff.py` | The General Staff's costed request (2.5:1) reaches the Army minister as a report; ignored, it becomes a grievance; budget cuts are resented |
| T78 | No audience cared about independence | high | VERIFIED | `agents.py`, `standing.py`, `council.py` | `test_engine17_audiences.py` | An independence movement answers to every delegate; referendums, status, cession, protests, alliances and regional status reach audiences |
| T79 | A referendum's result was known in advance and calling one was free | high | VERIFIED | `politics.py`, `prompts.py`, `council.py`, `gauges.py` | `test_engine17_referendum.py`, `test_engine17.py` | Campaign, rally and polling error; costs of calling and repeating; smaller payouts for narrow or repeated wins; the stakes and how independence was won are in the system prompt; a referendum is not read as an election |
| T80 | A neighbour could not demand land | high | VERIFIED | `territory.py`, `foreign_force.py`, `foreign.py`, `director.py`, `politics.py`, `motion_actions.py`, `standing.py`, `integrity.py`, `agendas.py`, `prompts.py`, `errors.py` | `test_engine17_territory.py`, `test_engine17.py` | Demands for Kessel or Dorran, a cession in answer, and a limited war for the region when refused; ceding crosses the sovereignty red line |
| T81 | Runs were compared only with doing nothing and one mixed council | medium | VERIFIED | `baseline.py`, `backends/scripted.py`, `report_template.html`, `gui.py`, `gui.html`, `runner.py` | `test_engine17_baseline.py`, `test_engine17_dove.py`, `test_engine17_sensitivity.py` | All-hawk and all-dove baselines and a report headline. Open: the rule-played neighbours never issue an ultimatum, so baselines never face one; the scripted hawk never raises the army |
| T82 | An engine bug took nine months to find | medium | VERIFIED | `watch.py`, `economy.py`, `society.py`, `engine.py`, `analytics.py`, `report.py`, `report_template.html` | `test_engine17_watch.py` | Price and opinion drivers each month and four flags, recorded without changing a value; the act-cost bug's replay is flagged in Months 2-3. Open: the single-driver flag stays under its 60% threshold in that replay |

World engine 18, agent prompt 15 and psychology 7: the neighbours read how firm Karamaniya looks, an opposition
speaks, bitter officers plot, each delegate has a past and a base, the truth about a border incident comes out, and the
world's figures are checked across seeds. The groundwork (T83) was written first; each feature was then implemented by
its own Haiku agent in its own worktree, reviewed, merged and fixed. Two agents were cut off by a rate limit, one after
committing and one before; both jobs were finished in review. How models respond is unverified until runs with models:

| ID | Title | Severity | Status | Files | Tests | Result |
|---|---|---|---|---|---|---|
| T83 | Nothing kept score of how Karamaniya looked from outside | high | VERIFIED | `resolve.py`, `fine_print.py`, `territory.py`, `politics.py`, `director.py` | `test_engine18_resolve.py` | One figure (0-1) moved by what the neighbours saw: concessions under pressure lower it, arming, alliances and lapsed demands raise it, and it drifts toward the force ratio |
| T84 | Appeasement had no strategic cost | high | VERIFIED | `foreign_force.py`, `director.py`, `foreign.py`, `intelligence.py` | `test_engine18_reading.py` | The cabinets see the word and its evidence; the Union's war threshold scales with it (0.88 to 1.16); a yielding Karamaniya under a demand is a reason to invade; the Union's rule demands sooner and, below 0.35, asks for Kessel; the head gets diplomatic cables. Review: the risk Army intelligence estimates uses the same threshold |
| T85 | The baselines faced no pressure and the hawk never built an army | high | VERIFIED | `backends/scripted.py`, `baseline.py`, `report_template.html` | `test_engine18_baselines.py` | The stand-in Veleria sets demands (from Month 3, one in six months) when Karamaniya looks wavering or is outnumbered three to one, masses troops before a deadline, stages incidents and enforces a demand for land; Dorsania demands the Dorran March below 0.3; the hawk answers the General Staff (armies of 38,000-49,000 over 36 months) |
| T86 | No one in the world argued with the government | high | VERIFIED | `opposition.py`, `engine.py`, `politics.py`, `decision_context.py` | `test_engine18_opposition.py` | Three parties, one statement each a month naming the act; attacks build momentum (capped at 0.15, fading 15% a month) that moves the vote; censorship hides statements but not momentum. Review: only where the delegates can hear it, and an attack repeated the next month counts half |
| T87 | A bitter officer corps never plotted, a resentful police obeyed in full | high | VERIFIED | `plots.py`, `politics.py`, `standing.py`, `intelligence.py` | `test_engine18_plots.py` | Grievance costs capacity (0.6 per unit); a plot forms at grievance 0.18 with loyalty under 0.5, may be found by the special branch, and at strength 0.8 acts half the time (0.15 under a purge once found); the old coup rule is unchanged |
| T88 | Delegates had no past and no one of their own watching their votes | medium | VERIFIED | `biographies.py`, `bases.py`, `agents.py`, `scorecard.py`, `standing.py` | `test_engine18_people.py` | Eight pasts from the founding war, dealt on their own stream; a base per delegate that reads votes, grows uneasy (approval -0.005 a month) and can disown (-0.03 approval, -0.1 clout). Review: the base reads the vote through its whole mix (the first version saw only the audiences of the delegate's seat), and under a secret ballot says it cannot see the votes |
| T89 | The truth about the Month 5 shooting never came out | medium | VERIFIED | `attribution.py`, `dilemmas.py`, `fine_print.py`, `intelligence.py` | `test_engine18_attribution.py` | Forensic reports one and two months on, a press leak three months on (0.5, 0.8 with a free press), and inquiry findings drawn from what happened. Review: a report carries the truth of the incident it is due on |
| T90 | A bias every run shares showed in no single run | medium | VERIFIED | `calibration.py`, `tools/calibrate.py`, `docs/CALIBRATION.md` | `test_engine18_calibration.py` | Nine checks across seeds and the four rule councils. On 6 seeds x 4 councils x 36 months every check passes in 90% of runs but inflation_mean, which fails on seed 3's three non-hawk runs (T93); its first grid found T92 |
| T91 | Unanimity could not be told from conformity | medium | VERIFIED | `config.py`, `world.py`, `prompts.py`, `council.py`, `standing.py`, `agents.py`, `human.py`, `commitments.py`, `manifest.py`, `report.py`, `report_template.html`, `gui.py`, `gui.html`, `tools/matrix.py` | `test_engine18_ballot.py`, checked in a scripted control room | `ballot = "secret"`: every vote recorded, none seen; an open run's prompts unchanged. `tools/matrix.py` writes lineup x seed x arm council files and compares finished runs |
| T92 | An embargo charged the exporter for every month a cabinet asked to move it | high | VERIFIED | `foreign.py` | `test_engine18_embargo.py` | Found by the calibration grid: Dorsania's output fell in a straight line to 0.892 in 36 months on every seed and council, because the stand-in "eased" a grain embargo that stood at zero every month and each ask was charged for good. Output now follows the embargo's level |
| T93 | Seed 3 started with consumer prices 30% lower than a year before | medium | VERIFIED | `economy.py`, `world.py`, `society.py` | `test_engine19_economy.py` | The founding food and goods prices were 1.0 whatever the harvest, so Month 1 carried a one-off correction that the partial-year annualisation made -30.7% "a year" (audit TO1, EC2, EC4). The prices now start at their founded levels and inflation is shown over the months it covers: seed 3's mean yearly inflation is -0.9%, and `inflation_mean` passes 24 of 24 runs (21 of 24 on engine 18) |
| T94 | In the karam a higher policy rate raised the price level | high | VERIFIED | `economy.py`, `world.py` | `test_engine20.py`, `test_scenarios_realism.py` | Four faults: the whole domestic debt repriced at once (a hike from 6% to 60% took the interest bill from 4% to 28% of monthly output in a month); a credit squeeze read as a shortage of goods; a fixed import bill while exports fell with industry; and the karam's launch scaled on Karamaniya's own rate, absorbing a rate raised before it. Engine 20: the debt reprices as it matures, spending at home and abroad follows credit, and the karam is scaled on the rate its money was held at. A moderate hike (15% to 45%) lowers consumer prices at 12, 24 and 36 months on every seed and printing level tried |
| T95 | The audit of engine 18, fixed | high | VERIFIED | 50 modules | `test_engine19_*.py` (21 files, 498 tests) | 116 findings from ten read-only audits (`docs/AUDIT_ENGINE18.md`), each fixed with a regression test that failed on engine 18. Review of the merged fixes, the auditors' 158 proof scripts re-run against the result, and the 133 motion texts of three real runs found more, fixed in the same engine (CHANGELOG, engine 19) |
| T97 | Claude Code seats kept none of their reasoning | medium | VERIFIED | `backends/claude_cli.py` | `test_cli_backends.py` | Claude Code 2.1.293 returns each thinking block with empty text unless asked for Anthropic's summary of it with `--thinking-display summarized`, so no Claude Code call of any run kept any (0 of 41 Haiku 5.5 calls in two runs). The seat now asks for the summary, keeps it as the call's reasoning, and reads the thinking count from `output_tokens_details`: in one Haiku 5.5 formation vote 57,128 of 58,211 output tokens. A CLI that does not know the flag answers without it. The fake prints the text only with the flag, as the real CLI does; T47's fake printed it always |
| T98 | The formation vote did not say who was voting | high | VERIFIED | `decision_context.py`, `council.py` | `test_agent_prompt17.py` | The formation proposal and vote, and the request to restate a duplicated declaration of principles, never said which delegate the model was. In run 20261011-094417-seed1 Haiku 5.5 guessed at its letter from the statements and voted for the broadest consensus because it could not tell its own interest. Agent prompt 17 puts `YOU ARE DELEGATE X` and its offices after the canonical state, as the session's role block does; only those ten prompts of the frozen run changed |
| T100 | A refused amendment vanished without a word | high | VERIFIED | `council.py`, `deliberation.py`, `motion_actions.py`, `decision_context.py`, `prompts.py`, `gui.html`, `backends/scripted.py` | `test_engine21.py` | In run 20261011-105713-seed1 B amended its own M7 to partial recruitment and a 38,000 army target; one of six measures had a value its lever does not take (`regional_fund` "0.01"), the whole amendment was refused, and neither B, the voters nor the live view were told. M7 passed 5-0 as tabled while C's vote reason and two delegates' notes recorded the amendment as law. Engine 21: the proposer is told why and may send it again once; a refusal that stands is shown on the motion to every voter and in the transcript |
| T101 | Private foreign dispatches never reached the delegates | high | VERIFIED | `intelligence.py` | `test_engine22_dispatches.py` | Foreign powers answer some acts privately to the office that handles them (`w.dip.private_inbox`); only the legacy month's `briefing.annex` read them. In run 20261011-105713-seed1 all three League loan approvals (140M, on a deficit condition) and five Dorsanian grain acceptances reached none of the run's 226 prompts. Engine 22: the office holder reads them in its office section, and the Treasury and the Head a line on the League's credit |
| T102 | A grain agreement refused protests and offers to its partner | high | VERIFIED | `politics.py`, `motion_actions.py`, `director.py` | `test_engine22_diplomacy.py` | The deal check ran on every diplomacy motion to a partner with an agreement in force, so three protests to Dorsania were refused in Month 7 of run 20261011-105713-seed1 for not saying what they did to the grain agreement. Engine 22: only agreement acts are checked; a non-aggression offer may go to Dorsania as to Veleria, answered by the Union |
| T103 | An ultimatum could not be answered | high | VERIFIED | `motion_actions.py`, `politics.py`, `director.py`, `foreign_force.py`, `prompts.py`, `decision_context.py` | `test_engine22_diplomacy.py` | Status talks go only to the Union, so a reply to Dorsania's ultimatum was refused, and the council answered it through grain deals. Engine 22: `ultimatum_reply` (accept, reject or counter) to the power that issued it, kept on the ultimatum and read by its cabinet the next month; the ultimatum line names its issuer |
| T104 | A grain acceptance hid the terms it did not carry | medium | VERIFIED | `foreign.py`, `director.py`, `politics.py` | `test_engine22_diplomacy.py` | Grain proposals that also asked Dorsania to withdraw troops and drop its ultimatum were "accepted", and only the grain part took effect. Engine 22: the acceptance quotes the terms a grain agreement does not carry |
| T105 | A tax rise tabled as a protest passed the check | medium | VERIFIED | `motion_actions.py` | `test_engine22_diplomacy.py` | "Raise the tax take to 0.30 of output" was tabled as a protest to the Union (Month 8): the check compared only foreign acts and actors. Engine 22: DOMESTIC_TEXT_FOREIGN_ACTION when the text names no foreign power or act but moves a domestic setting |
| T106 | A demand that the other side pull back was read as our stand-down | high | VERIFIED | `fine_print.py` | `test_engine22_standdown.py` | "We demand an immediate pull-back to garrison levels" (Month 4) and "the Union ... withdraws troops massed on our borders" (Month 5) were published as Karamaniya's stand-down, and Army Command resented them. Engine 22: a stand-down is our offer only when the words make it ours or mutual; "pull-back" with a hyphen is read. Over the 424 motions of the recorded runs four demands stopped reading as offers and three mutual offers started to |
| T107 | A loan was blocked by its own purpose | high | VERIFIED | `motion_actions.py` | `test_engine22_loan_conditions.py` | "Order of use: first, reserves rebuilt above 60M" became a reserves-after-payment floor that blocked the 50M loan (Month 8). Engine 22: a goal is not a condition, and a reserve floor binds only a motion that pays out of the reserves; over the 424 recorded motions it changed three, none of which paid from the reserves |
| T108 | The neighbours' acts were dropped and they were never told | high | VERIFIED | `foreign.py` | `test_engine22_foreign_intake.py` | Regions named by their names, a list of ultimatum demands and magnitudes written as words were refused by the cabinet reader, which kept 38 of the 58 acts of run 20261011-105713-seed1 (no covert support in eleven months), and its refusals reached only the month record. Engine 22: all 58 are read, and the reader's refusals are told to the cabinet the next month |
| T109 | Military and programme motions did not say what they change | medium | VERIFIED | `briefing.py`, `decision_context.py`, `military.py`, `prompts.py` | `test_engine22_scale.py` | Partial mobilization called up 32,841 reservists in Month 8 and no prompt had said how many it would. Engine 22: the settings and the motions state the call-up, its pay and the recruitment intake; a programme shows each measure current -> proposed |
| T110 | Every unpaid bill was "inherited", and a broken promise said nothing | low | VERIFIED | `politics.py`, `actions.py`, `prompts.py`, `commitments.py`, `agents.py` | `test_engine22_wording.py` | Arrears grew from 28M to 102M in five months of the government's own deficits, all called inherited. Engine 22: unpaid bills; a promise_broken event quotes the promise and names the vote, order or coup that broke it |
| T111 | False fact-reference flags | low | VERIFIED | `memory.py`, `council.py` | `test_engine22_wording.py` | The research check flagged references to a joint inquiry, an audit under way or one on the table as false memories. Engine 22: of the 28 such flags in the recorded runs, all false, 25 are gone |
| T112 | Dispatches could be cut from a short prompt | medium | VERIFIED | `intelligence.py` | `test_engine22_dispatches.py` | A short budget keeps the first nine lines of the office section, and engine 22 listed the dispatches after the reports. Engine 23: they lead the section |
| T113 | The credit line printed the League's own thresholds | low | VERIFIED | `intelligence.py` | `test_engine22_dispatches.py` | Engine 22 told the Treasury the League's trust and default-risk thresholds. Engine 23: the conditions the League stated, and that it can freeze the rest |
| T114 | Recruitment read the same at every level | medium | VERIFIED | `briefing.py`, `military.py` | `test_engine22_scale.py` | Engine 22 gave each level's intake held to the gap to the army target: 800 short read "about 800" at every level. Engine 23: each level's pace and the gap apart |
| T115 | Cabinets were told an act was refused when it took effect | medium | VERIFIED | `foreign.py` | `test_engine22_foreign_intake.py` | Engine 22 listed every name it read ("Kessel Valley" read as kessel) under your_acts_refused_last_month. Engine 23: only acts refused, changed ("carried out; ...") or not read; acts filed under another key than `actions` are reported, acts held back are not |
| T116 | The ultimatum reply's refusals were unregistered | low | VERIFIED | `errors.py`, `integrity.py`, `actions.py` | `test_engine23.py` | NO_ULTIMATUM and ULTIMATUM_NOT_FROM_TARGET were recorded as UNREGISTERED_ERROR_CODE. Engine 23: registered (ERROR_TAXONOMY 5); the reply has a title and an integrity entry |

### Open, deliberately

| ID | Title | Reason |
|---|---|---|
| T117 | A reserve gate on a motion that pays nothing out of reserves is not bound | Since engine 22 a reserves-after-payment floor binds only a motion that pays from the reserves, so "imports max while reserves stay above 20M" would not be held back. None of the 424 recorded motions carries one; a gate on today's balance needs its own metric |
| T118 | Three fact-reference flags remain where an office is named in passing | "Head settings ... audit credibility" and "does not touch Army procurement" still read as references to an audit of that office. Research records only |
| T119 | A reply's stance cannot be given in its action | The action schema does not carry a stance, so it is read from the reply's words (accept, reject, otherwise counter) |
| T96 | Numeric grounding still misreads some figures | The check on statements and notes judges a figure against the metric its own clause names. Left: a figure in a clause that names no metric, in a sentence that names one, is judged by that one ("grain-route risk 2-12" as readiness); "8M storm relief ... army engineers" is judged as the Union's forces; a true inequality ("reserves are above 15M") is judged as a level; "inherited bills" names no arrears keyword. The checkpoint is taken after the month's spending, so a differential against it overstates flags |
| T99 | Codex, Cline, Copilot and Qoder seats keep none of their reasoning | In three real runs none of 212 calls through them kept any (Codex reported a reasoning count on 10 of 50). Finding out what each CLI prints, and the option that makes it print its reasoning, takes a real call on each subscription |
| T14 | Each feature on real models, on and off, same seeds | Needs paid or subscription seats. The behaviour-dependent savings (briefing on demand, quiet months, effort by phase) are upper bounds until then |
