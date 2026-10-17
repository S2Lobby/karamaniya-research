# Running the study on rented GPUs

This folder is the kit for running the study grid for one day on rented GPUs (vast.ai). Every model is served locally by
vLLM on the same box: one server per model, each on its own port, each bound to 127.0.0.1. No API key is used, so no
key is ever on the box.

The last section says what is verified and what is not. Read it before you spend money.

## Before you rent: the decisions that are yours

1. **The models (brief Q1).** Five delegate models and one for the neighbours (Veleria and Dorsania). Each must be
   open-weight and ungated, pinned to a commit. Find a commit with
   `curl -s https://huggingface.co/api/models/<owner>/<name> | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])'`
   and put it in `tools/cluster/models.txt`. Until you do, the rows are `TBD` and `setup.sh` refuses them.
2. **The commit (brief Q7).** The box runs the freeze commit, and that commit must contain:
   - the office option (`office_assignment`) and the action-order option (`action_order`) in
     `karamaniya/config.py` `RUN_DEFAULTS`;
   - the study runner, `tools/study_grid.py`;
   - this kit, with the pinned `tools/cluster/models.txt`.
   The base commit 92f2cfa has none of these, so `setup.sh` and the runner both refuse it. Commit the pinned models
   file before the freeze, so that the freeze records it.
3. **The horizon, the workers and the resume policy (Q4, Q5).** `launch.sh` takes `--workers` and `--max-resumes` with
   no defaults, on purpose. A Month-36 election can extend a run by up to four months, so plan for 40.
4. **Thinking or not.** The estimate in step 1 shows both. Thinking traces are much slower.

## Why vLLM, not Ollama

The study needs many long prompts at once: 50 trajectories, 9-25k input tokens a call, one server per model. I compared
the two on what their own sources state, and picked vLLM.

- **Memory.** Ollama's default is one parallel request per model (`OLLAMA_NUM_PARALLEL`, from its config source). Its
  FAQ says the memory it reserves scales with the parallel slots times the context length, so fifty slots at a 40k
  context reserve far more than a card holds. vLLM's README says it manages attention memory with PagedAttention, so
  the room goes to the tokens in use.
- **Batching.** vLLM's README lists continuous batching, chunked prefill and prefix caching. The flags the kit uses
  exist in vLLM 0.31.0: `--max-num-seqs`, `--enable-prefix-caching`, `--reasoning-parser`.
- **Weights.** vLLM loads the Hugging Face weights at a pinned commit, which is the artefact a paper cites. Ollama pulls
  its own builds by tag.
- **The engine.** The existing ollama backend sizes prompts from `num_ctx` (12,288 by default), so long study prompts
  would be trimmed. The openai_compat backend has no such limit and needs no change.
- **The cost of the choice.** A heavier install (CUDA wheels, 16-20 GB of weights per model) and a fast-moving version,
  so the version is pinned in `setup.sh` and recorded in the manifest.

Nothing was measured on either. The rehearsal (step 3) measures vLLM on the box.

## Step 1: estimate the time and cost

    python tools/cluster/estimate.py

It prints the time and cost for each GPU type at 36 months (worst case 40), with and without thinking, and the fewest
GPUs per server that finish within 24 hours. These are model numbers, not measurements. They rest on the efficiency
factors in `SCENARIOS`, which the rehearsal in step 3 replaces.

On the planning numbers (UNVERIFIED until the rehearsal): a no-thinking run of 36 months takes about 7 hours on one
H100 per server, six GPUs in all, roughly $70-100. A thinking run at 8,000 tokens a call takes about 43 hours on one H100
per server, and about 18 hours with four per server (24 GPUs, roughly $760-1,050). Thinking over 40 months does not
fit four GPUs per server. The horizon and the thinking setting decide most of whether the study fits a day. The GPU
type matters too: the H100 is the fastest of the three cards, and it is the only one that fits a thinking run in a day.

## Step 2: rent the instance

- **Type:** on-demand, not interruptible. An interruptible instance can be taken away in the middle of the run.
- **Image:** Ubuntu 24.04 with the NVIDIA driver. `setup.sh --yes` refuses any other system, and the runner needs Python
  3.11 or later.
- **GPUs:** one per server. Six servers means six GPUs. An eight-GPU box leaves two idle, and you pay for them. Rent the
  count the estimate picks.
- **Disk:** at least 200 GB, for the weights (about 16-20 GB each), the venv and the runs.
- **Price:** the estimate uses the user's table of 2026-10-16 as dollars per GPU-hour. Check the offer page: vast.ai may
  show the price for the whole machine. (UNVERIFIED which it is.)
