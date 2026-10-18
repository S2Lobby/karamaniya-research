# Regime realism (world engine 33)

Status on 2026-10-18: implemented on the `regime-realism` branch (base GitHub main `274ad98`: WORLD_ENGINE 32,
AGENT_PROMPT 30, PSYCHOLOGY 8, ERROR_TAXONOMY 8). It is **not merged to main and not pushed**: nothing merges before
the SocioVerse batch is recorded and the user says so. The default is `legacy`, so a run that does not name the
option is byte-identical to engine 32. The RR-1 decisions are in `notes/regime-realism-decisions.md`; the workstream
reports are `reports/rr-uprising.md`, `reports/rr-relief.md`, `reports/rr-comparisons.md` and `reports/rr-profile.md`.

The run that motivated it is `research/runs/20261018-014944-seed1` (unobserved, menu harness, model neighbours,
`revolution` in Month 18). Four findings:

1. The national uprising chance read approval and unrest only. A provisional government that kept every democratic
   promise fell exactly as a junta did.
2. A lethal crackdown was a certain win whenever security cleared .55: no force ever refused an order.
3. Talks were inert below about 30% approval, exactly when a government needs them; nothing the government delivered
   was remembered.
4. The comparison councils faced rule-played neighbours, so the recorded run's invasions never happened beside it,
   and a run's only verdict was survive-or-not.

## 1. The run option

```
[run]
uprising_model = "legacy"        # default; engine 32 exactly
uprising_model = "legitimacy"    # the four changes below
```

- `config.RUN_DEFAULTS` carries `"legacy"`; `normalize_config` validates and lowercases it, and `new_run` checks the
  dict-config path as it checks the other arms.
- `runner.apply_run_options` stamps `world.uprising_model` and, under `legitimacy`,
  `world.institutions["uprising_model"]`, which a checkpoint keeps. Under `legacy` the key is not written, so a
  default checkpoint is engine 32's.
- `manifest.build` records a non-default model and `manifest.divergences` names `uprising_model` when two runs differ.
- `tools/study_grid.py` takes `[study] uprising_models = ["legacy", "legitimacy"]` (default `["legacy"]`); a
  non-default value prefixes the row name (`sv-legitimacy-...`) after a non-default harness token.
- Nothing in a prompt changes: `AGENT_PROMPT` stays 30 and `tools/prompt_freeze.py` reports the same 83 prompts under
  both settings.

## 2. The legitimacy factor (RR1, plan 4.1)

Under `legitimacy`, `politics._revolution` keeps its thresholds (approval < .20 and unrest > .45) and its formula, and
multiplies the chance by `L`:

```
D      = world.democracy_index(w)
elected = 1 if the government won a fair election, else 0
near   = 1 - months_left / 12, clamped, for a credible vote within 12 months; else 0
L      = max(L_MIN, 1 - a * D * (1 + elected) / 2 - b * D * near)
```

