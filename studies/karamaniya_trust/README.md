# Karamaniya trust study (SocioVerse2, Path C)

This folder is the study package for the SocioVerse Challenge entry, in the `studies/<study>/` layout that SocioVerse2
expects for a wrapped legacy simulator. Karamaniya, a governance simulator in which five LLM delegates govern a fictional
country month by month, is used unchanged. The wrap is the `adapter/` folder, and `run.py` is the one command.

The study question, the hypothesis and the design are in `study.yaml` and `grounding/grounding.json`.

## What is where

| Path | What it is |
|---|---|
| `study.yaml` | The study card: research question, hypothesis, metrics, and the discovery fields (`legacy_simulator: karamaniya`). |
| `grounding/grounding.json` | The assumptions and the legacy code references. The country is fictional (`method_notes: stylized`). |
| `environment/environment.json` | The two layers the wrap exposes: the country state and each delegate's office brief. |
| `population/` | The five delegates A-E. `population.json` and `roster.jsonl` are written by `run.py --materialize` for the study seed. |
| `simulation/simulation.json` | The horizon (36 months), the seed, and the names of the wrap's classes. |
| `adapter/engine_seam.py` | `LegacySeam`: the only code that drives Karamaniya. Standard library only. |
| `adapter/providers.py` | The four SocioVerse2 interfaces (EnvironmentProvider, PopulationProvider, DecisionModel, MetricCollector), implemented through the seam. |
| `run.py` | The one command: `--dry-run`, a real run from a council file, and `--materialize`. |
| `trajectory/` | Run output. Only the small JSON files of the dry run are committed. |
| `reports/` | Human-readable reports. `dry_run.md` is committed. |

The Karamaniya engine is the repository's `karamaniya/` folder. This study changes no file there.

## How a step maps onto the engine

- **Population** (`population.build`): opens the legacy run. The seats take the letters A-E, the questionnaire is answered, and the
  founding diagnoses are made.
- **Environment** (`env.reset`): forms the government with the Month-0 vote. This is the initial state.
- **Each step** (`decide_batch`): runs one whole council month (openings, responses, votes, the world step and the foreign
  cabinets). Each delegate gets one action for the month: `council_month`, or `exit` if it left office in that month. A
  delegate already out of office gets none.
- **Horizon**: the simulator runs `months + 4` steps. The legacy run can add up to four months after an election, when a
  government owes a handover. A step past the legacy end runs no month and records `month_ran = 0`.

The observation and the metrics only read the engine's records. The month's own prompts are built by the engine, as it
builds them in a normal run.

## Setup

There are two Python environments.

1. **The engine.** Scripted seats need only the standard library. Seats that call the Claude API need `anthropic>=1.8`
   (see `requirements.txt` in the repository).
2. **The wrap.** It needs socioverse2 0.2.0 in its own environment. Do not install it into the engine's environment.

```
python -m venv .venv-socioverse
.venv-socioverse\Scripts\python.exe -m pip install socioverse2==0.2.0      # Windows
.venv-socioverse/bin/python -m pip install socioverse2==0.2.0              # Linux, macOS
```

socioverse2 needs Python 3.11 or newer. The checks were run with Python 3.12.10 on Windows 11, with socioverse2 0.2.0. Other
platforms have not been checked.

The engine is found in this repository by default. To use another Karamaniya checkout, set `KARAMANIYA_ROOT` in the process
environment. The study does not read any `.env` file.

## The dry run (no model, no key)

```
.venv-socioverse\Scripts\python.exe studies\karamaniya_trust\run.py --dry-run
```

This runs `council.scripted.toml` through the wrap for two months, with seed 4201. The scripted seats are rule-following
stand-ins; they call no model. The same seed is then replayed through the engine's own loop (`karamaniya.runner.new_run`),
and the two runs are compared month by month and in their final world. The last line should read
`parity with the legacy loop: equal`. The exit code is 0 when they are equal and 1 when they are not.

