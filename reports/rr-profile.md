# RR4: the outcome profile

Branch `rr/profile`, worktree `C:\Users\litle\Karamaniya\karamaniya-test\rr4-profile`, based on `49a8d5b`.
Commit `490d62b`. Nothing was pushed or merged.

## What changed

- `karamaniya/scorecard.py`
  - `outcome_profile(history, months=None, outcome=None)` (RR4). One profile per run from the run's own history and
    counters, in six areas, with no composite score:
    - survival: months governed, exit type, exit month;
    - human cost: excess deaths and each of the eight scorecard death causes per 100,000 (famine, war, state
      violence, internment, coups, soldiers, political violence, border incidents), plus emigration and its rate;
    - democracy: minimum, mean and final index, months with a repressive act in force, lethal crackdowns;
    - living standards: real wage (final and mean), food ratio (minimum and mean), unemployment (mean and final),
      peak inflation;
    - stability: mean approval, mean unrest, months in the uprising zone (approval < .20 and unrest > .45, the
      engine's own thresholds in `politics._revolution`);
    - outside pressure: months at war, regions lost, foreign propaganda campaigns and exposures (from
      `analytics.deception`, the measure already present).
  - `PROFILE_DEATH_CAUSES`, `UPRISING_APPROVAL`, `UPRISING_UNREST`, `PROFILE_POPULATION_BASIS` constants, each with
    the reason and the source named.
  - The country block now carries `profile`, computed from the same history and counters as the existing figures.
- `karamaniya/report.py`
  - `select_comparison`, `baseline_profile`, `profile_comparison`, `profile_text`, `profile_view`.
  - Preference order `scripted_replayed`, `passive_replayed`, `scripted`, `passive`, then any finished mode. Failed
    modes are skipped. The `note` names the mode used and whether its neighbours were replayed or rule-played.
  - `report_data` adds `profile_view`: six plain-language sentences and one row per profile item with this run's
    value, the comparison's value and the difference where both exist.
  - An older `baseline.json` with no stored profile still compares the items it does hold (months, outcome, deaths,
    democracy min/mean, food, unemployment, inflation, approval, war, regions); the rest read "not recorded", never
    zero.
- `karamaniya/report_template.html`
  - A `profile-section` after the baseline section, `renderProfile()`, and formatting of counts, rates, indices and
    percentages. Missing comparison items print "not recorded"; a zero difference prints "the same".
- `tools/study_analysis.py`
  - Imports `outcome_profile` from the scorecard, so the study and the report cannot drift apart.
  - `profile_rows(runs, scope)` and `profile_run_rows(runs)`. A run is one government, so its profile is attributed
    to every model and formation office that served in it, once per run and group; the group tables report means
    across the runs a group served in.
  - New outputs `profile_by_model.csv`, `profile_by_office.csv`, `profile_by_run.csv`, and a summary section
    "Outcome profile (RR4): by model and by formation office". Module docstring and `--help` text updated.
- `docs/STATISTICS.md`: the profile's fields, formulas, denominator, attribution and output files.
- `tests/test_rr4_profile.py` (new): 20 tests, written first and failing on `49a8d5b`.

## Tests (commands and counts)

Run with the required interpreter from the worktree unless stated.

- Before the change, RED: `"C:/Users/litle/Karamaniya/research/.venv/Scripts/python.exe" -m unittest
  tests.test_rr4_profile -v` -> `Ran 20 tests`, `FAILED (failures=1, errors=19)`.
- After the change: `... -m unittest tests.test_rr4_profile` -> `Ran 20 tests ... OK`.
- Touched modules:
  `... -m unittest tests.test_engine24_study_analysis tests.test_engine24_study_statistics
  tests.test_engine17_baseline tests.test_engine17_watch tests.test_analytics tests.test_pipeline` ->
  `Ran 81 tests ... OK`.
- Scorecard and report consumers:
  `... -m unittest tests.test_consensus_tally tests.test_convergence tests.test_engine16 tests.test_engine18_ballot
  tests.test_engine19_infra tests.test_text_cuts tests.test_motion_integrity tests.test_gui tests.test_analyze` ->
  `Ran 215 tests ... OK`.
- Full suite, system Python 3.12:
  `python tools/test_fast.py tests --deselect
  tests/test_engine24_cluster_estimate.py::Bench::test_a_full_run_against_a_stub_server_reports_the_answer_and_its_reasoning`
  -> `3759 passed, 22 skipped, 6331 subtests passed in 195.38s (0:03:15)`.

## Verified

- The synthetic five-month history: every profile value by hand, including the per-100,000 rates against a stated
  1,000,000 denominator, the three repressive months, the two uprising-zone months, the two war months, the one
  region lost and the two foreign campaigns with one exposure.
- The scorecard on a fresh two-month scripted run: `country.profile` exists, `months_governed == country.months_run`,
  `excess_deaths == country.excess_deaths`, and the rate equals deaths / the stated population * 100,000.
- The report's plain-language lines name all six areas, and a survived run reads "survived to the end of the run",
  not "ended in survived".
- The comparison selection: `scripted_replayed` wins when it finished; rule-played `scripted` is used when no
  replayed mode is present; a failed replayed mode is skipped; no finished mode gives an empty comparison and a
  note saying no baseline was run; stored baseline profiles compare every item; an older file compares the items it
  records and reports the rest as not recorded.
- The study analysis end to end on two synthetic runs: `profile_by_model.csv`, `profile_by_office.csv` and
  `profile_by_run.csv` are written with the right group means (m1 only run 1 = 100.0 per 100,000; m2 in both = 150.0;
  m6 only run 2 = 200.0; the head office = 150.0), and `summary.md` has the new section.
- A real browser runtime, not just text: a two-month scripted report with a synthetic `scripted_replayed` baseline
  was rendered with `chrome --headless=new --dump-dom` (exit 0). The DOM contains the profile section, the six
  sentences with real values, the comparison note naming `scripted_replayed`, the comparison table, "the same" for
  zero differences and `+0.4` with the critical tone for a non-zero excess-death rate difference.
- Prompt freeze: `python tools/prompt_freeze.py` -> `seed 1: 2/4 contested, 1 failed, outcome survived` and
  `prompts unchanged`. No prompt text was touched.

## UNVERIFIED

- No recorded model run was read: the recorded run in `research/runs` is outside this worktree's permitted work.
  The integration on a real run is for the lead after merge.
- RR3's actual `scripted_replayed`/`passive_replayed` baseline files: no RR3 commit existed when this was written
  (`rr/uprising`, `rr/relief`, `rr/comparisons` all pointed at `49a8d5b`), so the mode names follow the RR-1
  decisions and the replayed comparison was exercised with a synthetic `baseline.json`.
- The full per-item comparison against a real replayed baseline depends on `baseline.json` storing each mode's
  profile (see Questions). Without that, the report compares the items baseline.json already records and marks the
  rest "not recorded"; this fallback was tested, the full real comparison was not.

## Prompt-freeze result

`prompts unchanged`. No prompt, briefing or schema text changed. `tools/prompt_freeze.py` was run without `--write`.

## Proposed changelog text (lead owns `CHANGELOG.md`)

- **An outcome profile per run (RR4).** The scorecard now reports survival, human cost per 100,000 by cause,
  democracy, living standards, stability and outside pressure, each from the run's own history and counters, with no
  composite score. The report renders it in plain language and compares every item against the replayed-neighbour
  council when one exists (`scripted_replayed`/`passive_replayed`), else the rule-played council, and says which.
  `tools/study_analysis.py` writes `profile_by_model.csv`, `profile_by_office.csv` and `profile_by_run.csv`, and a
  summary section. 20 new tests.

## Proposed backlog text (lead owns `docs/ENGINEERING_BACKLOG.md`)

- `| T??? | The report gave one verdict, survival | medium | IMPLEMENTED | karamaniya/scorecard.py, karamaniya/report.py, tools/study_analysis.py | test_rr4_profile.py | RR4 of the regime-realism plan: a six-area outcome profile per run, per-100,000 rates on a stated first-month population basis, the replayed-neighbour comparison when present else the rule-played council, and the profile by model and formation office in the study analysis. No composite score. |`

## Questions

1. **Population basis.** The scorecard had no per-100,000 denominator before this work. I used `population_all` at
   the first recorded month (the population the government inherited), the same basis
   `calibration._emigration_share` uses. Please confirm this is what "the same population basis as the scorecard"
   should mean; if the intended basis is the final recorded population, it is a one-line change in
   `outcome_profile` and one test constant.
2. **Baseline profiles must be stored for the full comparison.** I did not edit `baseline.py` (RR3 owns it), so
   `baseline.json` does not yet carry each mode's profile. Without it the report compares only the summary/monthly
   items the file already holds. Proposed patch for the lead or RR3, in `baseline.compute`:
   load `bmonths = RunStore(path).read_log("month")` beside the checkpoint, then store
   `"profile": outcome_profile(bworld.history, bmonths, bworld.outcome)` inside each mode's `summary` (and the same
   for `this_run` with `store.read_log("month")`). Import `outcome_profile` from `karamaniya.scorecard`. Once that
   is in, every item compares automatically; no RR4 change is needed.
3. **"Months under repressive acts"** uses the scorecard's `REPRESSIVE_MOTIONS` set, read from the state in force
   each month: press restricted/censored, assembly restricted/banned, emergency, minority restricted/interned,
   decision rule head-decides, lethal protest response, mass arrests, rigged elections, massaged statistics, closed
   emigration, high surveillance. Confirm the set (in particular that massaged statistics and closed emigration
   belong in a democracy measure).
4. **"Excess deaths"** includes `soldiers_killed`, as the scorecard's `country.excess_deaths` and
   `analytics.run_metrics` already do. The eight causes are therefore the scorecard's, not seven civilians plus a
   separate military line. Confirm.

## What is left

- The lead: add the profile to the baseline summaries (question 2), merge RR4 with RR3/RR1/RR2, update the final
  `docs/REGIME_REALISM.md`, and run the profile on the recorded run if wanted (the values are computed from the run
  file; no model call is involved).
- The lead's versioning, changelog, backlog, ENGINE.md and prompt fixture are untouched, as instructed.