`a = .30`, `b = .30`, `L_MIN = .50` (the user's decision 2: at most half the odds). A provisional government far from
a vote gets a 13.5-15% cut; a fair election won doubles the base term to .30; the last year before a credible vote
adds up to a further .30. `near` is 0 when the vote is postponed past its Charter date (or past the due date a win
recorded), cancelled, rigged, or a coup fell within 12 months. A rigged winning count that kept the Council List in
power does not count as `elected` once the conduct setting is set back to fair.

The month row gains `uprising_check` with approval, unrest, security, war factor, `D`, `elected`, `near`, `L`, the base
and final chance, the draw and whether it fired. It is written every month, including the zero-chance months where no
draw is taken; under `legacy` the key is absent. The existing `"politics"` draw is still the one the check takes, in
the same place, so no other political draw moves.

## 3. The crackdown is a gamble (RR1, plan 4.2)

Under `legitimacy`, when a fired uprising meets `protest_response == "lethal"` and security > .55, the engine draws
obedience separately for the police and the army on `rng_for(seed, month, "uprising_crackdown")` (police first):

```
obey(force) = clamp(.64 + .45*loyalty + .20*bond - .25*[unrest > .6] - .15
                    - min(.15, max(0, arrears) * .03), .05, .98)
```

The `.64` base is the RR5 calibration (section 5): over loyalty .55-.65 and bond .2-.3 the both-obey failure chance is
29.0-39.6%, inside the proposed 20-40% band; RR1's draft `.62` gave 32.4-42.6% and was outside it at the low end.
The regional formula in `society._protests` is unchanged.

- Both obey: the old massacre (0.08% of the population, grievance +.15, fear +.2, League trust -.3) plus a 3-month
  backlash: two grievance reactions in the regions that rose (`.03` with decay .9 and `.01` for the unrest side;
  `public_mood` has no unrest kind).
- One refuses: with `civil_war = "on"`, `civil_war.start(w, "crackdown_split", plotters=[holder], divisions=...)`; the
  refusing force's refusal share is its rebel share, the force that obeyed holds its whole share for the government,
  and the other armed office keeps its anticipated split. With the arm off, the uprising succeeds.
- Both refuse: the uprising succeeds even with the arm on (no government force is left to fight).
- The refusing office vacant: the uprising succeeds; no commander is invented.
- The draws, probabilities, refusing forces and outcome (and the civil-war cause, leader and rebel share) are recorded
  in `uprising_check["crackdown"]`.

## 4. Concessions and the grace period (RR2, plan 4.3-4.4)

Under `legitimacy`, the `negotiate` response of `society._protests` uses
`credibility = max(approval credibility, concession credibility)`. The existing cap stays: `relief = .02 + .13 *
credibility`, at most .15 a month, which cannot outlast real hardship. Concession credibility is political memory of
what the government delivered, decaying linearly over six months:

| Concession | Credited to | Credit |
|---|---|---:|
| status upgrade, central -> cultural or devolved | the upgraded region | .40 |
| amnesty transition to release | every region | .30 |
| regional fund begins paying a region | that region | .25 |
| repeal of rationing, price controls or requisition | regions whose protest named it | .30 |
| minority restored to equal after a restriction | the Vell Highlands | .35 |

Events are deduplicated: one status change, one amnesty transition, one fund transition, one repeal and one minority
restoration each count once, at the month it happened. The memory is a separate channel from the direct effect of the
same act (a status grant still raises approval as it always did, an amnesty still lowers grievance); the cap is what
keeps talks from switching unrest off. The talks' event carries the credibility, both inputs and the concessions that
counted.

Because no protest cause was recorded, `regime_relief.record_protest_cause` writes a deterministic per-region,
per-month entry in `w.institutions["protest_causes"]`: the largest live driver among hunger, repression, status envy
and the measures in force (rationing, price controls, requisition, minority restriction). It uses no draw, writes no
text a delegate sees, and is read only to credit a repeal.

The grace period: when a different head of government takes office, `public_mood.react(w, "approval", where="*",
value=.03, months=3, decay=.5)` grants one reaction a month for three months, halving. It is granted at most once in
12 months, not when the change is in the coup month or the month after, and at half strength when the new head already
held another office (a reshuffle among the same people). The record states the reaction, the scale and why; the actual
approval move is smaller (about .022 in the first month), because the channel's value is a monthly modifier.

Under `legacy` every function in both modules is inert and a scripted engine-32 run replays identically.

## 5. Fair comparisons (RR3, plan 4.5)

`baseline.MODES` keeps the four rule-played councils and adds `scripted_replayed` and `passive_replayed`.
`baseline.compute` reads the finished run's `log.jsonl` through `backends/replay.py` and passes a replay cabinet
backend only to the two replayed modes; the four rule modes keep their stand-in cabinets. A recorded act the comparison
world refuses is recorded as skipped with its month, actor, action and reason, beside the acts applied. Every mode's
result and delta names its neighbours (`rule-played` or `replayed from <run>`), and the report prints that line, up to
three refused acts, and the limitation: replayed neighbours do not react to the comparison council. A run without
recorded cabinet answers gets the four rule modes and the report says why; the log running out fails that comparison
mode with its reason rather than silently truncating it. `calibration.py` and `tools/calibrate.py` use `RULE_MODES`
only: a bare seed has no log to replay.

## 6. The outcome profile (RR4, plan 4.6)

`scorecard.outcome_profile` reports six areas, each stated against the replayed comparison where one exists:
survival (months, exit), human cost (excess deaths by cause per 100,000 on the first month's population, emigration),
democracy (minimum and mean index, months of repressive acts, lethal crackdowns), living standards (real wage, food
ratio minima and means, unemployment, peak inflation), stability (mean approval and unrest, months in the uprising
zone) and outside pressure (months at war, regions lost, foreign campaigns and exposures). The report has a profile
section and orders comparisons `scripted_replayed`, `passive_replayed`, `scripted`, `passive`; `tools/study_analysis.py`
writes `profile_by_model.csv`, `profile_by_office.csv` and `profile_by_run.csv`. There is no composite score.

## 7. Calibration (RR5)

`tools/regime_sweep.py` plays four scripted councils (the stand-in personas, passive, all-hawk and all-dove) over
seeds 1-12, both models and three presets, 288 runs in all, plus 144 forced crackdown probes. Each run is a real
engine run through the same `World`, `Council` and `ScriptedBackend` a baseline uses, with the option stamped by
`apply_run_options`; it keeps no run folder. The JSON is `reports/regime-sweep.json`.

- `default`: a baseline's own starting state.
- `stress`: after formation, approval .16, unrest .55, grievance .85, `lethal`, police and army loyalty .60 and bond
  .25. It is a calibration harness, not a scenario; it tells delegates nothing.
- `relief`: the same hardship with `negotiate`, the Kessel regional fund and an amnesty already in force. An active
  council chooses its own response in Month 1 and overrides the preset; the passive council leaves it, so the relief
  preset's talk evidence comes from the passive mode.

Results (proposed bands, adopted by the lead under the user's delegation; the user may change them at RR-2):

| Band | Result | Met |
|---|---|---|
| A quiet run never ends in revolution | 0 of 120 quiet runs (72 default and 48 relief runs with no zone month) | yes |
| Stress-run revolution share under legitimacy within half to all of legacy | 48/48 vs 48/48 stress pairs, ratio 1.00; mean months governed 2.81 vs 2.42 | yes |
| A crackdown at security .55-.65 fails in 20-40% of cases | forced sample 44/144 = 30.6% (100 massacres, 44 uprising successes); analytic census 29.0-39.6% at base .64 | yes |

The stress preset is severe enough that both worlds end in revolution in every run; what legitimacy buys there is time
(mean 2.81 vs 2.42 months, and up to 9 months for one council). The rate band is met at equality, not by a lower
share. Real councils may sit between the quiet and stress presets, which is where the legitimacy cut and the relief
channels have room to change an exit; the scripted sweep cannot show that.

In-run crackdowns are rare: the scripted councils' police loyalty falls below the lethal gate (at security .60 they
attempted 1 and failed 1), which is why the band is carried by the forced probe sample. The relief preset produced 767
talks, 360 of them with concession credibility above zero, maximum .55; the honeymoon channel was granted 0 times in
the sweep because no scripted council changed its head of government. The grace path is covered by
`tests/test_rr2_relief.py`, not by the sweep.

## 8. What-if table on the recorded run (final constants)

The inputs are the recorded run's history; no new run. `p` is today's formula, `L` uses the final constants, and
`near = 0` for every row (the Charter vote is 18-25 months away and the government is not elected). Crackdown columns
use the row's own force loyalty, bond and arrears with the final `.64` base.

| Month | approval | unrest | security | D | L | p today | p with legitimacy | obey police | obey army | crackdown success | crackdown failure |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 11 | .196 | .467 | .596 | .95 | .8575 | .0151 | .0129 | .8329 | .8252 | .6873 | .3127 |
| 12 | .190 | .504 | .598 | 1.00 | .8500 | .0711 | .0605 | .8350 | .8298 | .6929 | .3071 |
| 13 | .182 | .517 | .599 | .95 | .8575 | .0955 | .0819 | .8370 | .8340 | .6981 | .3019 |
| 14 | .172 | .528 | .600 | .95 | .8575 | .1221 | .1047 | .8390 | .8379 | .7030 | .2970 |
| 15 | .142 | .554 | .601 | .90 | .8650 | .1901 | .1644 | .8410 | .8413 | .7075 | .2925 |
| 16 | .135 | .572 | .601 | .90 | .8650 | .2196 | .1899 | .8429 | .8444 | .7117 | .2883 |
| 17 | .151 | .528 | .576 | .90 | .8650 | .0964 | .0834 | .8230 | .8469 | .6970 | .3030 |
| 18 | .129 | .562 | .575 | .90 | .8650 | .1390 | .1203 | .7667 | .7507 | .5756 | .4244 |

P(no uprising over Months 11-18) is **.357** today and **.416** with legitimacy: the factor alone would not have saved
this council. The concession and grace channels are the ones that would have to do the rest, which is the plan's
design. At these forces a crackdown would have failed 29-42% of the time, slightly wider than the fixed-force census
because the army's bond is high in this run and police loyalty falls in Month 18.

## 9. Legacy identity and prompts

- `python tools/replay_run.py reports/rr-base-36/base-seed1` on the final branch: "identical: the 37 month records and
  the final checkpoint match the original", and all 539 prompts are sent again unchanged.
- `python tools/prompt_freeze.py`: "prompts unchanged". The same check with `uprising_model = "legitimacy"` forced on
  the four-month scripted run: "prompts unchanged", 83 of 83 prompts.

## 10. Limitations

- Scripted councils are not models. The bands are a property of the world rules, not a forecast of what a model
  council does; they are checked again on the user's first real runs under the new model.
- The stress preset is synthetic and severe: its result is about the legitimacy cut's arithmetic, and the sample
  ends with everyone falling. The quiet runs show the other end. Nothing in the sweep samples the middle.
- Replayed neighbours give the answer they gave in the run and do not react to the comparison council.
- The grace period is not exercised by the sweep; it is unit-tested.
- The near-vote term is unit-tested but not exercised by a real run ending near a fair election.
- The concession credits (.40/.30/.25/.30/.35) are starting values; the sweep shows they fire and decay, not that
  those sizes are the right ones. Real runs are the evidence that would set them.
- The `legacy` option keeps the old world for replication. The recommendation is `legitimacy` as the default once the
  user accepts the RR-2 bands and the SocioVerse batch is recorded.

## Appendix A: every path by which the government ends or survives (RR0)

| Path | Condition | Draw stream | Outcome / effect | What delegates see |
|---|---|---|---|---|
| National uprising | approval < .20 and unrest > .45, then `p` below | `rng_for(seed, month, "politics")` | `revolution` / `revolution_union`; every member removed | approval and unrest levels; never the rule or the chance |
| Lethal crackdown | same roll, `protest_response == "lethal"` and security > .55 | same roll, then `"uprising_crackdown"` under legitimacy | legacy: massacre, government survives. legitimacy: massacre + backlash, a split, or an uprising success | the crackdown, split or refusal events |
| Army officers' coup | army loyalty < .30 and (arrears >= 3 or army vacant >= 3), 12% | `"politics"` | `officers_coup`; every member removed | unpaid bills and army reports |
| Officers' plot | `plots.monthly` detection and coup | `"plot-detection"`, `"plot-coup"` | `officers_coup` | the Interior's special-branch report if found |
| Council coup | a member's `coup` decision | `"coup"` | success removes targets and sets `coup_month`; failure can start a civil war (engine 32) | the coup decision and event |
| Handover | `handover_month == month` | no draw | `voted_out`; every member removed; suspended in a civil war | the election result and the rule in the prompt |
| Civil war | failed coup with a loyal force, split handover, or a split crackdown, with `civil_war = "on"` | `"civil_war"`, `"civil_war_combat"` | victory, settlement, partition or collapse | the faction prompt every month |
| Resignation / expulsion / lost seat | a decision, a motion, or the election | votes / election | member removed | the event and result |
| Vacancy / no government | every member removed or inactive | — | `no_government` | the vacancy in the briefing |
| Knockout | `knockout = {office, month}` | no draw | the holder is removed as `incapacitated` | an in-world illness event |

## Appendix B: the archive before this work (RR0)

`research/runs` held 15 readable checkpoints on 2026-10-18: one revolution
(`20261018-014944-seed1`, Month 18, minimum approval .129, maximum unrest .572), two `voted_out`, one `no_government`,
and ten unfinished runs. There was no officers' coup and no lethal crackdown in the corpus, so the calibration targets
had to come from new scripted sweeps.

## Appendix C: what each concession already rewards (RR0)

Status upgrades raise approval immediately and carry monthly status terms; amnesty lowers grievance and fear, raises
approval and police loyalty once; the regional fund lowers grievance and raises income and industry; a repeal has only
economic effects and no direct political credit; a minority guarantee changes the Highlands' trust multiplier. The
six-month credibility in section 4 is political memory on top of those effects, capped; it is not a second direct
effect.

## References

The plan's section 12, each checked on Crossref on 2026-10-18: Goldstone et al. 2010; Hegre et al. 2001; Lichbach
1987; Davenport 2007; Francisco 2004; Stephan and Chenoweth 2008; Nepstad 2011; Mueller 1970.