Outputs:

- `trajectory/dry_run/metrics_history.json`, `summary.json` and `parity_check.json` (committed);
- `trajectory/dry_run/study.duckdb`, and parquet copies of the panel and the metrics (git-ignored);
- `trajectory/dry_run/wrapped_run/` and `trajectory/dry_run/legacy_run/`, the engine's own run folders (git-ignored);
- `reports/dry_run.md` (committed).

The full default horizon, 36 months, is `run.py --dry-run --months 36` and takes about a minute. On the check run for this
study, the engine ran 37 months, because the government owed a handover after the Month-36 election. The wrap matched all 37
months and the final world. Under scripted seats the government kept power by force in Month 37. That is a result of the
stand-in rules, not a finding about models.

## A real run (costs money; the study owner starts it)

```
.venv-socioverse\Scripts\python.exe studies\karamaniya_trust\run.py COUNCIL.toml --months 36
```

- The seats in `COUNCIL.toml` call real models. Before the run, each seat gets one small call, as `python -m karamaniya run`
  does. `--no-check` skips that call.
- The council file's `max_cost_usd` caps the spend. 0 means no cap.
- Output: `trajectory/run/` and `reports/run.md`. The engine's run folder is `trajectory/run/wrapped_run/`.
- If a seat hits a usage limit, the run pauses at the last finished month. The engine's own resume should continue the same
  run folder: `python -m karamaniya resume trajectory/run/wrapped_run`. The wrap does not resume a paused run itself.
  UNVERIFIED: neither the pause nor that resume has been run on a wrap run, because scripted seats never pause.
- The foreign cabinets (Veleria and Dorsania) are played by the seats that hold letters A and B, unless the council file
  sets `foreign_cabinet_backend` (one model for both cabinets) or `foreign_cabinet_seats`. The study design needs one fixed
  model for both cabinets. Which model is still open.

## What a dry run reproduces, and what needs real models

Reproduced by a dry run (checked on Windows 11, Python 3.12.10, socioverse2 0.2.0):

- the seat mapping, and the offices after the Month-0 vote, for seed 4201;
- every month's state (approval, inflation, unrest, food ratio, army, members in office, removals) and the final world, equal
  to the engine's own loop;
- the committed files, byte for byte, on a second run.

Needs real models (not reproduced by a dry run):

- every result that depends on what a model says: openings, votes, motions, refusals, resignations and the foreign cabinets'
  moves. So the exit counts, the invalid-action rate and the execution-mismatch rate of a real run will differ from the dry
  run's. Scripted seats follow fixed rules, so their numbers show that the machinery works, not how delegates behave;
- the calls, tokens, runtime and cost of a real run.

## Tests

```
.venv\Scripts\python.exe -m unittest tests.test_study_karamaniya_trust -v          # the engine's Python: 6 run, 7 skip
.venv-socioverse\Scripts\python.exe -m unittest tests.test_study_karamaniya_trust -v   # socioverse2: 13 run
```

The first command checks the seam against the engine's loop, month by month and in the final world. It skips the seven
socioverse2 checks, which need the package. The second runs all thirteen: the wrap month by month and in its final world,
the panel and metric tables, the validation of the artifacts against the socioverse2 schemas, the one-command dry run, and
both horizons. It takes about two minutes.

## Known limits

- The 50-run grid (rotations, seeds and two action orders) is not built here. `run_cell()` in `run.py` is the hook the grid
  runner will call, once per cell.
- Office rotation and the second action-order protocol are not in the engine yet.
- The exit-event trace audit and the seeded replay are not in this package.
- The SocioVerse2 documentation pages named for this study could not be fetched during the build. The structure follows the
  v0.2.0 source and its developer guide (`CLAUDE-dev.md`).
- The paper cited in the proposal (arXiv:2609.24911) has not been checked.
- Seed 4201 is the study's default seed and the dry-run seed. The five environment seeds for the study are not fixed yet.
