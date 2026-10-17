#!/usr/bin/env bash
# One rented Ubuntu GPU box for the study: packages, a venv with vLLM, the repository at one commit, pinned model
# weights, one vLLM server per model on 127.0.0.1, health checks, and a manifest of what ran.
#
#   bash tools/cluster/setup.sh --commit <40-hex> [--models FILE] [--rehearsal] [--yes]
#       checks; with --yes, sets everything up. --rehearsal lets a commit without the study runner serve the rehearsal
#   bash tools/cluster/setup.sh --check-servers                              health of the servers in the manifest
#   bash tools/cluster/setup.sh --stop-servers                               stop them, before teardown
#
# Without --yes it runs the checks and prints the plan: nothing is installed, downloaded or started. Any failed check
# stops the run before anything is installed. Run it from the checkout of the repository at --commit (README, step 2).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(git -C "$HERE" rev-parse --show-toplevel)"
KARA_HOME="${KARA_HOME:-$HOME/karamaniya-cluster}"
PYTHON="${PYTHON:-python3}"
VLLM_VERSION="0.31.0"       # PyPI release of 2026-10-05; the freeze records the version actually used
GPU_UTIL="0.90"             # vLLM --gpu-memory-utilization, its default
MAX_NUM_SEQS="64"           # above the 50 trajectories, so no sequence waits for a slot
COMMIT="" MODELS="$HERE/models.txt" MODE="setup" YES=0 FAILS=0 NEED_GPUS=0 NEED_GB=0 REHEARSAL=0

say()  { printf '%s\n' "$*"; }
ok()   { printf '  ok    %s\n' "$*"; }
warn() { printf '  warn  %s\n' "$*"; }
bad()  { printf '  FAIL  %s\n' "$*"; FAILS=$((FAILS + 1)); }
die()  { printf 'setup: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --commit) COMMIT="${2:-}"; shift 2 ;;
    --models) MODELS="${2:-}"; shift 2 ;;
    --yes) YES=1; shift ;;
    --rehearsal) REHEARSAL=1; shift ;;
    --check-servers) MODE="check"; shift ;;
    --stop-servers) MODE="stop"; shift ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

# ---- the models file --------------------------------------------------------------------------------------------

