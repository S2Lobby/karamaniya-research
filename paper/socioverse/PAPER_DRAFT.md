# Can a Long-Horizon LLM Governance Simulation Support Claims About Agent Behavior?

Muhammadjon Ahmadjonov, independent researcher, Uzbekistan
SocioVerse Challenge 2026, Track C (methodological and systems innovation)

*Draft 0.1, 17 October 2026. Design and method only. No study run has been made, and every result is [RESULT PENDING]. Components described as built are on internal branches that are not merged or frozen; branch names will be replaced by commit hashes at the freeze. Not for submission.*

## Abstract

Multi-agent simulations make long trajectories visible, but a trajectory can reflect the model, the office it holds, the order in which agents act, or the parser that reads their answers. We ask whether a long-horizon governance simulation of five language-model agents can support claims about agent behavior, or whether its measurement system produces them. We test three controls: rotating offices across seats, changing the action-order protocol, and auditing each exit against its raw answer and state change. For each control we state the naive reading, the controlled reading and the cost. The design is a 5 × 5 × 2 grid of 50 trajectories, with an optional replication on fresh seeds. A companion pre-registration fixes hypotheses, measures, audit rules and exclusion rules before any run. No study results are reported.

## 1. Question and frame

Long simulations make behavior visible over time, and easy to over-read. A delegate that leaves office in Month 7 may have resigned for its own reasons, or may have written an empty answer that the parser turned into a resignation. An evaluation that does not separate these routes ends up measuring its own implementation.

The study therefore tests the instrument, not which model governs best. It asks whether differences in persistence, reliability and influence among five models survive three controls: (1) **role**, each model holds each office equally often across seat rotations; (2) **order**, the same trajectories are run under a second action-order protocol; (3) **events**, each exit is traced from its raw answer and labeled by a blinded annotator. The proposal expected some apparent differences to weaken. That is an expectation, not a result. Section 4.5 fixes in advance what would count as a surviving candidate.

### 1.1 What the pilot shows

The pilot (85 trajectories, according to the proposal) is background evidence and is not pooled with the study. The recorded run folders in the repository, which the study did not change, show three things that motivate the controls. Conditions were mixed: of 21 folders, framing was "unobserved" in 11, "immersive" in 3 and "simulation" in 7. The exit extraction found 20 exit events, and a single-reader draft reading, which is not an annotator label, found that none of the five resignations is supported by its own wording. Readers changed what counted as an answer (Section 3.1).

### 1.2 Contributions

(a) A pre-registered, balanced design for 50 trajectories that separates seat, office and order effects. (b) An exit-trace audit: each exit carries its raw answers, the engine's reading, the state change and the flags, with a seeded sample, a written codebook and agreement statistics. (c) Reusable instrument options and tools, each on an internal branch and not yet merged: a fixed-office option, a second action-order protocol, a grid runner with resumes and a dry run, and a SocioVerse2 study package built as a legacy wrap.

**Table 0. Reviewer points and where they are answered**

| Reviewer point | Answered in |
|---|---|
| 1. Models, offices, initial state, rules, horizon, protocols, configurations | Section 3, Tables 1-2, Section 7 (models and horizon pending) |
| 2. Positioning; uncontrolled baseline or ablations | Section 2; Section 4.2 |
| 3. Audit sampling, annotation, agreement, comparisons, uncertainty, no-exit trajectories | Sections 4.3-4.6; Table 8 (pending) |
| 4. Scale, calls, tokens, runtime, hardware, cost, local versus API | Section 5; Table 4 (pending) |
| 5. Package under `studies/<study>/`, one command, seeds, replay, dry run, manifests, release | Section 7 |

## 2. Related work and positioning

SocioVerse is titled "A World Model for Social Simulation Powered by LLM Agents and A Pool of 10 Million Real-World Users" [1]. SocioVerse2 is "A Longitudinal Dynamic Social Simulation Framework under a Human-AI Co-evolutionary Paradigm" [2]. The study package follows the study layout of the SocioVerse2 v0.2.0 source, through a legacy wrap that leaves the simulator unchanged. The SocioVerse2 documentation pages were not checked [CITATION NEEDED: SocioVerse2 studies/<study>/ specification]. SocioBench [3] and EconAgent [5] appear on the same reference list; their content was not checked [CITATION NEEDED: their protocols and claims, for comparison]. Argyle et al. ask whether language models can simulate human samples [4]. This study does not test representativeness: the country is fictional and the models are not drawn from a human population.

