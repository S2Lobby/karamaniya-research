# RR1: uprising legitimacy and the crackdown gamble

> Lead note at merge (RR5): the crackdown base in this report is `.62`, RR1's draft. The RR5 calibration moved it to
> `.64` so the both-obey failure chance over loyalty .55-.65 and bond .2-.3 is 29.0-39.6%, inside the proposed 20-40%
> band. The rest of the report is as delivered; see `docs/REGIME_REALISM.md` section 3.

Branch `rr/uprising`, worktree `C:\Users\litle\Karamaniya\karamaniya-test\rr1-uprising`, based on
`49a8d5b` (RR0 doc + the lead's RR-1 decisions; engine code identical to `274ad98`).

Commits:

- `272ed66` tests first, plus the base fixture (`tests/fixtures/uprising_legacy_36m.json`);
- `e4b69fc` the module and the `_revolution` hook;
- `f379d86` a rigged win is not an election for the legitimacy factor.

## What changed

**New `karamaniya/uprising.py`.** It owns the run-option reader (`uprising_model`, default
`"legacy"`), the legitimacy factor and the national crackdown draw.

- `legitimacy_factor(w)` returns `D = world.democracy_index(w)`, `elected` (a fair election won;
  a rigged winning count does not count), `near` and
  `L = max(L_MIN, 1 - a*D*(1+elected)/2 - b*D*near)` with `a = b = .30`, `L_MIN = .50`.
  `near = clamp(1 - months_left/12)` for a credible vote within 12 months; zero when the vote is
  postponed (past the Charter date, or past `election_due_month` for an elected government),
  cancelled (`election_month < 0`), rigged (`policy.election_conduct`), or when a coup fell within
  12 months. `L` never removes the chance.
- `obey_probability(force, unrest)` is the lead's national formula:
  `clamp(.62 + .45*loyalty + .20*bond - .25*[unrest > .6] - .15 - min(.15, max(0, arrears)*.03), .05, .98)`.
- `crackdown(w)` draws police then army on `rng_for(seed, month, "uprising_crackdown")`.
  Both obey: the old massacre (its body moved here unchanged) plus a 3-month backlash — a
  grievance reaction with slow decay (`.03`, decay `.90`) and an unrest-side push (a second
  grievance reaction `.01`; `public_mood` has no `unrest` kind and society derives
  `unrest = grievance*(1-.75*fear)`) — in the regions above the protest threshold `.33`, or
  nationwide when no region detail exists. One refuses: with `civil_war = "on"`, `civil_war.start`
  with cause `"crackdown_split"`, the refusing force's holder as leader, its refusal share
  (`1 - obey`) as its rebel share, the obeyed force holding its whole share for the government and
  the other armed office using `civil_war.armed_divisions`; with the arm off, or if the refusing
  office is vacant, the uprising succeeds and the record says why. Both refuse: the uprising
  succeeds even with the arm on.
- `record_idle` / `check` / `month_record` store the month's `uprising_check` on the world and
  expose it to the snapshot. Under `legitimacy` every month gets a record — including a zero-chance
  one, which takes no draw — with approval, unrest, security, war factor, `D`, `elected`, `near`,
  `L`, the base chance, the final chance and the draw. Under `legacy` no key is written.

**`karamaniya/politics.py`.** `_revolution` keeps its thresholds and chance formula. Under
`legitimacy` it multiplies by `L` through `uprising.check` (which takes the same single
`"politics"` draw in the same place) and, through the lethal gate, calls `uprising.crackdown`.
The existing success outcome moved into `_uprising_succeeds` unchanged; the massacre body moved to
`uprising.massacre` unchanged and the legacy branch calls it.

**`karamaniya/engine.py`.** `snapshot` adds `row["uprising_check"]` only when
`uprising.month_record(w)` returns this month's record (legitimacy only), next to the civil-war
record.

No prompt, schema, briefing or model-visible text changed.

## Tests

- `python -m unittest tests.test_rr1_uprising` — **20 tests, OK**. On the base commit the module
  failed as written: 17 of 18 then-existing tests errored on the missing `karamaniya.uprising`
  (only the legacy-identity test could pass, by construction); the one added later (fair/rigged
  election) was written against the same API.
- Touched modules: `tests.test_politics`, `tests.test_engine19_politics`,
  `tests.test_engine24_politics_intake`, `tests.test_civil_war`, `tests.test_civil_war_combat`,
  `tests.test_civil_war_faction`, `tests.test_civil_war_integration`,
  `tests.test_civil_war_negotiation`, `tests.test_civil_war_records`, `tests.test_rr1_uprising` —
  **266 tests, OK** (system: `C:/Users/litle/Karamaniya/research/.venv/Scripts/python.exe`,
  Python 3.12.10).
- Full suite, final code, foreground, system Python:
  `python tools/test_fast.py tests --deselect tests/test_engine24_cluster_estimate.py::Bench::test_a_full_run_against_a_stub_server_reports_the_answer_and_its_reasoning`
  — **3759 passed, 22 skipped, 6335 subtests passed in 160.78s**.

The tests cover: legacy 36-month identity; `L` falling with `D`, a fair election and a near vote;
`L_MIN`; postponed/cancelled/rigged/coup removing the election terms; a rigged win not counting as
elected; both-obey massacre and backlash; the one-refusal split with the arm on and the uprising
success with it off; both refusals with the arm on; a vacant refusing office succeeding with a
reason; both draws on `"uprising_crackdown"`; the politics stream twin-identical with and without
the new model; the row under legitimacy (threshold months and zero-chance months) and its absence
under legacy; a real `engine.step` month carrying the zero-chance record under legitimacy only.

**Legacy identity.** `tests/fixtures/uprising_legacy_36m.json` was recorded on `49a8d5b` before any
change: a 36-month `council.scripted.toml` run, seed 1, with per-row sha256 (the source fingerprint
removed) and its outcome. A run of the same script on the branch under `legacy` matches every
digest and the (empty) outcome, and has no `uprising_check` key in any row. The harness stops at the
configured 36th month, before the runner's handover extension, so the outcome is `{}` in both; the
identity covers all 36 history rows.

**Prompt freeze.** `python tools/prompt_freeze.py` (no `--write`): `prompts unchanged`. Repeated
with `uprising.model` patched to return `"legitimacy"` for the whole 4-month scripted run (the
option is not wired into config yet): `prompts unchanged`, exit 0. The patch script was temporary
and is not committed.

## Verified

- Legacy behaviour is byte-identical on the recorded 36-row fixture (row digests, outcome, no new
  key), and `uprising.massacre` is the old body moved.
- The legitimacy factor's algebra and every removal case; `L_MIN` is the floor.
- The crackdown's four outcomes, with both draws, obey probabilities, refusing forces, backlash and
  civil-war state recorded; the civil war's rebel share is `1 - obey` of the refusing force.
- The month's `"politics"` stream has the same state after the twin runs (legacy vs legitimacy),
  and the next five values match; the crackdown's two draws equal the first two values of
  `rng_for(seed, month, "uprising_crackdown")`.
- The month row carries/turns off the key exactly as described.
- Full suite, touched modules and both prompt-freeze settings above.

## UNVERIFIED

- The agreed 20-40% crackdown failure band at security .55-.65 on real engine states: only the
  formula arithmetic is checked here. RR5's `tools/regime_sweep.py` must measure it (the recorded
  run's loyalties give about 29-42% by the lead's calculation; not reproduced on a live sweep).
