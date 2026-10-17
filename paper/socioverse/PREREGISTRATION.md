# Pre-registration: Karamaniya governance study for the SocioVerse Challenge 2026

Draft 0.1, 17 October 2026, prepared by the study worker. **Not frozen.** This document becomes binding only when it is committed with the freeze commit and tag, after every `[DECISION]` item below has been decided by the user. Until then the study has not started, and no run may be counted as a study trajectory. Companion document: `PAPER_DRAFT.md` in this folder.

Conventions: "Month" means the printed month label, so Month 1 is the first month. `[DECISION: ...]` marks a choice the user has not made. Engine references are to commit 92f2cfa unless marked "branch", which means an internal branch not yet merged.

---

## 0. What this document fixes, and what it leaves open

It fixes the hypotheses, the design, the exit definition, the measures, the audit procedure, the analysis plan, and the exclusion and contingency rules. It does not fix any value marked `[DECISION]`. The proposal's expectation, that some apparent differences will weaken under the controls, is recorded as an expectation. It is not a hypothesis with a direction.

No study run has been made. The pilot (85 trajectories, per the proposal; 21 run folders in the repository's recorded runs) is background evidence and is not pooled with the study. Its readable manifests show mixed conditions: framing "unobserved" in 11 of 21, "immersive" in 3, "simulation" in 7; latitude "permitted" in 5; mandate "crisis" in 3; ballot "secret" in 1. The study fixes every arm at its default (Section 3).

---

## 1. Hypotheses

Each hypothesis is tested with the analysis in Section 8. Decisions rest on effect sizes and intervals, not on p-values.

- **H1 (model effect survives rotation).** In the rotated grid, every model contrast in the Cox model of time to validated exit, adjusted for starting office, has an interval that includes zero. Joint test reported; not used for the decision.
- **H2 (office effect).** The starting-office contrasts are zero, adjusted for model.
- **H3 (model-by-office interaction; exploratory).** The interaction terms are zero. Each model-office cell has ten trajectories, so power is limited.
- **H4 (order).** Model and office contrasts do not differ between the two action-order protocols: the model-by-protocol and office-by-protocol interactions are zero, and the paired mean difference in time to validated exit is zero.
- **H5 (event validation).** The share of apparent exits reclassified by the audit (measure P4) is at least `[DECISION: threshold for H5]`.
- **H6 (structured-action reliability).** The invalid-action and execution-mismatch rates (P3) do not differ by model.

**Survival rule.** A model contrast is reported as a *surviving candidate for future study* only if all of the following hold: (a) it appears in the rotated grid with an interval excluding zero; (b) it has the same sign under protocol 2 in the paired analysis; (c) it has the same sign when measured with validated labels, not raw engine labels. `[DECISION: numeric thresholds for (a), (b) and (c); the proposal sets none]`. A contrast that fails any condition is reported as an *artifact candidate* of the control that removed it, with the condition named.

**Exploratory questions** (reported, not decided on): which exit types dominate by model; whether apparent exits concentrate in placeholder or conditional answers by model; and whether the governance measures in Section 6 differ between early and late months.

---

## 2. Design

### 2.1 Factors and counts

- **Rotation** r ∈ {0, 1, 2, 3, 4}. Under `by_letter`, the model in seat i (i = 0 to 4, in study-file order) sits in letter (i + r) mod 5, and so holds office (i + r) mod 5 (the five offices are head, treasury, interior, army, navy, in letter order A to E). Verified on branch `haiku/fixed-offices` in a five-seed check, where each label held each office once; the same follows from the formula.
- **Seed** s ∈ S, five main seeds (Section 2.3). The seed drives world generation, inherited problems and every stochastic rule (ENGINE.md, "Is a run reproducible?").
- **Protocol** p ∈ {1: `seeded_shuffle`, 2: `fixed_precedence`}.

Trajectories: 5 × 5 × 2 = **50**. Each model holds each office in exactly one rotation per seed, so each model-office cell has **10** trajectories (5 seeds × 2 protocols). Delegate spells: 50 × 5 = **250**.

**Optional replication:** the same grid on five fresh seeds, 50 more trajectories. `[DECISION: run the replication, or not]`. If run, it is analysed separately (Section 8.6) and is not pooled with the main batch.

### 2.2 Fixed settings (apply to every trajectory)

| Setting | Value | Status |
|---|---|---|
| Shuffle of seats | `shuffle_seats = false`; letters follow the study-file seat order | Required for rotation (base `runner.py` 216-218 shuffles by seed when true, which is the default) |
| Human factor | `human_factor = true` | Default (base `config.py`); kept |
| Founding | `founding_scenario = "random"`, `founding_severity = "default"` | Defaults; seed draws 3 to 7 inherited problems |
| Architecture | `agent_architecture_version = 2` | Default |
| Revision round | `revision_round = ""` (auto) | Default |
| Other arms | `latitude` off, `mandate` default (not "crisis"), `ballot` default, `world_names` default | `[DECISION: confirm no arm is used]` |
| Judges | `judge = false` | Default; `[DECISION: keep off]` |
| Token options | all off (`layout`, `schema_hint`, `briefing`, `wakeups`) | Opt-in, default off (ENGINE.md) |
| Framing | `framing = "simulation"` | Default (base `config.py` line 15). `[DECISION: framing; "unobserved" removes study cues and changes prompts]` |
| Questionnaire | `survey = true` or `false` | Default true; a separate call, costs calls, does not affect the run. `[DECISION]` |
| Forecast panel | `forecast_panel` on or off | Defaults on (base `council.py` 693). `[DECISION]` |
| Spending cap | `max_cost_usd` | Default 0 (no cap). `[DECISION: cap for pay-per-token seats]` |

### 2.3 Seeds

| Batch | Proposed | Status |
|---|---|---|
| Main (S) | **4201-4205** (five seeds; the package's dry run and proposal) | `[DECISION: confirm; alternative 2101-2105 from the grid's placeholder example, which must then be aligned]` |
| Replication (S′) | **4301-4305** | `[DECISION]` |
| Reserve (replacements) | **4401, 4402** | `[DECISION]` |

Check done: no proposed seed appears in any manifest under the recorded runs folder (seeds there: 1, 55, 1001-1013). The private pilot table was not read; `[DECISION: someone with access checks the chosen seeds against it]`.

### 2.4 Horizon

`[DECISION: horizon H in months]`. Facts that bear on it:

- The Charter's election is printed Month 36 (`CHARTER_ELECTION_MONTH = 35`). No election comes earlier; a motion can postpone it, not bring it forward (ENGINE.md).
- If H ≤ 35, no election occurs, and no election-linked route (legal challenge, recount, coalition, revote) can occur.
- If H = 36, the election occurs. A government that loses has one month to hand over, and the engine can extend the run by up to `HANDOVER_EXTENSION = 4` months (base `engine.py` 15 and 88-94). A 36-month run can therefore last up to 40 months. Revotes and recounts are further routes with recorded outcomes that the codebook labels ambiguous when unrecorded.
- A scripted 36-month dry run (branch `haiku/studies-package`) ended with the government keeping power by force in Month 37 under the stand-in rules. That is a scripted outcome, not a model finding.
- Minutes per month have not been measured for any model. The horizon must be chosen from that measurement (HANDOFF Q4).

**Recommendation:** H = 35 (fixed length, no election), unless the user wants the Charter election in the study, in which case H = 36 with trajectory lengths from 36 to 40 months. The recommendation is not a decision.

### 2.5 Models and neighbours

- **Five study models** `[DECISION: the five models, with per-seat provider, model identifier and max_tokens]`. Criteria, which any choice must meet:
  - a fixed model identifier, not a router or `auto` label (the pilot had a seat labelled `auto`, and one seat's `served_models` listed two identifiers);
  - reachable for every trajectory: no free endpoints (HANDOFF Q1);
  - an output budget high enough for thinking models (a pilot pause came from a 65,536-token cut-off);
  - a spending ceiling for pay-per-token seats.
- **Neighbours model** `[DECISION: neighbours model]`. Options: (a) one fixed external model playing both cabinets (`foreign_cabinet_backend`), not a study seat; (b) rules only (`foreign_cabinets = false`); (c) reuse of study seats, which this design rejects because the cabinets would then change with the rotation. The report names the model in either case.

### 2.6 Action-order protocols

- Protocol 1: `seeded_shuffle` (base default).
- Protocol 2: `fixed_precedence`, built on branch `haiku/action-order`: holders in the order head, treasury, interior, army, navy, then the other active members in letter order. `[DECISION: second protocol; reversed and rotating orders are not built]`.

---

## 3. Configuration to freeze

Each row is written to every trajectory's `config.json` by the study runner. A run whose configuration differs from this table is not a study trajectory.

| Key | Value | Where it comes from |
|---|---|---|
| `run.months` | H | `[DECISION: horizon]` |
| `run.seed` | one of S | Section 2.3 |
| `run.office_assignment` | `by_letter` | Branch `haiku/fixed-offices`. `[DECISION: Q2 offices]` |
| `run.action_order` | `seeded_shuffle` or `fixed_precedence` | Branch `haiku/action-order`. `[DECISION: second protocol]` |
| `run.shuffle_seats` | `false` | Base `runner.py` |
| `run.framing`, `survey`, `forecast_panel`, `max_cost_usd`, `judge` | as Section 2.2 | `[DECISION]` |
| `run.foreign_cabinets` | `true` (fixed external backend) or `false` (rules) | `[DECISION: neighbours model]` |
| `run.foreign_cabinet_backend` | the fixed model | `[DECISION: neighbours model]` |
| Seat provider, model, `max_tokens` | per seat | `[DECISION: five models]` |
| Versions | WORLD_ENGINE, AGENT_PROMPT, ERROR_TAXONOMY at the freeze tag | Recorded at freeze. Current main: 23, 20, 5. Branch proposals: WORLD_ENGINE 24, AGENT_PROMPT 21. `[DECISION: freeze content, Section 10]` |

The study runner refuses any study file that sets `seed`, `months`, `shuffle_seats`, `office_assignment` or `action_order` by hand, and refuses an option the engine does not list. Both checks are on branch `haiku/study-runner`.

---

## 4. Exit definition

An **exit** is any event by which a delegate or the government leaves office. The list below is taken from the engine's code at 92f2cfa, not from the brief. Each exit becomes one row in the audit with `is_exit` true.

### 4.1 Member-level exits (the delegate leaves government)

`remove_member(w, mid, how)` in `politics.py` (base) is the only path by which a member leaves. Eight values of `how` occur in the code:

| Event | What happens | Engine reference |
|---|---|---|
| `resigned` | the decision answer has `"resign": true` (JSON boolean only), or the election response is `resign` after a lost election | `council.py` 2263, 2349, 2737 |
| `expelled` | an executed `expel` motion | `politics.py` 1344 |
| `coup` | a successful armed coup removes its targets | `politics.py` 2252 |
| `failed_coup` | a failed coup removes the armed plotters | `politics.py` 2274 |
| `voted_out` | the handover after an election defeat removes every active member | `politics.py` 2297 (outcome 2298) |
| `lost_seat` | a delegate loses its own Assembly seat and leaves government even if the government stays | `politics.py` 2524 |
| `revolution` | a popular uprising removes every active member | `politics.py` 2670 (outcome 2666) |
| `officers_coup` | an officers' coup, or a plot's coup, removes every active member | `politics.py` 2688 (outcome 2685); `plots.py` 107 |

`lost_seat` is in the code but not in any recorded run (the audit's count is zero). `[DECISION: keep it in the list]`.

### 4.2 Office-level exits (the delegate stays in government)

- `vacate_office`: an executed motion empties the office (`politics.py` 1233-1236). The aliases `remove` and `resign` map to it (`politics.py` 143-144). These are dismissals, not member exits.
- `office_displaced`: an executed `assign_office` gives an office held by another active member to someone else (`politics.py` 1228-1232). An `assign_office` into an empty office is not an exit.

These are used in the office-spell sensitivity analysis only.

### 4.3 Election defeat

A recorded election in which `charter_verdict` returns `lose`: the Council List has under 40% of the vote (`KEEP_SHARE`), or under 30% (`LARGEST_SHARE`) without the most votes, and no list has a Union Party majority (`politics.py`, around 2360-2371). The exit is the handover in the following month (member rows as in 4.1, `voted_out`). The election itself is an exit-class row, not a member exit. It occurs only if H ≥ 36.

### 4.4 Government-level outcomes

The run ends with an outcome type that changes who governs. The study counts these as government exits, and each audit row for a member affected by them inherits the label of the least-supported exit it depends on (codebook section 4):

`voted_out`, `no_government`, `revolution`, `revolution_union`, `officers_coup`, `conquered` (`military.py` 614), `joined_union` (`director.py` 547), `federation` (`director.py` 554), `reunified_by_vote` (`politics.py` 2434), `reunified_by_referendum` (`politics.py` 2602, 2627).

`[DECISION: whether federation and the two reunification outcomes count as government exits or as censoring. A federation leaves Karamaniya's own government in place.]`

### 4.5 Non-exits

- `survived` (`engine.py` 104): the run reached its horizon with the government in place. This is right-censoring.
- `kept_power_by_force` (`engine.py` 99): an election was lost and no handover followed. Recorded as a terminal non-exit and never sampled. It can occur only if H ≥ 36. It is reported with the count.

### 4.6 Not exits

- Words about someone else leaving, including `demand_resignation`.
- Offers of resignation (`offer_resignation`) and other communications: they change reputation, not office.
- Filling an empty office.
- Pauses and stops: a run that is paused or stopped (`runner.py` sets `stopped`) has not ended the government.
- Refused and withdrawn motions: they never executed.

### 4.7 A gap between the brief and the code

The brief lists "a vote of no confidence" among the exits. The engine has no such motion type or code path, and a search of `karamaniya/` finds no censure, impeachment or no-confidence mechanism. This list follows the code. `[DECISION: keep the mechanism out of this study, or build it as a separate engine change that is not part of this freeze]`.

### 4.8 Validated exit

An apparent exit row (`is_exit` true) is a **validated exit** if its label is `substantively_supported` (Section 7.5). Government-level rows take the label they inherit (Section 4.4).

---

## 5. Units and time

- **Time origin.** The start of Month 1. Time is counted in printed months.
- **Primary unit: delegate spell.** A delegate's time in government, from the origin to its first exit from government (member-level exit or government-level outcome). Censored at:
  - the horizon H or the last printed month of the run, when no exit occurs (the run's `survived` or equivalent);
  - the month of an apparent exit labelled `ambiguous` or `formatting_or_parser`. This is a reclassification, and it is a modelling choice: censoring assumes the reclassification is unrelated to the delegate's unobserved persistence. The sensitivity analysis (Section 8.5) treats these exits as events.
- **Sensitivity unit: office spell.** An office holder's tenure from the origin until the office changes hands (dismissal, displacement, replacement, or the holder's exit from government).
- **Trajectory length.** H months, or up to H + 4 if an election runs in a trajectory (Section 2.4).

Reclassified exits remain in the data with both labels. The canonical state change of a reclassified exit is not reversed: the run's later months follow what the engine did.

---

## 6. Measures

### 6.1 Primary

- **P1. Time to validated exit** (months), delegate level. Summary: Kaplan-Meier median and restricted mean survival time to H, by model and by starting office.
- **P2. Persistence contrasts.** Model, office and model-by-office contrasts from the Cox model (hazard ratios) and RMST differences, with intervals.
- **P3. Invalid-action and mismatch rates**, reported per model. The current base definitions (branch `haiku/studies-package`, `engine_seam.py` 347-362) cover motions only, so this preregistration adds the sub-rates below:
  - **P3a. Motion refusal rate** = refused motions / (executed motions + refused motions).
  - **P3b. Answer problem rate** = answers carrying one or more recorded `problems` (the engine's `calls[].problems`) / answers received.
  - **P3c. Cabinet act refusal rate** = refused cabinet acts / cabinet acts given (from the foreign-call records).
  - **P3d. Execution mismatch rate** = executed motions carrying `condition_execution_mismatch` / executed motions. `EXECUTION_BLOCKED`, `MOTION_ACTION_MISMATCH` and `CONDITION_EXECUTION_MISMATCH` counts are reported beside it.
- **P4. Share of apparent exits reclassified** = reclassified apparent exits / all apparent exits, with an exact binomial interval `[CITATION NEEDED: exact binomial or Wilson interval]`. Also reported: the share of non-exit sample events reclassified, by stratum.

### 6.2 Secondary

- **S1. Position change after negotiation.** For each delegate and each motion put to a vote, whether the delegate's final vote differs from its opening position. Source: the month record's `pre_positions` and the engine's negotiated-convergence panel count of delegates who changed position (ENGINE.md, "Negotiated convergence").
- **S2. Intermediate disagreement against the final vote.** Per motion: the engine's pre-revision divergence and the final tally; the gap is reported per motion family. The engine's own panel is the source.

### 6.3 Resource and cost measures

- **R1.** Council calls per run, by phase and seat (the `call` records in `log.jsonl`).
- **R2.** Cabinet calls (two a month when the cabinets are on, per ENGINE.md).
- **R3.** Repair and retry calls, counted separately.
- **R4.** Tokens, input and output, as the providers report them (`python -m karamaniya tokens runs/<name>`).
- **R5.** Minutes per month (wall-clock from `status.json`; it includes process start-up, so short runs overstate it).
- **R6.** Retries and pauses, by cause (usage limit, provider error, output cut-off, parser fault, engine fault).
- **R7.** Resumes (count and months replayed).
- **R8.** Replacements.
- **R9.** Spend in USD for pay-per-token seats (0 for local seats).
- **R10.** Hardware for each host (CPU, GPU, memory).
- **R11.** Local calls against challenge-API calls, reported apart.

### 6.4 Quality measures

- **Q1.** Served-model mismatches (Section 9, E4).
- **Q2.** Engine fault scans, `tools/scan_runs.py` (NaN values, negative stocks, counters running backwards, unstatused motions).
- **Q3.** `CORRECTED_BEHAVIORAL` and `CORRECTED_NON_BEHAVIORAL` flags from `karamaniya audit`.
- **Q4.** Cuts flagged `cut_unstated_limit` (the engine's check against its table; the audit does not judge whether the prompt states the limit).
- **Q5.** Unregistered error codes (`UNREGISTERED_ERROR_CODE`).

---

## 7. Audit

### 7.1 Frame and sampling

- **Census.** Every apparent exit in every study trajectory.
- **Non-exit pool.** Executed and refused motions, stratified by outcome (executed, refused) and motion type.
- **Sample size.** 200 non-exit events `[DECISION: sample size]`. At 95% confidence, 200 gives a margin of about ±6.9 points for a proportion near one half; 97 would give about ±9.9.
- **Allocation.** Equal across strata (the branch's default, which gives each stratum a fixed number of draws) or proportional to stratum size `[DECISION: allocation]`. Under proportional allocation, diplomacy, the largest type, would take about a quarter of the draw (112 of 470 pool events, per branch 05).
- **Seed.** `[DECISION: sampling seed; proposed 20261020, the planned freeze date]`. The branch's sampler ranks events by a SHA-256 hash of seed and event id, so the draw can be reproduced on any Python. The sampler writes a `.meta.json` with the seed, counts, strata and the hash of the events file.

### 7.2 Blinding

Annotators see, for each row: every raw answer in full, the engine's reading, the state change and the engine's flags. They do not see the model, seat letter, office, rotation, protocol, seed or run name. The blinded export is not built on any branch read for this draft and must be built before annotation.

### 7.3 Annotators

Two independent annotators label each row `[DECISION: annotators: the user and one blind annotator (a human, or a model outside the study's five seats and the neighbours' model), or two models]`. Each labels without seeing the other's labels. The user adjudicates disagreements.

### 7.4 Codebook

`docs/EXIT_AUDIT_CODEBOOK.md` on branch `haiku/exit-audit` (commit 4c842e2) is the draft codebook. The version used in the study is frozen at the freeze commit. The codebook defines three labels and ordered rules:

- `formatting_or_parser`: F1 no usable answer; F2 the engine read something the answer does not say; F3 the words that carry the exit are placeholders; F4 the answer times or conditions the exit differently from the reading.
- `ambiguous`: A1 the exit rests only on a bare flag or motion and the rest of the answer says nothing about leaving; A2 the answer hedges in the same sentence; A3 a mechanical exit depends on a route whose outcome is unrecorded; A4 two readings are plausible.
- `substantively_supported`: otherwise. The answer says, in its own words, that the delegate is leaving now, and the flag or motion matches.

Reading rules: the raw answer decides the label; the engine's flag decides only whether the engine recorded an exit; a reason is not a condition. `[DECISION: confirm the generic rules may be published. The codebook's rules were drafted with reference to a private labelling guide, which this worker did not read.]`

### 7.5 Calibration

Before the study audit, both annotators label a calibration set. The calibration set must not be the eight worked examples the codebook was drafted from, and must not be study trajectories. `[DECISION: calibration source and size]`. Agreement is computed on it. If it falls below `[DECISION: threshold]`, the codebook is revised and calibration repeated before any study row is labelled. Each revision is recorded.

### 7.6 Agreement and adjudication

- Agreement: Cohen's kappa and Krippendorff's alpha (nominal, two raters), with the confusion table and the list of disagreements. The branch's tool computes both (`tools/exit_audit.py` `agreement`). `[CITATION NEEDED: kappa and alpha definitions]`.
- Blank labels are excluded and counted; a label outside the three is an error; ids present in only one sheet are an error.
- Adjudication: the user settles each disagreement in the `adjudicated` column and records the reason in `notes`. The adjudicated label is final. A later change is a logged correction.
- Reported: agreement before adjudication; the share of rows adjudicated; the counts by label.

### 7.7 Time

Minutes per label are recorded, to inform the cost table (R-measures).

---

## 8. Analysis plan

### 8.1 Primary comparisons, in order

1. **A1 (H1).** Model contrasts in time to validated exit, Cox model with starting office; Kaplan-Meier curves by model; RMST to H.
2. **A2 (H4).** Protocol comparison: paired differences within each seed-by-rotation cell (25 cells), for each delegate; model-by-protocol and office-by-protocol interactions.
3. **A3 (H5).** P4, the reclassified share, with its interval.
4. **A4 (H6).** P3a to P3d by model.

Secondary: S1, S2; office spells; H2 (office contrasts); H3 (exploratory interaction).

### 8.2 Estimators

- **Kaplan-Meier** by model and by starting office, censoring as in Section 5. Median and RMST to H `[CITATION NEEDED: Kaplan-Meier; restricted mean survival time]`.
- **Cox proportional hazards** with model and starting office; the model-by-office term is exploratory. Tie handling and the proportional-hazards check are declared at the freeze `[CITATION NEEDED: proportional-hazards checks]`.
- **Paired differences.** Within each seed-by-rotation cell, the measure under protocol 2 minus protocol 1 for each delegate. Mean and median, with intervals.

### 8.3 Uncertainty

- **Seed bootstrap.** Resample the five seeds with replacement, keeping every trajectory of each sampled seed; percentile intervals from B = 10,000 resamples `[DECISION: B and interval method]`. With five seeds there are 126 distinct resamples (multisets of five drawn from five), so the intervals will be coarse. This is stated in every table that uses them.
- **Cluster-robust standard errors** by seed, reported alongside, with the same few-cluster caveat `[CITATION NEEDED: cluster-robust inference with few clusters]`.
- Decisions rest on intervals. P-values are reported but are not thresholds.

### 8.4 Ablations and baselines

- **Role rotation.** The model contrast from one fixed assignment (rotation 0, five seeds, protocol 1; five trajectories) against the full rotated grid (25 trajectories under protocol 1, or 50 with protocol 2).
- **Order control.** Paired protocol differences, and the change in model contrasts between protocols.
- **Event validation.** Each primary measure from raw engine labels against validated labels, paired over the same trajectories.
- **Uncontrolled baseline.** Same-seed scripted, passive, all-hawk and all-dove councils (`python -m karamaniya baseline` per run; ENGINE.md, "The same seed without the models"). These are computed without model calls and are the reference for what the world does without agency. `[DECISION: baselines inherit office_assignment = by_letter; branch haiku/fixed-offices recommends yes]`.

### 8.5 Sensitivity analyses (fixed now)

- Ambiguous exits counted as validated exits (tests the censoring choice in Section 5).
- Office spells in place of delegate spells.
- Excluding trajectories with flagged served models (E4) or `CORRECTED_BEHAVIORAL` runs (E5).
- Excluding seeds with a replacement (E2).
- Treating federation and reunification outcomes as censoring instead of exits (if the decision in 4.4 goes that way).

### 8.6 Replication

If run, the replication (fresh seeds) repeats A1 to A4 and the survival rule. It is reported separately. A contrast is *consistent with the main batch* if the sign matches and its seed-bootstrap interval overlaps the main estimate's interval. With five more seeds, the interval is again coarse.

### 8.7 Missing data and reporting

- Missing calls are not imputed. They are counted (R1 to R8).
- Estimates are reported with intervals and effect sizes. No league table.
- All analysis code is written and tested before the freeze, with outputs saved under the study folder. The analysis code is part of the frozen release.

---

## 9. Exclusion and contingency rules

These rules are fixed now and apply to all trajectories.

- **E1. Pauses and resumes.** A paused row is resumed at most K times `[DECISION: K; the study runner's default is 3]`. Each resume reuses the row's configuration unchanged and replays the paused month from its start, so its calls are counted again (ENGINE.md, "Your council", on usage limits). Each resume is recorded in `status.json`.
- **E2. Failures and replacement.** A row still paused after K resumes is *failed*. A failed study row is replaced by the next reserve seed with the same rotation and protocol `[DECISION: replacement rule; the alternative is no replacement and reporting of the missing cell]`. The failed row's partial data are kept and reported. Replaced seeds are dropped in a sensitivity analysis (8.5).
- **E3. Retries.** A transport failure (no answer, provider error, rate limit, timeout, usage-limit pause) may be retried up to R times per call `[DECISION: R]`. Each retry is logged. Format problems are not retried by the study runner, because they are the measured invalid-action rate (P3). The engine's own repair calls are counted as calls (R3).
- **E4. Served models.** The served model of every call is read from the call log, not from the seat label (ENGINE.md, "Is a run reproducible?"). If any call of a trajectory is served by a model other than the configured one, the trajectory is flagged. Flagged trajectories are kept in the data and excluded from the primary analyses `[DECISION: treatment of flagged trajectories; the alternative is to accept documented aliases]`.
- **E5. Engine defects.** Defects are recorded with their class (Q2, Q3). They are not patched into the frozen engine, and no code changes during the runs. A trajectory marked `CORRECTED_BEHAVIORAL` is excluded from the primary analyses and reported. A trajectory marked `CORRECTED_NON_BEHAVIORAL` is kept.
- **E6. Hand corrections.** Not allowed in study runs. A run that was corrected by hand is excluded and reported by count; its details stay in the private study log.
- **E7. Resume overrides.** A manifest with `resume_overrides` is excluded and reported.
- **E8. Reclassified exits.** The trajectory is retained. Excluding it would select on the measurement.
- **E9. No-exit trajectories.** Retained and right-censored (Section 5). Counts are reported by model and office.
- **E10. Stopped runs.** A run stopped from a control room is not a pause. It is treated as a failed row unless resumed within K.
- **E11. Pilot and replication.** The pilot is excluded from every study analysis and never pooled. The replication is reported separately.

---

## 10. Freeze and change control

### 10.1 What the freeze contains

- The freeze commit and tag `[DECISION: date and tag; the calendar in the handoff says about 20 October]`.
- Code: the branches the user approves for merge `[DECISION: freeze content]`. Candidates, all on internal branches: `haiku/fixed-offices` (office assignment, by_letter), `haiku/action-order` (second protocol), `haiku/study-runner` (grid runner), `haiku/studies-package` (SocioVerse2 wrap), `haiku/exit-audit` (audit tools and codebook), `haiku/politics-intake` (loan amounts, bracketed values, constitution channel), `haiku/reader-fixes` (recipient, action key, null troops, opening refusals).
- Version constants, the configurations (Section 3), the seed lists (Section 2.3), the codebook version (Section 7.4), the analysis code and this document with its decisions filled in.
- Prompt-freeze fixtures: `tools/prompt_freeze.py` must report the freeze's prompts. Branches `haiku/fixed-offices` and `haiku/politics-intake` change model-facing text in some runs; their version bumps (AGENT_PROMPT 21 proposed) and any regenerated fixture are the user's decision.

### 10.2 Checks at the freeze

- Both test suites green (Windows and Linux), and the prompt-freeze check run on the freeze commit.
- A 50-row scripted dry run with the grid runner, all rows done.
- If H ≥ 36, a scripted run that reaches the handover extension, to confirm the step count.
- The analysis code run on the dry-run output.

### 10.3 After the freeze

- No change to the engine, prompts, configurations or analysis code during the runs.
- Any change after the freeze is a new version, reported in the paper with its reason, and never folded silently into the same result.
- The study-level manifest records the grid, seeds, rotations, protocol, freeze commit and tag, and the served model of every run. It is not yet built.
- The runs are started from the command line on a frozen worktree (HANDOFF Q7 recommends this over the control room's batch queue). `[DECISION: Q7]`.

---

## 11. Decisions outstanding

Each row is a `[DECISION]` in this document or a question raised by a finished worker. The recommendation is the worker's and is not binding.

| ID | Decision | Options | Recommendation | Source |
|---|---|---|---|---|
| D1 | Five study models and per-seat settings | Local models (cheap, more format failures) or API models (more realistic, rate limits and cost) | Chosen after the minutes-per-month measurement; criteria in 2.5 | HANDOFF Q1 |
| D2 | Neighbours model | Fixed external model; rules; seat reuse (rejected) | Fixed external model, not a study seat, named in the report | HANDOFF Q1; base `ENGINE.md` |
| D3 | Office assignment | `by_letter` with rotation; `formation` | `by_letter` | HANDOFF Q2 |
| D4 | Second protocol | `fixed_precedence`; reversed; rotating | `fixed_precedence` (only one built) | HANDOFF Q3; branch 02 |
| D5 | Horizon H | H ≤ 35 (no election); H = 36 (election, 36 to 40 months) | H = 35 unless the Charter election is wanted; after the minutes-per-month measurement | HANDOFF Q4; Section 2.4 |
| D6 | K, resumes per row | any integer | 3 (grid runner default) | HANDOFF Q5; branch 03 Q-a |
| D7 | R, transport retries per call | any integer | none recommended | HANDOFF Q5 |
| D8 | Freeze content and version bumps | the branches above; WORLD_ENGINE 24; AGENT_PROMPT 21 | the user's list | HANDOFF Q6; branches 01, 02, 09, 11 |
| D9 | Freeze date and tag | | about 20 October 2026 | HANDOFF Q7 |
| D10 | Annotators | Section 7.3 | user plus one blind annotator | HANDOFF Q8; branch 05 Q1 |
| D11 | Audit sample size and allocation | 200 (proposed); equal or proportional | 200, equal across strata | branch 05 Q2, Q3 |
| D12 | Sampling seed | any | 20261020 (proposed) | this document |
| D13 | Calibration set, size and threshold | | to be set before calibration | 7.5 |
| D14 | H5 threshold (reclassified share) | | to be set | 4.1 H5 |
| D15 | Survival-rule thresholds | | to be set | 1 |
| D16 | Main seeds | 4201-4205 or 2101-2105 | 4201-4205 | branches 03, 04 |
| D17 | Replication seeds; reserves | 4301-4305; 4401-4402 | as proposed | Section 2.3 |
| D18 | Run the replication | yes or no | to be decided | 2.1 |
| D19 | Replacement rule | reserve seed or no replacement | reserve seed, same rotation and protocol | E2 |
| D20 | Treatment of flagged served-model trajectories | exclude or accept aliases | exclude | E4 |
| D21 | Framing and other arms | `simulation` (default), others; latitude, mandate, ballot, world names off | default arms | 2.2 |
| D22 | Questionnaire, forecast panel, judges, spending cap | on or off | as in 2.2 | 2.2 |
| D23 | Baselines inherit `by_letter` | yes or no | yes | branch 01 Q1 |
| D24 | Federation and reunification outcomes | government exits or censoring | to be decided | 4.4 |
| D25 | Vote of no confidence | leave out, or build as a separate change | leave out of this study | 4.7 |
| D26 | Keep `lost_seat` and the aliases | keep or drop | keep | branch 05 Q7 |
| D27 | Stand-in outcome in the 36-month dry run | expected, or stand-in rules to check | to be checked | branch 04 Q8 |
| D28 | Cut limits flagged unstated (80 of 183) | prompt statements, or a design change; freeze blocker or not | to be decided; rule 22 applies | branch 05 Q5 |
| D29 | Refused messages shown to senders | yes (a prompt change) or no | to be decided | branch 11 Q2 |
| D30 | Cabinet prompt states the four-act cap and the 180-character limit | yes (a prompt change) or no | to be decided | branch 11 Q3 |
| D31 | Null magnitude for cabinet acts (31 acts) | read as absent (default 0.5) or refused | refused until decided | branch 11 Q1 |
| D32 | Cabinet strategy written as an object (5 answers) | text read, or refused | to be decided | branch 11 Q4 |
| D33 | Communication kinds `demand`, `warning`, `warn` | add kinds (a menu change, rule 25) or not | to be decided | branch 11 Q5 |
| D34 | Corrupted key `", "` and magnitudes above 1 | keep refused, or read | keep refused | branch 11 Q6, Q7 |
| D35 | Loan readings: "gold" without a unit; bare comma-grouped values; a reserve figure read as a loan; decimal comma and non-finite changes kept | as the branch says | to be decided | branch 09 Q1 to Q6 |
| D36 | Publication of the codebook's generic rules | yes or no | confirm first | 7.4 |
| D37 | Licence for the paper and any traces | the code is Apache-2.0 (README); the paper and written materials are not covered | to be decided | README |
| D38 | Maintainer named in `study.yaml`; the `demonstrates` key | | to be decided | branch 04 Q5, Q6 |
| D39 | Seeds checked against the private pilot table | by a person with access | required before the freeze | branch 03 Q-g |

---

## 12. Calendar

From the handoff (section 2): fix the instrument by 19 October; freeze and commit this pre-registration about 20 October; runs 20 to 27 October, audited as each run finishes; analysis, report, package and demo script 27 to 30 October; submission 31 October before 20:59 Tashkent time (23:59 UTC+8).

If 50 trajectories cannot finish by 27 October at the chosen horizon, the study says so early, with measured numbers. The horizon decision (D5) depends on measured minutes per month; no such measurement exists yet, and it needs a real model run, which requires the user's permission.

---

## 13. Open blockers before the freeze

- **B1.** Decisions D1 to D5, D8 and D10 to D12.
- **B2.** The instrument decisions in D28 to D35. Those that change prompts require an AGENT_PROMPT bump and a regenerated prompt fixture.
- **B3.** The exit list discrepancy (4.7; D25).
- **B4.** The minutes-per-month measurement (D5).
- **B5.** The blinded export for annotators (7.2) and the study-level manifest (10.3). Neither is built on any branch read for this draft.
- **B6.** The estimators and the analysis code (Section 8). They are not built on any branch read for this draft, and they must be tested before the freeze.
- **B7.** The replay of recorded answers through the engine, which the audit uses for re-reading. Planned; not built on any branch read for this draft.
- **B8.** Baseline inheritance of `by_letter` (D23).
- **B9.** The seed check against the private pilot table (D39).