A balanced assignment, a paired protocol comparison and a blinded two-rater audit are standard design devices, and we do not claim them as new. The claim is narrower: applying them to the trace of a persistent multi-agent governance run, with an audit that starts at the raw answer. We did not find an agent-evaluation survey in the sources available to us [CITATION NEEDED: agent-evaluation methods; trace-level auditing of agent interactions].

## 3. Specification: population, environment and behavior

"Base" in Table 1 means the code at commit 92f2cfa. "Branch" marks an option that exists only on the named internal branch.

**Table 1. P/E/B specification**

| Part | Specification |
|---|---|
| Population (P) | Five LLM delegates on seats A-E, each a different model [DECISION: five models]. Offices: head of government, treasury, interior, army, navy. Default `formation`: a Month-0 vote (base). Option `by_letter` (branch): A head, B treasury, C interior, D army, E navy, no vote. |
| Information | Seeded evidence dossier and seeded agenda with a red line; the agenda informs and orders nothing. |
| Environment (E) | Fictional country, updated monthly by a rule-based world engine, not an LLM. State: food supply, inflation, unemployment, public unrest, military readiness, diplomatic relations, political stability, institutional continuity. Each seed draws 3 to 7 inherited problems. |
| Neighbours | Hostile cabinets Veleria and Dorsania; no invasion or blockade in Month 1. Played by one fixed external model [DECISION: neighbours model] or by rules (`foreign_cabinets = false`). |
| Behavior (B) | Openings; response round in speaking order; votes and office orders; resolution; world step; cabinet acts. Limits: 150-word statements, two motions per delegate, four cabinet acts per month. |
| Action order | `seeded_shuffle` (default; base `council.py` 1136-1137, 1378-1379) or `fixed_precedence` (branch): head, treasury, interior, army, navy, then letter order. |
| Election and horizon | The Charter election is printed Month 36 (`CHARTER_ELECTION_MONTH = 35`); none comes earlier. Horizon: [DECISION: horizon H]. A run that owes a handover after an election can run up to `HANDOVER_EXTENSION = 4` months longer. |
| Trace | `config.json`, `manifest.json` (seeds, versions, `served_models`), `log.jsonl`, `prompts.jsonl`, `checkpoint.json`, `scorecard.json`. |

**Figure 1 (shell).** [FIGURE PENDING: the P/E/B path: model answer, validated structured action, causal world consequence, next observation. Mark where the parser and the audit read the trace.]