- **Access:** add your own SSH key to the instance. The repository is public, so cloning needs no key.

## Step 3: the one-hour rehearsal on one RTX 4090

Rent one RTX 4090 (about $0.13-0.49 an hour), on-demand. The rehearsal checks the plumbing and measures the speed the
estimate needs. It uses Qwen3-8B (`tools/cluster/models-rehearsal.txt`), which is ungated and Apache-2.0.

1. Clone and check out the commit:

       git clone https://github.com/S2Lobby/karamaniya-research ~/karamaniya
       cd ~/karamaniya && git checkout <commit>

2. Check, then install. The rehearsal uses `--rehearsal`, so a commit without the study runner still runs it:

       bash tools/cluster/setup.sh --commit <commit> --models tools/cluster/models-rehearsal.txt --rehearsal
       bash tools/cluster/setup.sh --commit <commit> --models tools/cluster/models-rehearsal.txt --rehearsal --yes

   The second command installs vLLM 0.31.0, downloads about 16 GB, starts `rehearsal-qwen3-8b` on 127.0.0.1:8001 and
   writes `~/karamaniya-cluster/cluster-manifest.json`. Its progress is in `~/karamaniya-cluster/logs/`.

3. Smoke test one answer. Qwen3 thinks by default. The thinking must come back in the `reasoning` (or
   `reasoning_content`) field, and `content` must hold only the answer:

       curl -s http://127.0.0.1:8001/v1/chat/completions -H 'Content-Type: application/json' \
         -d '{"model":"rehearsal-qwen3-8b","messages":[{"role":"user","content":"Answer with the JSON {\"ok\": true} and nothing else."}],"max_tokens":3000}'

   If `<think>` appears in `content`, the reasoning parser is wrong for the model: stop and fix `models.txt` before the
   study.

4. Measure, one sequence at a time (a 24 GB card holds about one sequence of this length). The bench prints the
   calibration command:

       python3 tools/cluster/bench.py --url http://127.0.0.1:8001/v1 --model rehearsal-qwen3-8b \
         --input-tokens 12000 --output-tokens 1500 --concurrency 1 --requests 4 --gpu rtx-4090 --gpus 1

   Run the command it prints. The output gives `bw_eff` and `mfu`. If they differ from the central scenario (0.6 and
   0.4), change `SCENARIOS["central"]` in `estimate.py` on the study branch, then run the estimate again.

5. Stop the server and destroy the instance: `bash tools/cluster/setup.sh --stop-servers`, then destroy it on vast.ai.

## Step 4: set up the study box

1. Rent the study instance, with the GPU count from step 1, on-demand.
2. Clone and check out the freeze commit, as in step 3.
3. Plan the checks, then install:

       bash tools/cluster/setup.sh --commit <freeze-commit>
       bash tools/cluster/setup.sh --commit <freeze-commit> --yes

   Every check must pass, with no warnings about the runner or the engine options. A commit that lacks them fails here,
   which is the point. The install takes about an hour, mostly the downloads.
4. Confirm the six servers answer: `bash tools/cluster/setup.sh --check-servers`.
5. Write your study file from `tools/study_example.toml` (it is a placeholder, so change every value). The seats and the
   neighbours point at the local servers, like this:

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

   The study has exactly five seats (delegate-a to delegate-e, ports 8001 to 8005). Put the neighbours in `[run]`:

```toml
[study]
seeds = [2101, 2102, 2103, 2104, 2105]      # placeholders: new seeds, fixed before the freeze (brief S8)
rotations = 5
protocols = ["seeded_shuffle", "fixed_precedence"]
months = 36                                 # the horizon (Q4); the worst case adds four

[run]
framing = "simulation"
survey = true
dm_per_turn = 3
foreign_cabinets = true
foreign_cabinet_backend = { provider = "openai_compat", model = "neighbours", base_url = "http://127.0.0.1:8006/v1", label = "neighbours", max_tokens = 16000, max_tokens_cap = 24000, timeout = 3600, max_prompt_chars = 120000 }
```

   Check `max_model_len` in `models.txt` against the seats: the longest prompt (25,000 tokens) plus `max_tokens_cap`
   (24,000) must fit in 49,152. The runner refuses a study that sets `seed`, `months`, `shuffle_seats`,
   `office_assignment` or `action_order` in `[run]`, because the plan sets those.

## Step 5: the dry run, then the real run

