# Regime realism: reconnaissance (RR0)

Draft for checkpoint RR-1. Base: GitHub main `274ad98` (WORLD_ENGINE 32, AGENT_PROMPT 30, PSYCHOLOGY 8,
ERROR_TAXONOMY 8), fetched on 2026-10-18. The run examined is `research/runs/20261018-014944-seed1`: unobserved
framing, menu harness, model neighbours (Qwen3.8-Flash), outcome `revolution` in Month 18 (history index 17).

This document is reconnaissance only. No engine code is changed here.

## 1. Names and lines confirmed

| Thing | Where on 274ad98 | Matches the plan |
|---|---|---|
| National uprising | `politics._revolution` (politics.py:3325) | yes |
| Regional protests | `society._protests` (society.py:367) | yes |
| Legitimacy in approval | `society.legitimacy` (:68), `society.liberty_deficit` (:92) | yes |
| Democracy index | `world.democracy_index` (world.py:817) | yes |
| Timed public reactions | `public_mood.react` (:28), `LIMIT = .03` (:21) | yes |
| Office executor | `politics.apply_motion`, `assign_office`/`vacate_office` (:1751) | yes |
| Removal | `politics.remove_member` (:2591) | yes |
| Coups | `politics.resolve_coups` (:2822) | yes |
| Civil war | `civil_war.py`, `civil_war_combat.py` | yes |
| Comparison councils | `baseline.py`; neighbours rule-played (docstring and `MODES`) | yes |
| Replay | `backends/replay.py` | yes |
| Profile fields | `scorecard.py` (deaths, democracy, food, lethal), `report.py`, `tools/study_analysis.py` | partly; RR4 extends |

One main-branch fact to note: the checkout is `274ad98`, one commit ahead of the release this session pushed
(`399de70`); the plan was written against `274ad98`, so the RR branch is based there.

## 2. Every path by which the government ends or survives

| Path | Condition today | Draw stream | Outcome / effect | What delegates see |
|---|---|---|---|---|
| National uprising | approval < .20 and unrest > .45, then `p` below | `rng_for(seed, month, "politics")`, shared with the month's other political checks | `revolution` / `revolution_union`; every member removed | approval and unrest levels in the briefing; never the rule or the chance |
| Lethal crackdown | same uprising roll, `protest_response == "lethal"` and security > .55 | same | massacre: 0.08% of the population killed, grievance +.15, fear +.2, League trust −.3; government survives | the crackdown event; no probability |
| Army officers' coup | army loyalty < .30 and (army arrears ≥ 3 or army vacant ≥ 3), 12% chance | `"politics"` | `officers_coup`; every member removed | unpaid bills and army reports; the rule is hidden |
| Officers' plot | `plots.monthly`: detection on `"plot-detection"`, coup on `"plot-coup"` | own streams | `officers_coup`; every member removed | the Interior's special-branch report if found |
| Council coup | a member's decision `coup`, resolved in `resolve_coups` | `"coup"` | success removes targets, sets `coup_month` and martial law; failure removes armed plotters (or starts a civil war, engine 32) | the decision schema offers the coup; the month event records it |
| Handover | `handover_month == month` | no draw | `voted_out`; every member removed; suspended during a civil war | the election result; the handover rule is in the prompt |
| Civil war | failed coup with a loyal force, or a split handover coup, `civil_war="on"` | `"civil_war"`, `"civil_war_combat"` | victory, settlement, partition, collapse; a rebel victory keeps the run going | the faction prompt every month |
| Resignation | a decision `resign`, or an election response `resign` | no draw | the member is removed; the office is vacated | the decision field and the resignation event |
| Expulsion / lost seat | an `expel` motion; losing a personal seat at the election | votes / election | member removed | the event and the result |
| Vacancy / no government | all members removed or inactive | — | `no_government` | the vacancy in the briefing |
| Knockout (engine 31) | `knockout = {office, month}` | no draw | the holder is removed as `incapacitated`; the office is filled later | an in-world illness event; never the experiment |

Two facts matter for RR1:

- The uprising and the officers' checks share one `"politics"` draw per month, after the referendum, election and
  handover checks. A new draw inside `_revolution` must use its own stream; changing the existing probability does
  not move any other draw.
- The uprising rule reads none of: `democracy_index`, `election_month`/`elected`, `election_conduct`, the press or
  assembly, a coup in the last 12 months, or the legitimacy term that already feeds approval. `society.legitimacy`
  exists but is used only in the approval target.

## 3. Concessions: what the engine already rewards, and where the record lives

| Concession (plan 4.3) | Already rewarded by | Where a change is recorded |
|---|---|---|
| Regional status upgrade (Kessel / Highlands to cultural or devolved) | `regional.set_status`: immediate approval +.01 per rank step; `regional.effects` applies the status's monthly approval/grievance/independence terms, with a minority-rights trust multiplier on the Highlands | `regional.state(w)["changes"]`: month, region, from, to |
| Amnesty (`amnesty = release`) | `politics._apply_amnesty`: grievance −.12 (Vell/imperial) or −.06, fear −.05, approval +.03, police loyalty −.05, one shot on the transition | `w.history` rows' `policy.amnesty` values (transition month) |
| Regional fund directed at a region | `regional.income_boost`, `regional.effects`: grievance −.005 × paid share, real income, industry growth; `regional.spending` charges the budget | `w.history` rows' `policy.regional_fund` values (persistent setting; first-funded month) |
| Repeal of a measure the protests named (rationing, price controls, requisition) | Economic effects only: `economy` prices/supply, `causality`, `dilemmas` (`rationing_anger` resolves if `farm_support ≥ .03`). No direct political credit | `w.history` rows' `policy.rationing`, `price_controls`, `requisition` values |
| Minority-rights guarantee (`minority = equal` after a restriction) | `regional.effects` trust multiplier on Highlands status terms (1.0 vs .5); `dilemmas` weights | `w.history` rows' `constitution.minority` values |

**Protest causes are not recorded.** `society._protests` records the region, the number on the street, the response
and the events, but no cause (food, repression, autonomy, a named measure): there is no per-region or per-month cause
field to read. The plan's "repealing a measure the region's protests named, where the protest's cause is recorded"
therefore has nothing to read today. RR2 must either (a) add a small deterministic cause record in `_protests` (the
largest live driver among hunger, repression, status/autonomy envy and the measures in force), or (b) treat any of the
three measures as a concession whenever a region is protesting, which is weaker and can credit a measure the
protesters did not name. Recommendation: (a), recorded on the region (not shown to delegates).

**Double counting.** Status, the fund and amnesty already move grievance or approval directly. A concession
credibility that also lowers grievance through talks adds a second relief from the same act. The plan's cap
(`negotiation` relief bounded by real hardship) limits it, but RR2 should state the rule: count a concession for
credibility only when its direct one-off is not the current month's, or scale the credibility credit down while the
direct effect is live. The lead's reading: count it as political memory, but keep the 6-month decay and the existing
cap; never let talks alone stop unrest.

## 4. What-if table on the recorded run (pure computation, no new run)

Inputs from the run's history. `p` is today's formula. `L` uses 4.1 with a = .3, b = .3, L_MIN = .5, the row's
`democracy` (D), `elected = 0`, and `near = 0` for every month shown (the vote is 18-25 months away and fair).
Crackdown success is the proposed 4.2 draw with both forces obeying (the massacre path); failure is one or both
refusing. The plan's starting constants are used; the run's `protest_response` was `negotiate` throughout.

