# Running the study on rented GPUs

This folder is the kit for running the study grid for one day on rented GPUs (vast.ai). Every model is served locally
by vLLM on the same box, one server per model on its own port, and bound to 127.0.0.1. No API key is used.

Status: draft. The steps are being completed; see the report for what is verified and what is not.

## What commit the box must run

The study runner (`tools/study_grid.py`) refuses a study whose `[run]` sets `office_assignment` or `action_order`
unless the engine lists those keys in `karamaniya/config.py` RUN_DEFAULTS. The base commit 92f2cfa does not list them,
so `setup.sh` refuses that commit. Use the freeze commit, once the fixed-offices branch (`office_assignment`), the
action-order branch (`action_order`) and the study runner are all merged into `main`.

## The seat block

Each of the five delegate seats, and the neighbours' model, is an `openai_compat` seat pointed at its local server.
This block is checked by `tests/test_engine24_cluster_estimate.py`, so it is kept to what the engine accepts today.

```toml
[[seat]]
label = "delegate-a"
provider = "openai_compat"
model = "delegate-a"                  # must equal the server's --served-model-name (the name column in models.txt)
base_url = "http://127.0.0.1:8001/v1"
max_tokens = 16000                    # a thinking model spends part of this on thinking the reply never shows
max_tokens_cap = 24000                # a cut-off answer is retried with a bigger budget, up to this
timeout = 3600                        # calls queue behind the others on the server; the default 600 s is too short
max_prompt_chars = 120000             # without it the council trims the user prompt to 60,000 characters
```