Plan and dry-run first. A dry run uses scripted seats and no model calls, at most two months a row:

    bash tools/cluster/launch.sh ~/studies/s1/study.toml ~/studies/s1 --workers 50 --max-resumes 2 --dry-run

It must end with exit code 0 (every row done). Then start the real run. It is detached, so a dropped SSH session does
not stop it:

    bash tools/cluster/launch.sh ~/studies/s1/study.toml ~/studies/s1 --workers 50 --max-resumes 2

Watch it with `bash tools/cluster/launch.sh --status ~/studies/s1`. Its log is `~/studies/s1/launch.log`, and its exit
code is written to `~/studies/s1/run.exit` when it ends. After a pause, run the same command again: the runner resumes
the paused rows from their checkpoints. The numbers `50` and `2` are the study's policy, so choose them deliberately.

## Step 6: keep the data off the box

Nothing on the box is precious until it is on your machine. Make the copies as you go, not at the end.

1. Make a key for this sync only, on your machine: `ssh-keygen -t ed25519 -f ~/kara_sync -N ''`. Add its public key to
   your machine's `authorized_keys`, restricted to the study folder (for example `command="rrsync -wo <folder>"` with
   `no-pty,no-port-forwarding`). Put only the private key on the box.
2. Your machine must accept SSH from the instance. On Windows, enable the OpenSSH server (Optional Features). The
   instance's address changes with each rental, so you may need a relay on a server you control, or a reverse tunnel.
3. Start the sync before the run (or set `SYNC_DEST` and `SYNC_KEY`, and `launch.sh` starts it for you). The key path
   must contain no spaces, because rsync splits the ssh command itself:

       SYNC_DEST=you@your-host:/path/to/studies SYNC_KEY=~/kara_sync bash tools/cluster/sync.sh ~/studies/s1 &

   It copies the folder every 30 minutes and once more when stopped. Use `--interval 300` if you want less to lose.
   Copies never delete, so a file removed on the box stays on your machine. `rsync` must be installed on the box
   (`setup.sh` installs it).

## Step 7: teardown

1. Let the run finish (`~/studies/s1/run.exit` appears), or stop it with `pkill -f 'study_grid.py run'`. Rows still marked
   running are paused on the next run, and their checkpoints survive.
2. Make the final copy and check it: `bash tools/cluster/sync.sh ~/studies/s1 --once --verify`. It must print
   `verified`. Do not destroy the instance until it does.
3. Stop the servers: `bash tools/cluster/setup.sh --stop-servers`.
4. Delete the sync key on the box (`rm ~/kara_sync*`), and remove its public key from your machine's `authorized_keys`.
5. Destroy the instance on vast.ai.
6. Keep `~/studies/s1/cluster-manifest.json` with the study: it records the box.

## Security

- **No key on the box.** The study uses only local models. `setup.sh` refuses to run if an API key or token variable is
  set, or if the checkout has a `.env`. `launch.sh` refuses any seat that is not `openai_compat` on 127.0.0.1, and any
  study that names an API key. Never print or copy a `.env`.
- **No token for downloads.** Every model must be ungated: a Hugging Face token would be a key on the box.
- **Local only.** Each server binds 127.0.0.1. The kit opens no port to the internet. The only way in is the SSH key you
  added to the instance.
- **No remote code.** The kit never passes `--trust-remote-code`. A model that needs it runs code from its repository,
  so it is not allowed here.
- **No telemetry.** vLLM's usage reporting is switched off (`VLLM_NO_USAGE_STATS=1`, `VLLM_DO_NOT_TRACK=1`).
- **The sync key** is for the sync only. Restrict it on your side and delete it at teardown.
- **Check the data before any release.** The traces are synthetic, but check them for secrets before they leave your
  machine (brief S8).

## What the manifest must record for the paper

- **The box:** `cluster-manifest.json` has the GPU names, memory and driver for each GPU, and the versions of Python,
  vLLM, torch, CUDA and huggingface_hub.
- **The models:** each server's repository, revision, GPUs, port, `max_model_len` and reasoning parser. The seat in each
  run's `manifest.json` (`served_models`) matches these.
- **The code:** the freeze commit (`commit` in the manifest), and the study's `plan.json` and `study.toml`.
- **The cost:** the hours each instance ran and what vast.ai charged, plus the rehearsal's hours. The estimate's
  output is the planning figure, and the billed figure replaces it.
- **The calibration:** the rehearsal's measured rates and the `bw_eff` and `mfu` they gave.
- **Local and challenge-API use kept apart.** This kit uses only local servers, so no challenge credit is spent on it
  (brief S9).

