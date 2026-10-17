# Wave 3 plan — propaganda, wider diplomacy, the study package

Agreed 2026-10-17. Wave 3 starts on engine 26 (the small-fix release that closed T148, T150, T152,
T155, T157, T158, T160-T162). It is the last feature wave before the SocioVerse 2026 submission
(2026-10-31 23:59 UTC+8).

## Why

Wave 1 built the study machinery. Wave 2 fixed the census and the detector audit. Wave 3 adds the one
missing thing the design rules ask for — a world in which governments can lie and neighbours can run
propaganda — and finishes the submission package around it. Every worker follows the user's rule:
**change the world, not the agents.** No prompt says lying is good, bad, risky or expected; the world's
reaction teaches that.

## Workstreams

| # | Workstream | Branch | Owns (files) | Deliverables | Docs |
|---|---|---|---|---|---|
| A | Domestic state media (`media_campaign`) | `wave3/state-media` | `politics.py`, `world.py`, `motion_actions.py`, `actions.py`, `prompts.py`, `council.py`, `analytics.py`, `tests/test_engine27_media*.py` | Motion type, intake, execution, monthly effects, records, deception measures, democracy-index hook | `docs/PROPAGANDA_STATE.md` |
| B | Union propaganda and the counter | `wave3/union-propaganda` | `foreign.py`, `politics.py` (settings only), `actions.py`, `prompts.py`, `director.py`, `tests/test_engine27_union*.py` | `propaganda` cabinet act, `foreign_broadcasts` setting, effects, records | `docs/PROPAGANDA_UNION.md` |
| C | Jev as annotator 2 | `wave3/jev` | `tools/jev_annotate.py`, `tools/` tests, `docs/EXIT_AUDIT_CODEBOOK.md` | Blind second annotator, dry run against the stub, re-audit of D1/D2; no real calls | `docs/JEV_ANNOTATOR.md` |
| D | Wider diplomacy | `wave3/wider-diplomacy` | `foreign.py`, `director.py`, `motion_actions.py`, `actions.py`, `prompts.py`, `standing.py`, `tests/test_engine27_diplomacy*.py` | Six neighbour pairs with handlers; `demand` and `warning` communication kinds | `docs/WIDER_DIPLOMACY.md` |
| E | Scope test and packaging | `wave3/package` | `tools/scope_test.py`, `tools/package.py`, `README` (submission), tests | One reference SocioVerse2 study audited; a clean-machine zip that runs from the README | `docs/SCOPE_TEST.md`, `docs/PACKAGING.md` |
| F | Finishing the statistics | `wave3/statistics` | `tools/study_analysis.py`, `paper/socioverse/`, tests | Survival curves as plain SVG; the secondary measures; no regression unless time | `docs/STATISTICS.md` |
| H | Small fixes | done on `engine-26-fixes` | — | T148, T150, T152, T155, T157, T158, T160-T162 | CHANGELOG, backlog |

The three original Haiku briefs (A, B, C) are in `notes/wave3-spec.md`; this plan is the build order and
the file boundary between them.

## Shared contract: `w.media`

`w.media` lives in the checkpoint and defaults are present in an old checkpoint. A owns `credibility`,
`line`, `boost` and the state records. B writes only foreign records and reads `credibility`. Do not
change the shape without updating the other worker's tests and `docs/PROPAGANDA_STATE.md`.

| Field | Meaning |
|---|---|
| `credibility` | 0..1, the public's trust in state media. Starts at 0.6 (documented assumption) |
| `line` | The council's current campaign, or `None`: `{kinds, claims: [{metric, value}], intensity, text, since, motion_id}` |
| `boost` | The approval lift still in effect; it decays each month |
| `campaigns` | One record per campaign per month: `{month, source: "state" or "veleria" or "dorsania", kinds, claims: [{metric, claimed, true, gap}], intensity, executed_by, defied, exposed, effects: {...}}` |

## Rules every worker follows

1. **Test first.** Write the failing test, see it fail, then fix. Run the targeted module and the
   modules it touches; the full suite is the reviewer's job at merge.
2. **No silent cuts.** Any text the engine shortens must be to a limit the prompt states (engine 26's
   `STATED_LIMITS` is the model).
3. **Constants documented.** Every effect and its constant has a code comment with the reason; the
   worker's doc gathers them in one table.
4. **Own seeded stream.** A random draw uses `rng_for(seed, month, "media")` (or its own stream), so the
   world's other draws are unchanged.
5. **Prompts neutral.** Describe the tool, the menu and the costs; never say what the model should
   choose.
6. **Prompt freeze.** A prompt change needs `tools/prompt_freeze.py --write` and a note in the report.
7. **Docs.** Each workstream writes its `docs/` page, updates `docs/ENGINE.md` where the rule belongs,
   and proposes CHANGELOG and backlog rows. Do not edit the versions, the CHANGELOG or the shared
   backlog; the reviewer does that once at merge.
8. **Commit on your branch**, never on `main`, and never push. Report the commit ids, the tests run and
   the prompt-freeze result.

## Merge protocol (reviewer)

1. Fetch each branch into `research` and read its diff, file by file.
2. Merge in the order A, B, D, C, E, F. Resolve conflicts in `actions.py`, `prompts.py` and
   `foreign.py` by composing the changes, not choosing a side.
