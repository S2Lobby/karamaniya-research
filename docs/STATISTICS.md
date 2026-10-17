# Study statistics: measures and formulas

Wave 3, workstream F. This page documents every measure `tools/study_analysis.py` computes, the formula it uses, its
denominator and its source fields. The script is standard library only: no numpy, scipy or matplotlib. It reads run
folders and writes CSV tables, `summary.md` and plain SVG figures.

Run it from the worktree root:

    python tools/study_analysis.py RUNS [RUNS ...] --out DIR [--plan PLAN.json] [--status STATUS.json]
                                   [--labels SAMPLE.csv] [--horizon N] [--tau N] [--bootstrap B] [--seed S]
                                   [--fixed-rotation R] [--complete-only] [--no-integrity]

`RUNS` are run folders or folders that hold run folders. The engine version used to define the copied rules below is
engine 26 (commit 86c07d0): `karamaniya/analytics.py` (`initial_stance`, `MOTION_WORDS`),
`karamaniya/convergence.py` (motion statuses, `families`, `_divergence`, `_norm_stance`) and `ENGINE.md`,
"Negotiated convergence".

## Conventions

- `month` is the engine's zero-based month index. "Month N" in the output is N-1.
- A seat that exits at log index `m` has `raw_time = m + 1` months in office. A seat with no exit is censored at its
  run's last month (the number of month records), so a run that ran past Month 36 keeps its real length.
- An `exit` is an apparent exit as `tools/exit_audit.py` extracts it: member exits, office exits, government outcomes
  and a lost election. The validated variant counts only exits labelled `substantively_supported`; every other
  apparent exit is treated as censoring.
- The model key is the configured seat model. A router seat answered by several underlying models is still one
  configured key; `run_inventory.csv` keeps the served list.

## Survival: Kaplan-Meier and restricted mean

For a group of seats:

- Each seat contributes a duration `t_i` and an event flag `e_i` (1 exit, 0 censoring).
- At each distinct exit time `t`, with `n_t` seats at risk (duration at least `t`) and `d_t` exits,
  `S(t) = S(t-) * (1 - d_t / n_t)`. Ties are one step.
- The median is the first `t` with `S(t) <= 0.5`.
- The restricted mean survival time to `tau` is `RMST(tau) = integral_0^tau S(u) du`, computed as the area under the
  step curve. A group is not given an RMST when its longest follow-up ends before `tau`: carrying the last value
  forward would overstate persistence. It gets `NA` and `estimable = False` in `persistence.csv`.
- `tau` defaults to `min(horizon, the longest follow-up)` and can be set with `--tau`.
- Intervals are percentile bootstrap intervals over seed clusters: whole runs of a sampled seed are kept together,
  the RNG is seeded (`--seed`, default 20261031), and the same inputs give the same table.
- The trajectory curve treats each run as one subject: its duration is the first exit by any seat, or the run's last
  month when no seat exits.

### SVG figures

`write_survival_svgs` writes, into the analysis output folder:

| File | Content |
|---|---|
| `km_by_model.svg` | Kaplan-Meier by configured model, raw engine labels |
| `km_by_office.svg` | Kaplan-Meier by formation office, raw engine labels |
| `km_first_exit.svg` | Kaplan-Meier over runs, first exit by any seat |
| `km_by_model_validated.svg`, `km_by_office_validated.svg`, `km_first_exit_validated.svg` | the same with validated labels, after `--labels` |

The writer is pure Python; the SVG is self-contained (no external resource, no script, no timestamp). Each series is
a 2px step curve in the reference categorical palette, with a tick at every censored seat, hairline gridlines, a
legend naming every drawn group with its seat count, and a caption. At most 8 groups are drawn; when there are more,
the largest groups are drawn and the subtitle says how many were left to the CSV tables. A single-series chart has
no legend box, because its title names the series. The output is deterministic: the same observations give the same
bytes. The core path builder, `km_path(steps, x_max, x_of, y_of)`, is unit-tested against a hand-computed step curve.

