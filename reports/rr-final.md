# Regime realism: final report (RR-2 and RR-3)

Branch `regime-realism`, integration worktree `C:\Users\litle\Karamaniya\karamaniya-test\rr-merge`, base GitHub main
`274ad98`. **Not merged to main, not pushed.** The user's rule stands: nothing merges before the SocioVerse batch is
recorded and the user says so.

## Commits

- RR0 recon `cfdf724`; RR-1 decisions `49a8d5b`.
- RR1 `272ed66`, `e4b69fc`, `f379d86`; merged `4b691dd`.
- RR2 `14d9f64`, `63ba5ac`, `f27c95f`, `2cabf12`; merged `57d9b21`.
- RR4 `490d62b`, `e428f5d`; merged `de1641d`.
- RR3 `aad1276`, `738f8e2`, `f1b5591`; merged `fbd5348`.
- RR5 `b48a832` (option), `bf61048` (sweep + crackdown calibration), `2aa6605` (presets), `2471856` (full sweep and
  output), `b8b8906` (versions/docs), `3ecbad4` (final reports), `980d32d` (a baseline plays the run's world model).
- 41 files changed, 21,580 insertions, 118 deletions over `274ad98`.

## What changed

- **RR1, legitimacy and the crackdown gamble.** `karamaniya/uprising.py`: `L =
  max(.50, 1 - .30*D*(1+elected)/2 - .30*D*near)` multiplies the existing uprising chance; `near` is a credible vote
  within 12 months, zero after a postponement, cancellation, rig or recent coup. A lethal crackdown draws police and
  army obedience on `rng_for(seed, month, "uprising_crackdown")`: both obey = massacre + 3-month backlash, one refusal
  = civil war under `civil_war = "on"` (cause `crackdown_split`) or uprising success, both = success. `uprising_check`
  in the month row under legitimacy only. `CRACKDOWN_BASE` is `.64` after RR5 calibration (RR1's draft `.62`).
- **RR2, relief.** `karamaniya/regime_relief.py`: six-month decaying concession credibility (status .40, amnesty .30,
  fund .25, named repeal .30, minority .35) read as `max(approval credibility, concession)` under the existing .15
  monthly cap; a deterministic per-region protest-cause record; a new head's .03 approval reaction for three months,
  halving, once in 12 months, none after a coup, half for a reshuffle.
- **RR3, comparisons.** `baseline.MODES` adds `scripted_replayed` and `passive_replayed`, facing the run's recorded
  cabinets; refused acts recorded as skipped with reasons; every mode names its neighbours; the report prints them and
  the non-reaction limitation. Rule-played modes are unchanged.
- **RR4, profile.** Six-area outcome profile in `scorecard.py`, the report and `tools/study_analysis.py`, with
  per-100,000 death rates and comparison against the replayed baseline; no composite score.
- **RR5, options and integration.** `uprising_model` in `config.RUN_DEFAULTS`, validation, `runner.apply_run_options`
  (live attribute plus checkpointed institutions under legitimacy), manifest record/divergence, study-grid
  `uprising_models` dimension; `tools/regime_sweep.py`; WORLD_ENGINE 33, AGENT_PROMPT 30 unchanged; docs, changelog,
  backlog, final `docs/REGIME_REALISM.md`. A baseline keeps the run's `uprising_model` (`baseline.KEPT`) and
  `baseline.json` records it, so comparisons do not mix two uprising rules.

## Tests I ran myself

| Command | Result |
|---|---|
| `python -m unittest tests.test_rr1_uprising tests.test_rr2_relief tests.test_rr5_options tests.test_open_w6_arms` | 96 OK |
| `python -m unittest tests.test_rr3_comparisons tests.test_rr4_profile tests.test_engine13 tests.test_engine17_baseline tests.test_rr5_sweep` | 79 OK |
| `python -m unittest tests.test_rr1_uprising tests.test_rr5_sweep tests.test_rr5_options` | 45 OK |
| `python -m unittest tests.test_engine33_versions tests.test_agent_prompt30_versions tests.test_config tests.test_manifest tests.test_engine24_study_grid tests.test_rr5_options tests.test_rr5_sweep` | 89 OK |
| `python -m unittest tests.test_rr3_comparisons tests.test_engine13 tests.test_engine17_baseline tests.test_engine18_calibration tests.test_manifest` (on the RR3 branch) | 92 OK |
| `python tools/test_fast.py tests --deselect tests/test_engine24_cluster_estimate.py::Bench::...` | **3851 passed, 22 skipped, 6357 subtests passed in 144.00 s** |
| `python -m unittest tests.test_engine24_package` | 9 OK |
| `python tools/package.py all` | zip 1,343,658 bytes, 153 files; clean-venv smoke exit 0, 3.7 s |

The cluster timing test is deselected because it is load-sensitive, as in the engine-30 release. The full-suite figure
is from `tools/test_fast.py`, which runs the same test modules in 12 workers; the exact sequential
`python -m unittest discover -s tests -t .` was not run in one invocation because a foreground command is capped at
10 minutes. Every module is covered by the parallel run and the targeted runs above.

## Calibration (RR-2 bands)

`python tools/regime_sweep.py --workers 12 --out reports/regime-sweep.json`: 288 runs (4 councils x 12 seeds x 2
models x 3 presets) plus 144 forced crackdown probes. Output committed at `reports/regime-sweep.json`.

- Quiet runs: **0 of 120** quiet runs ended in revolution.
- Stress pairs: **48/48 legacy vs 48/48 legitimacy**, ratio 1.00, inside half-to-all; mean months governed 2.81
  (legitimacy) vs 2.42 (legacy). The band is met at equality, not by a lower share; legitimacy buys time in this
  extreme preset.
- Crackdown: forced sample **44/144 = 30.6% failures** (100 massacres, 44 uprising successes); analytic census
  **29.0-39.6%** at base .64. In-run crackdowns at that security were 1/1 (the councils' police loyalty falls below the
  lethal gate), which is why the forced sample carries the band.
- Relief evidence: 767 talks, 360 with concession credibility above zero, maximum .55.
- Honeymoons: **0 observed** in the sweep (no scripted council changed its head); the grace path is covered by
  `tests/test_rr2_relief.py` only.

Bands: the user delegated the RR-1/RR-2 choices, so I adopted the plan's proposed bands above. They are the lead's
choice, not a user decision; they can be changed without touching code.

## Legacy identity and prompts

- `python tools/replay_run.py reports/rr-base-36/base-seed1`: **"identical: the 37 month records and the final
  checkpoint match the original"**; all 539 prompts sent again unchanged.
- `python tools/prompt_freeze.py`: **prompts unchanged**.
- The same freeze check with `uprising_model = "legitimacy"` forced on the four-month scripted run: **prompts
  unchanged**, 83 of 83.

## What-if table

Recomputed on the final code from `research/runs/20261018-014944-seed1` (read only; nothing written under
`research`). P(no uprising, Months 11-18) is **.357** today and **.416** with legitimacy; at the run's forces a
crackdown would fail 29-42% of the time. Full table in `docs/REGIME_REALISM.md` section 8.

## Verified, and UNVERIFIED

Verified: legacy replay identity; prompt freeze under both settings; the sweep bands with the fixed-force census;
the package build and clean-venv smoke; the full test suite.

UNVERIFIED:
- Any real-model run under `legitimacy` (no paid or real model was called).
- Browser rendering of the RR3 report section (no GUI was opened; the generated scripts pass `node --check` per the
  RR3 report).
- The middle of the stress spectrum: the sweep has quiet and severe presets, not a realistic crisis.
- The grace period on a real head change; the sweep observed none.
- The near-vote term on a real election at Month 36.
- The concession credit sizes as calibrated quantities; the sweep shows the channel firing and decaying, not that
  .40/.30/.25/.30/.35 are right.

## Questions for you

1. Confirm the three bands (or change them): quiet 0 revolutions; legitimacy share half to all of legacy; crackdown
   failure 20-40% at security .55-.65.
2. Do you want `legitimacy` as the default after the SocioVerse batch, or keep `legacy` and select the new world per
   run? Current default is `legacy`; the change is one line in `config.RUN_DEFAULTS`.
3. The grace period is unit-tested but never fired in the sweep. Do you want a forced-succession probe added to
   `tools/regime_sweep.py`, or is the unit test enough?
4. Do you want the control room's Council form to expose `uprising_model`? It is a config key now; the GUI does not
   show it.

## What is left

User approval; merging to main and pushing (both deliberately not done); the SocioVerse batch; then the first real
runs under `legitimacy`, including the planned experiments in the plan section 9 (the recorded council on seed 1,
relief instead of force, and the Interior's model by rotation).
