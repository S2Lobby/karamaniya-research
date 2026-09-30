# Baseline experiment design — minimum clean baseline (Task E)

Frozen: HEAD `e4c27f7`, agent arch v2, prompt v4, schema `actions.py` strict-mode,
scenario + seed structure + sampling settings identical across conditions.
New runs only; historical runs never reused as baseline data (all 112 predate or
cross the e4c27f7 patch; 0/112 manifests store a commit).

## The confound

Different offices (head/treasury/interior/army/navy) and asymmetric information
(private dossiers, office-only reports, withheld intel) can create different
opening positions even with 5x the same model. A 5-0 vote after bargaining then
cannot by itself be attributed to model character. Three axes must be separated:
(1) role/office effects, (2) information effects, (3) model effects.

## Conditions

CONDITION A — INSTITUTIONAL BASELINE (5x same model, different offices, normal asymmetry)
- Seats: 5x claude-haiku-4-5-20251001 via claude_cli (Haiku 4.5 exists in harness:
  suggested-models `gui.py:47,54`; served before `runs/20260928-204444-seed1/survey.json:220`).
- Offices by formation vote as normal; asymmetric dossiers/reports ON.
- Held constant: engine, scenario, seed set, prompts, temperature/effort, DM quota.
- Changes vs today: homogeneous seats (prior live runs were heterogeneous).
- Primary comparison: opening-position divergence distribution vs final unanimity
  rate within A (the paper's endpoint, Task F).
- Expected confounds: office + information still entangled — that is what B/C undo.

CONDITION B — INFORMATION ABLATION (5x same model, different offices, equalized info)
- Same as A, except every delegate receives the same evidence dossier and all
  office-only reports are shared (implement as config flag; smallest patch: bypass
  dossier sampling + broadcast office reports — proposal only, not implemented here).
- Held constant: everything in A except information access.
- Primary comparison: A vs B divergence (A−B = information-attributable divergence).
- Expected confounds: equalization may itself change bargaining (shared knowledge
  changes what needs saying); report it, do not hide it.

CONDITION C — SEAT SWAP (same model, same world seed, rotated seats/offices)
- Re-run 2-3 A-seeds with seat letters permuted (model instance rotation across
  offices). World seed identical so pressure/weather/dilemmas replay identically
  (`world.py:47-50` rng_for derivation).
- Primary comparison: same model's opening positions across different offices.
- Expected confounds: formation vote may still seat differently; that IS the data.

OPTIONAL D — MIXED MODEL (heterogeneous seats, same setup)
- 5 different models, same scenario/seeds as A. Only after A-C pilot (D without
  A-C baseline cannot separate model from role effects).

## Seeds

- Pilot: 3 seeds per condition (A: 3 runs; B: 3; C: 2 swaps x 2 seeds = 4).
  Total pilot ~= 10 runs x ~6-13 months observed historical cost.
- Paper-quality: 10+ seeds per condition (power analysis not possible yet — no
  variance estimate for TDI exists; collect pilot variances first, then compute N).
- Power data needed: per-run TDI (Task F) variance within A; class-distribution
  variance; position-change rate variance.

## Readout (all conditions)

Per run: run_table row + metrics row (reuse `tools/research_mine.py`), blind/key
episode export (reuse `tools/export_validation_episodes.py`), human labels +
`tools/validation_agreement.py` agreement report.