- Any real-model behaviour under `legitimacy`: none was run and none may be run on this branch.
- `uprising_model` through `config.py`/`runner.py`/`manifest.py` and checkpoint round-trip: the
  world field does not exist yet (the lead's RR5). Here it is read from `getattr(w,
  "uprising_model", ...)` with an `institutions["uprising_model"]` fallback, so tests can set it and
  an old checkpoint reads `legacy`.
- `tools/replay_run.py` replay of a legitimacy run (and of the legacy scripted run); the lead's
  verification checklist owns it.
- The frequency of crackdown attempts and split wars in stress runs; a sweep question, not a unit
  one.

## Proposed changelog text (lead owns the file)

> World engine 33 (RR1): under the new `uprising_model = "legitimacy"`, the national uprising
> chance is multiplied by a legitimacy factor built from the democracy index, a fair election won
> and a credible vote within 12 months (at most halving the odds, never removing them), and a
> lethal crackdown draws police and army obedience instead of assuming it: both obey is a massacre
> plus a three-month backlash, one refusal is a `crackdown_split` civil war when `civil_war = "on"`
> (otherwise the uprising succeeds), both refusals end the government. The default `legacy` model
> is unchanged byte for byte. No prompt changed.

## Proposed backlog text

- RR5: add `uprising_model` to `RUN_DEFAULTS` (default `legacy`), validate it like
  `office_assignment`, carry it in `runner.py`, record it in the manifest, accept it in
  `tools/study_grid.py`, and add the `World` field so checkpoints round-trip it.
- RR5: calibrate the national crackdown constants on `tools/regime_sweep.py` to the agreed
  20-40% failure band at security .55-.65; check that a quiet run never ends in revolution and that
  stress-run revolution rates under `legitimacy` stay within half to all of `legacy`.
- RR5: decide whether the `uprising_check` record should stay in every legitimacy row (it is
  currently written every month, including zero-chance months) or only in months where the
  thresholds were met.

## Questions

1. **Record every month?** The brief said to record the check whenever it runs, including a zero
   chance. I read that as every `_revolution` call under `legitimacy`: a zero-chance month writes
   `uprising_check` with `thresholds_met: false`, `chance: 0`, `draw: null`, and takes no draw. If
   only threshold months should be recorded, it is a two-line change.
2. **Month-1 crackdown split.** `civil_war.start` is called even in Month 1 (the C1 triggers' own
   `FIRST_TRIGGER_MONTH` gate is not part of `start`). The user's rule "no war in Month 1" may be
   meant to cover this; the state is unlikely (approval under .20 and unrest over .45 in Month 1),
   but the lead may want a Month-1 split to count as an uprising success instead.
3. **The obeyed force's share.** I made the force that obeyed hold its whole share for the
   government (`obey_government = 1.0`) and only the refusing force split `obey`/`1-obey`. The
   alternative is to keep the obeyed force at `obey` government and let the rest go neutral.
4. **`elected` and rigging.** Plan 4.1 says a *fair* win; `const.elected` is also set on a rigged
   count, so the module reads the last recorded count's `rigged` flag. Confirm this is the intended
   reading (a checkpoint with no election record reads as fair).
5. **Unknown option values.** `uprising.model` raises `ValueError` on an unknown string, like
   `civil_war.validate_option`. If the lead prefers a defensive fallback to `legacy` for a bad
   checkpoint, it is one line.

## What is left

- RR5 wiring and calibration above; versions/CHANGELOG/ENGINE.md/backlog/prompt fixture stay with
  the lead, as does the final `docs/REGIME_REALISM.md`.
- The lead's verification: legacy run replay with `tools/replay_run.py`, `python tools/package.py
  all` and `tests.test_engine24_package`, and the prompt freeze with the option actually wired.
- Nothing pushes or merges; the branch is three commits ahead of `49a8d5b` and clean.
