#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <stage6_run_dir> <android_project_dir>" >&2
  exit 2
fi
RUN="$(realpath "$1")"
PROJECT="$(realpath "$2")"
SRC="$RUN/android_verification_bundle/stage6"
DST="$PROJECT/app/src/main/assets/stage6"
[ -f "$SRC/android_verification_spec.json" ] || { echo "Bundle Stage 6 tidak ditemukan: $SRC" >&2; exit 1; }
rm -rf "$DST"
mkdir -p "$DST"
cp -a "$SRC"/. "$DST"/
echo "Stage 6 assets -> $DST"
