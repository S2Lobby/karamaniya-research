# RR3 — fair comparison councils

Worktree `C:\Users\litle\Karamaniya\karamaniya-test\rr3-comparisons`, branch `rr/comparisons`, base `49a8d5b`.
Nothing was pushed or merged. No file in `research`, `private`, `private-wt` or `evidence` was written.

## What changed

- `karamaniya/baseline.py`
  - `MODES` now is `scripted, passive, hawk, dove, scripted_replayed, passive_replayed`; `RULE_MODES` is the
    first four (unchanged), `REPLAYED` maps each replayed mode to the council it runs (`scripted`,
    `passive`).
  - `compute()` builds the recorded cabinet backend from the run's `log.jsonl`: provider `replay`,
    `replay_log` (absolute), `replay_of` (the provider on the recorded `foreign_call` lines, the run's
    `foreign_cabinet_backend` or first seat as fallbacks), label `replayed neighbours from <run>`.
    The replayed mode's config keeps the run's `KEPT` settings, forces `foreign_cabinets=True`, and adds
    `foreign_cabinet_backend`; the four rule-played configs are untouched and gain no backend.
  - A run without a replayable log gets the four rule-played modes only: no log, no `foreign_call`
    records, or the pre-engine-24 `"(scripted)"` placeholder. The file records
    `"replay": {"status": "unavailable", "reason": ...}`, and the cache key now includes the replay state.
  - A replayed mode's summary carries `foreign_acts_skipped` (`month`, `actor`, `action`, `reason`) and
    `foreign_acts_applied` (`month`, `actor`, `action`). Skips come from `FOREIGN_ACTION_INVALID` records
    plus the reader's own `rejected_action` notes not already covered; kept-act notes ("carried out ...")
    are excluded. Each mode result and each `deltas` entry carries `neighbours` = `rule-played` or
    `replayed from <run>`.
  - A mode that raises (e.g. `ReplayMissing` when the comparison outlives the log) is recorded as failed
    with its reason; the other modes still run.
- `karamaniya/report_template.html`
  - The comparison section names each mode's neighbours ("Neighbours: ... faced rule-played / replayed from
    <run>"), shows a note with up to three recorded acts the comparison world refused and their reasons,
    says why the replayed comparisons were not run when they were not, and states the limitation: replayed
    neighbours do not react to the comparison council.
- `karamaniya/foreign.py`
  - `FOREIGN_ACTION_INVALID` records now carry the refused `action` in `details` (one line), so a replayed
    comparison can name the act, actor and reason. No new draw, no behaviour change.
- `karamaniya/calibration.py`, `tools/calibrate.py`: play/validate `RULE_MODES` only; the replayed modes
  need a finished run's log and are refused there.
- `karamaniya/__main__.py`: the `baseline` command's table now sizes each mode column to its name (the
  replayed names are longer than 12 characters); it used to abut the names and drop the last column's
  figures from every row.
- Tests: new `tests/test_rr3_comparisons.py`; `tests/test_engine13.py` and
  `tests/test_engine17_baseline.py` updated for the widened `MODES` and the `neighbours` key in `deltas`.
- A bug found in review was fixed before the final run: `_config` had passed the replay backend into every
  mode, so the four rule-played councils also faced the recorded neighbours. On run copy
  `20261018-014944-seed1` that changed all four from 18 months/survived/0 war to revolutions at Month 18.
  The backend is now set only for the replayed modes, and
  `test_the_rule_played_modes_are_unchanged_beside_the_same_recorded_log` pins the four summaries on the
  same run whose log supplies the replayed modes.

## Tests

Run from the worktree with `C:/Users/litle/Karamaniya/research/.venv/Scripts/python.exe` unless noted.

- Tests first, on base `49a8d5b` (a `git archive 49a8d5b` export in a temp dir, new test file copied in):
  `python -m unittest tests.test_rr3_comparisons` → **11 tests, FAILED (failures=5, errors=11)**.
- Branch: `python -m unittest tests.test_rr3_comparisons` → **12 tests OK** (~13 s).
- Touched modules:
  `python -m unittest tests.test_engine17_baseline tests.test_engine18_baselines tests.test_engine13 tests.test_engine19_infra tests.test_engine19_followups_c tests.test_engine24_replay tests.test_foreign_idempotency tests.test_open_w8_cabinets tests.test_engine18_calibration tests.test_engine17_sensitivity tests.test_rr3_comparisons`
  → **228 tests OK** (85.6 s).
