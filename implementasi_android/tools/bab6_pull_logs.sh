#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: bab6_pull_logs.sh <adb_serial> <destination_dir>" >&2
  exit 2
fi

SERIAL="$1"
DEST="$2"
mkdir -p "$DEST"

for name in events.jsonl events.previous.jsonl bab6_trials.jsonl; do
  if adb -s "$SERIAL" shell run-as id.ac.ub.rupiah test -f "files/$name" >/dev/null 2>&1; then
    adb -s "$SERIAL" exec-out run-as id.ac.ub.rupiah cat "files/$name" > "$DEST/$name"
  fi
done

echo "Log copied to: $DEST"
