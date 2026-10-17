# Karamaniya trust study: submission package

Karamaniya is a governance simulator in which five language-model delegates govern a fictional country month by
month under a Charter. This package holds the frozen engine, the SocioVerse2 study wrap (`studies/karamaniya_trust/`,
Path C: a legacy simulator wrapped for SocioVerse2 0.2.0), the grid and analysis tools, the pre-registration, and the
tests for them. The exact engine commit, the version constants and every file's SHA-256 are in
`PACKAGE_MANIFEST.json`.

The package contains no API keys, no `.env` file and no private runs.

## One command (no model, no key, standard library only)

```bash
python -m karamaniya simulate council.scripted.toml --runs 1 --months 1 --prefix package-smoke
```

This runs the engine with its five rule-following scripted seats, writes `runs/package-smoke-seed1/` (checkpoint,
manifest, log, report) and `runs/package-smoke-summary.json`, and calls no model. It needs Python 3.12 or newer and
nothing else. On Windows the interpreter is `python` (or the full path to your Python); on Linux or macOS,
`python3`.

## The SocioVerse2 wrap (needs socioverse2 0.2.0)

The study folder follows SocioVerse2's `studies/<study>/` layout. Install the framework in its own environment
(Python 3.11 or newer) and run the dry run, which needs no model and no key:

```bash
python -m venv .venv-socioverse
.venv-socioverse/Scripts/python.exe -m pip install socioverse2==0.2.0     # Windows
.venv-socioverse/bin/python -m pip install socioverse2==0.2.0             # Linux, macOS
.venv-socioverse/Scripts/python.exe studies/karamaniya_trust/run.py --dry-run
```

The dry run runs `council.scripted.toml` through the wrap for two months with seed 4201, replays the same seed
through the engine's own loop, and prints `parity with the legacy loop: equal`. Outputs go to
`studies/karamaniya_trust/trajectory/dry_run/` and `studies/karamaniya_trust/reports/dry_run.md`.

A real study run uses a council file whose seats name fixed models; it costs money and the study owner starts it:

```bash
.venv-socioverse/Scripts/python.exe studies/karamaniya_trust/run.py COUNCIL.toml --months 36
```

The study needs one fixed model per seat (no router or `auto` seat) and one fixed model for the neighbour
cabinets (`foreign_cabinet_backend`); the grid refuses a study file without them, and the analysis excludes such
runs. See `docs/PACKAGING.md` and `paper/socioverse/PREREGISTRATION.md`.

## The grid

```bash
python tools/study_grid.py plan studies/karamaniya_trust/study.toml study_plan
python tools/study_grid.py run study_plan/plan.json --workers 1
python tools/study_analysis.py --plan study_plan/plan.json --out analysis_out
```

The plan is five models x five rotations x five seeds x two action-order protocols (50 rows). `--dry-run` runs the
whole grid with scripted seats for two months and no model calls:

```bash
python tools/study_grid.py run study_plan/plan.json --dry-run
```

`python tools/scope_test.py` audits SocioVerse2's own reference study, `opinion_diffusion`, with no model or key; see
`docs/SCOPE_TEST.md`. The exit-event audit and codebook are `tools/exit_audit.py` and
`docs/EXIT_AUDIT_CODEBOOK.md`; the analysis is `tools/study_analysis.py`.

## Tests

```bash
python -m unittest tests.test_engine24_study_grid tests.test_engine24_study_analysis
python -m unittest tests.test_study_karamaniya_trust          # the wrap tests; 7 skip without socioverse2
```

## Privacy and data

The package is built from the frozen commit by `tools/package.py`, which refuses `.env` files, keys, private
folders, run folders and binary trajectory stores. The only trajectory files included are the small scripted
dry-run JSON files of the study. No model was called to build this package.

## License

The source code (`karamaniya/`, `tests/`, `tools/` and the example council files) is released under the Apache
License 2.0 (`LICENSE`). The paper, figures and written research materials are not covered by that license.