check_models() {
  local name repo rev gpus port max_len reasoning size extra rows=0 ports=" " names=" " total=0
  if [ ! -f "$MODELS" ]; then bad "models file $MODELS is missing"; return; fi
  while read -r name repo rev gpus port max_len reasoning size extra || [ -n "${name:-}" ]; do
    case "${name:-}" in ""|\#*) continue ;; esac
    rows=$((rows + 1))
    if [ -z "${size:-}" ] || [ -n "${extra:-}" ]; then
      bad "a row of $MODELS has the wrong number of fields (name repo revision gpus port max_len reasoning size_gb)"
      continue
    fi
    [[ "$name" =~ ^[A-Za-z0-9._-]+$ ]] || bad "$name: the name may use letters, digits, dot, underscore and dash"
    case "$repo" in *TBD*) bad "$name: repo is still TBD; pin the study's models first (brief Q1)" ;; esac
    [[ "$repo" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || bad "$name: repo must be owner/name on Hugging Face"
    [[ "$rev" =~ ^[0-9a-f]{40}$ ]] || bad "$name: revision must be the full 40-character commit hash, not '$rev'"
    [[ "$gpus" =~ ^[0-9]+(,[0-9]+)*$ ]] || bad "$name: gpus must be indexes such as 0 or 0,1"
    [[ "$port" =~ ^[0-9]+$ ]] && [ "$port" -ge 1024 ] && [ "$port" -le 65535 ] || bad "$name: port must be 1024-65535"
    [[ "$max_len" =~ ^[0-9]+$ ]] && [ "$max_len" -ge 4096 ] || bad "$name: max_len must be a whole number of at least 4096"
    [[ "$reasoning" =~ ^[a-z0-9_]+$ ]] || bad "$name: reasoning must be a parser name or none"
    [[ "$size" =~ ^[0-9]+$ ]] || bad "$name: size_gb must be a whole number"
    case "$ports" in *" $port "*) bad "$name: port $port is used twice" ;; esac
    case "$names" in *" $name "*) bad "$name: the name is used twice" ;; esac
    ports="$ports$port "; names="$names$name "
    if [[ "$gpus" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
      local top
      top="$(printf '%s\n' "$gpus" | tr ',' '\n' | sort -n | tail -1)"
      if [ "$((top + 1))" -gt "$NEED_GPUS" ]; then NEED_GPUS=$((top + 1)); fi
    fi
    if [[ "$size" =~ ^[0-9]+$ ]]; then total=$((total + size)); fi
  done < "$MODELS"
  NEED_GB=$((total + 25))           # the weights, plus room for the venv, logs and cache
  [ "$rows" -gt 0 ] || bad "$MODELS has no model rows"
  if [ "$FAILS" -eq 0 ] && [ "$rows" -gt 0 ]; then ok "$rows model rows in $(basename "$MODELS"), all pinned, ports and names unique"; fi
}

# Prints the rows as tab-separated lines: name, repo, revision, gpus, port, max_len, reasoning, size_gb.
read_models() {
  local name repo rev gpus port max_len reasoning size extra
  while read -r name repo rev gpus port max_len reasoning size extra || [ -n "${name:-}" ]; do
    case "${name:-}" in ""|\#*) continue ;; esac
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$repo" "$rev" "$gpus" "$port" "$max_len" "$reasoning" "$size"
  done < "$MODELS"
}

# ---- the checks -------------------------------------------------------------------------------------------------

preflight() {
  say "checks"
  if [[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]]; then ok "--commit is a full hash"; else bad "give --commit with the full 40-character hash of the freeze commit"; fi
  local head
  head="$(git -C "$REPO" rev-parse HEAD)"
  if [ "$head" = "$COMMIT" ]; then ok "the checkout is at $COMMIT"; else bad "the checkout is at $head, not $COMMIT: check it out first"; fi
  if [ -z "$(git -C "$REPO" status --porcelain)" ]; then ok "the checkout has no local changes"; else bad "the checkout has local changes: a study runs a clean commit"; fi
  if [ -e "$REPO/.env" ]; then bad "$REPO/.env exists: no .env on the box"; else ok "no .env in the checkout"; fi
  if [ -f "$REPO/tools/study_grid.py" ]; then ok "the commit has the study runner (tools/study_grid.py)"; elif [ "$REHEARSAL" -eq 1 ]; then warn "no study runner in this commit: fine for the rehearsal, not for the study"; else bad "tools/study_grid.py is missing from this commit"; fi
  if ! command -v "$PYTHON" >/dev/null 2>&1; then
    bad "$PYTHON is not installed"
  else
    if "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then ok "Python $("$PYTHON" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))') (the runner needs 3.11 or later)"; else bad "Python 3.11 or later is needed (tomllib)"; fi
    local spec='import importlib.util, sys
spec = importlib.util.spec_from_file_location("engine_config", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
sys.exit(0 if {"office_assignment", "action_order"} <= set(mod.RUN_DEFAULTS) else 1)'
    if "$PYTHON" -c "$spec" "$REPO/karamaniya/config.py" 2>/dev/null; then
      ok "the engine lists office_assignment and action_order in RUN_DEFAULTS"
    elif [ "$REHEARSAL" -eq 1 ]; then
      warn "the engine does not list office_assignment and action_order: fine for the rehearsal, not for the study"
    else
      bad "the engine does not list office_assignment and action_order: use a commit where the office and order branches are merged"
    fi
  fi
  local leaked
  leaked="$(env | cut -d= -f1 | grep -E '(_API_KEY|_TOKEN)$' || true)"
  if [ -z "$leaked" ]; then ok "no API key or token variable is set"; else bad "unset these variables (names only): $(echo $leaked)"; fi
  check_models
  if [ -r /etc/os-release ] && grep -q '^ID=ubuntu' /etc/os-release; then
    ok "Ubuntu: $(. /etc/os-release && echo "$VERSION_ID")"
  elif [ "$YES" -eq 1 ]; then
    bad "this is not Ubuntu (the kit is written for Ubuntu 24.04)"
  else
    warn "not Ubuntu here; the run with --yes needs Ubuntu"
  fi
  if command -v nvidia-smi >/dev/null 2>&1; then
    local have
    have="$(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l | tr -d ' ')"
    if [ "$have" -ge "$NEED_GPUS" ]; then ok "$have GPU(s) visible; the models need $NEED_GPUS"; else bad "$have GPU(s) visible; the models need $NEED_GPUS"; fi
  elif [ "$YES" -eq 1 ]; then
    bad "nvidia-smi is not installed: no NVIDIA driver on this box"
  else
    warn "no nvidia-smi here; the run with --yes needs the GPU driver"
  fi
  local free
  free="$(df -BG --output=avail "$HOME" 2>/dev/null | tail -1 | tr -dc '0-9' || echo 0)"
  if [ -n "$free" ] && [ "$free" -ge "$NEED_GB" ]; then ok "free disk ${free} GB; the weights need about $NEED_GB GB with the rest"; else warn "free disk ${free:-?} GB; about $NEED_GB GB are needed"; fi
  if [ "$FAILS" -gt 0 ]; then
    if [ "$YES" -eq 1 ]; then die "$FAILS check(s) failed; nothing was installed"; fi
    say "$FAILS check(s) failed; fix them, then run again"
    exit 1
  fi
}

print_plan() {
  say ""
  say "plan (with --yes)"
  say "  packages   git curl rsync python3-venv python3-pip ca-certificates"
  say "  venv       $KARA_HOME/venv with vllm==$VLLM_VERSION (pip, from PyPI)"
  say "  checkout   $REPO at $COMMIT"
  say "  weights    under $KARA_HOME/models, pinned by revision, from Hugging Face"
  say "  servers    one vLLM per row, on 127.0.0.1, served names as in $(basename "$MODELS")"
  say "  manifest   $KARA_HOME/cluster-manifest.json (versions, GPUs, revisions, ports)"
  say "  not done   nothing is installed, downloaded or started unless --yes is given"
}

# ---- setup (with --yes) -----------------------------------------------------------------------------------------

install_packages() {
  local root=""
  [ "$(id -u)" -eq 0 ] || root="sudo"
  $root apt-get update -qq
  $root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git curl rsync python3-venv python3-pip ca-certificates
}

make_venv() {
  mkdir -p "$KARA_HOME/logs" "$KARA_HOME/run" "$KARA_HOME/models"
  if [ ! -x "$KARA_HOME/venv/bin/python" ]; then "$PYTHON" -m venv "$KARA_HOME/venv"; fi
  "$KARA_HOME/venv/bin/python" -m pip install -q --upgrade pip
  "$KARA_HOME/venv/bin/python" -m pip install -q "vllm==$VLLM_VERSION"
  "$KARA_HOME/venv/bin/python" -c 'import torch, vllm
assert torch.cuda.is_available(), "torch sees no CUDA device: the driver or the wheel does not match"
print("torch", torch.__version__, "cuda", torch.version.cuda, "vllm", vllm.__version__)'
}

checkout_commit() {
  if [ "$(git -C "$REPO" rev-parse HEAD)" != "$COMMIT" ]; then die "the checkout moved during setup"; fi
  ok "checkout at $COMMIT"
}

DL_PY="$(cat <<'PY'
import sys
from huggingface_hub import snapshot_download
print(snapshot_download(repo_id=sys.argv[1], revision=sys.argv[2], local_dir=sys.argv[3]))
PY
)"

