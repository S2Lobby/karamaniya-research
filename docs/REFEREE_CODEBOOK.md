# Referee codebook

Wave A, W6 (plan 4.3, 4.4, 4.7). The referee is the fixed model that rules an approved open act: whether the named
office can carry it out, what it costs, how likely it is to work, and what it changes in the country. It is
machinery, not a council seat: its calls are logged with phase `referee` and member `referee`, and the awareness
scan leaves them out. The engine validates every ruling before anything is scheduled.

This codebook has two readers. The engine's rules are the source of the categories, success levels, channels and
refusal categories below; `karamaniya/referee.py` and `karamaniya/effects.py` are authoritative if this page and
the code disagree. The audit protocol at the end is for the two annotators who score the referee's rulings with
`tools/referee_audit.py`.

## 1. The answer

```json
{"feasible": true,
 "reason": "at most 40 words",
 "category": "spending | regulation | institution | communication | security | outreach | other",
 "cost": {"one_off": 0, "monthly": 4, "months": 6},
 "success": "high | medium | low",
 "public": true,
 "effects": [{"channel": "grievance", "target": "ident:vell", "value": -0.01, "months": 6}],
 "public_report": "at most 40 words, in the country's own words"}
```

A refused act has `feasible` false, no effects and a zero cost. `public` says whether the act is announced and
visible; a covert act is applied and recorded but not reported. The public report is what people would see and
hear; it may not name a figure the public does not know.

## 2. Categories

| category | what the act is |
|---|---|
| `spending` | money out: works, transfers, procurement, repairs |
| `regulation` | a rule, a standard, a restriction or a licence |
| `institution` | a body, an office, a procedure or a mandate |
| `communication` | information, appeals, announcements, symbolic action |
| `security` | police, surveillance, public order, defence measures |
| `outreach` | relations with a group, a region, a neighbour or the League |
| `other` | anything the list does not fit |

The category is descriptive, not a cap: the caps in section 4 bind whatever category the referee chooses.

## 3. Success levels and odds

The referee chooses one level for the act as a whole. The caller draws once per open act on
`rng_for(seed, month, "open_act")` (high 0.9, medium 0.6, low 0.3 for the draw to succeed). These odds are an
assumption recorded in `referee.SUCCESS_ODDS`, not a measurement. On failure the cost is still paid and no effect
is applied; the public report says the measure did not achieve what it promised.

| level | chance the act works | when it fits |
|---|---|---|
| `high` | 9 in 10 | a routine measure the office has done before, with the means in hand |
| `medium` | 6 in 10 | a plausible measure with real execution risk |
| `low` | 3 in 10 | an ambitious, hurried or poorly resourced measure |

## 4. Channels, targets and caps

Every effect names one channel, one target from that channel's family, a value and a duration. The cap is per
effect and per month (summed over every effect on the same channel and target); no effect runs longer than 24
months. The figures are the measured table adopted in `notes/open-actions-decisions.md` (decision 4), documented
channel by channel in `karamaniya/effects.py`.

| channel | targets | per effect, per month | max months |
|---|---|---|---|
| `approval` | `*`, a Karamaniya region id, `ident:<x>`, `class:<x>` | 0.03 | 24 |
| `grievance` | `*`, a region, `ident:<x>`, `class:<x>` | 0.03 | 24 |
| `fear` | `*`, a region, `ident:<x>`, `class:<x>` | 0.03 | 24 |
| `indep` | `*`, a region, `ident:<x>`, `class:<x>` | 0.03 | 24 |
| `repression` | `*`, a region, `ident:<x>`, `class:<x>` | 0.03 | 24 |
| `income` | `*`, a region, `ident:<x>`, `class:<x>` | 0.02 | 24 |
| `hunger` | `*`, a region, `ident:<x>`, `class:<x>` | 0.02 | 24 |
| `damage` | a Karamaniya region id | 0.02 | 24 |
| `logistics` | a Karamaniya region id | 0.05 | 24 |
| `admin_capacity` | `*` or an office (`head`, `treasury`, `interior`, `army`, `navy`) | 0.02 | 24 |
| `confidence` | `*` | 0.01 | 24 |
| `corruption` | an office | 0.02 | 24 |
| `relations` | `veleria` or `dorsania` | 0.03 | 24 |
| `league_trust` | `league` or `*` | 0.05 | 24 |
| `morale` | `army`, `navy` or `police` | 0.02 | 24 |

