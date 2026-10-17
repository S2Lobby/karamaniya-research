#!/usr/bin/env bash
# Run the study grid against the servers that setup.sh started.
#
#   bash tools/cluster/launch.sh <study.toml> <out_dir> --workers N --max-resumes K [--dry-run]
#   bash tools/cluster/launch.sh --status <out_dir>
#
# It plans the grid (tools/study_grid.py plan) if <out_dir> has no plan.json yet, then runs it (tools/study_grid.py
# run). --workers and --max-resumes have no defaults: they are the study's policy (brief Q5). --dry-run runs the grid
# with scripted seats (no servers, no model calls, at most 2 months a row) and writes status-dry-run.json, so run it
# first. A real run checks the commit, the study file and every server, then starts detached, so that a dropped SSH
# session does not stop it, and writes status.json. After a pause, run the same command again: the runner resumes
# the paused rows. Exit codes of the runner: 0 every row done, 1 a row failed, 3 rows paused or pending, 2 refused.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(git -C "$HERE" rev-parse --show-toplevel)"
KARA_HOME="${KARA_HOME:-$HOME/karamaniya-cluster}"
PYTHON="${PYTHON:-python3}"
if [ -x "$KARA_HOME/venv/bin/python" ]; then PY="$KARA_HOME/venv/bin/python"; else PY="$PYTHON"; fi

say()  { printf '%s\n' "$*"; }
ok()   { printf '  ok    %s\n' "$*"; }
bad()  { printf '  FAIL  %s\n' "$*"; FAILS=$((FAILS + 1)); }
die()  { printf 'launch: %s\n' "$*" >&2; exit 1; }

STATUS_PY="$(cat <<'PY'
import collections, json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
counts = collections.Counter(rec["state"] for rec in data.values())
print(sys.argv[1], "::", ", ".join(f"{n} {s}" for s, n in sorted(counts.items())) or "no rows yet")
for name, rec in sorted(data.items()):
    if rec["state"] != "done":
        print(f"  {name:<36} {rec['state']:<8} month {rec['months_done']:>3}  {rec['reason'][:90]}")
PY
)"

status_of() {  # out_dir: the state of every row, from the runner's status file
  local file="$1/status.json"
  [ -f "$file" ] || file="$1/status-dry-run.json"
  [ -f "$file" ] || die "no status file in $1 yet"
  "$PY" -c "$STATUS_PY" "$file"
}

if [ "$#" -lt 1 ]; then die "usage: launch.sh <study.toml> <out_dir> --workers N --max-resumes K [--dry-run]  |  --status <out_dir>"; fi
if [ "$1" = "--status" ]; then status_of "${2:?give the out_dir}"; exit 0; fi

STUDY="${1:?give the study file}"; OUT="${2:?give the out_dir}"; shift 2
WORKERS="" MAX_RESUMES="" DRY=0 FAILS=0
while [ $# -gt 0 ]; do
  case "$1" in
    --workers) WORKERS="${2:?give a number}"; shift 2 ;;
    --max-resumes) MAX_RESUMES="${2:?give a number}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    *) die "unknown argument: $1" ;;
  esac
done
[[ "$WORKERS" =~ ^[1-9][0-9]*$ ]] || die "--workers N is required, N at least 1 (rows at once; the study's policy, brief Q5)"
[[ "$MAX_RESUMES" =~ ^[0-9]+$ ]] || die "--max-resumes K is required (resumes per paused row; the study's policy, brief Q5)"
[ -f "$STUDY" ] || die "no study file at $STUDY"
STUDY="$(cd "$(dirname "$STUDY")" && pwd)/$(basename "$STUDY")"
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac

