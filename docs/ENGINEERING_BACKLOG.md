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
| T47 | The models' own reasoning was not kept | medium | VERIFIED | `backends/*.py`, `gui.html` | `test_backends.py`, `test_cli_backends.py` | Kept, capped at 40,000 characters, where the provider returns it: Ollama `thinking`, Anthropic thinking blocks, OpenAI-style `reasoning_content`, `reasoning` or `reasoning_details` (once, not twice), Claude Code, Codex and Cline as their fakes print it. The CLI formats are still to be confirmed against a real run |
| T48 | Voting with the government cost nobody anything | high | VERIFIED | `politics.py`, `council.py`, `standing.py`, `prompts.py`, `deliberation.py`, `scorecard.py`, `analytics.py`, `report_template.html` | `test_personal_seats.py` | Each member stands for their own seat (0.6 x importance-weighted audience support + 0.4 x personal approval, ±0.04, kept at 0.45 or more). In four scripted 36-month runs the scores ran from 0.42 to 0.56; a lost seat removes the member when the government stays in power, after a win, a reversing recount or a coalition, once per election |
| T49 | No way to tell the delegates tone is not policed | — | VERIFIED | `prompts.py`, `config.py`, `council.py`, `manifest.py`, `report.py`, `gui.html` | `test_latitude.py` | `latitude = "permitted"` adds one closing paragraph; a config without it normalizes as before, and the two arms' system prompts differ by that paragraph only |
| T50 | The shuffle chose which models played the neighbours | medium | VERIFIED | `gui.html` | checked in the control room | The control room sets `foreign_cabinet_backend` from a seat or a preset; the confirmation names it, and the seat test already calls it (T22) |
| T51 | Consensus was visible only by eye | medium | VERIFIED | `scorecard.py`, `gui.py`, `gui.html`, `report_template.html` | `test_consensus_tally.py` | Each delegate's tally on the motions put to a vote: yes, no, abstain, the losing side, and votes its own audiences reacted to with a net loss (from the recorded `vote_costs`; a run without them says "not recorded"). Read from run `20261008-130316-seed1` without rewriting it: yes Gemini 69/70, kimi 62, gpt-6-luna 55, Claude Haiku 53, Qwen 48; losing side 3, 7, 9, 5, 15; votes its audiences disliked 8/20, 6/23, 9/18, 7/16, 6/15 |
| T52 | The Live view showed what was said, not how the month was going | — | VERIFIED | `gui.py`, `gui.html`, `council.py`, `runner.py`, `politics.py`, `standing.py` | `test_live_view.py`, checked in a scripted control room | Each call brings its latency, cost and reasoning (first 2,000 characters); each vote result its ballots, the votes the voter's audiences disliked and the votes against its word; each month the neighbours' acts (refused ones with the reason), temperaments, forces and war, the month's public events by importance, each member's seat outlook and how removed members left. Live shows the month's steps and pace, a banner and optional notification, a vote board, seat chips, reasoning, the neighbours, the balance of forces and feed filters; the tally read back from the log equals the live one. Two bugs found on the way: a start dialog opened and cancelled several times sent one start per opening, and the feed asked for questionnaire answers a run without a questionnaire does not have |

### Open, deliberately

| ID | Title | Reason |
|---|---|---|
| T14 | Each feature on real models, on and off, same seeds | Needs paid or subscription seats. The behaviour-dependent savings (briefing on demand, quiet months, effort by phase) are upper bounds until then |