## Secondary measure S1: position change after negotiation

Unit: one delegate-motion pair, for every motion that reached a vote. A motion reached a vote when its recorded
`status` is `PASSED`, `DEFEATED`, `EXECUTION_BLOCKED`, `PASSED_CONDITIONALLY` or `EXECUTION_PENDING`; a legacy record
with no status is read from its tally or ballots. `assign_office` and `vacate_office` are procedural and are left
out of S2 families, but their ballots still count in S1.

### Opening position

`opening` is the position before the negotiation, from structured state where the record has it, in this order:

1. The motion's own proposer opened in support (`opening_basis = proposer`).
2. A delegate that tabled a rival motion in the same family in the same month opened in support of that family
   (`opening_basis = tabled_motion`). This is the engine's strongest evidence: the delegate's own motion is its
   opening offer.
3. Otherwise the opening is the engine's keyword read of the delegate's private-position text
   (`opening_basis = private_position`): `initial_stance(pre_positions[member], motion)`, a copy of
   `analytics.initial_stance` with the engine's `MOTION_WORDS`. The subject's keywords are searched in
   `would_support` plus `preferred_policy` (support) and `would_oppose` plus `unacceptable_outcome` (oppose). Both
   or neither hit gives `unknown`; an unknown opening is not guessed.

The opening is mapped to a vote: support -> yes, oppose -> no.

### Response position

`response` is the stance the delegate recorded in the revision round for that motion,
`revisions[member].stances[motion_id]`, normalised as `convergence._norm_stance` does: `support -> yes`,
`oppose -> no`, `conditional -> conditional`, `abstain` stays abstain, `undecided` stays undecided.

### Rates

| Rate | Numerator | Denominator |
|---|---|---|
| Opening-to-final (`opening_share`) | pairs whose final vote is the other way from a known opening | pairs with a known opening (`support`/`oppose`), a yes/no final vote, and a delegate other than the motion's own proposer |
| Response-to-final (`response_share`) | pairs whose final vote differs from a yes/no response stance | pairs with a yes/no response stance and a yes/no final vote |

