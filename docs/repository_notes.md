# Repository Notes

This repository contains the public-facing research materials for **Karamaniya**, a persistent multi-agent AI evaluation environment.

The project is currently in a **pilot / instrument-validation stage**.

The main purpose of this repository is to provide a clean public record of:

- the preliminary research paper,
- the executive brief,
- core figures,
- methodology notes,
- selected analysis outputs,
- and the simulator's source code.

## Current scope

The existing pilot consists of local small-model experiments used to validate the evaluation harness and identify measurement confounds before running a larger frontier-model study.

The pilot is not presented as definitive evidence of fixed model personalities or governance quality.

Instead, it is used to:

- test whether the environment can discriminate between long-horizon behaviors,
- identify model-by-role effects,
- inspect resignation and removal mechanics,
- evaluate structured-action reliability,
- examine whether final consensus hides earlier disagreement,
- and expose artifacts caused by the simulation or action interface.

## Data release status

The repository currently prioritizes curated, interpretable research materials rather than a full raw-data dump.

Some raw trajectories, logs, and intermediate analysis artifacts are not yet public while:

- trace formatting is being cleaned,
- behavioral labels are being validated,
- instrumentation changes are being frozen,
- and the next experimental version is being prepared.

A more complete reproducibility package is planned after the evaluation harness is frozen.

The simulator itself is public: the code in this repository is engine version 5, tagged `engine-5`, under
the Apache License 2.0 (see [ENGINE.md](../ENGINE.md) to run it). Raw trajectories, logs and intermediate
analysis artifacts are still not part of the repository.

## Important limitations

Several limitations identified during the pilot are documented openly in the paper.

These include:

- placeholder-like or low-substance resignation events,
- role-dependent removal mechanisms,
- excessive world-state persistence when offices become vacant,
- structured-action validation failures,
- and classifier outputs that require human validation.

These limitations are treated as part of the measurement problem rather than hidden from the analysis.

## Next phase

The next phase is a prospective frontier-model study using a corrected and frozen engine version.

Planned controls include:

- independent seeds,
- systematic seat rotations,
- same-model governments,
- model-by-role comparisons,
- action-order randomization,
- bridge replays across engine versions,
- human-validated trajectory labels,
- and preregistered time-to-event analysis.

## Project framing

Karamaniya is intended as **measurement science for persistent multi-agent AI systems**.

The fictional political environment is an experimental substrate for studying long-horizon agent behavior, coordination, role effects, persistence, disagreement, and evaluation reliability.

It is **not intended to predict real-world political behavior**.

## Contact

**Muhammadjon Ahmadjonov**  
Independent Researcher, Uzbekistan