- Full suite (system Python 3.12.10, final code, after the CLI fix):
  `python tools/test_fast.py tests --deselect tests/test_engine24_cluster_estimate.py::Bench::test_a_full_run_against_a_stub_server_reports_the_answer_and_its_reasoning`
  → **3751 passed, 22 skipped, 6350 subtests passed in 330.47 s** (exit 0). An earlier run of the same
  command on the code before the CLI-only change gave 3751 passed / 22 skipped / 6350 subtests in 129.71 s.
- Prompt freeze: `python tools/prompt_freeze.py` → **"prompts unchanged"** (exit 0, run again on the final
  code); never `--write`.
- Commits on `rr/comparisons`: `aad1276` (replayed modes, report, tests), `738f8e2` (rule-played modes no
  longer receive the replay backend; regression test), `f1b5591` (baseline CLI column widths).
- Emitted report JS: a generated `report.html`'s three inline `<script>` blocks pass `node --check`
  (Node v24.19.0).
- Recorded-run check (a copy of `research/runs/20261018-014944-seed1` — config, checkpoint and log copied to
  a temp dir; nothing under `research` was written): `baseline.compute(copy, force=True)`:
  - rule-played modes on the branch match base `49a8d5b` **and** the archived `baseline.json`: `scripted`
    18 months / survived / 0 war / approval .3837, `passive` .4072, `hawk` .3593, `dove` .4326;
  - `scripted_replayed` / `passive_replayed` face `replayed from 20261018-014944-seed1`; the recorded
    invasion at month index 5 (Month 6) is carried out in both, 18 recorded acts are refused with reasons,
    and the comparisons diverge (scripted 17 months / revolution / 12 war months, passive 15 / revolution /
    4 war months).

## Verified

- A replayed comparison faces the recorded invasion: synthetic fixture (deploy Month 1, refused east
  invasion Month 2, carried-out north invasion Month 3) and the recorded run copy above.
- An act the comparison world refuses is recorded as skipped with month, actor, action and reason
  (synthetic: the east invasion without troops; recorded run: e.g. an invasion refused because the
  countries are already at war, a mobilisation over the monthly cap, malformed recorded acts).
- The four rule-played summaries are identical to base `49a8d5b` on the synthetic fixture (exact dicts) and
  on the recorded run copy (figures above), including when the run's log is replayable.
- A run with no log (and a log of `"(scripted)"` placeholders) computes only the four rule-played modes,
  status `ok`, with a reason in `"replay"`.
- The report names each comparison's neighbours and carries the replayed-neighbour limitation text.

## UNVERIFIED

- Visual/browser rendering of the updated report section. No GUI may be spawned here; the emitted scripts
  parse (`node --check`) and the generated HTML is asserted by tests, but nothing was rendered in a browser.
- End-to-end use on a live model run after the RR branches merge (the replay was checked with a recorded
  run's files, not a new model run).

## Proposed changelog text

> Same-seed comparisons can now face the run's own neighbours: `scripted_replayed` and `passive_replayed`
> replay the run's recorded cabinet answers month by month, so an invasion or campaign the run's neighbours
> chose happens in the comparison when the comparison world allows it. Refused acts are recorded with their
> reasons, the report names each comparison's neighbours, and runs without recorded cabinets keep the four
> rule-played modes. Replayed neighbours do not react to the comparison council.

## Proposed backlog text

> RR3 (done on `rr/comparisons`): replayed-neighbour comparison modes in `baseline.py`. Consider adding
> `hawk_replayed` / `dove_replayed` if the calibration sweep wants them; they are one line each in `MODES`
> and `REPLAYED`. Consider surfacing `foreign_acts_skipped` counts in the scorecard/profile (RR4) once its
> profile lands.

## Questions

1. `karamaniya/foreign.py` was not in RR3's named file list, but one line was needed so a refused act can be
   named in the mode's summary; it adds `action` to the `FOREIGN_ACTION_INVALID` details and changes no
   behaviour. Keep it, or would you rather carry the action another way?
2. When a comparison world outlives the recorded log (handover extension), the replayed mode is recorded
   `failed` with "the replay ran out of recorded answers". Prefer that, or truncate the replayed modes at
   the last recorded month and say so?
3. The replayed modes run by default whenever the log is replayable (`baseline.compute` with no explicit
   modes, `python -m karamaniya baseline`). Confirm that six modes by default is wanted (RR4 consumes the
   two names).

## What is left

- RR5: versions/changelog/ENGINE.md/backlog wording; any decision on question 2.
- Optional: mention the replayed comparisons in `runner._end`'s console line (left untouched to avoid
  touching runner.py).
- RR4: use `scripted_replayed` / `passive_replayed` in the outcome profile and decide whether
  `foreign_acts_skipped` belongs in the scorecard.