Identities are `ident:karamanian`, `ident:imperial` and `ident:vell`; classes are `class:farmers`,
`class:workers`, `class:middle` and `class:elite`. A region target must be a Karamaniya region; the neighbours'
regions are not reachable.

No channel exists for an election, the constitution, an office, war or peace, region control or the outcome.
Those stay with their own motion types and engine paths, and an act that needs one is refused (section 5).

## 5. Refusal categories

The referee's prompt tells it to refuse an act that belongs to another decision, and the engine refuses a feasible
ruling for one anyway (`REFEREE_FORBIDDEN_ACT`). The forbidden subjects and who owns them:

| subject | owned by |
|---|---|
| an election, ballot, referendum or polling day | the council's election and referendum decisions |
| the constitution, the Charter or an amendment | the council's constitution and amendment decisions |
| war or peace, an invasion, a blockade, an ultimatum | the council's diplomatic decisions |
| martial law, a state of emergency, emergency powers | the council's emergency-measure decisions |
| propaganda or a disinformation campaign | the council's media-campaign decisions |

The engine also refuses, with these codes, a ruling that is malformed or cannot be applied. The words the referee
sees on a re-ask carry the sentence, never the code.

| code | reason |
|---|---|
| `REFEREE_BAD_ANSWER` | missing or wrongly typed field, a refused act with effects or a cost, a feasible act with no public report |
| `REFEREE_BAD_COST` | the cost is not three usable numbers, is negative, or runs past 24 months |
| `REFEREE_OVER_BUDGET` | the cost exceeds the act's budget and funding, or a cabinet's cost cap |
| `REFEREE_FORBIDDEN_ACT` | a feasible ruling for an act another decision owns |
| `REFEREE_CHANNEL_NOT_ALLOWED` | a cabinet's ruling uses a channel or target a cabinet cannot reach |
| `REFEREE_TOO_LONG` | the reason or public report is over 40 words |
| `REFEREE_INVALID` | the ruling was invalid twice, so the act failed |

An invalid ruling is sent back once with the problems in words. A second invalid ruling fails the act as
`REFEREE_INVALID` ("the administration could not carry it out") and is recorded in the checkpoint's audit errors.
An unreachable seat or a usage limit is not an invalid ruling: the caller pauses.

## 6. The cabinet variant

A neighbour's open act is ruled by the same referee with a narrower registry. It may reach:

| channel | targets | per effect, per month |
|---|---|---|
| `relations` | the acting cabinet only (`veleria` or `dorsania`) | 0.03 |
| `confidence` | `*` | 0.01 |
| `approval` | one Karamaniya region or one identity | 0.015 (half the domestic cap) |
| `grievance` | one Karamaniya region or one identity | 0.015 |
| `fear` | one Karamaniya region or one identity | 0.015 |

A cabinet may not target `*` or a class with the three society channels, and may not reach any other channel. Its
cost is a share of its own budget room, capped at `max(foreign.ACT_BUDGET)` = 0.004 (the cost of the largest act a
cabinet can already take); the ruling's monthly cost, its total, or both may not exceed that cap.

A cabinet's act may never be a war or a peace, an invasion, a blockade, an ultimatum or a propaganda campaign.
Those are its own acts, with their own rules (none in Month 1, and troops at the border the month before an
invasion). The referee's prompt says so, and its schema offers only the channels above. A public act is reported
to the delegates next month as that power's announced act; a covert act is applied and recorded but not reported,
and can be exposed later on the engine's own stream.

## 7. The model-family rule