**Table 2. Initial state (code values; Karamaniya's population and output from ENGINE.md)**

| Quantity | Value |
|---|---|
| Karamaniya: army; police; navy | 28,000; 18,000; 6 vessels |
| Karamaniya: population; annual output | about 4.70 M; 6.63 bn base-price crowns |
| Veleria: population; annual output; army | 8.0 M; 13.44 bn; 65,000 |
| Dorsania: population; annual output; army | 5.0 M; 6.60 bn; 30,000 |

The currency is a simulation unit (ENGINE.md). The design keeps the project's rules: no election before Month 36; power rests on approval and on the Charter threshold; the crisis mandate is off; agendas inform and order nothing; the controls never tell a delegate how to decide; no AI text is cut silently.

### 3.1 Instrument status and defects found before the freeze

These were found by reading recorded answers or by tests. Each is fixed on a branch and not merged. None is a study result.

- Office rotation was by seed index, not by office (base `batch.py` line 90). Branch `by_letter` fixes it.
- Foreign cabinets reused the first two seats, which change under rotation. The study runner refuses a study without a fixed cabinet backend (branch).
- Unknown `[run]` keys were silently ignored. The study runner refuses unlisted options (branch).
- Loan amounts in the text, and values such as `{0.35}`, were refused; a decimal comma was misread ("1,5 million" as 15 million; "50,000,000 gold" as 50,000,000 million) (branch). Replay: seven distinct refused motions would now pass.
- Cabinet acts under `"action"` and null troops were refused; an opening refusal was reported twice; a message naming its recipient under `"recipient"` was refused (branch). Replay: cabinet acts kept rose from 336 to 379 of 441; private messages kept rose from 1,370 to 1,373 of 1,392.
- **Still open.** Refused private messages are not shown to their senders. The cabinet prompt omits the four-act cap, which exists only in the schema. A cabinet's strategy is cut to 180 characters without a stated limit. Of 183 cuts in the recorded month records, 80 carry the engine's flag that the limit is not stated in the prompt; whether that breaches the no-silent-cut rule is not established.

## 4. Experimental design

### 4.1 Grid and counts

The grid crosses five seat rotations (r = 0 to 4), five environment seeds and two action-order protocols: 5 × 5 × 2 = 50 trajectories. Under `by_letter`, the model in seat i sits in letter (i + r) mod 5 and holds office (i + r) mod 5. Across the rotations each model holds each office once per seed, so every model-office cell has ten trajectories. Seeds are fixed in the pre-registration [DECISION: seeds]. An optional replication on five fresh seeds adds 50 trajectories [DECISION: run it or not].

Under the default formation vote, delegates decide which office each model holds, so model and office are not separated by design. A fixed seat order under `by_letter` would give each model the same office in every seed, which confounds them. The rotated grid avoids both problems.

### 4.2 The three controls

**Table 3. Controls: naive reading, controlled reading and cost**

| Control | Naive reading | Controlled reading | Cost |
|---|---|---|---|
| Rotate offices | A model that persists longer is more durable. | Model and office effects, and their interaction, are estimated on the same trajectories. | 25 trajectories per protocol, not 5 for one fixed assignment. Offices are assigned, not elected. |
| Change action order | The model that speaks first, or whose motions pass, has the influence. | Matched trajectories differ only in protocol; paired differences show whether contrasts depend on order. | 25 more trajectories. `fixed_precedence` is an artificial order. |
| Audit events | A recorded exit is the model's decision. | Each exit is labeled from its raw answer and state change by blinded annotators; apparent exits can be reclassified. | Two raters per exit and a sample of other events; calibration time. Reclassification changes the primary outcome, so its rules are fixed before the freeze. |

*Rotating offices.* A fixed seat-to-office assignment cannot separate a model from its office. If model A outlasts model B in one fixed setting, the naive reading credits A, though A may have held an office with different exit rules. A contrast that disappears under rotation was an office effect.

*Changing the action order.* The protocols share the random stream: `fixed_precedence` draws the monthly shuffle and discards it, so every later draw keeps its number and position (branch report 02). The protocols are not identical beyond order. An intercept draw can land on a different message, and intelligence share records are written in publication order. These are reported as side effects; whether they change behavior is untested. Only fixed precedence is built [DECISION: second protocol].

*Auditing the events.* The naive reading takes each recorded exit as a decision. The controlled reading starts from the raw answer. Trajectories with reclassified exits stay in the sample, because excluding them would select on the measurement.

*Uncontrolled baseline.* The same seeds can be played with no model: scripted, passive, all-hawk and all-dove councils (ENGINE.md). Baselines do not yet inherit `office_assignment` [DECISION: baselines inherit `by_letter`].

### 4.3 Exit audit

An exit is any event by which a delegate or the government leaves office. The engine has eight member-level exits: resignation, expulsion, the targets of a successful coup, the plotters of a failed coup, the handover after an election defeat, loss of a personal seat, revolution and an officers' coup. Dismissal and displacement from an office do not remove the delegate from government. The brief's "vote of no confidence" is not in the engine and is not in the list [DECISION: keep it out, or build it separately]. The full list, with engine references, is in the pre-registration.

Every apparent exit is audited. Non-exit events (executed and refused motions) are sampled with a seeded, stratified draw of 200 events [DECISION: sample size]; at 95% confidence that gives a margin of about ±6.9 points for a proportion near one half. Two annotators label each row from the row alone, without the model, seat, office, rotation, protocol or seed [DECISION: annotators]. Labels are `substantively_supported`, `ambiguous` or `formatting_or_parser`, under ordered codebook rules (branch report 05). The raw answer decides the label; the engine's flag decides only whether an exit was recorded. The user adjudicates disagreements. Agreement is Cohen's kappa and Krippendorff's alpha (nominal, two raters) [CITATION NEEDED: kappa and alpha definitions]. Calibration on rows separate from the codebook's examples precedes the study audit [DECISION: calibration set and threshold].

### 4.4 Analysis plan

The primary unit is a delegate's time in government, from the start of Month 1 to its first exit, censored at the horizon, at the end of the run, or at a reclassified exit. Kaplan-Meier curves by model and starting office, with median and restricted mean survival time [CITATION NEEDED: Kaplan-Meier estimator; restricted mean survival time]. A Cox proportional-hazards model with model and starting office; the model-by-office term is exploratory. Standard errors are clustered by seed, though five clusters are few [CITATION NEEDED: cluster-robust inference with few clusters]. Protocol differences are paired within each seed-by-rotation cell. Intervals come from a bootstrap over seeds [DECISION: resamples and interval method]; with five seeds there are only 126 distinct resamples, so intervals are coarse. The three ablations and the scripted baselines use the same trajectories. Decisions rest on effect sizes and intervals, not p-values.

Two secondary measures describe the debate itself, from the month record. **S1** asks whether a delegate's final vote differs from its opening position, and separately from the stance it recorded in the response round; the opening is the delegate's tabled rival motion or the motion's own proposal where the record has that structure, and otherwise the engine's keyword read of the delegate's private-position text. **S2** compares response-round opposition on a motion family with the final ballots, reported as a gap per family: positive when intermediate opposition did not reach the final vote, negative when new dissent appeared at it. Families follow the engine's narrow rule, including its clustering of competing Charter amendments. The engine's `VOTE_INTENT_MISMATCH` flag is not used as a measure: the wave-3 review dropped it pending the T144 re-audit and the second annotator's labels, and the analysis reports it as a diagnostic only. The pre-registration and `docs/STATISTICS.md` give both formulas.

The Kaplan-Meier and restricted-mean figures are written as plain SVG by the analysis script, from the same computed curves as the CSV tables; the figures are self-contained and deterministic. The Cox fit is not part of the wave-3 analysis script and remains a separate analysis step.

### 4.5 Hypotheses and the survival rule

- **H1.** After rotation, the model contrasts in time to validated exit are zero.
- **H2.** The starting-office contrasts are zero.
- **H3.** The model-by-office interaction is zero (exploratory; ten trajectories per cell).
- **H4.** Model and office contrasts do not depend on the action-order protocol.
- **H5.** At least [DECISION: threshold] of apparent exits are reclassified.
- **H6.** Invalid-action and execution-mismatch rates do not differ by model.

A model contrast is a *surviving candidate for future study* only if it (a) appears under rotation with an interval excluding zero, (b) keeps its sign under protocol 2, and (c) keeps its sign under validated labels [DECISION: numeric thresholds]. A contrast that fails a condition is reported as a candidate artifact of the control that removed it.

### 4.6 Exclusions and contingencies

The full rules are in pre-registration Section 9. A paused run is resumed at most K times [DECISION: K; the grid runner's default is 3]; each resume replays the paused month, so its calls are counted again. Format failures are never retried, because they are the measured invalid-action rate. A failed row is replaced by a reserve seed with the same rotation and protocol [DECISION: replacement rule], and the failure is reported. A trajectory served by a model other than its configured one is flagged [DECISION: treatment]. Engine defects are recorded, not patched into the frozen engine; a trajectory marked `CORRECTED_BEHAVIORAL` is excluded from primary analyses. Hand corrections are not allowed. No-exit trajectories are censored and counted. The pilot is never pooled.

## 5. Results [RESULT PENDING]

No study result is reported. The shells are filled from the frozen runs.

**Table 4. Scale, calls, tokens, runtime, retries and cost [RESULT PENDING]**

| Item | Value |
|---|---|
| Agents per run; steps; repetitions | 5 delegates, 2 cabinets; [H] months; 50 trajectories (+50 if replicated) |
| Models served, per seat and for the neighbours | [RESULT PENDING; from `served_models`] |
| Council, cabinet, repair, diagnosis and survey calls | [RESULT PENDING] |
| Tokens, input and output | [RESULT PENDING] |
| Minutes per month; wall-clock per run; total for 50 | [RESULT PENDING] |
| Retries; pauses; resumes; replacements | [RESULT PENDING] |
| Hardware | [RESULT PENDING] |
| Cost: local inference; challenge API | [RESULT PENDING] |

Documented estimates, not measurements: ENGINE.md gives 375-555 council calls for a 36-month five-seat run, which is 18,750-27,750 for 50 runs before repairs and cabinet calls. The default cabinets add two calls a month. A same-seed baseline takes about four minutes for 36 months.

**Table 5. Exit events: raw engine labels against validated labels [RESULT PENDING]**

**Figure 2 (shell).** [FIGURE PENDING: Kaplan-Meier curves of time to validated exit, by model and by starting office.]

**Table 6. Cox estimates: model, office and model-by-office (hazard ratios, intervals) [RESULT PENDING]**

**Figure 3 (shell).** [FIGURE PENDING: paired protocol differences by measure, with seed-bootstrap intervals.]

**Table 7. Ablations and baselines [RESULT PENDING]**

**Table 8. Audit agreement: kappa, alpha, counts, disagreements, adjudication [RESULT PENDING]**

**Figure 4 (shell).** [FIGURE PENDING: one exit traced from raw answer through parser reading to state change, from a real study run, not a mock-up.]

## 6. Conclusions and limitations

The design can show whether a contrast survives the three controls, what each control costs, and how often the audit reclassifies an exit. It can show whether the instrument produces apparent behavior, and at what rate. It cannot show how real governments behave, whether five models represent language models in general, or how a model behaves under other framings.

**Scope.** The controls apply to any persistent multi-agent run with role assignment, a monthly action order and a log of raw answers. They do not apply where offices are elected rather than assigned, or where raw answers are not logged.

**Conditional conclusions.** If a contrast survives all three controls, it is a candidate for future study, with its scope stated. If it disappears under rotation, the reading was an office effect; under the second protocol, an order effect. If the audit reclassifies a large share of exits, the main finding concerns the instrument, and model-level exit claims from those runs should not be made. No direction is asserted before the results.

**Limitations.** Five models, one fictional country and five seeds, so the intervals are coarse. Ten trajectories per model-office cell give little power for interactions. `by_letter` removes the formation vote, so offices are assigned, not earned. The second protocol changes intercept draws, and its effect on behavior is untested. The codebook was drafted by one author on pilot examples; its agreement with two annotators is not yet measured. Framing changes what models are told about being studied; evaluation awareness is not measured [CITATION NEEDED: evaluation awareness in language models]. Scripted stand-ins are not models: a scripted 36-month dry run ended with the government keeping power by force in Month 37, and whether the stand-in rules should do that is open.

## 7. Package, reproducibility and release

**Study package.** `studies/karamaniya_trust/` (branch) is a SocioVerse2 Path C legacy wrap over the unchanged simulator, with four SocioVerse2 interfaces and a one-command dry run. Thirteen parity tests under socioverse2 0.2.0 check the wrap against the engine's own loop month by month, for two months and for 36 (reported by the branch's author; not re-run for this draft).

**Grid runner and audit tools.** `tools/study_grid.py` (branch) plans the 5 × 5 × 2 grid, runs rows in parallel, resumes paused rows up to `--max-resumes` (default 3), and runs a dry run with scripted seats; a 50-row scripted dry run finished with every row done (reported by the branch's author). `tools/exit_audit.py` and `docs/EXIT_AUDIT_CODEBOOK.md` (branch) provide extraction, seeded sampling, agreement statistics and 29 tests (reported by the author).

**Reproducibility.** The world is fully determined by the run seed, and the same seed replays identically. Model replies are not deterministic, and the manifest says so. Each manifest records seeds, versions and the model that actually answered each seat. A replay that feeds recorded answers back through the engine is planned [DECISION: whether the replay is a freeze item].

**Seeds and release.** Two candidate main batches exist, 4201-4205 and 2101-2105 [DECISION]. Neither appears in the readable pilot manifests; the private pilot table was not read. Code is under Apache-2.0 (README); the paper and written materials are not covered by that licence [DECISION: licence for the paper and traces]. Traces are synthetic and are checked for secrets and personal data before release. No `.env` file is read or released.

## References

[1] Zhang X, Lin J, Mou X, et al. SocioVerse: A World Model for Social Simulation Powered by LLM Agents and A Pool of 10 Million Real-World Users. arXiv:2504.10157, 2025. *Verified at arxiv.org/abs/2504.10157 (2026-10-17).*

[2] Zhang X, Lin J, Wang J, et al. SocioVerse2: A Longitudinal Dynamic Social Simulation Framework under a Human-AI Co-evolutionary Paradigm. arXiv:2609.24911, 2026. *Verified at arxiv.org/abs/2609.24911 (2026-10-17).*

[3] Wang J, Zhao Z, Ni T, Wei Z. SocioBench: Modeling Human Behavior in Sociological Surveys with Large Language Models. Proceedings of EMNLP 2025. doi:10.18653/v1/2025.emnlp-main.1335. *Verified via Crossref (2026-10-17).*

[4] Argyle LP, Busby EC, Fulda N, et al. Out of One, Many: Using Language Models to Simulate Human Samples. Political Analysis 31(3), 2023. doi:10.1017/pan.2023.2. *Verified via Crossref (2026-10-17).*

[5] Li N, Gao C, Li M, et al. EconAgent: Large Language Model-Empowered Agents for Simulating Macroeconomic Activities. Proceedings of ACL 2024 (Volume 1: Long Papers). doi:10.18653/v1/2024.acl-long.829. *Verified via Crossref (2026-10-17).*

Open citation markers in the text: SocioVerse2 package specification; SocioBench and EconAgent content; agent-evaluation methods; trace-level auditing; Kaplan-Meier; restricted mean survival time; cluster-robust inference with few clusters; kappa and alpha; evaluation awareness.