say "checks"
if [ -z "$(git -C "$REPO" status --porcelain)" ]; then ok "the checkout has no local changes"; else bad "the checkout has local changes: a study runs a clean commit"; fi
if [ -f "$REPO/tools/study_grid.py" ]; then ok "the study runner is in this checkout"; else bad "tools/study_grid.py is missing: this commit has no study runner"; fi
if [ -e "$REPO/.env" ]; then bad "$REPO/.env exists: no .env on the box"; else ok "no .env in the checkout"; fi
providers="$(grep -oE 'provider *= *"[^"]*"' "$STUDY" | sed -E 's/.*"([^"]*)"/\1/' | sort -u || true)"
if [ "$providers" = "openai_compat" ]; then ok "every provider in the study is openai_compat"; else bad "every seat and the neighbours must be openai_compat on the local servers (found: $(echo $providers))"; fi
bases="$(grep -oE 'base_url *= *"[^"]*"' "$STUDY" | sed -E 's/.*"([^"]*)"/\1/' || true)"
remote="$(printf '%s\n' "$bases" | grep -v '^http://127\.0\.0\.1:' | grep -v '^$' || true)"
count="$(printf '%s\n' "$bases" | grep -c '^http' || true)"
if [ -n "$remote" ]; then bad "a base_url is not local: $remote"; elif [ "$count" -eq 0 ]; then bad "the study names no base_url: every seat needs its server's base_url"; else ok "every base_url points at 127.0.0.1 ($count found)"; fi
if grep -q 'api_key' "$STUDY"; then bad "the study names an API key: none may be on the box"; else ok "the study names no API key"; fi

if [ "$DRY" -eq 0 ]; then
  manifest="$KARA_HOME/cluster-manifest.json"
  if [ ! -f "$manifest" ]; then
    bad "no manifest at $manifest: run setup.sh --yes first"
  else
    recorded="$("$PY" -c 'import json, sys; print(json.load(open(sys.argv[1]))["commit"])' "$manifest")"
    head="$(git -C "$REPO" rev-parse HEAD)"
    if [ "$head" = "$recorded" ]; then ok "the checkout is the commit setup recorded ($head)"; else bad "the checkout is $head but setup recorded $recorded"; fi
  fi
  if bash "$HERE/setup.sh" --check-servers >/dev/null 2>&1; then ok "every server answers /health and lists its served name"; else bad "a server is down: run setup.sh --check-servers to see which"; fi
  lock="$OUT/.grid.lock"
else
  lock="$OUT/.grid-dry.lock"
fi
if [ -f "$lock" ]; then
  holder="$(cat "$lock" 2>/dev/null || true)"
  if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then bad "a run of this plan is in progress (pid $holder)"; else bad "$lock is left from a killed run: check that nothing runs, then delete it"; fi
else
  ok "no run of this plan is in progress"
fi
if [ "$FAILS" -gt 0 ]; then die "$FAILS check(s) failed; nothing was started"; fi

mkdir -p "$OUT"
if [ -f "$OUT/plan.json" ]; then
  say "plan exists: $OUT/plan.json (the runner never overwrites a plan; this run resumes it)"
else
  say "planning $OUT"
  (cd "$REPO" && "$PY" tools/study_grid.py plan "$STUDY" "$OUT")
fi

if [ "$DRY" -eq 1 ]; then
  say "dry run: scripted seats, no model calls, at most 2 months a row"
  rc=0
  (cd "$REPO" && "$PY" tools/study_grid.py run "$OUT/plan.json" --workers "$WORKERS" --max-resumes "$MAX_RESUMES" \
     --runs-dir "$OUT/runs" --dry-run) 2>&1 | tee -a "$OUT/launch-dry.log" || rc=$?
  say "dry run exit code $rc (0 every row done, 3 rows paused or pending, 2 refused, 1 a row failed)"
  status_of "$OUT"
  exit "$rc"
fi

rm -f "$OUT/run.exit"
nohup bash -c 'cd "$1" && "$2" tools/study_grid.py run "$3" --workers "$4" --max-resumes "$5" --runs-dir "$6"; echo $? > "$7"' \
  _ "$REPO" "$PY" "$OUT/plan.json" "$WORKERS" "$MAX_RESUMES" "$OUT/runs" "$OUT/run.exit" \
  > "$OUT/launch.log" 2>&1 < /dev/null &
echo $! > "$OUT/launch.pid"
say "started: pid $(cat "$OUT/launch.pid"), log $OUT/launch.log, exit code in $OUT/run.exit when it ends"
if [ -n "${SYNC_DEST:-}" ] && [ -x "$HERE/sync.sh" ]; then
  nohup "$HERE/sync.sh" "$OUT" > "$OUT/sync.log" 2>&1 < /dev/null &
  echo $! > "$OUT/sync.pid"
  say "sync started to $SYNC_DEST every 30 minutes (log $OUT/sync.log)"
else
  say "no SYNC_DEST: nothing copies the folder off the box (README, step 6)"
fi
say "watch: bash tools/cluster/launch.sh --status $OUT"
say "resume after a pause: run the same launch command again"