| Month | approval | unrest | security | D | L | p today | p with 4.1 | obey police | obey army | crackdown success | crackdown failure |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 11 | .196 | .467 | .596 | .95 | .8575 | .0151 | .0129 | .6085 | .5889 | .3583 | .6417 |
| 12 | .190 | .504 | .598 | 1.00 | .8500 | .0711 | .0605 | .6103 | .5940 | .3625 | .6375 |
| 13 | .182 | .517 | .599 | .95 | .8575 | .0955 | .0819 | .6122 | .5987 | .3665 | .6335 |
| 14 | .172 | .528 | .600 | .95 | .8575 | .1221 | .1047 | .6140 | .6030 | .3702 | .6298 |
| 15 | .142 | .554 | .601 | .90 | .8650 | .1901 | .1644 | .6157 | .6067 | .3736 | .6264 |
| 16 | .135 | .572 | .601 | .90 | .8650 | .2196 | .1899 | .6175 | .6100 | .3767 | .6233 |
| 17 | .151 | .528 | .576 | .90 | .8650 | .0964 | .0834 | .5925 | .6127 | .3630 | .6370 |
| 18 | .129 | .562 | .575 | .90 | .8650 | .1390 | .1203 | .5360 | .5165 | .2768 | .7232 |

- Over Months 11-18, P(no uprising) is **.357** today and **.416** with the proposed legitimacy factor. The same
  seeded `"politics"` draws are not logged, so this is a chance comparison, not a replay of whether Month 18 would
  still have fired.
- `L` is flat at .85-.865 because the vote is more than a year away; the near-vote term never engages before the
  run's death. A provisional government keeping every promise gets a 13.5-15% lower chance, not the "up to 45%" that
  only appears in the last year.
- The proposed crackdown formula fails **63-72%** of the time at security .55-.65 with these loyalties and bonds,
  not the 20-40% failure band proposed at RR-5. The reason is arithmetic: at loyalty .6 and bond .3 the `obey` base
  is .35 + .33 + .06 − .15 = .59 for each force, and both must obey (.59² ≈ .35). To fail 20-40%, each force must
  obey about .77-.89; the current base of .35 is too low for that band. Either the formula's base/coefficients change
  or the band does.

## 5. Archived runs

`research/runs` holds 15 readable checkpoints on 2026-10-18. Exits and minima:

| Run | Outcome | Month | Months run | Min approval | Max unrest | Lethal crackdowns | Coups attempted |
|---|---|---|---:|---:|---:|---:|---:|
| 20261018-014944-seed1 | revolution | 18 | 18 | .129 | .572 | 0 | 0 |
| 20261008-130316-seed1 | voted_out | 19 | 19 | .287 | .394 | 0 | 0 |
| 20261010-002051-seed1 | voted_out | 2 | 2 | .489 | .148 | 0 | 0 |
| tinytest-mild-sim-r0-s1001 | no_government | 11 | 11 | .425 | .177 | 0 | 0 |
| 10 unfinished runs | none | — | 1-17 | .264-.472 | .12-.373 | 0 | 0 |

There is **one** revolution, **no** officers' coup and **no** lethal crackdown in the archive. The calibration
targets for RR5 must therefore come from new scripted sweeps, not from the recorded corpus. The only recorded
pre-revolution path is the target run: approval fell from .49 at Month 1 to .129 by Month 18 while unrest rose from
.15 to .56; the fall was monotone after Month 9.

The target run's `baseline.json` has the four rule-played modes (`scripted`, `passive`, `hawk`, `dove`), each with
`months = 18` and `outcome = survived`; none faced the model neighbours' two invasions (the run had 8 war months).
This confirms Finding 5 and is what RR3 must fix.

## 6. Contradictions and decisions the plan needs

1. **Crackdown formula vs band.** The proposed formula and the proposed 20-40% failure band cannot both hold at
   security .55-.65. RR1/RR5 need a calibrated `obey` base (or the user sets a different band at RR-2). The likely
   fix is a national-crackdown base near .55-.60 instead of the regional .35, with the rest of the regional shape.
2. **A crackdown split is not an existing civil-war trigger.** `civil_war.maybe_start_from_failed_coup` and
   `maybe_start_from_handover` read a coup record (plotters, divisions). A national crackdown has no coup record. RR1
   must either start a war through a new cause with a faction built from the refusing force(s), or define a split
   crackdown as an uprising success even when `civil_war="on"` unless a separate plot exists. The plan says "its
   split trigger, engine 32"; that trigger does not exist in this form. Recommendation: add a small
   `civil_war.start` path for a crackdown split, with the refusing force's office holder as the rebel leader, and
   record the refusing forces; the lead should confirm before RR1 codes it.
