#!/usr/bin/env bash
# Copy a study folder off the rented box: every 30 minutes over ssh, and once more when the script is stopped.
#
#   SYNC_DEST=user@host:/path/to/studies SYNC_KEY=/path/to/key bash tools/cluster/sync.sh <out_dir>
#   ... --once               one copy, then exit
#   ... --verify             with --once: after the copy, compare both sides by checksum and fail on any difference
#   ... --interval 1800      seconds between copies (default 1800)
#
# SYNC_DEST may also be a local folder, which is useful for a test. SYNC_PORT defaults to 22. The copies are one-way
# (box to your machine) and never delete: a file removed on the box stays on your machine. Stop the script with
# kill (not kill -9): it then makes the final copy before it exits.
set -euo pipefail

OUT="" ONCE=0 VERIFY=0 INTERVAL=1800
KARA_HOME="${KARA_HOME:-$HOME/karamaniya-cluster}"

die() { printf 'sync: %s\n' "$*" >&2; exit 1; }
stamp() { date +%H:%M:%S; }

while [ $# -gt 0 ]; do
  case "$1" in
    --once) ONCE=1; shift ;;
    --verify) VERIFY=1; shift ;;
    --interval) INTERVAL="${2:?give seconds}"; shift 2 ;;
    -*) die "unknown argument: $1" ;;
    *) OUT="$1"; shift ;;
  esac
done
[ -n "$OUT" ] || die "usage: sync.sh <out_dir> [--once] [--verify] [--interval S]  (with SYNC_DEST and SYNC_KEY set)"
[ -d "$OUT" ] || die "no folder $OUT"
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac
[ -n "${SYNC_DEST:-}" ] || die "set SYNC_DEST, for example user@host:/path/to/studies"
DEST="${SYNC_DEST%/}/$(basename "$OUT")/"

RSYNC=(rsync -a --partial --timeout=120 --mkpath --exclude=.env --exclude='.env.*')
case "$SYNC_DEST" in
  *:*)
    [ -n "${SYNC_KEY:-}" ] && [ -r "$SYNC_KEY" ] || die "set SYNC_KEY to the readable key file for this sync only"
    mkdir -p "$KARA_HOME"
    RSYNC+=(-e "ssh -i $SYNC_KEY -p ${SYNC_PORT:-22} -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$KARA_HOME/known_hosts -o ConnectTimeout=20")
    ;;
esac

copy_once() {
  if "${RSYNC[@]}" "$OUT/" "$DEST"; then
    echo "$(stamp) copied $OUT to $DEST"
  else
    echo "$(stamp) copy failed (exit $?); the next copy will try again" >&2
    return 1
  fi
}

verify_once() {
  local differences
  differences="$("${RSYNC[@]}" --checksum --dry-run --itemize-changes "$OUT/" "$DEST")"
  if [ -n "$differences" ]; then
    printf '%s\n' "$differences" >&2
    die "the copy on $DEST differs from $OUT: do not tear the box down"
  fi
  echo "$(stamp) verified: $DEST matches $OUT by checksum"
}

if [ "$ONCE" -eq 1 ]; then
  copy_once
  if [ "$VERIFY" -eq 1 ]; then verify_once; fi
  exit 0
fi

trap 'copy_once || echo "$(stamp) final copy failed: copy $OUT by hand before teardown" >&2' EXIT
trap 'exit 130' INT TERM
echo "$(stamp) syncing $OUT to $DEST every $INTERVAL seconds"
while true; do
  copy_once || true
  sleep "$INTERVAL" &
  wait $! || true
done
