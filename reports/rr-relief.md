# RR2: concessions and the new head's grace period

Worktree `C:\Users\litle\Karamaniya\karamaniya-test\rr2-relief`, branch `rr/relief`, based on
`49a8d5b`. Nothing pushed or merged. Commits: `14d9f64` (tests and the base fixture), `63ba5ac`
(the implementation), then the report and a style follow-up.

## What changed

- **`karamaniya/regime_relief.py` (new).** The RR2 world rules behind
  `uprising_model = "legitimacy"`. `enabled(w)` reads the option defensively with
  `getattr(w, "uprising_model", "legacy")`; anything but `legitimacy` is legacy. Under legacy every
  function returns before touching the world (no records, effects or draws).
- **Concession credibility.** `negotiation_credits(w, region)` reads the delivered concessions and
  returns each with a linearly decaying credit (`weight x (1 - age/6)`, ages 0-5). The events:
  - a status upgrade from `regional.state(w)["changes"]` (rank increase), credited to that region;
  - an amnesty transition to `release` from the history rows' `policy.amnesty`, credited to every
    Karamaniya region (a national pardon);
  - a regional fund beginning to fund a region, from `policy.regional_fund`, credited to that region;
  - a repeal transition (`rationing` on->off, `price_controls`/`requisition` non-none->none),
    credited only to a region whose recorded protest named the measure;
  - `constitution.minority` back to `equal` after a restriction, credited to the Vell Highlands.
  Deduplication is by transition/change entry. Weights before decay (starting values for RR5):
  status .40, amnesty .30, fund .25, repeal .30, minority .35; the sum is clamped to 0..1.
  `concession_credibility` therefore stays in 0..1 and the negotiation relief cannot exceed the
  existing ceiling `0.02 + 0.13 x 1.0 = .15` a month. The choice to keep the direct effects of the
  same acts (status approval, amnesty grievance/fear, the fund's income) and add a separate
  talk-credibility channel is the lead's RR-1 decision 5; it is stated in the module docstring.
- **The negotiate hook (`karamaniya/society.py`).** In `_protests`, `credibility` is now
  `max(approval credibility, concession credibility)` under legitimacy; the approval term and the
  `0.02 + 0.13 x credibility` formula are unchanged. The protest event (and so the month row)
  records `credibility`, `approval_credibility`, `concession_credibility` and the list of
  concessions that counted. Under legacy the event has exactly its old fields and the old formula.
- **Protest cause record (`karamaniya/society.py`).** `_protests` writes one deterministic entry per
  protesting region and month to `w.institutions["protest_causes"]` (capped at 12 per region). The
  cause is the largest live driver among hunger (.7 x region hunger), repression (.2 x region
  repression), status envy (`regional.ENVY` x rank gap x 4, the effect bus's scale), and the
  measures in force (rationing .35, price controls .25/.35, requisition = `economy.REQUISITION`'s
  share, minority restriction .4/1.0). Ties go to the fixed order; "unrest" is the fallback when none
  is live. The record stores the drivers and the winning weight, uses no draw, adds no text, and is
  not read by any prompt.
- **The grace period (`karamaniya/politics.py`).** The `assign_office` branch captures the previous
  holder and calls `regime_relief.head_changed(w, old_head, new_head)` after setting the head office.
  `head_changed` calls `public_mood.react(w, "approval", where="*", value=.03 x scale, months=3,
  decay=.5, reason="new head of government (<id>)")`, once in 12 months
  (`w.institutions["regime_relief"]["head_grace_month"]`), never when `coup_month` is this or the
  previous month, scale .5 when the new head already held an office, 1.0 otherwise. Each change is
  recorded in `head_changes` (capped at 24) with the reaction, scale and why (`new_head`,
  `reshuffle`, `coup_blocked`, `within_12_months`). `vacate_office` grants nothing.
- **Tests and fixture.** `tests/test_rr2_relief.py` (33 tests) and
  `tests/fixtures/rr2_legacy_months.json`, two scripted engine months recorded **on base commit
  49a8d5b** with `engine_source_fingerprint` stripped (the convention of
  `tests/fixtures/civil_war_off_month.json`). The same months replayed on the branch under legacy
  are `assertEqual` to that fixture, including every event dict.

## Tests

Commands run from the worktree with the repository interpreters:

- `python -m unittest tests.test_rr2_relief -v` (venv): **33 tests, OK**.
- `python -m unittest tests.test_politics tests.test_regional_policy tests.test_engine17
  tests.test_engine18_opposition tests.test_engine19_prompts tests.test_civil_war
  tests.test_prompt_freeze` (venv): **128 tests, OK**, 21.8 s.
- Full suite, system Python, foreground:
  `python tools/test_fast.py tests --deselect tests/test_engine24_cluster_estimate.py::Bench::test_a_full_run_against_a_stub_server_reports_the_answer_and_its_reasoning`
  -> **3772 passed, 22 skipped, 6334 subtests passed in 116.67 s**.
- Two-month legitimacy integration check (`engine.step`): protest events carry
  `credibility .55 / .4583` from amnesty + fund, the cause and grace records are in the checkpoint
  state, the second head change is recorded as `within_12_months`, and the first reaction is the
  expected .015 reshuffle value.

## Verified and UNVERIFIED

Verified with output seen here:

- The legacy fixture equality (two engine months, all events and rows identical to base 49a8d5b) and
  the absence of `protest_causes` / `regime_relief` / reaction entries under legacy.
- Each concession credits its own region only (amnesty: every region, by design), the credit decays
  to zero at six months, deduplicates by transition, and the sum is capped at 1.
- A repeal is credited only to a region whose recorded protest named the measure; each of the three
  measures works.
- The negotiate hook gives the floor (.02) under legacy and low approval, lifts to the concession
  term under legitimacy, keeps the larger approval term, and does not exceed .15 a month.
- `public_mood` receives value .03 / three months / decay .5 for a fresh head, .015 for a reshuffle;
  the effect halves monthly and lasts three months; the 12-month limit, the coup block (this and the
  previous month) and the 12-month clock not being spent by a blocked change are all tested.
- The cause record is deterministic, capped, checkpointed through `World.to_dict`/`from_dict`, and
  does not change `briefing.public` or `briefing.public_v2`.
- Prompt freeze: `python tools/prompt_freeze.py` -> **prompts unchanged**.
- Prompt freeze under `legitimacy` (temporary, uncommitted shim in `runner.apply_run_options`):
  **unchanged**, the same 83 calls and hashes. RR5 should repeat this through the real config path.

UNVERIFIED:

- A full 36-month legacy run compared row-by-row against a base 36-month run. The two-month fixture,
  the full suite and the 4-month prompt-freeze scripted runs are the evidence here; the plan's
  36-month legacy identity check belongs to RR5's checklist.
- The calibration of every constant (weights, cause saliences, .03 grace value). These are starting
  values; the RR5 sweep and the user's bands must set them.
- The run option through config/runner/manifest, which RR5 owns. Note that the option is a dynamic
  attribute in my tests: `World` has no `uprising_model` field yet and `dataclasses.asdict` will not
  serialize a dynamic attribute, so until RR5 adds the field a checkpointed legitimacy run would
  load as legacy. This must be fixed with the field (or an institutions entry) at RR5.

## Proposed changelog text

- Regime realism (RR2, behind `uprising_model = "legitimacy"`): the negotiate protest response now
  takes the larger of approval credibility and the region's delivered-concession credibility
  (status upgrade, amnesty, regional fund, repeal of a measure its protest named, minority
  restoration), remembered for six decaying months and capped at 1. `society._protests` records a
  deterministic protest cause per region; `politics.apply_motion` gives a new head of government a
  three-month approval reaction of .03 halving monthly, once in twelve months, never after a coup,
  half for a reshuffle. Under `legacy` (the default) nothing changes.

## Proposed backlog text

- RR5: add `uprising_model` to `World`, `config.RUN_DEFAULTS`, the runner and the manifest so a
  checkpoint keeps it; calibrate `STATUS_CREDIT` .40, `AMNESTY_CREDIT` .30, `FUND_CREDIT` .25,
  `REPEAL_CREDIT` .30, `MINORITY_CREDIT` .35 and the cause saliences (rationing .35, price controls
  .25/.35) on the regime sweep; decide whether a national amnesty should credit every region or
  only the two minority regions; repeat the prompt freeze under the real option.

## Questions

1. **Amnesty is credited to every region** because it is a national pardon (`_apply_amnesty` reaches
   every population group, with more relief for the Vell and Imperial identities). If the lead
   reads "only for the region concerned" as requiring the two minority regions (Kessel and the
   Highlands) instead, the change is one line in `_transition_events`.
2. **A scenario-inherited amnesty or fund is credited in the run's first month**, because the first
   state is read against the engine's defaults. The defaults have neither, so only a scenario that
   deliberately starts with one is affected. Is that acceptable, or should inherited settings be
   excluded?
3. **The grace fires only through the `assign_office` motion**, as specified. A head installed by
   any other path (civil-war appointment, a formation) gets none. Confirm that is intended.
4. **"unrest" is the fallback cause** when none of the named drivers is live (grievance can be driven
   by inflation or unemployment, which the task's list does not name). It never matches a measure.

## What is left

- Lead review of the diff, then RR5: option wiring, versions, calibration, final docs, and the
  full 36-month legacy identity check.
- Nothing in RR2 touches `versions.py`, `CHANGELOG.md`, `ENGINE.md`, `docs/ENGINEERING_BACKLOG.md`,
  the prompt fixture or the version tests.