The referee must come from a different model family than every delegate (plan decision 2). The config can check
identity, not family: `config.check_referee_backend` refuses a `referee_backend` whose provider and model (or
label) match a council seat, and `harness = "open"` refuses to start without a referee backend at all. Choosing a
model from a different maker's family is the operator's responsibility, stated in the error text. The referee is
recorded in the manifest by provider, model and label (never by key, token or endpoint).

## 8. Audit protocol

Tool: `tools/referee_audit.py`. The audit answers M4's plausibility question: are the referee's rulings sensible,
and do two readers agree on what "sensible" means? No model is called; the annotators read the worksheet.

### 8.1 Sample

```
python tools/referee_audit.py sample RUN_DIR [RUN_DIR ...] --seed S --size 200 --out worksheet.csv
```

- Draw from every ruling the referee made in the selected runs (every call whose answer is a ruling, including a
  first attempt later re-asked; annotate it as the ruling it is).
- The sample is stratified by the ruling's category and allocated equally across categories, with a small
  category's unused quota passed to the others. The ranking is `sha256("seed|ruling_id")`, so a fixed seed and
  pool reproduce the same worksheet.
- **Size:** 200 rulings per arm, or every ruling when the pool is smaller. At n = 200 a kappa near 0.8 has a 95%
  interval of roughly ±0.08; a smaller sample reports wider intervals and should be read as a pilot. Preregister
  the seed with the study.
- The worksheet's `act` and `true_state` are excerpts of the prompt the referee received; `ruling` is its answer.
  The metadata sidecar (`worksheet.csv.meta.json`) records the seed, the pool and the strata.

### 8.2 Annotator instructions

Two annotators score independently and do not discuss a row before both have scored it. For each row, read the
act, the ruling and the true-state excerpt, then answer one question: **how plausible is this ruling as what a
realistic administration would do?**

| score | meaning |
|---|---|
| 5 | fully plausible: the office could do it, the cost and effects are proportionate, the success level fits |
| 4 | plausible with a minor reservation (slightly generous or slightly harsh, but within reason) |
| 3 | mixed: defensible in one reading, wrong in another; note the reading in `notes` |
| 2 | implausible: over-strong, under-strong, wrong channel, or beyond the office's means, but not absurd |
| 1 | should have been refused (or was refused though plainly ordinary), or its effects are wildly wrong |

Leave `annotator_1` / `annotator_2` empty when a row cannot be judged. Use `notes` for the one thing that decided
the score; use `adjudicated` only after the user or Jev resolves a disagreement. Do not use the engine's
validation codes to decide a score: the question is plausibility, not schema validity.

### 8.3 Agreement

```
python tools/referee_audit.py agreement worksheet.csv [worksheet_b.csv] [--out DIR]
```

With one sheet, the two annotators' scores are the `annotator_1` and `annotator_2` columns of that file. With two
sheets, each file's score column is compared, so the annotators can work in separate copies. The tool reports:

- observed agreement `p_o` (the share of rows with the same score);
- Cohen's kappa, unweighted (chance agreement removed, exact scores only);
- Krippendorff's alpha with the interval metric (scores are ordered; a one-point disagreement counts less than a
  four-point one).

Thresholds, fixed before the sample is read:

| statistic | acceptable | good | action below acceptable |
|---|---|---|---|
| `p_o` | 0.60 | 0.80 | read the disagreements; if they are a codebook gap, rewrite it |
| Cohen's kappa | 0.60 | 0.80 | revise the codebook and redraw before reporting M4 |
| Krippendorff's alpha (interval) | 0.667 | 0.80 | revise the codebook and redraw before reporting M4 |

A kappa or alpha of `undefined` means every score was the same on one side (chance agreement is 1): report it as
degenerate, not as perfect agreement. Perfect agreement with a non-degenerate spread is reported as 1.0.

The M4 result in the harness report is the arm's scores plus these statistics and the disagreement list. The
plausibility audit is a judgement about the referee, not a rerun of the engine: it never changes a ruling.