download_models() {
  local name repo rev gpus port max_len reasoning size
  while IFS=$'\t' read -r name repo rev gpus port max_len reasoning size; do
    say "  weights $name: $repo at ${rev:0:12}"
    "$KARA_HOME/venv/bin/python" -c "$DL_PY" "$repo" "$rev" "$KARA_HOME/models/$name" >> "$KARA_HOME/logs/download-$name.log" 2>&1 \
      || die "download of $repo at $rev failed: see $KARA_HOME/logs/download-$name.log"
  done < <(read_models)
}

server_up() {  # name port: the server answers /health and lists its served name
  local models
  curl -fsS -m 5 -o /dev/null "http://127.0.0.1:$2/health" 2>/dev/null || return 1
  models="$(curl -fsS -m 10 "http://127.0.0.1:$2/v1/models" 2>/dev/null || true)"
  [[ "$models" == *"\"id\":\"$1\""* || "$models" == *"\"id\": \"$1\""* ]]
}

start_servers() {
  local name repo rev gpus port max_len reasoning size pid tp
  while IFS=$'\t' read -r name repo rev gpus port max_len reasoning size; do
    pid="$(cat "$KARA_HOME/run/server-$name.pid" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then say "  running $name (pid $pid), not started again"; continue; fi
    if curl -fsS -m 2 -o /dev/null "http://127.0.0.1:$port/health" 2>/dev/null; then
      die "port $port answers already but is not this kit's $name: stop it first (setup.sh --stop-servers)"
    fi
    tp=$(( $(printf '%s' "$gpus" | tr -cd ',' | wc -c) + 1 ))
    local args=(serve "$KARA_HOME/models/$name" --host 127.0.0.1 --port "$port" --served-model-name "$name"
                --max-model-len "$max_len" --gpu-memory-utilization "$GPU_UTIL" --max-num-seqs "$MAX_NUM_SEQS"
                --enable-prefix-caching)
    if [ "$tp" -gt 1 ]; then args+=(--tensor-parallel-size "$tp"); fi
    if [ "$reasoning" != none ]; then args+=(--reasoning-parser "$reasoning"); fi
    say "  start   $name on 127.0.0.1:$port (GPU $gpus)"
    CUDA_VISIBLE_DEVICES="$gpus" HF_HUB_OFFLINE=1 VLLM_NO_USAGE_STATS=1 VLLM_DO_NOT_TRACK=1 \
      nohup "$KARA_HOME/venv/bin/vllm" "${args[@]}" > "$KARA_HOME/logs/server-$name.log" 2>&1 < /dev/null &
    echo $! > "$KARA_HOME/run/server-$name.pid"
  done < <(read_models)
}

