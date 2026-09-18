#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <stage7_bundle_dir> <android_project_dir>" >&2
  exit 2
fi
SRC="$(realpath "$1")"
PROJECT="$(realpath "$2")"
DST="$PROJECT/app/src/main/assets/stage7"
[ -f "$SRC/benchmark_spec.json" ] || { echo "Bundle Stage 7 tidak ditemukan: $SRC" >&2; exit 1; }
rm -rf "$DST"
mkdir -p "$DST"
cp -a "$SRC"/. "$DST"/
echo "Stage 7 assets -> $DST"
