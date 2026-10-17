# Packaging the submission

Wave 3, workstream E. The builder is [`tools/package.py`](../tools/package.py); this page records what the zip
contains, how it is pinned, what it refuses, and the clean-machine result.

## What the zip is

`python tools/package.py build [--ref REF] [--out ZIP]` writes
`dist/karamaniya-trust-submission-<commit8>.zip`. The zip root is the repository root of the frozen commit, with
this selection:

| Path in the zip | What it is |
|---|---|
| `README.md` | The submission README (`docs/SUBMISSION_README.md`): the one command, the wrap instructions, the grid and the tests. |
| `README-engine.md` | The repository's own `README.md`, kept for reference. |
| `PACKAGE_MANIFEST.json` | The commit, the branch (or detached), the version constants, every file's SHA-256 and the excluded-by-design list. |
| `karamaniya/` | The engine at the frozen commit (`.py` and `gui.html`; the 2.4 MB `council-chamber.png` artwork is excluded). |
| `studies/karamaniya_trust/` | The study: `study.yaml`, the three SocioVerse2 artifacts, the adapter, `run.py`, the seeded population, the committed dry-run reports. No trajectory store or run folder. |
| `tools/` | `study_grid.py`, `study_analysis.py`, `exit_audit.py`, `scope_test.py`, `package.py`, `prompt_freeze.py`, `replay_run.py`, `study_example.toml`. |
| `tests/` | The study grid, analysis, scope-test, packaging and SocioVerse2-wrap tests. |
| `docs/` | `SCOPE_TEST.md`, `PACKAGING.md`, `EXIT_AUDIT_CODEBOOK.md`, `WAVE3_PLAN.md`. |
| `paper/socioverse/PREREGISTRATION.md` | The pre-registration, with the wave-3 exclusion rules (E1, E12, E13). |
| Root files | `LICENSE`, `CITATION.cff`, `requirements.txt`, `council.scripted.toml`, `ENGINE.md`, `CHANGELOG.md`. |

## The pin

The builder never reads the working tree's content. It resolves `--ref` (default `HEAD`) with
`git rev-parse <ref>^{commit}`, reads the tree with `git archive <ref>`, and records the resolved commit in
`PACKAGE_MANIFEST.json`. A dirty checkout therefore cannot leak into the zip, and a later run with `--ref <freeze
tag>` builds exactly that tag. The package also records `WORLD_ENGINE`, `AGENT_PROMPT`, `ERROR_TAXONOMY`,
`PSYCHOLOGY` and `AGENT_ARCHITECTURE` read from the commit's `karamaniya/versions.py`.

## What it refuses

The selection is a whitelist, so nothing outside it can enter. On top of that every selected path is checked:

- no `.env` file (any name starting `.env.`), no `private/`, `runs/`, `.git/`, `wrapped_run/` or `legacy_run/`;
- no `.duckdb`, `.parquet`, `.db`, `.sqlite`, `.log`, `.pem`, `.key`, `.p12` or `.pfx`;
- no key-like value: `sk-...` or `API_KEY=...`/`TOKEN=...`/`SECRET=...`/`PASSWORD=...` with 20 or more
  non-placeholder characters. A finding stops the build and the value is not printed (the file is named instead);
- the finished zip is reopened and checked against its manifest: required files present, every SHA-256 matching,
  no forbidden path. A zip that fails is not left in place.

## The one command

The zip's `README.md` starts with a command that needs only Python 3.12 and the standard library:

```bash
python -m karamaniya simulate council.scripted.toml --runs 1 --months 1 --prefix package-smoke
```

It runs the engine's five scripted seats for one month, calls no model, and writes
`runs/package-smoke-seed1/` (checkpoint, manifest, log, report) and `runs/package-smoke-summary.json`.

## The clean-machine test

`python tools/package.py smoke` (or `all`, which builds first) does exactly what the README says:

1. builds the zip from `HEAD` and verifies its manifest and hashes;
2. extracts it into a fresh temporary folder;
3. creates a new virtual environment with `python -m venv --without-pip` (no site packages, no pip, no PYTHONPATH);
4. reads the first `python -m karamaniya simulate ...` line from the extracted `README.md`;
5. runs it with the venv's interpreter in the extracted root;
6. passes when the exit code is 0 and a run checkpoint exists.

Measured on 2026-10-17 from `C:\Users\litle\Karamaniya\karamaniya-test\wave3-merge` with Python 3.12.10, on the
engine-27 release commit `949854bd`:

```
built dist\karamaniya-trust-submission-949854bd.zip (1,179,412 bytes, 143 files, commit 949854bd, versions
      {'world_engine': 27, 'agent_prompt': 24, 'error_taxonomy': 5, 'psychology': 8, 'agent_architecture': 2})
clean-machine smoke: exit 0, 144 files, 4.5s, checkpoints ['runs\\package-smoke-seed1\\checkpoint.json']
command: <temp>\.venv-smoke\Scripts\python.exe -m karamaniya simulate council.scripted.toml --runs 1 --months 1
         --prefix package-smoke
```

The extracted package's run manifest recorded `world_engine_version: 27`, the five scripted seats A-E, seed 1 and
the outcome `survived`; the package's own checks found no forbidden path, no `.env`, no secret and no SHA-256
mismatch (143 files listed, 144 zip entries including `PACKAGE_MANIFEST.json`). `python -m unittest
tests.test_engine24_package -v` ran 9 tests, OK, including this build and smoke.

The unit tests are `python -m unittest tests.test_engine24_package -v`. The integration class builds from `HEAD`
and runs the smoke; it skips until the package files are committed, because the build reads a commit.

## What is not verified here

- **The SocioVerse2 wrap's dry run in a fresh environment.** `studies/karamaniya_trust/run.py` needs
  `socioverse2==0.2.0` and its dependencies (duckdb, pyarrow, pandas, PyYAML), which are not installed in this
  environment and would need the network to install. The package's README gives the exact commands. The wrap was
  tested in its own environment when it was built (see `studies/karamaniya_trust/README.md`); that install is not
  repeated here.
- **A real study run.** The seats call real models and cost money; the user starts those runs.
- **The GUI artwork.** `karamaniya/council-chamber.png` is left out to keep the zip small; the study and the CLI
  do not use it.

## Rebuilding after the freeze

```bash
python tools/package.py all --ref <freeze-tag> --out dist/karamaniya-trust-submission.zip
```

`--force` is needed only if the output path already exists. The built zip is not committed (`dist/` is in
`.gitignore`); the script builds it.