wait_servers() {  # up to 30 minutes each; a server that exits, or never answers, stops the run
  local name repo rev gpus port max_len reasoning size pid limit
  while IFS=$'\t' read -r name repo rev gpus port max_len reasoning size; do
    limit=$(( $(date +%s) + 1800 ))
    pid="$(cat "$KARA_HOME/run/server-$name.pid")"
    until server_up "$name" "$port"; do
      if ! kill -0 "$pid" 2>/dev/null; then die "$name exited: see the tail of $KARA_HOME/logs/server-$name.log"; fi
      if [ "$(date +%s)" -gt "$limit" ]; then die "$name did not answer in 30 minutes: see $KARA_HOME/logs/server-$name.log"; fi
      sleep 10
    done
    ok "$name ready on port $port"
  done < <(read_models)
}

write_manifest() {
  local versions gpus
  versions="$("$KARA_HOME/venv/bin/python" -c 'import sys, torch, vllm, huggingface_hub as h
print(vllm.__version__, torch.__version__, torch.version.cuda, h.__version__, sys.version.split()[0])')"
  gpus="$(nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader)"
  read_models | "$KARA_HOME/venv/bin/python" -c "$MANIFEST_PY" "$COMMIT" "$REPO" "$versions" "$gpus" \
    "$KARA_HOME/cluster-manifest.json"
  ok "manifest written: $KARA_HOME/cluster-manifest.json"
}

MANIFEST_PY="$(cat <<'PY'
import json, sys, time
commit, repo, versions, gpus, out = sys.argv[1:6]
vllm_v, torch_v, cuda_v, hub_v, python_v = versions.split()
gpu_rows = []
for row in gpus.splitlines():
    if row.strip():
        index, name, memory, driver = [c.strip() for c in row.split(",")]
        gpu_rows.append({"index": int(index), "name": name, "memory": memory, "driver": driver})
servers = []
for line in sys.stdin:
    name, repo_id, rev, gpu_ids, port, max_len, reasoning, size = line.rstrip("\n").split("\t")
    servers.append({"name": name, "repo": repo_id, "revision": rev, "gpus": gpu_ids, "port": int(port),
                    "max_model_len": int(max_len), "reasoning_parser": reasoning,
                    "weights_gb_planned": int(size), "log": f"logs/server-{name}.log"})
manifest = {"written": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "commit": commit, "repo": repo,
            "python": python_v, "vllm": vllm_v, "torch": torch_v, "cuda": cuda_v, "huggingface_hub": hub_v,
            "server_flags": {"gpu_memory_utilization": 0.90, "max_num_seqs": 64, "enable_prefix_caching": True,
                             "host": "127.0.0.1", "trust_remote_code": False},
            "gpus": gpu_rows, "servers": servers}
with open(out, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)
    f.write("\n")
PY
)"

check_servers() {
  local manifest="$KARA_HOME/cluster-manifest.json" name port down=0
  [ -f "$manifest" ] || die "no manifest at $manifest: run setup.sh --yes first"
  while IFS=$'\t' read -r name port; do
    if server_up "$name" "$port"; then say "  up    $name on port $port"; else say "  DOWN  $name on port $port (log: $KARA_HOME/logs/server-$name.log)"; down=$((down + 1)); fi
  done < <("$KARA_HOME/venv/bin/python" -c 'import json, sys
for s in json.load(open(sys.argv[1]))["servers"]:
    print(s["name"], s["port"], sep="\t")' "$manifest")
  [ "$down" -eq 0 ]
}

stop_servers() {
  local pidfile pid
  for pidfile in "$KARA_HOME"/run/server-*.pid; do
    [ -e "$pidfile" ] || continue
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then kill "$pid"; say "  stopped $(basename "$pidfile" .pid) (pid $pid)"; fi
    rm -f "$pidfile"
  done
}

# ---- main -------------------------------------------------------------------------------------------------------

case "$MODE" in
  check) if check_servers; then exit 0; else exit 1; fi ;;
  stop) stop_servers; exit 0 ;;
esac

preflight
print_plan
if [ "$YES" -ne 1 ]; then say ""; say "checks passed. Run again with --yes to set up the box."; exit 0; fi

say ""
say "setting up"
install_packages
make_venv
checkout_commit
download_models
start_servers
wait_servers
write_manifest
say ""
say "ready: six servers answer on 127.0.0.1. Next: tools/cluster/launch.sh (README, step 5)."