A conditional response is a condition being met, not a change of mind, and is not counted (the engine's rule). An
abstention is not a yes/no vote and is not in either denominator. A proposer is excluded from the opening rate
because its own motion makes the opening trivially support; it is included in the response rate, where the response
stance is informative.

Output: `position_change_rates.csv` (per model, then `office: <name>` rows) and `position_changes.csv` (the
pair-level audit with every field above). A positive share means the delegate voted against the position it opened
on.

## Secondary measure S2: disagreement in debate against the final vote

Unit: one motion family in one month with at least one final vote.

### Motion family

`motion_families` is a copy of `convergence.families` at engine 26, deliberately narrow:

- `settle_arrears` is one family whatever its subject (the funding mechanism differs, the question does not).
- Every other substantive motion is keyed by `type` and `subject.casefold()`.
- Charter amendments (`type = amend`) are linked by the engine's word test: at least 6 shared content words, Jaccard
  similarity at least 0.20, and at least 2 shared anchor words (content words minus the engine's boilerplate list).
  Linking is transitive. An amendment with no such partner is its own family.
- `assign_office` and `vacate_office` are procedural and are not in any family.

The family label in the output is `type:subject`, `settle_arrears`, or `amend:<root motion id>`.

### Components

- `response_opposition`: the number of recorded revision-round stances equal to `oppose` on any motion in the family.
  This is the engine's opposing-stance component.
- `competing_alternatives`: the number of family motions that reached the floor: recorded `status` in `PASSED`,
  `DEFEATED`, `WITHDRAWN` or `SUPERSEDED` (the engine's `live` states).
- `contested_withdrawals`: when the family holds more than one motion, the number of its motions withdrawn or
  superseded (declared `withdrawn`, or status `WITHDRAWN`/`SUPERSEDED`, including withdrawals listed in the revision
  round).
- `divergence_score`: the engine's `_divergence` formula applied to this one family:
  `2 * min(3, live_contest) + min(4, response_opposition) + 2 * min(2, contested_withdrawals)`, where
  `live_contest` is 1 when the family holds more than one live alternative and 0 otherwise. The level is `NONE` at 0,
  `LOW` up to 2, `MODERATE` up to 5, `HIGH` above 5, exactly as the engine labels the monthly score.
- Final tally: yes, no and abstain ballots across the family's voted motions. If a motion records `eligible_voters`,
  only those seats are counted; otherwise every seat with a ballot is counted. A delegate with no ballot is not an
  abstention.
- `final_dissent`: no ballots plus abstain ballots. An abstention breaks unanimity in the engine, so it is dissent
  against the final vote here too.
- `gap = response_opposition - final_dissent`. A positive gap means intermediate opposition did not reach the final
  ballot (some opponents ended up voting yes, or abstained after opposing). A negative gap means more dissent
  appeared at the final vote than the response round recorded. Zero means the recorded opposition carried through,
  or there was none on either side.

Output: `debate_disagreement.csv` (one row per family per month) and `debate_by_family.csv` (aggregated over runs:
family-months, motions, ballots, total response opposition and final dissent, ballot-weighted dissent share, mean
divergence score, and the mean per-family-month gap).

## Diagnostic, not a measure: VOTE_INTENT_MISMATCH

The engine's `VOTE_INTENT_MISMATCH` flag (`council.py`, reason-based rule, T144) is a diagnostic. The wave-3 reviewer
dropped it from the paper's measures; the T144 re-audit and Jev's second annotation may validate it later. It is not
part of P3 and no conclusion rests on it. The script keeps it for traceability in `vote_intent_diagnostic.csv`
(`group`, `seats`, `votes`, `vote_intent_mismatches`, `vote_intent_share`), and `summary.md` has a section headed
"Diagnostic, not a measure". `mismatch_rates.csv` contains only the P3 execution and directive rates.

## Output files added in wave 3

| File | Content |
|---|---|
| `position_change_rates.csv` | S1 counts and shares per model and formation office |
| `position_changes.csv` | S1 pair-level audit (opening, basis, response, final vote, both change flags) |
| `debate_disagreement.csv` | S2 family-month audit (opposition, alternatives, withdrawals, score, tally, gap) |
| `debate_by_family.csv` | S2 aggregated per family |
| `vote_intent_diagnostic.csv` | the vote-intent diagnostic, explicitly not a measure |
| `km_by_model.svg`, `km_by_office.svg`, `km_first_exit.svg` (and `_validated` variants with labels) | survival curves |

## What is not in this script

- No Cox proportional-hazards model. The survival analysis is Kaplan-Meier and restricted means only. The wave-3 plan
  made the regression optional ("no regression model unless time remains"); it was not added.
- No kappa or alpha. Agreement statistics live in `tools/exit_audit.py`. This script does not recompute annotator
  agreement.
- No imputation. A missing field is reported as unknown, blank or `NA`, never guessed.
- Bootstrap coverage is not simulated; the seed determinism and the no-estimate rule are tested.

## Tests

`tests/test_engine24_study_analysis.py` and `tests/test_engine24_study_statistics.py` cover the formulas:

- Kaplan-Meier and restricted means against hand values, censoring, the seed-fixed bootstrap and the no-estimate
  rule;
- `km_path` against a hand-computed step curve, well-formed and escaped SVG output, the 8-group cap, the empty
  figure;
- S1 opening bases and rates by hand, the proposer exclusion, the tabled-rival rule, conditional and abstention
  exclusions;
- S2 by hand, a contested withdrawal, and the amendment-family rule;
- an end-to-end synthetic grid that writes every table and figure, and a diagnostic-separation test.

The tests write their own run folders in temporary directories; they never read `research\runs` and never call a
model.