3. One version bump: `WORLD_ENGINE` 27 and `AGENT_PROMPT` 24 (or the next free pair), one prompt
   fixture rewrite, one CHANGELOG entry, one backlog update.
4. Run the full suite and the workers' own suites; fix what the merge broke.
5. Merge to `main`, fetch GitHub first, push without force.

## Decisions taken for wave 3 (2026-10-17)

| Question | Decision |
|---|---|
| Two programmes with the same measures, different wording | One act. What is executed is the measures (engine 25, T136) |
| New communication kinds `demand` and `warning` | Add both to `standing.COMM_KINDS`, with neutral descriptions and small effects; wider diplomacy (D) owns it |
| Ballot repair trigger | Use the reason-based check (engine 26, T155) |
| Vote-mismatch flag in the paper's measures | Drop it unless Jev's re-audit validates it |
| Exit-audit codebook: bare `resign: true` | `ambiguous` (rule A1) |
| Exit-audit codebook: a condition read as an immediate resignation | `formatting_or_parser` (rule F4) |
| Exit-audit sample | Seed 1, 60 non-exit events (all exits included); pre-register it |
| Maintainer in `study.yaml` | `S2Lobby` |
| A seat that cannot start | Fail its grid row at once; no retries |
| Router seats | Excluded from the study |
| The three runs where neighbours borrowed delegate seats | Excluded from study data |
| Unfinished runs | Kept and counted as censored in the survival analysis |
| Survival curves | Plain SVG; no regression model unless time remains |

## Definition of done for the wave

- A and B run in the same scripted month: a state campaign and a foreign campaign both leave records,
  and the democracy index moves.
- A replay of the recorded runs is identical with the new code on the old answers.
- Jev's dry run produces a second label column from the stub server, and the re-audit reports agreement
  before and after T144.
- The six wider-diplomacy pairs have handlers and tests; `demand` and `warning` are accepted and named.
- The package zip builds, and a fresh venv runs the README's one command.
- The statistics script writes an SVG and the secondary measures, and the pre-registration names them.
- Every workstream has its docs page, and `docs/WAVE3_PLAN.md` is updated with what actually shipped.

## Shipped — 2026-10-17

Engine 27 (`WORLD_ENGINE` 27, `AGENT_PROMPT` 24). The six workers built on engine 26 in separate worktrees and
were merged by the reviewer; the prompt fixture was rewritten once, and the full suite is the merge gate.

| # | Branch | Commits | Verified tests | Docs |
|---|---|---|---|---|
| A | `wave3/state-media` | `9bf3603`, `aeb3be3` | 38 new; 54 with the pipeline | `docs/PROPAGANDA_STATE.md` |
| B | `wave3/union-propaganda` | `805bd5e`, `a434ec5` | 27 new; 126 with the neighbours | `docs/PROPAGANDA_UNION.md` |
| C | `wave3/jev` | `616b30d`, `e71f60d`, `c45246e` | 60 with the exit and detector audits | `docs/JEV_ANNOTATOR.md` |
| D | `wave3/wider-diplomacy` | `2679bca` | 27 new; 134 with the diplomacy modules | `docs/WIDER_DIPLOMACY.md` |
| E | `wave3/package` | `9367789`, `6391829`, `732a1b3`, `01889e2`, `2aa97c5`, `9f21525` | 92 (7 + 3 skipped without the vendor) | `docs/SCOPE_TEST.md`, `docs/PACKAGING.md` |
| F | `wave3/statistics` | `eca402e`, `f18d81f` | 35 with the analysis | `docs/STATISTICS.md` |

What shipped, in one line each:

- **A:** `media_campaign` motion, state-media credibility and effects, exposure on the `media` stream, month
  records and deception analytics, the media-capture democracy term. Constants in `docs/PROPAGANDA_STATE.md`.
- **B:** the `propaganda` cabinet act, `foreign_broadcasts` (open/jammed), the counter's credibility and
  democracy-index costs, foreign campaign records. Constants in `docs/PROPAGANDA_UNION.md`.
- **C:** the blind Jev annotator, the codebook decisions (A1/F4, seed 1 and 60 non-exit events), the dry-run
  cost estimate and the D1/D2 re-audit method. Real labels await the user's key (T173).
- **D:** the six widened pairs with handlers, `demand` and `warning` in `COMM_KINDS`, their effects and the
  widened refusal lists. Constants in `docs/WIDER_DIPLOMACY.md`.
- **E:** the SocioVerse2 scope test (7 fallbacks in 48 decisions; 3 quiet replacements), the submission zip
  and clean-machine smoke test, the seat-start rule and the study exclusions. See `docs/SCOPE_TEST.md`,
  `docs/PACKAGING.md`.
- **F:** SVG Kaplan-Meier curves, S1/S2 secondary measures, the vote-mismatch flag demoted to a diagnostic,
  and the pre-registration/paper text. See `docs/STATISTICS.md`.

Open after the wave: T169-T175 (see the backlog) — the jamming cross-write, foreign campaign exposure, the
Dorsania status-talk compliance gap, the grain-wording reader fault, the real Jev/scope-test runs, the
bootstrap coverage and S1/S2 on a real grid.