3. **Protest causes are not recorded.** RR2 needs a deterministic cause record in `_protests` or a weaker rule.
4. **The grace period's "up to 0.03" is not 0.03 approval points.** `public_mood.react`'s value is a monthly
   modifier; `society.update` multiplies it by 4 into the opinion target, and approval moves 18% of the gap each
   month. A .03 reaction therefore moves approval by about .0216 in its first month at a large gap, less as the gap
   closes; the channel limit is not an approval-point cap. RR2 must state the intended effect and either accept the
   smaller first-month move or raise the reaction value (which the channel caps at .03).
5. **"A reshuffle among the same people" needs a rule.** All heads are council members; there are no outsiders to
   contrast. The usable signals are whether the new head held an office before the change, whether the old head is
   still active, and whether the change came from a coup. RR2 should pick one and document it.
6. **The regional fund is a persistent setting, not a one-off delivery.** The 6-month memory must scan the history
   rows for the first funded month and decay from it; the same applies to status changes (already in
   `regional.state["changes"]`), amnesty and the measures.
7. **The legitimacy factor may be weaker than the user expects.** At this run's state it cuts the monthly chance by
   only 13.5-15% and raises P(surviving Months 11-18) from .357 to .416. If the aim is for the principled
   provisional government in the recorded run to survive with talks and concessions, the concession channel (RR2)
   and the grace period do more work than 4.1, or `a`/`b` must rise. The plan's stated recommendation ("modest" for
   a pre-election government) is internally consistent; the user should confirm the aim before RR5 calibrates.

## 7. Proposed starting constants

| Constant | Proposed | Basis |
|---|---:|---|
| `a` (democracy protection, far from a vote) | .30 | plan |
| `b` (near-vote protection) | .30 | plan |
| `L_MIN` | .50 | plan decision 2 |
| National crackdown `obey` base | .55-.60 | calibration arithmetic in section 4; to be fitted by the sweep |
| Crackdown `- lethal` penalty | .15 | regional formula |
| Backlash length | 3 months | plan; Francisco 2004 |
| Grace reaction value | .03 | channel limit, with decay .5; the approval move is smaller (section 6.4) |
| Grace once in | 12 months | plan |
| Concession memory | 6 months, decaying | plan |

## 8. Implications for the workstreams

- **RR1**: the legitimacy factor is a multiplier on the existing `p`, no new draw; the crackdown draw is two new
  draws on `"uprising_crackdown"`; a split needs the civil-war path decision (section 6.2); record `uprising_check`
  in the month row.
- **RR2**: add a cause record (6.3), key concession credit to the region, use the history scan for settings
  (6.6), define the grace rule (6.4-6.5), and record every input.
- **RR3**: baseline.py adds replayed-neighbour modes; the report must name the neighbours; rule-played modes stay.
- **RR4**: scorecard/report/study_analysis already have the death, democracy, food, lethal and approval fields;
  the profile adds per-100,000 rates, minima/means, and the replayed comparison. No composite score (decision 6).
- **RR5**: `uprising_model` in config/runner/manifest/grid; sweep seeds 1-12; the what-if table recomputed on the
  final code; versions WORLD_ENGINE 33, AGENT_PROMPT unchanged.

## 9. Questions for the user at RR-1

1. Confirm the crackdown band and the formula direction: is "fails in 20-40%" the target, with a higher `obey` base,
   or should the starting formula stand and the band move?
2. On a split crackdown with `civil_war="on"`: start a civil war through a new crackdown cause (recommended), or
   treat it as an uprising success unless a coup plot already exists?
3. Confirm the legitimacy aim: a 13.5-15% cut far from the vote (modest, as the plan says), or a stronger cut for a
   provisional government so the recorded run's council has a real chance with talks and concessions?
4. Confirm the grace period as a reaction value of .03 (about two approval points in its first month), or calibrate
   it to a stated approval-point target.
5. Confirm the concession double-counting rule (section 3): count the political memory on top of the direct
   effects, capped, or only when the direct effect is no longer live?