## Troubleshooting

- **`setup.sh` refuses.** Each FAIL line names the fix. Nothing is installed when a check fails.
- **A server exits at start.** Read `~/karamaniya-cluster/logs/server-<name>.log`. A common cause is a `max_model_len`
  the KV cache cannot hold: lower it in `models.txt` or use a larger GPU. (UNVERIFIED: the exact message.)
- **`launch.sh` says a lock is left.** Check that nothing runs (`pgrep -fa study_grid`), then delete
  `<out_dir>/.grid.lock`. The runner made it, and only a killed run leaves it behind.
- **Thinking text in `content`.** The reasoning parser is missing or wrong for the model. Fix the `reasoning` column in
  `models.txt`, and check with the smoke test in step 3.
- **Calls time out.** The seat's `timeout` must exceed the per-call latency under load. The estimate's table shows it,
  and flags any call that outlasts the 600-second default.
- **The council trims prompts.** `max_prompt_chars` is too small. Each trim is marked in the prompt and recorded in the
  run log, so count them for the report.
- **The instance died.** Rent a new one at the same commit, and restore the study folder to the same absolute path:
  `status.json` stores the run folders' absolute paths. Then run `launch.sh` again. Rows left running are paused and
  resume from their checkpoints. The model revisions must be the same as before.

## What is verified and what is not (2026-10-17)

**Verified**, by reading the source, the registry or the vendor's page, or by running it here:
- vLLM 0.31.0 on PyPI (uploaded 2026-10-05), Python 3.10 to 3.14.
- In the 0.31.0 source: the `vllm` console script; the options `served_model_name`, `max_model_len`,
  `gpu_memory_utilization`, `max_num_seqs`, `enable_prefix_caching`, `tensor_parallel_size`, `reasoning_parser`,
  `trust_remote_code`, `host` and `port`; the routes `GET /health` and `GET /v1/models`; the reasoning parser named
  `qwen3`; and the switches `VLLM_NO_USAGE_STATS` and `VLLM_DO_NOT_TRACK`.
- Qwen3-8B: revision `b968826d9c46dd6066d109eabc6255188de91218`, not gated, Apache-2.0. Its config has 36 layers, 8 KV
  heads, head dimension 128 and bf16 weights. The 8.19 billion parameters are the Hugging Face count.
- GPU memory and bandwidth: H100 80 GB at 3.35 TB/s and 989 TFLOPS dense BF16 (NVIDIA's page); RTX PRO 6000 at 96 GB
  and 1792 GB/s (NVIDIA's page); RTX 4090 at 24 GB (NVIDIA's page).
- The study runner: `plan` writes 50 rows (run in a scratch copy), and `run --dry-run` refuses this base commit with
  exit code 2, because the commit lacks the two options.
- The commands the kit runs: `vllm serve [model_tag] [options]` (vLLM 0.31.0's serve entrypoint);
  `snapshot_download(repo_id=, revision=, local_dir=)` (huggingface_hub's source); `rsync --mkpath` (rsync's NEWS: added
  in 3.2.3).
- `estimate.py`, `bench.py` and the seat block: 34 tests pass, the seat block is accepted by the engine's config code,
  and it builds an `openai_compat` backend on 127.0.0.1 with no key.
- `setup.sh`, `launch.sh` and `sync.sh`: syntax checked. Their refusal paths were run here, and they created nothing.
  `sync.sh`'s copy and verify flow was run with a stub rsync.

**Not verified** (run on a rented box, or not run at all):
- Everything on a box: the package install, the download, vLLM starting, the health checks, the manifest, and the
  behaviour of `launch.sh` past its checks.
- The throughput model: the efficiency factors `mfu` and `bw_eff` are assumptions, and the rehearsal replaces them.
- The rsync behaviour: the `.env` excludes, and a real copy over ssh. (`--mkpath` is in rsync 3.2.3 and later, see below.)
- The GPU specifications for the RTX PRO 6000 BF16 rate (500 TFLOPS, derived from NVIDIA's FP4 figure) and for the
  RTX 4090 bandwidth (1008 GB/s) and BF16 rate (165 TFLOPS, FP32 accumulate). These are marked UNVERIFIED in
  `estimate.py`.
- Whether vast.ai's price is per GPU or per machine.
- Whether vLLM passes `chat_template_kwargs` through to switch thinking off for Qwen3 (`extra_body`).
- The exact message vLLM gives when the KV cache cannot hold `max_model_len`.
